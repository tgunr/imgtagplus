"""Tests for imgtagplus.converter — SVG/DXF detection and rasterization."""

from pathlib import Path

import pytest

from imgtagplus import converter
from imgtagplus.converter import (
    ConversionError,
    UnsupportedVectorError,
    VectorFormatError,
    detect_vector_format,
    is_valid_vector,
    rasterize_vector,
)
from imgtagplus.scanner import IMAGE_EXTENSIONS, scan

MINIMAL_SVG = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100">
  <rect x="10" y="10" width="80" height="80" fill="none" stroke="black"/>
  <line x1="0" y1="0" x2="100" y2="100" stroke="red"/>
</svg>
"""

MINIMAL_DXF = """  0\r
SECTION\r
  2\r
ENTITIES\r
  0\r
LINE\r
  8\r
0\r
 10\r
0.0\r
 20\r
0.0\r
 11\r
100.0\r
 21\r
50.0\r
  0\r
ENDSEC\r
  0\r
EOF\r
"""


@pytest.fixture()
def svg_file(tmp_path: Path) -> Path:
    p = tmp_path / "drawing.svg"
    p.write_text(MINIMAL_SVG, encoding="utf-8")
    return p


@pytest.fixture()
def dxf_file(tmp_path: Path) -> Path:
    p = tmp_path / "part.dxf"
    p.write_text(MINIMAL_DXF, encoding="ascii", newline="")
    return p


# ── format detection ──────────────────────────────────────────────────────


def test_detect_svg(svg_file):
    assert detect_vector_format(svg_file) == "svg"
    assert is_valid_vector(svg_file)


def test_detect_dxf(dxf_file):
    assert detect_vector_format(dxf_file) == "dxf"
    assert is_valid_vector(dxf_file)


def test_reject_non_vector_extension(tmp_path):
    p = tmp_path / "photo.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    with pytest.raises(UnsupportedVectorError):
        detect_vector_format(p)
    assert not is_valid_vector(p)


def test_reject_raster_renamed_svg(tmp_path):
    p = tmp_path / "fake.svg"
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    with pytest.raises(VectorFormatError):
        detect_vector_format(p)
    assert not is_valid_vector(p)


def test_reject_svg_renamed_dxf(tmp_path):
    p = tmp_path / "fake.dxf"
    p.write_text(MINIMAL_SVG, encoding="utf-8")
    with pytest.raises(VectorFormatError):
        detect_vector_format(p)


def test_reject_malformed_svg(tmp_path):
    p = tmp_path / "broken.svg"
    p.write_text("<?xml version='1.0'?><svg><rect", encoding="utf-8")
    with pytest.raises(VectorFormatError):
        detect_vector_format(p)


def test_reject_xml_wrong_root(tmp_path):
    p = tmp_path / "wrong.svg"
    p.write_text("<?xml version='1.0'?><html><body/></html>", encoding="utf-8")
    with pytest.raises(VectorFormatError):
        detect_vector_format(p)


def test_reject_empty_file(tmp_path):
    p = tmp_path / "empty.dxf"
    p.write_bytes(b"")
    with pytest.raises(VectorFormatError):
        detect_vector_format(p)


def test_reject_missing_file(tmp_path):
    with pytest.raises(VectorFormatError):
        detect_vector_format(tmp_path / "ghost.svg")


# ── rasterization ─────────────────────────────────────────────────────────


@pytest.mark.skipif(converter.shutil.which("resvg") is None, reason="resvg CLI not installed")
def test_rasterize_svg(svg_file):
    with rasterize_vector(svg_file) as raster:
        assert raster.fmt == "svg"
        assert raster.path.suffix == ".png"
        assert raster.path.stat().st_size > 0
        assert raster.source == svg_file
        tmpdir = raster._tmpdir
    assert not tmpdir.exists()  # isolated temp dir cleaned up


@pytest.mark.skipif(converter.shutil.which("resvg") is None, reason="resvg CLI not installed")
def test_rasterize_svg_pixels(svg_file):
    from PIL import Image

    with rasterize_vector(svg_file, target_px=256) as raster:
        with Image.open(raster.path) as im:
            assert max(im.size) <= 256 + 1  # resvg fit-to may round


def test_rasterize_dxf(dxf_file):
    pytest.importorskip("ezdxf")
    pytest.importorskip("matplotlib")
    with rasterize_vector(dxf_file) as raster:
        assert raster.fmt == "dxf"
        assert raster.path.suffix == ".png"
        assert raster.path.stat().st_size > 0
        tmpdir = raster._tmpdir
    assert not tmpdir.exists()


def test_rasterize_real_dxf_fixtures():
    """Generated real-world DXF fixtures round-trip through rasterization."""
    pytest.importorskip("ezdxf")
    pytest.importorskip("matplotlib")
    fixtures = sorted((Path(__file__).parent / "fixtures").glob("*.dxf"))
    assert fixtures, "DXF fixtures missing from tests/fixtures"
    for f in fixtures:
        with rasterize_vector(f) as raster:
            assert raster.fmt == "dxf"
            assert raster.path.stat().st_size > 0
            from PIL import Image

            with Image.open(raster.path) as im:
                assert im.size[0] > 0 and im.size[1] > 0
        assert not raster._tmpdir.exists()


def test_rasterize_invalid_svg_raises(tmp_path):
    p = tmp_path / "junk.svg"
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    with pytest.raises(VectorFormatError):
        rasterize_vector(p)


# ── scanner integration ───────────────────────────────────────────────────


def test_scanner_finds_vector_files(tmp_path, svg_file, dxf_file):
    found = scan(tmp_path)
    assert set(found) == {svg_file.resolve(), dxf_file.resolve()}


def test_scanner_accepts_single_vector_file(dxf_file):
    assert scan(dxf_file) == [dxf_file.resolve()]


def test_vector_extensions_in_image_extensions():
    assert {".svg", ".dxf"} <= IMAGE_EXTENSIONS
