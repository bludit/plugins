# Rules

What a submission is checked against. Maintained by the Bludit maintainers,
you do not need to touch anything here to add a plugin — that is one file in
[`../plugins/`](../plugins), see [CONTRIBUTING.md](../CONTRIBUTING.md).

| File | What it is |
|---|---|
| `plugin.schema.json` | JSON Schema for `plugins/<id>.json`. The single source of truth for the fields, read by `scripts/analyze.py` and by `scripts/validate.py`, so the rules can never drift from the documentation. |
| `reserved.json` | Plugin ids and PHP class names already used by Bludit core. A plugin colliding with one of these cannot be installed: a duplicate directory would clash with the bundled plugin, and a duplicate class name is a fatal error PHP cannot recover from. |

`reserved.json` is generated, do not edit it by hand. Regenerate it whenever
Bludit adds, removes or renames a bundled plugin:

```bash
python3 scripts/refresh_reserved.py ~/github/bludit
```
