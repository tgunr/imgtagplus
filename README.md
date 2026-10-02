> [!WARNING]  
> This project is in very early development stages and should not be relied on for production use.

# ImgTagPlus

**Bulk AI image tagger** — automatically tags images using CLIP (ViT-B/32) via ONNX Runtime and saves tags as XMP sidecar files, compatible with all major digital asset management (DAM) systems.

## Features

- **AI-powered tagging** — Uses OpenAI's CLIP (fast, zero-shot) or Microsoft Florence-2 (rich VLM captioning and OCR)
- **Interactive Web UI** — Beautiful, local real-time monitoring of tagging jobs through a browser interface.
- **Image viewer lightbox** — Browse any selected directory and inspect image files with their XMP tags in built-in grid/list views plus a lightbox viewer.
- **XMP sidecar files** — Non-destructive; tags saved in `.xmp` files recognised by Lightroom, Bridge, Darktable, digiKam, XnView, etc.
- **Bulk processing** — Tag a single image or an entire directory tree
- **Cross-platform** — Works on Linux, macOS, and Windows
- **Interactive CLI Manager** — Manage the local web server or execute headless tasks.
- **Detailed logging** — Full debug log written to file

## Screenshots

### Tagger
![ImgTagPlus Tagger UI](imgtagplus_tagger.png)

### Viewer
![ImgTagPlus Viewer UI](imgtagplus_viewer.png)

## Quick Start

### Install

```bash
# Clone and install the full Florence + CLIP stack
cd imgtagplus
pip install -r requirements.txt

# Or install a lighter CLIP-only environment
pip install -r requirements-clip.txt

# Or install as a package
pip install .
```

```bash
# Display the interactive CLI manager
imgtagplus

# From the interactive menu, you can start the Web UI server
# and manage background tagging tasks visually.
```

### Headless CLI Tagging

```bash
# Tag a directory using the classic CLIP model
imgtagplus -i ./photos/ -r

# Or explicitly start the Web UI Server in the background
imgtagplus --start-server

# To stop the server
imgtagplus --stop-server
```

### Run as a Python module

```bash
python -m imgtagplus -i photo.jpg
```

### Run tests

```bash
pip install -r requirements-dev.txt
pytest
```

### Frontend development

```bash
npm install
npm run build:css
```

Run the CSS build after changing `imgtagplus/static/input.css`.

### Local model cache setup for development

Model weights are **not** meant to live in Git. They are downloaded locally on first use and should stay in your local cache directory instead of being synced to GitHub.

Default cache locations:

- `~/.cache/imgtagplus`
- repo-local fallback: `.cache/imgtagplus` when the home cache is not writable

The repository ignores `.cache/` so local model downloads stay out of source control.

If you want to warm the cache during setup, run a local one-image pass that writes output somewhere disposable:

```bash
python -m imgtagplus -i ./test_image.jpg --model-id clip --silent --output-dir /tmp/imgtagplus-model-warmup
```

To pre-download Florence for local development, repeat the same command with `--model-id florence-2-base`.

## CLI Options

| Option | Short | Default | Description |
|---|---|---|---|
| `--start-server` |  |  | Starts the background Web UI Server |
| `--stop-server` |  |  | Stops the background Web UI Server |
| `--input` | `-i` | *(required for headless)* | Path to image or directory |
| `--recursive` | `-r` | `false` | Scan subdirectories |
| `--model-id` | | `clip` | Which AI to use (`clip` or `florence-2-base`) |
| `--threshold` | `-t` | `0.25` | Min confidence to keep a tag (CLIP only) |
| `--max-tags` | `-n` | `20` | Max tags per image |
| `--silent` | `-s` | `false` | Suppress interactive prompts |
| `--continue-on-error` | `-c` | `false` | Skip errors, keep going |
| `--overwrite` |  | `false` | Replace existing XMP tags instead of merging them |
| `--output-dir` | `-o` | *(alongside image)* | Custom output directory for `.xmp` files |
| `--log-file` | `-l` | `imgtagplus_TIMESTAMP.log` | Custom log file path |
| `--input-timeout` | | `30` | Seconds to wait for user input on errors before auto-skipping |
| `--model-dir` | | `~/.cache/imgtagplus` | Cache directory for model files |

`clip` and `florence-2-base` are user-facing aliases. Internally, Florence resolves to the Hugging Face model ID `microsoft/Florence-2-base`.

## HTTP API

When the local web server is running, FastAPI serves interactive API docs at [`/docs`](http://127.0.0.1:5000/docs).

The main endpoints are:

- `GET /api/browse` for directory browsing
- `GET /api/images` for listing image previews and XMP tags in a selected directory
- `GET /api/image` for same-origin image delivery to the browser lightbox
- `POST /api/tag` to start a tagging run
- `GET /api/status` to check whether a run is active
- `GET /api/stream` for SSE progress/log events
- `GET /api/models` and `GET /api/system` for hardware/model metadata
- `GET /health` for local readiness checks

## Output

After a run, you'll see a summary like:

```
============================================================
  ImgTagPlus — Run Summary
============================================================

Images processed : 42 / 42
Errors           : 0

Elapsed time  : 2m 15.3s
Avg CPU usage : 78.2%
Peak CPU usage: 95.1%
Avg RAM usage : 412.3 MB
Peak RAM usage: 523.7 MB

XMP output directories:
  /path/to/photos

Log file: /path/to/imgtagplus_20260210_190000.log
============================================================
```

## How It Works

1. **Scans** for images by extension (`.jpg`, `.jpeg`, `.png`, `.webp`, `.tiff`, `.bmp`, `.gif`)
2. **Downloads** the CLIP ViT-B/32 ONNX model on first run (~350 MB, cached)
3. **Pre-computes** text embeddings for ~600 curated tags
4. For each image:
   - Preprocesses (resize, centre crop, normalise)
   - Computes image embedding via ONNX Runtime
   - Calculates cosine similarity against all tag embeddings
   - Selects tags above the confidence threshold
5. **Writes** tags to XMP sidecar files (`dc:subject` keywords)

## Supported Image Formats

`.jpg` `.jpeg` `.png` `.webp` `.tiff` `.tif` `.bmp` `.gif`

## Dependencies

- Python 3.10+
- `fastapi` & `uvicorn` — Web Server framework
- `torch` & `transformers` — VLM inference via Florence-2
- `onnxruntime` — CLIP model inference via ONNX
- `Pillow` — Image loading and processing
- `psutil` — System resource profiling

## License

MIT
