"""License and evidence-comparison checks for trusted full-text enrichment."""

import unittest

import httpx

from researchos.fulltext import fetch_open_access_fulltext, parse_fulltext_xml
from researchos.workflow import build_evidence_matrix, comparable_metric_groups, merge_index_record


class EuropePmcFullTextTests(unittest.IsolatedAsyncioTestCase):
    def test_explicit_reuse_license_keeps_bounded_methods_tables_and_captions(self) -> None:
        xml = b'''<article xmlns:xlink="http://www.w3.org/1999/xlink"><front><article-meta><permissions>
        <license xlink:href="https://creativecommons.org/licenses/by/4.0/"><license-p>Creative Commons Attribution</license-p></license>
        </permissions></article-meta></front><body><sec><title>Methods</title>
        <p>We trained a three-dimensional U-Net with five-fold cross-validation on the public dataset.</p>
        <table-wrap><label>Table 1</label><caption><p>Performance on the held-out test split.</p></caption>
        <table><tr><td>Dice 0.91</td><td>95% confidence interval</td></tr></table></table-wrap>
        <fig><caption><p>Model architecture and data processing pipeline.</p></caption><graphic xlink:href="figure.png"/></fig>
        </sec></body></article>'''
        parsed = parse_fulltext_xml(xml)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["license"], "CC-BY")
        self.assertGreaterEqual(parsed["tables"], 1)
        self.assertGreaterEqual(parsed["figures"], 1)
        self.assertTrue(any(item["locator"] == "Section: Methods" and "five-fold" in item["text"]
                            for item in parsed["passages"]))
        self.assertTrue(any(item["locator"].startswith("Table:") and "Dice 0.91" in item["text"]
                            for item in parsed["passages"]))

    def test_no_license_or_no_derivatives_text_is_not_used(self) -> None:
        body = "<body><sec><title>Methods</title><p>We used this exact test passage with enough words to be useful in analysis.</p></sec></body>"
        no_license = f"<article>{body}</article>".encode()
        no_derivatives = ("<article xmlns:xlink=\"http://www.w3.org/1999/xlink\"><front><article-meta><permissions>"
                         "<license xlink:href=\"https://creativecommons.org/licenses/by-nd/4.0/\"><license-p>CC BY-ND</license-p></license>"
                         f"</permissions></article-meta></front>{body}</article>").encode()
        self.assertIsNone(parse_fulltext_xml(no_license))
        self.assertIsNone(parse_fulltext_xml(no_derivatives))

    def test_duplicate_provider_record_preserves_oa_locator_for_full_text(self) -> None:
        target = {"doi": "10.1234/test", "title": "Test study", "source": "Crossref",
                  "source_id": "10.1234/test", "abstract": "Short abstract."}
        merge_index_record(target, {"doi": "10.1234/test", "title": "Test study", "source": "Europe PMC",
                                    "source_id": "PMC123", "pmcid": "PMC123", "is_open_access": True,
                                    "abstract": "Longer abstract text."}, "Methods")
        self.assertEqual(target["fulltext_source"], "Europe PMC")
        self.assertEqual(target["pmcid"], "PMC123")
        self.assertIn("Europe PMC", target["sources"])
        self.assertIn("Methods", target["search_branches"])

    async def test_rest_fetch_is_open_access_only_and_uses_fulltextxml(self) -> None:
        xml = b'''<article xmlns:xlink="http://www.w3.org/1999/xlink"><front><article-meta><permissions>
        <license xlink:href="https://creativecommons.org/licenses/by/4.0/"/></permissions></article-meta></front>
        <body><sec><title>Methods</title><p>We used an explicitly documented public study dataset for evaluation.</p></sec></body></article>'''

        async def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.host, "www.ebi.ac.uk")
            self.assertEqual(request.url.path, "/europepmc/webservices/rest/PMC123/fullTextXML")
            return httpx.Response(200, content=xml)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            denied = await fetch_open_access_fulltext({"pmcid": "PMC123", "is_open_access": False}, client)
            allowed = await fetch_open_access_fulltext({"pmcid": "PMC123", "is_open_access": True}, client)
        self.assertIsNone(denied)
        self.assertEqual(allowed["license"], "CC-BY")
        self.assertEqual(allowed["pmcid"], "PMC123")


class EvidenceMatrixComparisonTests(unittest.TestCase):
    def test_matrix_marks_missing_fields_and_comparison_requires_all_context(self) -> None:
        papers = [{"id": "a", "title": "Study A", "source": "Europe PMC", "evidence_kind": "Abstract"},
                  {"id": "b", "title": "Study B", "source": "Europe PMC", "evidence_kind": "Abstract"}]
        details = []
        for paper_id in ("a", "b"):
            for aspect, value in (("dataset", "ChestX Dataset"), ("data_split", "official patient-level split"),
                                  ("evaluation_protocol", "same external test set")):
                details.append({"paper_id": paper_id, "aspect": aspect, "value": value,
                                "evidence_quote": f"The study used {value}.", "location": "Abstract"})
        metrics = [{"paper_id": "a", "metric": "AUROC", "reported_result": "0.91", "evidence_quote": "AUROC was 0.91."},
                   {"paper_id": "b", "metric": "AUROC", "reported_result": "0.93", "evidence_quote": "AUROC was 0.93."}]
        matrix = build_evidence_matrix(papers, details, metrics, {"a": "P1", "b": "P2"})
        self.assertEqual(len(matrix[0]["cells"]), 13)
        missing = next(cell for cell in matrix[0]["cells"] if cell["aspect"] == "preprocessing")
        self.assertEqual(missing["evidence"][0]["value"], "Not found in available text")
        self.assertEqual(len(comparable_metric_groups(metrics, matrix)), 1)
        details = [item for item in details if not (item["paper_id"] == "b" and item["aspect"] == "data_split")]
        matrix = build_evidence_matrix(papers, details, metrics, {"a": "P1", "b": "P2"})
        self.assertEqual(comparable_metric_groups(metrics, matrix), [])


if __name__ == "__main__":
    unittest.main()
