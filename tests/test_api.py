"""Regression tests for the local ResearchOS API and static UI shell."""

from pathlib import Path
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from researchos.config import settings
from researchos import store
from researchos.main import OLLAMA_MODEL_CATALOG, _local_ollama_api_base, _trusted_web_url, app


class ResearchOSApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="researchos-tests-")
        self.data_dir = Path(self.temp_dir.name)
        self.original_model_name = settings.model_name
        self.settings_patch = patch.object(settings, "data_dir", self.data_dir)
        self.settings_patch.start()
        self.client_context = TestClient(app)
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.settings_patch.stop()
        settings.model_name = self.original_model_name
        self.temp_dir.cleanup()

    def test_health_and_static_application_shell(self) -> None:
        self.assertEqual(self.client.get("/health").json()["status"], "ok")
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="view-project"', response.text)
        self.assertIn('id="help-dialog"', response.text)
        self.assertIn("20261010-specter2-roles-2", response.text)
        self.assertIn('id="role-model-research"', response.text)
        self.assertIn('id="specter2-setup"', response.text)
        self.assertIn('id="model-role-memory-note"', response.text)
        self.assertIn('data-view="discover"', response.text)
        self.assertIn('data-view="analysis"', response.text)
        script = self.client.get("/static/app.js")
        self.assertEqual(script.status_code, 200)
        self.assertIn("data-refine-run", script.text)
        self.assertIn("Visuals and diagrams", script.text)
        self.assertIn("Literature review", script.text)

    def test_project_create_and_dashboard_counts(self) -> None:
        projects = self.client.get("/api/projects").json()
        self.assertEqual(len(projects), 1)
        response = self.client.post("/api/projects", json={"name": "Vision review", "topic": "Medical imaging"})
        self.assertEqual(response.status_code, 200)
        created = response.json()
        self.assertEqual(created["name"], "Vision review")
        self.assertEqual(created["topic"], "Medical imaging")

        listed = self.client.get("/api/projects").json()
        self.assertEqual({project["id"] for project in listed}, {project["id"] for project in projects} | {created["id"]})
        dashboard = self.client.get("/api/dashboard").json()
        self.assertEqual(dashboard["project_count"], 2)
        self.assertEqual(dashboard["run_count"], 0)

    def test_store_connection_closes_after_each_operation(self) -> None:
        with store.connect() as db:
            self.assertEqual(db.execute("SELECT 1").fetchone()[0], 1)
        with self.assertRaises(sqlite3.ProgrammingError):
            db.execute("SELECT 1")

    def test_missing_run_returns_not_found(self) -> None:
        response = self.client.get("/api/runs/not-a-real-run")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Research run was not found")

    def test_report_chat_uses_saved_report_context_and_persists_the_conversation(self) -> None:
        project = store.project_list()[0]
        run = store.create_run(project["id"], "Compare the evidence for this research topic")
        paper = {"doi": "10.1234/chat-paper", "title": "Saved evidence paper", "authors": ["A. Author"],
                 "year": 2025, "abstract": "The study reports a Dice score of 0.91.", "source": "OpenAlex",
                 "source_id": "W-chat-paper", "url": "https://doi.org/10.1234/chat-paper", "open_access_url": ""}
        paper_id = store.save_paper(paper, run["id"], "Core", 1.0)
        store.update_run(run["id"], status="completed", stage="completed", progress=100,
                         result={"executive_summary": "A source reports a Dice score [P1].",
                                 "citation_refs": [{"label": "P1", "paper_id": paper_id, "title": paper["title"],
                                                    "year": 2025, "source": "OpenAlex", "url": paper["url"]}],
                                 "study_metrics": [],
                                 "paper_appraisals": [{"aspect": "what_studied", "assessment": "The paper evaluates a model.",
                                                      "status": "evidence_found", "source_label": "P1",
                                                      "title": paper["title"], "evidence_quote": "The study reports a Dice score of 0.91."}],
                                 "paper_appraisal_coverage": {"records_analyzed": 1, "evidence_backed_facets": 1},
                                 "study_details": [{"aspect": "method", "paper_id": paper_id,
                                                    "source_label": "P1", "title": paper["title"],
                                                    "evidence_quote": "The study reports a Dice score of 0.91."}]})
        markdown = self.client.get(f"/api/runs/{run['id']}/report.md")
        self.assertEqual(markdown.status_code, 200)
        self.assertIn("Methods and experiments quoted from retrieved sources", markdown.text)
        self.assertIn("Annotated bibliography", markdown.text)
        self.assertIn("The paper evaluates a model.", markdown.text)
        self.assertIn("The study reports a Dice score of 0.91.", markdown.text)
        self.client.app.state.model_provider.complete = AsyncMock(return_value="The saved study reports 0.91 [P1].")

        response = self.client.post(f"/api/runs/{run['id']}/chat", json={"message": "What result did it report?"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["role"] for item in response.json()["messages"]], ["user", "assistant"])
        self.assertEqual(response.json()["message"]["content"], "The saved study reports 0.91 [P1].")
        prompt = self.client.app.state.model_provider.complete.await_args.args[1]
        self.assertIn("Saved evidence paper", prompt)
        self.assertIn("The study reports a Dice score of 0.91.", prompt)
        self.assertIn('"aspect": "method"', prompt)
        self.assertIn('"paper_appraisals"', prompt)
        self.assertEqual(self.client.get(f"/api/runs/{run['id']}/chat").json()["messages"], response.json()["messages"])

    def test_report_chat_rejects_not_ready_runs_and_unlisted_citations(self) -> None:
        project = store.project_list()[0]
        run = store.create_run(project["id"], "A pending research question about papers")
        response = self.client.post(f"/api/runs/{run['id']}/chat", json={"message": "What does the report say?"})
        self.assertEqual(response.status_code, 409)

        store.update_run(run["id"], status="completed", stage="completed", progress=100,
                         result={"citation_refs": [{"label": "P1", "paper_id": "missing", "title": "Paper"}]})
        self.client.app.state.model_provider.complete = AsyncMock(return_value="The report says this [P99].")
        response = self.client.post(f"/api/runs/{run['id']}/chat", json={"message": "Tell me about the findings."})
        self.assertEqual(response.status_code, 200)
        self.assertIn("[source not linked in this report]", response.json()["message"]["content"])

    def test_saved_paper_details_include_prior_metrics_and_pdf_analysis_is_queued(self) -> None:
        project = store.project_list()[0]
        run = store.create_run(project["id"], "Review results for a segmentation method")
        paper = store.save_uploaded_pdf(project["id"], "segmentation-study.pdf", str(self.data_dir / "paper.pdf"),
                                        "a" * 64, ["We evaluated Dice score and obtained 0.91."], 43, False)
        store.save_paper({"title": paper["title"], "authors": [], "year": None, "abstract": "",
                          "source": "User PDF", "source_id": "a" * 64, "url": "", "open_access_url": ""},
                         run["id"], "Project PDF", 1.0)
        store.save_paper({"doi": "10.1234/metadata", "title": "Metadata match", "authors": [],
                          "year": 2024, "abstract": "Study abstract.", "source": "OpenAlex",
                          "source_id": "W-meta", "url": "https://doi.org/10.1234/metadata", "open_access_url": ""},
                         run["id"], "Core", 0.8)
        store.update_run(run["id"], status="completed", stage="completed", progress=100,
                         result={"executive_summary": "The study reports overlap [P1].",
                                 "study_metrics": [{"paper_id": paper["id"], "metric": "Dice score",
                                                    "reported_result": "0.91", "evidence_quote": "We evaluated Dice score and obtained 0.91."}]})
        saved = self.client.get(f"/api/papers/{paper['id']}/research")
        self.assertEqual(saved.status_code, 200)
        self.assertTrue(saved.json()["already_saved"])
        self.assertEqual(saved.json()["reported_metrics"][0]["reported_result"], "0.91")
        self.assertEqual(len(saved.json()["prior_reports"]), 1)
        self.assertEqual(self.client.get("/api/papers?q=segmentation-study").json()[0]["id"], paper["id"])

        with patch("researchos.main.analyze_saved_paper", new_callable=AsyncMock) as analyze:
            queued = self.client.post(f"/api/papers/{paper['id']}/analyses")
        self.assertEqual(queued.status_code, 202)
        analyze.assert_awaited_once()
        self.assertEqual(self.client.get(f"/api/paper-analyses/{queued.json()['id']}").json()["status"], "queued")

    def test_paper_figure_previews_are_confined_to_saved_pdf_assets(self) -> None:
        project = store.project_list()[0]
        digest = "c" * 64
        pdf_path = self.data_dir / "documents" / f"{digest}.pdf"
        pdf_path.parent.mkdir(parents=True)
        pdf_path.write_bytes(b"%PDF-test")
        paper = store.save_uploaded_pdf(project["id"], "visual-paper.pdf", str(pdf_path), digest,
                                       ["Figure 1. Model architecture overview."], 40, False)
        figure_path = self.data_dir / "paper_figures" / digest / "page-001-preview.jpg"
        figure_path.parent.mkdir(parents=True)
        figure_path.write_bytes(b"\xff\xd8\xff\xd9")

        preview = self.client.get(f"/api/papers/{paper['id']}/figures/page-001-preview.jpg")
        self.assertEqual(preview.status_code, 200)
        self.assertTrue(preview.headers["content-type"].startswith("image/jpeg"))
        self.assertEqual(preview.content, b"\xff\xd8\xff\xd9")
        missing = self.client.get(f"/api/papers/{paper['id']}/figures/../researchos.sqlite3")
        self.assertNotEqual(missing.status_code, 200)
        inline_pdf = self.client.get(f"/api/papers/{paper['id']}/file?inline=true")
        self.assertEqual(inline_pdf.status_code, 200)
        self.assertEqual(inline_pdf.headers["content-disposition"], "inline")

    def test_existing_saved_record_is_enriched_when_a_later_search_finds_abstract(self) -> None:
        project = store.project_list()[0]
        first_run = store.create_run(project["id"], "Initial metadata-only source collection")
        first_id = store.save_paper({"doi": "10.5555/reused", "title": "Reused study", "authors": [],
                                     "year": None, "abstract": "", "source": "OpenAlex", "source_id": "W-reused",
                                     "url": "", "open_access_url": ""}, first_run["id"], "Core", 0.5)
        second_run = store.create_run(project["id"], "Later search with source details")
        second_id = store.save_paper({"doi": "10.5555/reused", "title": "Reused study", "authors": ["A. Researcher"],
                                      "year": 2023, "abstract": "The paper reports a reproducible evaluation.",
                                      "source": "Crossref", "source_id": "10.5555/reused",
                                      "url": "https://doi.org/10.5555/reused", "open_access_url": ""},
                                     second_run["id"], "Core", 0.8)
        self.assertEqual(first_id, second_id)
        matches = self.client.get("/api/papers?q=A.%20Researcher").json()
        self.assertEqual(matches[0]["abstract"], "The paper reports a reproducible evaluation.")
        self.assertEqual(matches[0]["year"], 2023)

    def test_find_papers_is_temporary_deduplicated_and_saves_selected_metadata(self) -> None:
        project = store.project_list()[0]
        hits = [
            {"doi": "10.9999/discovery", "title": "A discoverable study", "authors": ["A. Researcher"],
             "year": 2025, "abstract": "An abstract from Crossref.", "source": "Crossref",
             "source_id": "10.9999/discovery", "url": "https://doi.org/10.9999/discovery", "open_access_url": "",
             "journal": "Journal of Local Research", "publisher": "Research Press", "volume": "4", "issue": "2", "pages": "10-20"},
            {"doi": "10.9999/discovery", "title": "A discoverable study", "authors": ["A. Researcher"],
             "year": 2025, "abstract": "A longer abstract with additional detail from another trusted index.",
             "source": "OpenAlex", "source_id": "https://openalex.org/W9999", "url": "https://doi.org/10.9999/discovery",
             "open_access_url": "https://example.com/file.pdf", "journal": "", "publisher": "", "volume": "", "issue": "", "pages": ""},
        ]
        with patch("researchos.main.search_branch", new_callable=AsyncMock, return_value=(hits, [])) as search:
            found = self.client.get("/api/paper-search?q=discoverable%20study&per_source=80")
        self.assertEqual(found.status_code, 200)
        search.assert_awaited_once_with("discoverable study", per_source_limit=80)
        self.assertEqual(len(found.json()["papers"]), 1)
        record = found.json()["papers"][0]
        self.assertEqual(record["sources"], ["Crossref", "OpenAlex"])
        self.assertEqual(record["abstract"], "A longer abstract with additional detail from another trusted index.")
        self.assertEqual(record["open_access_url"], "")
        self.assertFalse(record.get("saved_paper_id"))
        self.assertEqual(self.client.get("/api/papers").json(), [])

        saved = self.client.post("/api/papers/save-discovered", json={
            "project_id": project["id"], "source": "Crossref", "source_id": "10.9999/discovery",
            "title": record["title"], "doi": record["doi"], "authors": record["authors"], "year": record["year"],
            "abstract": record["abstract"], "url": record["url"], "journal": record["journal"],
            "publisher": record["publisher"], "volume": record["volume"], "issue": record["issue"], "pages": record["pages"],
        })
        self.assertEqual(saved.status_code, 201)
        stored = self.client.get("/api/papers").json()[0]
        self.assertEqual(stored["id"], saved.json()["paper_id"])
        self.assertEqual(stored["journal"], "Journal of Local Research")
        self.assertEqual(stored["pages"], "10-20")
        with patch("researchos.main.search_branch", new_callable=AsyncMock, return_value=(hits, [])):
            found_again = self.client.get("/api/paper-search?q=discoverable%20study")
        self.assertEqual(found_again.json()["papers"][0]["saved_paper_id"], saved.json()["paper_id"])

    def test_discovered_paper_save_rejects_untrusted_links(self) -> None:
        project = store.project_list()[0]
        response = self.client.post("/api/papers/save-discovered", json={
            "project_id": project["id"], "source": "Crossref", "source_id": "untrusted-record",
            "title": "Untrusted link test", "url": "https://example.com/paper",
        })
        self.assertEqual(response.status_code, 422)

    def test_paper_question_answers_with_only_ids_from_validated_pdf_quotes(self) -> None:
        project = store.project_list()[0]
        pdf_path = self.data_dir / "paper.pdf"
        pdf_path.write_bytes(b"%PDF-test")
        paper = store.save_uploaded_pdf(project["id"], "source-paper.pdf", str(pdf_path), "d" * 64,
                                        ["The model used an independent test cohort and achieved a Dice score of 0.91."],
                                        72, False)
        analysis = store.create_paper_analysis(paper["id"])
        store.update_paper_analysis(analysis["id"], status="completed", stage="completed", progress=100,
                                    result={"paper": {"title": "source-paper"}, "evidence": [
                                        {"id": "F001", "category": "results", "detail": "Dice score was 0.91.",
                                         "page": 3, "evidence_quote": "The model used an independent test cohort and achieved a Dice score of 0.91."}]})
        self.client.app.state.model_provider.complete = AsyncMock(return_value=json.dumps({
            "answer": "The paper reports a Dice score of 0.91 [F001] [F999].", "evidence_ids": ["F001", "F999"]
        }))
        response = self.client.post(f"/api/paper-analyses/{analysis['id']}/chat", json={"message": "What Dice score did it report?"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["evidence_ids"], ["F001"])
        self.assertNotIn("F999", response.json()["answer"])
        self.assertEqual(response.json()["evidence"][0]["page"], 3)
        prompt = self.client.app.state.model_provider.complete.await_args.args[1]
        self.assertIn("The model used an independent test cohort", prompt)
        self.client.app.state.model_provider.complete = AsyncMock(return_value=json.dumps({
            "answer": "This paper introduces a novel method.", "evidence_ids": []
        }))
        unsupported = self.client.post(f"/api/paper-analyses/{analysis['id']}/chat", json={"message": "Is this method novel?"})
        self.assertEqual(unsupported.status_code, 200)
        self.assertEqual(unsupported.json()["answer"],
                         "The validated findings from this PDF do not provide enough evidence to answer that question.")

    def test_run_validation_rejects_short_question_and_unknown_project(self) -> None:
        short = self.client.post("/api/runs", json={"question": "short"})
        self.assertEqual(short.status_code, 422)
        missing_project = self.client.post(
            "/api/runs",
            json={"question": "A sufficiently detailed research question", "project_id": "missing"},
        )
        self.assertEqual(missing_project.status_code, 404)

    def test_refined_run_persists_user_clarification_answers(self) -> None:
        project = store.project_list()[0]
        answers = "Question: Prefer external validation?\nUser answer: Yes, use a held-out site."
        with patch("researchos.main.run_research", new_callable=AsyncMock):
            response = self.client.post("/api/runs", json={
                "question": "Compare methods for a focused research project",
                "project_id": project["id"],
                "brief": {"clarification_answers": answers},
            })
        self.assertEqual(response.status_code, 202)
        self.assertEqual(store.get_run(response.json()["id"])["brief"]["clarification_answers"], answers)

    def test_run_rejects_untrusted_web_sources(self) -> None:
        response = self.client.post("/api/runs", json={
            "question": "A sufficiently detailed research question",
            "web_urls": ["https://example.com/paper"],
        })
        self.assertEqual(response.status_code, 422)
        self.assertIn("trusted scholarly", response.json()["detail"])

    def test_trusted_web_source_allowlist_checks_https_and_host_boundaries(self) -> None:
        self.assertTrue(_trusted_web_url("https://pubmed.ncbi.nlm.nih.gov/12345/"))
        self.assertTrue(_trusted_web_url("https://journals.sagepub.com/article/example"))
        self.assertFalse(_trusted_web_url("http://pubmed.ncbi.nlm.nih.gov/12345/"))
        self.assertFalse(_trusted_web_url("https://notcrossref.org/item"))

    def test_model_picker_lists_and_persists_an_installed_model(self) -> None:
        self.client.app.state.model_provider.available_models = AsyncMock(return_value=["qwen2.5:7b", "llama3.2:3b", "nomic-embed-text:latest"])
        status = self.client.get("/api/model")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["models"], ["qwen2.5:7b", "llama3.2:3b"])

        selected = self.client.post("/api/model", json={"model": "llama3.2:3b"})
        self.assertEqual(selected.status_code, 200)
        self.assertEqual(selected.json()["selected_model"], "llama3.2:3b")
        self.assertEqual(settings.model_name, "llama3.2:3b")
        self.assertEqual(self.client.get("/api/model").json()["selected_model"], "llama3.2:3b")

    def test_model_picker_rejects_a_model_not_installed_locally(self) -> None:
        self.client.app.state.model_provider.available_models = AsyncMock(return_value=["qwen2.5:7b", "nomic-embed-text:latest"])
        response = self.client.post("/api/model", json={"model": "nomic-embed-text:latest"})
        self.assertEqual(response.status_code, 422)

    def test_task_model_roles_only_accept_installed_chat_models(self) -> None:
        self.client.app.state.model_provider.available_models = AsyncMock(
            return_value=["qwen3:4b", "gemma3:4b", "nomic-embed-text:latest"]
        )
        available = self.client.get("/api/model/roles")
        self.assertEqual(available.status_code, 200)
        self.assertEqual(available.json()["models"], ["qwen3:4b", "gemma3:4b"])

        saved = self.client.post("/api/model/roles", json={"roles": {
            "research": "qwen3:4b", "pdf_analysis": "gemma3:4b", "chat": "",
        }})
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["roles"], {
            "research": "qwen3:4b", "pdf_analysis": "gemma3:4b", "chat": "",
        })
        rejected = self.client.post("/api/model/roles", json={"roles": {"chat": "not-installed"}})
        self.assertEqual(rejected.status_code, 422)

    def test_specter2_status_is_available_without_installing_optional_runtime(self) -> None:
        status = self.client.get("/api/paper-ranker/status")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["model"], "SPECTER2 · scientific-paper semantic retrieval")
        self.assertIn("dependencies_ready", status.json())
        self.assertIn("weights_cached", status.json())
        self.assertIn("ready", status.json())

    def test_model_download_catalog_is_bounded_and_local(self) -> None:
        self.assertEqual([item["name"] for item in OLLAMA_MODEL_CATALOG], [
            "qwen3.5:4b", "qwen3.5:9b", "qwen2.5-coder:7b",
        ])
        self.assertEqual(_local_ollama_api_base("http://127.0.0.1:11434/v1"), "http://127.0.0.1:11434")
        self.assertIsNone(_local_ollama_api_base("https://example.com/v1"))
        response = self.client.post("/api/models/pull", json={"model": "arbitrary-model"})
        self.assertEqual(response.status_code, 404)

        with patch("researchos.main._ollama_api_base_or_error", new_callable=AsyncMock,
                   return_value="http://127.0.0.1:11434"):
            self.client.app.state.model_provider.available_models = AsyncMock(return_value=["qwen3.5:4b"])
            catalog = self.client.get("/api/models/catalog")
        self.assertEqual(catalog.status_code, 200)
        self.assertTrue(catalog.json()["ollama_available"])
        self.assertTrue(next(item for item in catalog.json()["models"] if item["name"] == "qwen3.5:4b")["installed"])

    def test_model_download_starts_only_for_catalog_models_without_selecting_them(self) -> None:
        selected_before = settings.model_name
        self.client.app.state.model_provider.available_models = AsyncMock(return_value=["qwen2.5:7b"])
        with (patch("researchos.main._ollama_api_base_or_error", new_callable=AsyncMock,
                    return_value="http://127.0.0.1:11434"),
              patch("researchos.main._pull_ollama_model", new_callable=AsyncMock) as pull):
            response = self.client.post("/api/models/pull", json={"model": "qwen3.5:4b"})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["model"], "qwen3.5:4b")
        self.assertEqual(settings.model_name, selected_before)
        self.assertIn("qwen3.5:4b", self.client.app.state.ollama_pull_tasks)
        pull.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
