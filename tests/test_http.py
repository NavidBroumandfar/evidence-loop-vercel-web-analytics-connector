"""Tests for HTTP transport."""

import json
import unittest

from evidence_loop_vercel_web_analytics.errors import (
    ProviderUnavailableError,
    TransportError,
)
from evidence_loop_vercel_web_analytics.http import (
    HTTPResponse,
    MAX_RESPONSE_SIZE,
    NoRedirectHandler,
    Transport,
    check_nesting_depth,
    parse_response,
)


class FakeTransport(Transport):
    """Fake transport for testing."""

    def __init__(self, response: HTTPResponse):
        self.response = response
        self.last_url = None
        self.last_headers = None
        self.last_params = None

    def get(self, url: str, headers: dict[str, str], params: dict[str, str]) -> HTTPResponse:
        self.last_url = url
        self.last_headers = headers
        self.last_params = params
        return self.response


class TestHTTPResponse(unittest.TestCase):
    """Test HTTPResponse dataclass."""

    def test_immutable(self):
        """Response is immutable."""
        response = HTTPResponse(
            status=200,
            headers={"Content-Type": "application/json"},
            body=b'{"test": 1}',
        )
        with self.assertRaises(AttributeError):
            response.status = 400

    def test_no_sha256_field(self):
        """HTTPResponse has no sha256 field."""
        response = HTTPResponse(
            status=200,
            headers={"Content-Type": "application/json"},
            body=b'{"test": 1}',
        )
        self.assertFalse(hasattr(response, "sha256"))


class TestParseResponse(unittest.TestCase):
    """Test response parsing."""

    def test_parse_valid_json(self):
        """Parse valid JSON response."""
        body = b'{"version": 1, "data": {"pageviews": 100, "visitors": 50}}'
        response = HTTPResponse(
            status=200,
            headers={"Content-Type": "application/json"},
            body=body,
        )
        result = parse_response(response)
        self.assertEqual(result["version"], 1)

    def test_reject_non_200(self):
        """Reject non-200 status."""
        response = HTTPResponse(
            status=404,
            headers={"Content-Type": "application/json"},
            body=b'{"error": "not found"}',
        )
        with self.assertRaises(ProviderUnavailableError) as ctx:
            parse_response(response)
        self.assertEqual(ctx.exception.code, "NON_200_STATUS")

    def test_reject_boolean_status(self):
        """Boolean status must not pass integer validation."""
        response = HTTPResponse(
            status=True,
            headers={"Content-Type": "application/json"},
            body=b"{}",
        )
        with self.assertRaises(TransportError) as ctx:
            parse_response(response)
        self.assertEqual(ctx.exception.code, "INVALID_STATUS")

    def test_reject_non_json_content_type(self):
        """Reject non-JSON content type."""
        response = HTTPResponse(
            status=200,
            headers={"Content-Type": "text/html"},
            body=b'<html></html>',
        )
        with self.assertRaises(TransportError) as ctx:
            parse_response(response)
        self.assertEqual(ctx.exception.code, "INVALID_CONTENT_TYPE")

    def test_accept_mixed_case_content_type(self):
        """Accept mixed-case application/json content type."""
        body = b'{"version": 1}'
        response = HTTPResponse(
            status=200,
            headers={"Content-Type": "Application/JSON"},
            body=body,
        )
        result = parse_response(response)
        self.assertEqual(result["version"], 1)

    def test_accept_content_type_with_params(self):
        """Accept content type with parameters."""
        body = b'{"version": 1}'
        response = HTTPResponse(
            status=200,
            headers={"Content-Type": "application/json; charset=utf-8"},
            body=body,
        )
        result = parse_response(response)
        self.assertEqual(result["version"], 1)

    def test_reject_invalid_utf8(self):
        """Reject invalid UTF-8."""
        response = HTTPResponse(
            status=200,
            headers={"Content-Type": "application/json"},
            body=b'\xff\xfe',
        )
        with self.assertRaises(TransportError) as ctx:
            parse_response(response)
        self.assertEqual(ctx.exception.code, "INVALID_UTF8")

    def test_reject_invalid_json(self):
        """Reject malformed JSON."""
        response = HTTPResponse(
            status=200,
            headers={"Content-Type": "application/json"},
            body=b'{invalid}',
        )
        with self.assertRaises(TransportError) as ctx:
            parse_response(response)
        self.assertEqual(ctx.exception.code, "INVALID_JSON")

    def test_reject_duplicate_keys(self):
        """Reject duplicate JSON keys."""
        body = b'{"key": 1, "key": 2}'
        response = HTTPResponse(
            status=200,
            headers={"Content-Type": "application/json"},
            body=body,
        )
        with self.assertRaises(TransportError) as ctx:
            parse_response(response)
        self.assertEqual(ctx.exception.code, "INVALID_JSON")

    def test_reject_oversize_body(self):
        """Reject body exceeding size limit."""
        body = b"x" * (MAX_RESPONSE_SIZE + 1)
        response = HTTPResponse(
            status=200,
            headers={"Content-Type": "application/json"},
            body=body,
        )
        with self.assertRaises(TransportError) as ctx:
            parse_response(response)
        self.assertEqual(ctx.exception.code, "RESPONSE_TOO_LARGE")

    def test_reject_non_bytes_body(self):
        """Reject non-bytes body."""
        response = HTTPResponse(
            status=200,
            headers={"Content-Type": "application/json"},
            body="not bytes",
        )
        with self.assertRaises(TransportError) as ctx:
            parse_response(response)
        self.assertEqual(ctx.exception.code, "INVALID_BODY")

    def test_reject_non_dict_headers(self):
        """Reject non-dict headers."""
        response = HTTPResponse(
            status=200,
            headers="not a dict",
            body=b'{"test": 1}',
        )
        with self.assertRaises(TransportError) as ctx:
            parse_response(response)
        self.assertEqual(ctx.exception.code, "INVALID_HEADERS")

    def test_reject_non_string_header_entries(self):
        """Header names and values must be strings before case folding."""
        response = HTTPResponse(
            status=200,
            headers={"Content-Type": None},
            body=b"{}",
        )
        with self.assertRaises(TransportError) as ctx:
            parse_response(response)
        self.assertEqual(ctx.exception.code, "INVALID_HEADERS")


