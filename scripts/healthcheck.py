#!/usr/bin/env python3
"""Verify every asset in index.json still resolves and still matches its checksum.

The plugins are hosted by their authors, so a release can disappear or an asset
can be replaced long after the review. This is what catches that.

    python3 scripts/healthcheck.py --index index.json --output healthcheck.md

Writes nothing to the output file when everything is fine, so the workflow can
use an empty file to mean "no problems". Exit status is always 0, the report is
the result.
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

MAX_ZIP_BYTES = 10 * 1024 * 1024


def check(entry):
    """Returns (status, detail) where status is ok, gone or mismatch."""
    request = Request(entry["download"], headers={"User-Agent": "bludit-plugins-healthcheck"})
    try:
        with urlopen(request, timeout=60) as response:
            payload = response.read(MAX_ZIP_BYTES + 1)
    except HTTPError as exc:
        return "gone", "HTTP %s %s" % (exc.code, exc.reason)
    except (URLError, OSError) as exc:
        return "gone", str(exc)

    if len(payload) > MAX_ZIP_BYTES:
        return "mismatch", "the asset is bigger than the maximum allowed"

    digest = hashlib.sha256(payload).hexdigest()
    if digest != entry.get("sha256"):
        return "mismatch", "expected %s, got %s" % (entry.get("sha256"), digest)

    if len(payload) != entry.get("size"):
        return "mismatch", "expected %s bytes, got %d" % (entry.get("size"), len(payload))

    return "ok", ""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", default="index.json")
    parser.add_argument("--output", default="healthcheck.md")
    args = parser.parse_args()

    if not os.path.exists(args.index):
        print("No index to check: %s" % args.index, file=sys.stderr)
        open(args.output, "w").close()
        return 0

    with open(args.index) as fh:
        index = json.load(fh)

    gone, mismatch = [], []
    for entry in index.get("plugins", []):
        status, detail = check(entry)
        print("  %-30s %s %s" % (entry["id"], status, detail), file=sys.stderr)
        if status == "gone":
            gone.append((entry, detail))
        elif status == "mismatch":
            mismatch.append((entry, detail))

    if not gone and not mismatch:
        open(args.output, "w").close()
        print("Every asset resolves and matches its checksum.", file=sys.stderr)
        return 0

    lines = [
        "Automatic check of the assets listed in `index.json`.",
        "",
        "_Last run: %s_" % datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "",
    ]

    if mismatch:
        lines += [
            "## Checksum no longer matches",
            "",
            "The bytes changed under a version number that did not. This is what the checksum",
            "exists to catch, so **nothing is repaired automatically** — a maintainer has to look.",
            "Bludit refuses to install these, so users are not at risk in the meantime.",
            "",
        ]
        for entry, detail in mismatch:
            lines.append("- **%s %s** — %s" % (entry["id"], entry.get("version", ""), detail))
            lines.append("  <%s>" % entry["download"])
        lines.append("")

    if gone:
        lines += [
            "## Asset unreachable",
            "",
            "The release or the repository may have been deleted, or made private.",
            "",
        ]
        for entry, detail in gone:
            lines.append("- **%s %s** — %s" % (entry["id"], entry.get("version", ""), detail))
            lines.append("  <%s>" % entry["download"])
        lines.append("")

    with open(args.output, "w") as fh:
        fh.write("\n".join(lines) + "\n")

    print("%d unreachable, %d checksum mismatch" % (len(gone), len(mismatch)), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
