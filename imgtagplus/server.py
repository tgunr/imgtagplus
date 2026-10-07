"""FastAPI server for the local ImgTagPlus web UI.

The server keeps a single background tagging job alive at a time and mirrors
logs/progress to the browser via Server-Sent Events so the frontend can stay
simple and stateless.
"""

import argparse
import asyncio
import collections
import json
import logging
import mimetypes
import os
import queue
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from imgtagplus.app import run as app_run
from imgtagplus.logger import DEFAULT_LOG_DIR
from imgtagplus.metadata import (
    compute_file_hash,
    read_tag_sidecar,
    read_xmp_tags,
    remove_xmp_tags,
    sidecar_path_for_image,
    write_tag_sidecar,
    write_xmp,
)
from imgtagplus.profiler import get_model_recommendations, get_profiler_summary
from imgtagplus.scanner import IMAGE_EXTENSIONS, scan
from imgtagplus.tags import (
    KEYWORD_FEEDBACK_MIN_INTERSECTION,
    TaxonomyError,
    _deletion_axis,
    build_feedback_artifact,
    make_deletion,
    make_override,
    make_user_tag,
    merge_sidecar,
    merge_tags,
    normalize_key,
    normalize_keyword,
    sanitize_user_keywords,
    taxonomy_summary,
    validate_axis_key,
)


class JobCancelledError(BaseException):
    """Raised by the progress callback when the user requests a stop.

    Inherits from BaseException (not Exception) so it is NOT swallowed by the
    ``except Exception`` handler in app.run that absorbs per-callback errors.
    """

static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)

app = FastAPI(title="ImgTagPlus Web UI")
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

QUEUE_MAXSIZE = 1000

log = logging.getLogger(__name__)
log_queue = queue.Queue(maxsize=QUEUE_MAXSIZE)
progress_queue = queue.Queue(maxsize=QUEUE_MAXSIZE)
_job_lock = threading.Lock()
_job_state_lock = threading.Lock()
_job_started_at: datetime | None = None
_job_started_monotonic: float | None = None
_last_job_runtime_seconds: int | None = None
_stop_requested = False
_sse_semaphore = asyncio.Semaphore(5)

_rate_limits: dict[str, collections.deque] = {}
_RATE_LIMIT_WINDOW = 10  # seconds


def _check_rate_limit(client_ip: str, limit: int) -> bool:
    """Return True if the request should be allowed."""
    now = time.monotonic()
    if client_ip not in _rate_limits:
        _rate_limits[client_ip] = collections.deque()
    timestamps = _rate_limits[client_ip]
    while timestamps and now - timestamps[0] > _RATE_LIMIT_WINDOW:
        timestamps.popleft()
    if len(timestamps) >= limit:
        return False
    timestamps.append(now)
    return True


def _is_processing() -> bool:
    """Return whether the single worker slot is currently busy."""
    return _job_lock.locked()


def _mark_job_started() -> str:
    """Record the start of the active job and return an ISO timestamp."""
    started_at = datetime.now().astimezone()
    with _job_state_lock:
        global _job_started_at, _job_started_monotonic, _last_job_runtime_seconds
        _job_started_at = started_at
        _job_started_monotonic = time.monotonic()
        _last_job_runtime_seconds = None
    return started_at.isoformat()


def _current_runtime_seconds() -> int | None:
    """Return the active job runtime in whole seconds, if available."""
    with _job_state_lock:
        if _job_started_monotonic is None:
            return None
        return max(0, int(time.monotonic() - _job_started_monotonic))


def _mark_job_finished() -> int | None:
    """Finalize job timing state and return the total runtime in seconds."""
    with _job_state_lock:
        global _job_started_at, _job_started_monotonic, _last_job_runtime_seconds
        runtime_seconds = None
        if _job_started_monotonic is not None:
            runtime_seconds = max(0, int(time.monotonic() - _job_started_monotonic))
        _last_job_runtime_seconds = runtime_seconds
        _job_started_at = None
        _job_started_monotonic = None
        return runtime_seconds


