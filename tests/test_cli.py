from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import imgtagplus.cli as cli


def test_start_server_daemon_skips_spawn_when_already_running(
    monkeypatch,
    tmp_path: Path,
) -> None:
    pid_file = tmp_path / "imgtagplus.pid"
    pid_file.write_text("123")

    monkeypatch.setattr(cli, "PID_FILE", pid_file)
    monkeypatch.setattr(cli, "_is_process_running", lambda pid: True)
    monkeypatch.setattr(cli, "stop_server_daemon", lambda: (_ for _ in ()).throw(AssertionError("should not stop")))
    monkeypatch.setattr(
        cli.subprocess,
        "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not spawn")),
    )

    cli.start_server_daemon()

    assert pid_file.read_text() == "123"


def test_start_server_daemon_spawns_and_records_pid(
    monkeypatch,
    tmp_path: Path,
) -> None:
    pid_file = tmp_path / "imgtagplus.pid"

    popen_calls: list[dict[str, object]] = []

    monkeypatch.setattr(cli, "PID_FILE", pid_file)
    monkeypatch.setattr(cli, "_is_process_running", lambda pid: False)
    monkeypatch.setattr(cli, "_wait_for_server_ready", lambda url: True)
    monkeypatch.setattr(cli.time, "sleep", lambda *_args, **_kwargs: None)

    def fake_popen(command, stdout, stderr, env, start_new_session):
        popen_calls.append(
            {
                "command": command,
                "stdout": stdout,
                "stderr": stderr,
                "env": env,
                "start_new_session": start_new_session,
            }
        )
        return SimpleNamespace(pid=456)

    monkeypatch.setattr(cli.subprocess, "Popen", fake_popen)

    cli.start_server_daemon()

    assert len(popen_calls) == 1
    assert "IMGTAGPLUS_FFSA" not in popen_calls[0]["env"]
    assert pid_file.read_text() == "456"


def test_restart_server_daemon_bounces_through_stop_and_start(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(cli, "stop_server_daemon", lambda: calls.append("stop"))
    monkeypatch.setattr(cli, "start_server_daemon", lambda: calls.append("start"))
    monkeypatch.setattr(cli.time, "sleep", lambda *_args, **_kwargs: None)

    cli.restart_server_daemon()

    assert calls == ["stop", "start"]
