"""Hugging Face cache placement helpers.

Model downloads must land in a writable cache even when a development shell
exports ``HF_HOME`` to an external volume that is not mounted. ``huggingface_hub``
and ``transformers`` snapshot their cache locations at import time, so the
environment must be corrected *before* either library is imported.
"""

from __future__ import annotations

import os
from pathlib import Path


def _is_usable(path: Path) -> bool:
    """Return True if Hugging Face can use (and write to) this cache root."""
    try:
        if path.is_symlink() and not path.exists():
            # Dangling symlink, e.g. ~/.cache/huggingface -> unmounted volume.
            return False
        if path.exists():
            return path.is_dir() and os.access(path, os.W_OK)
    except OSError:
        return False

    # Nonexistent target: it must be creatable from the nearest existing parent.
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return probe.is_dir() and os.access(probe, os.W_OK)


def default_cache_root() -> Path:
    """Writable per-user model cache shared by the CLIP and Florence loaders."""
    xdg = os.environ.get("XDG_CACHE_HOME", "").strip()
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / "imgtagplus"


def point_hf_caches_at(root: Path) -> Path:
    """Force every Hugging Face cache env var at ``root`` and return it.

    Must run before ``huggingface_hub``/``transformers`` are imported, since both
    resolve these values into module-level constants at import time.
    """
    root = Path(root).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(root)
    # The app passes cache_dir=<root> to from_pretrained, so the hub cache is the
    # root itself (models--* live directly under it) rather than a "hub" subdir.
    os.environ["HUGGINGFACE_HUB_CACHE"] = str(root)
    os.environ["HF_HUB_CACHE"] = str(root)
    os.environ["HF_MODULES_CACHE"] = str(root / "modules")
    os.environ["HF_XET_CACHE"] = str(root / "xet")
    return root


def ensure_hf_cache_env() -> Path:
    """Point every Hugging Face cache at the app's own writable model cache.

    The CLIP and Florence loaders always pass an explicit ``cache_dir`` under
    this root, so a development shell's ``HF_HOME`` (frequently an external
    volume that is unmounted, or an empty mount-point stub) is deliberately
    ignored. That prevents both ``PermissionError`` while creating the cache
    under ``/Volumes`` and surprise re-downloads to the wrong location. Pass
    ``--model-dir`` / ``IMGTAGPLUS_MODEL_DIR`` to use a different root.
    """
    root = default_cache_root()
    if not _is_usable(root):
        root = Path(__file__).resolve().parent.parent / ".cache" / "imgtagplus"
    return point_hf_caches_at(root)
