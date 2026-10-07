from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import imgtagplus.server as server
from imgtagplus.metadata import read_xmp_tags, write_xmp


@pytest.fixture
def client(monkeypatch) -> TestClient:
    monkeypatch.setattr(server, "_check_rate_limit", lambda *a: True)
    return TestClient(server.app)


def _put_tags(client: TestClient, image: Path, tags) -> object:
    return client.put("/api/tags/keywords", json={"path": str(image), "tags": tags})


def test_put_keywords_adds_tags_to_new_sidecar(client: TestClient, tmp_path: Path) -> None:
    image = tmp_path / "alpha.jpg"
    image.write_bytes(b"jpeg-bytes")

    response = _put_tags(client, image, ["sunset", "beach"])

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["tags"] == ["beach", "sunset"]
    assert payload["tag_count"] == 2
    assert read_xmp_tags(image) == ["beach", "sunset"]
    # Canonical sidecar is created next to the image.
    assert (tmp_path / "alpha.jpg.xmp").exists()


def test_put_keywords_replaces_existing_tags(client: TestClient, tmp_path: Path) -> None:
    """modify and delete are the same replacement write: the submitted list wins."""
    image = tmp_path / "alpha.jpg"
    image.write_bytes(b"jpeg-bytes")
    write_xmp(image, ["sunset", "landscape"])

    # Modify: rename one keyword.
    response = _put_tags(client, image, ["sunset", "orange_sky"])
    assert response.status_code == 200
    assert read_xmp_tags(image) == ["orange_sky", "sunset"]

    # Delete: drop a keyword.
    response = _put_tags(client, image, ["sunset"])
    assert response.status_code == 200
    assert response.json()["tags"] == ["sunset"]
    assert read_xmp_tags(image) == ["sunset"]

    # Delete all: empty list is legal.
    response = _put_tags(client, image, [])
    assert response.status_code == 200
    assert response.json()["tags"] == []
    assert read_xmp_tags(image) == []


def test_put_keywords_dedupes_trims_and_sorts(client: TestClient, tmp_path: Path) -> None:
    image = tmp_path / "alpha.jpg"
    image.write_bytes(b"jpeg-bytes")

    response = _put_tags(client, image, ["  beach ", "beach", "", "sunset   "])

    assert response.status_code == 200
    assert response.json()["tags"] == ["beach", "sunset"]


def test_put_keywords_replaces_legacy_sidecar_tags(client: TestClient, tmp_path: Path) -> None:
    """After the edit, reads serve the canonical sidecar holding the submitted list."""
    image = tmp_path / "alpha.jpg"
    image.write_bytes(b"jpeg-bytes")
    write_xmp(image, ["old", "legacy"])

    legacy = tmp_path / "alpha.xmp"
    legacy.write_bytes((tmp_path / "alpha.jpg.xmp").read_bytes())
    (tmp_path / "alpha.jpg.xmp").unlink()

    response = _put_tags(client, image, ["new"])

    assert response.status_code == 200
    assert response.json()["tags"] == ["new"]
    assert read_xmp_tags(image) == ["new"]


def test_put_keywords_images_in_nested_directories(client: TestClient, tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    image = nested / "alpha.jpg"
    image.write_bytes(b"jpeg-bytes")

    response = _put_tags(client, image, ["deep"])

    assert response.status_code == 200
    assert read_xmp_tags(image) == ["deep"]


def test_put_keywords_rejects_bad_payloads(client: TestClient, tmp_path: Path) -> None:
    image = tmp_path / "alpha.jpg"
    image.write_bytes(b"jpeg-bytes")
    assert _put_tags(client, image, ["fine"]).status_code == 200  # sanity

    response = client.put(
        "/api/tags/keywords", json={"path": str(image), "tags": "not-a-list"}
    )
    assert response.status_code == 400
    assert "list of strings" in response.json()["detail"]

    response = client.put(
        "/api/tags/keywords", json={"path": str(image), "tags": [1, 2]}
    )
    assert response.status_code == 400

    response = client.put("/api/tags/keywords", json={})
    assert response.status_code == 400
    assert "tags must be a list of strings" in response.json()["detail"]

    # Valid tags but a missing path resolves to Image does not exist.
    response = client.put(
        "/api/tags/keywords", json={"path": str(tmp_path / "absent.jpg"), "tags": ["x"]}
    )
    assert response.status_code == 404


def test_put_keywords_unknown_image_404(client: TestClient, tmp_path: Path) -> None:
    response = _put_tags(client, tmp_path / "absent.jpg", ["x"])
    assert response.status_code == 404
