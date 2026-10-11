# ResearchOS: researcher workflow audit

This is a product checklist for a researcher using ResearchOS to move from a question to a defensible literature review, paper analysis, or experiment plan. It favors a traceable evidence trail over a polished answer that cannot be checked.

## What a researcher needs from the whole workflow

1. **Turn an idea into a reviewable question.** Collect the field, population or data, methods, comparisons, outcomes, date range, review type, and practical constraints. Ask only questions that change the scope; let the researcher answer in a form or the report chat.
2. **Make the search reproducible.** Save exact provider, query, filters, time, per-source counts, deduplication decisions, and the date searched. Separate query expansion from the user's original question. Show where a provider failed and what the system did next.
3. **Screen records transparently.** Let the researcher set inclusion and exclusion rules, see why each record matched, and mark include, exclude, or maybe with a reason. Keep screening decisions reversible and exportable.
4. **Read and compare the studies.** Capture research question, design, sample/cohort, dataset, preprocessing, method, architecture, baselines, protocol, metrics, numeric results, uncertainty/statistics, ablations, limitations, and funding/conflicts when reported. Every extracted detail should link to an exact abstract, full-text passage, table, or PDF page.
5. **Show the evidence as a matrix.** Let the researcher compare methods, datasets, sample sizes, baselines, metrics, and results across papers. Preserve incompatible protocols and contradictory findings instead of averaging them into a false consensus.
6. **Keep coverage honest.** Label abstract-only, full-text, OCR, and figure coverage separately. Show missing facets as “not found in available text,” not as facts about the paper. Report search limits and records screened so a small result set cannot look exhaustive.
7. **Support decisions and next experiments.** Separate paper-reported facts from ResearchOS interpretations. Suggest experiments with a baseline, data split, metrics, ablations, expected failure modes, resource estimate, and evidence-backed reason. A novelty check should identify closest prior work and what still needs manual verification.
8. **Make the project reusable.** Keep the question, protocol, decisions, papers, notes, report versions, and follow-up chat together. Export portable citations and tables, and let the researcher resume, revise, or rerun a stage without losing the earlier evidence.
9. **Protect research material.** Default to local documents and local inference; show when a search or download contacts an outside service. Treat papers and web pages as data, limit tool permissions, and ask before writing code, changing files, or sending content elsewhere.

## Suggested next build order

### P0 — make ranking and model usage legible

- SPECTER2 is now an optional local ranker for Find papers and research runs. Keep exact DOI/title search and lexical/topic screening alongside it; semantic order is a relevance aid, not proof of relevance or a probability.
- Keep Research runs, PDF analysis, and chat on the shared default model until the user assigns specialist models. Show the task routing, queue activity, and per-task local-session calls/token counts in Model settings.
- Improve the current rough weight-plus-context warning with measured runtime memory and explicit load/unload state. Keep the small SPECTER2 encoder offloaded before a chat model starts. Treat image generation as its own queued runtime because it has a different model format and memory profile.

### P1 — systematic search and screening

- Add review profiles: exploratory/narrative, scoping, and systematic. A systematic profile should require a protocol, eligibility rules, date/language limits, and planned databases before search.
- Add a screening inbox with include/exclude/maybe decisions, reasons, duplicate provenance, and a flow summary. Preserve the pre-screen and post-screen counts.
- Add a query log and exports for RIS, BibTeX, CSV, and a simple PRISMA-style flow record. Store links and chosen records; do not keep every unselected abstract forever.
- Add citation chaining and trusted provider integrations only when each source can supply stable IDs, transparent provenance, and a clear license/usage path.

### P2 — stronger evidence extraction

- Prefer lawful open full text or a user-provided PDF. Add OCR for scanned files, section/table extraction, and figure-aware multimodal review as separately labeled passes.
- Turn the paper dossier into a researcher-editable extraction sheet. Save reviewer corrections and distinguish paper text, OCR, model interpretation, and user notes.
- Add study-level risk-of-bias prompts appropriate to the field and design. Make the rubric visible and never imply an official clinical or methodological assessment unless the user selected that rubric.
- Add a comparison matrix with units, denominators, confidence intervals, data splits, and protocol notes, so numbers from unlike experiments are not presented as direct comparisons.

### P3 — reproducibility and evaluation

