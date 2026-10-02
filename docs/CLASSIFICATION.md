# Classification: Setup, Formats, Taxonomy, and Feedback

This document covers the image-classification workflow end to end: how to set it
up, which file formats are supported (including the SVG/DXF vector pipeline),
how the category taxonomy is configured, and how user feedback is stored,
prioritized, and re-applied on later scans.

## Setup

1. Create a virtualenv and install the package:

   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -e .
   ```

2. Vector support requires two system tools:

   - `resvg` — rasterizes SVG (install via Homebrew: `brew install resvg`)
   - `ezdxf` — Python DXF reader (installed with the package)

3. The CLIP model (`Xenova/clip-vit-base-patch32`) plus tag embeddings are
   downloaded on first use (~2.5 GB). For air-gapped runs, pre-populate the
   HuggingFace cache and set:

   ```bash
   export HF_HUB_OFFLINE=1
   export TRANSFORMERS_OFFLINE=1
   ```

4. Start the server (`imgtagplus serve`, binds `127.0.0.1:5000`) and POST a
   scan job:

   ```bash
   curl -X POST http://127.0.0.1:5000/api/tag \
     -H 'Content-Type: application/json' \
     -d '{"directory": "/path/to/assets"}'
   ```

   Job completion is announced on the SSE stream `GET /api/stream`
   (`{"type":"progress","done":true,"result_status":...}`); `GET /api/status`
   only reports `is_processing` / `started_at` / `runtime_seconds`.

   Note: the scan job exits with code `2` when any file in the directory
   failed (e.g. a malformed asset) even though the remaining files were
   processed — `continue_on_error` semantics. Exit `0` means every file
   succeeded.

## Supported formats

The scanner walks the target directory and recognizes:

- Raster images: `.png`, `.jpg`, `.jpeg`, `.webp`, `.bmp`, `.gif`, `.tiff`
- Vector drawings: `.svg`, `.dxf`

SVG/DXF files are rasterized on the fly into a temporary directory
(`imgtagplus-svg-*` / `imgtagplus-dxf-*` under the system temp dir) before the
image model sees them. Temp directories are removed after conversion — a
completed scan leaves no `imgtagplus-*` artifacts behind.

Malformed files (truncated PNGs, broken SVG markup, invalid or empty DXFs) are
skipped cleanly: they are logged as errors, counted toward the job's non-zero
exit code, and produce no sidecar output. One bad file never aborts the scan.

Sidecars written next to each processed asset:

- `<stem>.xmp` — XMP metadata with the analyzer's tags
- `<name>.imgtagplus.json` — tag state: `derived_tags`, `user_tags`,
  `user_overrides`, `file_hash`, and `feedback_for_future_scans`

Known limitation: because the XMP file is named from the stem only, two assets
with the same stem but different extensions in one directory (e.g. `panel.png`
and `panel.dxf`) share one `<stem>.xmp` — last writer wins. JSON sidecars are
not affected.

## Taxonomy configuration

Category tags are organized into five axes, defined in
`imgtagplus/tags.py` (`AXES`):

| Axis | Meaning | Example values |
| --- | --- | --- |
| `process` | fabrication process | `PROFILE_CUT`, `POCKET_MILL`, `ENGRAVE`, `ETCH`, ... |
| `geometry_kind` | shape topology | closed contours, open paths, ... |
| `material_family` | material class | wood, acrylic, metal, ... |
| `machine_context` | target machine | CNC router, laser, UV printer, ... |
| `output_intent` | what the file is for | cut file, engrave file, print asset, ... |

The full value catalog and rationale live in `CATEGORY_TAXONOMY.md` at the
repository root. Editing the taxonomy means editing the `AXES` table; the API
validates every request against it and returns `400` with a precise message
for unknown axes or values (e.g. `"unknown axis 'bogus_axis'; expected one of
process, geometry_kind, ..."`).

Tag state resolution follows a strict precedence, strongest first:

1. `user_overrides` — explicit human corrections (with optional reason)
2. `user_tags` with `confirmed_by: "user"` — human confirmations
3. `derived_tags` — machine guesses from the analyzer

## Feedback behavior

Every tag edit through the API is persisted immediately to the JSON sidecar and
also recorded in the `feedback_for_future_scans` artifact, which captures the
human decision (confirm / override / delete) per axis with the old and new
value and the file hash at decision time.

Feedback API:

- `PUT /api/tags/<path>` with `{"axis": ..., "value": ...}` — confirm a value
- `PUT /api/tags/<path>` with `{"axis": ..., "action": "delete"}` — remove an axis
- overrides and invalid inputs are rejected with `400` when the axis has no
  current value to override/delete

At scan time, `_refresh_scan_feedback` re-applies stored decisions so they
survive rescans and artifact regeneration:

- A **deleted** axis never resurrects — deletions are permanent unless the
  human tags the axis again.
- A **user-confirmed** axis is re-asserted as `confirmed_by: "user"` and beats
  any fresh analyzer guess.
- A **user override** is re-asserted as an override record.
- Machine-derived guesses are never promoted into `user_tags`; stale
  `confirmed_by: "unvetted"` records from older builds are purged.

Verified behavior (E2E, 2026-10-02): user tags and deletions persist across
server restarts and full rescans; the feedback artifact is regenerated
correctly on edit; rescans do not clobber human input.

Related documents: `docs/API.md` (HTTP surface), `docs/ARCHITECTURE.md`
(component overview), `docs/OPERATIONS.md` (running and operating the server),
`docs/MODELS.md` (model provenance).
