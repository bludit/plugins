#!/usr/bin/env python3
"""Validate submissions without downloading anything.

A quick check of the JSON files themselves, useful while writing a submission.
The full check, including the zip and the PHP inside it, is analyze.py.

    python3 scripts/validate.py                      # every submission
    python3 scripts/validate.py plugins/hello.json   # only this one
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from analyze import Report, check_submission  # noqa: E402


def main():
    targets = sys.argv[1:]
    if not targets:
        directory = os.path.join(ROOT, "plugins")
        targets = [os.path.join(directory, name)
                   for name in sorted(os.listdir(directory)) if name.endswith(".json")]

    if not targets:
        print("No submissions found in plugins/")
        return 0

    total_errors = 0
    for path in targets:
        plugin_id = os.path.basename(path)[:-5]
        report = Report(plugin_id)
        check_submission(path, report)
        if report.errors:
            total_errors += len(report.errors)
            print("FAIL %s" % path)
            for finding in report.errors:
                print("     [%s] %s" % (finding["code"], finding["message"]))
                if finding["hint"]:
                    print("            %s" % finding["hint"])
        else:
            print("ok   %s" % path)

    print()
    print("%d file(s) checked, %d error(s)" % (len(targets), total_errors))
    print("Run scripts/analyze.py to also check the zip and the PHP source.")
    return 1 if total_errors else 0


if __name__ == "__main__":
    sys.exit(main())
