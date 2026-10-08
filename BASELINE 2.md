# Baseline: imgtagplus fork

Established 2026-10-01 by Kanban task t_9f55ed61.

## Repository layout

- Upstream (original, DO NOT MODIFY): https://github.com/flatdotcodes/imgtagplus
- Origin (user fork): git@github.com:tgunr/imgtagplus.git (true GitHub fork; parent = flatdotcodes/imgtagplus)
- Working clone: /Users/davec/Desktop/DXF/imgtagplus-fork
- Original checkout (left untouched): /Users/davec/Desktop/DXF/imgtagplus
- Branch for subsequent work: `feature/classification` (clean tree, based on upstream/main @ 88e4caf)
- Remotes: `origin` = user fork (push), `upstream` = original (fetch only)

Note: an earlier attempt used `gh repo create` (empty standalone repo, wrong default branch, no
fork provenance). It was deleted and replaced by a real `gh repo fork`.

## What the project is

ImgTagPlus v1.0.0 — bulk AI image tagger (CLIP ViT-B/32 via ONNX Runtime) that writes XMP
sidecar files for DAM compatibility. Ships a FastAPI Web UI (`imgtagplus/server.py` +
`imgtagplus/static/`), a Textual TUI (`tui.py`), a file watcher (`monitor.py`), and a headless
CLI entry point `imgtagplus` (`cli.py:main`). Optional Florence-2 VLM caption mode
(`vlm.py`, `--model-id florence-2-base|florence-2-large`).

## Supported formats (today)

`imgtagplus/scanner.py:15` `IMAGE_EXTENSIONS` = jpg, jpeg, png, webp, tiff, tif, bmp, gif.

Gap for the planned work: **no SVG, no DXF** — the classification task (t_5054147f) must add
these, converting them to a raster the analyzer can consume.

## Classification settings (current)

- Default model: `clip` (ONNX `Xenova/clip-vit-base-patch32`, `tagger.py:22-24`); weights
  auto-download through `hf_hub_download` into the model dir on first use.
- `--threshold` (default 0.25), `--max-tags` (default 20), `--model-id {clip, florence-2-base,
  florence-2-large}`, `--model-dir`, `--overwrite`, `-o` output dir for XMP sidecars,
  `--input-timeout`, `-r` recursive.
- Vocabulary: curated candidate tag list in `imgtagplus/tags.py` (human-scale object/activity
  nouns; no CNC/laser/DXF-specific vocabulary yet).
- Florence-2 revisions are pinned in `vlm.py` (`FLORENCE_MODEL_REVISIONS`) because
  `trust_remote_code=True` is required.

## Runtime requirements

- Python >= 3.10 (pyproject). Baseline venv: Python 3.13 (uv-managed, `.venv/` in the fork
  clone). Host default `python3` is 3.14; not used.
- Heavy deps: onnxruntime, Pillow, numpy, psutil, huggingface-hub, fastapi, uvicorn, torch,
  transformers (<6), optimum[onnxruntime], einops, timm, textual.
- Node/npm only for CSS build (`npm run build:css`, Tailwind v4) and dev tooling. Upstream
  tracks `node_modules/` in git — after `npm install`, run `git checkout -- node_modules` to
  restore tracked state.
- First CLIP run downloads ~100 MB of ONNX weights into the model cache dir.

## Baseline verification (this clone)

- `uv venv --python 3.13 .venv` + `uv pip install -e .` + `uv pip install pytest pytest-asyncio
  httpx` — clean install.
- `python -m pytest` — **55 passed, 0 failed** (requires pytest-asyncio; the project does not
  declare dev deps, so this was installed manually).
- `imgtagplus --version` → 1.0.0; `--help` renders all CLI options.
- Real tag smoke test: generated a synthetic PNG, ran
  `imgtagplus -i smoke_test.png -o /tmp/imgtagplus-smoke/xmp --overwrite --no-tui` —
  1/1 processed, 0 errors, ~2.3 s, peak RAM ~1.2 GB, valid XMP sidecar written with tag
  `flag`.
- `npm test` is a placeholder (`echo "Error: no test specified" && exit 1`) — upstream artifact,
  not a real failure; pytest is the test suite.

## Baseline failures / notes for downstream tasks

1. No pytest-asyncio (or any dev extra) declared — async server tests fail on a bare install
   (`pytest.ini_options` has no `asyncio_mode`). Consider adding a `[project.optional-dependencies]
   dev = [pytest, pytest-asyncio, httpx]` group on the fork.
2. `IMAGE_EXTENSIONS` lacks `.svg`/`.dxf` (and there is no conversion path) — the core gap the
   classification child task addresses.
3. `node_modules/` is committed upstream; keep it out of feature diffs.
4. Florence-2 weights are NOT cached on this machine (HF cache holds only a config stub);
   a florence-mode smoke test would download ~500 MB-1 GB. CLIP mode was used for the baseline
   smoke test instead.
