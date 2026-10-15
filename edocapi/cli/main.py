"""eDocAPI command-line interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="edocapi",
        description="eDocAPI – pure-Python document processing toolkit (v0.1.1)",
    )
    parser.add_argument("--version", action="store_true", help="Show version and exit")

    sub = parser.add_subparsers(dest="command")

    # convert
    p_conv = sub.add_parser("convert", help="Convert a document to PDF")
    p_conv.add_argument("input", type=Path, help="Input file")
    p_conv.add_argument("-o", "--output", type=Path, help="Output PDF path")

    # extract
    p_ext = sub.add_parser("extract", help="Extract text from a document")
    p_ext.add_argument("input", type=Path, help="Input file")

    # info
    p_info = sub.add_parser("info", help="Show document metadata")
    p_info.add_argument("input", type=Path, help="Input file")

    # ocr
    p_ocr = sub.add_parser("ocr", help="OCR an image or scanned PDF (requires ml extra)")
    p_ocr.add_argument("input", type=Path, help="Input file")
    p_ocr.add_argument("--lang", default="eng", help="Tesseract language (default: eng)")

    # compress
    p_comp = sub.add_parser("compress", help="Compress a PDF or image")
    p_comp.add_argument("input", type=Path, help="Input file")
    p_comp.add_argument("-o", "--output", type=Path, help="Output path")
    p_comp.add_argument("--target", type=str, help="Target size e.g. 500KB")

    args = parser.parse_args(argv)

    if args.version or args.command is None:
        from edocapi import __version__
        print(f"edocapi {__version__}")
        return 0

    from edocapi import Document
    from edocapi.config import _parse_size

    try:
        if args.command == "convert":
            doc = Document(args.input)
            result = doc.to_pdf()
            out = args.output or Path(args.input.stem + ".pdf")
            out.write_bytes(result.path.read_bytes())
            print(f"Wrote {out} ({out.stat().st_size} bytes)")

        elif args.command == "extract":
            text = Document(args.input).extract_text()
            print(text)

        elif args.command == "info":
            import json
            info = Document(args.input).info()
            print(json.dumps(info, indent=2, default=str))

        elif args.command == "ocr":
            text = Document(args.input).ocr(lang=args.lang)
            print(text)

        elif args.command == "compress":
            target = _parse_size(args.target) if args.target else None
            result = Document(args.input).compress(target_size=target)
            out = args.output or Path(f"compressed_{args.input.name}")
            out.write_bytes(result.path.read_bytes())
            print(f"Wrote {out} ({out.stat().st_size} bytes)")

    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
