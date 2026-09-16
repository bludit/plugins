# Adding a plugin

Copy [`templates/plugin.json`](templates/plugin.json) to `plugins/<your-id>.json`,
fill it in, open a pull request. That is the whole thing.

```json
{
  "name": "Hello World",
  "description": {
    "en": "One line describing what the plugin does.",
    "es": "Una linea describiendo lo que hace el plugin."
  },
  "author": "Your Name",
  "website": "https://github.com/your-user/hello-world",
  "license": "MIT",
  "compatible": "4.0",
  "version": "1.0.0",
  "download": "https://github.com/your-user/hello-world/releases/download/v1.0.0/hello-world.zip",
  "type": "",
  "tags": ["example"]
}
```

`type` and `tags` are optional, everything above them is required. `id`,
`sha256` and `size` are added by the workflow, do not write them yourself.

Three things trip people up:

- **The filename is the id.** `plugins/hello-world.json` becomes
  `bl-plugins/hello-world`, so use lowercase letters, digits and hyphens.
- **`download` has to be a zip attached to a GitHub release.** Not
  `/archive/main.zip` — GitHub regenerates those, so the bytes change and the
  checksum recorded for your plugin would stop matching.
- **`compatible` decides who is offered the plugin.** Bludit only lists a
  plugin that names the `major.minor` the site is running, so `4.0` today.

`description` takes one line per language, keyed by a Bludit language code.
English is required and is what a site falls back to.

Nothing is read out of your zip. This file is the listing, so it is worth
getting right. The bot does compare the two and points out any difference for a
maintainer to look at, but it never rewrites what you wrote.

A bot checks the pull request and comments with anything that needs fixing,
pointing at the file and the line. Push a fix and the comment updates itself.
Nothing else is expected from you.

Want to check before opening the pull request?

```bash
python3 .github/scripts/analyze.py plugins/hello-world.json
```

## Building the zip

Your plugin repository needs `plugin.php`, `metadata.json` and
`languages/en.json`, and the zip has to contain them inside a directory named
after the plugin.

[`templates/release.yml`](templates/release.yml) does that for you. Copy it into
your repository as `.github/workflows/release.yml`, set `PLUGIN_ID`, push a tag,
and the zip is built and attached to the release.

## Releasing a new version

Open a pull request changing `version` and `download`.

The checksum recorded for a plugin is what guarantees the bytes people install
are the bytes that were reviewed, so a new version is reviewed too.

## Selling a plugin

Set `price_in_usd` and leave `download` out. Bludit cannot install an asset it
has to pay for, so a priced plugin is a listing only: it is hidden from the
plugin directory in the admin panel, it carries no checksum, and **its source
is never analyzed**. Sell and deliver it from your own website.

## What the bot rejects

**Blocks the merge:** a zip that cannot be downloaded or is not a valid plugin,
entries with `..` or symbolic links, a missing `plugin.php`, `metadata.json` or
`languages/en.json`, a `metadata.json` without `version` or `compatible`
(Bludit refuses to install it), PHP that does not parse, no class extending `Plugin`, an id or class name already used by
Bludit, and `eval`, shell commands or hidden encoded code. Also blocked:
`include` or `unserialize` reaching `$_GET`, `$_POST`, `$_REQUEST` or `$_COOKIE`,
and calling a function whose name was assembled at runtime.

**Flagged for a person to read, not blocked:** outbound HTTP requests, writing
files, calling a closure held in a variable, including a path built from
constants, `unserialize` on your own data, printing `$_GET` without
`Sanitize::html()`. These are legitimate for plenty of plugins — mention in the
pull request why you need them and it will go faster.

The checks read the parsed PHP, so the word `system` in a comment or a string
is not a problem.

## Removing a plugin

Open a pull request deleting `plugins/<id>.json`. Sites that already installed
it keep it, they just stop being offered updates.
