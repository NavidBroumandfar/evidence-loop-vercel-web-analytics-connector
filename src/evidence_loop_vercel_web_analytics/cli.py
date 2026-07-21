"""CLI interface for the connector."""

import argparse
import json
import sys

from .connector import DEFAULT_STALE_THRESHOLD_HOURS, collect
from .errors import (
    ConnectorError,
    PartialResponseError,
    ProviderUnavailableError,
    SecurityError,
    ValidationError,
)
from .safety import serialize_envelope


class _ParseError(Exception):
    """Private exception for argument parsing failures."""

    pass


class _SafeArgumentParser(argparse.ArgumentParser):
    """Argument parser that raises _ParseError instead of printing usage."""

    def error(self, message):
        raise _ParseError()


def main(argv: list[str] | None = None) -> int:
    """Main CLI entry point."""
    parser = _SafeArgumentParser(
        prog="evidence-loop-vercel-web-analytics-connector",
        description="Collect Vercel Web Analytics visits/count data",
        add_help=True,
    )
    parser.add_argument("--site-url", required=True, help="HTTPS site origin")
    parser.add_argument("--site-id", required=True, help="Public site identifier")
    parser.add_argument("--scope-ref", required=True, help="Public scope reference")
    parser.add_argument("--since", required=True, help="Window start (UTC ISO-8601 Z)")
    parser.add_argument("--until", required=True, help="Window end (UTC ISO-8601 Z)")
    parser.add_argument(
        "--stale-threshold",
        type=int,
        default=DEFAULT_STALE_THRESHOLD_HOURS,
        help=f"Stale threshold in hours (default: {DEFAULT_STALE_THRESHOLD_HOURS})",
    )

    try:
        args = parser.parse_args(argv)
    except _ParseError:
        error_msg = json.dumps({"error": {"code": "INVALID_ARGUMENTS", "message": "Invalid command-line arguments"}})
        print(error_msg, file=sys.stderr)
        return 2
    except SystemExit as e:
        if e.code == 0:
            return 0
        error_msg = json.dumps({"error": {"code": "INVALID_ARGUMENTS", "message": "Invalid command-line arguments"}})
        print(error_msg, file=sys.stderr)
        return 2

    try:
        envelope = collect(
            site_url=args.site_url,
            site_id=args.site_id,
            scope_ref=args.scope_ref,
            since=args.since,
            until=args.until,
            stale_threshold_hours=args.stale_threshold,
        )

        output = serialize_envelope(envelope)
        print(output, end="")
        return 0

    except ValidationError as e:
        error_msg = json.dumps({"error": {"code": e.code, "message": e.message}})
        print(error_msg, file=sys.stderr)
        return 1

    except PartialResponseError as e:
        error_msg = json.dumps({"error": {"code": e.code, "message": e.message}})
        print(error_msg, file=sys.stderr)
        return 2

    except ProviderUnavailableError as e:
        error_msg = json.dumps({"error": {"code": e.code, "message": e.message}})
        print(error_msg, file=sys.stderr)
        return 3

    except SecurityError as e:
        error_msg = json.dumps({"error": {"code": e.code, "message": e.message}})
        print(error_msg, file=sys.stderr)
        return 4

    except ConnectorError as e:
        error_msg = json.dumps({"error": {"code": e.code, "message": e.message}})
        print(error_msg, file=sys.stderr)
        return 5