- Snapshot each run's exact queries, provider timestamps, paper identifiers, model/runtime/quantization, task role, prompt/schema version, source text coverage, and user decisions.
- Build a small human-reviewed benchmark from real questions: retrieval recall/precision at top-k, duplicate handling, relevance by field, exact-quote support, extraction accuracy, and report usefulness. Compare lexical-only and hybrid ranking before changing defaults.
- Add resumable stage checkpoints, cancellation, stale-job recovery, and per-stage cost in time, memory, and model calls.
- Add a local project export/import bundle with the SQLite database, selected PDFs, reports, citation data, and a manifest. Keep automatic backups easy to restore.

## Model roles for this Mac

Model choices should be a measured, user-controlled mapping. A name or benchmark does not guarantee quality on a particular research task.

| Work | Best fit | Practical default on 16 GB unified memory |
| --- | --- | --- |
| Find and rank scientific papers | SPECTER2 query adapter plus its paper-proximity adapter; keep title/DOI/keyword search and provider balance | SPECTER2 is purpose-trained for scientific-paper retrieval: use its query adapter for the question and proximity adapter for title-plus-abstract records. It ranks; it does not write prose. [Model card](https://huggingface.co/allenai/specter2_adhoc_query) |
| Research planning, synthesis, and report chat | One general instruction model with tool calling, structured output, and reliable evidence handling | Keep the installed Qwen3 8B Q4 as the baseline. Compare Qwen3.5 4B for a smaller, image-capable model or Qwen3.5 9B for harder synthesis; their published Ollama weights are roughly 3.3–4 GB and 6.6–7.6 GB. Use modest context on this Mac. [Qwen3.5](https://ollama.com/library/qwen3.5) |
| PDF dossier and grounded Q&A | General model on extracted passages, followed by deterministic quote/page validation | Reuse the research model for text. Add multimodal input only when the workflow can attach a specific figure/page image and cite it separately; changing the model alone does not give PDF analysis access to pixels. |
| Biomedical paper/image review | General model plus an optional biomedical specialist measured on the user's own papers | MedGemma 1.5 4B is worth a controlled comparison for biomedical text and medical images, including 3D MRI/CT inputs. Its Hugging Face access has Health AI Developer Foundation terms, and its card says it is not optimized for multi-turn applications; keep it as a clearly labeled one-shot specialist and check the terms before use. [MedGemma card](https://huggingface.co/google/medgemma-1.5-4b-it) |
| Code generation or debugging in a future developer workspace | A code-tuned instruct model | Qwen2.5-Coder 7B Q4 is a practical specialist candidate at about 4.7 GB. Newer Qwen3-Coder-Next is around 52 GB, so it cannot fit this 16 GB Mac locally. Put code tools in a permissioned workspace with diff review and explicit execution approval. [Qwen2.5-Coder](https://ollama.com/library/qwen2.5-coder) · [Qwen3-Coder-Next sizes](https://ollama.com/library/qwen3-coder-next/tags) |
| Interpret paper figures and diagrams | Vision-language model with page/figure attachments | Compare Qwen3.5 4B as the general local option and MedGemma 1.5 for biomedical figures. The current PDF previewer captures images but the text model does not interpret pixels yet. |
| OCR, deduplication, citation formatting, metric normalization | Deterministic local tools first; use an LLM only to resolve ambiguity | OCR and parsing should return confidence and page/table locations. Citation formatting should come from metadata and a style formatter, not generated prose. |
| Image generation | A dedicated diffusion/image runtime, not a chat LLM | Queue one image task at a time, render a small draft, then upscale. Keep generated assets in a project folder with the model/license recorded. |

### Default operating policy

- One shared general model first; specialist assignments are optional and persist by task.
- One model-heavy ResearchOS request at a time. Search APIs and file preparation can run in parallel while local inference waits.
- Release SPECTER2 tensors when a chat model begins, then reload the ranker only when paper ranking is requested again.
- Show that token totals are local session estimates reported by the model server; some runtimes omit usage metadata. Do not describe them as billing totals.
- Show each model's exact repository, format/quantization, file size, license/usage terms, context setting, and estimated memory before download or role assignment. Gate-restricted or nonstandard-terms models need a clear notice.
- Let the user disable a specialist or reset all tasks to the shared default without losing papers or reports.
