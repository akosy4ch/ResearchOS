# ResearchOS Implementation Roadmap

## v1: evidence-first literature review

### Current implementation status

- Implemented: FastAPI service, responsive single-page app, SQLite project/run/paper/event/claim store, local OpenAI-compatible model client, persistent chat-model selection, task-specific model assignment for research/PDF/chat, a single local inference queue with per-task session usage counts, optional SPECTER2 semantic ranking for Find papers and research runs, Crossref, Europe PMC, and OpenAlex search, branch-balanced result selection and Crossref rate pacing, bounded research workflow, optional public web-page reading, project PDF attachment and page text extraction, structured per-run research brief, interviewer scope questions, focused search map, exact quote matching against supplied text, model fact-check, provisional novelty and impact/feasibility passes, research strategy and experiment-planning pass, adversarial review, source-linked report and library views, Markdown report export, System Care status page, incident log, startup preflight, weekly Systems Engineer suggestions, and staged reversible repairs for supported source and startup failures.
- In progress: interactive clarification-and-resume loop, durable job recovery/cancellation, per-branch screening records, broader open full-text acquisition and OCR, and source-side API error handling.
- Planned: official-source venue research, continuous discovery beyond System Care, calibrated analysis, portfolio discovery, and opportunity mining.

The researcher-focused gap analysis and model-role proposals are in [researcher-workflow-audit.md](researcher-workflow-audit.md). Highest-value next work is transparent inclusion/exclusion screening, a reproducible search protocol and query log, portable review exports, fuller table/OCR extraction, and human-reviewed retrieval/report evaluation.

### Slice 1 — local foundation

- FastAPI app, configuration, health endpoint, and local model provider adapter.
- SQLite schema and migrations for projects, runs, papers, passages, claims, and review decisions.
- Local data directory and clear ignore rules for PDFs, extracted files, database, and secrets.
- CLI/API operation with no frontend requirement.

**Done when:** the app starts locally, reports model availability, and can create a project/run without a cloud service.

### Slice 2 — scholarly search and library

- Implemented Crossref, Europe PMC, and OpenAlex metadata search. Add arXiv as a future connector if it improves coverage for the user's research areas.
- Persist search queries, results, source timestamps, and per-record provenance.
- Deduplicate by DOI, then stable provider ID and normalized title.
- Add screening decisions and searchable paper library.

**Done when:** a topic search creates reproducible records and the UI/API can explain why each paper was included or excluded.

### Slice 3 — paper reading and extraction

- Accept user PDFs and open-access PDFs/XML where permitted.
- Extract text with page/section metadata and retain exact passages.
- Generate structured method, dataset, metric, finding, and limitation records.
- Mark abstract-only extraction explicitly.

**Done when:** each extracted factual item links to a paper passage or is rejected as unsupported.

### Slice 4 — verification and synthesis

- Verify source existence, passage relevance, and claim support in a separate workflow stage.
- Preserve conflicting passages.
- Create a paper comparison matrix and thematic synthesis from verified records.
- Add bounded reviewer-triggered targeted search.

**Done when:** the report displays support, contradiction, limitations, and open questions for its key claims.

### Slice 5 — report and usable interface

- Research Intelligence Report with references, evidence links, search log, coverage definition, and unresolved issues.
- Minimal local web interface for creating a run, tracking stages, and opening evidence.
- Export Markdown and structured JSON.

**Done when:** a user can trace each cited claim from report to passage and see what the search did not cover.

## Later phases

1. Novelty, impact, feasibility, experiment planning, and publication advice.
2. Project portfolio and user-configured Research Radar with quiet notifications.
3. Idea discovery cards that undergo the same novelty, evidence, and feasibility checks.
4. Evaluation against a human-reviewed benchmark for citation support, coverage, and usefulness.

## Initial bounded defaults

- At most 3 planned search branches per run, with up to 20 results from each of 3 scholarly indexes per branch (up to 180 provider hits before deduplication).
- Retain at most 48 linked records per run; keep newly retrieved abstracts only for the 12 records passed to local analysis. Other candidates stay transient and are discarded after the run.
- At most 3 local project PDFs included in one run; the latest attachments are selected first.
- At most 2 targeted search/revision cycles.
- One loaded model, sequential inference, modest concurrency for metadata APIs.
- Stop on token, wall-clock, API quota, or memory limit; preserve a partial run and checkpoint.

These values are safety defaults for a personal Mac, not evidence of literature completeness. Make them configurable per run and report them in the final search log.
