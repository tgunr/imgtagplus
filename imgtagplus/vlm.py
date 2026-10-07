"""Florence-2 integration used for caption-driven tagging.

This module adapts Florence's rich text generation output into the tag-shaped
results expected elsewhere in the application and carries a few narrowly scoped
compatibility shims for the pinned transformers stack.
"""

import gc
import logging
import os
from pathlib import Path

from PIL import Image

log = logging.getLogger(__name__)

# Pin reviewed Florence repository revisions so trust_remote_code=True does not
# float to the latest remote state. Base and large do not currently share the
# same commit history, so the loader must resolve revisions per model variant.
FLORENCE_MODEL_REVISIONS = {
    "microsoft/Florence-2-base": "5ca5edf5bd017b9919c05d08aebef5e4c7ac3bac",
    "microsoft/Florence-2-large": "21a599d414c4d928c9032694c424fb94458e3594",
}
FLORENCE_GENERATION_BEAMS = 3

ONNX_MODEL_REVISIONS: dict[str, str] = {
    "onnx-community/Florence-2-base-ft": "refs/pr/1",
    "onnx-community/Florence-2-large-ft": "refs/pr/1",
}


def _validate_florence_transformers_version(version: str) -> None:
    """Raise a clear error when Florence is used with unsupported transformers versions."""
    major, minor = (int(x) for x in version.split(".")[:2])
    if (major, minor) >= (5, 0):
        raise RuntimeError(
            "Florence models require transformers>=4.44.2,<5.0.0. "
            f"Detected {version}. "
            "Please install a supported version (for example: pip install 'transformers>=4.44.2,<5.0.0')."
        )


def _resolve_florence_revision(model_id: str) -> str | None:
    """Return a pinned revision for known Florence variants.

    Unknown Florence IDs are left unpinned rather than forced onto the base
    revision, which can make processor/model files 404 as seen with `large`.
    """
    return FLORENCE_MODEL_REVISIONS.get(model_id)


def _florence_pretrained_kwargs(model_id: str, cache_dir: Path) -> dict[str, object]:
    """Build shared kwargs for Florence processor/model loading."""
    kwargs: dict[str, object] = {
        "cache_dir": str(cache_dir),
    }
    # SECURITY: trust_remote_code executes Python from the HF model repo.
    # We only enable it for known model IDs with pinned revisions.
    revision = _resolve_florence_revision(model_id)
    if model_id in FLORENCE_MODEL_REVISIONS:
        kwargs["trust_remote_code"] = True
        if revision:
            kwargs["revision"] = revision
    else:
        log.warning(
            "Model %s is not in the known Florence model list — "
            "trust_remote_code will NOT be enabled.",
            model_id,
        )
    return kwargs

