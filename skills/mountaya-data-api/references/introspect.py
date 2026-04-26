#!/usr/bin/env python3
"""
introspect.py — Fetch and display the Mountaya Data API GraphQL schema.

Authenticates via the mountaya-auth session script, runs a GraphQL
introspection query, and prints a human-readable schema to stdout.
Caches the rendered schema on disk for 24 hours to minimize API usage.

Usage:
  python3 references/introspect.py
  python3 references/introspect.py --no-cache
  python3 references/introspect.py --help

Environment variables:
  MOUNTAYA_SECRET_KEY        Secret key (sk_...) for session token creation.
  MOUNTAYA_PUBLISHABLE_KEY   Publishable key (pk_...) with the data scope.
  MOUNTAYA_SESSION_BASE_URL  Override session base URL (default: https://internal.mountaya.com).
  MOUNTAYA_DATA_BASE_URL     Override Data API base URL (default: https://data.mountaya.com).
  MOUNTAYA_CACHE_DIR         Override cache directory (default: ~/.cache/mountaya).

Exit codes:
  0  Success
  1  Missing environment variables
  2  Session token creation failed
  3  Introspection query failed
"""

import hashlib
import json
import os
import stat
import subprocess
import sys
import time
import urllib.request
import urllib.error

DATA_BASE_URL = os.environ.get("MOUNTAYA_DATA_BASE_URL", "https://data.mountaya.com")
DATA_ENDPOINT = DATA_BASE_URL.rstrip("/") + "/graphql"
CACHE_DIR = os.environ.get("MOUNTAYA_CACHE_DIR", os.path.join(os.path.expanduser("~"), ".cache", "mountaya"))
CACHE_TTL_SECONDS = 24 * 60 * 60  # 24 hours
REQUEST_TIMEOUT = 60  # introspection payloads can be large

# Retry/backoff policy (matches SKILL.md "Rate limiting" sections).
RETRY_429_WAITS = [2, 4, 8]         # between attempts 1→2, 2→3, 3→4 (max 4 attempts on 429)
RETRY_AFTER_CAP_SECONDS = 15        # clamp Retry-After header to this
RETRY_5XX_WAIT = 2                  # single retry after 2s on 5xx

_REFERENCES_DIR = os.path.dirname(os.path.abspath(__file__))
_SKILL_DIR = os.path.dirname(_REFERENCES_DIR)
_SKILLS_DIR = os.path.dirname(_SKILL_DIR)
SESSION_SCRIPT = os.path.join(_SKILLS_DIR, "mountaya-auth", "scripts", "session.py")

_TYPE_REF = """
type {
  name
  kind
  ofType { name kind ofType { name kind ofType { name kind ofType { name kind ofType { name kind ofType { name kind ofType { name kind } } } } } } }
}
"""

INTROSPECTION_QUERY = """
{
  __schema {
    queryType { name }
    types {
      name
      kind
      description
      fields {
        name
        description
        %(type_ref)s
        args {
          name
          description
          %(type_ref)s
          defaultValue
        }
      }
      inputFields {
        name
        description
        %(type_ref)s
        defaultValue
      }
      enumValues {
        name
        description
      }
    }
  }
}
""" % {"type_ref": _TYPE_REF.strip()}

HELP = """\
Usage: python3 references/introspect.py [--no-cache]

Fetch and display the Mountaya Data API GraphQL schema via introspection.

Outputs a human-readable schema showing all query types, input types, enums,
fields, arguments, and descriptions. Use this to discover available fields
and types without relying on static documentation.

The rendered schema is cached on disk (keyed by Data API base URL) for 24
hours to minimize organization API usage. Pass --no-cache to force a refetch.

Options:
  --no-cache    Skip the cache and refetch the schema from the API.
  --help, -h    Show this help.

Environment variables (required):
  MOUNTAYA_SECRET_KEY        Secret key (sk_...) for session token creation
  MOUNTAYA_PUBLISHABLE_KEY   Publishable key (pk_...) with the data scope

Environment variables (optional):
  MOUNTAYA_SESSION_BASE_URL  Override session base URL (default: https://internal.mountaya.com)
  MOUNTAYA_DATA_BASE_URL     Override Data API base URL (default: https://data.mountaya.com)
  MOUNTAYA_CACHE_DIR         Override cache directory (default: ~/.cache/mountaya)

Exit codes:
  0  Success
  1  Missing environment variables
  2  Session token creation failed
  3  Introspection query failed"""


def log(message):
    print(message, file=sys.stderr)


