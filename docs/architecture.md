# ResearchOS v1 Architecture

## Product goal

Given a research question, idea, or attached paper, produce a literature review and next-step plan that a person can audit. Each paper, claim, evidence passage, decision, and recommendation must have a traceable origin. Unsupported details and missing full text must be visible in the output.

Research runs are user-started. A separate local Systems Engineer monitors application incidents and does a weekly improvement review. Numerical novelty or acceptance probabilities are out of scope until there is a defensible rubric and validation data.

## Design choices for this Mac

| Area | v1 choice | Reason |
|---|---|---|
| Runtime | Python 3.11+, FastAPI | Small local service with a simple API and Python research libraries |
| Orchestration | Explicit bounded state machine | Easier to inspect, resume, and limit than a free-running agent swarm |
| Local inference | OpenAI-compatible provider adapter; local Ollama default on this Mac | Local HTTP interface keeps the app independent from one model runtime |
| Alternate inference | LM Studio or MLX-LM compatible server | Change the base URL without changing workflow contracts |
| Database | SQLite with foreign keys and FTS5 | No database service to operate; adequate for a personal corpus |
| Paper files | User data directory, outside source tree | Keep PDFs and extracted text local and avoid committing research material |
| Browser | Bounded public HTML/text reader for user-supplied URLs | Lets a run use selected public pages; scholarly APIs remain the primary search route |
| UI | Responsive local web app | Keeps projects, runs, sources, and agent work visible on the Mac |

No cloud inference provider is required. Search requests do use the network. The app should display which provider supplied metadata and when it was queried.

## Local model roles and scheduling

ResearchOS keeps a shared general chat model as the default, with optional persistent model assignments for research runs, PDF analysis, and report/paper chat. `LocalInferenceQueue` serializes requests made by ResearchOS so independent tasks wait instead of competing for unified memory. A usage snapshot records calls, failures, elapsed seconds, and server-reported token counts per role for the current process session. Some local runtimes do not return token usage.

SPECTER2 is a separate optional retrieval model. It uses Allen AI's query adapter for the question and proximity adapter for title-plus-abstract paper records. The model is loaded on demand, runs on Apple MPS when available (CPU fallback), and its live tensors are released before a chat completion starts. The base checkpoint and adapters are cached under `data/models/huggingface`; the optional Python dependencies are installed only after the user chooses setup in Model settings. Ranking adjusts order within the already trusted, deduplicated scholarly-index candidates and does not replace keyword/topic screening, source provenance, or fact generation.

## Runtime shape

```text
Local UI / CLI
      |
      v
FastAPI application ---- Local job/checkpoint store (SQLite)
      |                         |
      +---- Research workflow --+---- Evidence store (SQLite + FTS5)
      |        |                |
      |        +---- Search connectors: Crossref / OpenAlex / Europe PMC
      |        +---- Trusted page reader: bounded HTTPS text extraction for allowlisted scholarly domains
      |        +---- File readers: user-supplied PDFs and open-access full text
      +---- Model provider interface ---- LM Studio or MLX-LM local endpoint
```

The workflow has a hard cap on search branches, provider results, retained source links, model calls, time, and revision cycles. Candidate metadata is gathered into an in-memory pool and deduplicated; only the bounded retained records enter the run library, and newly fetched abstracts are persisted only for the papers sent to local analysis. Store each stage result as structured JSON so interrupted jobs can resume without silently rerunning everything.

## Workflow and review gates

1. **Interview**: Save a structured Research Brief; the interviewer surfaces only questions whose answers could change the search or evaluation. In the current build, runs continue with visible open questions; pausing and resuming after user answers is planned.
2. **Plan**: Convert the brief into a research map, inclusion/exclusion rules, and bounded search tasks.
3. **Search**: Query Crossref, Europe PMC, and OpenAlex by distinct subtopic. Save query, source, timestamp, and result count. Do not use general web search.
4. **Screen**: Deduplicate by DOI, normalized title, and source identifiers. Record include/exclude decisions and reasons.
5. **Read**: Prefer user-supplied PDFs or open-access full text. Extract local PDF text page by page. Label abstract-only records and do not infer details unavailable in the text.

