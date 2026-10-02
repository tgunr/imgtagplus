# Architecture

This guide explains how ImgTagPlus is structured today and how its major runtime paths fit together. It complements the user-facing overview in `README.md` and the behavioral contract in `SPEC.md`.

## Top-level layout

### CLI and server entry points

- `imgtagplus/cli.py` — command-line entry point and server daemon helpers
  - starts/stops/restarts the local web server daemon
  - dispatches headless tagging runs into the shared application pipeline
- `imgtagplus/tui.py` + `imgtagplus/tui.tcss` — Textual terminal UI launched when `imgtagplus` is run with no arguments
  - keyboard-driven dashboard: arrow keys (↑/↓) navigate action buttons; Tab/Shift-Tab also works
  - command palette disabled (`ENABLE_COMMAND_PALETTE = False`) — Ctrl+P does nothing
  - shows a "Server detected" toast at startup when the web UI is already running
  - exit confirmation dialog (`ExitConfirmScreen`) when quitting with the server running — lets the user stop the server, leave it running, or cancel
- `imgtagplus/server.py` — FastAPI app for the local web UI
  - serves `/`, `/static/*`, and FastAPI's generated `/docs`
  - exposes local API endpoints under `/api/*`
  - runs at most one tagging job at a time
  - streams logs and progress to the browser over SSE

### Core application modules

- `imgtagplus/app.py` — orchestration layer for a tagging run
  - resolves the requested model
  - scans the input path
  - starts resource monitoring
  - loads the tagger backend
  - tags each image and writes XMP sidecars
  - prints the end-of-run summary and returns an exit code
- `imgtagplus/scanner.py` — image discovery for a single file or directory tree
- `imgtagplus/metadata.py` — XMP sidecar read/merge/write logic
- `imgtagplus/logger.py` — file + console logging setup
- `imgtagplus/monitor.py` — per-process CPU/RAM sampling during a run

### Model and selection modules

- `imgtagplus/tagger.py` — CLIP-based zero-shot tagger using ONNX Runtime
- `imgtagplus/vlm.py` — Florence-2 caption-driven tagger
- `imgtagplus/profiler.py` — hardware detection and model recommendation data
- `imgtagplus/tags.py` — curated CLIP vocabulary used for zero-shot tagging

### Frontend assets

- `imgtagplus/static/index.html` — local single-page UI shell
- `imgtagplus/static/main.js` — API calls, SSE connection management, browser-side state

## Main execution paths

### 1. Headless CLI flow

Typical example:

```bash
imgtagplus -i ./photos -r --model-id clip
```

Execution path:

1. `imgtagplus/cli.py` parses arguments.
2. For headless runs, the CLI imports `imgtagplus.app.run()` and calls it directly.
3. `imgtagplus/app.py`:
   - configures logging
   - resolves the requested model key or Hugging Face model ID
   - scans for images
   - starts the resource monitor
   - instantiates either the CLIP tagger or Florence tagger
   - loops over images, tags them, writes XMP files, and records summary stats
4. `imgtagplus/metadata.py` writes a sidecar per image, either:
   - alongside the source image, or
   - under `--output-dir`
5. `app.run()` prints a summary and returns:
   - `0` when all images succeeded
   - `2` when one or more images failed during processing
   - `1` for setup failures such as scan or model-load errors

### Error handling in CLI mode

- Scan failures return early before any work starts.
- Per-image failures are logged and then routed through `_prompt_on_error()` in `app.py`.
- `--continue-on-error` skips prompts and keeps going.
- `--silent` suppresses the prompt and aborts on the first image failure.
- `--input-timeout` (default 30 s) controls how long the prompt waits before auto-skipping.

### Zero-images behavior

When the scanner finds no supported images at the input path:

- `app.run()` calls `progress_callback(0, 0, "")` to signal an empty result, then returns `0`.
- The web server emits a WARNING log and the frontend shows a yellow "No Images Found" state.

### 2. Interactive TUI flow

When `imgtagplus` runs with no arguments, `tui.py` launches a Textual terminal UI (`ImgTagPlusApp`) that can:

- start the web server
- stop or restart the existing server daemon
- open a tagging form (`TaggingScreen`) and run the same `imgtagplus.app.run()` pipeline headlessly, with a live progress view

Key UX details:
- arrow keys (↑/↓) navigate the action button list; first button is auto-focused on load
- `q` and Ctrl+C both route through `ImgTagPlusApp.action_quit()` — if the server is running, an `ExitConfirmScreen` modal asks whether to stop it, leave it running, or cancel
- a "Server detected" notification is shown at startup when the web UI is already active
- the command palette is disabled (`ENABLE_COMMAND_PALETTE = False`)

The TUI is intentionally thin. It does not implement its own tagging logic.

