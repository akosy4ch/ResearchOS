"""Optional local SPECTER2 ranking for scholarly paper discovery."""

from __future__ import annotations

import os
import threading
import asyncio
import time
from pathlib import Path
from typing import Any

from researchos.config import settings


BASE_MODEL = "allenai/specter2_base"
QUERY_ADAPTER = "allenai/specter2_adhoc_query"
PAPER_ADAPTER = "allenai/specter2"
MAX_SEQUENCE_LENGTH = 512
BATCH_SIZE = 8


def configure_huggingface_cache() -> Path:
    """Keep model weights under ResearchOS's local data directory."""
    cache = (settings.data_dir / "models" / "huggingface").resolve()
    cache.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(cache)
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    return cache


def dependency_status() -> dict[str, Any]:
    import importlib.util

    packages = {name: importlib.util.find_spec(name) is not None
                for name in ("torch", "transformers", "adapters")}
    cache = configure_huggingface_cache() / "hub"
    cache_names = (
        "models--allenai--specter2_base",
        "models--allenai--specter2_adhoc_query",
        "models--allenai--specter2",
    )
    cached = all((cache / name / "snapshots").is_dir()
                 and any((cache / name / "snapshots").iterdir()) for name in cache_names)
    return {"dependencies": packages, "dependencies_ready": all(packages.values()),
            "weights_cached": cached, "cache_path": str(cache.parent)}


class Specter2Ranker:
    """One lazily loaded SPECTER2 model with task-specific query/paper adapters."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._model = None
        self._tokenizer = None
        self._torch = None
        self._device = "not loaded"

    @property
    def loaded(self) -> bool:
        return self._model is not None

    @property
    def device(self) -> str:
        return self._device

    def load(self) -> None:
        with self._lock:
            if self._model is not None:
                return
            configure_huggingface_cache()
            import torch
            from adapters import AutoAdapterModel
            from transformers import AutoTokenizer

            tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, trust_remote_code=False)
            model = AutoAdapterModel.from_pretrained(BASE_MODEL, trust_remote_code=False)
            query_adapter_name = model.load_adapter(QUERY_ADAPTER, source="hf", load_as="specter2_query")
            paper_adapter_name = model.load_adapter(PAPER_ADAPTER, source="hf", load_as="specter2_paper")
            model.set_active_adapters(paper_adapter_name)
            model.eval()
            device = "mps" if torch.backends.mps.is_available() else "cpu"
            model.to(device)
            self._tokenizer = tokenizer
            self._model = model
            self._torch = torch
            self._query_adapter = query_adapter_name
            self._paper_adapter = paper_adapter_name
            self._device = device

    def unload(self) -> None:
        """Release live tensor memory before a chat model starts using the Mac."""
        import gc

        with self._lock:
            torch = self._torch
            self._model = None
            self._tokenizer = None
            self._torch = None
            self._device = "not loaded"
            gc.collect()
            if torch and torch.backends.mps.is_available():
                torch.mps.empty_cache()

    def _encode(self, texts: list[str], adapter: str):
        torch = self._torch
        self._model.set_active_adapters(adapter)
        chunks = []
        for start in range(0, len(texts), BATCH_SIZE):
            batch = self._tokenizer(
                texts[start:start + BATCH_SIZE], padding=True, truncation=True,
                max_length=MAX_SEQUENCE_LENGTH, return_tensors="pt", return_token_type_ids=False,
            )
            batch = {key: value.to(self._device) for key, value in batch.items()}
            with torch.inference_mode():
                output = self._model(**batch)
                vectors = output.last_hidden_state[:, 0, :]
                chunks.append(torch.nn.functional.normalize(vectors, p=2, dim=1))
        return torch.cat(chunks, dim=0)

    def rank(self, query: str, papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not papers:
            return []
        with self._lock:
            self.load()
            paper_texts = []
            for paper in papers:
                title = str(paper.get("title") or "").strip()
                abstract = str(paper.get("abstract") or "").strip()
                paper_texts.append(f"{title}{self._tokenizer.sep_token}{abstract}"[:12000])
            try:
                query_vector = self._encode([query[:2000]], self._query_adapter)
                paper_vectors = self._encode(paper_texts, self._paper_adapter)
            except Exception:
                if self._device != "mps":
                    raise
                self._model.to("cpu")
                self._device = "cpu"
                query_vector = self._encode([query[:2000]], self._query_adapter)
                paper_vectors = self._encode(paper_texts, self._paper_adapter)
            scores = (paper_vectors @ query_vector.T).squeeze(1).detach().cpu().tolist()
            ranked = [{**paper, "semantic_score": float(score)}
                      for paper, score in zip(papers, scores)]
        ranked.sort(key=lambda paper: (-paper["semantic_score"],
                                      -int(paper.get("year") or 0),
                                      str(paper.get("title") or "").casefold()))
        return ranked


ranker = Specter2Ranker()


async def rank_papers(query: str, papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rank retrieved papers without blocking the web server's event loop."""
    from researchos.providers.local_openai import LocalInferenceQueue

    started = time.perf_counter()
    try:
        async with LocalInferenceQueue.slot("paper ranking · SPECTER2"):
            return await asyncio.to_thread(ranker.rank, query, papers)
    finally:
        LocalInferenceQueue.record("paper_ranking", time.perf_counter() - started)
