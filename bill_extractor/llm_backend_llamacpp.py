"""LlamaCpp LLM backend — CPU-optimised inference via llama-cpp-python.

Install the optional dep before using:
    pip install -e ".[llamacpp]"
"""
from __future__ import annotations

from pathlib import Path

from loguru import logger


class LlamaCppBackend:
    """LLMBackend implementation using llama-cpp-python (GGUF models, CPU-only)."""

    def __init__(
        self,
        model_path: str | Path,
        n_threads: int = 4,
        n_ctx: int = 4096,
        verbose: bool = False,
    ) -> None:
        try:
            from llama_cpp import Llama
        except ImportError as exc:
            raise ImportError(
                "llama-cpp-python is not installed. "
                "Run: pip install -e '.[llamacpp]'"
            ) from exc

        resolved = Path(model_path).expanduser().resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"GGUF model not found: {resolved}")

        logger.info("LlamaCppBackend: {} ({} threads, ctx={})", resolved.name, n_threads, n_ctx)
        self._llm = Llama(
            model_path=str(resolved),
            n_threads=n_threads,
            n_ctx=n_ctx,
            n_gpu_layers=0,  # CPU-only
            verbose=verbose,
        )

    def generate(self, prompt: str, max_new_tokens: int) -> str:
        resp = self._llm.create_chat_completion(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_new_tokens,
            temperature=0.0,
        )
        text = resp["choices"][0]["message"]["content"].strip()
        if not text:
            raise RuntimeError("LlamaCppBackend returned empty response.")
        logger.debug("Generated text ({} chars):\n{}", len(text), text)
        return text
