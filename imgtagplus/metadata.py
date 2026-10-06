"""XMP sidecar file writer for ImgTagPlus.

Generates Adobe-compatible XMP sidecar files (``.xmp``) that store
keywords in the ``dc:subject`` field.  Recognised by Lightroom, Bridge,
Darktable, digiKam, XnView, and virtually all DAM systems.

Sidecars are named after the *full* asset filename (``panel.png`` →
``panel.png.xmp``) so assets that differ only by extension never share one
sidecar.  This matches the JSON sidecar convention
(``TAG_SIDECAR_SUFFIX``) and the ``<name>.<ext>.xmp`` form Adobe software
also accepts.  Sidecars written by older builds used the bare stem
(``panel.xmp``); those are still *read* — see ``resolve_xmp_path`` for the
migration policy.

Also owns the taxonomy JSON sidecar (``.imgtagplus.json``) that carries
the analyzer's ``derived_tags`` alongside human edits — user tags,
deletions, overrides, and the ``feedback_for_future_scans`` artifact.
The JSON sidecar is deliberately separate from the XMP file so DAM
software never sees internal bookkeeping.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import threading
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping, Sequence

log = logging.getLogger(__name__)

# XML namespaces used in XMP.
_NS = {
    "x": "adobe:ns:meta/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "dc": "http://purl.org/dc/elements/1.1/",
    "xmp": "http://ns.adobe.com/xap/1.0/",
    "xmpMM": "http://ns.adobe.com/xap/1.0/mm/",
    "lr": "http://ns.adobe.com/lightroom/1.0/",
}

# Register namespaces so ElementTree preserves prefixes.
for prefix, uri in _NS.items():
    ET.register_namespace(prefix, uri)


#: Filename suffix of the XMP sidecar.  Appended to the full asset name
#: (``panel.png`` → ``panel.png.xmp``) rather than to the bare stem.
XMP_SIDECAR_SUFFIX = ".xmp"


def _canonical_xmp_path(
    image_path: Path, output_dir: Path | None = None
) -> Path:
    """Return the canonical XMP sidecar path for *image_path*.

    Named from the full filename so ``panel.png`` and ``panel.dxf`` in one
    directory get ``panel.png.xmp`` and ``panel.dxf.xmp``.
    """
    base_dir = output_dir if output_dir is not None else image_path.parent
    return base_dir / f"{image_path.name}{XMP_SIDECAR_SUFFIX}"


def _legacy_xmp_path(
    image_path: Path, output_dir: Path | None = None
) -> Path:
    """Return the pre-2026-10 stem-only XMP sidecar path, or ``None``.

    ``panel.png`` → ``panel.xmp``.  This collides across extensions, so it
    is only consulted as a read fallback for sidecars written by builds
    that predate the extension-preserving name.
    """
    base_dir = output_dir if output_dir is not None else image_path.parent
    legacy = base_dir / f"{image_path.stem}{XMP_SIDECAR_SUFFIX}"
    if legacy == _canonical_xmp_path(image_path, output_dir):
        # Extensionless asset: ``name == stem``, so the canonical and legacy
        # names coincide and there is no second candidate to fall back to.
        return None
    return legacy


def write_xmp(
    image_path: Path,
    tags: Sequence[str],
    output_dir: Path | None = None,
    overwrite: bool = False,
) -> Path:
    """Write (or merge into) an XMP sidecar file for *image_path*.

    The sidecar is written to the canonical ``<name>.<ext>.xmp`` path.
    Tags from a pre-existing legacy ``<stem>.xmp`` (written by older
    builds) are carried over on the first write so human keywords entered
    in Lightroom are not silently lost, and the legacy file is left in
    place — removal is the user's call, not the scanner's.

    Parameters
    ----------
    image_path:
        Absolute path to the source image.
    tags:
        Keyword strings to store in ``dc:subject``.
    output_dir:
        Directory for the ``.xmp`` file.  Defaults to the same
        directory as the image.
    overwrite:
        If ``True``, replace existing tags entirely instead of merging.
        This is a clean slate: neither an existing canonical
        ``<name>.<ext>.xmp`` nor a legacy ``<stem>.xmp`` is read, so
        ``overwrite=True`` never resurrects stale or legacy tags.

    Returns
    -------
    Path
        Absolute path to the written ``.xmp`` file.
    """
    if output_dir is None:
        output_dir = image_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    xmp_path = _canonical_xmp_path(image_path, output_dir)
    legacy_path = _legacy_xmp_path(image_path, output_dir)

    # Merge tags unless the caller asked for a clean slate.  ``overwrite=True``
    # deliberately ignores *both* the canonical sidecar and any legacy
    # ``<stem>.xmp`` — it means "these tags are the complete truth".
    existing_tags: set[str] = set()
    if not overwrite:
        if xmp_path.exists():
            existing_tags = _read_existing_tags(xmp_path)
            log.debug("Existing XMP has %d tags: %s", len(existing_tags), xmp_path)
        elif legacy_path is not None and legacy_path.exists():
            # Migration: adopt the legacy sidecar's keywords on this write so
            # hand-typed keywords are not lost when the name changes.
            legacy_tags = _read_existing_tags(legacy_path)
            if legacy_tags:
                log.info(
                    "Migrating legacy XMP sidecar %s to %s (%d tag(s))",
                    legacy_path,
                    xmp_path,
                    len(legacy_tags),
                )
                existing_tags = legacy_tags

    merged = sorted(existing_tags | set(tags))

    # Build the XMP document.
    xml_str = _build_xmp(merged, image_path.name)
    xmp_path.write_text(xml_str, encoding="utf-8")
    log.debug("Wrote %d tags to %s", len(merged), xmp_path)
    return xmp_path


def sidecar_path_for_image(image_path: Path, output_dir: Path | None = None) -> Path:
    """Return the canonical XMP sidecar path associated with *image_path*.

    ``panel.png`` → ``panel.png.xmp``, so assets that differ only by
    extension never collide.  This is a pure path computation — no
    filesystem access, no legacy fallback; use ``resolve_xmp_path`` when
    you need to know which file a read would actually hit.
    """
    return _canonical_xmp_path(image_path, output_dir)


def resolve_xmp_path(image_path: Path, output_dir: Path | None = None) -> Path | None:
    """Return the XMP sidecar path a read should use, or ``None``.

    Prefers the canonical ``<name>.<ext>.xmp``.  When that is absent and a
    legacy stem-only ``<stem>.xmp`` from an older build exists, the legacy
    path is returned so its tags remain visible until the next scan
    migrates them.  ``None`` means the asset has no XMP metadata at all.
    """
    canonical = _canonical_xmp_path(image_path, output_dir)
    if canonical.exists():
        return canonical
    legacy = _legacy_xmp_path(image_path, output_dir)
    if legacy is not None and legacy.exists():
        return legacy
    return None


def read_xmp_tags(image_path: Path, output_dir: Path | None = None) -> list[str]:
    """Return sorted tags from the XMP sidecar for *image_path*.

    Falls back to a legacy stem-only ``<stem>.xmp`` written by an older
    build when the canonical sidecar is missing, so pre-existing human
    keywords stay visible after the naming change.

    Missing sidecars are treated as empty metadata rather than an error so
    callers can render "untagged" images without extra exception handling.
    """
    xmp_path = resolve_xmp_path(image_path, output_dir=output_dir)
    if xmp_path is None:
        return []
    return sorted(_read_existing_tags(xmp_path))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_xmp(tags: list[str], source_filename: str) -> str:
    """Return a complete XMP XML string containing *tags*."""
    lines = [
        '<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>',
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">',
        '  <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">',
        '    <rdf:Description',
        f'      rdf:about="{source_filename}"',
        '      xmlns:dc="http://purl.org/dc/elements/1.1/"',
        '      xmlns:xmp="http://ns.adobe.com/xap/1.0/"',
        '      xmlns:lr="http://ns.adobe.com/lightroom/1.0/">',
        '      <dc:subject>',
        '        <rdf:Bag>',
    ]
    for tag in tags:
        escaped = tag.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        lines.append(f"          <rdf:li>{escaped}</rdf:li>")
    lines += [
        '        </rdf:Bag>',
        '      </dc:subject>',
        '    </rdf:Description>',
        '  </rdf:RDF>',
        '</x:xmpmeta>',
        '<?xpacket end="w"?>',
    ]
    return "\n".join(lines) + "\n"


def _read_existing_tags(xmp_path: Path) -> set[str]:
    """Parse existing ``dc:subject`` tags from an XMP file."""
    try:
        tree = ET.parse(xmp_path)
        root = tree.getroot()
        tags: set[str] = set()
        ns = {
            "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
            "dc": "http://purl.org/dc/elements/1.1/",
        }
        # Navigate specifically to dc:subject > rdf:Bag > rdf:li
        for subject in root.iter(f"{{{ns['dc']}}}subject"):
            for bag in subject.iter(f"{{{ns['rdf']}}}Bag"):
                for li in bag.iter(f"{{{ns['rdf']}}}li"):
                    text = (li.text or "").strip()
                    if text:
                        tags.add(text)
        return tags
    except ET.ParseError:
        log.warning("Could not parse existing XMP file: %s", xmp_path)
        return set()


# ---------------------------------------------------------------------------
# Per-image serialization
# ---------------------------------------------------------------------------

#: Guards ``_IMAGE_LOCKS`` itself (not the per-image locks).
_IMAGE_LOCKS_GUARD = threading.Lock()

#: One re-entrant lock per resolved image path, so a tag mutation and a
#: concurrent write for the same image never interleave a read-modify-write
#: on the sidecar.  RLock because the server's load and save paths both
#: acquire it for the same image within one request.
_IMAGE_LOCKS: dict[str, threading.RLock] = {}


def _get_image_lock(image_path: Path) -> threading.RLock:
    """Return the re-entrant lock associated with *image_path*.

    Keyed on the resolved path so symlinked or relative spellings of the
    same image share one lock.  Distinct images never contend.
    """
    try:
        key = str(image_path.resolve())
    except OSError:  # pragma: no cover - unresolvable path
        key = str(image_path)
    with _IMAGE_LOCKS_GUARD:
        lock = _IMAGE_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _IMAGE_LOCKS[key] = lock
        return lock


# ---------------------------------------------------------------------------
# Taxonomy JSON sidecar (.imgtagplus.json)
# ---------------------------------------------------------------------------

#: Sidecar filename, stored next to the image (dotfile, invisible in DAM UIs).
TAG_SIDECAR_SUFFIX = ".imgtagplus.json"

#: Keys this module owns inside the sidecar.  Any other key found in an
#: existing sidecar file is preserved verbatim on rewrite (read-modify-write).
_OWNED_SIDECAR_KEYS = (
    "schema_version",
    "file_hash",
    "filename",
    "derived_tags",
    "user_tags",
    "user_deletions",
    "user_overrides",
    "feedback_for_future_scans",
)


def tag_sidecar_path_for_image(image_path: Path, output_dir: Path | None = None) -> Path:
    """Return the taxonomy JSON sidecar path for *image_path*.

    ``photo.png`` → ``photo.png.imgtagplus.json`` in the same directory
    (or *output_dir* when given), so multiple images differing only by
    extension never collide.
    """
    base_dir = output_dir if output_dir is not None else image_path.parent
    return base_dir / f"{image_path.name}{TAG_SIDECAR_SUFFIX}"


def compute_file_hash(image_path: Path) -> str:
    """Return the SHA-256 hex digest of *image_path*'s bytes."""
    digest = hashlib.sha256()
    with image_path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_tag_sidecar(image_path: Path, output_dir: Path | None = None) -> dict[str, Any]:
    """Read the taxonomy sidecar for *image_path*.

    Missing or unreadable sidecars return ``{}`` — callers treat absent
    bookkeeping the same way the analyzer treats an unclassifiable image.
    A corrupt JSON body logs a warning and returns ``{}`` rather than
    crashing a scan.
    """
    sidecar = tag_sidecar_path_for_image(image_path, output_dir=output_dir)
    if not sidecar.exists():
        return {}
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Could not read taxonomy sidecar %s: %s", sidecar, exc)
        return {}
    if not isinstance(data, dict):
        log.warning("Taxonomy sidecar %s is not a JSON object; ignoring", sidecar)
        return {}
    return data


