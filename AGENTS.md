# ImgTagPlus — Agent Context

Local-first bulk image tagger (CLIP + Florence-2) writing XMP sidecars for DAM workflows. Python >=3.10, venv at `.venv` (Python 3.13.9). Install: `.venv/bin/pip install -e .`.

## File map (don't re-discover)

- `imgtagplus/cli.py` — CLI entry (`imgtagplus.cli:main`), flags `--no-vector`, `--vector-px` (default 1024), `--input/-i`, `--recursive/-r`, `--model-id`, `--threshold/-t`, `--max-tags/-n`, `--silent`, `--continue-on-error`, `--overwrite`, `--output-dir`, `--log-file`
- `imgtagplus/app.py` — run orchestration: resolve model → scan → monitor → tag → XMP → summary + exit code
- `imgtagplus/scanner.py` — discovery; `IMAGE_EXTENSIONS` includes raster (jpg/jpeg/png/webp/tiff/tif/bmp/gif) + vector (svg/dxf)
- `imgtagplus/converter.py` — vector validation + rasterization: `detect_vector_format` / `is_valid_vector` / `rasterize_vector` → `RasterHandle` (isolated mkdtemp PNG, cleaned on exit). SVG via `resvg` CLI (`brew install resvg`); DXF via `ezdxf` + matplotlib Agg. Errors: `VectorFormatError` / `UnsupportedVectorError` / `ConversionError`
- `imgtagplus/tagger.py` — CLIP ONNX zero-shot; `imgtagplus/vlm.py` — Florence-2 caption→keywords; `imgtagplus/tags.py` — curated CLIP vocabulary
- `imgtagplus/metadata.py` — XMP read/merge/write; `imgtagplus/server.py` — FastAPI (`127.0.0.1:5000`, `/api/*`, SSE `/api/stream`); `imgtagplus/tui.py` — Textual UI
- `imgtagplus/logger.py`, `monitor.py`, `profiler.py` — logging, CPU/RAM sampling, hardware/model picks
- Docs: `SPEC.md` (behavioral contract), `docs/ARCHITECTURE.md` (module paths), `docs/CLASSIFICATION.md` (vector pipeline + taxonomy + feedback), `CATEGORY_CONFIG.yaml` (taxonomy), `README.md` (CLI/API)
- Tests: `tests/test_converter.py`, `test_scanner.py`, `test_app_runtime.py`, `test_cli.py`, `test_metadata.py`, `test_server_*.py`, `test_tagger_cache.py`, `test_vlm.py`, etc.

## Verify (run these, don't narrate)

```bash
.venv/bin/pytest tests/test_converter.py tests/test_scanner.py -q
.venv/bin/pytest tests/ -q
.venv/bin/python -c "import imgtagplus.app, imgtagplus.converter, imgtagplus.cli; print('imports OK')"
```

## Conventions

- Sidecars: `<name>.xmp` (named from full filename, e.g. `panel.png` → `panel.png.xmp`) + `<name>.imgtagplus.json` (derived_tags, user_tags, file_hash). Legacy pre-2026-10 `<stem>.xmp` still recognized.
- Vector temp dirs `imgtagplus-svg-*` / `imgtagplus-dxf-*` under system temp; removed after conversion.
- Malformed files: log, count toward exit code 2, never abort scan. Missing paths rejected before start.
- Upstream `origin` = `git@github.com:tgunr/imgtagplus.git`, `upstream` = flatdotcodes; active branch `feature/classification`. `imgtagplus/cli.py` may carry uncommitted changes from sibling tasks — edit, don't commit others' work.
- Token discipline: batch independent reads per turn, `grep -n` + ranged reads over full files, no tool narration, one conclusion at end.
