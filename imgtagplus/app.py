"""Main orchestrator for ImgTagPlus.

Ties together scanning, tagging, metadata writing, monitoring, and
error handling into a single ``run()`` function called by the CLI.
"""

from __future__ import annotations

import argparse
import json
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
    TAG_SIDECAR_SUFFIX,
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
    collect_similar_feedback,
    derive_tags_from_clip_results,
    make_override,
    validate_axis_key,
)

log = logging.getLogger(__name__)


def _scan_roots(images, output_dir: Path | None) -> set[Path]:
    """Directories a scan reads feedback from: every image dir + the output dir."""
    roots = {Path(p).parent for p in images}
    if output_dir is not None:
        roots.add(Path(output_dir))
    return roots


def _build_feedback_index(roots) -> list[dict]:
    """Collect every persisted ``feedback_for_future_scans`` artifact under *roots*.

    ``build_feedback_artifact`` stores only a hash-prefix pattern, never the full
    hash, so the only way a scan can honor feedback recorded against a *different*
    but similar file is to read the artifacts of the files it knows about.  One
    flat list of artifacts is enough — :func:`collect_similar_feedback` buckets
    them by hash prefix when a candidate is scored.
    """
    artifacts: list[dict] = []
    seen: set[Path] = set()
    for root in roots:
        try:
            sidecars = sorted(Path(root).glob(f"*{TAG_SIDECAR_SUFFIX}"))
        except OSError:  # pragma: no cover - unreadable dir
            continue
        for sidecar in sidecars:
            if sidecar in seen:
                continue
            seen.add(sidecar)
            try:
                data = json.loads(sidecar.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict):
                feedback = data.get("feedback_for_future_scans")
                if isinstance(feedback, dict) and feedback:
                    artifacts.append(feedback)
    return artifacts


def _persist_scan_taxonomy(
    image_path: Path,
    results,
    *,
    feedback_index: list[dict] | None = None,
    output_dir: Path | None = None,
) -> None:
    """Persist this scan's derived taxonomy tags into the JSON sidecar.

    Before this existed the scan loop wrote XMP and then re-read the sidecar for
    feedback, but nothing ever wrote ``derived_tags`` — so on a fresh scan the
    sidecar stayed empty and the entire feedback path was dead.  This buckets the
    CLIP results into taxonomy axes (:func:`derive_tags_from_clip_results`) and
    stores them, merging human input that already exists in the file: pure
    ``derived`` records are replaced by a fresh scan, while axes the human
    confirmed, overrode, or deleted are left untouched for
    :func:`_refresh_scan_feedback` to re-assert afterwards.
    """
    try:
        file_hash = compute_file_hash(image_path)
        sidecar = read_tag_sidecar(image_path, output_dir=output_dir)
        derived = derive_tags_from_clip_results(results)

        # Human input outranks the analyzer: drop any fresh guess on an axis the
        # user already confirmed, overrode, or deleted so the persisted set can
        # never contradict the stored feedback artifact.
        human_axes = {
            *(sidecar.get("user_tags") or {}),
            *(sidecar.get("user_overrides") or {}),
            *(sidecar.get("user_deletions") or ()),
        }
        for axis in human_axes:
            derived.pop(axis, None)

        # Feedback recorded against a *similar* file (shared hash-prefix bucket),
        # not just this exact file, so a human's answer to "what is this part"
        # carries over to a re-export of it.
        feedback = collect_similar_feedback(feedback_index or (), file_hash)
        if not feedback:
            feedback = sidecar.get("feedback_for_future_scans") or {}
        if feedback:
            # ``apply_feedback_at_scan`` answers "what is the effective tag for
            # each axis".  The ``derived_tags`` slot is only for analyzer
            # output, so keep the original record where the answer came from
            # ``derived`` and drop it everywhere a human won — the stored
            # feedback artifact is what re-asserts those axes on the next read.
            effective = apply_feedback_at_scan(feedback, derived)
            for axis, record in effective.items():
                if not isinstance(record, dict) or record.get("source") == "derived":
                    continue
                derived.pop(axis, None)

        write_tag_sidecar(
            image_path,
            derived_tags=derived,
            file_hash=file_hash,
            output_dir=output_dir,
        )
    except Exception as exc:  # pragma: no cover - never break a scan
        log.warning("Could not persist taxonomy tags for %s: %s", image_path, exc)


def _refresh_scan_feedback(image_path: Path) -> None:
    """Honor persisted human feedback for *image_path* at scan time.

    A rescan must not resurrect an axis the human deleted, nor clobber a
    confirmed/overridden axis with a fresh analyzer guess.  We re-evaluate the
    stored ``derived_tags`` through the feedback artifact and persist ONLY the
    axes the artifact asserts as human input:

      * ``user_confirmed`` → re-asserted as ``confirmed_by: "user"`` user tag
      * ``user_override``  → re-asserted as a user override record

    Pure ``derived`` axes are skipped — a machine guess is already served
    from ``derived_tags`` and must never be promoted into ``user_tags``.
    ``user_unvetted`` records are dropped: the only writer of unvetted tags
    was this function (an earlier bug), and a stale one would outrank fresh
    analyzer output forever.

    Failures here never abort a scan — the XMP sidecar is already written and
    is the primary artifact.
    """
    try:
        sidecar = read_tag_sidecar(image_path)
    except Exception:  # pragma: no cover - defensive, read path already guards
        return

    user_tags = dict(sidecar.get("user_tags") or {})
    overrides = dict(sidecar.get("user_overrides") or {})

    # Purge unvetted user-tag leftovers from the pre-fix stamper: they were
    # never genuine human input and would outrank fresh analyzer output
    # forever.  This runs even without a feedback artifact (the old stamper
    # was the only writer of ``confirmed_by: "unvetted"``).
    stale_unvetted = [
        axis
        for axis, rec in user_tags.items()
        if isinstance(rec, dict) and rec.get("confirmed_by") == "unvetted"
    ]
    for axis in stale_unvetted:
        del user_tags[axis]
    changed = bool(stale_unvetted)

    feedback = sidecar.get("feedback_for_future_scans")
    derived = sidecar.get("derived_tags") or {}

    if feedback and derived:
        resolved = apply_feedback_at_scan(feedback, derived)

        for axis, record in resolved.items():
            try:
                canonical_axis = validate_axis_key(axis)
            except TaxonomyError:
                continue
            source = record.get("source")
            if source == "user_confirmed":
                # Restamp from the artifact so the human assertion survives
                # even if its on-disk record was lost.
                user_tags[canonical_axis] = {
                    "key": record.get("key"),
                    "label": record.get("label"),
                    "confirmed_by": "user",
                }
                # A fresh confirmation supersedes a deletion of the same axis.
                overrides.pop(canonical_axis, None)
                changed = True
            elif source == "user_override":
                try:
                    overrides[canonical_axis] = make_override(
                        canonical_axis,
                        record.get("old"),
                        record.get("key"),
                        reason="",
                    )
                except TaxonomyError:
                    continue
                changed = True

    if not changed:
        return

    try:
        write_tag_sidecar(
            image_path,
            user_tags=user_tags,
            user_overrides=overrides,
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

    # Feedback recorded against a *different* but similar file lives in that
    # file's sidecar, so gather every artifact in the scan's directories once.
    feedback_index = _build_feedback_index(_scan_roots(images, args.output_dir))
    if feedback_index:
        log.info("Loaded %d feedback artifact(s) for cross-file matching", len(feedback_index))

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
            _persist_scan_taxonomy(
                img_path,
                results,
                feedback_index=feedback_index,
                output_dir=args.output_dir,
            )
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
