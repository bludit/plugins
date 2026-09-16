#!/usr/bin/env python3
"""Turn a report from analyze.py into the Markdown posted on the pull request.

The report is data produced while looking at code from a pull request, so
everything that comes out of it is escaped before it reaches the comment.
"""

import json
import sys

MARKER = "<!-- bludit-plugin-analyzer -->"

TITLES = {
    "error": "Errors — these block the merge",
    "warning": "Warnings — a maintainer will review these",
    "info": "Suggestions",
}


def escape(text):
    """Neutralize anything in a finding that could break out of the comment."""
    if text is None:
        return ""
    text = str(text).replace("\r", " ").replace("\n", " ")
    # A comment is never allowed to close the marker or open raw HTML
    text = text.replace("<", "&lt;").replace(">", "&gt;")
    return text.strip()


def location(finding):
    where = escape(finding.get("file"))
    if not where:
        return ""
    line = finding.get("line") or 0
    return "`%s:%d`" % (where, line) if line else "`%s`" % where


def render(report):
    plugin_id = escape(report.get("pluginId", "unknown"))
    errors = [f for f in report["findings"] if f["severity"] == "error"]
    warnings = [f for f in report["findings"] if f["severity"] == "warning"]
    infos = [f for f in report["findings"] if f["severity"] == "info"]

    lines = [MARKER]

    if errors:
        lines.append("## Plugin check failed — `%s`" % plugin_id)
    elif warnings:
        lines.append("## Plugin check passed with warnings — `%s`" % plugin_id)
    else:
        lines.append("## Plugin check passed — `%s`" % plugin_id)

    lines.append("")
    lines.append(summary(len(errors), len(warnings), len(infos)))
    lines.append("")

    for severity, group in (("error", errors), ("warning", warnings), ("info", infos)):
        if not group:
            continue
        lines.append("### %s" % TITLES[severity])
        lines.append("")
        for finding in group:
            head = "**%s" % escape(finding["message"])
            if not head.endswith("**"):
                head += "**"
            where = location(finding)
            if where:
                head = "**%s** — %s" % (where.strip("`"), escape(finding["message"]))
                head = head.replace("**%s**" % where.strip("`"), "**`%s`**" % where.strip("`"), 1)
            lines.append("%s &nbsp;`%s`" % (head, escape(finding["code"])))
            hint = escape(finding.get("hint"))
            if hint:
                lines.append(hint)
            lines.append("")

    passed = report.get("passed") or []
    if passed:
        lines.append("---")
        lines.append(" · ".join("✅ %s" % escape(p) for p in passed))
        lines.append("")

    lines.append("Run the same checks locally:")
    lines.append("")
    lines.append("```")
    lines.append("python3 scripts/analyze.py plugins/%s.json" % plugin_id)
    lines.append("```")

    return "\n".join(lines) + "\n"


def summary(errors, warnings, infos):
    if not errors and not warnings:
        return "Everything checks out. A maintainer will take it from here."

    parts = []
    if errors:
        parts.append("**%d error%s**" % (errors, "" if errors == 1 else "s"))
    if warnings:
        parts.append("**%d warning%s**" % (warnings, "" if warnings == 1 else "s"))
    if infos:
        parts.append("%d suggestion%s" % (infos, "" if infos == 1 else "s"))

    text = ", ".join(parts) + "."
    if errors:
        text += " Push a fix and this comment updates automatically."
    else:
        text += " Nothing here blocks the merge."
    return text


if __name__ == "__main__":
    source = sys.argv[1] if len(sys.argv) > 1 else "report.json"
    with open(source) as fh:
        sys.stdout.write(render(json.load(fh)))
