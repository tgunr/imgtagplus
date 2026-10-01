"""Vector-format (SVG/DXF) detection and raster conversion for ImgTagPlus.

PNG and the other native raster formats are consumed by the analyzer
directly.  SVG and DXF files are fabrication drawings, not rasters, so
they are first validated (safe format detection) and then rasterized
into a temporary PNG that the existing analyzer can consume:

- SVG -> PNG via the ``resvg`` CLI (``/opt/homebrew/bin/resvg``; chosen
  because cairosvg/cairocffi cannot resolve the Homebrew libcairo at
  import time on this machine).
- DXF -> PNG via ``ezdxf`` + its matplotlib drawing add-on.

All rasterization happens inside a :class:`RasterHandle` context
manager, which owns an isolated temporary file and deletes it on exit.
Malformed or oversized inputs raise :class:`VectorFormatError` or
:class:`UnsupportedVectorError` with a useful message instead of
crashing the run.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from xml.etree import ElementTree

log = logging.getLogger(__name__)

#: Extensions treated as vector drawings that need rasterization.
VECTOR_EXTENSIONS: frozenset[str] = frozenset({".svg", ".dxf"})

#: Reject absurdly large inputs before parsing (zip-bomb / memory guard).
MAX_INPUT_BYTES: int = 100 * 1024 * 1024  # 100 MB

#: Longest raster side, in pixels, for converted drawings.
DEFAULT_RASTER_PX: int = 1024

#: Seconds allowed for one resvg invocation.
RESVG_TIMEOUT_S: int = 60

_SVG_ROOT_RE = re.compile(rb"<svg[\s>]", re.IGNORECASE)
_XML_MAGIC = b"<?xml"


class VectorFormatError(ValueError):
    """The file claims a vector extension but its content is invalid."""


class UnsupportedVectorError(ValueError):
    """The vector format cannot be rasterized in this environment."""


class ConversionError(RuntimeError):
    """Rasterization of a valid vector file failed."""


def is_valid_vector(path: Path) -> bool:
    """Return True when *path* passes format detection for its extension."""
    try:
        detect_vector_format(path)
        return True
    except (VectorFormatError, UnsupportedVectorError, OSError):
        return False


def detect_vector_format(path: Path) -> str:
    """Validate a vector file and return its format (``"svg"`` / ``"dxf"``).

    Raises
    ------
    UnsupportedVectorError
        The extension is not a supported vector format.
    VectorFormatError
        The content is malformed, empty, oversized, or not the format
        its extension claims.
    """
    path = Path(path)
    ext = path.suffix.lower()
    if ext not in VECTOR_EXTENSIONS:
        raise UnsupportedVectorError(f"Not a vector format: {ext or path.name}")

    try:
        size = path.stat().st_size
    except OSError as exc:
        raise VectorFormatError(f"Cannot read {path}: {exc}") from exc
    if size == 0:
        raise VectorFormatError(f"Empty file: {path}")
    if size > MAX_INPUT_BYTES:
        raise VectorFormatError(
            f"File too large for conversion ({size} bytes > {MAX_INPUT_BYTES}): {path}"
        )

    head = _read_head(path, 4096)
    if ext == ".svg":
        _validate_svg(path, head)
    else:
        _validate_dxf(path, head)
    return ext.lstrip(".")


def _read_head(path: Path, nbytes: int) -> bytes:
    try:
        with open(path, "rb") as fh:
            return fh.read(nbytes)
    except OSError as exc:
        raise VectorFormatError(f"Cannot read {path}: {exc}") from exc


def _validate_svg(path: Path, head: bytes) -> None:
    # Cheap binary rejection first (rasters renamed to .svg etc.).
    if head.startswith((b"\x89PNG", b"GIF8", b"\xff\xd8", b"RIFF", b"BM")):
        raise VectorFormatError(f"Not SVG content (binary image?): {path}")
    if not (_SVG_ROOT_RE.search(head) or head.lstrip().startswith(_XML_MAGIC)):
        raise VectorFormatError(f"Not SVG content (no <svg> root): {path}")
    try:
        root = ElementTree.parse(path).getroot()
    except ElementTree.ParseError as exc:
        raise VectorFormatError(f"Malformed SVG XML in {path}: {exc}") from exc
    except OSError as exc:
        raise VectorFormatError(f"Cannot parse SVG {path}: {exc}") from exc
    if not root.tag.lower().endswith("svg"):
        raise VectorFormatError(
            f"XML root is <{root.tag}>, expected <svg>: {path}"
        )


def _validate_dxf(path: Path, head: bytes) -> None:
    # ASCII DXF starts with group codes; binary DXF starts with a known
    # 22-byte sentinel.  Reject anything else (e.g. an SVG renamed .dxf).
    if head.startswith(b"  0\r\nSECTION") or head.startswith(b"  0\nSECTION"):
        return
    if b"AutoCAD Binary DXF" in head[:64]:
        return
    if _SVG_ROOT_RE.search(head) or head.lstrip().startswith(_XML_MAGIC):
        raise VectorFormatError(f"File looks like SVG/XML, not DXF: {path}")
    try:
        text = head.decode("utf-8", errors="replace")
    except Exception as exc:  # pragma: no cover - decode(replace) rarely fails
        raise VectorFormatError(f"Unreadable DXF {path}: {exc}") from exc
    if "SECTION" not in text.upper():
        raise VectorFormatError(f"Not DXF content (no SECTION marker): {path}")


def rasterize_vector(
    path: Path,
    target_px: int = DEFAULT_RASTER_PX,
) -> "RasterHandle":
    """Validate and rasterize *path*, returning an open :class:`RasterHandle`.

    Use as a context manager so the isolated temporary PNG is cleaned up::

        with rasterize_vector(drawing) as raster:
            tags = tagger.tag_image(raster.path)
    """
    fmt = detect_vector_format(path)
    if fmt == "svg":
        return _rasterize_svg(path, target_px)
    return _rasterize_dxf(path, target_px)


class RasterHandle:
    """Owns a temporary PNG rasterized from a vector source."""

    def __init__(self, tmpdir: Path, path: Path, source: Path, fmt: str):
        self._tmpdir = tmpdir
        self.path = path
        self.source = source
        self.fmt = fmt

    def __enter__(self) -> "RasterHandle":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def close(self) -> None:
        shutil.rmtree(self._tmpdir, ignore_errors=True)


def _rasterize_svg(path: Path, target_px: int) -> RasterHandle:
    resvg = shutil.which("resvg")
    if not resvg:
        raise UnsupportedVectorError(
            "SVG conversion needs the 'resvg' CLI on PATH "
            "(brew install resvg); not found."
        )
    tmpdir = Path(tempfile.mkdtemp(prefix="imgtagplus-svg-"))
    out = tmpdir / f"{path.stem}.png"
    cmd = [
        resvg,
        "--quiet",
        f"--width={int(target_px)}",
        "--background=white",
        str(path),
        str(out),
    ]
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            cmd,
            capture_output=True,
            timeout=RESVG_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise ConversionError(f"resvg timed out on {path}") from exc
    except OSError as exc:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise UnsupportedVectorError(f"Cannot run resvg: {exc}") from exc

    if proc.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
        detail = (proc.stderr or proc.stdout or b"").decode("utf-8", "replace").strip()
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise ConversionError(
            f"resvg failed on {path} (exit {proc.returncode}): {detail[:500]}"
        )
    log.debug("Rasterized SVG %s -> %s", path, out)
    return RasterHandle(tmpdir, out, path, "svg")


def _rasterize_dxf(path: Path, target_px: int) -> RasterHandle:
    try:
        import ezdxf
        from ezdxf.addons.drawing import RenderContext, Frontend
        from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise UnsupportedVectorError(
            f"DXF conversion needs 'ezdxf' and 'matplotlib' installed: {exc}"
        ) from exc

    try:
        doc = ezdxf.readfile(str(path))
    except FileNotFoundError as exc:
        raise VectorFormatError(f"DXF file vanished: {path}") from exc
    except Exception as exc:
        raise ConversionError(f"ezdxf cannot read {path}: {exc}") from exc

    msp = doc.modelspace()
    tmpdir = Path(tempfile.mkdtemp(prefix="imgtagplus-dxf-"))
    out = tmpdir / f"{path.stem}.png"
    dpi = 100
    inches = max(2.0, target_px / dpi)
    fig = plt.figure(figsize=(inches, inches), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor("white")
    fig.patch.set_facecolor("white")
    try:
        ctx = RenderContext(doc)
        Frontend(ctx, MatplotlibBackend(ax)).draw_layout(msp, finalize=True)
        fig.savefig(out, facecolor="white", bbox_inches="tight", pad_inches=0.1)
    except Exception as exc:
        raise ConversionError(f"DXF drawing failed for {path}: {exc}") from exc
    finally:
        plt.close(fig)

    if not out.is_file() or out.stat().st_size == 0:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise ConversionError(f"DXF rasterization produced no output for {path}")
    log.debug("Rasterized DXF %s -> %s", path, out)
    return RasterHandle(tmpdir, out, path, "dxf")
