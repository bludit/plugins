#!/usr/bin/env python3
"""Rebuild index.json from the submissions in plugins/.

Every submission is re-validated, its asset downloaded, and the sha256 and the
size recorded. The output is deterministic: same submissions, same bytes, so a
rebuild with nothing to change produces an empty diff.

    python3 scripts/build_index.py --output index.json

Exit status is 1 when a submission fails to build.
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

HERE = os.path.dirname(os.path.abspath(__file__))
INTERNAL = os.path.dirname(HERE)          # .github, the machinery
ROOT = os.path.dirname(INTERNAL)          # the repository, where plugins/ lives
sys.path.insert(0, HERE)

from analyze import Report, check_submission  # noqa: E402

SCHEMA_VERSION = 1
MAX_ZIP_BYTES = 10 * 1024 * 1024

# The order of the keys in every entry of index.json. id, sha256 and size are
# added here, everything else is copied from the submission unchanged.
FIELD_ORDER = [
    "id", "name", "description", "author", "website", "license",
    "compatible", "version", "download", "price_in_usd", "type", "tags",
    "sha256", "size",
]


def submissions():
    directory = os.path.join(ROOT, "plugins")
    if not os.path.isdir(directory):
        return []
    return [os.path.join(directory, name)
            for name in sorted(os.listdir(directory)) if name.endswith(".json")]


def fetch(url):
    request = Request(url, headers={"User-Agent": "bludit-plugins-index"})
    with urlopen(request, timeout=60) as response:
        payload = response.read(MAX_ZIP_BYTES + 1)
    if len(payload) > MAX_ZIP_BYTES:
        raise ValueError("the asset is bigger than %d bytes" % MAX_ZIP_BYTES)
    return payload


def build(fail_fast=False):
    entries = []
    failures = []

    for path in submissions():
        name = os.path.basename(path)
        # Validate again before publishing. The pull request is gated, but this
        # is what index.json is actually generated from, so a file that reached
        # main any other way must not be able to publish itself.
        report = Report(name[:-5])
        data = check_submission(path, report)
        if data is None or report.errors:
            for finding in report.errors:
                failures.append("%s: [%s] %s" % (name, finding["code"], finding["message"]))
            continue

        # The filename is the id, the submission does not carry it
        data["id"] = name[:-5]

        # A priced plugin is a listing. There is no public asset to fetch, so it
        # carries no checksum and Bludit hides it from the admin panel.
        if data.get("price_in_usd") is not None:
            entry = {key: data[key] for key in FIELD_ORDER if key in data}
            entries.append(entry)
            print("  %-30s %s  paid listing, no asset"
                  % (entry["id"], entry.get("version", "?")), file=sys.stderr)
            continue

        try:
            payload = fetch(data["download"])
        except (HTTPError, URLError, OSError, ValueError, KeyError) as exc:
            failures.append("%s: unable to download the asset, %s" % (name, exc))
            if fail_fast:
                break
            continue

        entry = {key: data[key] for key in FIELD_ORDER if key in data}
        entry["sha256"] = hashlib.sha256(payload).hexdigest()
        entry["size"] = len(payload)
        entries.append(entry)
        print("  %-30s %s  %s" % (entry["id"], entry["version"], entry["sha256"][:16]), file=sys.stderr)

    entries.sort(key=lambda e: e["id"])
    return entries, failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=os.path.join(ROOT, "index.json"))
    parser.add_argument("--keep-generated", action="store_true",
                        help="keep the previous generated timestamp when nothing else changed")
    args = parser.parse_args()

    print("Building the index from %d submission(s)" % len(submissions()), file=sys.stderr)
    entries, failures = build()

    for failure in failures:
        print("  FAILED %s" % failure, file=sys.stderr)

    # Never write a partial index. A submission that fails to build would
    # silently drop the plugin from the directory, and every site would stop
    # being offered it. Leave the previous index in place and fail instead.
    if failures:
        print("", file=sys.stderr)
        print("The index was NOT written, %d submission(s) failed." % len(failures), file=sys.stderr)
        print("Fix them, or remove the submission, then run this again.", file=sys.stderr)
        return 1

    previous = None
    if os.path.exists(args.output):
        try:
            with open(args.output) as fh:
                previous = json.load(fh)
        except json.JSONDecodeError:
            previous = None

    # Only move the timestamp when the content actually changed, otherwise a
    # rebuild would produce a diff on every run
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if previous and previous.get("plugins") == entries:
        generated = previous.get("generated", generated)

    index = {
        "schema": SCHEMA_VERSION,
        "generated": generated,
        "plugins": entries,
    }

    with open(args.output, "w") as fh:
        json.dump(index, fh, indent=2)
        fh.write("\n")

    print("Wrote %s with %d plugin(s)" % (args.output, len(entries)), file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
