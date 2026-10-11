"""Coverage for the separate detailed PDF analysis service."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from researchos import store
from researchos.config import settings
from researchos.paper_analysis import _capture_figure_pages, analyze_saved_paper


class FakePdfBitmap:
    def __init__(self):
        self.image = Image.new("RGB", (420, 560), "white")

    def to_pil(self):
        return self.image

    def close(self):
        self.image.close()


class FakePdfPage:
    def __init__(self):
        self.closed = False

    def get_size(self):
        return 612, 792

    def render(self, **kwargs):
        return FakePdfBitmap()

    def close(self):
        self.closed = True


class FakePdfDocument:
    def __init__(self):
        self.pages = [FakePdfPage(), FakePdfPage()]
        self.closed = False

    def __len__(self):
        return len(self.pages)

    def __getitem__(self, index):
        return self.pages[index]

    def close(self):
        self.closed = True


class FakePaperAnalysisProvider:
    def __init__(self):
        self.closed = False

    async def complete(self, system, user, *, max_tokens, **kwargs):
        payload = json.loads(user)
        if "pdf_excerpt" in payload:
            page = payload["pdf_excerpt"][0]
            text = page["text"]
            start = text.find("This randomized trial")
            quote = (text[start:] if start >= 0 else text)[:72]
            return json.dumps({"findings": [
                {"category": "results", "detail": "Reported Dice score is 0.91.", "page": page["page"],
                 "evidence_quote": quote},
                {"category": "results", "detail": "Unsupported extra result.", "page": page["page"],
                 "evidence_quote": "This sentence is not in the paper."},
            ]})
        return json.dumps({"summary": {"text": "The paper reports a Dice score of 0.91 [F001].", "evidence_ids": ["F001"]},
                           "sections": [{"title": "Results", "items": [
                               {"text": "The reported score is 0.91 [F001].", "evidence_ids": ["F001"]},
                               {"text": "An unsupported claim [F999].", "evidence_ids": ["F999"]}]}],
                           "state_of_art": {"paper_claim": {"text": "Current SOTA [F999].", "evidence_ids": ["F999"]},
                                            "assessment": "One paper cannot establish current SOTA."},
                           "not_reported_or_unclear": ["External validation was not located in extracted text."]})

    async def close(self):
        self.closed = True


class MalformedPaperAnalysisProvider(FakePaperAnalysisProvider):
    def __init__(self):
        super().__init__()
        self.extraction_calls = 0

    async def complete(self, system, user, *, max_tokens, **kwargs):
        payload = json.loads(user)
        if "pdf_excerpt" in payload:
            self.extraction_calls += 1
            return "truncated {\"findings\":"
        return await super().complete(system, user, max_tokens=max_tokens, **kwargs)


class PaperAnalysisTests(unittest.IsolatedAsyncioTestCase):
    async def test_pdf_analysis_keeps_only_exact_quotes_and_valid_evidence_links(self):
        with tempfile.TemporaryDirectory(prefix="researchos-paper-analysis-") as temporary:
            with patch.object(settings, "data_dir", Path(temporary)):
                store.init_db()
                project = store.project_list()[0]
                pdf_path = Path(temporary) / "documents" / ("b" * 64 + ".pdf")
                pdf_path.parent.mkdir(parents=True)
                pdf_path.write_bytes(b"%PDF-test")
                page_texts = ["Figure 1. Proposed model architecture with the tabular branch and signal branch. "
                              "This randomized trial evaluates a segmentation model. We report a Dice score of 0.91.",
                              "The paper states that testing used an independent cohort."]
                paper = store.save_uploaded_pdf(project["id"], "results.pdf", str(pdf_path), "b" * 64,
                                                page_texts, sum(map(len, page_texts)), False)
                analysis = store.create_paper_analysis(paper["id"])
                provider = FakePaperAnalysisProvider()
                fake_document = FakePdfDocument()
                with patch("researchos.paper_analysis.LocalOpenAIProvider", return_value=provider), \
                     patch("researchos.paper_analysis.pdfium.PdfDocument", return_value=fake_document):
                    await analyze_saved_paper(analysis["id"], paper["id"], asyncio.Lock())

                completed = store.get_paper_analysis(analysis["id"])
                self.assertEqual(completed["status"], "completed")
                self.assertEqual(completed["result"]["coverage"]["validated_finding_count"], 1)
                self.assertEqual(completed["result"]["evidence"][0]["page"], 1)
                self.assertIn(completed["result"]["evidence"][0]["evidence_quote"],
                              "This randomized trial evaluates a segmentation model. We report a Dice score of 0.91.")
                self.assertEqual(len(completed["result"]["sections"][0]["items"]), 1)
                self.assertIsNone(completed["result"]["state_of_art"]["paper_claim"])
                self.assertEqual(completed["result"]["coverage"]["pdf_pages"], 2)
                self.assertEqual(completed["result"]["coverage"]["figure_pages_captured"], 1)
                self.assertEqual(completed["result"]["figures"][0]["kind"], "Model architecture")
                self.assertEqual(completed["result"]["figures"][0]["page"], 1)
                self.assertTrue(fake_document.closed)
                figure_path = Path(temporary) / "paper_figures" / ("b" * 64) / "page-001-preview.jpg"
                self.assertTrue(figure_path.read_bytes().startswith(b"\xff\xd8"))
                with Image.open(figure_path) as preview:
                    self.assertEqual(preview.size, (420, 560))

    async def test_malformed_model_output_retries_then_marks_partial_pages(self):
        with tempfile.TemporaryDirectory(prefix="researchos-paper-analysis-") as temporary:
            with patch.object(settings, "data_dir", Path(temporary)):
                store.init_db()
                project = store.project_list()[0]
                pdf_path = Path(temporary) / "documents" / ("c" * 64 + ".pdf")
                pdf_path.parent.mkdir(parents=True)
                pdf_path.write_bytes(b"%PDF-test")
                page_texts = ["The paper evaluates a method on an independent test cohort."]
                paper = store.save_uploaded_pdf(project["id"], "partial.pdf", str(pdf_path), "c" * 64,
                                                page_texts, len(page_texts[0]), False)
                analysis = store.create_paper_analysis(paper["id"])
                provider = MalformedPaperAnalysisProvider()
                with patch("researchos.paper_analysis.LocalOpenAIProvider", return_value=provider):
                    await analyze_saved_paper(analysis["id"], paper["id"], asyncio.Lock())

                completed = store.get_paper_analysis(analysis["id"])
                self.assertEqual(completed["status"], "completed")
                self.assertEqual(provider.extraction_calls, 2)
                self.assertEqual(completed["result"]["coverage"]["unreadable_sections"],
                                 [{"section": 1, "pages": [1]}])
                self.assertTrue(any("affected PDF pages: 1" in item for item in completed["result"]["limits"]))


if __name__ == "__main__":
    unittest.main()