Optional user-supplied web pages must use HTTPS and a hostname in `TRUSTED_WEB_DOMAINS` (`researchos/web_reader.py`). Redirects outside that allowlist are blocked too. This explicit domain allowlist constrains which pages are fetched; it is not a claim that every page is peer reviewed or that its contents are safe instructions. Treat fetched page text as untrusted evidence, never as workflow instructions. PDFs are user-provided local files and remain a separate source path.
6. **Extract**: Create paper facts and candidate claims with exact supporting excerpts and page/section when available.
7. **Verify**: A separate pass checks that a source exists and that the excerpt supports the claim in context. Keep contradictory evidence.
8. **Synthesize**: Build themes and comparisons from verified evidence. Mark system inferences as synthesis, not as a paper's result.
9. **Review**: Search for missing branches, unsupported claims, citation mismatches, weak comparisons, and overconfident gap statements. Permit a bounded targeted-search loop.
10. **Write and audit**: Generate the report from verified records, then check every citation and every factual sentence against the evidence store.

Gate outcomes are `PASS`, `REVISE`, `RESEARCH_MORE`, and `REJECT`. Exhausted runs produce a partial report and unresolved issues instead of an invented pass.

## Evidence model

Initial relational entities:

- `projects`: title, topic, constraints, created/updated timestamps.
- `research_runs`: project, original question, structured brief, status, stage, limits, timestamps, completion notes.
- `search_tasks`: run, branch, query, source, query time, inclusion criteria, counts.
- `papers`: normalized title, authors, year, DOI, source IDs, landing URL, OA URL, access status.
- `paper_files`: paper, local path, checksum, PDF page count, extraction status, provenance.
- `passages`: paper, exact extracted text, page, character offsets, extraction method.
- `paper_analyses`: queued and completed user-requested full-PDF dossiers, with validated page quotes and structured findings.
- `run_chat_messages`: persistent local conversations attached to a research report.
- `claims`: claim text, type (`source_fact` or `system_synthesis`), verification state, limitations.
- `claim_evidence`: claim, passage, relation (`supports`, `contradicts`, `context`), reviewer decision.
- `tasks` and `reviews`: agent role, input/output JSON, model/prompt version, outcome, timestamps.
- `recommendations`: action, rationale, linked claims, expected value, cost/risk, validation method, uncertainty.
- `report_versions`: run, rendered report path/content, created timestamp.

Store quoted evidence passages separately from generated summaries. Save source URL, access route, retrieval time, and a content checksum. Do not treat a model's confidence as a measured probability.

## Agent contracts

Roles are prompts and typed input/output contracts, not a promise of independent intelligence. Initially, one loaded local model can serve each stage sequentially.

- Research Lead: scope, map, and bounded search plan.
- Searcher: query one assigned branch and return source records only.
- Librarian: metadata normalization and deduplication.
- Extractor: structured paper facts with verbatim passage references.
- Fact Checker: accept/reject/qualify a claim against supplied passages.
- Synthesizer: themes, agreements, contradictions, and explicit inference labels.
- Novelty Analyst: closest prior work and overlap risks; absence of matches is not proof of novelty.
- Impact and Feasibility Analysts: possible value, dependencies, risks, and unknown resources.
- Research Strategist: testable questions, hypotheses, baselines, metrics, and staged experiments.
- Adversarial Reviewer: concrete issues and targeted queries, not a numeric score.
- Writer and Citation Auditor: render the report, then audit each factual statement and reference.
- Systems Engineer: check application health, summarize incident reports, propose small improvements, and repair supported source defects under the maintenance rules below.