def urlopen_with_retry(req, timeout):
    """urlopen with retry on 429 (up to 4 attempts) and 5xx (one retry after 2s).

    Matches the backoff policy documented in the mountaya-data-api SKILL.md
    "Rate limiting" section. Retry-After, when numeric, is honored and clamped
    to RETRY_AFTER_CAP_SECONDS. Other 4xx failures (400/401/403) are not retried.
    """
    five_xx_retried = False
    max_attempts = len(RETRY_429_WAITS) + 1
    for attempt in range(max_attempts):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < max_attempts - 1:
                retry_after = (e.headers.get("Retry-After") or "").strip()
                wait = min(int(retry_after), RETRY_AFTER_CAP_SECONDS) if retry_after.isdigit() else RETRY_429_WAITS[attempt]
                log(f"Rate limited (HTTP 429). Retrying in {wait}s ({max_attempts - attempt - 1} attempt(s) left)...")
                time.sleep(wait)
                continue
            if 500 <= e.code < 600 and not five_xx_retried:
                five_xx_retried = True
                log(f"Server error (HTTP {e.code}). Retrying in {RETRY_5XX_WAIT}s...")
                time.sleep(RETRY_5XX_WAIT)
                continue
            raise
    raise RuntimeError("urlopen_with_retry exhausted without result")


def require_env_keys():
    """Return (secret_key, publishable_key) or exit with code 1."""
    secret_key = os.environ.get("MOUNTAYA_SECRET_KEY", "")
    publishable_key = os.environ.get("MOUNTAYA_PUBLISHABLE_KEY", "")

    missing = []
    if not secret_key:
        missing.append("MOUNTAYA_SECRET_KEY")
    if not publishable_key:
        missing.append("MOUNTAYA_PUBLISHABLE_KEY")

    if missing:
        log(f"Error: missing environment variable(s): {' '.join(missing)}")
        log("Set them with:")
        log('  export MOUNTAYA_SECRET_KEY="sk_..."')
        log('  export MOUNTAYA_PUBLISHABLE_KEY="pk_..."')
        log("Create keys at https://app.mountaya.com/settings/api-keys")
        sys.exit(1)

    return secret_key, publishable_key


def cache_path():
    """Return the cache file path for the current Data API endpoint."""
    digest = hashlib.sha256(DATA_ENDPOINT.encode()).hexdigest()[:16]
    return os.path.join(CACHE_DIR, f"schema-{digest}.txt")


def read_cached_schema():
    """Return cached schema text if fresh, else None."""
    path = cache_path()
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None

    if time.time() - mtime >= CACHE_TTL_SECONDS:
        return None

    try:
        with open(path, "r") as f:
            return f.read()
    except OSError:
        return None


def write_cached_schema(text):
    """Persist the rendered schema. Silent on failure (cache is an optimization)."""
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        os.chmod(CACHE_DIR, stat.S_IRWXU)  # 0o700
    except OSError:
        return

    path = cache_path()
    try:
        tmp_path = path + ".tmp"
        with open(tmp_path, "w") as f:
            f.write(text)
        os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
        os.replace(tmp_path, path)
    except OSError:
        pass


def get_session_token(publishable_key):
    """Get a session token by calling the auth skill's session script."""
    if not os.path.exists(SESSION_SCRIPT):
        log(f"Error: session script not found at {SESSION_SCRIPT}")
        log("Ensure the mountaya-auth skill is installed alongside mountaya-data-api.")
        sys.exit(1)

    try:
        result = subprocess.run(
            [sys.executable, SESSION_SCRIPT],
            capture_output=True,
            text=True,
        )
    except OSError as e:
        log(f"Error: could not run session script: {e}")
        sys.exit(2)

    if result.returncode != 0:
        if result.stderr:
            sys.stderr.write(result.stderr)
        sys.exit(result.returncode)

    token = result.stdout.strip()
    if not token:
        log("Error: session script returned an empty token.")
        sys.exit(2)

    return token


def resolve_type(type_info):
    """Resolve a GraphQL type reference to a readable string."""
    if type_info is None:
        return "Unknown"

    kind = type_info.get("kind")
    name = type_info.get("name")

    if kind == "NON_NULL":
        inner = resolve_type(type_info.get("ofType"))
        return f"{inner}!"
    elif kind == "LIST":
        inner = resolve_type(type_info.get("ofType"))
        return f"[{inner}]"
    elif name:
        return name
    else:
        return "Unknown"


