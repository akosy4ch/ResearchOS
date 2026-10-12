import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from researchos.config import settings


def now() -> str:
    return datetime.now(UTC).isoformat()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(settings.database_path, timeout=30)
    try:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA journal_mode = WAL")
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    with connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                topic TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS research_runs (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id),
                question TEXT NOT NULL,
                status TEXT NOT NULL,
                stage TEXT NOT NULL,
                progress INTEGER NOT NULL DEFAULT 0,
                brief_json TEXT NOT NULL DEFAULT '{}',
                result_json TEXT NOT NULL DEFAULT '{}',
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS papers (
                id TEXT PRIMARY KEY,
                doi TEXT,
                title TEXT NOT NULL,
                authors_json TEXT NOT NULL DEFAULT '[]',
                year INTEGER,
                abstract TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL,
                source_id TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '',
                open_access_url TEXT NOT NULL DEFAULT '',
                journal TEXT NOT NULL DEFAULT '',
                publisher TEXT NOT NULL DEFAULT '',
                volume TEXT NOT NULL DEFAULT '',
                issue TEXT NOT NULL DEFAULT '',
                pages TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE(source, source_id)
            );
            CREATE TABLE IF NOT EXISTS run_papers (
                run_id TEXT NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
                paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
                relevance REAL NOT NULL DEFAULT 0,
                branch TEXT NOT NULL DEFAULT '',
                PRIMARY KEY(run_id, paper_id)
            );
            CREATE TABLE IF NOT EXISTS project_papers (
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
                added_at TEXT NOT NULL,
                PRIMARY KEY(project_id, paper_id)
            );
            CREATE TABLE IF NOT EXISTS paper_files (
                paper_id TEXT PRIMARY KEY REFERENCES papers(id) ON DELETE CASCADE,
                filename TEXT NOT NULL,
                local_path TEXT NOT NULL,
                sha256 TEXT NOT NULL UNIQUE,
                page_count INTEGER NOT NULL,
                character_count INTEGER NOT NULL,
                truncated INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS passages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
                page_number INTEGER NOT NULL,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS run_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
                agent TEXT NOT NULL,
                stage TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS run_screening_decisions (
                run_id TEXT NOT NULL,
                paper_id TEXT NOT NULL,
                decision TEXT NOT NULL CHECK(decision IN ('include', 'exclude', 'maybe')),
                reason TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                PRIMARY KEY(run_id, paper_id),
                FOREIGN KEY(run_id, paper_id) REFERENCES run_papers(run_id, paper_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS run_chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS paper_analyses (
                id TEXT PRIMARY KEY,
                paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
                status TEXT NOT NULL DEFAULT 'queued',
                stage TEXT NOT NULL DEFAULT 'queued',
                progress INTEGER NOT NULL DEFAULT 0,
                result_json TEXT NOT NULL DEFAULT '{}',
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS claims (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
                paper_id TEXT REFERENCES papers(id) ON DELETE SET NULL,
                text TEXT NOT NULL,
                evidence TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'unverified',
                agent TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_runs_project_created ON research_runs(project_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_papers_year ON papers(year DESC);
            CREATE INDEX IF NOT EXISTS idx_run_events_run ON run_events(run_id, id);
            CREATE INDEX IF NOT EXISTS idx_screening_run ON run_screening_decisions(run_id, decision);
            CREATE INDEX IF NOT EXISTS idx_run_chat_messages_run ON run_chat_messages(run_id, id);
            CREATE INDEX IF NOT EXISTS idx_paper_analyses_paper ON paper_analyses(paper_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_passages_paper_page ON passages(paper_id, page_number);
            """
        )
        claim_columns = {row[1] for row in db.execute("PRAGMA table_info(claims)")}
        if "location" not in claim_columns:
            db.execute("ALTER TABLE claims ADD COLUMN location TEXT NOT NULL DEFAULT ''")
        run_columns = {row[1] for row in db.execute("PRAGMA table_info(research_runs)")}
        if "brief_json" not in run_columns:
            db.execute("ALTER TABLE research_runs ADD COLUMN brief_json TEXT NOT NULL DEFAULT '{}'")
        paper_columns = {row[1] for row in db.execute("PRAGMA table_info(papers)")}
        for column in ("journal", "publisher", "volume", "issue", "pages"):
            if column not in paper_columns:
                db.execute(f"ALTER TABLE papers ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
        existing = db.execute("SELECT id FROM projects LIMIT 1").fetchone()
        if not existing:
            db.execute(
                "INSERT INTO projects(id, name, topic, created_at) VALUES (?, ?, ?, ?)",
                (str(uuid4()), "Personal Research Lab", "", now()),
            )


def get_app_setting(key: str) -> str | None:
    with connect() as db:
        row = db.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None


def set_app_setting(key: str, value: str) -> None:
    with connect() as db:
        db.execute("INSERT INTO app_settings(key, value) VALUES (?, ?) "
                   "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def project_list() -> list[dict[str, Any]]:
    with connect() as db:
        return [dict(row) for row in db.execute("SELECT * FROM projects ORDER BY created_at")]


def create_project(name: str, topic: str = "") -> dict[str, Any]:
    item = {"id": str(uuid4()), "name": name, "topic": topic, "created_at": now()}
    with connect() as db:
        db.execute(
            "INSERT INTO projects(id, name, topic, created_at) VALUES (:id, :name, :topic, :created_at)",
            item,
        )
    return item


def create_run(project_id: str, question: str, brief: dict[str, Any] | None = None) -> dict[str, Any]:
    timestamp = now()
    item = {
        "id": str(uuid4()), "project_id": project_id, "question": question,
        "status": "queued", "stage": "queued", "progress": 0,
        "brief_json": json.dumps(brief or {}, ensure_ascii=False),
        "result_json": "{}", "error": "", "created_at": timestamp, "updated_at": timestamp,
    }
    with connect() as db:
        db.execute(
            "INSERT INTO research_runs(id, project_id, question, status, stage, progress, brief_json, created_at, updated_at) "
            "VALUES (:id, :project_id, :question, :status, :stage, :progress, :brief_json, :created_at, :updated_at)", item,
        )
    return item


def update_run(run_id: str, *, status: str | None = None, stage: str | None = None,
               progress: int | None = None, result: dict[str, Any] | None = None,
               error: str | None = None) -> None:
    fields: list[str] = ["updated_at = ?"]
    values: list[Any] = [now()]
    for key, value in (("status", status), ("stage", stage), ("progress", progress), ("error", error)):
        if value is not None:
            fields.append(f"{key} = ?")
            values.append(value)
    if result is not None:
        fields.append("result_json = ?")
        values.append(json.dumps(result, ensure_ascii=False))
    values.append(run_id)
    with connect() as db:
        db.execute(f"UPDATE research_runs SET {', '.join(fields)} WHERE id = ?", values)


def add_event(run_id: str, agent: str, stage: str, message: str) -> None:
    with connect() as db:
        db.execute(
            "INSERT INTO run_events(run_id, agent, stage, message, created_at) VALUES (?, ?, ?, ?, ?)",
            (run_id, agent, stage, message, now()),
        )


def save_screening_decision(run_id: str, paper_id: str, decision: str, reason: str = "") -> dict[str, Any]:
    if decision == "unreviewed":
        with connect() as db:
            db.execute("DELETE FROM run_screening_decisions WHERE run_id = ? AND paper_id = ?", (run_id, paper_id))
        return {"run_id": run_id, "paper_id": paper_id, "decision": "unreviewed", "reason": ""}
    timestamp = now()
    with connect() as db:
        db.execute(
            "INSERT INTO run_screening_decisions(run_id, paper_id, decision, reason, updated_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(run_id, paper_id) DO UPDATE SET decision=excluded.decision, reason=excluded.reason, updated_at=excluded.updated_at",
            (run_id, paper_id, decision, reason[:500], timestamp),
        )
    return {"run_id": run_id, "paper_id": paper_id, "decision": decision, "reason": reason[:500], "updated_at": timestamp}


def list_screening_decisions(run_id: str) -> list[dict[str, Any]]:
    with connect() as db:
        return [dict(row) for row in db.execute(
            "SELECT d.run_id, d.paper_id, d.decision, d.reason, d.updated_at, p.title, p.doi, p.source "
            "FROM run_screening_decisions d JOIN papers p ON p.id=d.paper_id "
            "WHERE d.run_id=? ORDER BY d.updated_at, p.title", (run_id,)
        )]


def list_run_chat_messages(run_id: str, limit: int = 200) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute(
            "SELECT id, run_id, role, content, created_at FROM ("
            "SELECT id, run_id, role, content, created_at FROM run_chat_messages "
            "WHERE run_id = ? ORDER BY id DESC LIMIT ?) ORDER BY id",
            (run_id, max(1, min(limit, 500))),
        )
        return [dict(row) for row in rows]


def create_paper_analysis(paper_id: str) -> dict[str, Any]:
    timestamp = now()
    analysis = {"id": str(uuid4()), "paper_id": paper_id, "status": "queued", "stage": "queued",
                "progress": 0, "result_json": "{}", "error": "", "created_at": timestamp,
                "updated_at": timestamp}
    with connect() as db:
        db.execute(
            "INSERT INTO paper_analyses(id, paper_id, status, stage, progress, result_json, error, created_at, updated_at) "
            "VALUES (:id, :paper_id, :status, :stage, :progress, :result_json, :error, :created_at, :updated_at)",
            analysis,
        )
    return {**analysis, "result": {}}


def update_paper_analysis(analysis_id: str, *, status: str | None = None, stage: str | None = None,
                          progress: int | None = None, result: dict[str, Any] | None = None,
                          error: str | None = None) -> None:
    fields = ["updated_at = ?"]
    values: list[Any] = [now()]
    for key, value in (("status", status), ("stage", stage), ("progress", progress), ("error", error)):
        if value is not None:
            fields.append(f"{key} = ?")
            values.append(value)
    if result is not None:
        fields.append("result_json = ?")
        values.append(json.dumps(result, ensure_ascii=False))
    values.append(analysis_id)
    with connect() as db:
        db.execute(f"UPDATE paper_analyses SET {', '.join(fields)} WHERE id = ?", values)


def _paper_analysis_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if not row:
        return None
    item = dict(row)
    item["result"] = json.loads(item.pop("result_json") or "{}")
    return item


def get_paper_analysis(analysis_id: str) -> dict[str, Any] | None:
    with connect() as db:
        return _paper_analysis_dict(db.execute("SELECT * FROM paper_analyses WHERE id = ?", (analysis_id,)).fetchone())


def list_paper_analyses(paper_id: str, limit: int = 20) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute("SELECT * FROM paper_analyses WHERE paper_id = ? ORDER BY created_at DESC LIMIT ?",
                          (paper_id, max(1, min(limit, 50)))).fetchall()
        return [_paper_analysis_dict(row) for row in rows if row]


def recover_interrupted_paper_analyses() -> None:
    with connect() as db:
        db.execute(
            "UPDATE paper_analyses SET status = 'failed', stage = 'interrupted', "
            "error = 'The app stopped before this analysis finished. Start it again to retry.', updated_at = ? "
            "WHERE status IN ('queued', 'running')", (now(),)
        )


def paper_analysis_pages(paper_id: str) -> list[dict[str, Any]]:
    with connect() as db:
        return [dict(row) for row in db.execute(
            "SELECT page_number, text FROM passages WHERE paper_id = ? ORDER BY page_number", (paper_id,)
        )]


def paper_research(paper_id: str) -> dict[str, Any] | None:
    with connect() as db:
        paper_row = db.execute(
            "SELECT papers.*, paper_files.filename AS local_filename, paper_files.page_count, "
            "paper_files.character_count, paper_files.truncated FROM papers "
            "LEFT JOIN paper_files ON paper_files.paper_id = papers.id WHERE papers.id = ?", (paper_id,)
        ).fetchone()
        if not paper_row:
            return None
        paper = dict(paper_row)
        paper["authors"] = json.loads(paper.pop("authors_json") or "[]")
        run_rows = db.execute(
            "SELECT r.id, r.question, r.status, r.created_at, r.result_json FROM research_runs r "
            "JOIN run_papers rp ON rp.run_id = r.id WHERE rp.paper_id = ? ORDER BY r.created_at DESC LIMIT 50",
            (paper_id,),
        ).fetchall()
        historical_rows = db.execute(
            "SELECT id, question, result_json FROM research_runs WHERE status IN ('completed', 'partial') "
            "ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
        claim_rows = db.execute(
            "SELECT c.text, c.evidence, c.status, c.location, c.created_at, r.id AS run_id, r.question "
            "FROM claims c JOIN research_runs r ON r.id = c.run_id "
            "WHERE c.paper_id = ? ORDER BY c.created_at DESC LIMIT 100", (paper_id,),
        ).fetchall()
        analysis_rows = db.execute("SELECT * FROM paper_analyses WHERE paper_id = ? ORDER BY created_at DESC LIMIT 5",
                                   (paper_id,)).fetchall()
        runs = []
        reported_metrics = []
        candidate_metrics = []
        for row in run_rows:
            result = json.loads(row["result_json"] or "{}")
            report = {key: result.get(key) for key in ("executive_summary", "novelty_analysis", "next_steps")
                      if result.get(key) is not None}
            runs.append({"id": row["id"], "question": row["question"], "status": row["status"],
                         "created_at": row["created_at"], **report})
            for metric in result.get("study_metrics", []) if isinstance(result.get("study_metrics"), list) else []:
                if isinstance(metric, dict) and metric.get("paper_id") == paper_id:
                    reported_metrics.append({**metric, "run_id": row["id"], "report_question": row["question"]})
            strategy = result.get("research_strategy", {})
            phases = strategy.get("experimental_plan", []) if isinstance(strategy, dict) else []
            for phase in phases if isinstance(phases, list) else []:
                metrics = phase.get("metrics", []) if isinstance(phase, dict) else []
                for metric in metrics if isinstance(metrics, list) else []:
                    if isinstance(metric, dict):
                        candidate_metrics.append({**metric, "phase": phase.get("phase", ""),
                                                  "run_id": row["id"], "report_question": row["question"]})
        metric_names = {str(metric.get("metric", "")).casefold() for metric in reported_metrics if metric.get("metric")}
        saved_comparisons = []
        if metric_names:
            for row in historical_rows:
                result = json.loads(row["result_json"] or "{}")
                for metric in result.get("study_metrics", []) if isinstance(result.get("study_metrics"), list) else []:
                    if (isinstance(metric, dict) and metric.get("paper_id") != paper_id
                            and str(metric.get("metric", "")).casefold() in metric_names):
                        saved_comparisons.append({**metric, "run_id": row["id"], "report_question": row["question"]})
                        if len(saved_comparisons) >= 50:
                            break
                if len(saved_comparisons) >= 50:
                    break
        return {"paper": paper, "already_saved": True, "prior_reports": runs,
                "reported_metrics": reported_metrics, "candidate_metrics": candidate_metrics,
                "same_metric_saved_results": saved_comparisons, "claims": [dict(row) for row in claim_rows],
                "analyses": [_paper_analysis_dict(row) for row in analysis_rows if row]}


def add_run_chat_message(run_id: str, role: str, content: str) -> dict[str, Any]:
    if role not in {"user", "assistant"}:
        raise ValueError("Run chat role must be user or assistant")
    message = {"run_id": run_id, "role": role, "content": content, "created_at": now()}
    with connect() as db:
        cursor = db.execute(
            "INSERT INTO run_chat_messages(run_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (run_id, role, content, message["created_at"]),
        )
        message["id"] = cursor.lastrowid
    return message


def get_run(run_id: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute("SELECT research_runs.*, projects.name AS project_name FROM research_runs "
                         "JOIN projects ON projects.id = research_runs.project_id WHERE research_runs.id = ?", (run_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["result"] = json.loads(result.pop("result_json"))
        result["brief"] = json.loads(result.pop("brief_json", "{}") or "{}")
        result["events"] = [dict(e) for e in db.execute(
            "SELECT agent, stage, message, created_at FROM run_events WHERE run_id = ? ORDER BY id", (run_id,)
        )]
        result["papers"] = [dict(p) for p in db.execute(
            "SELECT papers.*, paper_files.filename AS local_filename, run_papers.relevance, run_papers.branch FROM papers "
            "JOIN run_papers ON run_papers.paper_id = papers.id "
            "LEFT JOIN paper_files ON paper_files.paper_id = papers.id WHERE run_papers.run_id = ? "
            "ORDER BY run_papers.relevance DESC, papers.year DESC", (run_id,)
        )]
        result["screening_decisions"] = [dict(item) for item in db.execute(
            "SELECT run_id, paper_id, decision, reason, updated_at FROM run_screening_decisions WHERE run_id = ?",
            (run_id,),
        )]
        decision_counts = {decision: sum(1 for item in result["screening_decisions"] if item["decision"] == decision)
                           for decision in ("include", "exclude", "maybe")}
        prisma_flow = result["result"].get("prisma_flow")
        if isinstance(prisma_flow, dict):
            prisma_flow["human_decisions"] = decision_counts
            prisma_flow["pending_human_decision"] = max(0, len(result["papers"]) - sum(decision_counts.values()))
        result["claims"] = [dict(c) for c in db.execute(
            "SELECT claims.*, papers.title AS paper_title, papers.source AS paper_source, papers.url AS paper_url "
            "FROM claims LEFT JOIN papers ON papers.id = claims.paper_id "
            "WHERE claims.run_id = ? ORDER BY claims.created_at", (run_id,)
        )]
        return result


def list_runs(limit: int = 20) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute(
            "SELECT r.*, p.name AS project_name, "
            "(SELECT COUNT(*) FROM run_papers rp WHERE rp.run_id = r.id) AS paper_count "
            "FROM research_runs r JOIN projects p ON p.id = r.project_id "
            "ORDER BY r.created_at DESC LIMIT ?", (limit,)
        )
        results = [dict(row) for row in rows]
        for result in results:
            result["brief"] = json.loads(result.pop("brief_json", "{}") or "{}")
        return results


def list_papers(limit: int = 100, query: str = "") -> list[dict[str, Any]]:
    with connect() as db:
        if query:
            rows = db.execute(
                "SELECT papers.*, paper_files.filename AS local_filename, paper_files.page_count FROM papers "
                "LEFT JOIN paper_files ON paper_files.paper_id = papers.id "
                "WHERE papers.title LIKE ? OR papers.abstract LIKE ? OR papers.authors_json LIKE ? "
                "OR papers.doi LIKE ? OR papers.source_id LIKE ? ORDER BY papers.year DESC LIMIT ?",
                (f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%", limit),
            )
        else:
            rows = db.execute("SELECT papers.*, paper_files.filename AS local_filename, paper_files.page_count FROM papers "
                              "LEFT JOIN paper_files ON paper_files.paper_id = papers.id "
                              "ORDER BY papers.year DESC, papers.created_at DESC LIMIT ?", (limit,))
        result = []
        for row in rows:
            item = dict(row)
            item["authors"] = json.loads(item.pop("authors_json"))
            item["local_file"] = bool(item.get("local_filename"))
            result.append(item)
        return result


def find_saved_paper(paper: dict[str, Any]) -> dict[str, Any] | None:
    with connect() as db:
        row = None
        if paper.get("doi"):
            row = db.execute("SELECT papers.id, paper_files.filename AS local_filename FROM papers "
                             "LEFT JOIN paper_files ON paper_files.paper_id = papers.id "
                             "WHERE lower(papers.doi) = lower(?) LIMIT 1", (paper["doi"],)).fetchone()
        if not row and paper.get("source_id"):
            row = db.execute("SELECT papers.id, paper_files.filename AS local_filename FROM papers "
                             "LEFT JOIN paper_files ON paper_files.paper_id = papers.id "
                             "WHERE papers.source = ? AND papers.source_id = ? LIMIT 1",
                             (paper.get("source", ""), paper["source_id"])).fetchone()
        if not row and paper.get("title"):
            row = db.execute("SELECT papers.id, paper_files.filename AS local_filename FROM papers "
                             "LEFT JOIN paper_files ON paper_files.paper_id = papers.id "
                             "WHERE trim(lower(papers.title)) = trim(lower(?)) LIMIT 1", (paper["title"],)).fetchone()
        return dict(row) if row else None


def save_paper(paper: dict[str, Any], run_id: str, branch: str, relevance: float) -> str:
    paper_id = str(uuid4())
    with connect() as db:
        existing = None
        if paper.get("doi"):
            existing = db.execute("SELECT id FROM papers WHERE lower(doi) = lower(?) LIMIT 1", (paper["doi"],)).fetchone()
        if not existing and paper.get("source_id"):
            existing = db.execute(
                "SELECT id FROM papers WHERE source = ? AND source_id = ? LIMIT 1",
                (paper["source"], paper["source_id"]),
            ).fetchone()
        if existing:
            paper_id = existing["id"]
            authors = paper.get("authors") or []
            db.execute(
                "UPDATE papers SET doi = COALESCE(doi, ?), "
                "authors_json = CASE WHEN authors_json = '[]' AND ? != '[]' THEN ? ELSE authors_json END, "
                "year = COALESCE(year, ?), "
                "abstract = CASE WHEN abstract = '' THEN ? ELSE abstract END, "
                "url = CASE WHEN url = '' THEN ? ELSE url END, "
                "open_access_url = CASE WHEN open_access_url = '' THEN ? ELSE open_access_url END, "
                "journal = CASE WHEN journal = '' THEN ? ELSE journal END, "
                "publisher = CASE WHEN publisher = '' THEN ? ELSE publisher END, "
                "volume = CASE WHEN volume = '' THEN ? ELSE volume END, "
                "issue = CASE WHEN issue = '' THEN ? ELSE issue END, "
                "pages = CASE WHEN pages = '' THEN ? ELSE pages END "
                "WHERE id = ?",
                (paper.get("doi"), json.dumps(authors), json.dumps(authors), paper.get("year"),
                 paper.get("abstract") or "", paper.get("url") or "", paper.get("open_access_url") or "",
                 paper.get("journal") or "", paper.get("publisher") or "", paper.get("volume") or "",
                 paper.get("issue") or "", paper.get("pages") or "", paper_id),
            )
        else:
            db.execute(
                "INSERT OR IGNORE INTO papers(id, doi, title, authors_json, year, abstract, source, source_id, url, open_access_url, journal, publisher, volume, issue, pages, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (paper_id, paper.get("doi"), paper["title"], json.dumps(paper.get("authors", [])), paper.get("year"),
                 paper.get("abstract", ""), paper["source"], paper.get("source_id", ""), paper.get("url", ""),
                 paper.get("open_access_url", ""), paper.get("journal", ""), paper.get("publisher", ""),
                 paper.get("volume", ""), paper.get("issue", ""), paper.get("pages", ""), now()),
            )
            row = db.execute("SELECT id FROM papers WHERE source = ? AND source_id = ? LIMIT 1",
                              (paper["source"], paper.get("source_id", ""))).fetchone()
            if row:
                paper_id = row["id"]
        db.execute("INSERT OR REPLACE INTO run_papers(run_id, paper_id, relevance, branch) VALUES (?, ?, ?, ?)",
                   (run_id, paper_id, relevance, branch))
    return paper_id


def save_discovered_paper(paper: dict[str, Any], project_id: str) -> dict[str, Any]:
    """Save one explicitly selected index record to a project without creating a research run."""
    paper_id = str(uuid4())
    with connect() as db:
        if not db.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone():
            raise ValueError("Research project was not found")
        existing = None
        if paper.get("doi"):
            existing = db.execute("SELECT id FROM papers WHERE lower(doi) = lower(?) LIMIT 1", (paper["doi"],)).fetchone()
        if not existing and paper.get("source_id"):
            existing = db.execute("SELECT id FROM papers WHERE source = ? AND source_id = ? LIMIT 1",
                                  (paper["source"], paper["source_id"])).fetchone()
        if not existing and paper.get("title"):
            existing = db.execute("SELECT id FROM papers WHERE trim(lower(title)) = trim(lower(?)) LIMIT 1",
                                  (paper["title"],)).fetchone()
        if existing:
            paper_id = existing["id"]
            db.execute(
                "UPDATE papers SET doi = COALESCE(doi, ?), "
                "authors_json = CASE WHEN authors_json = '[]' AND ? != '[]' THEN ? ELSE authors_json END, "
                "year = COALESCE(year, ?), abstract = CASE WHEN abstract = '' THEN ? ELSE abstract END, "
                "url = CASE WHEN url = '' THEN ? ELSE url END, open_access_url = CASE WHEN open_access_url = '' THEN ? ELSE open_access_url END, "
                "journal = CASE WHEN journal = '' THEN ? ELSE journal END, publisher = CASE WHEN publisher = '' THEN ? ELSE publisher END, "
                "volume = CASE WHEN volume = '' THEN ? ELSE volume END, issue = CASE WHEN issue = '' THEN ? ELSE issue END, "
                "pages = CASE WHEN pages = '' THEN ? ELSE pages END WHERE id = ?",
                (paper.get("doi"), json.dumps(paper.get("authors") or []), json.dumps(paper.get("authors") or []),
                 paper.get("year"), paper.get("abstract") or "", paper.get("url") or "", paper.get("open_access_url") or "",
                 paper.get("journal") or "", paper.get("publisher") or "", paper.get("volume") or "",
                 paper.get("issue") or "", paper.get("pages") or "", paper_id),
            )
        else:
            db.execute(
                "INSERT INTO papers(id, doi, title, authors_json, year, abstract, source, source_id, url, open_access_url, journal, publisher, volume, issue, pages, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (paper_id, paper.get("doi"), paper["title"], json.dumps(paper.get("authors") or []), paper.get("year"),
                 paper.get("abstract") or "", paper["source"], paper.get("source_id") or "", paper.get("url") or "",
                 paper.get("open_access_url") or "", paper.get("journal") or "", paper.get("publisher") or "",
                 paper.get("volume") or "", paper.get("issue") or "", paper.get("pages") or "", now()),
            )
            row = db.execute("SELECT id FROM papers WHERE source = ? AND source_id = ? LIMIT 1",
                              (paper["source"], paper.get("source_id") or "")).fetchone()
            if row:
                paper_id = row["id"]
        already_in_project = bool(db.execute("SELECT 1 FROM project_papers WHERE project_id = ? AND paper_id = ?",
                                             (project_id, paper_id)).fetchone())
        db.execute("INSERT OR IGNORE INTO project_papers(project_id, paper_id, added_at) VALUES (?, ?, ?)",
                   (project_id, paper_id, now()))
    return {"paper_id": paper_id, "already_in_project": already_in_project}


def save_uploaded_pdf(project_id: str, filename: str, local_path: str, sha256: str,
                      page_texts: list[str], character_count: int, truncated: bool) -> dict[str, Any]:
    with connect() as db:
        existing = db.execute("SELECT paper_id FROM paper_files WHERE sha256 = ?", (sha256,)).fetchone()
        if existing:
            paper_id = existing["paper_id"]
        else:
            paper_id = str(uuid4())
            title = Path(filename).stem.strip() or "Uploaded research paper"
            timestamp = now()
            db.execute(
                "INSERT INTO papers(id, title, authors_json, abstract, source, source_id, created_at) VALUES (?, ?, ?, '', 'User PDF', ?, ?)",
                (paper_id, title, "[]", sha256, timestamp),
            )
            db.execute(
                "INSERT INTO paper_files(paper_id, filename, local_path, sha256, page_count, character_count, truncated, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (paper_id, filename, local_path, sha256, len(page_texts), character_count, int(truncated), timestamp),
            )
            db.executemany(
                "INSERT INTO passages(paper_id, page_number, text, created_at) VALUES (?, ?, ?, ?)",
                [(paper_id, index, text, timestamp) for index, text in enumerate(page_texts, 1) if text.strip()],
            )
        db.execute("INSERT OR IGNORE INTO project_papers(project_id, paper_id, added_at) VALUES (?, ?, ?)",
                   (project_id, paper_id, now()))
        record = db.execute(
            "SELECT papers.id, papers.title, paper_files.filename, paper_files.page_count, "
            "paper_files.character_count, paper_files.truncated FROM papers "
            "JOIN paper_files ON paper_files.paper_id = papers.id WHERE papers.id = ?", (paper_id,)
        ).fetchone()
        return dict(record)


def project_documents(project_id: str, limit: int = 3) -> list[dict[str, Any]]:
    with connect() as db:
        docs = db.execute(
            "SELECT papers.*, paper_files.filename AS local_filename, paper_files.local_path, "
            "paper_files.page_count, paper_files.character_count, paper_files.truncated "
            "FROM papers JOIN project_papers ON project_papers.paper_id = papers.id "
            "JOIN paper_files ON paper_files.paper_id = papers.id "
            "WHERE project_papers.project_id = ? ORDER BY project_papers.added_at DESC LIMIT ?", (project_id, limit)
        ).fetchall()
        output = []
        for doc in docs:
            item = dict(doc)
            pages = db.execute("SELECT page_number, text FROM passages WHERE paper_id = ? ORDER BY page_number", (doc["id"],)).fetchall()
            item["pages"] = [dict(page) for page in pages]
            item["evidence_text"] = "\n\n".join(f"[Page {page['page_number']}]\n{page['text']}" for page in pages)
            output.append(item)
        return output


def attach_project_documents_to_run(run_id: str, project_id: str,
                                   document_ids: list[str] | None = None) -> list[dict[str, Any]]:
    documents = project_documents(project_id)
    if document_ids is not None:
        included_ids = set(document_ids)
        documents = [document for document in documents if document["id"] in included_ids]
    with connect() as db:
        db.executemany(
            "INSERT OR IGNORE INTO run_papers(run_id, paper_id, relevance, branch) VALUES (?, ?, ?, ?)",
            [(run_id, document["id"], 1.0, "Project PDF") for document in documents],
        )
    return documents


def project_document_count(project_id: str) -> int:
    with connect() as db:
        return db.execute("SELECT COUNT(*) FROM project_papers JOIN paper_files ON paper_files.paper_id = project_papers.paper_id WHERE project_id = ?",
                          (project_id,)).fetchone()[0]


def paper_file(paper_id: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute("SELECT local_path, filename FROM paper_files WHERE paper_id = ?", (paper_id,)).fetchone()
        return dict(row) if row else None


def find_passage_location(paper_id: str, evidence: str) -> str:
    with connect() as db:
        row = db.execute(
            "SELECT page_number FROM passages WHERE paper_id = ? AND instr(lower(text), lower(?)) > 0 ORDER BY page_number LIMIT 1",
            (paper_id, evidence),
        ).fetchone()
    return f"Page {row['page_number']}" if row else ""


def save_claim(run_id: str, paper_id: str | None, text: str, evidence: str, status: str, agent: str,
               location: str = "") -> None:
    with connect() as db:
        db.execute(
            "INSERT INTO claims(id, run_id, paper_id, text, evidence, status, agent, created_at, location) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (str(uuid4()), run_id, paper_id, text, evidence, status, agent, now(), location),
        )


def dashboard() -> dict[str, Any]:
    with connect() as db:
        projects = db.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        papers = db.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        runs = db.execute("SELECT COUNT(*) FROM research_runs").fetchone()[0]
        active = db.execute("SELECT COUNT(*) FROM research_runs WHERE status IN ('queued', 'running')").fetchone()[0]
    return {"project_count": projects, "paper_count": papers, "run_count": runs, "active_runs": active,
            "recent_runs": list_runs(6), "recent_papers": list_papers(6)}
