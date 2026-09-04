#!/usr/bin/env python3
"""Create a portable, validated BTC Committee visual URL.

The HTML shell is served by a stable Vercel production alias. Immutable CSS and
JavaScript are pinned by commit inside that shell. The report travels only in
the URL fragment, so it is not sent to the host.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import json
import pathlib
import sys

from validate_report import validate

BASE_URL = "https://btc-committee-visual-marceloapplemob-7630s-projects.vercel.app/"


def encode_base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", default="latest.json")
    parser.add_argument("--plain", action="store_true", help="use uncompressed #report= payload")
    args = parser.parse_args()

    path = pathlib.Path(args.path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    errors = validate(payload)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if args.plain:
        print(f"{BASE_URL}#report={encode_base64url(compact)}")
    else:
        compressed = gzip.compress(compact, compresslevel=9, mtime=0)
        print(f"{BASE_URL}#gz={encode_base64url(compressed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
