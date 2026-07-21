"""Tests for CLI interface."""

import json
import os
import sys
import unittest
from io import StringIO
from unittest.mock import patch

from evidence_loop_vercel_web_analytics.cli import main
from evidence_loop_vercel_web_analytics.http import UrllibTransport


def _guard_urllib_get(self, url, headers, params):
    raise AssertionError("UrllibTransport.get called without mock - real network call prevented")


_original_urllib_get = UrllibTransport.get
_urllib_get_patcher = patch.object(UrllibTransport, "get", _guard_urllib_get)


def setUpModule():
    """Guard accidental network calls only while this module runs."""
    _urllib_get_patcher.start()


def tearDownModule():
    """Restore the real transport for subsequent test modules."""
    _urllib_get_patcher.stop()


class TestCLIArguments(unittest.TestCase):
    """Test CLI argument parsing."""

    def test_required_arguments(self):
        """Require all public arguments."""
        with patch("sys.stderr", new_callable=StringIO):
            exit_code = main([])
        self.assertEqual(exit_code, 2)

    def test_no_path_options(self):
        """CLI has no path options."""
        import argparse
        from evidence_loop_vercel_web_analytics.cli import main

        parser = argparse.ArgumentParser()
        parser.add_argument("--site-url", required=True)
        parser.add_argument("--site-id", required=True)
        parser.add_argument("--scope-ref", required=True)
        parser.add_argument("--since", required=True)
        parser.add_argument("--until", required=True)
        parser.add_argument("--stale-threshold", type=int, default=24)

        actions = {action.dest for action in parser._actions}
        self.assertNotIn("output", actions)
        self.assertNotIn("output_file", actions)
        self.assertNotIn("output_path", actions)
        self.assertNotIn("file", actions)
        self.assertNotIn("path", actions)

    def test_help_exits_zero(self):
        """Help exits with zero."""
        with patch("sys.stdout", new_callable=StringIO):
            exit_code = main(["--help"])
        self.assertEqual(exit_code, 0)

    def test_nonreflective_unknown_argument(self):
        """Unknown argument does not echo value."""
        with patch("sys.stderr", new_callable=StringIO) as stderr:
            with patch("sys.stdout", new_callable=StringIO) as stdout:
                exit_code = main(["--unknown-arg", "secret-token-value-12345"])

        self.assertEqual(exit_code, 2)
        stderr_output = stderr.getvalue()
        stdout_output = stdout.getvalue()
        self.assertNotIn("secret-token-value-12345", stderr_output)
        self.assertNotIn("secret-token-value-12345", stdout_output)
        self.assertNotIn("--unknown-arg", stderr_output)

    def test_nonreflective_bad_integer(self):
        """Bad integer value does not echo value."""
        with patch("sys.stderr", new_callable=StringIO) as stderr:
            with patch("sys.stdout", new_callable=StringIO) as stdout:
                exit_code = main([
                    "--site-url", "https://example.com",
                    "--site-id", "site-123",
                    "--scope-ref", "scope-456",
                    "--since", "2025-01-01T00:00:00Z",
                    "--until", "2025-01-02T00:00:00Z",
                    "--stale-threshold", "not-a-number-secret",
                ])

        self.assertEqual(exit_code, 2)
        stderr_output = stderr.getvalue()
        stdout_output = stdout.getvalue()
        self.assertNotIn("not-a-number-secret", stderr_output)
        self.assertNotIn("not-a-number-secret", stdout_output)

    def test_parse_error_is_json(self):
        """Parse error outputs valid JSON to stderr."""
        with patch("sys.stderr", new_callable=StringIO) as stderr:
            exit_code = main(["--invalid"])

        self.assertEqual(exit_code, 2)
        error = json.loads(stderr.getvalue())
        self.assertEqual(error["error"]["code"], "INVALID_ARGUMENTS")


class TestCLIExecution(unittest.TestCase):
    """Test CLI execution."""

    def setUp(self):
        """Set up test environment."""
        self.env_patcher = patch.dict(
            os.environ,
            {
                "VERCEL_TOKEN": "test_token",
                "VERCEL_PROJECT_ID": "prj_abc123",
                "VERCEL_SITE_URL": "https://example.com",
            },
            clear=False,
        )
        self.env_patcher.start()

    def tearDown(self):
        """Clean up test environment."""
        self.env_patcher.stop()

    def test_validation_error_exit_1(self):
        """Validation error exits with code 1."""
        with patch("sys.stderr", new_callable=StringIO) as stderr:
            exit_code = main([
                "--site-url", "http://example.com",
                "--site-id", "site-123",
                "--scope-ref", "scope-456",
                "--since", "2025-01-01T00:00:00Z",
                "--until", "2025-01-02T00:00:00Z",
            ])

        self.assertEqual(exit_code, 1)
        stderr_output = stderr.getvalue()
        error = json.loads(stderr_output)
        self.assertEqual(error["error"]["code"], "INVALID_SITE_URL")

    def test_no_credentials_in_error(self):
        """Error output contains no credentials."""
        with patch("sys.stderr", new_callable=StringIO) as stderr:
            main([
                "--site-url", "http://example.com",
                "--site-id", "site-123",
                "--scope-ref", "scope-456",
                "--since", "2025-01-01T00:00:00Z",
                "--until", "2025-01-02T00:00:00Z",
            ])

        stderr_output = stderr.getvalue()
        self.assertNotIn("test_token", stderr_output)
        self.assertNotIn("prj_abc123", stderr_output)
        self.assertNotIn("VERCEL_TOKEN", stderr_output)
        self.assertNotIn("VERCEL_PROJECT_ID", stderr_output)

    def test_invalid_window_exit_1(self):
        """Invalid window exits with code 1."""
        with patch("sys.stderr", new_callable=StringIO):
            exit_code = main([
                "--site-url", "https://example.com",
                "--site-id", "site-123",
                "--scope-ref", "scope-456",
                "--since", "2025-01-02T00:00:00Z",
                "--until", "2025-01-01T00:00:00Z",
            ])

        self.assertEqual(exit_code, 1)

    def test_missing_env_exit_1(self):
        """Missing environment variables exits with code 1."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("sys.stderr", new_callable=StringIO):
                exit_code = main([
                    "--site-url", "https://example.com",
                    "--site-id", "site-123",
                    "--scope-ref", "scope-456",
                    "--since", "2025-01-01T00:00:00Z",
                    "--until", "2025-01-02T00:00:00Z",
                ])

        self.assertEqual(exit_code, 1)

    def test_stdout_empty_on_failure(self):
        """Stdout must be empty on all failures."""
        with patch("sys.stdout", new_callable=StringIO) as stdout:
            with patch("sys.stderr", new_callable=StringIO):
                main([
                    "--site-url", "http://example.com",
                    "--site-id", "site-123",
                    "--scope-ref", "scope-456",
                    "--since", "2025-01-01T00:00:00Z",
                    "--until", "2025-01-02T00:00:00Z",
                ])

        self.assertEqual(stdout.getvalue(), "")


class TestCLINoRealSockets(unittest.TestCase):
    """Test CLI does not use real sockets."""

    def test_no_network_imports(self):
        """CLI module does not import network libraries."""
        import evidence_loop_vercel_web_analytics.cli as cli_module

        source_file = cli_module.__file__
        with open(source_file) as f:
            source = f.read()

        self.assertNotIn("import socket", source)
        self.assertNotIn("import requests", source)
        self.assertNotIn("import httpx", source)
        self.assertNotIn("import aiohttp", source)


if __name__ == "__main__":
    unittest.main()
