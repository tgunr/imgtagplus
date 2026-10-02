"""Main orchestrator for ImgTagPlus.

Ties together scanning, tagging, metadata writing, monitoring, and
error handling into a single ``run()`` function called by the CLI.
"""

from __future__ import annotations

import argparse
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from imgtagplus import logger as log_setup
from imgtagplus.converter import (
    DEFAULT_RASTER_PX,
    VECTOR_EXTENSIONS,
    ConversionError,
    UnsupportedVectorError,
    VectorFormatError,
    rasterize_vector,
)
from imgtagplus.metadata import (
    compute_file_hash,
    read_tag_sidecar,
    write_tag_sidecar,
    write_xmp,
)
from imgtagplus.monitor import Monitor
from imgtagplus.profiler import AVAILABLE_MODELS
from imgtagplus.scanner import scan
from imgtagplus.tags import (
    TAGS,
    TaxonomyError,
    apply_feedback_at_scan,
    validate_axis_key,
)

log = logging.getLogger(__name__)


def _refresh_scan_feedback(image_path: Path) -> None:
    """Honor persisted human feedback for *image_path* at scan time.

    A rescan must not resurrect an axis the human deleted, nor clobber a
    confirmed/overridden axis with a fresh analyzer guess.  We re-evaluate the
    stored ``derived_tags`` through the feedback artifact and persist each
    surviving axis as an unvetted user tag, which loses to genuine human input
    (``confirmed_by: user`` / overrides) but outranks a fresh derived guess.

    Failures here never abort a scan — the XMP sidecar is already written and
    is the primary artifact.
    """
    try:
        sidecar = read_tag_sidecar(image_path)
    except Exception:  # pragma: no cover - defensive, read path already guards
        return

    feedback = sidecar.get("feedback_for_future_scans")
    if not feedback:
        return

    derived = sidecar.get("derived_tags") or {}
    if not derived:
        return

    resolved = apply_feedback_at_scan(feedback, derived)
    user_tags = dict(sidecar.get("user_tags") or {})

    for axis, record in resolved.items():
        try:
            canonical_axis = validate_axis_key(axis)
        except TaxonomyError:
            continue
        user_tags[canonical_axis] = {
            "key": record.get("key"),
            "label": record.get("label"),
            "confirmed_by": "unvetted",
        }

    try:
        write_tag_sidecar(
            image_path,
            user_tags=user_tags,
            file_hash=sidecar.get("file_hash") or compute_file_hash(image_path),
        )
    except Exception as exc:  # pragma: no cover - never break a scan
        log.warning("Could not persist feedback for %s: %s", image_path, exc)


def _tag_with(tagger, image_path: Path, args: argparse.Namespace) -> list[tuple[str, float]]:
    """Run the active tagger against *image_path* with the run's settings.

    Different taggers need different args: CLIP takes tags/threshold,
    Florence-2 VLMs ignore them.
    """
    if getattr(tagger, "precompute_tag_embeddings", None):
        return tagger.tag_image(
            image_path,
            tags=TAGS,
            threshold=args.threshold,
            max_tags=args.max_tags,
        )
    return tagger.tag_image(
        image_path,
        max_tags=args.max_tags,
    )


