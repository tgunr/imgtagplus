"""CRUD, persistence, precedence, and scan-time-feedback tests for the tag API.

Covers the taxonomy contract in ``CATEGORY_TAXONOMY.md``:
  * add / modify / delete both derived and user tags via the HTTP API
  * validation of axis names, value keys, and asset identifiers
  * persistence across a "restart" (fresh sidecar read, no in-memory carry-over)
  * the 4-level precedence order
  * derivations not being lost when a human edits an axis
  * the feedback artifact that downstream similar-file scans consume
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from imgtagplus.metadata import (
    compute_file_hash,
    read_tag_sidecar,
    tag_sidecar_path_for_image,
)
from imgtagplus.server import app, _tag_view
from imgtagplus.tags import (
    apply_feedback_at_scan,
    build_feedback_artifact,
    merge_sidecar,
    merge_tags,
    normalize_key,
)

AXES = ("process", "geometry_kind", "material_family", "machine_context", "output_intent")


def _derive(sidecar: dict) -> dict:
    """Write ``derived_tags`` straight to the sidecar, as a scan would."""
    from imgtagplus.metadata import write_tag_sidecar

    write_tag_sidecar(sidecar["path"], derived_tags=sidecar["derived"])
    return read_tag_sidecar(sidecar["path"])


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def image(tmp_path: Path) -> Path:
    """A fake (but non-empty) JPEG so hashing and stat() work."""
    path = tmp_path / "part.jpg"
    path.write_bytes(b"\xff\xd8\xff\xe0" + b"pixel-data" * 32)
    return path


def _get(client: TestClient, image: Path) -> dict:
    response = client.get("/api/tags", params={"path": str(image)})
    assert response.status_code == 200, response.text
    return response.json()["tags"]


def _put(client: TestClient, route: str, image: Path, **body: Any) -> Any:
    payload = {"path": str(image), **body}
    return client.put(f"/api/tags/{route}", json=payload)


# ---------------------------------------------------------------------------
# Taxonomy surface
# ---------------------------------------------------------------------------

def test_taxonomy_lists_all_five_axes(client: TestClient) -> None:
    response = client.get("/api/taxonomy")
    assert response.status_code == 200
    axes = [entry["axis"] for entry in response.json()["taxonomy"]["axes"]]
    assert axes == list(AXES)


def test_read_tags_on_untouched_image_is_empty(client: TestClient, image: Path) -> None:
    view = _get(client, image)
    assert view["axes"] == {}
    assert view["file_hash"] == compute_file_hash(image)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_missing_image_returns_404(client: TestClient, tmp_path: Path) -> None:
    response = client.get("/api/tags", params={"path": str(tmp_path / "absent.jpg")})
    assert response.status_code == 404


def test_unknown_axis_returns_400(client: TestClient, image: Path) -> None:
    assert _put(client, "user", image, axis="NOT_AN_AXIS", key="PROFILE_CUT").status_code == 400


def test_unknown_value_key_returns_400(client: TestClient, image: Path) -> None:
    assert _put(client, "user", image, axis="process", key="NOPE_NOT_A_VALUE").status_code == 400


def test_empty_key_returns_400(client: TestClient, image: Path) -> None:
    assert _put(client, "user", image, axis="process", key="").status_code == 400


@pytest.mark.parametrize(
    "spelling,expected",
    [
        ("process", "process"),
        ("PROCESS", "process"),
        ("Process", "process"),
        ("geometry-kind", "geometry_kind"),
        ("geometry kind", "geometry_kind"),
    ],
)
def test_axis_spelling_is_normalized(
    client: TestClient, image: Path, spelling: str, expected: str
) -> None:
    key = "OPEN_CONTOUR" if expected == "geometry_kind" else "PROFILE_CUT"
    response = _put(client, "user", image, axis=spelling, key=key)
    assert response.status_code == 200, response.text
    assert expected in _get(client, image)["axes"]


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def test_add_user_tag(client: TestClient, image: Path) -> None:
    response = _put(client, "user", image, axis="process", key="POCKET_MILL")
    assert response.status_code == 200
    axis = response.json()["tags"]["axes"]["process"]
    assert axis["key"] == "POCKET_MILL"
    assert axis["source"] == "user_confirmed"
    assert axis["confirmed_by"] == "user"


def test_modify_user_tag_replaces_previous(client: TestClient, image: Path) -> None:
    _put(client, "user", image, axis="process", key="POCKET_MILL")
    _put(client, "user", image, axis="process", key="ENGRAVE")
    assert _get(client, image)["axes"]["process"]["key"] == "ENGRAVE"


def test_delete_user_tag_removes_axis(client: TestClient, image: Path) -> None:
    _put(client, "user", image, axis="process", key="POCKET_MILL")
    response = _put(client, "delete", image, axis="process")
    assert response.status_code == 200
    assert _get(client, image)["axes"].get("process") is None


def test_delete_records_axis_in_sidecar(client: TestClient, image: Path) -> None:
    _put(client, "user", image, axis="process", key="POCKET_MILL")
    _put(client, "delete", image, axis="process")
    deletions = read_tag_sidecar(image)["user_deletions"]
    assert [d.get("axis") for d in deletions] == ["process"]


def test_delete_without_current_value_returns_400(client: TestClient, image: Path) -> None:
    assert _put(client, "delete", image, axis="material_family").status_code == 400


def test_reset_deletion_reopens_axis(client: TestClient, image: Path) -> None:
    _put(client, "user", image, axis="process", key="POCKET_MILL")
    _put(client, "delete", image, axis="process")
    response = client.post(
        "/api/tags/reset-deletion", json={"path": str(image), "axis": "process"}
    )
    assert response.status_code == 200
    assert read_tag_sidecar(image)["user_deletions"] == []


# ---------------------------------------------------------------------------
# Precedence (contract: user_confirmed > override > unvetted > derived)
# ---------------------------------------------------------------------------

def test_confirmed_user_tag_beats_derived() -> None:
    merged = merge_tags(
        derived_tags={"process": {"key": "ENGRAVE", "confidence": 0.9}},
        user_tags={"process": {"key": "POCKET_MILL", "confirmed_by": "user"}},
    )
    assert merged["process"]["key"] == "POCKET_MILL"
    assert merged["process"]["source"] == "user_confirmed"


def test_override_beats_unvetted_but_loses_to_confirmed() -> None:
    merged = merge_tags(
        derived_tags={"process": {"key": "ENGRAVE", "confidence": 0.9}},
        user_tags={"process": {"key": "PROFILE_CUT", "confirmed_by": "unvetted"}},
        user_overrides={"process": {"old": "PROFILE_CUT", "new": "POCKET_MILL"}},
    )
    assert merged["process"]["key"] == "POCKET_MILL"
    assert merged["process"]["source"] == "user_override"


def test_unvetted_beats_derived() -> None:
    merged = merge_tags(
        derived_tags={"process": {"key": "ENGRAVE", "confidence": 0.9}},
        user_tags={"process": {"key": "DRILL", "confirmed_by": "unvetted"}},
    )
    assert merged["process"]["source"] == "user_unvetted"


def test_below_threshold_derived_is_suppressed() -> None:
    merged = merge_tags(derived_tags={"process": {"key": "ENGRAVE", "confidence": 0.1}})
    assert merged == {}


def test_deletion_suppresses_re_emitted_derived_tag() -> None:
    """A human deletion is sticky: a rescan must not resurrect the axis."""
    derived = {"process": {"key": "ENGRAVE", "confidence": 0.95}}
    merged = merge_tags(
        derived_tags=derived,
        user_deletions=[{"axis": "process", "key": "ENGRAVE"}],
    )
    assert "process" not in merged


def test_bare_string_deletion_is_also_honoured() -> None:
    """Deletions written as plain axis strings must still suppress."""
    derived = {"process": {"key": "ENGRAVE", "confidence": 0.95}}
    assert "process" not in merge_tags(derived_tags=derived, user_deletions=["process"])


def test_empty_classification_is_empty_not_uncategorized() -> None:
    assert merge_tags() == {}


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def test_user_tags_survive_fresh_read(client: TestClient, image: Path) -> None:
    _put(client, "user", image, axis="material_family", key="WOOD")
    # Re-read through a cold path, as a new process would.
    assert _tag_view(image)["axes"]["material_family"]["key"] == "WOOD"


def test_sidecar_is_valid_json_with_owned_keys(client: TestClient, image: Path) -> None:
    _put(client, "user", image, axis="process", key="ENGRAVE")
    payload = json.loads(tag_sidecar_path_for_image(image).read_text())
    for key in (
        "schema_version",
        "file_hash",
        "filename",
        "derived_tags",
        "user_tags",
        "user_deletions",
        "user_overrides",
        "feedback_for_future_scans",
    ):
        assert key in payload, f"sidecar missing {key}"


def test_unknown_sidecar_keys_are_preserved(client: TestClient, image: Path) -> None:
    sidecar_path = tag_sidecar_path_for_image(image)
    sidecar_path.write_text(json.dumps({"custom_plugin_key": {"keep": "me"}}))
    _put(client, "user", image, axis="process", key="ENGRAVE")
    payload = json.loads(sidecar_path.read_text())
    assert payload["custom_plugin_key"] == {"keep": "me"}


def test_user_edit_does_not_lose_derived_tags(client: TestClient, image: Path) -> None:
    """The analyzer's original result must survive a human edit."""
    from imgtagplus.metadata import write_tag_sidecar

    write_tag_sidecar(
        image, derived_tags={"process": {"key": "PROFILE_CUT", "confidence": 0.8}}
    )
    _put(client, "user", image, axis="material_family", key="WOOD")
    derived = read_tag_sidecar(image)["derived_tags"]
    assert derived["process"]["key"] == "PROFILE_CUT"


