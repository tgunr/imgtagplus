"""Regression coverage for the scan-time derived-tag persistence path.

Before this the scan loop wrote XMP and re-read the sidecar but never wrote
``derived_tags``, so a fresh scan left the sidecar empty and the whole
feedback path was dead until something else populated it by hand.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from imgtagplus.app import run
from imgtagplus.metadata import compute_file_hash, read_tag_sidecar, write_tag_sidecar
from imgtagplus.tags import (
    AXES,
    DERIVED_CONFIDENCE_THRESHOLD,
    VALUE_LIST_BY_AXIS,
    apply_feedback_at_scan,
    build_feedback_artifact,
    collect_similar_feedback,
    derive_tags_from_clip_results,
    feedback_applies_to_hash,
    hash_prefix_pattern,
)

from test_app_runtime import FakeTagger, _make_args

# CLIP labels whose normalized text names a taxonomy value on two axes, plus a
# control ("photo") that must not map to anything.
_CNC_LABELS = [("cnc part", 0.9), ("blueprint", 0.7), ("photo", 0.3)]


def _create_distinct_image(path: Path, marker: str) -> Path:
    """A minimal valid JPEG whose bytes differ per *marker*.

    Distinct content matters: the feedback path is keyed on a SHA-256 prefix,
    so two byte-identical copies would exercise a rescan while claiming to
    cover a "similar file".
    """
    soi = b"\xff\xd8"
    app0 = b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    eoi = b"\xff\xd9"
    path.write_bytes(soi + app0 + marker.encode("ascii") + eoi)
    return path


def _run_scan(tmp_path: Path, images, results) -> int:
    """Drive app.run() over *images* with a fake tagger, as the CLI would."""
    monitor = MagicMock()
    monitor.stop.return_value = MagicMock(summary=lambda: "test stats")
    with (
        patch("imgtagplus.app.scan", return_value=list(images)),
        patch("imgtagplus.app.Monitor", return_value=monitor),
        patch("imgtagplus.tagger.Tagger", return_value=FakeTagger(results=results)),
    ):
        return run(_make_args(tmp_path))


def test_derive_tags_from_clip_results_maps_axes() -> None:
    derived = derive_tags_from_clip_results(_CNC_LABELS)

    assert set(derived) <= set(AXES)
    assert derived["machine_context"]["key"] == "CNC_MILL"
    assert derived["output_intent"]["key"] == "DOCUMENTATION"
    for axis, record in derived.items():
        assert record["key"] in VALUE_LIST_BY_AXIS[axis]
        assert 0.0 <= record["confidence"] <= 1.0
        assert record["confidence"] >= DERIVED_CONFIDENCE_THRESHOLD
        assert "confirmed_by" not in record


def test_derive_tags_suppresses_sub_threshold_labels() -> None:
    """A label scoring below the threshold yields no axis at all."""
    assert (
        derive_tags_from_clip_results([("blueprint", DERIVED_CONFIDENCE_THRESHOLD - 0.01)]) == {}
    )


def test_scan_persists_derived_tags_into_sidecar(tmp_path: Path) -> None:
    img = _create_distinct_image(tmp_path / "part.jpg", "solo")

    assert _run_scan(tmp_path, [img], _CNC_LABELS) == 0

    sidecar = read_tag_sidecar(img)
    assert sidecar["derived_tags"], "scan left derived_tags empty"
    assert sidecar["derived_tags"]["machine_context"]["key"] == "CNC_MILL"
    assert sidecar["file_hash"] == compute_file_hash(img)


def test_rescan_honors_feedback_for_future_scans(tmp_path: Path) -> None:
    """A user confirmation recorded against a file survives a rescan of it."""
    img = _create_distinct_image(tmp_path / "part.jpg", "rescan")
    file_hash = compute_file_hash(img)

    write_tag_sidecar(
        img,
        derived_tags=derive_tags_from_clip_results(_CNC_LABELS),
        file_hash=file_hash,
        feedback=build_feedback_artifact(
            file_hash=file_hash,
            user_tags={"output_intent": {"key": "CUT_PATH", "confirmed_by": "user"}},
        ),
    )

    # Rescan: the analyzer re-derives OUTPUT_INTENT, but the stored
    # confirmation must keep the fresh guess out of derived_tags.
    assert _run_scan(tmp_path, [img], _CNC_LABELS) == 0

    persisted = read_tag_sidecar(img)
    assert "output_intent" not in persisted["derived_tags"]
    # The confirmation itself is untouched by the scan.
    assert persisted["user_tags"]["output_intent"]["key"] == "CUT_PATH"
    # And it still wins the effective view.
    effective = apply_feedback_at_scan(persisted["feedback_for_future_scans"], persisted["derived_tags"])
    assert effective["output_intent"]["source"] == "user_confirmed"


def test_feedback_applies_to_hash_buckets_by_prefix() -> None:
    """The bucket key is the hash prefix, not the whole hash."""
    artifact = build_feedback_artifact(
        file_hash="abcdef1234567890" * 4,
        user_tags={"output_intent": {"key": "CUT_PATH", "confirmed_by": "user"}},
    )
    assert artifact["similar_file_hash_pattern"] == "ABCDEF12*"

    # Same bucket, different full hash → feedback carries over.
    assert feedback_applies_to_hash(artifact, "abcdef1299" + "0" * 56) is True
    assert feedback_applies_to_hash(artifact, "abcdef1234567890" * 4) is True
    # Different bucket → no carry-over.
    assert feedback_applies_to_hash(artifact, "99999999" + "0" * 56) is False

    # collect_similar_feedback merges only the matching bucket, and the more
    # specific prefix wins the axes the two share.
    other = build_feedback_artifact(
        file_hash="99999999" + "0" * 56,
        user_tags={"material_family": {"key": "STEEL", "confirmed_by": "user"}},
    )
    merged = collect_similar_feedback([other, artifact], "abcdef1299" + "0" * 56)
    assert merged["user_confirmed_axes"] == {"output_intent": "CUT_PATH"}


def test_scan_borrows_feedback_from_a_similar_file(tmp_path: Path) -> None:
    """The real wiring: feedback crosses to a *different* file in one bucket.

    Two genuinely distinct files cannot be made to share a SHA-256 prefix by
    construction, so the donor artifact is minted against the target's real
    hash — which is what a near-duplicate re-export looks like on disk.
    """
    donor = _create_distinct_image(tmp_path / "part-a.jpg", "donor")
    target = _create_distinct_image(tmp_path / "part-b.jpg", "target")
    target_hash = compute_file_hash(target)
    assert compute_file_hash(donor) != target_hash

    write_tag_sidecar(
        donor,
        file_hash=compute_file_hash(donor),
        feedback=build_feedback_artifact(
            file_hash=target_hash,
            user_tags={"output_intent": {"key": "CUT_PATH", "confirmed_by": "user"}},
        ),
    )

    # part-b has no sidecar of its own and still inherits the confirmation.
    assert _run_scan(tmp_path, [target], _CNC_LABELS) == 0
    persisted = read_tag_sidecar(target)
    assert "output_intent" not in persisted["derived_tags"]
    # The un-confirmed axes still come from the analyzer.
    assert persisted["derived_tags"]["machine_context"]["key"] == "CNC_MILL"


def test_scan_does_not_borrow_unrelated_feedback(tmp_path: Path) -> None:
    """A different hash bucket must not leak its feedback into this file."""
    donor = _create_distinct_image(tmp_path / "part-a.jpg", "donor")
    unrelated = _create_distinct_image(tmp_path / "part-z.jpg", "unrelated")
    donor_hash = compute_file_hash(donor)
    unrelated_hash = compute_file_hash(unrelated)
    assert hash_prefix_pattern(donor_hash) != hash_prefix_pattern(unrelated_hash)

    write_tag_sidecar(
        donor,
        file_hash=donor_hash,
        feedback=build_feedback_artifact(
            file_hash=donor_hash,
            user_tags={"output_intent": {"key": "CUT_PATH", "confirmed_by": "user"}},
        ),
    )

    assert _run_scan(tmp_path, [unrelated], _CNC_LABELS) == 0
    assert read_tag_sidecar(unrelated)["derived_tags"]["output_intent"]["key"] == "DOCUMENTATION"