def format_schema(schema):
    """Format the introspection result into a human-readable string."""
    types = schema["data"]["__schema"]["types"]
    lines = []

    query_types = []
    input_types = []
    enum_types = []
    object_types = []
    scalar_types = []

    builtin_scalars = {"String", "Int", "Float", "Boolean", "ID"}

    for t in types:
        name = t["name"]
        if name.startswith("__"):
            continue

        kind = t["kind"]
        if kind == "ENUM":
            enum_types.append(t)
        elif kind == "INPUT_OBJECT":
            input_types.append(t)
        elif kind == "SCALAR":
            if name not in builtin_scalars:
                scalar_types.append(t)
        elif kind == "OBJECT":
            if name == "Query":
                query_types.append(t)
            else:
                object_types.append(t)

    for t in query_types:
        lines.append("=" * 60)
        lines.append("QUERIES (root operations)")
        lines.append("=" * 60)
        for field in (t.get("fields") or []):
            return_type = resolve_type(field["type"])
            desc = field.get("description") or ""
            lines.append(f"\n  {field['name']} -> {return_type}")
            if desc:
                lines.append(f"    {desc}")
            for arg in (field.get("args") or []):
                arg_type = resolve_type(arg["type"])
                arg_desc = arg.get("description") or ""
                default = arg.get("defaultValue")
                default_str = f" = {default}" if default else ""
                lines.append(f"    arg {arg['name']}: {arg_type}{default_str}")
                if arg_desc:
                    lines.append(f"      {arg_desc}")

    if scalar_types:
        lines.append(f"\n{'=' * 60}")
        lines.append("SCALARS (custom)")
        lines.append("=" * 60)
        for t in sorted(scalar_types, key=lambda x: x["name"]):
            desc = t.get("description") or ""
            lines.append(f"\n  {t['name']}")
            if desc:
                for line in desc.splitlines():
                    lines.append(f"    {line}")

    if enum_types:
        lines.append(f"\n{'=' * 60}")
        lines.append("ENUMS")
        lines.append("=" * 60)
        for t in sorted(enum_types, key=lambda x: x["name"]):
            desc = t.get("description") or ""
            lines.append(f"\n  {t['name']}")
            if desc:
                lines.append(f"    {desc}")
            for val in (t.get("enumValues") or []):
                val_desc = val.get("description") or ""
                if val_desc:
                    lines.append(f"    - {val['name']}: {val_desc}")
                else:
                    lines.append(f"    - {val['name']}")

    if input_types:
        lines.append(f"\n{'=' * 60}")
        lines.append("INPUT TYPES")
        lines.append("=" * 60)
        for t in sorted(input_types, key=lambda x: x["name"]):
            desc = t.get("description") or ""
            lines.append(f"\n  {t['name']}")
            if desc:
                lines.append(f"    {desc}")
            for field in (t.get("inputFields") or []):
                field_type = resolve_type(field["type"])
                field_desc = field.get("description") or ""
                default = field.get("defaultValue")
                default_str = f" = {default}" if default else ""
                lines.append(f"    {field['name']}: {field_type}{default_str}")
                if field_desc:
                    lines.append(f"      {field_desc}")

    if object_types:
        lines.append(f"\n{'=' * 60}")
        lines.append("OBJECT TYPES (response shapes)")
        lines.append("=" * 60)
        for t in sorted(object_types, key=lambda x: x["name"]):
            desc = t.get("description") or ""
            lines.append(f"\n  {t['name']}")
            if desc:
                lines.append(f"    {desc}")
            for field in (t.get("fields") or []):
                field_type = resolve_type(field["type"])
                field_desc = field.get("description") or ""
                lines.append(f"    {field['name']}: {field_type}")
                if field_desc:
                    lines.append(f"      {field_desc}")

    return "\n".join(lines)


def fetch_schema(publishable_key):
    """Run the introspection query and return the rendered schema text."""
    session_token = get_session_token(publishable_key)

    log("Running introspection query...")
    body = json.dumps({"query": INTROSPECTION_QUERY}).encode()
    req = urllib.request.Request(
        DATA_ENDPOINT,
        data=body,
        headers={
            "X-API-Key": publishable_key,
            "X-Session-Token": session_token,
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen_with_retry(req, timeout=REQUEST_TIMEOUT) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode(errors="replace")
        log(f"Error: introspection query failed (HTTP {e.code}).")
        log(error_body)
        sys.exit(3)
    except urllib.error.URLError as e:
        log(f"Error: could not reach Data API: {e.reason}")
        sys.exit(3)
    except (TimeoutError, OSError) as e:
        log(f"Error: Data API timed out or unreachable: {e}")
        sys.exit(3)
    except json.JSONDecodeError as e:
        log(f"Error: Data API returned non-JSON payload: {e}")
        sys.exit(3)

    if "errors" in payload:
        log("Error: introspection query returned errors.")
        log(json.dumps(payload["errors"], indent=2))
        sys.exit(3)

    if not (isinstance(payload.get("data"), dict) and isinstance(payload["data"].get("__schema"), dict)):
        log("Error: introspection payload missing data.__schema.")
        log(json.dumps(payload)[:500])
        sys.exit(3)

    return format_schema(payload)


def main():
    args = sys.argv[1:]
    if any(a in ("--help", "-h") for a in args):
        print(HELP)
        sys.exit(0)

    use_cache = "--no-cache" not in args

    if use_cache:
        cached = read_cached_schema()
        if cached:
            log("Using cached schema (pass --no-cache to refetch).")
            print(cached)
            return

    _, publishable_key = require_env_keys()
    text = fetch_schema(publishable_key)
    if use_cache:
        write_cached_schema(text)
    print(text)


if __name__ == "__main__":
    main()
