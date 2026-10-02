"""Textual TUI for the ImgTagPlus interactive manager.

Replaces the plain print/input loop with a keyboard-driven terminal UI styled
after the shadcn/basecoat-ui neutral zinc palette used in the web frontend.

Entry point: ``launch_tui()``
"""

from __future__ import annotations

import argparse
import threading
from pathlib import Path

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.css.query import NoMatches
from textual.message import Message
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    Log,
    ProgressBar,
    Rule,
    Select,
    Static,
    Switch,
)

from imgtagplus import __version__
from imgtagplus.cli import (
    _get_server_pid,
    _is_process_running,
    restart_server_daemon,
    start_server_daemon,
    stop_server_daemon,
)
from imgtagplus.profiler import AVAILABLE_MODELS


# ── Helper ─────────────────────────────────────────────────────────────────

def _server_status() -> tuple[bool, str | None]:
    """Return (is_running, url_or_none)."""
    pid = _get_server_pid()
    if pid and _is_process_running(pid):
        return True, "http://127.0.0.1:5000"
    return False, None


# ── Messages ────────────────────────────────────────────────────────────────

class ProgressUpdate(Message):
    def __init__(self, current: int, total: int, message: str) -> None:
        super().__init__()
        self.current = current
        self.total = total
        self.message = message


class TaggingComplete(Message):
    def __init__(self, exit_code: int) -> None:
        super().__init__()
        self.exit_code = exit_code


# ── Server Status Card ───────────────────────────────────────────────────────

class ServerStatusCard(Static):
    """Compact one- or two-line server status display."""

    def compose(self) -> ComposeResult:
        yield Label("Web UI Server", id="status-title")
        yield Label("", id="status-detail")

    def on_mount(self) -> None:
        self.refresh_status()

    def refresh_status(self) -> None:
        try:
            detail = self.query_one("#status-detail", Label)
        except NoMatches:
            return
        running, url = _server_status()
        if running:
            detail.update(f"[bold green]● Running[/bold green]  {url}")
        else:
            detail.update("[bold red]● Stopped[/bold red]")


# ── Dashboard Screen ─────────────────────────────────────────────────────────

