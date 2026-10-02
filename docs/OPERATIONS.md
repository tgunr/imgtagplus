# Operations

This short guide covers the local operational details that are easy to miss when reading only the user docs.

## System requirements

- **Python 3.10+** (enforced in `pyproject.toml` and checked by `setup.sh`)
- Node.js / npm — optional, only needed to rebuild frontend CSS
- OS: Linux, macOS, or Windows

## Setup

```bash
# Full install (CLIP + Florence)
bash setup.sh

# Dev install (adds ruff, pytest, etc.)
bash setup.sh --dev

# CLIP-only install
pip install -r requirements-clip.txt
```

`setup.sh` checks the Python version before proceeding and builds frontend CSS automatically when npm is available.

## Model cache

Model assets are downloaded locally and are not intended to be checked into Git.

- default cache: `~/.cache/imgtagplus`
- repo-local fallback: `.cache/imgtagplus` when the home cache is not writable

The repository ignores `.cache/` so local cache files stay out of source control.

To warm the local cache after setup, run:

```bash
python -m imgtagplus -i ./test_image.jpg --model-id clip --silent --output-dir /tmp/imgtagplus-model-warmup
```

For Florence local development, repeat that command with `--model-id florence-2-base`.

## Server lifecycle

The web UI server is managed by `imgtagplus/cli.py`.

Useful commands:

```bash
imgtagplus --start-server
imgtagplus --stop-server
imgtagplus --restart-server
```

Behavior:

- the CLI launches `imgtagplus/server.py` as a detached subprocess
- a PID file is stored in the system temp directory and is namespaced by user ID where available
- startup is not reported as successful until `http://127.0.0.1:5000/health` answers with HTTP 200
- stop logic validates that the stored PID still looks like an ImgTagPlus server before signaling it

## File access

The web UI has no path restrictions: browsing starts at the user's home directory, and tagging jobs accept any local path the server process can read.

Headless CLI runs likewise operate on whichever input path the user passes locally.

## Logging

By default, each run writes a log file into the current working directory:

```text
imgtagplus_YYYYMMDD_HHMMSS.log
```

Notes:

- file logging is always DEBUG level
- console logging is INFO, or WARNING in silent mode
- the browser's live log panel mirrors runtime log records from the same process
- `/api/logs/download` returns the newest matching log file from the current working directory

## Job model

The local web server runs only one tagging job at a time.

That means:

- no internal job queue
- no multi-user scheduling
- no persistent run history beyond logs and written XMP files

If you need parallelism, launch separate local processes carefully and avoid overlapping writes to the same output locations.

## Rate limiting

The server enforces per-client-IP rate limits using a 10-second sliding window:

| Endpoint | Limit |
| --- | --- |
| `GET /api/browse` | 100 requests / 10 s |
| `POST /api/tag` | 10 requests / 10 s |
| `GET /api/stream` | 5 concurrent SSE connections |

Exceeding a limit returns HTTP 429. The limits are in-memory and reset when the server restarts.

## Environment files

Environment variables can be set in `.env` files. The `.gitignore` excludes `.env*` patterns to prevent accidentally committing secrets or local overrides.

## Validation notes

Current contributor guidance in `CONTRIBUTING.md` points to:

```bash
ruff check .
pytest
```

If tests fail during collection, check that the repository root is on `PYTHONPATH` or run the suite in the same environment used for normal package development.
