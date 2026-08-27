# Adding a plugin

Copy [`templates/plugin.json`](templates/plugin.json) to `plugins/<your-id>.json`,
fill it in, open a pull request. That is the whole thing.

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

Three things trip people up:

- **The filename must match the `id`**, and the `id` is the directory Bludit
  creates inside `bl-plugins`.
- **`download` has to be a zip attached to a GitHub release.** Not
  `/archive/main.zip` — GitHub regenerates those, so the bytes change and the
  checksum recorded for your plugin would stop matching.
- **`version` has to be the same** as the one in your `metadata.json`.

A bot checks the pull request and comments with anything that needs fixing,
pointing at the file and the line. Push a fix and the comment updates itself.
Nothing else is expected from you.

Want to check before opening the pull request?

```bash
python3 scripts/analyze.py plugins/hello-world.json
```

## Building the zip

Your plugin repository needs `plugin.php`, `metadata.json` and
`languages/en.json`, and the zip has to contain them inside a directory named
after the plugin.

[`templates/release.yml`](templates/release.yml) does that for you. Copy it into
your repository as `.github/workflows/release.yml`, set `PLUGIN_ID`, push a tag,
and the zip is built and attached to the release.

## Releasing a new version

Open a pull request changing `version`, `releaseDate` and `download`.

The checksum recorded for a plugin is what guarantees the bytes people install
are the bytes that were reviewed, so a new version is reviewed too.

## What the bot rejects

**Blocks the merge:** a zip that cannot be downloaded or is not a valid plugin,
entries with `..` or symbolic links, a missing `plugin.php`, `metadata.json` or
`languages/en.json`, a version that disagrees with `metadata.json`, PHP that does
not parse, no class extending `Plugin`, an id or class name already used by
Bludit, and `eval`, shell commands or hidden encoded code.

**Flagged for a person to read, not blocked:** outbound HTTP requests, writing
files, dynamic calls, printing `$_GET` without `Sanitize::html()`. These are
legitimate for plenty of plugins — mention in the pull request why you need
them and it will go faster.

The checks read the parsed PHP, so the word `system` in a comment or a string
is not a problem.

## Removing a plugin

Open a pull request deleting `plugins/<id>.json`. Sites that already installed
it keep it, they just stop being offered updates.