class DashboardScreen(Screen):
    """Main dashboard — server controls + shortcut menu."""

    BINDINGS = [
        Binding("1", "start_server", show=False),
        Binding("2", "start_server", show=False),
        Binding("3", "stop_server", show=False),
        Binding("4", "restart_server", show=False),
        Binding("5", "open_tagging", "Tag Images", show=True),
        Binding("t", "open_tagging", show=False),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("q", "app.quit", "Quit", show=True),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        # Status card — fixed height, always visible at top
        yield ServerStatusCard(id="server-status-card")
        # Action panel — expands to fill remaining space
        with Vertical(id="action-panel"):
            yield Label("Actions", id="action-title")
            yield Button("Start Web UI Server",             id="btn-action-1", classes="action-btn")
            yield Button("Stop Web UI Server",              id="btn-action-3", classes="action-btn")
            yield Button("Restart Web UI Server",           id="btn-action-4", classes="action-btn")
            yield Rule(id="action-rule")
            yield Button("Run Tagging Task", id="btn-action-5", classes="action-btn action-btn--accent")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(ServerStatusCard).refresh_status()
        # Auto-focus first action button so arrow keys work immediately
        self.query_one("#btn-action-1").focus()
        # Startup notice if server is already running
        running, url = _server_status()
        if running:
            self.notify(
                f"Web UI is already running at {url}",
                title="Server detected",
                timeout=5,
            )

    def on_key(self, event) -> None:
        if event.key in ("up", "down"):
            buttons = list(self.query(".action-btn"))
            focused = self.focused
            if focused in buttons:
                idx = buttons.index(focused)
                delta = 1 if event.key == "down" else -1
                buttons[(idx + delta) % len(buttons)].focus()
            elif buttons:
                buttons[0 if event.key == "down" else -1].focus()
            event.stop()

    def _status_card(self) -> ServerStatusCard:
        return self.query_one(ServerStatusCard)

    # ── Keyboard actions ──────────────────────────────────────────────────

    def action_refresh(self) -> None:
        self._status_card().refresh_status()
        self.notify("Status refreshed", timeout=1.5)

    def action_start_server(self) -> None:
        self.app.run_worker(self._do_start_server, thread=True)

    def action_stop_server(self) -> None:
        self.app.run_worker(self._do_stop, thread=True)

    def action_restart_server(self) -> None:
        self.app.run_worker(self._do_restart, thread=True)

    def action_open_tagging(self) -> None:
        self.app.push_screen(TaggingScreen())

    # ── Mouse / button handlers ───────────────────────────────────────────

    @on(Button.Pressed, "#btn-action-1")
    def _on_btn1(self) -> None: self.action_start_server()

    @on(Button.Pressed, "#btn-action-3")
    def _on_btn3(self) -> None: self.action_stop_server()

    @on(Button.Pressed, "#btn-action-4")
    def _on_btn4(self) -> None: self.action_restart_server()

    @on(Button.Pressed, "#btn-action-5")
    def _on_btn5(self) -> None: self.action_open_tagging()

    # ── Worker callbacks ──────────────────────────────────────────────────

    def _do_start_server(self) -> None:
        self.app.call_from_thread(self.notify, "Starting server…", timeout=2)
        start_server_daemon()
        self.app.call_from_thread(self._status_card().refresh_status)

    def _do_stop(self) -> None:
        self.app.call_from_thread(self.notify, "Stopping server…", timeout=2)
        stop_server_daemon()
        self.app.call_from_thread(self._status_card().refresh_status)

    def _do_restart(self) -> None:
        self.app.call_from_thread(self.notify, "Restarting server…", timeout=2)
        restart_server_daemon()
        self.app.call_from_thread(self._status_card().refresh_status)


# ── Tagging Screen ────────────────────────────────────────────────────────────

class TaggingScreen(Screen):
    """Collect tagging parameters and launch a headless tagging run."""

    BINDINGS = [
        Binding("escape", "back", "Back", show=True),
        Binding("ctrl+enter", "submit", "Run", show=True),
    ]

    def compose(self) -> ComposeResult:
        model_options = [(info["name"], key) for key, info in AVAILABLE_MODELS.items()]

        yield Header(show_clock=False)
        # ScrollableContainer lets the form work on short terminals too
        with ScrollableContainer(id="tagging-scroll"):
            with Vertical(id="tagging-form"):
                yield Label("Run Tagging Task", id="form-title")
                yield Rule()

                yield Label("Image directory", classes="form-label")
                yield Input(placeholder="/path/to/images", id="input-path")

                yield Label("Model", classes="form-label")
                yield Select(model_options, value=model_options[0][1], id="input-model")

                yield Label("Output directory  (blank → alongside source images)", classes="form-label")
                yield Input(placeholder="(optional)", id="input-output-dir")

                # Options in a horizontal row; collapses gracefully on narrow terminals
                with Horizontal(id="options-row"):
                    with Vertical(classes="option-block"):
                        yield Label("Recursive", classes="option-label")
                        yield Switch(value=True, id="opt-recursive")
                    with Vertical(classes="option-block"):
                        yield Label("Threshold", classes="option-label")
                        yield Input(value="0.25", id="opt-threshold")
                    with Vertical(classes="option-block"):
                        yield Label("Max tags", classes="option-label")
                        yield Input(value="20", id="opt-max-tags")

                yield Button("Run Tagging", id="btn-run", variant="primary")
        yield Footer()

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_submit(self) -> None:
        self._run()

    @on(Button.Pressed, "#btn-run")
    def _on_run_btn(self) -> None:
        self._run()

    def _run(self) -> None:
        path_str = self.query_one("#input-path", Input).value.strip()
        if not path_str:
            self.notify("Please enter an image directory path.", severity="error")
            return

        model_key = str(self.query_one("#input-model", Select).value)
        model_info = AVAILABLE_MODELS.get(model_key, {})
        model_id = model_info.get("id", model_key)

        output_str = self.query_one("#input-output-dir", Input).value.strip()
        output_dir = Path(output_str) if output_str else None

        try:
            threshold = float(self.query_one("#opt-threshold", Input).value)
        except ValueError:
            threshold = 0.25

        try:
            max_tags = int(self.query_one("#opt-max-tags", Input).value)
        except ValueError:
            max_tags = 20

        recursive = self.query_one("#opt-recursive", Switch).value

        run_args = argparse.Namespace(
            input=Path(path_str),
            recursive=recursive,
            threshold=threshold,
            max_tags=max_tags,
            silent=False,
            continue_on_error=True,
            log_file=None,
            model_dir=None,
            model_id=model_id,
            output_dir=output_dir,
            overwrite=False,
        )

        self.app.push_screen(
            TaggingProgressScreen(
                run_args,
                model_name=model_info.get("name", model_id),
                path_str=path_str,
            )
        )


# ── Tagging Progress Screen ───────────────────────────────────────────────────

class TaggingProgressScreen(Screen):
    """Shows live progress while a headless tagging job runs in a worker thread."""

    BINDINGS = [
        Binding("escape", "back", "Back", show=False),
    ]

    def __init__(self, run_args: argparse.Namespace, model_name: str, path_str: str) -> None:
        super().__init__()
        self._run_args = run_args
        self._model_name = model_name
        self._path_str = path_str
        self._cancel_event = threading.Event()
        self._done = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        # Vertical fills the full viewport height; Log gets the 1fr remainder
        with Vertical(id="progress-container"):
            yield Label(
                f"Model: [bold]{self._model_name}[/bold]   Path: {self._path_str}",
                id="progress-meta",
            )
            yield ProgressBar(total=100, show_eta=False, id="progress-bar")
            yield Log(id="log-view", highlight=True)
            with Horizontal(id="progress-buttons"):
                yield Button("Cancel", id="btn-cancel", variant="error")
        yield Footer()

    def on_mount(self) -> None:
        self._start_tagging()

    @work(thread=True)
    def _start_tagging(self) -> None:
        from imgtagplus.app import run as app_run

        def _cb(current: int, total: int, message: str) -> None:
            if self._cancel_event.is_set():
                raise InterruptedError("Tagging cancelled by user.")
            self.post_message(ProgressUpdate(current, total, message))

        try:
            exit_code = app_run(self._run_args, progress_callback=_cb)
        except InterruptedError:
            exit_code = 130
        except Exception as exc:
            exit_code = 1
            self.post_message(ProgressUpdate(0, 0, f"[red]Error: {exc}[/red]"))

        self.post_message(TaggingComplete(exit_code))

    def on_progress_update(self, event: ProgressUpdate) -> None:
        if event.total > 0:
            self.query_one("#progress-bar", ProgressBar).update(
                total=event.total, progress=event.current
            )
        if event.message:
            self.query_one("#log-view", Log).write_line(event.message)

    def on_tagging_complete(self, event: TaggingComplete) -> None:
        self._done = True
        log = self.query_one("#log-view", Log)
        bar = self.query_one("#progress-bar", ProgressBar)

        # Repurpose the cancel button as a back button
        try:
            btn = self.query_one("#btn-cancel", Button)
            btn.label = "← Back"
            btn.variant = "default"
        except NoMatches:
            pass

        if event.exit_code == 0:
            bar.update(progress=bar.total)
            log.write_line("✓ Tagging complete.")
            self.notify("Tagging complete!", severity="information")
        elif event.exit_code == 130:
            log.write_line("⚠ Tagging cancelled.")
            self.notify("Cancelled.", severity="warning")
        else:
            log.write_line(f"✗ Tagging finished with exit code {event.exit_code}.")
            self.notify("Tagging finished with errors.", severity="error")

        # Show escape hint in footer now that it's safe to leave
        self.app.bind("escape", "pop_screen", description="Back", show=True)
        self.query_one(Footer).refresh()

    @on(Button.Pressed, "#btn-cancel")
    def _on_cancel_or_back(self) -> None:
        if self._done:
            self.app.pop_screen()
        else:
            self._cancel_event.set()
            self.notify("Cancelling…", timeout=1.5)

    def action_back(self) -> None:
        if self._done:
            self.app.pop_screen()
        else:
            self.notify("Tagging is still running. Press Cancel to stop.", timeout=2)


# ── Exit Confirmation Modal ───────────────────────────────────────────────────

class ExitConfirmScreen(ModalScreen):
    """Ask what to do with a running server on exit."""

    BINDINGS = [Binding("escape", "dismiss_cancel", show=False)]

    def compose(self) -> ComposeResult:
        with Vertical(id="exit-dialog"):
            yield Label("Web UI server is running", id="exit-dialog-title")
            yield Label("What would you like to do?", id="exit-dialog-subtitle")
            yield Button("Stop server and exit",       id="btn-stop-exit",   variant="error")
            yield Button("Exit, keep server running",  id="btn-keep-exit",   variant="default")
            yield Button("Cancel",                     id="btn-cancel-exit", variant="default")

    def action_dismiss_cancel(self) -> None:
        self.dismiss("cancel")

    @on(Button.Pressed, "#btn-stop-exit")
    def _stop(self): self.dismiss("stop")

    @on(Button.Pressed, "#btn-keep-exit")
    def _keep(self): self.dismiss("keep")

    @on(Button.Pressed, "#btn-cancel-exit")
    def _cancel(self): self.dismiss("cancel")


# ── App ───────────────────────────────────────────────────────────────────────

class ImgTagPlusApp(App):
    """Root Textual application."""

    ENABLE_COMMAND_PALETTE = False
    CSS_PATH = "tui.tcss"
    TITLE = f"ImgTagPlus v{__version__}"
    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=False, priority=True),
    ]

    def on_mount(self) -> None:
        self.push_screen(DashboardScreen())

    def action_quit(self) -> None:
        running, _ = _server_status()
        if running:
            def _on_result(choice: str | None) -> None:
                if choice == "stop":
                    stop_server_daemon()
                    self.exit()
                elif choice == "keep":
                    self.exit()
                # "cancel" or None → stay in TUI
            self.push_screen(ExitConfirmScreen(), _on_result)
        else:
            self.exit()


# ── Public entry point ────────────────────────────────────────────────────────

def launch_tui() -> None:
    """Instantiate and run the TUI app (blocking until exit)."""
    ImgTagPlusApp().run()
