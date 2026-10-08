# Category Taxonomy — CNC & Laser Design Assets

Status: design artifact (no classifier pipeline yet). Added on `feature/classification`.
Consumers: child tasks `t_5dcb6595` (editable tags + persistence) and `t_f8d7ce26` (similar-file feedback influence).

## Design principle
A CNC/laser design file is a fabrication plan, not a photo. Taxonomy has 5 orthogonal axes — any tag is `(axis, value)`. A user can override one axis without touching the rest; the feedback loop compares changed axes only.

Axes:
- `process` — what the machine does (primary).
- `geometry_kind` — what the file describes.
- `material_family` — substrate (advisory).
- `machine_context` — hardware class (advisory).
- `output_intent` — why the file exists.

## Taxonomy v0.1 (UPPER_SNAKE_CASE keys; title-case labels; keys are stable)

### process
PROFILE_CUT | POCKET_MILL | ENGRAVE | ETCH | DRILL | MARK | INLAY | FIXTURE | STENCIL

### geometry_kind
CONTOUR_PROFILE | INNER_POCKET | THROUGH_HOLE | SLOT | TEXT_GLYPH | DECORATIVE_PATTERN | SIGN_PANEL | FITTING_PAIR

### material_family
WOOD_SOFT | WOOD_HARD | ACRYLIC | POLYCARB | ALUMINUM | STEEL | COMPOSITE_PANEL | PAPER_CARD | UNKNOWN

### machine_context
LASER_CO2 | LASER_FIBER | CNC_ROUTER | PEN_PLOTTER | UV_FLATS

### output_intent
PRODUCTION | PROTOTYPE | TEMPLATE | DECORATIVE | FUNCTIONAL

## Normalization rules
1. Key = UPPER_SNAKE_CASE (stable); label = title-case (may change); axis separated from value.
2. Ambiguous file → classifier may emit two process tags; user confirmation selects primary (`user_confirmed`); deleted axis persisted (`user_deleted`) so future similar-file scans suppress it.
3. No format recognized (scanner) → no category tags (`{}`); taxonomy applied only after format detection succeeds (see scanner behavior in BASELINE.md).
4. Score below `threshold` (default 0.25, `app.py`) → no derived process; other axes also suppressed (future: user/filename heuristics may emit them).
5. Empty classification is `{}` (not synthetic `UNCATEGORIZED`). UI treats empty as "needs user input".
6. User-added unvetted tags → `user_added=unvetted` until promoted; live only in `user_tags`.

## Missing / ambiguous handling
- Missing format: `{}` tags, file listed by scanner.
- Missing process below threshold: `{}`.
- Conflicting scores (PROFILE_CUT 0.42 vs ENGRAVE 0.41): both emitted; edit picks primary + deletes other.
- Material unspecified: `UNKNOWN` (not inferred from filename).

## Data contract (for child `t_5dcb6595`)

Per-file JSON sidecar (alongside `.xmp` or `.imgtagplus.json`):
```json
{
  "file_hash": "sha256:...",
  "filename": "fixture_plate.svg",
  "derived_tags": {
    "process":     {"key":"POCKET_MILL", "label":"Pocket mill", "confidence":0.78},
    "geometry_kind":{"key":"INNER_POCKET","label":"Inner pocket","confidence":0.72},
    "material_family":{"key":"COMPOSITE_PANEL","label":"Composite panel","confidence":0.33},
    "machine_context": null,
    "output_intent": null
  },
  "user_tags": {
    "process":     {"key":"PROFILE_CUT","label":"Profile cut","confirmed_by":"user","set_at_utc":"2026-10-01T20:07:00Z"},
    "geometry_kind":{"key":"INNER_POCKET","label":"Inner pocket","confirmed_by":"user","set_at_utc":"2026-10-01T20:07:00Z"},
    "output_intent":{"key":"FUNCTIONAL","label":"Functional","confirmed_by":"user","set_at_utc":"2026-10-01T20:08:00Z"}
  },
  "user_deletions": ["ENGRAVE","STENCIL"],
  "user_overrides": {
    "material_family":{"old":"ALUMINUM","new":"COMPOSITE_PANEL","reason":"fixture, not part"}
  },
  "feedback_for_future_scans":{"similar_file_hash_pattern":"bucket/hash-prefix","user_confirmed_axes":["process","geometry_kind"],"user_deleted_axes":["ENGRAVE"],"user_overrides":{"material_family":"COMPOSITE_PANEL"},"applied_at_utc":"2026-10-01T20:08:00Z"}
}
```

## Precedence and confirmation rules (distinguish user feedback from analyzer output)
1. Per-axis, `user_tags` (with `confirmed_by: user`) always wins over `derived_tags`.
2. `user_deletions` suppresses a derived tag even if the classifier re-emits it on a future scan of the same/similar file.
3. `user_overrides` records the original derived value (`old_derived_key`) and the user replacement (`new_user_key`); on future similar-file scans, if classifier proposes `old`, it is replaced by `new`; if it proposes something else, `new` still wins.
4. `feedback_for_future_scans` is the artifact the similarity mechanism (future, `t_f8d7ce26`) reads: `similar_file_hash_pattern` defines which files are "similar" (bucket/prefix); `user_confirmed_axes` lists axes the user locked; `user_deleted_axes` lists axes the user removed.
5. Analyzer output is distinguishable: `derived_tags` keys have `confidence` (float); `user_tags` keys have `confirmed_by: user` and `set_at_utc`. There is no `confidence` on user tags.
6. Persistence: user edits survive restarts (written to `.imgtagplus.json` or embedded in XMP); derived tags are recomputed on each scan but overridden by persisted user settings.

## What this task does NOT implement
- The classifier pipeline (process tagger, similarity mechanism) — out of scope for `t_d99dd92e`; owned by sibling `t_5054147f` / downstream tasks.
- The editable-tag CRUD UI/API (`t_5dcb6595`).
- The similar-file feedback influence (`t_f8d7ce26`).
- Normalization enforcement in runtime — rules documented here; runtime validation belongs in `t_5dcb6595`.

## Extensions (future)
- Add `geometry_subtype` axis (e.g. `POCKET_FLAT_BOTTOM` vs `POCKET_BALL_END`) when 3D/CAM data is available.
- Add `surface_finish` axis (`ROUGH`, `FINISH`, `POLISH`) when material/finish metadata is available.
- Taxonomy promotion: an unvetted user tag promoted to the axis value list changes `user_tags` → `derived_tags` with `confirmed_by: taxonomy_owner`.