def _job_status_payload() -> dict[str, object]:
    """Return the frontend-facing snapshot of the current job state."""
    with _job_state_lock:
        started_at = _job_started_at.isoformat() if _job_started_at is not None else None
        last_runtime = _last_job_runtime_seconds

    runtime_seconds = _current_runtime_seconds() if _is_processing() else last_runtime
    return {
        "is_processing": _is_processing(),
        "started_at": started_at,
        "runtime_seconds": runtime_seconds,
    }


def _enqueue_latest(target_queue: queue.Queue, item: dict) -> None:
    """Queue an SSE payload, dropping the oldest entry if the buffer is full."""
    try:
        target_queue.put_nowait(item)
    except queue.Full:
        # Prefer fresh UI state over preserving a stale backlog.
        try:
            target_queue.get_nowait()
        except queue.Empty:
            pass
        target_queue.put_nowait(item)


def _drain_queue(target_queue: queue.Queue) -> None:
    """Discard queued SSE events so a new job starts with a clean stream."""
    while True:
        try:
            target_queue.get_nowait()
        except queue.Empty:
            break


class SSEQueueHandler(logging.Handler):
    """Mirror application logs into the SSE stream consumed by the browser."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            _enqueue_latest(log_queue, {"type": "log", "level": record.levelname, "message": msg})
        except Exception:
            self.handleError(record)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Apply a restrictive CSP because the UI only serves local static assets."""
    if request.method in ("POST", "PUT", "DELETE"):
        origin = request.headers.get("origin")
        if origin:
            parsed = urlparse(origin)
            if parsed.hostname not in ("localhost", "127.0.0.1"):
                return HTMLResponse("Forbidden: cross-origin request", status_code=403)

    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
        "base-uri 'self'; form-action 'self'"
    )
    return response

sse_handler = SSEQueueHandler()
sse_handler.setFormatter(logging.Formatter("%(message)s"))
logging.getLogger("imgtagplus").addHandler(sse_handler)
logging.getLogger("imgtagplus").setLevel(logging.INFO)


@app.get("/", response_class=HTMLResponse)
async def index():
    """Serves the main frontend UI."""
    index_file = static_dir / "index.html"
    if not index_file.exists():
        return HTMLResponse("Static file 'index.html' not found.", status_code=404)
    with open(index_file, "r") as f:
        return f.read()

def _serialize_image_record(image_path: Path) -> dict[str, object]:
    """Build a frontend-friendly image record for the viewer grid."""
    stat = image_path.stat()
    tags = read_xmp_tags(image_path)
    xmp_path = sidecar_path_for_image(image_path)
    return {
        "path": str(image_path),
        "name": image_path.name,
        "modified_at": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(),
        "size_bytes": stat.st_size,
        "tags": tags,
        "tag_count": len(tags),
        "xmp_exists": xmp_path.exists(),
    }

