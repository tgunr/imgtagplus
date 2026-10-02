"""Curated tag vocabulary for CLIP zero-shot image tagging, plus the
editable-category CRUD layer defined by CATEGORY_TAXONOMY.md.

Organized by category. Each tag is a short phrase that CLIP can match
against image embeddings.  The list is deliberately kept practical and
relevant to digital-asset-management workflows.

The second half of this module implements the taxonomy contract:
five orthogonal axes, validation of user/analyzer tags, the four-level
precedence merge, and the ``feedback_for_future_scans`` artifact that
downstream consumers use to learn from human corrections.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, MutableMapping, Sequence

# ---------------------------------------------------------------------------
# Tag vocabulary — ~600 tags across common categories
# ---------------------------------------------------------------------------

TAGS: list[str] = [
    # ── Objects ────────────────────────────────────────────────────────────
    "person", "man", "woman", "child", "baby", "group of people", "crowd",
    "face", "hands", "silhouette",
    "dog", "cat", "bird", "horse", "fish", "butterfly", "insect", "deer",
    "bear", "rabbit", "cow", "sheep", "elephant", "lion", "tiger", "wolf",
    "snake", "frog", "turtle", "whale", "dolphin", "penguin", "owl",
    "eagle", "parrot", "duck", "chicken", "pig", "goat", "monkey",
    "car", "truck", "bus", "motorcycle", "bicycle", "train", "airplane",
    "helicopter", "boat", "ship", "sailboat", "canoe",
    "house", "building", "skyscraper", "church", "castle", "bridge",
    "tower", "lighthouse", "barn", "cabin", "tent", "ruins",
    "tree", "flower", "grass", "leaf", "bush", "cactus", "palm tree",
    "pine tree", "mushroom", "vine", "moss", "fern", "rose", "tulip",
    "sunflower", "daisy", "orchid", "lily", "lavender",
    "mountain", "hill", "cliff", "rock", "boulder", "cave", "volcano",
    "river", "lake", "ocean", "waterfall", "stream", "pond", "puddle",
    "island", "peninsula", "glacier", "iceberg",
    "road", "path", "trail", "sidewalk", "highway", "alley", "crosswalk",
    "stairs", "fence", "gate", "wall", "door", "window", "roof",
    "chair", "table", "desk", "bed", "sofa", "bench", "stool",
    "lamp", "chandelier", "candle", "mirror", "clock", "bookshelf",
    "computer", "laptop", "phone", "tablet", "keyboard", "monitor",
    "camera", "television", "speaker", "headphones", "microphone",
    "book", "newspaper", "magazine", "letter", "pen", "pencil",
    "cup", "mug", "glass", "bottle", "plate", "bowl", "fork", "knife",
    "spoon", "pan", "pot", "kettle", "teapot",
    "hat", "glasses", "sunglasses", "shoe", "boot", "bag", "backpack",
    "umbrella", "watch", "ring", "necklace", "tie", "scarf",
    "ball", "balloon", "kite", "flag", "sign", "banner", "poster",
    "guitar", "piano", "violin", "drum", "flute", "trumpet",
    "painting", "sculpture", "statue", "fountain", "mural",
    "gift", "box", "basket", "vase", "jar", "barrel",
    "key", "lock", "chain", "rope", "wire", "cable",
    "fire", "smoke", "flame", "spark", "fireworks", "explosion",
    "weapon", "sword", "shield", "helmet", "armor",
    "wheel", "gear", "engine", "propeller", "antenna",
    "robot", "drone",

    # ── Food & Drink ──────────────────────────────────────────────────────
    "food", "fruit", "apple", "banana", "orange", "grape", "strawberry",
    "watermelon", "lemon", "pineapple", "cherry", "peach", "pear",
    "mango", "avocado", "coconut", "blueberry", "raspberry",
    "vegetable", "tomato", "carrot", "potato", "onion", "pepper",
    "corn", "broccoli", "lettuce", "cucumber", "pumpkin", "garlic",
    "bread", "cake", "pie", "cookie", "donut", "pizza", "hamburger",
    "sandwich", "pasta", "rice", "soup", "salad", "sushi", "steak",
    "cheese", "egg", "butter", "chocolate", "ice cream", "candy",
    "coffee", "tea", "juice", "wine", "beer", "cocktail", "water",
    "milk", "smoothie",

    # ── Scenes & Environments ─────────────────────────────────────────────
    "landscape", "cityscape", "skyline", "panorama", "aerial view",
    "beach", "desert", "forest", "jungle", "meadow", "field", "garden",
    "park", "farm", "vineyard", "orchard", "swamp", "marsh", "wetland",
    "tundra", "prairie", "savanna", "canyon", "valley", "ravine",
    "countryside", "village", "suburb", "downtown", "urban", "rural",
    "harbor", "marina", "dock", "pier", "boardwalk", "promenade",
    "market", "bazaar", "shop", "store", "mall", "restaurant", "cafe",
    "bar", "hotel", "resort", "spa", "museum", "library", "theater",
    "stadium", "arena", "gym", "pool", "playground", "zoo", "aquarium",
    "airport", "train station", "bus stop", "parking lot", "garage",
    "factory", "warehouse", "office", "classroom", "kitchen", "bedroom",
    "bathroom", "living room", "dining room", "hallway", "attic",
    "basement", "balcony", "patio", "porch", "courtyard", "terrace",
    "rooftop", "greenhouse",

    # ── Nature & Weather ──────────────────────────────────────────────────
    "sky", "clouds", "sun", "moon", "stars", "rainbow", "aurora",
    "rain", "snow", "ice", "frost", "fog", "mist", "haze", "dew",
    "storm", "lightning", "thunder", "tornado", "hurricane",
    "wind", "breeze", "overcast", "clear sky", "partly cloudy",
    "sunrise", "sunset", "dawn", "dusk", "twilight", "golden hour",
    "blue hour", "night sky", "starry night", "full moon", "crescent moon",
    "spring", "summer", "autumn", "fall", "winter",
    "shadow", "reflection", "lens flare", "sunbeam", "ray of light",

    # ── Activities & Actions ──────────────────────────────────────────────
    "walking", "running", "jumping", "climbing", "swimming", "diving",
    "surfing", "skiing", "skating", "cycling", "hiking", "camping",
    "fishing", "hunting", "gardening", "cooking", "eating", "drinking",
    "reading", "writing", "drawing", "painting", "photographing",
    "dancing", "singing", "playing music", "performing",
    "working", "studying", "shopping", "traveling", "driving",
    "flying", "sailing", "rowing", "paddling",
    "playing", "exercising", "stretching", "yoga", "meditation",
    "celebrating", "wedding", "party", "festival", "parade", "ceremony",
    "graduation", "birthday", "holiday", "vacation",
    "meeting", "presentation", "conference", "interview",
    "construction", "demolition", "renovation", "repair",
    "praying", "worshipping",

    # ── Sports ────────────────────────────────────────────────────────────
    "soccer", "football", "basketball", "baseball", "tennis", "golf",
    "volleyball", "hockey", "rugby", "cricket", "boxing", "wrestling",
    "martial arts", "karate", "judo", "fencing", "archery",
    "gymnastics", "track and field", "marathon", "relay race",
    "weightlifting", "bodybuilding", "crossfit",
    "rock climbing", "bouldering", "mountaineering",
    "skateboarding", "snowboarding", "wakeboarding",
    "kayaking", "canoeing", "rafting", "windsurfing",
    "horse riding", "polo", "rodeo",
    "racing", "car racing", "motorcycle racing", "cycling race",
    "triathlon", "pentathlon", "decathlon",

    # ── Emotions & Expressions ────────────────────────────────────────────
    "happy", "sad", "angry", "surprised", "scared", "excited",
    "calm", "peaceful", "serious", "thoughtful", "confused",
    "laughing", "smiling", "crying", "frowning", "yelling",
    "love", "romance", "affection", "hug", "kiss", "handshake",

    # ── Colors & Visual Attributes ────────────────────────────────────────
    "red", "blue", "green", "yellow", "orange", "purple", "pink",
    "black", "white", "gray", "brown", "gold", "silver", "bronze",
    "colorful", "monochrome", "pastel", "vivid", "muted", "neon",
    "warm tones", "cool tones", "earth tones",
    "bright", "dark", "dim", "glowing", "shiny", "glossy", "matte",
    "transparent", "translucent", "opaque",
    "patterned", "striped", "checkered", "spotted", "textured",

    # ── Photography Styles ────────────────────────────────────────────────
    "portrait", "close-up", "macro", "wide angle", "telephoto",
    "long exposure", "double exposure", "HDR", "time-lapse",
    "black and white", "sepia", "vintage", "retro", "film grain",
    "bokeh", "shallow depth of field", "tilt-shift",
    "aerial photography", "drone photography", "satellite imagery",
    "underwater photography", "night photography", "astrophotography",
    "street photography", "documentary", "photojournalism",
    "fashion photography", "food photography", "product photography",
    "architecture photography", "wildlife photography",
    "studio lighting", "natural lighting", "backlit", "side-lit",
    "high contrast", "low contrast", "high key", "low key",
    "symmetry", "pattern", "repetition", "minimalist", "abstract",
    "still life", "flat lay", "overhead shot", "eye level",
    "rule of thirds", "leading lines", "framing", "negative space",

    # ── Concepts & Themes ─────────────────────────────────────────────────
    "travel", "adventure", "exploration", "journey", "freedom",
    "nature", "wildlife", "conservation", "ecology", "environment",
    "technology", "science", "innovation", "futuristic", "vintage tech",
    "art", "culture", "heritage", "tradition", "history",
    "education", "learning", "knowledge", "wisdom",
    "health", "wellness", "fitness", "nutrition",
    "business", "finance", "economy", "commerce",
    "family", "friendship", "community", "teamwork", "diversity",
    "spirituality", "religion", "faith",
    "luxury", "elegance", "rustic", "industrial", "modern",
    "cozy", "warm", "cold", "wet", "dry", "dusty", "clean",
    "old", "new", "ancient", "contemporary",
    "large", "small", "tiny", "huge", "tall", "short",
    "crowded", "empty", "busy", "quiet", "noisy",
    "dangerous", "safe", "mysterious", "magical", "dreamy",
    "romantic", "dramatic", "epic", "serene", "chaotic",
]


# ---------------------------------------------------------------------------
# Taxonomy axes (CATEGORY_CONFIG.yaml, mirrored here so the CRUD layer has no
# YAML dependency and can validate without touching disk)
# ---------------------------------------------------------------------------

#: Canonical axis names, in the order they should be presented to users.
_AXES: tuple[str, ...] = (
    "process",
    "geometry_kind",
    "material_family",
    "machine_context",
    "output_intent",
)


def normalize_key(raw: Any) -> str:
    """Normalize a user/analyzer-supplied tag key to UPPER_SNAKE_CASE.

    Accepts ``Title Case``, ``kebab-case``, ``snake_case`` and plain
    lowercase. Returns ``""`` for non-string/empty input so callers can
    reject it uniformly.
    """
    if raw is None:
        return ""
    text = str(raw).strip()
    if not text:
        return ""
    # Split on any run of non-alphanumeric characters, then rejoin.
    parts = [p for p in re.split(r"[^0-9A-Za-z]+", text) if p]
    return "_".join(parts).upper()


#: Public re-export (kept after the definition so module-level consumers
#: such as ``_AXIS_LOOKUP`` below can use it).
AXES: tuple[str, ...] = _AXES

#: Normalized-axis → canonical (lowercase) name, for case-insensitive lookup.
_AXIS_LOOKUP: dict[str, str] = {normalize_key(a): a for a in AXES}

#: Allowed UPPER_SNAKE keys per axis.
VALUE_LIST_BY_AXIS: dict[str, tuple[str, ...]] = {
    "process": (
        "PROFILE_CUT", "POCKET_MILL", "ENGRAVE", "ETCH", "DRILL",
        "MARK", "INLAY", "FIXTURE", "STENCIL",
    ),
    "geometry_kind": (
        "OPEN_CONTOUR", "CLOSED_CONTOUR", "FILLED_AREA", "HATCH",
        "POLYLINE_CHAIN", "POINT_CLOUD", "TEXT_BLOCK", "MIXED",
    ),
    "material_family": (
        "WOOD", "PLYWOOD", "MDF", "ACRYLIC", "PLASTIC", "ALUMINUM",
        "STEEL", "BRASS", "COPPER", "LEATHER", "FABRIC", "PAPER",
        "CARDBOARD", "GLASS", "STONE", "RUBBER", "FOAM", "COMPOSITE",
        "UNKNOWN",
    ),
    "machine_context": (
        "LASER_CO2", "LASER_FIBER", "DIODE_LASER", "CNC_ROUTER",
        "CNC_MILL", "PLOTTER", "VINYL_CUTTER", "PRINTER_UV", "3D_PRINTER",
        "HAND_TOOL", "UNSPECIFIED",
    ),
    "output_intent": (
        "CUT_PATH", "ENGRAVE_RASTER", "MARKING", "TEMPLATE", "ARTWORK",
        "PROTOTYPE", "PRODUCTION", "DOCUMENTATION", "UNKNOWN",
    ),
}

#: Provenance values a user tag may carry.
USER_CONFIRMED_BY: tuple[str, ...] = ("user", "taxonomy_owner", "unvetted")

#: Confidence below this is not emitted as a derived process tag.
DERIVED_CONFIDENCE_THRESHOLD: float = 0.25

#: Number of leading hash characters used to bucket similar files.
FEEDBACK_HASH_PREFIX_LEN: int = 8


class TaxonomyError(ValueError):
    """Raised when a tag, axis, or payload violates the taxonomy contract."""


def label_for(key: str) -> str:
    """Return the human label for a canonical key (``POCKET_MILL`` → ``Pocket Mill``)."""
    canonical = normalize_key(key)
    if not canonical:
        return ""
    return canonical.replace("_", " ").title()


def validate_axis_key(axis: Any) -> str:
    """Return the canonical axis name or raise ``TaxonomyError``."""
    canonical = normalize_key(axis)
    canonical = _AXIS_LOOKUP.get(canonical, canonical.lower() if canonical else "")
    if canonical not in AXES:
        raise TaxonomyError(
            f"unknown axis {axis!r}; expected one of {', '.join(AXES)}"
        )
    return canonical


def validate_value_key(axis: str, value: Any) -> str:
    """Return the canonical value key for ``axis`` or raise ``TaxonomyError``."""
    canonical_axis = validate_axis_key(axis)
    canonical_value = normalize_key(value)
    if not canonical_value:
        raise TaxonomyError("tag value must be a non-empty string")
    allowed = VALUE_LIST_BY_AXIS[canonical_axis]
    if canonical_value not in allowed:
        raise TaxonomyError(
            f"value {value!r} is not valid for axis {canonical_axis!r}; "
            f"expected one of {', '.join(allowed)}"
        )
    return canonical_value


def validate_confidence(value: Any) -> float:
    """Return ``value`` as a float in [0, 1] or raise ``TaxonomyError``."""
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        raise TaxonomyError(f"confidence must be numeric, got {value!r}") from None
    if confidence != confidence:  # NaN
        raise TaxonomyError("confidence must be numeric, got NaN")
    if not 0.0 <= confidence <= 1.0:
        raise TaxonomyError(f"confidence must be in [0, 1], got {confidence}")
    return confidence


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def make_derived_tag(key: str, confidence: Any) -> dict[str, Any]:
    """Build a validated derived-tag record.

    Derived tags carry ``confidence`` and must NOT carry ``confirmed_by``.
    """
    canonical = normalize_key(key)
    if not canonical:
        raise TaxonomyError("derived tag key must be a non-empty string")
    return {
        "key": canonical,
        "label": label_for(canonical),
        "confidence": validate_confidence(confidence),
    }


def make_user_tag(
    axis: str,
    key: str,
    *,
    confirmed_by: str = "user",
    set_at_utc: str | None = None,
) -> dict[str, Any]:
    """Build a validated user-tag record.

    User tags carry ``confirmed_by`` + ``set_at_utc`` and must NOT carry
    ``confidence`` (the contract forbids assigning a confidence to a
    human assertion).
    """
    canonical_axis = validate_axis_key(axis)
    canonical_key = validate_value_key(canonical_axis, key)
    if confirmed_by not in USER_CONFIRMED_BY:
        raise TaxonomyError(
            f"confirmed_by must be one of {', '.join(USER_CONFIRMED_BY)}, "
            f"got {confirmed_by!r}"
        )
    return {
        "key": canonical_key,
        "label": label_for(canonical_key),
        "confirmed_by": confirmed_by,
        "set_at_utc": set_at_utc or _utc_now_iso(),
    }


def make_deletion(
    axis: str,
    key: Any = None,
    *,
    set_at_utc: str | None = None,
) -> dict[str, Any]:
    """Build a validated deletion record for ``axis``.

    A deletion records which axis a human removed and what it was holding at
    the time, so the UI can offer "undo" with the original value.  ``key`` is
    optional because an axis may be deleted before any value existed.
    """
    canonical_axis = validate_axis_key(axis)
    old_key = normalize_key(key) if key else None
    return {
        "axis": canonical_axis,
        "key": old_key,
        "set_at_utc": set_at_utc or _utc_now_iso(),
    }


def make_override(
    axis: str,
    old: Any,
    new: Any,
    *,
    reason: str = "",
    set_at_utc: str | None = None,
) -> dict[str, Any]:
    """Build a validated user-override record for ``axis``.

    ``new`` must be a legal axis value; ``old`` records what the analyzer
    (or a previous user tag) asserted and may be ``None`` when the axis was
    previously empty. ``reason`` is free text and may be empty.
    """
    canonical_axis = validate_axis_key(axis)
    new_key = validate_value_key(canonical_axis, new)
    old_key = normalize_key(old) if old is not None else None
    return {
        "old": old_key,
        "new": new_key,
        "reason": str(reason or ""),
        "set_at_utc": set_at_utc or _utc_now_iso(),
    }


def _deletion_axis(entry: Any) -> str | None:
    """Return the canonical axis named by a ``user_deletions`` entry, or ``None``.

    Accepts both shapes seen in the wild: a bare axis string, and the
    ``{"axis", "key", "set_at_utc"}`` record written by the delete endpoint.
    Returns the *canonical* (lowercase) axis so it compares equal to the names
    in ``AXES``; unrecognised entries return ``None`` and are discarded by
    callers rather than raising inside a merge.
    """
    if isinstance(entry, Mapping):
        entry = entry.get("axis")
    if not entry:
        return None
    try:
        return validate_axis_key(entry)
    except TaxonomyError:
        return None


def merge_tags(
    derived_tags: Mapping[str, Any] | None = None,
    user_tags: Mapping[str, Any] | None = None,
    user_overrides: Mapping[str, Any] | None = None,
    user_deletions: Iterable[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Resolve the effective classification for one image.

    Precedence per axis (highest wins):

    1. ``user_tags`` with ``confirmed_by: "user"``
    2. ``user_overrides``
    3. ``user_tags`` with ``confirmed_by: "unvetted"`` (or ``taxonomy_owner``)
    4. ``derived_tags`` (suppressed below ``DERIVED_CONFIDENCE_THRESHOLD``)

    Any axis listed in ``user_deletions`` is dropped from the result and is
    NOT re-emitted from derived tags — a human deletion is sticky.

    Returns ``{}`` when nothing survives; the contract forbids synthesizing
    an ``UNCATEGORIZED`` placeholder.
    """
    derived = dict(derived_tags or {})
    users = dict(user_tags or {})
    overrides = dict(user_overrides or {})
    deletions = {_deletion_axis(a) for a in (user_deletions or ())}
    deletions.discard(None)

    effective: dict[str, dict[str, Any]] = {}

    for axis in AXES:
        if axis in deletions:
            continue

        user_record = users.get(axis)
        override_record = overrides.get(axis)

        confirmed_user = None
        unvetted_user = None
        if isinstance(user_record, Mapping):
            confirmed_by = user_record.get("confirmed_by")
            if confirmed_by == "user":
                confirmed_user = user_record
            elif confirmed_by in ("unvetted", "taxonomy_owner"):
                unvetted_user = user_record

        if confirmed_user is not None:
            key = normalize_key(confirmed_user.get("key"))
            if key:
                effective[axis] = {
                    "key": key,
                    "label": label_for(key),
                    "source": "user_confirmed",
                    "confirmed_by": "user",
                }
                continue

        if isinstance(override_record, Mapping):
            key = normalize_key(override_record.get("new"))
            if key:
                effective[axis] = {
                    "key": key,
                    "label": label_for(key),
                    "source": "user_override",
                    "old": normalize_key(override_record.get("old")) or None,
                }
                continue

        if unvetted_user is not None:
            key = normalize_key(unvetted_user.get("key"))
            if key:
                effective[axis] = {
                    "key": key,
                    "label": label_for(key),
                    "source": "user_unvetted",
                    "confirmed_by": unvetted_user.get("confirmed_by"),
                }
                continue

        derived_record = derived.get(axis)
        if isinstance(derived_record, Mapping):
            key = normalize_key(derived_record.get("key"))
            try:
                confidence = float(derived_record.get("confidence", 0.0))
            except (TypeError, ValueError):
                confidence = 0.0
            if key and confidence >= DERIVED_CONFIDENCE_THRESHOLD:
                effective[axis] = {
                    "key": key,
                    "label": label_for(key),
                    "source": "derived",
                    "confidence": confidence,
                }

    return effective


