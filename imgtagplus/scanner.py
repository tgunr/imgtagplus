"""Image file discovery for ImgTagPlus.

Finds image files by extension, supporting single-file, directory, and
recursive directory scanning.
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

# Extensions recognised as images (case-insensitive matching).
# Vector drawing formats (.svg/.dxf) are discovered here too — they are
# rasterized on the fly by app.py via converter before tagging.
IMAGE_EXTENSIONS: set[str] = {
    ".jpg", ".jpeg", ".png", ".webp", ".tiff", ".tif",
    ".bmp", ".gif",
    ".svg", ".dxf",
}


def scan(input_path: Path, recursive: bool = False) -> list[Path]:
    """Return a sorted list of image paths found at *input_path*.

    Parameters
    ----------
    input_path:
        A single image file **or** a directory to scan.
    recursive:
        When *True* and *input_path* is a directory, search all
        subdirectories as well.

    Returns
    -------
    list[Path]
        Absolute paths to discovered image files, sorted alphabetically.

    Raises
    ------
    FileNotFoundError
        If *input_path* does not exist.
    ValueError
        If *input_path* is a file but not a recognised image type.
    """
    input_path = input_path.resolve()

    if not input_path.exists():
        raise FileNotFoundError(f"Input path does not exist: {input_path}")

    # -- Single file ----------------------------------------------------------
    if input_path.is_file():
        if input_path.suffix.lower() not in IMAGE_EXTENSIONS:
            raise ValueError(
                f"Not a recognised image file ({input_path.suffix}): "
                f"{input_path}"
            )
        log.info("Single image: %s", input_path)
        return [input_path]

    # -- Directory ------------------------------------------------------------
    if not input_path.is_dir():
        raise ValueError(f"Input path is neither a file nor directory: {input_path}")

    glob_pattern = "**/*" if recursive else "*"
    images = sorted(
        p.resolve()
        for p in input_path.glob(glob_pattern)
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    )

    mode = "recursively" if recursive else "non-recursively"
    log.info("Found %d image(s) scanning %s (%s)", len(images), input_path, mode)
    return images
