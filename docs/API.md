# API

This document describes the local HTTP surface exposed by `imgtagplus/server.py`. The API is intended for the bundled local web UI, not for a multi-user remote service.

When the server is running, FastAPI also exposes generated OpenAPI docs at `/docs`.

## Base assumptions

- default bind address: `127.0.0.1:5000`
- server process: local FastAPI app in `imgtagplus/server.py`
- concurrency model: one active tagging job at a time
- response format: JSON for API routes unless noted otherwise

## Security and request handling

Every HTTP response receives these headers from middleware:

- `X-Frame-Options: DENY`
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: no-referrer`
- restrictive `Content-Security-Policy`

POST, PUT, and DELETE requests are subject to origin validation. Only requests from `localhost` or `127.0.0.1` (any port) are accepted; requests with a foreign `Origin` header receive HTTP 403.

### Rate limiting

Endpoints are rate-limited per client IP using a sliding 10-second window:

| Endpoint | Limit |
| --- | --- |
| `GET /api/browse` | 100 requests / 10 s |
| `POST /api/tag` | 10 requests / 10 s |
| `GET /api/stream` | 5 concurrent connections (semaphore) |

Exceeding these limits returns HTTP 429 with `{"detail": "Rate limit exceeded"}` (or `"Too many SSE connections"` for streams).

### Frontend XSS protection

All server-provided strings (error messages, filenames, log content) are escaped via `escapeHtml()` before HTML interpolation in the frontend.

## Endpoint summary

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/` | Serves the main HTML UI |
| `GET` | `/static/*` | Serves static frontend assets |
| `GET` | `/health` | Simple readiness probe |
| `GET` | `/api/models` | Returns model recommendation metadata |
| `GET` | `/api/system` | Returns system profile + model metadata |
| `GET` | `/api/status` | Returns whether a job is running |
| `GET` | `/api/browse` | Server-side directory browser for the file picker |
| `POST` | `/api/tag` | Starts a tagging job |
| `GET` | `/api/stream` | SSE stream for logs and progress |
| `GET` | `/api/logs/download` | Downloads the most recent log file |

## `GET /health`

Readiness endpoint used by the CLI daemon manager.

Response:

```json
{"status": "ok"}
```

Notes:

- this is a liveness/readiness check only
- it does not validate model availability or filesystem access

## `GET /api/models`

Returns model recommendation data from `imgtagplus.profiler.get_model_recommendations()`.

Response shape:

```json
{
  "models": [
    {
      "id": "clip",
      "name": "CLIP (Zero-Shot)",
      "description": "Fast tagger using predefined categories. Uses ~1GB RAM.",
      "min_ram_gb": 1.0,
      "type": "tagger",
      "recommended": true,
      "key": "clip",
      "supported": true,
      "warning": ""
    }
  ]
}
```

Notes:

- `key` is the user-facing selection value the frontend posts back
- `id` may be the same as `key` or a full Hugging Face model ID
- `supported` is a heuristic based on detected RAM/VRAM, not a hard guarantee

## `GET /api/system`

Returns the full profiler summary used by the UI at startup.

Response shape:

```json
{
  "hardware": {
    "os": "Darwin",
    "arch": "arm64",
    "total_ram_gb": 16.0,
    "available_ram_gb": 9.5,
    "vram_gb": 16.0,
    "accelerator": "mps"
  },
  "models": [...],
  "performance_rating": "Good"
}
```

Notes:

- `models` mirrors the `GET /api/models` payload
- `performance_rating` is coarse UI copy, not a benchmark

## `GET /api/status`

Returns whether the single worker slot is busy.

Response:

```json
{"is_processing": false}
```

The frontend uses this on page load to reconnect to an in-flight job after refresh.

## `GET /api/browse`

Lists visible directories for the file picker.

Query parameter:

- `path` — optional absolute path string

Behavior:

- with an empty `path`, the server starts from the user's home directory
- only directories are returned
- hidden entries are omitted
- files are not listed

Success response shape:

```json
{
  "current_path": "/Users/example",
  "items": [
    {"name": "..", "path": "/Users/example", "is_dir": true},
    {"name": "photos", "path": "/Users/example/photos", "is_dir": true}
  ],
  "sandbox": false
}
```

Error responses use standard HTTP status codes:

- `404` — Directory does not exist
- `403` — Permission denied
- `429` — Rate limit exceeded

