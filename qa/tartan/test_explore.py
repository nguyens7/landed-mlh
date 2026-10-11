"""Offline safety checks for public archive ranges and legacy timestamp parsing."""

import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from explore import RemoteZip, parse_time


class Response:
    def __init__(self, status=206, content_range="bytes 0-2/10", data=b"abc"):
        self.status = status
        self.headers = {"Content-Range": content_range}
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, n):
        return self.data[:n]


class SampleSafety(unittest.TestCase):
    def reader(self):
        reader = RemoteZip.__new__(RemoteZip)
        reader.url, reader.size, reader.pos = "https://example.invalid/data.zip", 10, 0
        reader.transferred, reader.budget, reader.etag = 0, 8, '"fixed"'
        return reader

    def test_legacy_date_is_utc(self):
        stamp = parse_time(
            {"Date": "[u'2020', u'11', u'14']", "Time": "[u'13', u'53', u'43.5']"}
        )
        self.assertEqual(stamp, datetime(2020, 11, 14, 13, 53, 43, 500000, tzinfo=UTC))

    def test_executable_date_is_rejected(self):
        with self.assertRaises((ValueError, SyntaxError)):
            parse_time({"Date": "__import__('os').getcwd()", "Time": "['0','0','0']"})

    def test_exact_range_and_etag(self):
        reader = self.reader()
        with patch("urllib.request.urlopen", return_value=Response()) as request:
            self.assertEqual(reader.read(3), b"abc")
            self.assertEqual(reader.transferred, 3)
            self.assertEqual(
                request.call_args.args[0].get_header("If-match"), '"fixed"'
            )

    def test_ignored_range_truncation_and_wrong_range_rejected(self):
        for response in (
            Response(status=200),
            Response(data=b"ab"),
            Response(content_range="bytes 1-3/10"),
        ):
            with (
                self.subTest(response=response),
                patch("urllib.request.urlopen", return_value=response),
                self.assertRaises(ValueError),
            ):
                self.reader().read(3)

    def test_total_budget_is_enforced_before_network(self):
        reader = self.reader()
        reader.transferred = 7
        with patch("urllib.request.urlopen") as request:
            with self.assertRaises(ValueError):
                reader.read(2)
            request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