@app.get("/api/browse")
async def browse_directory(request: Request, path: str = ""):
    """List visible directories for the file picker within the allowed root."""
    client_ip = request.client.host if request and request.client else "unknown"
    if not _check_rate_limit(client_ip, 100):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    if not path:
        current_path = Path.home()
    else:
        current_path = Path(path)

    if not current_path.exists() or not current_path.is_dir():
        raise HTTPException(status_code=404, detail="Directory does not exist")

    items = []
    if current_path != Path.home() and current_path != Path(current_path.root):
        items.append({"name": "..", "path": str(current_path.parent), "is_dir": True})

    try:
        for item in sorted(current_path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            if not item.name.startswith("."):
                if item.is_dir():
                    items.append({"name": item.name, "path": str(item), "is_dir": True})
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied reading directory")

    return {
        "current_path": str(current_path),
        "items": items,
        "sandbox": False,
    }


@app.get("/api/images")
async def list_images(
    request: Request,
    path: str,
    recursive: bool = False,
    offset: int = 0,
    limit: int = 60,
):
    """List images in a directory for the gallery/lightbox viewer."""
    client_ip = request.client.host if request and request.client else "unknown"
    if not _check_rate_limit(client_ip, 100):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    if not path:
        raise HTTPException(status_code=400, detail="Directory path is required")

    directory_path = Path(path)
    if not directory_path.exists():
        raise HTTPException(status_code=404, detail="Directory does not exist")
    if not directory_path.is_dir():
        raise HTTPException(status_code=400, detail="Path must be a directory")

    safe_offset = max(0, offset)
    safe_limit = max(1, min(120, limit))
    images = scan(directory_path, recursive=recursive)
    page = images[safe_offset:safe_offset + safe_limit]

    return {
        "current_path": str(directory_path.resolve()),
        "images": [_serialize_image_record(image_path) for image_path in page],
        "total": len(images),
        "offset": safe_offset,
        "limit": safe_limit,
        "has_more": safe_offset + safe_limit < len(images),
        "recursive": recursive,
    }


@app.get("/api/image")
async def get_image_file(request: Request, path: str):
    """Serve a single image file to the same-origin frontend viewer."""
    client_ip = request.client.host if request and request.client else "unknown"
    if not _check_rate_limit(client_ip, 200):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    if not path:
        raise HTTPException(status_code=400, detail="Image path is required")

    image_path = Path(path)
    if not image_path.exists() or not image_path.is_file():
        raise HTTPException(status_code=404, detail="Image does not exist")

    resolved_path = image_path.resolve()
    if resolved_path.suffix.lower() not in IMAGE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported image type")

    media_type = mimetypes.guess_type(resolved_path.name)[0] or "application/octet-stream"
    return FileResponse(path=resolved_path, filename=resolved_path.name, media_type=media_type)


# ---------------------------------------------------------------------------
# Taxonomy / editable-tag API
# ---------------------------------------------------------------------------

def _require_image_file(path: str | None) -> Path:
    """Validate a tag-API ``path`` parameter and return the resolved image."""
    if not path:
        raise HTTPException(status_code=400, detail="Image path is required")
    image_path = Path(path)
    if not image_path.exists() or not image_path.is_file():
        raise HTTPException(status_code=404, detail="Image does not exist")
    return image_path.resolve()


def _load_tag_state(image_path: Path) -> dict:
    """Read the sidecar, applying stale-content rules.

    When the image bytes changed since the sidecar was written, derived tags
    and deletions are dropped (they describe the old content) but user tags,
    overrides, and feedback persist across content changes.
    """
    from imgtagplus.metadata import _get_image_lock

    with _get_image_lock(image_path):
        sidecar = read_tag_sidecar(image_path)
        stale = (
            bool(sidecar.get("file_hash"))
            and sidecar.get("file_hash") != compute_file_hash(image_path)
        )
        if stale:
            sidecar["derived_tags"] = {}
            sidecar["user_deletions"] = []
            sidecar["file_hash"] = compute_file_hash(image_path)
        elif not sidecar.get("file_hash"):
            sidecar["file_hash"] = compute_file_hash(image_path)
        return sidecar


def _save_tag_state(image_path: Path, sidecar: dict) -> dict:
    """Write the sidecar under the per-image lock and return the merged view."""
    from imgtagplus.metadata import _get_image_lock

    with _get_image_lock(image_path):
        file_hash = sidecar.get("file_hash") or compute_file_hash(image_path)
        user_keywords = sanitize_user_keywords(sidecar.get("user_keywords"))
        # Keyword feedback needs to know what the image looked like when the
        # human was editing it: the condition is the full effective keyword
        # surface (machine tags in the XMP bag + typed user keywords), so
        # similar-tagged images can inherit the keywords later.
        condition_keywords = [*read_xmp_tags(image_path), *user_keywords]
        # Regenerate the feedback artifact from the human edits being saved,
        # so it always reflects the current sidecar rather than drifting.
        feedback = build_feedback_artifact(
            file_hash=file_hash,
            user_tags=sidecar.get("user_tags"),
            user_deletions=sidecar.get("user_deletions"),
            user_overrides=sidecar.get("user_overrides"),
            user_keywords=user_keywords,
            condition_keywords=condition_keywords,
        )
        write_tag_sidecar(
            image_path,
            derived_tags=sidecar.get("derived_tags"),
            user_tags=sidecar.get("user_tags"),
            user_deletions=sidecar.get("user_deletions"),
            user_overrides=sidecar.get("user_overrides"),
            user_keywords=user_keywords,
            feedback=feedback,
            file_hash=file_hash,
        )
        # Re-read under the same lock so the response reflects exactly what
        # landed on disk (write_tag_sidecar returns a path, not the payload).
        persisted = read_tag_sidecar(image_path)
    return merge_sidecar(persisted)


def _tag_view(image_path: Path) -> dict:
    """Merged effective-tag view for one image, including sidecar internals."""
    sidecar = _load_tag_state(image_path)
    merged = merge_sidecar(sidecar)
    merged["file_hash"] = sidecar.get("file_hash")
    merged["user_keywords"] = sanitize_user_keywords(sidecar.get("user_keywords"))
    merged["sidecar_path"] = str(sidecar_path_for_image(image_path))
    return merged


@app.get("/api/taxonomy")
async def get_taxonomy(request: Request):
    """Full axes/keys/labels/precedence summary for building the editor UI."""
    client_ip = request.client.host if request and request.client else "unknown"
    if not _check_rate_limit(client_ip, 100):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    return {"ok": True, "taxonomy": taxonomy_summary()}


@app.get("/api/tags")
async def get_tags(request: Request, path: str):
    """Effective tags for one image: axes, provenance, deletions, overrides."""
    client_ip = request.client.host if request and request.client else "unknown"
    if not _check_rate_limit(client_ip, 200):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    image_path = _require_image_file(path)
    return {"ok": True, "tags": _tag_view(image_path)}


async def _mutate_tags(request: Request, body: dict, mutate) -> dict:
    """Shared write path: validate, load, mutate, save. ``mutate`` raises
    TaxonomyError (→ 400) or HTTPException for contract violations."""
    client_ip = request.client.host if request and request.client else "unknown"
    if not _check_rate_limit(client_ip, 60):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    image_path = _require_image_file(body.get("path"))
    sidecar = _load_tag_state(image_path)
    try:
        mutate(sidecar, body)
    except TaxonomyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    merged = _save_tag_state(image_path, sidecar)
    return {"ok": True, "tags": merged}


@app.put("/api/tags/user")
async def put_user_tag(request: Request):
    """Assign a user tag on an axis. Body: {path, axis, key}."""
    body = await request.json()

    def mutate(sidecar: dict, payload: dict) -> None:
        axis = validate_axis_key(payload.get("axis", ""))
        record = make_user_tag(axis, payload.get("key", ""))
        user_tags = dict(sidecar.get("user_tags", {}))
        user_tags[axis] = record
        # A fresh user tag supersedes a deletion of the same axis.
        deletions = [
            d for d in sidecar.get("user_deletions", [])
            if _deletion_axis(d) != axis
        ]
        sidecar["user_tags"] = user_tags
        sidecar["user_deletions"] = deletions

    return await _mutate_tags(request, body, mutate)


@app.put("/api/tags/override")
async def put_override(request: Request):
    """Override the current value of an axis. Body: {path, axis, new, reason?}.

    The axis must have a current value (derived or user) to override — 400
    otherwise.
    """
    body = await request.json()

    def mutate(sidecar: dict, payload: dict) -> None:
        axis = validate_axis_key(payload.get("axis", ""))
        current = merge_sidecar(sidecar)["axes"].get(axis)
        if not current or not current.get("key"):
            raise HTTPException(
                status_code=400,
                detail=f"axis {axis} has no current value to override",
            )
        record = make_override(
            axis, current.get("key"), payload.get("new"), reason=payload.get("reason", "")
        )
        overrides = dict(sidecar.get("user_overrides", {}))
        overrides[axis] = record
        sidecar["user_overrides"] = overrides

    return await _mutate_tags(request, body, mutate)


@app.put("/api/tags/delete")
async def delete_tag(request: Request):
    """Delete the tag on an axis. Body: {path, axis}.

    The axis must have a current value; the deletion persists in the sidecar
    and suppresses re-derived tags at the next scan.
    """
    body = await request.json()

    def mutate(sidecar: dict, payload: dict) -> None:
        axis = validate_axis_key(payload.get("axis", ""))
        current = merge_sidecar(sidecar)["axes"].get(axis)
        if not current or not current.get("key"):
            raise HTTPException(
                status_code=400,
                detail=f"axis {axis} has no current value to delete",
            )
        deletions = [
            d for d in sidecar.get("user_deletions", [])
            if _deletion_axis(d) != axis
        ]
        deletions.append(make_deletion(axis, current.get("key")))
        sidecar["user_deletions"] = deletions

    return await _mutate_tags(request, body, mutate)


@app.post("/api/tags/reset-deletion")
async def reset_deletion(request: Request):
    """Undo a deletion so the analyzer can re-propose a tag. Body: {path, axis}."""
    body = await request.json()

    def mutate(sidecar: dict, payload: dict) -> None:
        axis = validate_axis_key(payload.get("axis", ""))
        before = len(sidecar.get("user_deletions", []))
        sidecar["user_deletions"] = [
            d for d in sidecar.get("user_deletions", [])
            if _deletion_axis(d) != axis
        ]
        if len(sidecar["user_deletions"]) == before:
            raise HTTPException(
                status_code=400,
                detail=f"axis {axis} has no deletion to reset",
            )

    return await _mutate_tags(request, body, mutate)


# ---------------------------------------------------------------------------
# Free-form keyword feedback
# ---------------------------------------------------------------------------

def _propagate_keyword_feedback(donor_path: Path, artifact: dict) -> list[dict]:
    """Apply a donor's keyword-feedback artifact to its sibling images now.

    Mirrors what a scan would do with :func:`keyword_feedback_additions` but
    is limited to the donor's own directory, so an interactive save stays
    bounded.  A sibling receives the keywords when its known tag surface
    (XMP bag + its own sidecar user keywords) meets the artifact's
    ``keyword_condition``.  The donor itself is skipped — it already carries
    the keywords.  Returns one record per successfully updated sibling.
    """
    keywords = artifact.get("user_added_keywords") or []
    condition = artifact.get("keyword_condition") or {}
    must = [
        m for m in (normalize_keyword(t) for t in (condition.get("must_intersect") or ()))
        if m
    ]
    try:
        min_required = max(
            1,
            int(condition.get("min_intersection", KEYWORD_FEEDBACK_MIN_INTERSECTION)),
        )
    except (TypeError, ValueError):
        min_required = KEYWORD_FEEDBACK_MIN_INTERSECTION

    if not keywords or not must:
        return []

    try:
        candidates = scan(donor_path.parent)
    except (FileNotFoundError, ValueError) as exc:
        log.warning("Keyword feedback sweep could not list %s: %s", donor_path.parent, exc)
        return []

    donor_resolved = donor_path.resolve()
    applied: list[dict] = []
    for candidate in candidates:
        if candidate.resolve() == donor_resolved:
            continue
        known = set(read_xmp_tags(candidate))
        sidecar = read_tag_sidecar(candidate)
        known |= {normalize_keyword(k) for k in (sidecar.get("user_keywords") or ()) if k}
        overlap = known & set(must)
        if len(overlap) < min_required:
            continue
        try:
            write_xmp(candidate, list(keywords))
        except Exception as exc:
            log.warning("Keyword feedback could not update %s: %s", candidate.name, exc)
            continue
        log.info(
            "Feedback: offered %s to %s (shares %d tag(s): %s)",
            ", ".join(keywords),
            candidate.name,
            len(overlap),
            ", ".join(sorted(overlap)[:5]),
        )
        applied.append({
            "path": str(candidate),
            "name": candidate.name,
            "added": list(keywords),
        })
    return applied


def _apply_keyword_to_image(image_path: Path, keywords: list[str]) -> dict:
    """Core keyword-apply logic for single-image and batch endpoints."""
    from imgtagplus.metadata import _get_image_lock

    with _get_image_lock(image_path):
        sidecar = _load_tag_state(image_path)
        existing = sanitize_user_keywords(sidecar.get("user_keywords"))
        added_now = [k for k in keywords if k not in existing]
        if not added_now:
            return {"path": str(image_path), "added": [], "skipped": True}
        sidecar["user_keywords"] = sorted(set(existing) | set(keywords))
        merged = _save_tag_state(image_path, sidecar)
        write_xmp(image_path, added_now)
        artifact = read_tag_sidecar(image_path).get("feedback_for_future_scans") or {}
        applied = _propagate_keyword_feedback(image_path, artifact) if added_now else []
        return {
            "path": str(image_path),
            "added": added_now,
            "user_keywords": list(read_tag_sidecar(image_path).get("user_keywords") or []),
            "applied_to": applied,
            "tags": merged,
        }


@app.put("/api/tags/keyword")
async def put_keyword(request: Request):
    """Add free-form keywords to an image and offer them to similar siblings.

    Body: ``{path, keyword}`` or ``{path, keywords: [...]}``.  Keywords are
    normalized (trimmed, whitespace-collapsed, lowercased) and stored in the
    sidecar's ``user_keywords``; the feedback artifact records them with a
    ``keyword_condition`` built from the image's effective tags, and the new
    keywords are merged into the image's own XMP immediately.

    Propagation: sibling images in the same directory that share at least
    ``KEYWORD_FEEDBACK_MIN_INTERSECTION`` of the condition tags receive the
    keywords in their XMP right away.  Any later scan re-applies this from
    the persisted artifact, recursively.
    """
    client_ip = request.client.host if request and request.client else "unknown"
    if not _check_rate_limit(client_ip, 60):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    body = await request.json()
    image_path = _require_image_file(body.get("path"))
    raw = body.get("keywords")
    if not isinstance(raw, list):
        single = body.get("keyword")
        raw = [single] if single is not None else []
    if not raw:
        raise HTTPException(status_code=400, detail="keyword(s) required")
    keywords = sanitize_user_keywords(raw)
    if not keywords:
        raise HTTPException(status_code=400, detail="no usable keywords supplied")

    from imgtagplus.metadata import _get_image_lock

    with _get_image_lock(image_path):
        sidecar = _load_tag_state(image_path)
        existing = sanitize_user_keywords(sidecar.get("user_keywords"))
        added_now = [k for k in keywords if k not in existing]
        sidecar["user_keywords"] = sorted(set(existing) | set(keywords))
        merged = _save_tag_state(image_path, sidecar)
        persisted = read_tag_sidecar(image_path)

        if added_now:
            write_xmp(image_path, added_now)
        artifact = persisted.get("feedback_for_future_scans") or {}
        applied = _propagate_keyword_feedback(image_path, artifact) if added_now else []

    return {
        "ok": True,
        "user_keywords": list(persisted.get("user_keywords") or []),
        "added": added_now,
        "applied_to": applied,
        "tags": merged,
    }


@app.put("/api/tags/batch-keyword")
async def batch_keyword(request: Request):
    """Apply one or more keywords to many images in one request.

    Body: ``{paths: [...], keyword}`` or ``{paths: [...], keywords: [...]}``.
    Returns per-image results including any immediate feedback propagation
    that fired for each donor.
    """
    client_ip = request.client.host if request and request.client else "unknown"
    if not _check_rate_limit(client_ip, 20):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    body = await request.json()
    raw_paths = body.get("paths") or []
    paths = [str(p).strip() for p in raw_paths if str(p).strip()]
    raw = body.get("keywords")
    if not isinstance(raw, list):
        single = body.get("keyword")
        raw = [single] if single is not None else []
    if not paths or not raw:
        raise HTTPException(status_code=400, detail="paths and keyword(s) required")
    keywords = sanitize_user_keywords(raw)
    if not keywords:
        raise HTTPException(status_code=400, detail="no usable keywords supplied")

    results = []
    for path_str in paths:
        try:
            image_path = Path(path_str).resolve()
            if not image_path.exists() or not image_path.is_file():
                results.append({"path": path_str, "ok": False, "error": "file not found"})
                continue
            result = _apply_keyword_to_image(image_path, keywords)
            results.append({"ok": True, **result})
        except Exception as exc:
            results.append({"path": path_str, "ok": False, "error": str(exc)})
    return {"ok": True, "results": results}


@app.put("/api/tags/keyword-remove")
async def remove_keyword(request: Request):
    """Remove a free-form keyword from an image. Body: {path, keyword}.

    Drops it from ``user_keywords`` and the image's own XMP bag.  Keywords
    already inherited by other images stay there — removing stops *future*
    propagation, it does not retract history.
    """
    client_ip = request.client.host if request and request.client else "unknown"
    if not _check_rate_limit(client_ip, 60):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    body = await request.json()
    image_path = _require_image_file(body.get("path"))
    keyword = normalize_keyword(body.get("keyword"))
    if not keyword:
        raise HTTPException(status_code=400, detail="keyword required")

    from imgtagplus.metadata import _get_image_lock

    with _get_image_lock(image_path):
        sidecar = _load_tag_state(image_path)
        existing = sanitize_user_keywords(sidecar.get("user_keywords"))
        if keyword not in existing:
            raise HTTPException(
                status_code=404,
                detail=f"keyword {keyword!r} is not stored for this image",
            )
        sidecar["user_keywords"] = [k for k in existing if k != keyword]
        merged = _save_tag_state(image_path, sidecar)
        persisted = read_tag_sidecar(image_path)
        xmp_removed = remove_xmp_tags(image_path, [keyword]) is not None

    return {
        "ok": True,
        "user_keywords": list(persisted.get("user_keywords") or []),
        "xmp_removed": xmp_removed,
        "tags": merged,
    }


@app.get("/api/models")
async def get_models():
    """Returns available models based on profiler specs."""
    return {"models": get_model_recommendations()}


@app.get("/api/system")
async def get_system():
    """Returns full system profile."""
    return get_profiler_summary()


@app.get("/api/status")
async def get_status():
    """Check if a tagging job is currently running."""
    return _job_status_payload()


@app.post("/api/stop")
async def stop_job():
    """Request the current background job to stop."""
    if not _job_lock.locked():
        raise HTTPException(status_code=409, detail="No job is currently running")
    
    global _stop_requested
    _stop_requested = True
    _enqueue_latest(
        log_queue,
        {"type": "log", "level": "WARNING", "message": "Stop signal received. Job will stop after completing current image..."},
    )
    return {"status": "stop_requested"}

@app.get("/health")
async def health_check():
    """Return a simple readiness response for local process management."""
    return {"status": "ok"}

@app.post("/api/tag")
async def start_tagging(request: Request):
    """Validate a tag request and launch the single background worker."""
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip, 10):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    data = await request.json()
    input_path_raw = data.get("input")
    model_id = data.get("model_id", "clip")
    threshold = max(0.0, min(1.0, float(data.get("threshold", 0.25))))
    max_tags = max(1, min(200, int(data.get("max_tags", 20))))
    recursive = bool(data.get("recursive", False))
    output_dir_str = data.get("output_dir")
    output_dir = Path(output_dir_str) if output_dir_str else None
    accelerator = data.get("accelerator")
    overwrite = bool(data.get("overwrite", False))

    if not input_path_raw:
        raise HTTPException(status_code=400, detail="Invalid or non-existent path")

    input_path = Path(input_path_raw)
    if not input_path.exists():
        raise HTTPException(status_code=400, detail=f"Invalid or non-existent path: {input_path}")

    if not _job_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A tagging job is already in progress")

    _drain_queue(log_queue)
    _drain_queue(progress_queue)
    started_at = _mark_job_started()
    _last_progress = {"current": 0, "total": 0}
    worker_result = {"status": "unknown", "message": None}
    
    global _stop_requested
    _stop_requested = False

    def progress_callback(current, total, filename):
        global _stop_requested
        if _stop_requested:
            raise JobCancelledError("Job stopped by user")
        _last_progress["current"] = current
        _last_progress["total"] = total
        _enqueue_latest(
            progress_queue,
            {
                "type": "progress",
                "current": current,
                "total": total,
                "filename": filename,
                "runtime_seconds": _current_runtime_seconds(),
            },
        )

    def run_worker():
        try:
            args = argparse.Namespace(
                input=input_path,
                recursive=recursive,
                threshold=threshold,
                max_tags=max_tags,
                silent=True,
                continue_on_error=True,
                log_file=None, # use default
                model_dir=None, # use default
                model_id=model_id,
                output_dir=output_dir,
                accelerator=accelerator,
                overwrite=overwrite,
                input_timeout=30,
            )
            _enqueue_latest(
                progress_queue,
                {
                    "type": "progress",
                    "current": 0,
                    "total": 0,
                    "filename": "Scanning files...",
                    "runtime_seconds": _current_runtime_seconds(),
                },
            )
            exit_code = app_run(args, progress_callback=progress_callback)
            if exit_code != 0:
                worker_result["status"] = "failed"
                worker_result["message"] = f"Job exited with code {exit_code}. Check terminal output for details."
            else:
                worker_result["status"] = "completed"

            if worker_result["status"] == "completed" and _last_progress["total"] == 0:
                worker_result["status"] = "empty_scan"
                _enqueue_latest(
                    log_queue,
                    {"type": "log", "level": "WARNING",
                     "message": f"No images found at {input_path}. "
                                "Check that the path contains supported image files."},
                )
        except JobCancelledError:
            worker_result["status"] = "stopped"
            worker_result["message"] = "Job stopped by user"
        except Exception as e:
            worker_result["status"] = "failed"
            worker_result["message"] = str(e)
            _enqueue_latest(
                log_queue,
                {"type": "log", "level": "ERROR", "message": f"Worker crashed: {e}"},
            )
        finally:
            global _stop_requested
            _stop_requested = False
            runtime_seconds = _mark_job_finished()
            try:
                _job_lock.release()
            except RuntimeError:
                pass
            _enqueue_latest(
                progress_queue,
                {
                    "type": "done",
                    "runtime_seconds": runtime_seconds,
                    "result_status": worker_result["status"],
                    "result_message": worker_result["message"],
                },
            )

    thread = threading.Thread(target=run_worker, daemon=True)
    thread.start()
    return {"status": "started", "started_at": started_at}

