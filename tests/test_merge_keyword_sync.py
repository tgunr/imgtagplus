"""Verify /api/tags/keywords (replacement) stays in sync with feedback user_keywords."""
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from imgtagplus.server import app
from imgtagplus.metadata import read_tag_sidecar, read_xmp_tags


@pytest.fixture(autouse=True)
def _isolate_rate_limiter():
    from imgtagplus import server as s
    s._rate_limits.clear(); yield; s._rate_limits.clear()


def _img(p, marker):
    p.write_bytes(b"\xff\xd8" + b"\xff\xe0\x00\x10JFIF\x00" + marker.encode() + b"\xff\xd9")
    return p


def test_replacement_editor_does_not_resurrect_deleted_keyword(tmp_path):
    client = TestClient(app)
    img = _img(tmp_path / "a.png", "a")

    # Human teaches "vase" via the additive feedback endpoint.
    r = client.put("/api/tags/keyword", json={"path": str(img), "keyword": "vase"})
    assert r.status_code == 200, r.text
    assert read_tag_sidecar(img)["user_keywords"] == ["vase"]

    # Human now uses main's replacement editor and DROPS "vase".
    r2 = client.put("/api/tags/keywords", json={"path": str(img), "tags": ["face", "eyes"]})
    assert r2.status_code == 200, r2.text

    # The sidecar must forget "vase", otherwise the next scan resurrects it.
    assert "vase" not in read_xmp_tags(img)
    user_keywords = read_tag_sidecar(img)["user_keywords"]
    assert "vase" not in user_keywords, user_keywords
    # "face"/"eyes" were newly typed by the human in that same edit, so they
    # legitimately become feedback inputs.
    assert user_keywords == ["eyes", "face"]
    fb = read_tag_sidecar(img)["feedback_for_future_scans"]
    assert "vase" not in fb.get("user_added_keywords", [])
    assert set(fb.get("user_added_keywords", [])) == {"eyes", "face"}


def test_replacement_editor_records_newly_added_keyword_as_feedback(tmp_path):
    client = TestClient(app)
    img = _img(tmp_path / "b.png", "b")
    client.put("/api/tags/keywords", json={"path": str(img), "tags": ["face", "flowers"]})

    sidecar = read_tag_sidecar(img)
    # Both tags were newly added by a human, so both become feedback inputs.
    assert sidecar["user_keywords"] == ["face", "flowers"]
    assert set(sidecar["feedback_for_future_scans"]["user_added_keywords"]) == {"face", "flowers"}


def test_scan_does_not_resurrect_keyword_deleted_via_replacement_editor(tmp_path):
    """End-to-end guard for the merge hazard.

    ``/api/tags/keywords`` uses replacement semantics with ``overwrite=True``.
    Before the sidecar sync it never updated ``user_keywords``, so a keyword the
    human deleted there was still re-applied by the next scan from the stale
    sidecar value.
    """
    from unittest.mock import MagicMock, patch

    from imgtagplus.app import run
    from test_app_runtime import FakeTagger, _make_args

    client = TestClient(app)
    img = _img(tmp_path / "c.png", "c")

    client.put("/api/tags/keyword", json={"path": str(img), "keyword": "vase"})
    assert "vase" in read_xmp_tags(img)

    client.put("/api/tags/keywords", json={"path": str(img), "tags": ["face", "eyes"]})
    assert "vase" not in read_xmp_tags(img)

    class _MonitorStub:
        def start(self):
            return None

        def stop(self):
            stub = MagicMock()
            stub.summary.return_value = "monitor stub"
            return stub

    with (
        patch("imgtagplus.app.scan", return_value=[img]),
        patch("imgtagplus.app.Monitor", return_value=_MonitorStub()),
        patch("imgtagplus.tagger.Tagger", return_value=FakeTagger(results=[("face", 0.8), ("eyes", 0.7)])),
    ):
        assert run(_make_args(tmp_path)) == 0

    assert "vase" not in read_xmp_tags(img), read_xmp_tags(img)
