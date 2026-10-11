# ResearchOS quick start for macOS

## What you need

- A Mac with Apple silicon or Intel and macOS.
- Python 3.11 or newer.
- Ollama for local model analysis. Research search and report browsing can start without it, but reports will be metadata-only until a local model is connected.

## First launch

1. Install Python 3.11 or newer if needed, and install [Ollama](https://ollama.com/download/mac) for local model analysis. The launcher reuses a supported project environment or finds an installed Python 3.11+ automatically.
2. Download or clone this repository and open its folder.
3. Double-click **Start ResearchOS.command**. On first launch it creates `.venv`, installs the app and dependencies, starts Ollama's local service when available, runs the app's startup check, and opens the browser when the app is ready. If an instance already runs at port 8000, it opens that instance instead of starting a duplicate.
4. In ResearchOS, open **Model settings**. Pick Ollama or connect a local llama.cpp server, then install/select a chat model. A compact 3B–4B quantized model is a good starting point on a 16 GB Mac; larger models need more memory and can be slower.
5. Optional: in **Model settings**, choose **Set up SPECTER2** to add local scientific-semantic ranking. This installs the optional PyTorch/adapter packages and downloads about 450 MB of model weights from Hugging Face; allow at least 4 GB of free disk space for the runtime. Turn on **Use semantic ranking** when setup says ready. Search providers remain Crossref, Europe PMC, and OpenAlex.
6. Use **Model settings → Choose a model for each job** to keep one shared model or assign installed models to research runs, PDF analysis, and report/paper chat. All ResearchOS local model jobs wait in one queue; the settings show per-task calls and token totals for the current session when the local server reports them.
7. Create a project, write a focused question, and start a run. Add domain, data, method, and success-criteria context when you know it. Open **Research runs** to follow the live journal and the report, then use **Ask this report** for follow-up questions.
8. Use **Find papers** to search a title, author, DOI, or topic across Crossref, Europe PMC, and OpenAlex (up to 100 records per index). With SPECTER2 enabled, results are reordered by scientific-semantic similarity; the displayed rank is not a probability. Results are temporary; save only the papers you want in the library. Existing saved records link back to prior reports and metrics.
9. Open **PDF analysis** to add a full-text PDF. Select it in the left panel; run or retry analysis there, and the dossier and paper Q&A appear beside the PDF list. Findings and answers link to validated quotes and exact PDF pages. Copy a suggested citation or BibTeX from saved metadata; check it with the publisher.

Keep the Terminal window open while using ResearchOS. Press **Control-C** in that window to stop the server. Double-click the launcher again to restart it. The launcher reuses a healthy private environment and installs dependencies when the environment needs setup or repair.

## What a report keeps

Each run searches up to 20 records per provider per branch, deduplicates the candidates, and retains at most 48 linked records for the run. The candidate pool is processed in memory; candidates outside the retained set are not added to the library by that run. Full abstracts are kept for the 12 records reserved as local model inputs; other newly retained records keep citation metadata and source links. PDFs you attach are separate project files and stay until you remove them from the project data folder.

The report distinguishes metrics named in available source text from metrics proposed for your experiment plan. Abstract-only searches often miss evaluation details in methods sections and tables. Attach the full paper when you need reliable metric, method, or result comparisons.

For the broader researcher workflow and task-by-task model recommendations, see the [researcher workflow audit](researcher-workflow-audit.md) and the [implementation roadmap](roadmap.md).

## If something goes wrong

- If the browser does not open, visit <http://127.0.0.1:8000>.
- If the report says local analysis is unavailable, confirm Ollama is running or connect a llama.cpp-compatible local server in **Model settings**.
- Open **System Care** for local startup, database, and model diagnostics.
- ResearchOS stores its local database, attached PDFs, and downloaded models under `data/`. Back up that folder before moving the project or reinstalling the app.

## Run without the macOS launcher

From the repository folder:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
cp .env.example .env
.venv/bin/researchos serve --host 127.0.0.1 --port 8000
```

Then open <http://127.0.0.1:8000>. To run the offline checks, use `.venv/bin/python -m unittest discover -s tests -v`.

## Keep the GitHub repository clean

Commit source code, docs, and `.env.example`. Do not commit `.env`, `data/`, downloaded model files, SQLite databases, attached PDFs, or extracted paper text. These paths are excluded by `.gitignore`.