class FlorenceTagger:
    """Caption-first tagger backed by Microsoft Florence-2.

    Florence produces free-form descriptions rather than CLIP-style logits, so
    this adapter focuses on choosing a workable runtime and reshaping captions
    into ordered keyword tags for the rest of the pipeline.
    """

    def __init__(
        self,
        model_id: str = "microsoft/Florence-2-base",
        model_dir: Path | None = None,
        accelerator: str | None = None,
    ) -> None:
        self._model_id = model_id
        self._accelerator = accelerator
        if model_dir is None:
            # Fallback to local project directory if home cache is not writable
            try:
                model_dir = Path.home() / ".cache" / "imgtagplus"
                model_dir.mkdir(parents=True, exist_ok=True)
                # Test write access
                test_file = model_dir / ".write_test"
                test_file.touch()
                test_file.unlink()
            except (PermissionError, OSError):
                log.warning(f"Could not use {model_dir} for cache. Falling back to local .cache directory.")
                model_dir = Path(__file__).parent.parent / ".cache" / "imgtagplus"
                model_dir.mkdir(parents=True, exist_ok=True)

        self._model_dir = model_dir

        # Keep processor/model downloads (and the trust_remote_code module cache)
        # in the same writable cache root, before any HF library is imported.
        from imgtagplus.hfcache import point_hf_caches_at

        point_hf_caches_at(self._model_dir)

        import torch

        # ── Compatibility shim for Florence-2 on transformers 4.44.x ─────────
        # Florence-2's remote code currently assumes several attributes exist
        # during processor/model initialization that are absent or not yet set
        # on upstream transformers objects when loaded in this project.
        #
        # These patches are intentionally narrow and paired with the pinned
        # `FLORENCE_REMOTE_CODE_REVISION` above. If Florence-2 or transformers
        # is upgraded, this block should be re-validated before the pin or the
        # patches are changed.
        import transformers
        from transformers import AutoModelForCausalLM, AutoProcessor
        _validate_florence_transformers_version(transformers.__version__)
        _tf_version = tuple(int(x) for x in transformers.__version__.split(".")[:2])
        if _tf_version >= (4, 44) and _tf_version < (5, 0):
            # 1. Patch TokenizersBackend for processor initialization
            try:
                from transformers.tokenization_utils_tokenizers import TokenizersBackend
                if not hasattr(TokenizersBackend, "additional_special_tokens"):
                    TokenizersBackend.additional_special_tokens = property(
                        lambda self: getattr(self, "_additional_special_tokens", [])
                    )
                    log.debug("Patched TokenizersBackend.additional_special_tokens")
            except ImportError:
                pass

            # 2. Patch PretrainedConfig for model config initialization
            from transformers.configuration_utils import PretrainedConfig
            _orig_config_getattribute = PretrainedConfig.__getattribute__

            def _patched_config_getattribute(self, item):
                try:
                    return _orig_config_getattribute(self, item)
                except AttributeError:
                    if item == "forced_bos_token_id":
                        return None
                    raise
            PretrainedConfig.__getattribute__ = _patched_config_getattribute

            # 3. Patch PreTrainedModel for model instance initialization
            # Florence-2's @property '_supports_sdpa' / '_supports_flash_attn_2' 
            # fail during __init__ because they access self.language_model before it exists.
            from transformers.modeling_utils import PreTrainedModel
            _orig_model_getattribute = PreTrainedModel.__getattribute__

            def _patched_model_getattribute(self, item):
                try:
                    return _orig_model_getattribute(self, item)
                except AttributeError:
                    # If these specific properties fail, it's usually because language_model is missing
                    if item in ("_supports_sdpa", "_supports_flash_attn_2"):
                        return False
                    raise
            PreTrainedModel.__getattribute__ = _patched_model_getattribute
            log.debug("Applied full Florence-2 compatibility triple-patch (Tokenizer/Config/Model).")
        else:
            log.warning(
                "Untested transformers version %s — Florence-2 compatibility patches skipped. "
                "If model loading fails, try transformers>=4.44.2,<5.0.0.",
                transformers.__version__,
            )

        # Decide on the device and precision
        self.device = "cpu"
        self.dtype = torch.float32
        self.is_onnx = False

        if self._accelerator:
            self.device = self._accelerator
            if self.device == "cuda":
                self.dtype = torch.float16
        elif torch.cuda.is_available():
            self.device = "cuda"
            self.dtype = torch.float16
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            self.device = "mps"
            self.dtype = torch.float32

        if self.device == "cpu":
            log.info(f"CPU environment detected. Attempting to load ONNX optimized {self._model_id} via Optimum...")
            try:
                from optimum.onnxruntime import ORTModelForConditionalGeneration
                onnx_model_id = f"onnx-community/{self._model_id.split('/')[-1]}-ft"
                # SECURITY: trust_remote_code executes Python from the HF model repo.
                # We only enable it for known model IDs with pinned revisions.
                onnx_revision = ONNX_MODEL_REVISIONS.get(onnx_model_id)
                self.processor = AutoProcessor.from_pretrained(
                    onnx_model_id,
                    trust_remote_code=True,
                    cache_dir=str(self._model_dir),
                    **({"revision": onnx_revision} if onnx_revision else {}),
                )
                self.model = ORTModelForConditionalGeneration.from_pretrained(
                    onnx_model_id,
                    cache_dir=str(self._model_dir),
                )
                self.is_onnx = True
                log.info("Successfully loaded ONNX CPU pathway.")
            except ImportError:
                log.warning("Optimum ONNX not available. Falling back to native PyTorch CPU inference with SDPA...")
                pretrained_kwargs = _florence_pretrained_kwargs(self._model_id, self._model_dir)
                self.processor = AutoProcessor.from_pretrained(self._model_id, **pretrained_kwargs)
                self.model = AutoModelForCausalLM.from_pretrained(
                    self._model_id, 
                    torch_dtype=self.dtype, 
                    attn_implementation="eager",
                    low_cpu_mem_usage=False,
                    device_map=None,
                    **pretrained_kwargs,
                )
        else:
            log.info(
                "GPU environment detected. Loading native %s on %s with eager attention...",
                self._model_id,
                self.device,
            )
            pretrained_kwargs = _florence_pretrained_kwargs(self._model_id, self._model_dir)
            self.processor = AutoProcessor.from_pretrained(self._model_id, **pretrained_kwargs)
            self.model = AutoModelForCausalLM.from_pretrained(
                self._model_id, 
                torch_dtype=self.dtype,
                attn_implementation="eager",
                low_cpu_mem_usage=False,
                device_map=None,
                **pretrained_kwargs,
            ).to(self.device)

        if not self.is_onnx:
            self.model.eval()

    def unload(self) -> None:
        """Drop model references and clear accelerator caches when possible."""
        self.model = None
        self.processor = None

        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            # torch.mps.empty_cache() is available in newer PyTorch versions.
            try:
                torch.mps.empty_cache()
            except AttributeError:
                pass

        gc.collect()
        log.info(f"Unloaded {self._model_id}")

    def tag_image(self, image_path: Path, max_tags: int = 15) -> list[tuple[str, float]]:
        """Generate a detailed caption, then turn it into keyword-style tags."""
        image = self._load_image(image_path)

        prompt = "<DETAILED_CAPTION>"
        inputs = self.processor(text=prompt, images=image, return_tensors="pt")
        inputs = {k: v.to(self.device, self.dtype if k == "pixel_values" else None) for k, v in inputs.items()}

        log.debug(f"Running inference on {image_path.name}")

        import torch
        with torch.no_grad():
            generated_ids = self.model.generate(
                input_ids=inputs["input_ids"],
                pixel_values=inputs["pixel_values"],
                max_new_tokens=1024,
                early_stopping=False,
                do_sample=False,
                num_beams=FLORENCE_GENERATION_BEAMS,
                use_cache=False,
            )

        generated_text = self.processor.batch_decode(generated_ids, skip_special_tokens=False)[0]
        # Clean up output
        parsed = self.processor.post_process_generation(
            generated_text,
            task="<DETAILED_CAPTION>",
            image_size=(image.width, image.height)
        )

        caption = parsed["<DETAILED_CAPTION>"].strip()

        log.debug(f"Generated caption: {caption}")

        keywords = self._extract_keywords_from_caption(caption)

        # Florence does not emit per-keyword confidences here, so downstream code
        # gets stable pseudo-scores instead of a different result shape.
        results = [(kw, 1.0) for kw in keywords[:max_tags]]

        if results is None or len(results) == 0:
            if caption:
                # Preserve some usable output for metadata writers even when the
                # keyword heuristic finds nothing interesting.
                results = [(caption[:100], 1.0)]

        return results

    def _extract_keywords_from_caption(self, caption: str) -> list[str]:
        """Convert a generated caption into ordered, deduplicated keyword tags."""
        import string

        translator = str.maketrans("", "", string.punctuation)
        clean = caption.translate(translator).lower()

        words = clean.split()

        stopwords = {
            "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
            "with", "of", "is", "are", "was", "were", "this", "that", "it", "there",
            "their", "they", "its", "photo", "image", "picture", "shows", "showing"
        }

        keywords = [w for w in words if w not in stopwords and len(w) > 2]

        seen = set()
        unique_keywords = []
        for kw in keywords:
            if kw not in seen:
                seen.add(kw)
                unique_keywords.append(kw)

        # Preserve adjacent word pairs as compound tags when both words
        # survived filtering individually.
        keyword_set = set(unique_keywords)
        words_in_caption = caption.lower().split()
        for i in range(len(words_in_caption) - 1):
            w1 = words_in_caption[i].strip(".,;:!?\"'()[]")
            w2 = words_in_caption[i + 1].strip(".,;:!?\"'()[]")
            if w1 in keyword_set and w2 in keyword_set:
                compound = f"{w1} {w2}"
                if compound not in keyword_set:
                    unique_keywords.append(compound)
                    keyword_set.add(compound)

        return unique_keywords

    @staticmethod
    def _load_image(path: Path) -> Image.Image:
        """Load an image."""
        img = Image.open(path).convert("RGB")
        return img
