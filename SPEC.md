# ImgTagPlus Specification

## Purpose

ImgTagPlus is a local-first image-tagging tool that scans images on disk, runs an AI tagging backend, and writes keywords to XMP sidecar files for DAM workflows.

## Supported execution modes

- Headless CLI runs against a file or directory.
- Local web UI runs on `127.0.0.1:5000`.
- The web UI browses without sandbox restrictions; server-side browse and tag requests accept any path the server process can read.

## Input behavior

- Supported image extensions are `.jpg`, `.jpeg`, `.png`, `.webp`, `.tiff`, `.tif`, `.bmp`, and `.gif`.
- A single image path processes one file.
- A directory path scans either one level or recursively depending on `--recursive`.
- Missing paths are rejected before processing starts.
- Server-side browse and tag requests are not path-restricted.

## Tagging behavior

- `clip` performs zero-shot tagging against the built-in tag vocabulary.
- `florence-2-base` performs caption-driven keyword extraction.
- `florence-2-large` performs the same caption-driven extraction with a larger model.
- `threshold` applies to CLIP-style scoring and is clamped to the inclusive range `0.0..1.0`.
- Florence backends ignore the `threshold` parameter; all extracted keywords are returned.
- Florence-2 also generates compound keywords by detecting adjacent word pairs in the caption (e.g. "blue sky").
- `max_tags` is clamped to the inclusive range `1..200`.

## XMP behavior

- XMP sidecars are written alongside the image by default unless `--output-dir` is provided.
- Existing XMP tags are merged by default.
- `--overwrite` replaces existing ImgTagPlus tags instead of merging.
- Malformed existing XMP is treated as unreadable input and ignored with a warning rather than crashing the run.
- XML-special characters in tags must be escaped correctly.

## Viewer behavior

- The web UI includes a viewer mode for browsing a selected directory of images.
- Viewer browsing reuses the existing server-mediated directory picker.
- The viewer lists supported image files from the selected directory and can optionally include subdirectories recursively.
- The viewer supports both grid and list preview modes for the loaded files.
- The viewer reads tags from `.xmp` sidecar files located next to each image.
- Images without sidecar tags still appear in the viewer and show an explicit empty-tag state.
- The lightbox supports previous/next navigation and keyboard shortcuts with `ArrowLeft`, `ArrowRight`, and `Escape`.
- The lightbox keeps a consistent preview frame size while navigating between images.

## Zero-images behavior

- When the scanner finds no supported images at the given path, `app.run()` returns exit code `0` but fires a progress callback with `(0, 0, "")` to signal an empty result.
- The web server emits a WARNING log: "No images found at {path}."
- The web UI shows a yellow "No Images Found" state instead of the green success bar.

## Security

- All HTTP responses include `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, and a restrictive `Content-Security-Policy`.
- POST, PUT, and DELETE requests are subject to origin validation; only `localhost` and `127.0.0.1` origins are accepted.
- Rate limiting is enforced per client IP on browse, image, and tag endpoints.
- SSE connections are limited to 5 concurrent clients.
- The frontend escapes all server-provided strings before HTML interpolation to prevent XSS.
- Florence-2 `trust_remote_code` is only enabled for model IDs in the pinned revision allowlist.

## Error handling

- Headless CLI returns a non-zero exit code when scanning or model loading fails.
- Per-image processing failures can continue or abort depending on CLI flags and interactive choices.
- The web server returns explicit error responses for invalid paths.

## Operational behavior

- The server exposes `/health` for readiness checks.
- The server exposes `/api/images` for viewer image/tag listing and `/api/image` for serving viewer image assets to the local browser.
- Only one tagging job may run at a time in the current server architecture.
- Log files are written to the process log directory and can be downloaded from the web UI.

## Non-goals

- Multi-user scheduling
- Remote/multi-host deployment
- Database-backed job orchestration
