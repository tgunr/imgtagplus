from __future__ import annotations

from pathlib import Path

from imgtagplus.metadata import (
    _build_xmp,
    _read_existing_tags,
    read_xmp_tags,
    resolve_xmp_path,
    sidecar_path_for_image,
    write_xmp,
)


def test_write_xmp_creates_sidecar_with_escaped_tags(sample_image: Path) -> None:
    xmp_path = write_xmp(sample_image, ["cats & dogs", "a < b > c"])

    text = xmp_path.read_text(encoding="utf-8")

    assert xmp_path.name == "sample.jpg.xmp"
    assert "&amp;" in text
    assert "&lt;" in text
    assert "&gt;" in text
    assert 'rdf:about="sample.jpg"' in text


def test_write_xmp_merges_existing_tags_when_not_overwriting(sample_image: Path) -> None:
    write_xmp(sample_image, ["beta"])

    merged_path = write_xmp(sample_image, ["alpha"], overwrite=False)

    assert _read_existing_tags(merged_path) == {"alpha", "beta"}


def test_write_xmp_overwrites_existing_tags(sample_image: Path) -> None:
    write_xmp(sample_image, ["legacy"])

    xmp_path = write_xmp(sample_image, ["fresh"], overwrite=True)

    assert _read_existing_tags(xmp_path) == {"fresh"}


def test_read_existing_tags_returns_empty_set_for_malformed_xml(
    tmp_path: Path, caplog
) -> None:
    broken_xmp = tmp_path / "broken.xmp"
    broken_xmp.write_text("<not-xml", encoding="utf-8")

    tags = _read_existing_tags(broken_xmp)

    assert tags == set()
    assert "Could not parse existing XMP file" in caplog.text


def test_read_existing_tags_ignores_non_subject_rdf_li(tmp_path: Path) -> None:
    """Only dc:subject rdf:li elements should be read as tags."""
    xmp_content = '''<?xml version="1.0" encoding="UTF-8"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
  <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
    <rdf:Description xmlns:dc="http://purl.org/dc/elements/1.1/">
      <dc:subject>
        <rdf:Bag>
          <rdf:li>landscape</rdf:li>
          <rdf:li>sunset</rdf:li>
        </rdf:Bag>
      </dc:subject>
      <dc:creator>
        <rdf:Bag>
          <rdf:li>John Doe</rdf:li>
        </rdf:Bag>
      </dc:creator>
    </rdf:Description>
  </rdf:RDF>
</x:xmpmeta>'''
    xmp_path = tmp_path / "test.xmp"
    xmp_path.write_text(xmp_content)
    tags = _read_existing_tags(xmp_path)
    assert tags == {"landscape", "sunset"}
    assert "John Doe" not in tags


def test_build_xmp_includes_all_tags_and_packet_markers() -> None:
    xml = _build_xmp(["alpha", "beta"], "image.jpg")

    assert xml.startswith('<?xpacket begin=')
    assert '<rdf:li>alpha</rdf:li>' in xml
    assert '<rdf:li>beta</rdf:li>' in xml
    assert xml.rstrip().endswith('<?xpacket end="w"?>')


def test_sidecar_path_for_image_defaults_to_image_directory(sample_image: Path) -> None:
    assert sidecar_path_for_image(sample_image) == sample_image.parent / "sample.jpg.xmp"


def test_sidecar_path_keeps_full_name_so_extensions_do_not_collide(
    tmp_path: Path,
) -> None:
    """``panel.png`` and ``panel.dxf`` must not share one sidecar."""
    png = tmp_path / "panel.png"
    dxf = tmp_path / "panel.dxf"

    assert sidecar_path_for_image(png) == tmp_path / "panel.png.xmp"
    assert sidecar_path_for_image(dxf) == tmp_path / "panel.dxf.xmp"
    assert sidecar_path_for_image(png) != sidecar_path_for_image(dxf)


