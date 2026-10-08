"""Free-form keyword feedback (Option A: artifact-based propagation).

Covers the user-keyword sidecar field, the ``keyword_condition`` rule in
``feedback_for_future_scans``, the interactive sweep in the server, and the
scan-time application in ``app.run``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from imgtagplus.app import run
from imgtagplus.metadata import (
    compute_file_hash,
    read_tag_sidecar,
    read_xmp_tags,
    write_tag_sidecar,
    write_xmp,
)
from imgtagplus.server import app
from imgtagplus.tags import (
    KEYWORD_FEEDBACK_MIN_INTERSECTION,
    build_feedback_artifact,
    keyword_feedback_additions,
    normalize_keyword,
    sanitize_user_keywords,
)

from test_app_runtime import FakeTagger, _make_args


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def _isolate_rate_limiter():
    """Keep this module's request volume out of the shared rate-limit bucket.

    ``server._rate_limits`` is keyed by the TestClient's constant IP, so the
    requests made here would push later test modules (e.g. test_server_tagging)
    over their per-window budgets otherwise.
    """
    from imgtagplus import server as server_module

    server_module._rate_limits.clear()
    yield
    server_module._rate_limits.clear()


def _fake_image(path: Path, marker: str) -> Path:
    """A minimal valid JPEG whose bytes differ per *marker*."""
    path.write_bytes(b"\xff\xd8" + b"\xff\xe0\x00\x10JFIF\x00" + marker.encode("ascii") + b"\xff\xd9")
    return path


# ---------------------------------------------------------------------------
# normalize_keyword / sanitize_user_keywords
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("  Vase  ", "vase"),
        ("Blue   Glass", "blue glass"),
        (None, ""),
        ("", ""),
        ("a" * 65, ""),  # over USER_KEYWORD_MAX_LEN → invalid
        ("a" * 64, "a" * 64),  # at the cap → valid
    ],
)
def test_normalize_keyword(raw, expected: str) -> None:
    assert normalize_keyword(raw) == expected


def test_sanitize_user_keywords_dedupes_and_caps() -> None:
    assert sanitize_user_keywords(["Vase", " vase ", "", "FLOWERS", None]) == ["vase", "flowers"]
    assert sanitize_user_keywords(None) == []
    bulk = sanitize_user_keywords([f"kw{i:04d}" for i in range(300)])
    assert bulk == [f"kw{i:04d}" for i in range(200)]


# ---------------------------------------------------------------------------
# Artifact construction
# ---------------------------------------------------------------------------

def test_artifact_records_keywords_with_condition() -> None:
    artifact = build_feedback_artifact(
        file_hash="abcdef1234567890" + "0" * 48,
        user_keywords=["  Vase ", "flowers"],
        condition_keywords=[" Composed ", "eyes", "face"],
    )
    assert artifact["user_added_keywords"] == ["flowers", "vase"]
    condition = artifact["keyword_condition"]
    assert condition["must_intersect"] == ["composed", "eyes", "face"]
    assert condition["min_intersection"] == KEYWORD_FEEDBACK_MIN_INTERSECTION
    assert artifact["similar_file_hash_pattern"] == "ABCDEF12*"


def test_artifact_without_human_input_is_empty_even_with_typo_keywords() -> None:
    assert build_feedback_artifact(file_hash="abcd", user_keywords=["", "x" * 65]) == {}


# ---------------------------------------------------------------------------
# keyword_feedback_additions
# ---------------------------------------------------------------------------

def test_condition_met_if_intersection_reaches_minimum() -> None:
    artifact = build_feedback_artifact(
        file_hash="abc",
        user_keywords=["vase"],
        condition_keywords=["composed", "eyes", "face"],
        min_intersection=2,
    )
    # Two of the three condition tags → inherit.
    additions = keyword_feedback_additions([artifact], ["rose", "composed", "face"], file_hash="9999")
    assert additions == ["vase"]


def test_below_minimum_intersection_no_inheritance() -> None:
    artifact = build_feedback_artifact(
        file_hash="abc",
        user_keywords=["vase"],
        condition_keywords=["composed", "eyes", "face"],
        min_intersection=2,
    )
    # Only one shared tag → not similar enough.
    assert keyword_feedback_additions([artifact], ["composed", "rose"]) == []
    # Nothing shared at all.
    assert keyword_feedback_additions([artifact], ["sunset", "beach"]) == []


def test_condition_matching_is_case_and_space_insensitive() -> None:
    artifact = build_feedback_artifact(
        file_hash="abc",
        user_keywords=["vase"],
        condition_keywords=["Composed Photo", "face"],
        min_intersection=2,
    )
    assert keyword_feedback_additions([artifact], ["composed  photo", "FACE", "extra"]) == ["vase"]


def test_conditionless_artifact_falls_back_to_hash_bucket() -> None:
    artifact = build_feedback_artifact(
        file_hash="abcd1234" + "0" * 56,
        user_keywords=["vase"],
    )
    assert not artifact["keyword_condition"]["must_intersect"]
    same_bucket = "abcd1234" + "9" * 56  # shares the 8-char prefix
    other_bucket = "ffff1111" + "0" * 56
    assert keyword_feedback_additions([artifact], ["rose"], file_hash=same_bucket) == ["vase"]
    assert keyword_feedback_additions([artifact], ["rose"], file_hash=other_bucket) == []
    # No hash supplied → the bucket rule cannot fire.
    assert keyword_feedback_additions([artifact], ["rose"]) == []


def test_existing_keywords_and_multiple_artifacts_are_deduped() -> None:
    first = build_feedback_artifact(
        file_hash="aaaa",
        user_keywords=["vase"],
        condition_keywords=["face", "eyes"],
    )
    second = build_feedback_artifact(
        file_hash="bbbb",
        user_keywords=["vase", "flowers"],
        condition_keywords=["face", "smile"],
    )
    # "vase" already known → only "flowers" remains from the second donor.
    additions = keyword_feedback_additions([first, second], ["face", "eyes", "smile", "vase"])
    assert additions == ["flowers"]


def test_donor_does_not_inherit_its_own_keywords() -> None:
    artifact = build_feedback_artifact(
        file_hash="aaaa",
        user_keywords=["vase"],
        condition_keywords=["composed", "face"],
    )
    assert keyword_feedback_additions([artifact], ["composed", "face", "vase"]) == []


# ---------------------------------------------------------------------------
# Interactive API: add / remove keyword, sibling sweep
# ---------------------------------------------------------------------------

def test_put_keyword_updates_sidecar_xmp_and_propagates_to_siblings(
    client: TestClient, tmp_path: Path
) -> None:
    donor = _fake_image(tmp_path / "donor.png", "donor")
    target = _fake_image(tmp_path / "target.png", "target")
    other = _fake_image(tmp_path / "other.png", "other")
    write_xmp(donor, ["composed", "eyes", "face"])
    write_xmp(target, ["smile", "composed", "face"])  # shares two → qualifies
    write_xmp(other, ["sunset", "beach"])  # shares none

    response = client.put("/api/tags/keyword", json={"path": str(donor), "keyword": "Vase "})
    assert response.status_code == 200, response.text
    payload = response.json()

    # Own image: keyword stored and immediately visible in XMP.
    assert payload["user_keywords"] == ["vase"]
    assert payload["added"] == ["vase"]
    assert "vase" in read_xmp_tags(donor)

    # Feedback artifact carries keywords + condition built from the donor's
    # effective tags (its XMP bag plus the typed keyword).
    artifact = read_tag_sidecar(donor)["feedback_for_future_scans"]
    assert artifact["user_added_keywords"] == ["vase"]
    assert artifact["keyword_condition"]["min_intersection"] == 2
    assert set(artifact["keyword_condition"]["must_intersect"]) == {
        "composed", "eyes", "face", "vase",
    }

    # The sweep wrote the keyword into the qualifying sibling only.
    assert "vase" in read_xmp_tags(target)
    assert "vase" not in read_xmp_tags(other)
    applied_paths = [entry["path"] for entry in payload["applied_to"]]
    assert applied_paths == [str(target)]


def test_put_keyword_without_shared_tags_applies_to_nothing(
    client: TestClient, tmp_path: Path
) -> None:
    donor = _fake_image(tmp_path / "donor.jpg", "donor")
    write_xmp(donor, ["portrait"])

    response = client.put("/api/tags/keyword", json={"path": str(donor), "keywords": ["vase"]})
    assert response.status_code == 200
    assert response.json()["applied_to"] == []


def test_put_keyword_rejects_invalid_input(client: TestClient, tmp_path: Path) -> None:
    donor = _fake_image(tmp_path / "donor.jpg", "donor")
    assert client.put("/api/tags/keyword", json={"path": str(donor), "keyword": "   "}).status_code == 400
    assert client.put("/api/tags/keyword", json={"path": str(donor), "keywords": []}).status_code == 400
    assert client.put("/api/tags/keyword", json={"path": str(donor)}).status_code == 400


def test_remove_keyword_clears_sidecar_and_xmp(client: TestClient, tmp_path: Path) -> None:
    image = _fake_image(tmp_path / "img.jpg", "img")
    write_xmp(image, ["face", "vase"])
    assert client.put("/api/tags/keyword", json={"path": str(image), "keyword": "vase"}).status_code == 200

    remove = client.put("/api/tags/keyword-remove", json={"path": str(image), "keyword": "VASE"})
    assert remove.status_code == 200
    assert remove.json()["user_keywords"] == []
    assert remove.json()["xmp_removed"] is True
    assert "vase" not in read_xmp_tags(image)

    # The regenerated feedback artifact must not re-propagate the removed
    # keyword.
    artifact = read_tag_sidecar(image)["feedback_for_future_scans"]
    assert artifact.get("user_added_keywords", []) == []


def test_remove_unknown_keyword_returns_404(client: TestClient, tmp_path: Path) -> None:
    image = _fake_image(tmp_path / "img.jpg", "img")
    response = client.put("/api/tags/keyword-remove", json={"path": str(image), "keyword": "vase"})
    assert response.status_code == 404


def test_keyword_endpoints_reject_missing_path(client: TestClient, tmp_path: Path) -> None:
    absent = str(tmp_path / "absent.jpg")
    assert client.put("/api/tags/keyword", json={"path": absent, "keyword": "vase"}).status_code == 404
    assert client.put("/api/tags/keyword-remove", json={"path": absent, "keyword": "vase"}).status_code == 404


# ---------------------------------------------------------------------------
# Scan-time propagation
# ---------------------------------------------------------------------------

class _MonitorStub:
    def start(self) -> None:
        return None

    def stop(self):
        stub = MagicMock()
        stub.summary.return_value = "monitor stub"
        return stub


def _run_scan(images, results) -> int:
    """Drive app.run() over *images* with a fake tagger."""
    with (
        patch("imgtagplus.app.scan", return_value=list(images)),
        patch("imgtagplus.app.Monitor", return_value=_MonitorStub()),
        patch("imgtagplus.tagger.Tagger", return_value=FakeTagger(results=results)),
    ):
        return run(_make_args(Path(images[0].parent)))


def test_scan_propagates_keywords_from_similar_image(tmp_path: Path) -> None:
    donor = _fake_image(tmp_path / "donor.png", "donor")
    target = _fake_image(tmp_path / "target.png", "target")

    # Simulate what the interactive API did for the donor: XMP tags, a typed
    # keyword, and the feedback artifact its save wrote.
    write_xmp(donor, ["composed", "eyes", "face"])
    write_tag_sidecar(
        donor,
        user_keywords=["vase"],
        file_hash=compute_file_hash(donor),
        feedback=build_feedback_artifact(
            file_hash=compute_file_hash(donor),
            user_keywords=["vase"],
            condition_keywords=["composed", "eyes", "face"],
        ),
    )

    # The analyzer tags both files with the donor's condition tags, so the
    # target shares them and must inherit "vase" during this scan.
    results = [("composed", 0.8), ("eyes", 0.7), ("face", 0.6)]
    assert _run_scan([donor, target], results) == 0

    assert "vase" in read_xmp_tags(target)
    # The donor keeps its typed keyword too.
    assert "vase" in read_xmp_tags(donor)
    # Provenance: the inherited keyword is XMP-level only — it is never
    # promoted into the target's user_tags or user_keywords.
    target_sidecar = read_tag_sidecar(target)
    assert target_sidecar["user_tags"] == {}
    assert target_sidecar["user_keywords"] == []


def test_scan_respects_min_intersection_for_keyword_inheritance(
    tmp_path: Path,
) -> None:
    donor = _fake_image(tmp_path / "donor.png", "donor")
    weak = _fake_image(tmp_path / "weak.png", "weak")

    write_xmp(donor, ["composed", "eyes", "face"])
    write_tag_sidecar(
        donor,
        user_keywords=["vase"],
        file_hash=compute_file_hash(donor),
        feedback=build_feedback_artifact(
            file_hash=compute_file_hash(donor),
            user_keywords=["vase"],
            condition_keywords=["composed", "eyes", "face"],
            min_intersection=2,
        ),
    )

    # Donor scan: should re-assert its own keyword (already carried).
    assert _run_scan([donor], [("composed", 0.8), ("eyes", 0.7), ("face", 0.6)]) == 0
    assert "vase" in read_xmp_tags(donor)

    # Weak scan: analyzer output shares only ONE condition tag ("composed")
    # with the donor, so "vase" must not be inherited.
    assert _run_scan([weak], [("composed", 0.8), ("rose", 0.5)]) == 0
    assert "vase" not in read_xmp_tags(weak)


def test_scan_overwrite_mode_does_not_reapply_feedback(tmp_path: Path) -> None:
    donor = _fake_image(tmp_path / "donor.png", "donor")
    write_xmp(donor, ["composed", "eyes", "face"])
    write_tag_sidecar(
        donor,
        user_keywords=["vase"],
        file_hash=compute_file_hash(donor),
        feedback=build_feedback_artifact(
            file_hash=compute_file_hash(donor),
            user_keywords=["vase"],
            condition_keywords=["composed", "eyes", "face"],
        ),
    )

    with (
        patch("imgtagplus.app.scan", return_value=[donor]),
        patch("imgtagplus.app.Monitor", return_value=_MonitorStub()),
        patch("imgtagplus.tagger.Tagger", return_value=FakeTagger(results=[("composed", 0.9)])),
    ):
        exit_code = run(_make_args(donor.parent, overwrite=True))
    assert exit_code == 0
    # Clean slate: only the analyzer's tag lands on the XMP.
    assert read_xmp_tags(donor) == ["composed"]