def merge_sidecar(sidecar: Mapping[str, Any] | None) -> dict[str, Any]:
    """Resolve a persisted sidecar dict into the wrapped effective-tag view.

    ``merge_tags`` resolves one image from explicit keyword arguments; this
    adapter unpacks the on-disk sidecar's owned keys into that call and wraps
    the flat result in ``{"axes": ...}`` so API callers have a stable shape.
    """
    data = sidecar if isinstance(sidecar, Mapping) else {}
    return {
        "axes": merge_tags(
            derived_tags=data.get("derived_tags"),
            user_tags=data.get("user_tags"),
            user_overrides=data.get("user_overrides"),
            user_deletions=data.get("user_deletions"),
        )
    }


def hash_prefix_pattern(file_hash: Any, length: int = FEEDBACK_HASH_PREFIX_LEN) -> str:
    """Return a glob-ish prefix pattern bucketing files with a similar hash.

    Downstream consumers match ``similar_file_hash_pattern`` against candidate
    hashes with ``str.startswith`` on the literal prefix portion.
    """
    text = normalize_key(file_hash).replace("_", "")
    if not text:
        return ""
    prefix = text[: max(1, length)]
    return f"{prefix}*"


def build_feedback_artifact(
    *,
    file_hash: Any,
    user_tags: Mapping[str, Any] | None = None,
    user_deletions: Iterable[str] | None = None,
    user_overrides: Mapping[str, Any] | None = None,
    applied_at_utc: str | None = None,
) -> dict[str, Any]:
    """Build the ``feedback_for_future_scans`` artifact.

    Only records what a human actually did:
      * ``user_confirmed_axes`` — axes where ``confirmed_by == "user"``
      * ``user_deleted_axes``   — axes the human deleted
      * ``user_overrides``      — axis → ``{old, new, reason}``

    Axes with no human input are omitted entirely (never zero-filled), and an
    artifact with no human input at all is ``{}`` so callers can skip writing
    it.
    """
    users = dict(user_tags or {})
    overrides = dict(user_overrides or {})
    deletions = sorted({a for a in (_deletion_axis(e) for e in (user_deletions or ())) if a})

    confirmed_axes: dict[str, str] = {}
    for axis in AXES:
        record = users.get(axis)
        if isinstance(record, Mapping) and record.get("confirmed_by") == "user":
            key = normalize_key(record.get("key"))
            if key:
                confirmed_axes[axis] = key

    override_axes: dict[str, dict[str, Any]] = {}
    for axis in AXES:
        record = overrides.get(axis)
        if isinstance(record, Mapping):
            override_axes[axis] = {
                "old": normalize_key(record.get("old")) or None,
                "new": normalize_key(record.get("new")) or None,
                "reason": str(record.get("reason") or ""),
            }

    if not confirmed_axes and not deletions and not override_axes:
        return {}

    artifact: dict[str, Any] = {
        "user_confirmed_axes": confirmed_axes,
        "user_deleted_axes": deletions,
        "user_overrides": override_axes,
        "applied_at_utc": applied_at_utc or _utc_now_iso(),
    }
    pattern = hash_prefix_pattern(file_hash)
    if pattern:
        artifact["similar_file_hash_pattern"] = pattern
    return artifact


