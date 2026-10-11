# Initial Technology Source Notes

Checked on 2026-10-05. These links support initial implementation choices; confirm service terms and versions before shipping integrations.

- [MLX installation guide](https://github.com/ml-explore/mlx/blob/main/docs/src/install.rst): MLX targets Apple silicon and documents current Python/macOS requirements.
- [LM Studio local server](https://lmstudio.ai/docs/developer/core/server): local REST and OpenAI-compatible server endpoints are available.
- [LM Studio tool use](https://lmstudio.ai/docs/developer/openai-compat/tools): model tool calls are requests for application-mediated functions; the model does not execute tools itself.
- [Ollama OpenAI compatibility](https://github.com/ollama/ollama/blob/main/docs/api/openai-compatibility.mdx): local Ollama exposes an OpenAI-compatible chat API at `http://localhost:11434/v1`.
- [Ollama local API](https://github.com/ollama/ollama/blob/main/docs/api.md): its loopback `/api/pull` endpoint streams model download progress. ResearchOS uses this only against a local Ollama server and only for its curated small-model list.
- [Ollama Qwen3 4B](https://ollama.com/library/qwen3:4b), [Gemma 3 4B](https://ollama.com/library/gemma3:4b), and [Llama 3.2 3B](https://ollama.com/library/llama3.2:3b): current small-model tags and published download sizes used by the in-app catalog.
- [Crossref REST API](https://api.crossref.org/): public scholarly metadata API with works search and pagination.
- [Europe PMC RESTful Web Service](https://europepmc.org/RestfulWebService): public search API for publication records, abstracts, open-access full-text links, and other literature metadata.
- [OpenAlex API search documentation](https://help.openalex.org/api/searching/): broad works search across scholarly metadata and, for some records, full text. Casual API requests work without a key; OpenAlex also offers a free account tier with a daily usage budget.
- [Playwright browser docs](https://playwright.dev/docs/browsers): Playwright can install a Chromium browser for controlled page reading.
- [Ollama web search API](https://ollama.com/blog/web-search): alternative web search exists but requires an account API key, so it is not the default no-account path for v1.

OpenAlex and Europe PMC endpoints were checked against their official API documentation when these connectors were implemented. The v1 design does not depend on any one provider. arXiv remains a possible later connector.