```json
{"detail": "Directory does not exist"}
```

```json
{"detail": "Permission denied reading directory"}
```

Notes:

- error detail is in the `detail` field (standard FastAPI HTTPException format)
- the browser cannot inspect local folders directly, so the frontend proxies navigation through this endpoint

## `POST /api/tag`

Starts a tagging job in a background thread.

Request body:

```json
{
  "input": "/absolute/path/to/image-or-directory",
  "model_id": "clip",
  "threshold": 0.25,
  "max_tags": 20,
  "recursive": true,
  "overwrite": false,
  "output_dir": "/absolute/path/for/xmp",
  "accelerator": "mps"
}
```

### Fields

- `input` — required; absolute or otherwise server-resolvable path to one image or a directory
- `model_id` — optional; defaults to `"clip"`
- `threshold` — optional; parsed as float and clamped to `0.0..1.0`
- `max_tags` — optional; parsed as int and clamped to `1..200`
- `recursive` — optional boolean
- `overwrite` — optional boolean; replaces existing XMP tags instead of merging
- `output_dir` — optional output directory for `.xmp` files
- `accelerator` — optional explicit runtime choice such as `cuda`, `mps`, or `cpu`

Successful response:

```json
{"status": "started"}
```

Possible error responses (standard HTTP status codes):

- `409` — A tagging job is already in progress
- `400` — Invalid or missing input path
- `429` — Rate limit exceeded

```json
{"detail": "A tagging job is already in progress"}
```

```json
{"detail": "Invalid or non-existent path"}
```

```json
{"detail": "Invalid or non-existent path: /bad/path"}
```

### Validation behavior worth noting

- the server acquires the job lock before parsing the body, so concurrent callers see the busy error early
- numeric values are clamped, not rejected
- missing or nonexistent `input` returns a JSON error payload instead of a 4xx validation response

### Runtime behavior

Once accepted, the server:

1. clears old SSE queue contents
2. sends an initial `"Scanning files..."` progress item
3. creates a background thread
4. calls `imgtagplus.app.run()` with `silent=True` and `continue_on_error=True`
5. emits a final completion item after the worker exits

## `GET /api/stream`

Server-Sent Events endpoint used by the local UI.

Response type:

- `text/event-stream`

Each message is emitted as:

```text
data: {"type":"..."}\n\n
```

### Event types

#### Log event

```json
{
  "type": "log",
  "level": "INFO",
  "message": "Model       : clip (clip)"
}
```

Source:

- regular application log records
- worker crash messages

#### Progress event

Normal progress:

```json
{
  "type": "progress",
  "current": 3,
  "total": 12,
  "filename": "/path/to/image.jpg",
  "done": false
}
```

Completion event:

```json
{
  "type": "progress",
  "current": 0,
  "total": 0,
  "filename": "",
  "done": true
}
```

Important details:

- the server stores a raw `{"type": "done"}` marker internally, but the SSE stream normalizes it into a `"progress"` event with `"done": true`
- when `total` is `0` on the done event, this means no images were found — the frontend shows a yellow "No Images Found" state instead of green "Finished"
- the server also emits a WARNING log event ("No images found at {path}") when this occurs

#### Idle heartbeat

```json
{"type": "idle"}
```

The server emits this only when:

- no job is running
- `log_queue` is empty
- `progress_queue` is empty

The frontend uses this to recover from stale stream state after a page refresh.

### Event ordering

Within each loop iteration, the server sends:

1. queued log events first
2. queued progress events second
3. an idle heartbeat if the app is fully idle

This ordering is intentional so that error logs reach the browser before the UI processes the completion signal.

### Queue behavior

- log and progress queues are bounded in memory
- on overflow, the oldest item is discarded and the newest one is kept
- this favors current UI state over preserving the full event backlog

## `GET /api/logs/download`

Downloads the newest log file matching `imgtagplus_*.log` from the current working directory.

Success:

- file response with the latest log attached

Failure:

- HTTP 404 with a simple HTML body when no matching logs exist

## File access behavior

The web server flow has no path restrictions: browse requests start at the user's home directory, and tagging jobs accept whichever `input` / `output_dir` paths the caller provides.

## Static and docs routes

- `/` serves `static/index.html`
- `/static/*` serves bundled frontend files
- `/docs` is FastAPI's generated interactive API reference for the same app

Those routes are part of the same local process and same-origin policy as the API.
