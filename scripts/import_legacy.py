#!/usr/bin/env python3
"""Generate draft submissions from the old bludit/plugins-repository.

Only the entries that already declare a Bludit v4 download are worth looking at,
the rest were written for v2 and v3. The output is a **starting point for a pull
request**, not something to merge: the old repository has no compatibility
field, no checksums and no fixed shape for the zip, so every draft still has to
pass analyze.py before it means anything.

    python3 scripts/import_legacy.py --out drafts/
"""

import argparse
import json
import os
import sys
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

API = "https://api.github.com/repos/bludit/plugins-repository/contents/items"
RAW = "https://raw.githubusercontent.com/bludit/plugins-repository/master/items/%s/metadata.json"


def get(url):
    request = Request(url, headers={
        "User-Agent": "bludit-plugins-import",
        "Accept": "application/vnd.github+json",
    })
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", "Bearer %s" % token)
    with urlopen(request, timeout=30) as response:
        return response.read()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="drafts")
    args = parser.parse_args()

    try:
        listing = json.loads(get(API))
    except (HTTPError, URLError, OSError) as exc:
        print("Unable to list the old repository: %s" % exc, file=sys.stderr)
        print("Set GITHUB_TOKEN if you are being rate limited.", file=sys.stderr)
        return 1

    os.makedirs(args.out, exist_ok=True)
    written = skipped = 0

    for item in listing:
        if item.get("type") != "dir":
            continue
        slug = item["name"]
        try:
            legacy = json.loads(get(RAW % slug))
        except (HTTPError, URLError, OSError, json.JSONDecodeError):
            continue

        download = legacy.get("download_url_v4")
        if not download:
            skipped += 1
            continue

        plugin_id = slug.lower().replace("_", "-").replace(" ", "-")
        draft = {
            "id": plugin_id,
            "name": legacy.get("name") or slug,
            "description": (legacy.get("description") or "").strip().replace("\n", " ")[:200],
            "author": legacy.get("author_username") or "",
            "website": legacy.get("information_url") or "",
            "license": legacy.get("license") or "",
            "compatible": "4.0",
            "version": legacy.get("version") or "",
            "releaseDate": legacy.get("release_date") or "",
            "download": download,
            "type": "",
        }

        target = os.path.join(args.out, "%s.json" % plugin_id)
        with open(target, "w") as fh:
            json.dump(draft, fh, indent=2)
            fh.write("\n")
        written += 1
        print("  %s" % target)

    print()
    print("%d draft(s) written, %d entry without a v4 download" % (written, skipped))
    print()
    print("These are drafts. Every one of them still needs:")
    print("  - a real release asset, /archive/*.zip is not accepted")
    print("  - the version to match the metadata.json inside the zip")
    print("  - to pass: python3 scripts/analyze.py <file>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