def _format_runtime(seconds: float) -> str:
    """Format an elapsed runtime as HH:MM:SS."""
    total_seconds = max(0, int(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _prompt_on_error(
    message: str,
    timeout: int,
    silent: bool,
    continue_on_error: bool,
) -> bool:
    """Ask the user whether to continue after an error.

    Returns ``True`` if processing should continue, ``False`` to abort.
    In silent mode or when *continue_on_error* is set, returns
    immediately without prompting.
    """
    if continue_on_error:
        log.info("Continuing after error (--continue-on-error).")
        return True

    if silent:
        log.warning("Aborting in silent mode due to error.")
        return False

    # Interactive prompt with timeout.
    prompt = f"\n{message}\nContinue? [Y/n] (auto-continue in {timeout}s): "
    try:
        print(prompt, end="", flush=True)
        result: list[str] = []
        event = threading.Event()

        def _read_input() -> None:
            try:
                result.append(input())
            except EOFError:
                result.append("")
            event.set()

        t = threading.Thread(target=_read_input, daemon=True)
        t.start()
        event.wait(timeout=timeout)

        if not event.is_set():
            # Timeout expired — auto-continue.
            print("\n(timeout — continuing)")
            return True

        answer = result[0].strip().lower()
        if answer in ("n", "no"):
            return False
        return True
    except Exception:
        return True

def run(args: argparse.Namespace, progress_callback: Optional[Callable[[int, int, str], None]] = None) -> int:
    """Execute the full tagging pipeline.  Returns an exit code."""

    # ── Logging setup ─────────────────────────────────────────────────────
    log_path = log_setup.setup_logging(
        log_file=args.log_file,
        silent=args.silent,
    )
    run_started_at = datetime.now().astimezone()
    run_started_monotonic = time.monotonic()

    # Resolve the model ID. It might be an internal key or a full Hugging Face ID.
    model_id = getattr(args, "model_id", "clip")
    model_info = AVAILABLE_MODELS.get(model_id)
    if not model_info:
        # Fallback check if they passed the raw HF ID (e.g., from old frontend state)
        for key, info in AVAILABLE_MODELS.items():
            if info.get("id") == model_id:
                model_info = info
                model_id = key
                break
    
    # Default to clip info if still not found
    if not model_info:
        log.warning("Unknown model '%s', falling back to 'clip'.", model_id)
        model_info = AVAILABLE_MODELS["clip"]
        model_id = "clip"
    
    log.info("Model       : %s (%s)", model_id, model_info["id"])
    log.info("Recursive   : %s", args.recursive)
    if model_info["type"] == "tagger":
        log.info("Threshold   : %s", args.threshold)
    log.info("Max tags    : %s", args.max_tags)
    
    log.info("Silent      : %s", args.silent)
    log.info("Continue err: %s", args.continue_on_error)
    log.info("Log file    : %s", log_path)
    log.info("Run started : %s", run_started_at.strftime("%Y-%m-%d %H:%M:%S"))

    # ── Discover images ───────────────────────────────────────────────────
    try:
        images = scan(args.input, recursive=args.recursive)
    except (FileNotFoundError, ValueError) as exc:
        log.error("Scan failed: %s", exc)
        return 1

    if not images:
        log.warning("No images found at %s", args.input)
        if progress_callback:
            try:
                progress_callback(0, 0, "")
            except Exception:
                pass
        return 0

    log.info("Images to process: %d", len(images))

    # ── Start resource monitor ────────────────────────────────────────────
    monitor = Monitor()
    monitor.start()

    # ── Load model ────────────────────────────────────────────────────────
    try:
        if model_info["type"] == "tagger":
            from imgtagplus.tagger import Tagger
            
            # The original CLIP implementation caches on first run, but it doesn't take 'model_id' arg.
            tagger = Tagger(model_dir=args.model_dir, accelerator=getattr(args, "accelerator", None))
            tagger.precompute_tag_embeddings(TAGS)
        else:
            from imgtagplus.vlm import FlorenceTagger
            
            # Use the resolved Hugging Face ID instead of the internal key
            hf_model_id = model_info["id"]
            log.info("Resolved %s to Hugging Face ID: %s", model_id, hf_model_id)
            tagger = FlorenceTagger(
                model_id=hf_model_id,
                model_dir=args.model_dir,
                accelerator=getattr(args, "accelerator", None),
            )

    except Exception as exc:
        log.error("Failed to load AI model: %s", exc, exc_info=True)
        monitor.stop()
        return 1

    # ── Process images ────────────────────────────────────────────────────
    xmp_dirs: set[Path] = set()
    success_count = 0
    error_count = 0

    for idx, img_path in enumerate(images, 1):
        log.info("[%d/%d] Tagging: %s", idx, len(images), img_path)
        
        if progress_callback:
            try:
                progress_callback(idx, len(images), str(img_path))
            except Exception as cb_exc:
                log.warning("Progress callback failed: %s", cb_exc)

        try:
            if img_path.suffix.lower() in VECTOR_EXTENSIONS:
                # Vector drawing: validate + rasterize into an isolated
                # temporary PNG, tag that, then write the sidecar against
                # the ORIGINAL vector file.
                if getattr(args, "no_vector", False):
                    log.info("  -> skipped (--no-vector): %s", img_path.name)
                    continue
                try:
                    with rasterize_vector(
                        img_path,
                        target_px=getattr(args, "vector_px", DEFAULT_RASTER_PX),
                    ) as raster:
                        results = _tag_with(tagger, raster.path, args)
                except (VectorFormatError, UnsupportedVectorError) as exc:
                    error_count += 1
                    log.error("  Unsupported vector file %s: %s", img_path, exc)
                    should_continue = _prompt_on_error(
                        message=f"Unsupported vector file {img_path.name}: {exc}",
                        timeout=args.input_timeout,
                        silent=args.silent,
                        continue_on_error=args.continue_on_error,
                    )
                    if not should_continue:
                        log.info("Aborting at user request.")
                        break
                    continue
            else:
                results = _tag_with(tagger, img_path, args)

            tag_names = [t for t, _ in results]
            log.info(
                "  -> %d tag(s): %s",
                len(tag_names),
                ", ".join(tag_names[:10])
                + (" …" if len(tag_names) > 10 else ""),
            )
            log.debug("  Full results: %s", results)

            xmp_path = write_xmp(
                img_path,
                tag_names,
                output_dir=args.output_dir,
                overwrite=getattr(args, "overwrite", False),
            )
            xmp_dirs.add(xmp_path.parent)
            _refresh_scan_feedback(img_path)
            success_count += 1

        except Exception as exc:
            error_count += 1
            log.error("  ERROR processing %s: %s", img_path, exc, exc_info=True)

            should_continue = _prompt_on_error(
                message=f"Error processing {img_path.name}: {exc}",
                timeout=args.input_timeout,
                silent=args.silent,
                continue_on_error=args.continue_on_error,
            )
            if not should_continue:
                log.info("Aborting at user request.")
                break

    # ── Stop monitor & collect stats ──────────────────────────────────────
    stats = monitor.stop()
    total_runtime = _format_runtime(time.monotonic() - run_started_monotonic)
    log.info("Runtime     : %s", total_runtime)

    # ── Summary ───────────────────────────────────────────────────────────
    separator = "=" * 60
    summary_lines = [
        "",
        separator,
        "  ImgTagPlus — Run Summary",
        separator,
        "",
        f"Images processed : {success_count} / {len(images)}",
        f"Errors           : {error_count}",
        f"Runtime          : {total_runtime}",
        "",
        stats.summary(),
        "",
    ]

    if xmp_dirs:
        summary_lines.append("XMP output directories:")
        for d in sorted(xmp_dirs):
            summary_lines.append(f"  {d}")
    else:
        summary_lines.append("No XMP files written.")

    summary_lines += [
        "",
        f"Log file: {log_path}",
        separator,
    ]

    summary = "\n".join(summary_lines)
    log.debug(summary)
    # Print to stdout directly so it's always visible (even in silent mode).
    print(summary)

    return 0 if error_count == 0 else 2
