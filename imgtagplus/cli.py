"""CLI entry points for both the interactive manager and headless tagging mode."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import psutil

from imgtagplus import __version__

_PID_SUFFIX = str(os.getuid()) if hasattr(os, "getuid") else "default"
PID_FILE = Path(tempfile.gettempdir()) / f"imgtagplus_server_{_PID_SUFFIX}.pid"
STATE_FILE = Path(tempfile.gettempdir()) / f"imgtagplus_server_{_PID_SUFFIX}.json"

def _get_server_pid() -> int | None:
    """Return the last recorded daemon PID, or None if the pid file is missing/invalid."""
    if PID_FILE.exists():
        try:
            return int(PID_FILE.read_text().strip())
        except ValueError:
            return None
    return None


def _normalize_server_config(ffsa: bool = False, sandbox_dir: str | None = None) -> dict[str, object]:
    """Return a stable server-config payload for persistence and comparisons."""
    return {
        "ffsa": bool(ffsa),
        "sandbox_dir": str(sandbox_dir) if sandbox_dir else None,
    }


def _load_server_config() -> dict[str, object] | None:
    """Return the persisted server mode, if present and valid."""
    if not STATE_FILE.exists():
        return None

    try:
        payload = json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return None

    return _normalize_server_config(
        ffsa=bool(payload.get("ffsa", False)),
        sandbox_dir=payload.get("sandbox_dir"),
    )


def _save_server_config(ffsa: bool = False, sandbox_dir: str | None = None) -> None:
    """Persist the active server mode so restart operations can reuse it."""
    STATE_FILE.write_text(json.dumps(_normalize_server_config(ffsa=ffsa, sandbox_dir=sandbox_dir)))


def _clear_server_config() -> None:
    """Remove any persisted server mode state."""
    if STATE_FILE.exists():
        STATE_FILE.unlink()


def _is_process_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _is_imgtagplus_server_process(pid: int) -> bool:
    """Confirm the stored PID still belongs to an ImgTagPlus server before signaling it."""
    try:
        process = psutil.Process(pid)
        cmdline = " ".join(process.cmdline())
    except (psutil.Error, OSError):
        return False

    return "imgtagplus" in cmdline and "server.py" in cmdline


def _wait_for_server_ready(url: str, attempts: int = 20, delay: float = 0.25) -> bool:
    """Poll the health endpoint so the CLI only reports success once the UI can answer requests."""
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError):
            time.sleep(delay)
    return False

def start_server_daemon(ffsa: bool = False, sandbox_dir: str | None = None) -> None:
    """Spawn the Web UI server in a detached process and persist its PID for later control."""
    pid = _get_server_pid()
    desired_config = _normalize_server_config(ffsa=ffsa, sandbox_dir=sandbox_dir)
    if pid and _is_process_running(pid):
        current_config = _load_server_config()
        if current_config == desired_config:
            print(f"Server is already running (PID {pid}).")
            return

        print("Server is already running in a different mode. Restarting with the selected mode...")
        stop_server_daemon()
        time.sleep(1)
        
    print("Starting ImgTagPlus Web UI...")
    
    # We run the uvicorn server via our server module entrypoint
    # For a robust daemon, we use subprocess.Popen
    server_script = Path(__file__).parent / "server.py"
    
    # Ensure .imgtagplus directory exists
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    # Start process
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).parent.parent)
    if ffsa:
        env["IMGTAGPLUS_FFSA"] = "1"
    if sandbox_dir:
        env["IMGTAGPLUS_SANDBOX_DIR"] = str(sandbox_dir)
    
    # We use python -m uvicorn or directly python server.py
    proc = subprocess.Popen(
        [sys.executable, str(server_script)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
        start_new_session=True # Detach from terminal
    )
    
    # Persist the PID immediately so later stop/restart commands can recover even across shells.
    PID_FILE.write_text(str(proc.pid))
    _save_server_config(ffsa=ffsa, sandbox_dir=sandbox_dir)
    if _wait_for_server_ready("http://127.0.0.1:5000/health"):
        print(f"Server started on http://127.0.0.1:5000 (PID {proc.pid})")
        return

    print(f"Server process started (PID {proc.pid}), but /health did not become ready in time.")

def stop_server_daemon() -> None:
    """Stop the background Web UI server, but only if the pid file still points at our process."""
    pid = _get_server_pid()
    if not pid or not _is_process_running(pid):
        print("Server is not currently running.")
        if PID_FILE.exists():
            PID_FILE.unlink()
        _clear_server_config()
        return

    if not _is_imgtagplus_server_process(pid):
        print("PID file does not point to an ImgTagPlus server. Refusing to stop it.")
        if PID_FILE.exists():
            PID_FILE.unlink()
        _clear_server_config()
        return

    print(f"Stopping Server (PID {pid})...")
    try:
        os.kill(pid, signal.SIGTERM)
        # Wait a moment
        time.sleep(1)
        if _is_process_running(pid):
            os.kill(pid, signal.SIGKILL)
    except OSError as e:
        print(f"Error stopping process: {e}")
        
    if PID_FILE.exists():
        PID_FILE.unlink()
    _clear_server_config()
    print("Server stopped.")

def restart_server_daemon(ffsa: bool | None = None, sandbox_dir: str | None = None) -> None:
    """Bounce the background server through the same guarded stop/start path used elsewhere."""
    saved_config = _load_server_config() or _normalize_server_config()
    target_ffsa = bool(saved_config["ffsa"]) if ffsa is None else ffsa
    target_sandbox_dir = saved_config["sandbox_dir"] if sandbox_dir is None else sandbox_dir
    stop_server_daemon()
    time.sleep(1)
    start_server_daemon(ffsa=target_ffsa, sandbox_dir=target_sandbox_dir)

def print_menu():
    print("\n" + "="*40)
    print("  ImgTagPlus Interactive Manager")
    print("="*40)
    
    pid = _get_server_pid()
    is_running = pid and _is_process_running(pid)
    
    status = "\033[92mRunning\033[0m" if is_running else "\033[91mStopped\033[0m"
    print(f"  Web UI Status: {status}")
    if is_running:
        print("  URL: http://127.0.0.1:5000")
        server_config = _load_server_config() or _normalize_server_config()
        mode_label = "Full File Access" if server_config["ffsa"] else "Sandbox Access"
        print(f"  Mode: {mode_label}")
        if server_config["sandbox_dir"]:
            print(f"  Sandbox Dir: {server_config['sandbox_dir']}")
        
    print("-" * 40)
    print("  [1] Start Web UI Server (Sandbox Access)")
    print("  [2] Start Web UI Server (Full File Access)")
    print("  [3] Stop Web UI Server")
    print("  [4] Restart Web UI Server")
    print("  [5] Run Tagging Task (Headless Prompt)")
    print("  [0] Exit")
    print("="*40)

def run_interactive_menu():
    """Interactive CLI menu loop.

    The menu is intentionally thin: once it has collected a few prompts, it reuses the same
    `imgtagplus.app.run()` entry point as the non-interactive CLI to keep behavior aligned.
    """
    while True:
        print_menu()
        choice = input("\nSelect an option: ").strip()
        
        if choice == '1':
            start_server_daemon(ffsa=False)
        elif choice == '2':
            start_server_daemon(ffsa=True)
        elif choice == '3':
            stop_server_daemon()
        elif choice == '4':
            restart_server_daemon()
        elif choice == '5':
            print("\n[Headless Tagging Task]")
            input_path = input("Enter directory path to scan: ").strip()
            if not input_path:
                print("Operation cancelled.")
                continue
                
            from imgtagplus.profiler import AVAILABLE_MODELS
            print("\nAvailable Models:")
            for m in AVAILABLE_MODELS.values():
                print(f" - {m['id']} ({m['name']})")
                
            model_id = input("\nEnter model ID (default 'clip'): ").strip()
            if not model_id:
                model_id = "clip"

            output_dir_str = input("\nOutput directory for XMP files (leave blank for alongside source): ").strip()
            output_dir = Path(output_dir_str) if output_dir_str else None
                
            # Reuse the headless execution path so the menu and argparse modes stay in sync.
            args = argparse.Namespace(
                input=Path(input_path),
                recursive=True,
                threshold=0.25,
                max_tags=20,
                silent=False,
                continue_on_error=True,
                log_file=None,
                model_dir=None,
                model_id=model_id,
                output_dir=output_dir
            )
            
            from imgtagplus.app import run
            run(args)
            input("\nPress Enter to return to menu...")
            
        elif choice == '0' or choice.lower() in ('q', 'quit', 'exit'):
            print("Goodbye!")
            break
        else:
            print("Invalid choice. Please try again.")

def build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser."""
    p = argparse.ArgumentParser(
        prog="imgtagplus",
        description=(
            "ImgTagPlus — Local AI image tagger and Web UI Manager.\n\n"
            "Run without arguments for an interactive menu:\n"
            "  $ imgtagplus\n\n"
            "Manage Web server:\n"
            "  $ imgtagplus --start-server\n"
            "  $ imgtagplus --stop-server\n\n"
            "Or run headless tagging:\n"
            "  $ imgtagplus -i ./photos/ --model-id florence-2-base -r"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    p.add_argument(
        "-V", "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    # ── Server Management ──────────────────────────────────────────────────
    p.add_argument("--start-server", action="store_true", help="Start the Web UI server in the background")
    p.add_argument("--stop-server", action="store_true", help="Stop the Web UI server")
    p.add_argument("--restart-server", action="store_true", help="Restart the Web UI server")
    p.add_argument(
        "--full-file-system-access",
        "--ffsa",
        action="store_true",
        help="Allow Web UI file picker to access the entire file system",
    )
    p.add_argument(
        "--sandbox",
        action="store_true",
        default=True,
        help="Run Web UI in sandbox mode (default). File picker restricted to sandbox directory.",
    )
    p.add_argument("--sandbox-dir", type=Path, default=None, help="Custom sandbox directory path (default: ./sandbox)")

    # ── Input / Output (Headless) ──────────────────────────────────────────
    p.add_argument(
        "-i", "--input",
        type=Path,
        default=None,
        help="Path to a single image or a directory of images.",
    )
    p.add_argument(
        "-r", "--recursive",
        action="store_true",
        default=False,
        help="Scan directories recursively.",
    )
    p.add_argument(
        "-o", "--output-dir",
        type=Path,
        default=None,
        help="Directory for XMP sidecar files. Default: alongside each source image.",
    )

    # ── Model / Tagging ────────────────────────────────────────────────────
    p.add_argument(
        "--model-id",
        type=str,
        default="clip",
        help="Model ID to use (e.g., 'clip', 'florence-2-base'). Default: 'clip'.",
    )
    p.add_argument(
        "-t", "--threshold",
        type=float,
        default=0.25,
        help="Minimum confidence score to keep a tag (default: 0.25).",
    )
    p.add_argument(
        "-n", "--max-tags",
        type=int,
        default=20,
        help="Maximum number of tags per image (default: 20).",
    )
    p.add_argument(
        "--model-dir",
        type=Path,
        default=None,
        help="Directory for cached model files (default: ~/.cache/imgtagplus).",
    )

    # ── Execution mode ─────────────────────────────────────────────────────
    p.add_argument(
        "--overwrite",
        action="store_true",
        default=False,
        help="Overwrite existing tags instead of merging with them.",
    )
    p.add_argument(
        "-s", "--silent",
        action="store_true",
        default=False,
        help="Run without interactive prompts (only warnings/errors to console).",
    )
    p.add_argument(
        "-c", "--continue-on-error",
        action="store_true",
        default=False,
        help="Skip images that cause errors instead of stopping.",
    )
    p.add_argument(
        "--input-timeout",
        type=int,
        default=30,
        help="Seconds to wait before auto-continuing on error.",
    )
    p.add_argument(
        "--no-vector",
        action="store_true",
        default=False,
        help="Skip SVG/DXF vector drawings instead of rasterizing and tagging them.",
    )
    p.add_argument(
        "--vector-px",
        type=int,
        default=1024,
        help="Longest raster side (px) when converting SVG/DXF drawings (default: 1024).",
    )

    # ── Logging ────────────────────────────────────────────────────────────
    p.add_argument(
        "-l", "--log-file",
        type=Path,
        default=None,
        help="Custom log file path (default: imgtagplus_TIMESTAMP.log).",
    )

    p.add_argument(
        "--no-tui",
        action="store_true",
        default=False,
        help="Use the plain text menu instead of the Textual TUI.",
    )

    return p

def main(argv: list[str] | None = None) -> None:
    """Dispatch to the menu, server lifecycle commands, or headless tagging.

    Running with no args is a user-facing shortcut into the interactive manager; any explicit
    flags bypass the menu and behave like a traditional CLI.
    """
    _raw_argv = sys.argv[1:] if argv is None else list(argv)
    _interactive_flags = {a for a in _raw_argv if a not in ("--no-tui",)}
    _is_interactive = not _interactive_flags

    if _is_interactive:
        # Keep Ctrl+C from dumping a traceback when the user is just backing out of the menu.
        no_tui = os.environ.get("IMGTAGPLUS_NO_TUI", "").strip() not in ("", "0", "false", "False")
        if not no_tui:
            no_tui = "--no-tui" in _raw_argv
        if not no_tui:
            try:
                from imgtagplus.tui import launch_tui
                launch_tui()
                sys.exit(0)
            except ImportError:
                pass  # textual not installed → fall through to plain menu
        try:
            run_interactive_menu()
        except KeyboardInterrupt:
            print("\nExiting...")
        sys.exit(0)

    parser = build_parser()
    args = parser.parse_args(argv)

    # Server flags are handled first so they never fall through into a tagging run.
    if args.start_server:
        start_server_daemon(
            ffsa=args.full_file_system_access,
            sandbox_dir=str(args.sandbox_dir) if args.sandbox_dir else None
        )
        sys.exit(0)
    elif args.stop_server:
        stop_server_daemon()
        sys.exit(0)
    elif args.restart_server:
        restart_server_daemon(
            ffsa=True if args.full_file_system_access else None,
            sandbox_dir=str(args.sandbox_dir) if args.sandbox_dir else None,
        )
        sys.exit(0)

    # Everything else is treated as a headless tagging invocation.
    if args.input is None:
        parser.error("The -i/--input argument is required for headless tagging.")

    # Lazy import to keep CLI parsing fast.
    from imgtagplus.app import run  # noqa: E402
    sys.exit(run(args))
