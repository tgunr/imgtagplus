"""CLIP-based image tagger using ONNX Runtime.

Downloads the CLIP ViT-B/32 model (ONNX) on first use and caches it
locally.  Performs zero-shot classification against the tag vocabulary
defined in ``imgtagplus.tags``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

import numpy as np
from PIL import Image

log = logging.getLogger(__name__)

# Hugging Face repo hosting the ONNX-exported CLIP ViT-B/32.
_HF_REPO = "Xenova/clip-vit-base-patch32"
_VISUAL_MODEL_FILE = "onnx/vision_model.onnx"
_TEXT_MODEL_FILE = "onnx/text_model.onnx"
_TOKENIZER_FILE = "tokenizer.json"

# CLIP image pre-processing (ImageNet normalisation).
_MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
_STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)
_IMAGE_SIZE = 224

# CLIP tokenizer special-token IDs.
_SOT_TOKEN = 49406
_EOT_TOKEN = 49407
_CONTEXT_LENGTH = 77
_TAG_EMBED_BATCH_SIZE = 64
_TAG_EMBED_CACHE_PREFIX = "clip_tag_embeddings"
_LOGIT_SCALE = 100.0


# ---------------------------------------------------------------------------
# Minimal CLIP tokenizer (avoids heavy ``transformers`` dependency)
# ---------------------------------------------------------------------------

class _SimpleTokenizer:
    """Bare-minimum BPE tokenizer that reads the HF ``tokenizer.json``."""

    def __init__(self, tokenizer_path: Path) -> None:
        with open(tokenizer_path, encoding="utf-8") as fh:
            data = json.load(fh)

        # Build token -> id map from the vocabulary stored in the file.
        vocab_items = data.get("model", {}).get("vocab", {})
        if isinstance(vocab_items, dict):
            self._vocab: dict[str, int] = vocab_items
        else:
            self._vocab = {}

        # Merges (list of "token_a token_b" strings).
        merges_raw = data.get("model", {}).get("merges", [])
        self._merges: list[tuple[str, str]] = [
            tuple(m.split()) for m in merges_raw  # type: ignore[misc]
        ]
        self._bpe_ranks: dict[tuple[str, str], int] = {
            pair: i for i, pair in enumerate(self._merges)
        }

    # -- public API -----------------------------------------------------------

    def encode(self, text: str) -> list[int]:
        """Return token IDs for *text*, surrounded by SOT / EOT."""
        text = text.lower().strip()
        tokens: list[int] = [_SOT_TOKEN]
        for word in text.split():
            word_tokens = self._bpe(word)
            tokens.extend(word_tokens)
        tokens.append(_EOT_TOKEN)
        return tokens

    def tokenize(self, texts: list[str]) -> np.ndarray:
        """Tokenize a batch of strings into a padded int64 array."""
        batch = np.zeros((len(texts), _CONTEXT_LENGTH), dtype=np.int64)
        for i, text in enumerate(texts):
            ids = self.encode(text)[:_CONTEXT_LENGTH]
            batch[i, : len(ids)] = ids
        return batch

    # -- internals ------------------------------------------------------------

    def _bpe(self, token: str) -> list[int]:
        """Run byte-pair encoding on a single word."""
        # Add end-of-word marker used by CLIP's tokenizer.
        word: list[str] = list(token[:-1]) + [token[-1] + "</w>"]

        while len(word) > 1:
            pairs = [
                (word[j], word[j + 1]) for j in range(len(word) - 1)
            ]
            best = min(
                pairs,
                key=lambda p: self._bpe_ranks.get(p, float("inf")),
            )
            if best not in self._bpe_ranks:
                break

            new_word: list[str] = []
            i = 0
            while i < len(word):
                if (
                    i < len(word) - 1
                    and word[i] == best[0]
                    and word[i + 1] == best[1]
                ):
                    new_word.append(best[0] + best[1])
                    i += 2
                else:
                    new_word.append(word[i])
                    i += 1
            word = new_word

        ids: list[int] = []
        for piece in word:
            tok_id = self._vocab.get(piece)
            if tok_id is not None:
                ids.append(tok_id)
            else:
                # Fall back: encode each character individually.
                for ch in piece:
                    ch_id = self._vocab.get(ch, 0)
                    ids.append(ch_id)
        return ids


# ---------------------------------------------------------------------------
# Tagger
# ---------------------------------------------------------------------------

class Tagger:
    """Zero-shot image tagger backed by CLIP (ONNX).

    Parameters
    ----------
    model_dir:
        Directory to cache downloaded model files.  Defaults to
        ``~/.cache/imgtagplus``.
    accelerator:
        Preferred ONNX Runtime execution provider. When omitted, the CPU
        provider is used.
    """

    def __init__(self, model_dir: Path | None = None, accelerator: str | None = None) -> None:
        import onnxruntime as ort  # deferred so import errors are clear

        if model_dir is None:
            model_dir = Path.home() / ".cache" / "imgtagplus"
        self._model_dir = model_dir
        self._model_dir.mkdir(parents=True, exist_ok=True)

        # Align every HF cache env var with this root before HF libs are imported.
        from imgtagplus.hfcache import point_hf_caches_at

        point_hf_caches_at(self._model_dir)

        # Download model files from Hugging Face (cached after first run).
        visual_path = self._ensure_file(_VISUAL_MODEL_FILE)
        text_path = self._ensure_file(_TEXT_MODEL_FILE)
        tok_path = self._ensure_file(_TOKENIZER_FILE)

        log.info("Loading CLIP visual model …")
        sess_opts = ort.SessionOptions()
        sess_opts.inter_op_num_threads = os.cpu_count() or 1
        sess_opts.intra_op_num_threads = os.cpu_count() or 1

        providers = ["CPUExecutionProvider"]
        if accelerator == "cuda":
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        elif accelerator == "mps":
            providers = ["CoreMLExecutionProvider", "CPUExecutionProvider"]

        self._vis_session = ort.InferenceSession(
            str(visual_path),
            sess_options=sess_opts,
            providers=providers,
        )
        log.info("Loading CLIP text model …")
        self._txt_session = ort.InferenceSession(
            str(text_path),
            sess_options=sess_opts,
            providers=providers,
        )
        log.info("Loading tokenizer …")
        self._tokenizer = _SimpleTokenizer(tok_path)
        self._text_embeds: np.ndarray | None = None

    # -- public API -----------------------------------------------------------

    def precompute_tag_embeddings(self, tags: list[str]) -> None:
        """Pre-compute and cache normalised text embeddings for a tag list."""
        cache_path = self._tag_embedding_cache_path(tags)
        if cache_path.exists():
            self._text_embeds = np.load(cache_path).astype(np.float32)
            log.info("Loaded cached text embeddings from %s", cache_path)
            return

        log.info("Pre-computing text embeddings for %d tags …", len(tags))

        # Process tags in batches to stay within memory.
        all_embeds: list[np.ndarray] = []

        for start in range(0, len(tags), _TAG_EMBED_BATCH_SIZE):
            batch_tags = tags[start : start + _TAG_EMBED_BATCH_SIZE]
            # Prefix each tag with "a photo of " for better CLIP performance.
            prompts = [f"a photo of {t}" for t in batch_tags]
            input_ids = self._tokenizer.tokenize(prompts)

            # Determine correct input name.
            txt_input_name = self._txt_session.get_inputs()[0].name
            attention_mask = (input_ids != 0).astype(np.int64)

            feeds: dict[str, np.ndarray] = {txt_input_name: input_ids}
            # Supply attention_mask if model expects it.
            input_names = {inp.name for inp in self._txt_session.get_inputs()}
            if "attention_mask" in input_names:
                feeds["attention_mask"] = attention_mask

            outputs = self._txt_session.run(None, feeds)
            embeds = outputs[0]  # (batch, dim) or (batch, seq, dim)
            if embeds.ndim == 3:
                # Use the embedding at the EOT token position per sequence.
                # For simplicity, take the last non-padding position.
                eot_indices = attention_mask.sum(axis=1) - 1
                embeds = embeds[np.arange(embeds.shape[0]), eot_indices]

            all_embeds.append(embeds)

        self._text_embeds = np.concatenate(all_embeds, axis=0).astype(np.float32)
        # L2-normalise.
        norms = np.linalg.norm(self._text_embeds, axis=1, keepdims=True)
        norms = np.maximum(norms, 1e-8)
        self._text_embeds /= norms
        np.save(cache_path, self._text_embeds)
        log.info("Cached text embeddings at %s", cache_path)
        log.info("Text embeddings ready: shape %s", self._text_embeds.shape)

    def tag_image(
        self,
        image_path: Path,
        tags: list[str],
        threshold: float = 0.25,
        max_tags: int = 20,
    ) -> list[tuple[str, float]]:
        """Tag a single image.

        Returns a list of ``(tag, score)`` tuples sorted by descending
        confidence, filtered by *threshold* and capped at *max_tags*.
        """
        if self._text_embeds is None:
            self.precompute_tag_embeddings(tags)

        img = self._load_image(image_path)
        vis_input_name = self._vis_session.get_inputs()[0].name

        feeds: dict[str, np.ndarray] = {vis_input_name: img}
        # Supply pixel_values under alternate name if needed.
        vis_input_names = {inp.name for inp in self._vis_session.get_inputs()}
        if "pixel_values" in vis_input_names and vis_input_name != "pixel_values":
            feeds["pixel_values"] = img

        outputs = self._vis_session.run(None, feeds)
        img_embed = outputs[0].astype(np.float32)

        if img_embed.ndim == 3:
            img_embed = img_embed[:, 0, :]  # CLS token

        # L2-normalise.
        norm = np.linalg.norm(img_embed, axis=1, keepdims=True)
        norm = np.maximum(norm, 1e-8)
        img_embed /= norm

        # Cosine similarity (both already normalised).
        assert self._text_embeds is not None
        similarities = (img_embed @ self._text_embeds.T)[0]

        # Convert to pseudo-probabilities with a softmax-like scaling.
        # CLIP uses a learned temperature; we approximate with 100.
        logits = similarities * _LOGIT_SCALE
        # Also compute softmax for ranking.
        exp_logits = np.exp(logits - logits.max())
        softmax_scores = exp_logits / exp_logits.sum()

        # Combine: use softmax ranking but sigmoid for thresholding.
        ranked = np.argsort(-softmax_scores)
        results: list[tuple[str, float]] = []
        for idx in ranked:
            score = float(softmax_scores[idx])
            # Keep the best match even on weak images so callers are not forced
            # to special-case an empty result when CLIP produced a ranking.
            if score < threshold and len(results) > 0:
                break
            results.append((tags[int(idx)], round(score, 4)))
            if len(results) >= max_tags:
                break

        return results

    # -- internals ------------------------------------------------------------

    def _ensure_file(self, rel_path: str) -> Path:
        """Resolve a CLIP asset path, downloading it through the HF cache if needed."""
        from huggingface_hub import hf_hub_download

        log.debug("Ensuring model file: %s", rel_path)
        local = hf_hub_download(
            repo_id=_HF_REPO,
            filename=rel_path,
            cache_dir=str(self._model_dir),
        )
        return Path(local)

    def _tag_embedding_cache_path(self, tags: list[str]) -> Path:
        """Return the cache path keyed by the exact ordered tag vocabulary."""
        digest = hashlib.sha256("\n".join(tags).encode("utf-8")).hexdigest()[:16]
        return self._model_dir / f"{_TAG_EMBED_CACHE_PREFIX}_{digest}.npy"

    @staticmethod
    def _load_image(path: Path) -> np.ndarray:
        """Load, resize, and normalise an image for CLIP."""
        img = Image.open(path).convert("RGB")

        # Resize with centre crop.
        w, h = img.size
        scale = _IMAGE_SIZE / min(w, h)
        new_w, new_h = int(w * scale), int(h * scale)
        img = img.resize((new_w, new_h), Image.BICUBIC)

        # Centre crop.
        left = (new_w - _IMAGE_SIZE) // 2
        top = (new_h - _IMAGE_SIZE) // 2
        img = img.crop((left, top, left + _IMAGE_SIZE, top + _IMAGE_SIZE))

        arr = np.array(img, dtype=np.float32) / 255.0
        arr = (arr - _MEAN) / _STD
        # HWC -> NCHW
        arr = arr.transpose(2, 0, 1)[np.newaxis, ...]
        return arr
