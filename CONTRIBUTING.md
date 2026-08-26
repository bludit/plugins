# Adding a plugin to the directory

A submission is **one JSON file**. You keep the code in your own repository.

## 1. Publish a release

The `download` field must point at a **zip attached to a GitHub release**.

Archives that GitHub generates for you (`/archive/main.zip`,
`/archive/refs/tags/v1.0.0.zip`) are **not accepted**. Their bytes are not
stable over time, so the checksum recorded in the index would eventually stop
matching and Bludit would refuse to install the plugin.

Copy [`templates/release.yml`](templates/release.yml) into your repository as
`.github/workflows/release.yml`, set `PLUGIN_ID`, and push a tag. It builds the
zip, checks the version matches the tag, and attaches it to the release.

The zip must contain, either at the top level or inside a single directory:

```
plugin.php          the class extending Plugin
metadata.json       version, compatible, author, licence
languages/en.json   {"plugin-data":{"name":"...","description":"..."}}
```

## 2. Write the submission

Copy [`templates/plugin.json`](templates/plugin.json) to
`plugins/<your-plugin-id>.json`. The filename must equal the `id`.

```json
{
  "id": "hello-world",
  "name": "Hello World",
  "description": "One line describing what the plugin does.",
  "author": "Your Name",
  "website": "https://github.com/your-user/hello-world",
  "license": "MIT",
  "compatible": "4.0",
  "version": "1.0.0",
  "releaseDate": "2026-01-31",
  "download": "https://github.com/your-user/hello-world/releases/download/v1.0.0/hello-world.zip",
  "type": "",
  "tags": ["example"]
}
```

| Field | Rule |
|---|---|
| `id` | Lowercase letters, numbers and hyphens. This is the directory Bludit creates inside `bl-plugins`. It must not collide with a plugin bundled with Bludit. |
| `description` | One line, up to 200 characters. |
| `compatible` | Bludit versions as `major.minor`, comma separated: `4.0` or `4.0,4.1`. Must match `metadata.json`. |
| `version` | Must be **identical** to the `version` in your `metadata.json`. |
| `download` | https, a GitHub release asset, ending in `.zip`. |
| `type` | Empty, or `editor` for a content editor, or `theme`. |

Do **not** add `sha256` or `size`. They are calculated by the workflow when the
index is rebuilt, and a submission that includes them is rejected.

## 3. Check it before opening the pull request

```bash
# the JSON only, instant
python3 scripts/validate.py plugins/hello-world.json

# everything, including the zip and the PHP inside it
python3 scripts/analyze.py plugins/hello-world.json

# against a local zip, before the release exists
python3 scripts/analyze.py plugins/hello-world.json --zip build/hello-world.zip
```

## 4. Open the pull request

A bot analyzes the submission and comments with anything that needs fixing:
file, line, what is wrong and how to fix it. Push a fix and the comment updates
itself.

- **Errors** block the merge.
- **Warnings** do not block, a maintainer reads them. Outbound HTTP requests,
  writing files outside the plugin workspace and dynamic calls are all
  legitimate for some plugins — say in the pull request why you need them and
  it will go faster.

## Releasing a new version

Open a pull request that changes `version`, `releaseDate` and `download`.

This is on purpose. The `sha256` in the index is what guarantees that the bytes
being installed are the bytes that were reviewed, so a new version has to be
reviewed too. It is a real change from pointing at `master.zip` and forgetting,
and it is the reason a plugin from this directory can be trusted.

## What the analyzer rejects

**Always an error**

- The zip is unreachable, too big, or not a zip.
- Entries with `..`, absolute paths, or symbolic links.
- No `plugin.php`, no `metadata.json`, no `languages/en.json`.
- The version in the submission does not match the one in `metadata.json`.
- Any `.php` file that does not parse. A plugin with a syntax error takes down
  the whole site, not only the plugin.
- No class extending `Plugin`.
- A class name, or a plugin id, already used by Bludit.
- `eval`, `assert`, `create_function`, backticks, `exec`, `shell_exec`,
  `system`, `passthru`, `proc_open`, `popen`.
- Chained decoding such as `eval(base64_decode(gzinflate(...)))`.

**A warning, reviewed by a person**

- Outbound HTTP requests.
- Writing files: `unlink`, `file_put_contents`, `rmdir`, `chmod`.
- Dynamic calls: `call_user_func`, `extract`.
- Printing `$_GET` or `$_POST` without `Sanitize::html()`.

The checks look at the parsed PHP, not at the raw text, so the word `system`
inside a comment or a string is not a finding.

## Removing a plugin

Open a pull request deleting `plugins/<id>.json`. Sites that already installed
it keep it, they simply stop being offered updates.