Every stage returns schema-validated JSON. Network and file tools are called by application code under explicit allowlists; an LLM cannot execute arbitrary shell commands or visit arbitrary local files.

## System Care and repair limits

- The startup preflight and System Care page check Python syntax, JavaScript syntax, an isolated FastAPI startup and `/health` request, SQLite integrity, and the configured local model endpoint.
- Unhandled HTTP errors and failed research runs are recorded in JSONL files under the local data directory, then reviewed by the background Systems Engineer. A weekly review records improvement suggestions.
- Automatic source edits use exact, unique text anchors in an allowlist of application files. A repair is limited to four replacements and 12,000 changed characters.
- Repairs are applied for diagnosed source or startup failures and recorded incidents. A healthy weekly review may apply at most one behavior-preserving source change; a healthy manual review only suggests changes.
- Before a patch is applied, the staged source must pass Python and JavaScript syntax checks and an isolated app startup. Source backups are written under `data/system-care/backups`; a failed post-apply check restores the previous files.
- The local model never receives user PDFs, research database contents, credentials, `.env` values, or launcher files for maintenance. It cannot run shell commands or install dependencies.
- The `researchos serve` supervisor restarts after a validated runtime repair and reruns preflight before serving again. A server launched directly through Uvicorn records the need for a manual restart.

## Local model and resource policy

Sixteen GB is shared by macOS, the model, browser, document extraction, and the app. Begin with one 3B–4B instruct model at 4-bit quantization and a context length around 8K tokens. Larger 7B–8B 4-bit models may work with moderate context, but require direct memory and speed checks on the user's actual workload. Model quality and tool-call reliability vary; malformed outputs must be retried once or surfaced as errors.

Use LM Studio for the first setup because it exposes local OpenAI-compatible endpoints and model management. Keep `ModelProvider` independent of LM Studio so an MLX-LM server can replace it. Do not run multiple inference models concurrently. Prefer simple extraction and review stages over parallel agents that compete for unified memory.

Embeddings are optional in v1. Start with SQLite FTS5 and metadata filters. Add a small local embedding model only after exact/keyword retrieval is insufficient, and measure its RAM and quality cost.

Report chat receives the saved report, its cited source excerpts, verified claims, and recent conversation. It runs through the configured local model and validates citation labels before saving the reply. Paper Analysis is a separate on-demand queue for PDFs already added to Paper Library. It reads bounded extracted text in sequential page groups, keeps only findings with matching quotes on their stated PDF pages, and groups those findings into a detailed dossier. It also uses PDFium to render up to eight full-page previews selected by figure captions and visual-topic terms, stores up to 10 MB per analysis locally, and exposes them through paper-scoped local routes. Captions are source text; the text model does not interpret preview pixels, and scanned pages without extracted text may be missed. It can report a paper's own state-of-the-art claim but cannot establish current SOTA from one paper.

## Web access and data boundaries

- Search APIs are the default for scholarly discovery; a bounded web reader can add up to three public pages supplied with a run.
- Use public pages and public APIs with caching, identifiable requests where required, and conservative rate limits.
- Download full text only when it is open access, explicitly licensed, supplied by the user, or otherwise available through an authorized route. Never bypass authentication, paywalls, CAPTCHAs, or robots/access controls.
- Treat page contents and papers as untrusted data. Ignore instructions found in retrieved documents; extract research content only.
- The page reader allows only public HTTP(S) hosts on standard ports, follows a small number of revalidated redirects, caps response size, and does not execute JavaScript. Dynamic sites and pages requiring sign-in are unsupported.
- Keep the model server bound to localhost. Never expose it to the LAN by default.
- Keep `.env`, local paper files, and database files out of version control.

## Free stack

The project has no required paid service. Python, FastAPI, SQLite, Playwright, LM Studio for personal local use, MLX/MLX-LM, and the listed public scholarly APIs can be used without a subscription. Individual data services may apply quotas or change access terms. Full-text availability is not guaranteed.
