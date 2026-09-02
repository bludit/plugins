#!/usr/bin/env python3
"""Check the source rules in analyze.py against a fixed corpus.

Every file in tests/corpus is a small plugin, either an attack that has to be
caught or a legitimate pattern that must not be flagged. tests/expected.json
records what each one has to produce, so a rule that stops firing, or starts
firing on real code, fails here instead of on somebody's pull request.

    python3 scripts/selftest.py

Exit status is 0 when the corpus matches, 1 otherwise.
"""

import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import analyze  # noqa: E402

CORPUS = os.path.join(ROOT, "tests", "corpus")
EXPECTED = os.path.join(ROOT, "tests", "expected.json")

# The guard is advisory and the corpus files do not carry it, it would only add
# the same noise to all of them
IGNORED = {"SRC_NO_GUARD"}


def findings(php, path, reserved):
    report = analyze.Report("selftest")
    tokens = analyze.tokenize(php, path)
    if tokens is None:
        raise SystemExit("unable to tokenize %s, is PHP installed?" % path)
    analyze.scan_tokens(tokens, os.path.basename(path), reserved, report)
    return sorted("%s/%s" % (f["severity"], f["code"])
                  for f in report.findings if f["code"] not in IGNORED)


def main():
    php = shutil.which("php")
    if php is None:
        print("PHP is not installed, the source checks cannot run.", file=sys.stderr)
        return 1

    reserved = json.load(open(os.path.join(ROOT, "rules", "reserved.json")))
    expected = {k: v for k, v in json.load(open(EXPECTED)).items()
                if not k.startswith("_")}

    on_disk = {n for n in os.listdir(CORPUS) if n.endswith(".php")}
    failures = []

    for name in sorted(on_disk | set(expected)):
        if name not in expected:
            failures.append("%s: in the corpus but not in expected.json" % name)
            continue
        if name not in on_disk:
            failures.append("%s: in expected.json but not in the corpus" % name)
            continue

        got = findings(php, os.path.join(CORPUS, name), reserved)
        want = sorted(expected[name])
        if got == want:
            print("  ok   %-22s %s" % (name, ", ".join(got) or "no findings"))
        else:
            print("  FAIL %-22s" % name)
            print("       expected: %s" % (", ".join(want) or "no findings"))
            print("       got:      %s" % (", ".join(got) or "no findings"))
            failures.append(name)

    print("")
    if failures:
        print("%d of %d failed." % (len(failures), len(expected)), file=sys.stderr)
        return 1
    print("All %d corpus files match." % len(expected))
    return 0


if __name__ == "__main__":
    sys.exit(main())
