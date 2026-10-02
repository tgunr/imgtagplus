from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import imgtagplus.server as server
from imgtagplus.metadata import write_xmp


@pytest.fixture
def image_client(monkeypatch, tmp_path: Path):
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    monkeypatch.setattr(server, "_check_rate_limit", lambda *a: True)

    return TestClient(server.app), work_dir


def test_list_images_returns_supported_images_and_tags(image_client) -> None:
    client, work_dir = image_client
    photos_dir = work_dir / "photos"
    photos_dir.mkdir()

    tagged_image = photos_dir / "alpha.jpg"
    untagged_image = photos_dir / "beta.png"
    ignored_file = photos_dir / "notes.txt"
    tagged_image.write_bytes(b"jpeg-bytes")
    untagged_image.write_bytes(b"png-bytes")
    ignored_file.write_text("ignore me", encoding="utf-8")
    write_xmp(tagged_image, ["sunset", "landscape"])

    response = client.get("/api/images", params={"path": str(photos_dir)})

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert payload["has_more"] is False
    assert [item["name"] for item in payload["images"]] == ["alpha.jpg", "beta.png"]
    assert payload["images"][0]["tags"] == ["landscape", "sunset"]
    assert payload["images"][0]["xmp_exists"] is True
    assert payload["images"][1]["tags"] == []
    assert payload["images"][1]["xmp_exists"] is False


def test_list_images_supports_pagination(image_client) -> None:
    client, work_dir = image_client
    photos_dir = work_dir / "photos"
    photos_dir.mkdir()

    for name in ("alpha.jpg", "beta.jpg", "gamma.jpg"):
        (photos_dir / name).write_bytes(b"image")

    response = client.get(
        "/api/images",
        params={"path": str(photos_dir), "offset": 1, "limit": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3
    assert payload["offset"] == 1
    assert payload["limit"] == 1
    assert payload["has_more"] is True
    assert [item["name"] for item in payload["images"]] == ["beta.jpg"]


def test_get_image_file_serves_supported_image(image_client) -> None:
    client, work_dir = image_client
    image_path = work_dir / "photo.jpg"
    image_path.write_bytes(b"binary-image")

    response = client.get("/api/image", params={"path": str(image_path)})

    assert response.status_code == 200
    assert response.content == b"binary-image"
    assert response.headers["content-type"].startswith("image/jpeg")


def test_get_image_file_rejects_non_image_paths(image_client) -> None:
    client, work_dir = image_client
    text_path = work_dir / "notes.txt"
    text_path.write_text("nope", encoding="utf-8")

    response = client.get("/api/image", params={"path": str(text_path)})

    assert response.status_code == 400
    assert response.json() == {"detail": "Unsupported image type"}
