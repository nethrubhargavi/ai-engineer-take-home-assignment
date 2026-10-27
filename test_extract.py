import io
import json
import unittest
import urllib.error
from datetime import datetime, timezone
from email.message import Message
from pathlib import Path
from unittest.mock import call, patch

import extract
from extract import ResponseParseError, clean, parse


class CleanTests(unittest.TestCase):
    def test_preserves_ranges_qualitative_and_comparison_values(self):
        rows = [
            {"test_name": "Pus Cells", "value": "8-10", "unit": "/hpf"},
            {"test_name": "RBC", "value": "Nil", "unit": "/hpf"},
            {"test_name": "Protein", "value": "Negative", "unit": None},
            {"test_name": "CRP", "value": "< 0.5", "unit": "mg/L"},
        ]

        self.assertEqual([row["value"] for row in clean(rows)],
                         ["8-10", "Nil", "Negative", "< 0.5"])

    def test_removes_repeated_rows_across_pages(self):
        rows = [
            {"test_name": "Glucose", "value": 92, "unit": "mg/dL", "reference_range": "70-100"},
            {"test_name": " glucose ", "value": 92.0, "unit": "MG/DL", "reference_range": "70 - 110"},
        ]

        self.assertEqual(len(clean(rows)), 1)

    def test_keeps_same_test_with_different_values(self):
        rows = [
            {"test_name": "Glucose", "value": 92, "unit": "mg/dL"},
            {"test_name": "Glucose", "value": 96, "unit": "mg/dL"},
        ]

        self.assertEqual(len(clean(rows)), 2)


class ParseTests(unittest.TestCase):
    def test_malformed_json_raises_clear_parse_error(self):
        with self.assertRaisesRegex(ResponseParseError, "malformed or truncated JSON"):
            parse("{not json}")

    def test_truncated_json_raises_clear_parse_error(self):
        with self.assertRaisesRegex(ResponseParseError, "malformed or truncated JSON"):
            parse('{"tests":[{"test_name":"Glucose","value":92}')

    def test_valid_empty_tests_array_returns_empty_list(self):
        self.assertEqual(parse('{"tests":[]}'), [])

    def test_extract_propagates_parse_error_without_empty_result(self):
        with patch.object(extract, "load_images", return_value=[]):
            with patch.object(extract, "call_model", return_value='{"tests":[}'):
                with self.assertRaisesRegex(ResponseParseError, "malformed or truncated JSON"):
                    extract.extract(Path("unused.jpg"))


class RetryTests(unittest.TestCase):
    URL = "https://generativelanguage.googleapis.com/test"
    IMAGES = [("image/jpeg", "dGVzdA==")]

    def setUp(self):
        self.api_key_patch = patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"})
        self.api_key_patch.start()
        self.addCleanup(self.api_key_patch.stop)

    def http_error(self, status, headers=None, body=b""):
        return urllib.error.HTTPError(
            self.URL, status, "test error", headers or Message(), io.BytesIO(body)
        )

    def success_response(self):
        data = {"candidates": [{"content": {"parts": [{"text": "model response"}]}}]}
        return io.BytesIO(json.dumps(data).encode("utf-8"))

    def test_retries_429_with_exponential_jitter_then_succeeds(self):
        with patch.object(extract.urllib.request, "urlopen",
                          side_effect=[self.http_error(429), self.success_response()]) as urlopen:
            with patch.object(extract.time, "sleep") as sleep:
                with patch.object(extract.random, "uniform", return_value=0.4):
                    result = extract.call_model(self.IMAGES)

        self.assertEqual(result, "model response")
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(0.4)
        self.assertEqual(urlopen.call_args_list[0].args[0].data,
                         urlopen.call_args_list[1].args[0].data)

    def test_stops_after_three_retries(self):
        errors = [self.http_error(503) for _ in range(extract.MAX_RETRIES + 1)]
        with patch.object(extract.urllib.request, "urlopen", side_effect=errors) as urlopen:
            with patch.object(extract.time, "sleep") as sleep:
                with patch.object(extract.random, "uniform", side_effect=[0.5, 1.0, 2.0]) as jitter:
                    with self.assertRaisesRegex(RuntimeError, "after 3 retries"):
                        extract.call_model(self.IMAGES)

        self.assertEqual(urlopen.call_count, 4)
        self.assertEqual(sleep.call_args_list, [call(0.5), call(1.0), call(2.0)])
        self.assertEqual(jitter.call_args_list, [
            call(0.0, 1.0), call(0.0, 2.0), call(0.0, 4.0)
        ])

    def test_does_not_retry_non_retryable_http_error(self):
        with patch.object(extract.urllib.request, "urlopen",
                          side_effect=self.http_error(400)) as urlopen:
            with patch.object(extract.time, "sleep") as sleep:
                with self.assertRaisesRegex(RuntimeError, "Gemini HTTP 400"):
                    extract.call_model(self.IMAGES)

        urlopen.assert_called_once()
        sleep.assert_not_called()

    def test_does_not_retry_ambiguous_connection_error(self):
        with patch.object(extract.urllib.request, "urlopen",
                          side_effect=urllib.error.URLError("connection reset")) as urlopen:
            with patch.object(extract.time, "sleep") as sleep:
                with self.assertRaisesRegex(RuntimeError, "Gemini connection failed"):
                    extract.call_model(self.IMAGES)

        urlopen.assert_called_once()
        sleep.assert_not_called()

    def test_honors_retry_after_and_structured_retry_info(self):
        headers = Message()
        headers["Retry-After"] = "5"
        body = json.dumps({"error": {"details": [{
            "@type": "type.googleapis.com/google.rpc.RetryInfo",
            "retryDelay": "8s",
        }]}}).encode("utf-8")
        with patch.object(extract.urllib.request, "urlopen",
                          side_effect=[self.http_error(503, headers, body), self.success_response()]):
            with patch.object(extract.time, "sleep") as sleep:
                with patch.object(extract.random, "uniform", return_value=0.25):
                    extract.call_model(self.IMAGES)

        sleep.assert_called_once_with(8.25)

    def test_parses_http_date_retry_after(self):
        now = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
        delay = extract.parse_retry_after("Tue, 27 Oct 2026 12:00:05 GMT", now)

        self.assertEqual(delay, 5.0)

    def test_declines_server_delay_beyond_automatic_wait_limit(self):
        headers = Message()
        headers["Retry-After"] = "120"
        with patch.object(extract.urllib.request, "urlopen",
                          side_effect=self.http_error(429, headers)) as urlopen:
            with patch.object(extract.time, "sleep") as sleep:
                with self.assertRaisesRegex(RuntimeError, "beyond the 60s automatic wait limit"):
                    extract.call_model(self.IMAGES)

        urlopen.assert_called_once()
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