### 3. Web UI flow

Typical example:

```bash
imgtagplus --start-server
```

Runtime path:

1. `imgtagplus/cli.py` launches `imgtagplus/server.py` as a detached subprocess and waits for `/health`.
2. `imgtagplus/server.py` starts FastAPI and serves the local UI.
3. `imgtagplus/static/main.js` loads:
   - `/api/system` for hardware and model metadata
   - `/api/status` to restore run state after refresh
4. When the user starts a job, the browser `POST`s `/api/tag`.
5. The server validates inputs, acquires the single worker lock, drains old SSE queues, and starts one background thread.
6. That thread builds an `argparse.Namespace` and calls the same `imgtagplus.app.run()` used by the CLI.
7. Progress updates are pushed into `progress_queue`; log records are mirrored into `log_queue`.
8. The browser stays connected to `/api/stream` and updates the progress bar and log view from those events.

## Data flow

### Image discovery to metadata output

```text
input path
  -> scanner.scan()
  -> list[Path]
  -> selected tagger backend
  -> list[(tag, score)]
  -> metadata.write_xmp()
  -> .xmp sidecar file
```

### CLIP path

1. `scanner.scan()` resolves files with supported image extensions.
2. `Tagger.precompute_tag_embeddings()` builds or loads cached text embeddings for the curated `TAGS` list.
3. `Tagger.tag_image()`:
   - preprocesses the image
   - runs the ONNX visual encoder
   - compares the image embedding against cached tag embeddings
   - ranks tags and applies threshold / max tag limits
4. `app.py` strips scores down to tag names for XMP writing.

### Florence path

1. `scanner.scan()` resolves the input images.
2. `FlorenceTagger.tag_image()`:
   - generates a `<DETAILED_CAPTION>`
   - post-processes the generated text
   - extracts keywords from the caption
   - preserves adjacent word pairs as compound tags (e.g. "blue sky")
   - returns `(keyword, 1.0)` tuples because this path does not expose per-tag confidence scores
3. `app.py` writes the extracted keyword list to XMP.

## Key runtime components

### Single-job coordination

The web server is intentionally single-tenant:

- `_job_lock` in `imgtagplus/server.py` allows only one active job at a time
- a second `POST /api/tag` while busy returns an error payload instead of queueing work

This keeps the local UI simple and avoids overlapping model loads and filesystem writes.

### Log and progress streaming

`imgtagplus/server.py` uses two in-memory queues:

- `log_queue` for formatted log records
- `progress_queue` for progress and completion events

Important details:

- queues are bounded
- when full, the oldest event is dropped so the UI sees current state
- old queue contents are cleared before a new run begins
- SSE emits log events first, then progress events, then an idle heartbeat when nothing is running

### Resource monitoring

`imgtagplus/monitor.py` samples:

- process CPU percentage
- process RSS memory

The resulting summary is appended to the end-of-run output shown in the CLI and mirrored to the UI logs.

### Logging

`imgtagplus/logger.py` configures:

- a DEBUG file log in the current working directory by default
- a console handler at INFO, or WARNING in `--silent` mode

The web server also adds an extra handler so application logs appear in the browser's live stream.

### File access and path boundaries

The browser file picker is server-mediated; it does not read the filesystem directly.

- browsing starts at the user's home directory and can navigate anywhere the server process can read
- `input` and `output_dir` for tagging jobs are not path-restricted

### Persistence and caches

- CLIP model assets and embedding caches live under the configured model directory
- Florence downloads also use that model directory and set `HF_HOME` to the same location
- XMP sidecars persist on disk next to the source images or under the chosen output directory
- log files are written into the current working directory unless `--log-file` overrides the path

## Security design

The server applies several layers of protection appropriate for a local tool:

- **Request validation:** CSRF origin checking on mutating requests (POST/PUT/DELETE) — only `localhost`/`127.0.0.1` origins are accepted.
- **Rate limiting:** Per-client-IP sliding window limits on browse (100/10 s), tag (10/10 s), and a semaphore cap on SSE connections (5 concurrent).
- **Response hardening:** `Content-Security-Policy`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` on every response.
- **Frontend escaping:** `escapeHtml()` sanitises all server-provided strings before innerHTML interpolation.
- **Model trust:** Florence-2 `trust_remote_code` is only enabled for model IDs in the pinned revision allowlist; community ONNX processor revisions are pinned.

## Design notes

Some current design choices are deliberate:

- one shared pipeline for CLI and web requests keeps behavior aligned
- local-only web serving avoids a separate API/auth layer
- model recommendations are advisory; unsupported models may still appear, but the UI flags them

For exact endpoint contracts, see `docs/API.md`. For model-specific runtime behavior, see `docs/MODELS.md`.
