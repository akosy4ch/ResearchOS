"""Offline regression checks for scholarly search adapters."""

import unittest

import httpx

from researchos.search import is_collection_level_record, search_openalex
from researchos.workflow import balance_search_results


class OpenAlexSearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_maps_work_metadata_and_reconstructs_abstract(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.host, "api.openalex.org")
            self.assertEqual(request.url.params["search"], "medical image segmentation")
            return httpx.Response(200, json={"results": [
                {
                    "id": "https://openalex.org/W123",
                    "doi": "https://doi.org/10.1234/example",
                    "title": "Uncertainty in image segmentation",
                    "type": "article",
                    "authorships": [{"author": {"display_name": "A. Researcher"}}],
                    "publication_year": 2024,
                    "abstract_inverted_index": {"models": [1], "compare": [0], "uncertainty": [2]},
                    "primary_location": {"landing_page_url": "https://publisher.example/paper"},
                    "best_oa_location": {"pdf_url": "https://repository.example/paper.pdf"},
                },
                {"id": "https://openalex.org/W456", "title": ""},
            ]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            papers = await search_openalex("medical image segmentation", client)

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0]["source"], "OpenAlex")
        self.assertEqual(papers[0]["record_type"], "article")
        self.assertEqual(papers[0]["doi"], "10.1234/example")
        self.assertEqual(papers[0]["authors"], ["A. Researcher"])
        self.assertEqual(papers[0]["abstract"], "compare models uncertainty")
        self.assertEqual(papers[0]["url"], "https://publisher.example/paper")
        self.assertEqual(papers[0]["open_access_url"], "https://repository.example/paper.pdf")

    def test_filters_issue_level_records_but_keeps_regular_articles(self) -> None:
        self.assertTrue(is_collection_level_record({"title": "Special Issue: EACR 2026 Congress"}))
        self.assertTrue(is_collection_level_record({"title": "Cancer research collection", "record_type": "journal-issue"}))
        self.assertFalse(is_collection_level_record({"title": "A cancer segmentation study", "record_type": "article"}))


class SearchBalanceTests(unittest.TestCase):
    def test_result_limit_gets_breadth_across_branches_and_indexes(self) -> None:
        branches = []
        for branch in ("uncertainty", "dataset", "2D methods"):
            papers = [{"source": source, "title": f"{branch} {source} {number}"}
                      for source in ("Crossref", "Europe PMC", "OpenAlex") for number in range(4)]
            branches.append((branch, papers))

        balanced = balance_search_results(branches)
        first_18 = balanced[:18]
        self.assertEqual(len(balanced), 36)
        self.assertEqual({branch for _, branch, _ in first_18}, {"uncertainty", "dataset", "2D methods"})
        self.assertEqual({paper["source"] for paper, _, _ in first_18}, {"Crossref", "Europe PMC", "OpenAlex"})
        self.assertEqual([paper["source"] for paper, _, _ in first_18[:9]],
                         ["Crossref", "Europe PMC", "OpenAlex"] * 3)


if __name__ == "__main__":
    unittest.main()
