"""eDocAPI command-line interface."""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

from edocapi import __author__, __version__


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="edocapi",
        description="eDocAPI - lightweight document-processing API framework",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"eDocAPI {__version__} (by {__author__})",
    )

    sub = parser.add_subparsers(dest="command")

    # edocapi run
    run_parser = sub.add_parser("run", help="Start the development server")
    run_parser.add_argument(
        "app",
        nargs="?",
        default="main:app",
        help="Application import path (default: main:app)",
    )
    run_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind host (default: 127.0.0.1)",
    )
    run_parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Bind port (default: 8000)",
    )
    run_parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload on code changes",
    )

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    if args.command == "run":
        _run_server(args)


def _run_server(args: argparse.Namespace) -> None:
    try:
        import uvicorn
    except ImportError:
        print(
            "uvicorn is required to run the development server.\n"
            "Install with: pip install 'uvicorn[standard]'",
            file=sys.stderr,
        )
        sys.exit(1)

    module_str, _, attr = args.app.partition(":")
    if not attr:
        attr = "app"

    print(f"eDocAPI v{__version__}")
    print(f"Author:      {__author__}")
    print()
    print(f"Application: {args.app}")
    print(f"Server:      http://{args.host}:{args.port}")
    print(f"Reload:      {'enabled' if args.reload else 'disabled'}")
    print()

    uvicorn.run(
        f"{module_str}:{attr}",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