def apply_feedback_at_scan(
    feedback: Mapping[str, Any] | None,
    derived_tags: Mapping[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """Apply a persisted feedback artifact to freshly derived tags at scan time.

    This is the scan-time half of the contract: a deletion suppresses the
    re-emitted derived tag, an override replaces it, and a user-confirmed
    axis wins outright. ``derived_tags`` are never mutated in place.
    """
    if not isinstance(feedback, Mapping) or not feedback:
        return merge_tags(derived_tags=derived_tags)

    confirmed_axes = feedback.get("user_confirmed_axes") or {}
    deleted_axes = feedback.get("user_deleted_axes") or ()
    override_axes = feedback.get("user_overrides") or {}

    user_tags: dict[str, dict[str, Any]] = {}
    for axis, key in (confirmed_axes.items() if isinstance(confirmed_axes, Mapping) else ()):  # noqa: E501
        try:
            canonical_axis = validate_axis_key(axis)
            canonical_key = validate_value_key(canonical_axis, key)
        except TaxonomyError:
            continue
        user_tags[canonical_axis] = {
            "key": canonical_key,
            "label": label_for(canonical_key),
            "confirmed_by": "user",
        }

    user_overrides: dict[str, dict[str, Any]] = {}
    for axis, record in (override_axes.items() if isinstance(override_axes, Mapping) else ()):
        if not isinstance(record, Mapping):
            continue
        try:
            canonical_axis = validate_axis_key(axis)
            canonical_new = validate_value_key(canonical_axis, record.get("new"))
        except TaxonomyError:
            continue
        user_overrides[canonical_axis] = {
            "old": normalize_key(record.get("old")) or None,
            "new": canonical_new,
            "reason": str(record.get("reason") or ""),
        }

    return merge_tags(
        derived_tags=derived_tags,
        user_tags=user_tags,
        user_overrides=user_overrides,
        user_deletions=list(deleted_axes),
    )


def iter_axis_values(axis: str) -> tuple[str, ...]:
    """Return the allowed value keys for ``axis`` (validated)."""
    return VALUE_LIST_BY_AXIS[validate_axis_key(axis)]


def taxonomy_summary() -> dict[str, Any]:
    """Return the whole taxonomy as a JSON-friendly structure for the UI."""
    return {
        "axes": [
            {
                "axis": axis,
                "label": label_for(axis),
                "values": [
                    {"key": key, "label": label_for(key)}
                    for key in VALUE_LIST_BY_AXIS[axis]
                ],
            }
            for axis in AXES
        ],
        "precedence": [
            "user_confirmed",
            "user_override",
            "user_unvetted",
            "derived",
        ],
        "derived_confidence_threshold": DERIVED_CONFIDENCE_THRESHOLD,
    }

