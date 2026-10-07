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
async def test_browse_directory_defaults_to_configured_dir(
    monkeypatch, tmp_path: Path
) -> None:
    default_dir = tmp_path / "samples"
    default_dir.mkdir()
    monkeypatch.setattr(server, "_check_rate_limit", lambda *a: True)
    monkeypatch.setattr(server, "_default_dir", lambda: str(default_dir))

    result = await server.browse_directory(request=None, path=None)

    assert result["current_path"] == str(default_dir)
    assert result["sandbox"] is False


def test_default_dir_prefers_env_override(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("IMGTAGPLUS_DEFAULT_DIR", str(tmp_path))
    assert server._default_dir() == str(tmp_path)


def test_default_dir_falls_back_to_dev_default(monkeypatch) -> None:
    monkeypatch.delenv("IMGTAGPLUS_DEFAULT_DIR", raising=False)
    assert server._default_dir() == server.DEV_DEFAULT_DIR