def test_sidecar_path_honours_output_dir(sample_image: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"

    assert sidecar_path_for_image(sample_image, out) == out / "sample.jpg.xmp"


def test_write_xmp_writes_extension_preserving_name(tmp_path: Path) -> None:
    png = tmp_path / "panel.png"
    png.write_bytes(b"png bytes")
    dxf = tmp_path / "panel.dxf"
    dxf.write_bytes(b"dxf bytes")

    write_xmp(png, ["from-png"])
    write_xmp(dxf, ["from-dxf"])

    assert read_xmp_tags(png) == ["from-png"]
    assert read_xmp_tags(dxf) == ["from-dxf"]
    assert not (tmp_path / "panel.xmp").exists()


# ---------------------------------------------------------------------------
# Legacy stem-only sidecars (<stem>.xmp) written by older builds
# ---------------------------------------------------------------------------


def test_read_xmp_tags_falls_back_to_legacy_stem_sidecar(sample_image: Path) -> None:
    legacy = sample_image.with_suffix(".xmp")
    legacy.write_text(_build_xmp(["hand-typed"], sample_image.name), encoding="utf-8")

    assert read_xmp_tags(sample_image) == ["hand-typed"]


def test_canonical_sidecar_supersedes_legacy_stem_sidecar(sample_image: Path) -> None:
    """Once the canonical file exists, the legacy file is never read again."""
    sample_image.with_suffix(".xmp").write_text(
        _build_xmp(["legacy"], sample_image.name), encoding="utf-8"
    )
    canonical = write_xmp(sample_image, ["current"], overwrite=True)

    # Rewrite the legacy file with a tag the canonical sidecar lacks; a read
    # must still come from the canonical file only.
    sample_image.with_suffix(".xmp").write_text(
        _build_xmp(["ghost"], sample_image.name), encoding="utf-8"
    )

    assert read_xmp_tags(sample_image) == ["current"]
    assert resolve_xmp_path(sample_image) == canonical


def test_write_xmp_migrates_legacy_sidecar_tags_on_first_write(sample_image: Path) -> None:
    legacy = sample_image.with_suffix(".xmp")
    legacy.write_text(_build_xmp(["hand-typed"], sample_image.name), encoding="utf-8")

    new_path = write_xmp(sample_image, ["scanned"])

    assert new_path == sidecar_path_for_image(sample_image)
    assert read_xmp_tags(sample_image) == ["hand-typed", "scanned"]
    # The legacy file is left for the user to remove deliberately.
    assert legacy.exists()


def test_write_xmp_overwrite_does_not_adopt_legacy_tags(sample_image: Path) -> None:
    """``overwrite=True`` means a clean slate for the canonical sidecar."""
    legacy = sample_image.with_suffix(".xmp")
    legacy.write_text(_build_xmp(["hand-typed"], sample_image.name), encoding="utf-8")

    xmp_path = write_xmp(sample_image, ["fresh"], overwrite=True)

    assert _read_existing_tags(xmp_path) == {"fresh"}


def test_write_xmp_overwrite_flag_is_not_shadowed_by_a_previous_legacy_scan(
    sample_image: Path,
) -> None:
    """A canonical file already written stops the legacy fallback forever."""
    write_xmp(sample_image, ["first"])
    xmp_path = write_xmp(sample_image, ["second"], overwrite=True)

    assert _read_existing_tags(xmp_path) == {"second"}


def test_resolve_xmp_path_returns_none_without_any_sidecar(sample_image: Path) -> None:
    assert resolve_xmp_path(sample_image) is None


def test_resolve_xmp_path_prefers_canonical_over_legacy(sample_image: Path) -> None:
    sample_image.with_suffix(".xmp").write_text(
        _build_xmp(["legacy"], sample_image.name), encoding="utf-8"
    )
    canonical = write_xmp(sample_image, ["current"])

    assert resolve_xmp_path(sample_image) == canonical


def test_legacy_and_canonical_collide_only_for_extensionless_names(tmp_path: Path) -> None:
    """``panel`` has no stem/extension split, so there is nothing to migrate."""
    asset = tmp_path / "panel"
    asset.write_bytes(b"no extension")

    canonical = write_xmp(asset, ["tag"])

    assert canonical == tmp_path / "panel.xmp"
    assert resolve_xmp_path(asset) == canonical
    assert read_xmp_tags(asset) == ["tag"]