@app.get("/api/stream")
async def sse_stream():
    """Stream batched log/progress updates and idle heartbeats to the browser."""
    if _sse_semaphore.locked():
        raise HTTPException(status_code=429, detail="Too many SSE connections")

    async def event_generator():
        async with _sse_semaphore:
            try:
                sleep_interval = 0.1
                while True:
                    # Send logs first to ensure errors reach the UI before a 'done' event closes the connection
                    chunks = []
                    try:
                        # Batch up to 50 log messages to prevent overwhelming the socket
                        for _ in range(50):
                            log = log_queue.get_nowait()
                            chunks.append(log)
                    except queue.Empty:
                        pass

                    if chunks:
                        for c in chunks:
                            yield f"data: {json.dumps(c)}\n\n"

                    # Send progress updates
                    progress_chunks = []
                    try:
                        while True:
                            prog = progress_queue.get_nowait()
                            progress_chunks.append(prog)
                            is_done = prog.get('type') == 'done'
                            event_data = json.dumps({
                                "type": "progress",
                                "current": prog.get('current', 0),
                                "total": prog.get('total', 0),
                                "filename": prog.get('filename', ''),
                                "done": is_done,
                                "runtime_seconds": prog.get('runtime_seconds'),
                                "result_status": prog.get('result_status'),
                                "result_message": prog.get('result_message'),
                            })
                            yield f"data: {event_data}\n\n"
                            await asyncio.sleep(0.01)
                    except queue.Empty:
                        pass

                    if not _is_processing() and log_queue.empty() and progress_queue.empty():
                        yield "data: {\"type\": \"idle\"}\n\n"

                    if chunks or progress_chunks:
                        sleep_interval = 0.1
                    else:
                        sleep_interval = min(sleep_interval * 1.5, 1.0)
                    await asyncio.sleep(sleep_interval)
            except asyncio.CancelledError:
                logging.getLogger(__name__).debug("SSE client disconnected.")
                return

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/logs/download")
async def download_log():
    """Download the newest CLI log file for the most recent run."""
    log_files = list(DEFAULT_LOG_DIR.glob("imgtagplus_*.log"))
    if not log_files:
        return HTMLResponse("No log files found.", status_code=404)
    # Sort by modification time to get the latest
    latest_log = sorted(log_files, key=lambda p: p.stat().st_mtime)[-1]
    return FileResponse(path=latest_log, filename=latest_log.name)


def start_server(host="127.0.0.1", port=5000):
    """Run the FastAPI app under uvicorn for the local web UI."""
    logging.info(f"Starting Web UI on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    start_server()