def write_tag_sidecar(
    image_path: Path,
    *,
    derived_tags: Mapping[str, Any] | None = None,
    user_tags: Mapping[str, Any] | None = None,
    user_deletions: Sequence[str] | None = None,
    user_overrides: Mapping[str, Any] | None = None,
    feedback: Mapping[str, Any] | None = None,
    output_dir: Path | None = None,
    file_hash: str | None = None,
    merge: bool = True,
) -> Path:
    """Create or update the taxonomy JSON sidecar for *image_path*.

    With ``merge=True`` (default) the write is a read-modify-write: unknown
    keys already in the file survive, and only the taxonomy-owned keys are
    updated.  The file is written atomically (temp file + ``os.replace``)
    so a crash mid-write cannot truncate an existing sidecar.
    """
    sidecar = tag_sidecar_path_for_image(image_path, output_dir=output_dir)
    sidecar.parent.mkdir(parents=True, exist_ok=True)

    existing: dict[str, Any] = {}
    if merge and sidecar.exists():
        existing = read_tag_sidecar(image_path, output_dir=output_dir)

    updates: dict[str, Any] = {
        "schema_version": 1,
        "file_hash": file_hash if file_hash is not None else existing.get("file_hash"),
        "filename": image_path.name,
        "derived_tags": dict(derived_tags) if derived_tags is not None else existing.get("derived_tags", {}),
        "user_tags": dict(user_tags) if user_tags is not None else existing.get("user_tags", {}),
        "user_deletions": list(user_deletions) if user_deletions is not None else existing.get("user_deletions", []),
        "user_overrides": dict(user_overrides) if user_overrides is not None else existing.get("user_overrides", {}),
        "feedback_for_future_scans": dict(feedback) if feedback is not None else existing.get("feedback_for_future_scans", {}),
    }

    payload = dict(existing)
    for key in _OWNED_SIDECAR_KEYS:
        payload.pop(key, None)
    payload.update(updates)

    fd, tmp_name = tempfile.mkstemp(
        dir=str(sidecar.parent), prefix=".imgtagplus-", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp_name, sidecar)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    log.debug("Wrote taxonomy sidecar %s", sidecar)
    return sidecar

