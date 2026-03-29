"""LLM backend abstraction for bill extraction."""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    pass


@runtime_checkable
class LLMBackend(Protocol):
    """Minimal protocol for LLM inference backends.

    A backend receives a plain-text prompt string and returns the model's
    completion string. Chat formatting, tokenisation, and device management
    are the backend's responsibility.
    """

    def generate(self, prompt: str, max_new_tokens: int) -> str: ...


def create_backend(backend_type: str, **kwargs) -> LLMBackend:
    """Factory: construct an LLMBackend by name.

    backend_type == "transformers"  →  TransformersBackend(**kwargs)
        kwargs: model_name (str), device (torch.device), dtype (torch.dtype)

    backend_type == "llamacpp"      →  LlamaCppBackend(**kwargs)
        kwargs: model_path (str|Path), n_threads (int), n_ctx (int)
    """
    if backend_type == "transformers":
        from .bill_parser import TransformersBackend
        return TransformersBackend(**kwargs)
    if backend_type == "llamacpp":
        from .llm_backend_llamacpp import LlamaCppBackend
        return LlamaCppBackend(**kwargs)
    raise ValueError(f"Unknown LLM backend type: {backend_type!r}")
