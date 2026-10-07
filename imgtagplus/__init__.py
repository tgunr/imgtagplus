"""ImgTagPlus — Bulk AI image tagger using CLIP (ONNX)."""

from imgtagplus.hfcache import ensure_hf_cache_env

__version__ = "1.0.0"

# Correct the Hugging Face cache before any HF library is imported so a stale
# HF_HOME (for example, an external volume that is not mounted) cannot break
# model downloads with a PermissionError.
ensure_hf_cache_env()