class TestNestingDepth(unittest.TestCase):
    """Test nesting depth validation."""

    def test_accept_shallow(self):
        """Accept shallow nesting."""
        obj = {"a": {"b": {"c": 1}}}
        result = check_nesting_depth(obj, max_depth=10)
        self.assertIsNone(result)

    def test_reject_deep_nesting(self):
        """Reject excessive nesting."""
        obj = {"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": {"i": {"j": {"k": 1}}}}}}}}}}}
        with self.assertRaises(TransportError) as ctx:
            check_nesting_depth(obj, max_depth=10)
        self.assertEqual(ctx.exception.code, "EXCESSIVE_NESTING")

    def test_check_nested_lists(self):
        """Check nesting in lists."""
        obj = {"a": [{"b": [{"c": 1}]}]}
        result = check_nesting_depth(obj, max_depth=10)
        self.assertIsNone(result)


class TestNoRedirectHandler(unittest.TestCase):
    """Test no-redirect handler."""

    def test_redirect_request_returns_none(self):
        """redirect_request returns None to prevent redirect."""
        handler = NoRedirectHandler()
        result = handler.redirect_request(None, None, 302, "Found", {}, "http://example.com")
        self.assertIsNone(result)


class TestFakeTransport(unittest.TestCase):
    """Test fake transport captures requests."""

    def test_capture_url(self):
        """Capture URL."""
        response = HTTPResponse(200, {}, b"")
        transport = FakeTransport(response)
        transport.get("https://example.com", {}, {"key": "value"})
        self.assertEqual(transport.last_url, "https://example.com")

    def test_capture_headers(self):
        """Capture headers."""
        response = HTTPResponse(200, {}, b"")
        transport = FakeTransport(response)
        transport.get("https://example.com", {"Auth": "token"}, {})
        self.assertEqual(transport.last_headers, {"Auth": "token"})

    def test_capture_params(self):
        """Capture params."""
        response = HTTPResponse(200, {}, b"")
        transport = FakeTransport(response)
        transport.get("https://example.com", {}, {"projectId": "prj_123"})
        self.assertEqual(transport.last_params, {"projectId": "prj_123"})


if __name__ == "__main__":
    unittest.main()