def test_xmp_tags_are_not_clobbered(client: TestClient, image: Path) -> None:
    from imgtagplus.metadata import read_xmp_tags, write_xmp

    write_xmp(image, ["ExistingKeyword"])
    _put(client, "user", image, axis="process", key="ENGRAVE")
    assert "ExistingKeyword" in read_xmp_tags(image)


# ---------------------------------------------------------------------------
# Feedback artifact + influence on subsequent scans
# ---------------------------------------------------------------------------

def test_feedback_artifact_records_human_actions(client: TestClient, image: Path) -> None:
    from imgtagplus.metadata import write_tag_sidecar

    write_tag_sidecar(
        image,
        derived_tags={
            "process": {"key": "ENGRAVE", "confidence": 0.9},
            "material_family": {"key": "WOOD", "confidence": 0.8},
        },
    )
    _put(client, "user", image, axis="geometry_kind", key="OPEN_CONTOUR")
    _put(client, "delete", image, axis="material_family")

    feedback = read_tag_sidecar(image)["feedback_for_future_scans"]
    assert feedback["user_confirmed_axes"] == {"geometry_kind": "OPEN_CONTOUR"}
    assert "material_family" in feedback["user_deleted_axes"]
    assert "similar_file_hash_pattern" in feedback
    assert feedback["applied_at_utc"]


