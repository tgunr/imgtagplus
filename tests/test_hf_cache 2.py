from __future__ import annotations

import os
from pathlib import Path

from imgtagplus import hfcache


def test_is_usable_rejects_dangling_symlink(tmp_path: Path) -> None:
    link = tmp_path / "huggingface"
    link.symlink_to(tmp_path / "unmounted-volume")

    assert hfcache._is_usable(link) is False


def test_is_usable_rejects_uncreatable_parent(tmp_path: Path) -> None:
    readonly = tmp_path / "volumes"
    readonly.mkdir()
    readonly.chmod(0o500)
    try:
        assert hfcache._is_usable(readonly / "AI" / "cache" / "huggingface") is False
    finally:
        readonly.chmod(0o700)


def test_point_hf_caches_at_sets_every_env_var(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "cache" / "imgtagplus"

    returned = hfcache.point_hf_caches_at(root)

    assert returned == root
    assert root.is_dir()
    assert os.environ["HF_HOME"] == str(root)
    assert os.environ["HF_HUB_CACHE"] == str(root)
    assert os.environ["HUGGINGFACE_HUB_CACHE"] == str(root)
    assert os.environ["HF_MODULES_CACHE"] == str(root / "modules")
    assert os.environ["HF_XET_CACHE"] == str(root / "xet")


def test_ensure_hf_cache_env_redirects_when_configured_root_is_broken(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    broken = tmp_path / "HuggingFace"  # dangling symlink mimics an unmounted volume
    broken.symlink_to(tmp_path / "unmounted-volume")
    monkeypatch.setenv("HF_HOME", str(broken))

    resolved = hfcache.ensure_hf_cache_env()

    assert resolved == tmp_path / "xdg" / "imgtagplus"
    assert os.environ["HF_HOME"] == str(tmp_path / "xdg" / "imgtagplus")


def test_ensure_hf_cache_env_ignores_shell_home_and_uses_app_cache(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    mounted = tmp_path / "Volumes" / "AI" / "cache" / "huggingface"
    mounted.mkdir(parents=True)
    monkeypatch.setenv("HF_HOME", str(mounted))

    resolved = hfcache.ensure_hf_cache_env()

    assert resolved == tmp_path / "xdg" / "imgtagplus"
    assert os.environ["HF_HOME"] == str(tmp_path / "xdg" / "imgtagplus")
