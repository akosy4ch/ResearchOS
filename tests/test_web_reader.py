"""Offline checks for the trusted public-page reader boundary."""

import unittest
from unittest.mock import patch

from researchos.web_reader import is_trusted_web_url, read_public_page


class RedirectResponse:
    status_code = 302
    headers = {"location": "https://untrusted.example/track"}


class RedirectStream:
    async def __aenter__(self):
        return RedirectResponse()

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class RedirectClient:
    def __init__(self):
        self.requested = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    def stream(self, method, url):
        self.requested.append(url)
        return RedirectStream()


class TrustedPageReaderTests(unittest.IsolatedAsyncioTestCase):
    def test_allowlist_matches_host_boundaries_and_https(self):
        self.assertTrue(is_trusted_web_url("https://www.nature.com/articles/example"))
        self.assertFalse(is_trusted_web_url("http://nature.com/articles/example"))
        self.assertFalse(is_trusted_web_url("https://nature.com.untrusted.example/paper"))

    async def test_reader_stops_before_requesting_an_untrusted_redirect(self):
        client = RedirectClient()
        with (patch("researchos.web_reader.validate_public_url", side_effect=lambda value: value),
              patch("researchos.web_reader.httpx.AsyncClient", return_value=client)):
            with self.assertRaisesRegex(ValueError, "redirected outside"):
                await read_public_page("https://www.nature.com/articles/example")
        self.assertEqual(client.requested, ["https://www.nature.com/articles/example"])


if __name__ == "__main__":
    unittest.main()