def test_feedback_hash_pattern_is_prefix_bucketed() -> None:
    artifact = build_feedback_artifact(
        file_hash="a1b2c3d4e5f6",
        user_tags={"process": {"key": "ENGRAVE", "confirmed_by": "user"}},
    )
    pattern = artifact["similar_file_hash_pattern"]
    assert pattern == "A1B2C3D4*"
    assert normalize_key("a1b2c3d4e5f6").startswith(pattern.rstrip("*"))


def test_feedback_with_no_human_input_is_empty() -> None:
    assert build_feedback_artifact(file_hash="a1b2c3d4") == {}


def test_scan_time_feedback_honours_deletion_and_confirmation() -> None:
    feedback = {
        "user_confirmed_axes": {"geometry_kind": "OPEN_CONTOUR"},
        "user_deleted_axes": ["material_family"],
        "user_overrides": {},
    }
    derived = {
        "process": {"key": "ENGRAVE", "confidence": 0.9},
        "geometry_kind": {"key": "TEXT_BLOCK", "confidence": 0.9},
        "material_family": {"key": "WOOD", "confidence": 0.9},
    }
    resolved = apply_feedback_at_scan(feedback, derived)
    assert resolved["geometry_kind"]["key"] == "OPEN_CONTOUR"
    assert resolved["geometry_kind"]["source"] == "user_confirmed"
    assert "material_family" not in resolved


def test_scan_time_feedback_without_artifact_passes_derived_through() -> None:
    derived = {"process": {"key": "ENGRAVE", "confidence": 0.9}}
    assert apply_feedback_at_scan({}, derived)["process"]["key"] == "ENGRAVE"


def test_rescan_does_not_resurrect_deleted_axis(client: TestClient, image: Path) -> None:
    """End-to-end: delete an axis, re-derive it, and it stays deleted."""
    from imgtagplus.metadata import write_tag_sidecar
    from imgtagplus.app import _refresh_scan_feedback

    write_tag_sidecar(
        image, derived_tags={"process": {"key": "ENGRAVE", "confidence": 0.9}}
    )
    _put(client, "delete", image, axis="process")

    # A rescan re-emits the same derived tag...
    write_tag_sidecar(
        image,
        derived_tags={"process": {"key": "ENGRAVE", "confidence": 0.95}},
    )
    _refresh_scan_feedback(image)
    # ...but the human deletion still wins.
    assert _tag_view(image)["axes"].get("process") is None


def test_merge_sidecar_shape_matches_api(client: TestClient, image: Path) -> None:
    _put(client, "user", image, axis="process", key="ENGRAVE")
    assert merge_sidecar(read_tag_sidecar(image))["axes"]["process"]["key"] == "ENGRAVE"
