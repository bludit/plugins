#!/usr/bin/env python3
"""Check the rules in analyze.py against fixed fixtures.

Two suites, both driven by a file that records exactly what has to be reported:

  tests/corpus        one PHP file per case, an attack that has to be caught or
                      a legitimate pattern that must not be flagged
  tests/payload       a submission next to the zip it claims to describe, so
                      the cross-check keeps refusing a submission that does not
                      match what the author actually uploaded
  tests/submission    one case per field of the submission itself, run with
                      jsonschema and with the fallback so the two agree

A rule that stops firing, or starts firing on real code, fails here instead of
on somebody's pull request.

    python3 scripts/selftest.py

Exit status is 0 when everything matches, 1 otherwise.
"""

import copy
import json
import os
import shutil
import sys
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import analyze  # noqa: E402

CORPUS = os.path.join(ROOT, "tests", "corpus")
EXPECTED = os.path.join(ROOT, "tests", "expected.json")
PAYLOAD = os.path.join(ROOT, "tests", "payload")
PAYLOAD_EXPECTED = os.path.join(ROOT, "tests", "payload-expected.json")
SUBMISSION_EXPECTED = os.path.join(ROOT, "tests", "submission-expected.json")

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


def payload_findings(case):
    """Run the structure checks over one submission and its extracted zip."""
    directory = os.path.join(PAYLOAD, case)
    with open(os.path.join(directory, "submission.json")) as fh:
        submission = json.load(fh)

    roots = [n for n in sorted(os.listdir(directory))
             if os.path.isdir(os.path.join(directory, n))]
    if len(roots) != 1:
        raise SystemExit("%s must contain exactly one plugin directory" % case)

    # The id is the name of the submission file, which in a fixture is the name
    # of the plugin directory sitting next to it
    report = analyze.Report(roots[0])
    analyze.check_structure(os.path.join(directory, roots[0]), submission, report)
    return sorted("%s/%s" % (f["severity"], f["code"]) for f in report.findings)


def compare(label, cases, load):
    """Run every case and print one line each. Returns the failures."""
    failures = []
    for name in cases:
        got, want = load(name)
        if got == want:
            print("  ok   %-22s %s" % (name, ", ".join(got) or "no findings"))
        else:
            print("  FAIL %-22s" % name)
            print("       expected: %s" % (", ".join(want) or "no findings"))
            print("       got:      %s" % (", ".join(got) or "no findings"))
            failures.append(name)
    return failures


def run_payload():
    expected = {k: v for k, v in json.load(open(PAYLOAD_EXPECTED)).items()
                if not k.startswith("_")}
    on_disk = {n for n in os.listdir(PAYLOAD) if os.path.isdir(os.path.join(PAYLOAD, n))}

    failures = []
    for name in sorted(on_disk | set(expected)):
        if name not in expected:
            failures.append("%s: in payload/ but not in payload-expected.json" % name)
            print("  FAIL %-22s not in payload-expected.json" % name)
        elif name not in on_disk:
            failures.append("%s: in payload-expected.json but not in payload/" % name)
            print("  FAIL %-22s not in payload/" % name)

    cases = sorted(on_disk & set(expected))
    failures += compare("payload", cases,
                        lambda n: (payload_findings(n), sorted(expected[n])))
    return failures, len(expected)


def submission_case(spec, base):
    """Build one submission from the base and return the errors it produces."""
    data = copy.deepcopy(base)
    for field in spec.get("remove", []):
        data.pop(field, None)
    data.update(spec.get("set", {}))

    directory = os.path.join(ROOT, "plugins")
    name = spec.get("filename", "hello-world.json")
    path = os.path.join(directory, name)
    try:
        with open(path, "w") as fh:
            json.dump(data, fh)
        report = analyze.Report(name[:-5])
        analyze.check_submission(path, report)
        return sorted({f["code"] for f in report.errors})
    finally:
        if os.path.exists(path):
            os.remove(path)


def run_submission():
    spec = json.load(open(SUBMISSION_EXPECTED))
    base = spec["_base"]
    cases = spec["cases"]

    failures = []
    for name in sorted(cases):
        want = sorted(set(cases[name]["expect"]))

        got = submission_case(cases[name], base)

        # The same case again with jsonschema unavailable. An entry of None in
        # sys.modules makes the import raise, which is the fallback path.
        with mock.patch.dict(sys.modules, {"jsonschema": None}):
            got_fallback = submission_case(cases[name], base)

        if got != want:
            print("  FAIL %-26s expected: %s" % (name, ", ".join(want) or "accepted"))
            print("       %-26s got:      %s" % ("", ", ".join(got) or "accepted"))
            failures.append(name)
        elif got_fallback != want:
            print("  FAIL %-26s jsonschema and the fallback disagree" % name)
            print("       %-26s jsonschema: %s" % ("", ", ".join(got) or "accepted"))
            print("       %-26s fallback:   %s" % ("", ", ".join(got_fallback) or "accepted"))
            failures.append(name)
        else:
            print("  ok   %-26s %s" % (name, ", ".join(got) or "accepted"))

    return failures, len(cases)


def main():
    php = shutil.which("php")
    if php is None:
        print("PHP is not installed, the source checks cannot run.", file=sys.stderr)
        return 1

    reserved = json.load(open(os.path.join(ROOT, "rules", "reserved.json")))
    expected = {k: v for k, v in json.load(open(EXPECTED)).items()
                if not k.startswith("_")}

    print("Source rules against the corpus")
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
    print("The submission file")
    submission_failures, submission_total = run_submission()

    print("")
    print("Submission against the uploaded zip")
    payload_failures, payload_total = run_payload()

    print("")
    if failures or payload_failures or submission_failures:
        print("%d source, %d submission and %d payload case(s) failed."
              % (len(failures), len(submission_failures), len(payload_failures)),
              file=sys.stderr)
        return 1
    print("All %d corpus files, %d submission cases and %d payload cases match."
          % (len(expected), submission_total, payload_total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
