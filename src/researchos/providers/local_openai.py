import asyncio
import time
from contextlib import asynccontextmanager

from openai import AsyncOpenAI

from researchos import store
from researchos.config import settings


MODEL_ROLE_SETTINGS = {
    "research": "model_role_research",
    "pdf_analysis": "model_role_pdf_analysis",
    "chat": "model_role_chat",
}


class LocalInferenceQueue:
    """Serialize local model work so role-specific models take turns in memory."""

    _lock = asyncio.Lock()
    _waiting = 0
    _active = ""
    _stats: dict[str, dict[str, int | float]] = {}

    @classmethod
    @asynccontextmanager
    async def slot(cls, task: str):
        cls._waiting += 1
        entered = False
        try:
            async with cls._lock:
                cls._waiting -= 1
                entered = True
                cls._active = task
                try:
                    yield
                finally:
                    cls._active = ""
        finally:
            if not entered:
                cls._waiting -= 1

    @classmethod
    def status(cls) -> dict[str, object]:
        return {"active": cls._active, "waiting": cls._waiting,
                "policy": "one local model task at a time", "usage": {key: dict(value) for key, value in cls._stats.items()}}

    @classmethod
    def record(cls, task: str, elapsed_seconds: float, input_tokens: int = 0, output_tokens: int = 0,
               *, failed: bool = False) -> None:
        usage = cls._stats.setdefault(task, {"calls": 0, "failures": 0, "seconds": 0.0,
                                             "input_tokens": 0, "output_tokens": 0})
        usage["calls"] += 1
        usage["failures"] += int(failed)
        usage["seconds"] = round(float(usage["seconds"]) + elapsed_seconds, 2)
        usage["input_tokens"] += input_tokens
        usage["output_tokens"] += output_tokens


class LocalOpenAIProvider:
    """Client for a localhost OpenAI-compatible inference server."""

    def __init__(self, *, timeout: float | None = None, role: str = "shared") -> None:
        self.role = role
        self.client = AsyncOpenAI(
            base_url=settings.model_base_url,
            api_key=settings.model_api_key,
            timeout=timeout or settings.request_timeout_seconds,
        )

    async def available_models(self) -> list[str]:
        response = await self.client.models.list()
        return [model.id for model in response.data]

    async def complete(self, system: str, user: str, *, model: str | None = None,
                       temperature: float = 0.2, max_tokens: int = 1600) -> str:
        role_setting = MODEL_ROLE_SETTINGS.get(self.role)
        selected = model or (store.get_app_setting(role_setting) if role_setting else None) or settings.model_name
        if not selected:
            models = await self.available_models()
            if not models:
                raise RuntimeError("No model is loaded in the local model server")
            selected = models[0]
        started = time.perf_counter()
        try:
            async with LocalInferenceQueue.slot(self.role):
                from researchos.paper_ranker import ranker
                if ranker.loaded:
                    await asyncio.to_thread(ranker.unload)
                response = await self.client.chat.completions.create(
                    model=selected,
                    messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
        except Exception:
            LocalInferenceQueue.record(self.role, time.perf_counter() - started, failed=True)
            raise
        usage = response.usage
        LocalInferenceQueue.record(self.role, time.perf_counter() - started,
                                   int(usage.prompt_tokens or 0) if usage else 0,
                                   int(usage.completion_tokens or 0) if usage else 0)
        return response.choices[0].message.content or ""

    async def close(self) -> None:
        await self.client.close()
