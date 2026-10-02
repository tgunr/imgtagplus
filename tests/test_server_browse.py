from __future__ import annotations

from pathlib import Path

import pytest

import imgtagplus.server as server


@pytest.mark.asyncio
async def test_browse_directory_lists_child_directories(
    monkeypatch, tmp_path: Path
) -> None:
    root_dir = tmp_path / "photos"
    hidden_dir = tmp_path / ".hidden"
    image_file = tmp_path / "image.jpg"
    root_dir.mkdir()
    hidden_dir.mkdir()
    image_file.write_bytes(b"image")

    monkeypatch.setattr(server, "_check_rate_limit", lambda *a: True)

    result = await server.browse_directory(request=None, path=str(tmp_path))

    assert result["current_path"] == str(tmp_path)
    assert result["sandbox"] is False
    assert result["items"][0]["name"] == ".."
    assert result["items"][1:] == [
        {"name": "photos", "path": str(root_dir), "is_dir": True}
    ]


@pytest.mark.asyncio
async def test_browse_directory_defaults_to_home(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(server, "_check_rate_limit", lambda *a: True)
    monkeypatch.setattr(server.Path, "home", lambda: tmp_path)

    result = await server.browse_directory(request=None, path=None)

    assert result["current_path"] == str(tmp_path)
    assert result["sandbox"] is False
