# ResearchOS quick start for Windows and Linux

## What you need

- Windows 10/11 with PowerShell, or a current Linux distribution with Bash.
- Python 3.11 or newer. On Windows, enable **Add Python to PATH** in the Python installer.
- Ollama for local model analysis. You can start ResearchOS without it and connect a compatible local model server later.

## Windows: first launch

1. Install [Python](https://www.python.org/downloads/windows/) and [Ollama](https://ollama.com/download/windows) if needed.
2. Download or clone this repository.
3. Double-click **Start ResearchOS.bat**. It creates `.venv`, installs the app locally, starts Ollama's service if needed, runs startup checks, and opens the browser when ResearchOS is ready. If an instance already runs at port 8000, it opens that instance instead of creating a duplicate.
4. In the app, open **Model settings**, select Ollama or connect another local OpenAI-compatible server, then install/select a chat model.
5. Create a project, enter a focused research question, and start a run. **Research runs** and **Agent team** show progress and the source-linked report. Open the finished report and use **Ask this report** to chat about its findings.
6. Use **Find papers** to search a title, author, DOI, or topic across Crossref, Europe PMC, and OpenAlex (up to 100 records per index). Results are temporary; save only papers you want to keep. Existing records show links to saved reports and results.
7. Open **PDF analysis** to add a full-text PDF. Select it in the left panel; run or retry analysis there, and the dossier and paper Q&A appear beside the PDF list. Findings and answers link to validated quotations and exact PDF pages. Copy a suggested citation or BibTeX from saved metadata and verify it with the publisher.

Keep the launcher window open while using the app. Press **Control-C** there to stop it. Double-click the batch file to restart.

If you prefer PowerShell, run this from the repository folder:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\Start ResearchOS.ps1"
```

The policy override applies only to that process; it does not change your system-wide policy.

## Linux: first launch

Install Python 3.11+, Bash, and optionally [Ollama](https://ollama.com/download/linux). In a terminal, run:

```bash
chmod +x scripts/start-linux.sh
./scripts/start-linux.sh
```

The launcher creates `.venv`, installs the app, starts Ollama if installed but not running, runs startup checks, and opens the browser when `xdg-open` is available. If an instance already runs at port 8000, it opens that instance instead of creating a duplicate. Keep the terminal open and press **Control-C** to stop the app. Run the same script again to restart it.

## Run offline checks

After setup:

- Windows: `.venv\Scripts\python.exe -m unittest discover -s tests -v`
- Linux: `.venv/bin/python -m unittest discover -s tests -v`

GitHub Actions runs these checks automatically for pushes and pull requests on Linux, Windows, and macOS with Python 3.11, 3.12, and 3.13.

## Local data and reports

ResearchOS keeps its SQLite database, attached PDFs, and downloaded models under `data/`. Back up that directory before moving or reinstalling the project. Do not commit `data/`, `.env`, databases, model files, or paper files to GitHub; `.gitignore` excludes them.

Each run searches a wider temporary candidate pool, then retains up to 48 source links and the 12 abstracts reserved for local model input. The rest of the candidate pool is discarded when the run finishes. Metrics explicitly reported in available paper text appear separately from candidate metrics in the proposed experiment plan. Abstract-only searches often miss evaluation details in methods and results tables, so attach full-text PDFs when accurate method or metric comparison matters.

If the browser does not open automatically, visit <http://127.0.0.1:8000>. Use **System Care** for startup, database, and model diagnostics.
