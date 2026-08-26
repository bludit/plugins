#!/usr/bin/env python3
"""Regenerate data/reserved.json from a Bludit checkout.

The directory needs to know which plugin ids ship with Bludit and which class
names are already taken, so a submission colliding with core is rejected before
it reaches anybody's site.

    python3 scripts/refresh_reserved.py ~/github/bludit
"""

import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def classes_in(pattern):
    found = set()
    for path in glob.glob(pattern):
        with open(path, encoding="utf-8", errors="replace") as fh:
            for match in re.finditer(r"^class\s+([A-Za-z_][A-Za-z0-9_]*)", fh.read(), re.M):
                found.add(match.group(1))
    return found


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    bludit = os.path.abspath(sys.argv[1])
    if not os.path.isdir(os.path.join(bludit, "bl-plugins")):
        print("Not a Bludit checkout: %s" % bludit)
        return 2

    ids = sorted(os.path.basename(d) for d in glob.glob(os.path.join(bludit, "bl-plugins", "*"))
                 if os.path.isdir(d))

    reserved = classes_in(os.path.join(bludit, "bl-plugins", "*", "plugin.php"))
    for pattern in ("bl-kernel/*.class.php", "bl-kernel/helpers/*.class.php", "bl-kernel/abstract/*.class.php"):
        reserved |= classes_in(os.path.join(bludit, pattern))

    version = ""
    init = os.path.join(bludit, "bl-kernel", "boot", "init.php")
    if os.path.exists(init):
        match = re.search(r"BLUDIT_VERSION',\s*'([^']+)'", open(init).read())
        if match:
            version = match.group(1)

    payload = {
        "_comment": "Names already used by Bludit core. A plugin in the directory must not collide "
                    "with any of these. Regenerate with scripts/refresh_reserved.py against a Bludit checkout.",
        "bluditVersion": version,
        "bundledPluginIds": ids,
        "reservedClassNames": sorted(reserved),
    }

    target = os.path.join(ROOT, "data", "reserved.json")
    with open(target, "w") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")

    print("Wrote %s: %d bundled plugin(s), %d reserved class name(s), Bludit %s"
          % (target, len(ids), len(reserved), version or "unknown"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
