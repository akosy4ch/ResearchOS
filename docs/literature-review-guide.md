# Literature review in ResearchOS

ResearchOS treats a literature review as both a synthesis and an auditable record of how the evidence was found. Open a completed research run and use the **Literature review** section before reading its themes and recommendations.

## What the report shows

- **Search scope:** trusted indexes, search branches and exact queries, search hits, topic-screened records, retained links, and the subset analyzed by the local model. The first-pass screen looks for meaningful topic terms in result titles and abstracts, and in attached PDF text. It removes clear mismatches before they use the retained-source limit. Because this is a lightweight lexical check, it may miss relevant work described with different terminology; inspect the queries and use **Find papers** with alternate terms when needed. The review date and counts make the search's boundary visible; they do not prove the search is exhaustive.
- **Annotated bibliography:** for each analyzed paper, the report asks what the study did, how it relates to the current question, what strengths are actually supported by the supplied text, and what limitations the authors state. Each populated assessment includes a source excerpt and a link to the paper or local PDF.
- **Not assessable:** if the abstract or excerpt does not support an assessment, the report says so. In particular, a limitation missing from an abstract is not treated as a flaw in the paper, and an unmentioned limitation is not treated as proof that none exists.
- **Cross-paper synthesis:** themes, disagreements, and possible research gaps remain separate from the paper-by-paper annotations. Gaps are provisional; a bounded search cannot establish that no prior work exists.
- **Methods and results:** exact source excerpts, reported metrics, claims, and PDF page locations remain available in their dedicated report sections. This helps readers compare design, data, baselines, evaluation, and findings without confusing a proposed metric with a published result.

## How these choices map to good-review practice

The supplied guidance recommends searching broadly, keeping references organized, appraising each source consistently, grouping sources into themes, citing literature-supported statements, and revisiting the review near the end of a project. ResearchOS now supports transparent search logs, linked references, consistent annotations, thematic synthesis, and source checks. A research run is still a bounded discovery and analysis aid rather than a systematic-review protocol: it does not yet screen every result with human inclusion/exclusion decisions or trace references forward and backward from each paper. Use **Find papers** for additional focused searches, save relevant records, attach full-text PDFs when available, and rerun the search before final submission to check for newer work. Older saved reports offer **Run this review again**, which reuses their question and brief and carries forward selected scholarly pages and project PDFs.

The pasted guidance's suggested impact-factor cutoff is not used as a universal quality test. Journal impact factor is not a substitute for relevance, study design, reporting quality, or source type, and its meaning varies across fields. ResearchOS therefore surfaces source type and evidence detail but leaves final inclusion and quality judgments to the researcher.

## Reading the counts

The broad provider result pool is temporary. A run retains a bounded set of source links and keeps full abstracts only for the records selected for local analysis. Thus **records analyzed** is smaller than **unique records** by design. The visible counts, search queries, source errors, and coverage notes should guide follow-up searches; they must not be reported as proof that the field contains only those papers.
