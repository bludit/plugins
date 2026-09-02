#!/usr/bin/env python3
"""Analyze a plugin submission: the JSON, the zip it points at, and the PHP inside it.

Writes a machine readable report so the workflow that comments on the pull
request never has to run any of the code it is reporting about.

    python3 scripts/analyze.py plugins/hello-world.json --report report.json

Exit status is 0 when there are no errors, 1 when there is at least one.
Warnings never change the exit status, a maintainer decides on those.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import zipfile
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

MAX_ZIP_BYTES = 10 * 1024 * 1024          # keep in sync with PLUGINS_MAX_ZIP_SIZE
MAX_UNCOMPRESSED_BYTES = 40 * 1024 * 1024  # keep in sync with PLUGINS_MAX_UNCOMPRESSED_SIZE
MAX_ASSET_BYTES = 200 * 1024              # single vendored asset, advisory only

ALLOWED_HOSTS = {
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
    "codeload.github.com",
    "raw.githubusercontent.com",
}

# Functions with no legitimate use inside a plugin listed in the directory
BANNED_CALLS = {
    "eval": "SRC_EVAL",
    "assert": "SRC_EVAL",
    "create_function": "SRC_EVAL",
    "exec": "SRC_SHELL",
    "shell_exec": "SRC_SHELL",
    "system": "SRC_SHELL",
    "passthru": "SRC_SHELL",
    "proc_open": "SRC_SHELL",
    "popen": "SRC_SHELL",
    "pcntl_exec": "SRC_SHELL",
    "dl": "SRC_SHELL",
}

# Legitimate for some plugins, always worth a human look
REVIEW_CALLS = {
    "curl_exec": "SRC_REMOTE_HTTP",
    "fsockopen": "SRC_REMOTE_HTTP",
    "stream_socket_client": "SRC_REMOTE_HTTP",
    "unlink": "SRC_FILESYSTEM_WRITE",
    "rmdir": "SRC_FILESYSTEM_WRITE",
    "file_put_contents": "SRC_FILESYSTEM_WRITE",
    "fopen": "SRC_FILESYSTEM_WRITE",
    "rename": "SRC_FILESYSTEM_WRITE",
    "chmod": "SRC_FILESYSTEM_WRITE",
    "call_user_func": "SRC_DYNAMIC_CALL",
    "call_user_func_array": "SRC_DYNAMIC_CALL",
    "extract": "SRC_DYNAMIC_CALL",
}

DECODERS = {"base64_decode", "gzinflate", "gzuncompress", "str_rot13", "gzdecode"}

SUPERGLOBALS = {"$_GET", "$_POST", "$_REQUEST", "$_COOKIE"}

# include and require are language constructs, not functions, so they never
# reach the T_STRING branch and need their own token names
INCLUDE_TOKENS = ("T_INCLUDE", "T_INCLUDE_ONCE", "T_REQUIRE", "T_REQUIRE_ONCE")


class Report:
    def __init__(self, plugin_id):
        self.plugin_id = plugin_id
        self.findings = []
        self.passed = []

    def add(self, severity, code, message, hint="", file="", line=0):
        self.findings.append({
            "severity": severity,
            "code": code,
            "file": file,
            "line": line,
            "message": message,
            "hint": hint,
        })

    def ok(self, label):
        self.passed.append(label)

    def error(self, *a, **kw):
        self.add("error", *a, **kw)

    def warning(self, *a, **kw):
        self.add("warning", *a, **kw)

    def info(self, *a, **kw):
        self.add("info", *a, **kw)

    @property
    def errors(self):
        return [f for f in self.findings if f["severity"] == "error"]

    @property
    def warnings(self):
        return [f for f in self.findings if f["severity"] == "warning"]

    def to_dict(self):
        return {
            "pluginId": self.plugin_id,
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "passed": self.passed,
            "findings": self.findings,
        }


# ---------------------------------------------------------------------------
# The submission
# ---------------------------------------------------------------------------

def load_reserved():
    with open(os.path.join(ROOT, "rules", "reserved.json")) as fh:
        return json.load(fh)


def check_submission(path, report):
    """Validate the JSON file itself. Returns the parsed submission or None."""
    filename_id = os.path.basename(path)[:-5] if path.endswith(".json") else None

    try:
        with open(path) as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        report.error("JSON_INVALID", "The file is not valid JSON: %s" % exc,
                     "Check for a trailing comma or a missing quote.", file=path, line=exc.lineno)
        return None

    if not isinstance(data, dict):
        report.error("JSON_INVALID", "The file must contain a JSON object.", file=path)
        return None

    # Derived fields are computed by CI, a submission must not carry them
    for field in ("sha256", "size", "checkedAt"):
        if field in data:
            report.error("FIELD_DERIVED",
                         "The field `%s` is calculated by the workflow and must not be in the submission." % field,
                         "Delete it, it is added to index.json automatically.", file=path)

    ok, schema_errors = validate_schema(data)
    for msg, hint in schema_errors:
        report.error("SCHEMA", msg, hint, file=path)

    plugin_id = data.get("id")

    if plugin_id and filename_id and plugin_id != filename_id:
        report.error("ID_FILENAME",
                     "The id `%s` does not match the filename `%s.json`." % (plugin_id, filename_id),
                     "Rename the file to `plugins/%s.json`, or change the id." % plugin_id, file=path)

    reserved = load_reserved()
    if plugin_id in reserved["bundledPluginIds"]:
        report.error("ID_BUNDLED",
                     "`%s` is a plugin bundled with Bludit." % plugin_id,
                     "Bundled plugins are not listed in the directory. Choose another id.", file=path)

    # Another submission already using this id
    for other in sorted(os.listdir(os.path.join(ROOT, "plugins"))):
        if not other.endswith(".json") or other == os.path.basename(path):
            continue
        if other[:-5] == plugin_id:
            report.error("ID_DUPLICATE",
                         "The id `%s` is already used by `plugins/%s`." % (plugin_id, other), file=path)

    if ok and not report.errors:
        report.ok("submission")

    return data


def validate_schema(data):
    """Validate against rules/plugin.schema.json.

    Uses jsonschema when it is installed, otherwise falls back to a check of
    the required fields and their patterns so the script still runs locally
    without any dependency.
    """
    with open(os.path.join(ROOT, "rules", "plugin.schema.json")) as fh:
        schema = json.load(fh)

    try:
        import jsonschema
    except ImportError:
        return _validate_manual(data, schema)

    validator = jsonschema.Draft7Validator(schema)
    errors = []
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
        field = ".".join(str(p) for p in err.path) or "(root)"
        errors.append(("`%s`: %s" % (field, err.message), _hint_for(field, schema)))
    return not errors, errors


def _validate_manual(data, schema):
    errors = []
    for field in schema["required"]:
        if field not in data:
            errors.append(("`%s` is required." % field, _hint_for(field, schema)))

    for field, value in data.items():
        spec = schema["properties"].get(field)
        if spec is None:
            errors.append(("`%s` is not a known field." % field, ""))
            continue
        if spec.get("type") == "string":
            if not isinstance(value, str):
                errors.append(("`%s` must be a string." % field, ""))
                continue
            pattern = spec.get("pattern")
            if pattern and not re.search(pattern, value):
                errors.append(("`%s` does not have the expected format." % field, _hint_for(field, schema)))
            if "maxLength" in spec and len(value) > spec["maxLength"]:
                errors.append(("`%s` is longer than %d characters." % (field, spec["maxLength"]), ""))
            if "minLength" in spec and len(value) < spec["minLength"]:
                errors.append(("`%s` is shorter than %d characters." % (field, spec["minLength"]), ""))
            if "enum" in spec and value not in spec["enum"]:
                errors.append(("`%s` must be one of: %s." % (field, ", ".join(repr(e) for e in spec["enum"])), ""))
    return not errors, errors


def _hint_for(field, schema):
    spec = schema["properties"].get(field.split(".")[0], {})
    return spec.get("description", "")


# ---------------------------------------------------------------------------
# The download
# ---------------------------------------------------------------------------

def check_download(url, report, dest):
    """Download the asset. Returns the path on success, None on failure."""
    from urllib.parse import urlparse

    parts = urlparse(url)
    if parts.scheme != "https":
        report.error("URL_SCHEME", "The download URL must use https.", file="download")
        return None
    if parts.hostname not in ALLOWED_HOSTS:
        report.error("URL_HOST",
                     "The host `%s` is not allowed." % parts.hostname,
                     "Allowed hosts: %s" % ", ".join(sorted(ALLOWED_HOSTS)), file="download")
        return None
    if "/archive/" in parts.path:
        report.error("URL_ARCHIVE",
                     "Archives generated by GitHub (`/archive/*.zip`) are not accepted.",
                     "Their bytes change over time so the checksum would not hold. "
                     "Attach a zip to a release instead, see templates/release.yml.", file="download")
        return None
    if not re.match(r"^/[^/]+/[^/]+/releases/download/[^/]+/[^/]+\.zip$", parts.path):
        report.error("URL_NOT_RELEASE",
                     "The download URL must point at a zip attached to a GitHub release.",
                     "Expected https://github.com/<user>/<repo>/releases/download/<tag>/<file>.zip", file="download")
        return None

    request = Request(url, headers={"User-Agent": "bludit-plugins-analyzer"})
    try:
        with urlopen(request, timeout=60) as response:
            payload = response.read(MAX_ZIP_BYTES + 1)
    except HTTPError as exc:
        report.error("URL_HTTP", "The server answered %s %s." % (exc.code, exc.reason),
                     "Check the release asset still exists and is public.", file="download")
        return None
    except (URLError, OSError) as exc:
        report.error("URL_UNREACHABLE", "Unable to download the file: %s" % exc, file="download")
        return None

    if len(payload) > MAX_ZIP_BYTES:
        report.error("ZIP_TOO_BIG",
                     "The zip is bigger than %d MB." % (MAX_ZIP_BYTES // (1024 * 1024)), file="download")
        return None

    with open(dest, "wb") as fh:
        fh.write(payload)

    report.ok("download")
    return dest


# ---------------------------------------------------------------------------
# The archive
# ---------------------------------------------------------------------------

def check_archive(zip_path, report, extract_to):
    """Check the archive is safe, then extract it. Returns the plugin root or None."""
    try:
        archive = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile:
        report.error("ZIP_INVALID", "The file is not a valid zip archive.", file="download")
        return None

    with archive:
        uncompressed = 0
        for info in archive.infolist():
            name = info.filename
            if ".." in name or name.startswith("/") or "\\" in name or ":" in name:
                report.error("ZIP_TRAVERSAL",
                             "The entry `%s` has an unsafe name." % name,
                             "Entries must be relative paths without `..`.", file=name)
                return None
            # High bits of the external attributes hold the Unix file mode
            if (info.external_attr >> 16) & 0xF000 == 0xA000:
                report.error("ZIP_SYMLINK",
                             "The entry `%s` is a symbolic link." % name,
                             "Symbolic links can point outside bl-plugins and are not allowed.", file=name)
                return None
            uncompressed += info.file_size
            if uncompressed > MAX_UNCOMPRESSED_BYTES:
                report.error("ZIP_BOMB",
                             "The uncompressed content is bigger than %d MB."
                             % (MAX_UNCOMPRESSED_BYTES // (1024 * 1024)), file="download")
                return None

        archive.extractall(extract_to)

    report.ok("archive safety")
    return find_root(extract_to, report)


def find_root(extract_to, report):
    """The directory holding plugin.php, either the top level or a single wrapper."""
    if os.path.isfile(os.path.join(extract_to, "plugin.php")):
        return extract_to

    entries = [e for e in sorted(os.listdir(extract_to)) if not e.startswith("__MACOSX")]
    directories = [e for e in entries if os.path.isdir(os.path.join(extract_to, e))]
    for directory in directories:
        candidate = os.path.join(extract_to, directory)
        if os.path.isfile(os.path.join(candidate, "plugin.php")):
            return candidate

    report.error("ZIP_NO_PLUGIN",
                 "The zip does not contain a `plugin.php`.",
                 "The zip must hold the plugin files, either at the top level or inside a single directory.",
                 file="download")
    return None


# ---------------------------------------------------------------------------
# The structure
# ---------------------------------------------------------------------------

def check_structure(root, submission, report):
    plugin_id = submission.get("id", "")

    junk = {".git", "node_modules", ".DS_Store", "__MACOSX", ".idea", ".vscode"}
    for current, directories, files in os.walk(root):
        for name in list(directories) + files:
            if name in junk:
                relative = os.path.relpath(os.path.join(current, name), root)
                report.warning("ZIP_JUNK",
                               "`%s` should not be in the released zip." % relative,
                               "Exclude development files from the release asset.", file=relative)

    metadata_path = os.path.join(root, "metadata.json")
    if not os.path.isfile(metadata_path):
        report.error("META_MISSING", "The plugin has no `metadata.json`.",
                     "Every Bludit plugin needs one next to plugin.php.", file="metadata.json")
        return
    try:
        with open(metadata_path) as fh:
            metadata = json.load(fh)
    except json.JSONDecodeError as exc:
        report.error("META_INVALID", "`metadata.json` is not valid JSON: %s" % exc, file="metadata.json")
        return

    for field in ("version", "compatible"):
        if not metadata.get(field):
            report.error("META_INCOMPLETE", "`metadata.json` has no `%s`." % field, file="metadata.json")

    if metadata.get("version") and metadata["version"] != submission.get("version"):
        report.error("META_VERSION_MISMATCH",
                     "The submission says `%s`, `metadata.json` says `%s`."
                     % (submission.get("version"), metadata["version"]),
                     "The two must be identical, otherwise the directory advertises a version it does not ship.",
                     file="metadata.json")

    if metadata.get("compatible") and metadata["compatible"] != submission.get("compatible"):
        report.error("META_COMPATIBLE_MISMATCH",
                     "The submission says `%s`, `metadata.json` says `%s`."
                     % (submission.get("compatible"), metadata["compatible"]),
                     file="metadata.json")

    language_path = os.path.join(root, "languages", "en.json")
    if not os.path.isfile(language_path):
        report.error("LANG_MISSING", "The plugin has no `languages/en.json`.",
                     "Bludit reads the name and the description of the plugin from it.",
                     file="languages/en.json")
    else:
        try:
            with open(language_path) as fh:
                language = json.load(fh)
        except json.JSONDecodeError as exc:
            report.error("LANG_INVALID", "`languages/en.json` is not valid JSON: %s" % exc,
                         file="languages/en.json")
        else:
            data = language.get("plugin-data")
            if not isinstance(data, dict) or not data.get("name") or not data.get("description"):
                report.error("LANG_INCOMPLETE",
                             "`languages/en.json` needs `plugin-data.name` and `plugin-data.description`.",
                             'For example: {"plugin-data":{"name":"Hello","description":"Says hello."}}',
                             file="languages/en.json")

    # The directory inside the zip should carry the plugin id
    if root != os.path.dirname(root) and os.path.basename(root) not in ("", plugin_id):
        if os.path.basename(root) != os.path.basename(os.path.normpath(root)):
            pass
        report.info("ZIP_DIRNAME",
                    "The directory inside the zip is `%s`, the id is `%s`."
                    % (os.path.basename(root), plugin_id),
                    "Bludit uses the id, so this is only cosmetic, but matching them avoids confusion.")

    for asset_dir, _dirs, files in os.walk(root):
        for name in files:
            path = os.path.join(asset_dir, name)
            if os.path.getsize(path) > MAX_ASSET_BYTES and name.endswith((".js", ".css")):
                relative = os.path.relpath(path, root)
                report.info("ASSET_LARGE",
                            "`%s` is %d KB." % (relative, os.path.getsize(path) // 1024),
                            "Large vendored assets make every install slower.", file=relative)

    if not any(f["code"].startswith(("META_", "LANG_")) for f in report.findings):
        report.ok("structure")


# ---------------------------------------------------------------------------
# The PHP source
# ---------------------------------------------------------------------------

def php_files(root):
    for current, _directories, files in os.walk(root):
        for name in sorted(files):
            if name.endswith(".php"):
                yield os.path.join(current, name)


def check_source(root, report):
    php = which_php()
    if php is None:
        report.warning("PHP_MISSING", "PHP is not available, the source was not analyzed.",
                       "Install PHP to run the source checks locally.")
        return

    reserved = load_reserved()
    found_plugin_class = False
    lint_failed = False

    for path in php_files(root):
        relative = os.path.relpath(path, root)

        # A parse error takes down the whole site, buildPlugins() includes
        # every plugin.php before any controller runs
        lint = subprocess.run([php, "-l", path], capture_output=True, text=True)
        if lint.returncode != 0:
            message = (lint.stdout + lint.stderr).strip().splitlines()
            detail = message[0] if message else "syntax error"
            report.error("SRC_PARSE", "`%s` does not parse: %s" % (relative, re.sub(r' in /.*', '', detail)),
                         "A plugin that does not parse takes down the whole site, not only the plugin.",
                         file=relative)
            lint_failed = True
            continue

        source = open(path, encoding="utf-8", errors="replace").read()

        # Advisory only: no bundled Bludit plugin uses this guard, and a
        # plugin.php that only declares a class does nothing when requested
        # directly. Worth suggesting, never worth blocking a merge.
        if not re.search(r"defined\s*\(\s*['\"]BLUDIT['\"]\s*\)", source[:400]):
            report.info("SRC_NO_GUARD",
                        "`%s` does not start with the Bludit guard." % relative,
                        "Optional. Adding `<?php defined('BLUDIT') or die('Bludit CMS.');` as the "
                        "first line stops the file being requested directly over HTTP.",
                        file=relative, line=1)

        tokens = tokenize(php, path)
        if tokens is None:
            continue

        found_plugin_class |= scan_tokens(tokens, relative, reserved, report)

    if not lint_failed:
        report.ok("php -l")

    if not found_plugin_class:
        report.error("SRC_NO_CLASS",
                     "No class extending `Plugin` was found.",
                     "`plugin.php` must declare `class pluginYourName extends Plugin`.",
                     file="plugin.php")


def which_php():
    for candidate in ("php", "/usr/bin/php", "/opt/homebrew/opt/php@8.5/bin/php"):
        try:
            subprocess.run([candidate, "-v"], capture_output=True, check=True)
            return candidate
        except (OSError, subprocess.CalledProcessError):
            continue
    return None


def tokenize(php, path):
    result = subprocess.run([php, os.path.join(HERE, "tokens.php"), path],
                            capture_output=True, text=True)
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def significant(tokens):
    """Tokens without whitespace and comments, keeping the original index."""
    return [t for t in tokens if t["name"] not in ("T_WHITESPACE", "T_COMMENT", "T_DOC_COMMENT")]


def scan_tokens(tokens, relative, reserved, report):
    """Returns True when the file declares a class extending Plugin."""
    items = significant(tokens)
    found_plugin_class = False
    decoders_seen = set()
    assembled = _assembled_variables(items)
    inside_backticks = False

    for index, token in enumerate(items):
        name, text, line = token["name"], token["text"], token["line"]

        # --- language constructs ---
        # eval is not a function, the tokenizer gives it its own token, the
        # same for the backtick operator which is a shell call
        if name == "T_EVAL":
            report.error("SRC_EVAL",
                         "`%s` uses `eval()` on line %d." % (relative, line),
                         "There is no legitimate use for this in a plugin listed in the directory.",
                         file=relative, line=line)
            continue

        # A backtick expression is delimited by two identical tokens, so the
        # closing one has to be swallowed or every shell call is reported twice
        if name == "T_SHELL_EXEC" or (name == "CHAR" and text == "`"):
            inside_backticks = not inside_backticks
            if inside_backticks:
                report.error("SRC_SHELL",
                             "`%s` runs a shell command with backticks on line %d." % (relative, line),
                             "There is no legitimate use for this in a plugin listed in the directory.",
                             file=relative, line=line)
            continue

        # include and require reach a file path that Bludit will execute. A
        # request controlled path is a remote code execution, anything else
        # computed is worth a human reading it.
        if name in INCLUDE_TOKENS:
            window = _statement_window(items, index)
            variables = [t for t in window if t["name"] == "T_VARIABLE"]
            tainted = [t for t in variables if t["text"] in SUPERGLOBALS]
            if tainted:
                report.error("SRC_DYNAMIC_INCLUDE",
                             "`%s` includes a path taken from `%s` on line %d."
                             % (relative, tainted[0]["text"], line),
                             "Request data must never reach include or require, that is a remote "
                             "code execution. Include a fixed path instead.",
                             file=relative, line=line)
            elif variables:
                report.warning("SRC_DYNAMIC_INCLUDE",
                               "`%s` includes a computed path on line %d." % (relative, line),
                               "Fine when the path is built from constants such as `PATH_PLUGINS`. "
                               "Please say in the pull request what it loads.",
                               file=relative, line=line)
            continue

        # Calling a variable bypasses every check that matches on a function
        # name, so the name it was built from decides the severity
        if name == "T_VARIABLE" and index + 1 < len(items) and items[index + 1]["text"] == "(":
            previous = items[index - 1]["name"] if index else ""
            if previous in ("T_OBJECT_OPERATOR", "T_DOUBLE_COLON", "T_FUNCTION",
                            "T_NULLSAFE_OBJECT_OPERATOR"):
                continue
            if text in assembled:
                report.error("SRC_DYNAMIC_CALL",
                             "`%s` calls `%s()`, a function name assembled at runtime, on line %d."
                             % (relative, text, line),
                             "Building a function name from pieces hides which function is called "
                             "and defeats every other check here. Call it by its name.",
                             file=relative, line=line)
            else:
                report.warning("SRC_DYNAMIC_CALL",
                               "`%s` calls the variable `%s()` on line %d." % (relative, text, line),
                               "Fine for a closure. Please say in the pull request what it calls.",
                               file=relative, line=line)
            continue

        # --- class declarations ---
        if name == "T_CLASS" and index + 1 < len(items) and items[index + 1]["name"] == "T_STRING":
            class_name = items[index + 1]["text"]
            previous = items[index - 1]["name"] if index else ""
            if previous == "T_DOUBLE_COLON":
                continue  # SomeClass::class
            if class_name in reserved["reservedClassNames"]:
                report.error("SRC_CLASS_RESERVED",
                             "The class `%s` is already used by Bludit." % class_name,
                             "Two classes with the same name is a fatal error that Bludit cannot recover "
                             "from. Rename the class.",
                             file=relative, line=line)
            if (index + 3 < len(items) and items[index + 2]["name"] == "T_EXTENDS"
                    and items[index + 3]["text"] == "Plugin"):
                found_plugin_class = True
            continue

        if name != "T_STRING":
            continue

        # A function call is a name followed by an open parenthesis, and not
        # preceded by -> :: or the keyword function
        is_call = (index + 1 < len(items) and items[index + 1]["text"] == "(")
        previous = items[index - 1]["name"] if index else ""
        if previous in ("T_OBJECT_OPERATOR", "T_DOUBLE_COLON", "T_FUNCTION", "T_NULLSAFE_OBJECT_OPERATOR"):
            continue
        if not is_call:
            continue

        lowered = text.lower()

        # unserialize on request data is object injection, on its own data it
        # is ordinary
        if lowered == "unserialize":
            window = _statement_window(items, index)
            tainted = [t for t in window
                       if t["name"] == "T_VARIABLE" and t["text"] in SUPERGLOBALS]
            if tainted:
                report.error("SRC_UNSERIALIZE",
                             "`%s` unserializes `%s` on line %d." % (relative, tainted[0]["text"], line),
                             "Unserializing request data lets a visitor build any object in Bludit. "
                             "Use `json_decode()` instead.",
                             file=relative, line=line)
            else:
                report.warning("SRC_UNSERIALIZE",
                               "`%s` calls `unserialize()` on line %d." % (relative, line),
                               "Safe only when the data is yours. Prefer `json_decode()`.",
                               file=relative, line=line)
            continue

        if lowered in BANNED_CALLS:
            report.error(BANNED_CALLS[lowered],
                         "`%s` calls `%s()` on line %d." % (relative, text, line),
                         "There is no legitimate use for this in a plugin listed in the directory.",
                         file=relative, line=line)
        elif lowered in DECODERS:
            decoders_seen.add(lowered)
        elif lowered in REVIEW_CALLS:
            report.warning(REVIEW_CALLS[lowered],
                           "`%s` calls `%s()` on line %d." % (relative, text, line),
                           "Legitimate for some plugins. Please say in the pull request why it is needed.",
                           file=relative, line=line)
        elif lowered == "file_get_contents" and _reads_remote(items, index):
            report.warning("SRC_REMOTE_HTTP",
                           "`%s` reads a remote URL on line %d." % (relative, line),
                           "Please say in the pull request what it contacts and why.",
                           file=relative, line=line)

    if len(decoders_seen) > 1:
        report.error("SRC_OBFUSCATION",
                     "`%s` combines %s." % (relative, " and ".join(sorted("`%s()`" % d for d in decoders_seen))),
                     "Chained decoding is the shape of hidden code. Ship readable source.",
                     file=relative)
    elif decoders_seen:
        report.warning("SRC_DECODER",
                       "`%s` uses %s." % (relative, ", ".join(sorted("`%s()`" % d for d in decoders_seen))),
                       "Fine for real data, suspicious when it hides code.",
                       file=relative)

    _scan_echoed_input(items, relative, report)
    return found_plugin_class


def _statement_window(items, index, limit=24):
    """The tokens of the expression starting after index, up to the statement end."""
    window = []
    depth = 0
    for offset in range(index + 1, min(index + limit, len(items))):
        text = items[offset]["text"]
        if text == "(":
            depth += 1
        elif text == ")":
            depth -= 1
            if depth < 0:
                break
        elif text == ";" and depth <= 0:
            break
        window.append(items[offset])
    return window


def _assembled_variables(items):
    """Variables assigned from concatenated literals or from a decoder.

    This is the shape that defeats every name based check in this file:

        $f = 'ass' . 'ert';
        $f($_POST['x']);

    Nothing here ever calls a banned function by its name, so matching on the
    call site alone would let it through. Knowing which variables were built
    rather than written is what turns that back into an error.
    """
    assembled = set()
    for index, token in enumerate(items):
        if token["name"] != "T_VARIABLE":
            continue
        if index + 1 >= len(items) or items[index + 1]["text"] != "=":
            continue
        window = _statement_window(items, index + 1)
        strings = [t for t in window if t["name"] == "T_CONSTANT_ENCAPSED_STRING"]
        concatenated = any(t["text"] == "." for t in window) and len(strings) > 1
        decoded = any(t["name"] == "T_STRING" and t["text"].lower() in DECODERS for t in window)
        if concatenated or decoded:
            assembled.add(token["text"])
    return assembled


def _reads_remote(items, index):
    for offset in range(index + 1, min(index + 4, len(items))):
        if items[offset]["name"] == "T_CONSTANT_ENCAPSED_STRING":
            return items[offset]["text"].strip("'\"").startswith(("http://", "https://", "//"))
    return False


def _scan_echoed_input(items, relative, report):
    """echo $_GET[...] without passing it through Sanitize::html()."""
    for index, token in enumerate(items):
        if token["name"] != "T_ECHO" and token["text"] != "print":
            continue
        for offset in range(index + 1, min(index + 8, len(items))):
            if items[offset]["text"] == ";":
                break
            if items[offset]["name"] == "T_VARIABLE" and items[offset]["text"] in SUPERGLOBALS:
                window = " ".join(t["text"] for t in items[max(0, index - 2):offset])
                if "Sanitize" not in window and "htmlspecialchars" not in window:
                    report.warning("SRC_ECHO_INPUT",
                                   "`%s` prints `%s` directly on line %d."
                                   % (relative, items[offset]["text"], items[offset]["line"]),
                                   "Pass it through `Sanitize::html()` first, otherwise it is an XSS.",
                                   file=relative, line=items[offset]["line"])
                break


# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("submission", help="path to plugins/<id>.json")
    parser.add_argument("--report", help="write the report as JSON to this path")
    parser.add_argument("--markdown", help="write the report as Markdown to this path")
    parser.add_argument("--skip-download", action="store_true",
                        help="only check the submission file, do not fetch the zip")
    parser.add_argument("--zip", dest="local_zip",
                        help="analyze this local zip instead of downloading, for checking a "
                             "plugin before publishing the release")
    args = parser.parse_args()

    plugin_id = os.path.basename(args.submission)
    plugin_id = plugin_id[:-5] if plugin_id.endswith(".json") else plugin_id
    report = Report(plugin_id)

    submission = check_submission(args.submission, report)

    if submission and not args.skip_download and not report.errors:
        import tempfile
        with tempfile.TemporaryDirectory() as workdir:
            if args.local_zip:
                zip_path = args.local_zip
                report.ok("local zip")
            else:
                zip_path = check_download(submission["download"], report,
                                          os.path.join(workdir, "plugin.zip"))
            if zip_path:
                extract_to = os.path.join(workdir, "extracted")
                os.makedirs(extract_to)
                root = check_archive(zip_path, report, extract_to)
                if root:
                    check_structure(root, submission, report)
                    check_source(root, report)

    payload = report.to_dict()

    if args.report:
        with open(args.report, "w") as fh:
            json.dump(payload, fh, indent=2)
    if args.markdown:
        from render import render
        with open(args.markdown, "w") as fh:
            fh.write(render(payload))

    if not args.report and not args.markdown:
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")

    print("\n%s: %d error(s), %d warning(s)"
          % (plugin_id, len(report.errors), len(report.warnings)), file=sys.stderr)
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.path.insert(0, HERE)
    sys.exit(main())
