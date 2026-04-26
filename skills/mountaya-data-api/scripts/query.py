#!/usr/bin/env python3
"""
query.py — Authenticated query to the Mountaya Data API.

Authenticates via the mountaya-auth session script, then sends a GraphQL
query to the Data API.

Usage:
  python3 scripts/query.py '<graphql-query>'
  python3 scripts/query.py --file path/to/query.graphql
  cat query.graphql | python3 scripts/query.py -
  python3 scripts/query.py --help

Environment variables:
  MOUNTAYA_SECRET_KEY        Secret key (sk_...) for session token creation.
  MOUNTAYA_PUBLISHABLE_KEY   Publishable key (pk_...) with the data scope.
  MOUNTAYA_SESSION_BASE_URL  Override session base URL (default: https://internal.mountaya.com).
  MOUNTAYA_DATA_BASE_URL     Override Data API base URL (default: https://data.mountaya.com).

Exit codes:
  0  Success
  1  Missing environment variables, query argument, or file read error
  2  Session token creation failed
  3  GraphQL query failed (HTTP error, network error, or top-level errors in response)
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error

DATA_BASE_URL = os.environ.get("MOUNTAYA_DATA_BASE_URL", "https://data.mountaya.com")
DATA_ENDPOINT = DATA_BASE_URL.rstrip("/") + "/graphql"
REQUEST_TIMEOUT = 30  # seconds

# Retry/backoff policy (matches SKILL.md "Rate limiting" sections).
RETRY_429_WAITS = [2, 4, 8]         # between attempts 1→2, 2→3, 3→4 (max 4 attempts on 429)
RETRY_AFTER_CAP_SECONDS = 15        # clamp Retry-After header to this
RETRY_5XX_WAIT = 2                  # single retry after 2s on 5xx

# Resolve the path to the auth skill's session script.
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
_SKILLS_DIR = os.path.dirname(os.path.dirname(_SCRIPTS_DIR))
SESSION_SCRIPT = os.path.join(_SKILLS_DIR, "mountaya-auth", "scripts", "session.py")

HELP = """\
Usage: python3 scripts/query.py '<graphql-query>'
       python3 scripts/query.py --file path/to/query.graphql
       cat query.graphql | python3 scripts/query.py -

Authenticate and query the Mountaya Data API (GraphQL).

The script creates a session token using the mountaya-auth skill (reusing a
cached token when possible), then sends the GraphQL query with both
authentication headers.

Input modes:
  '<graphql-query>'         Inline query as the first argument.
  --file <path>             Read the query from a file (recommended for long queries).
  -                         Read the query from stdin.

Environment variables (required):
  MOUNTAYA_SECRET_KEY        Secret key (sk_...) for session token creation
  MOUNTAYA_PUBLISHABLE_KEY   Publishable key (pk_...) with the data scope

Environment variables (optional):
  MOUNTAYA_SESSION_BASE_URL  Override session base URL (default: https://internal.mountaya.com)
  MOUNTAYA_DATA_BASE_URL     Override Data API base URL (default: https://data.mountaya.com)

Examples:
  python3 scripts/query.py '{ directions(input: { activity: HIKING_AND_TRAIL, waypoints: [[6.1294, 45.8992], [6.2169, 45.8458]] }) { routes { distance duration summary } } }'

  python3 scripts/query.py --file queries/hike.graphql

  echo '{ directions(input: ...) { routes { distance } } }' | python3 scripts/query.py -

Exit codes:
  0  Success
  1  Missing environment variables, query argument, or file read error
  2  Session token creation failed
  3  GraphQL query failed (HTTP error, network error, or top-level errors in response)"""


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


def read_query(argv):
    """Resolve the GraphQL query from argv (inline, --file, or stdin). Exit 1 on error."""
    if len(argv) < 2:
        log("Error: missing GraphQL query argument.")
        log("Usage: python3 scripts/query.py '<graphql-query>'")
        log("       python3 scripts/query.py --file path/to/query.graphql")
        log("       cat query.graphql | python3 scripts/query.py -")
        log("Run with --help for examples.")
        sys.exit(1)

    first = argv[1]

    if first == "--file":
        if len(argv) < 3:
            log("Error: --file requires a path argument.")
            sys.exit(1)
        try:
            with open(argv[2], "r") as f:
                return f.read()
        except OSError as e:
            log(f"Error: could not read query file {argv[2]}: {e}")
            sys.exit(1)

    if first == "-":
        return sys.stdin.read()

    return first


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


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("--help", "-h"):
        print(HELP)
        sys.exit(0)

    _, publishable_key = require_env_keys()

    query = read_query(sys.argv)
    if not query.strip():
        log("Error: query is empty.")
        sys.exit(1)

    session_token = get_session_token(publishable_key)

    log("Querying Data API...")
    query_body = json.dumps({"query": query}).encode()
    query_req = urllib.request.Request(
        DATA_ENDPOINT,
        data=query_body,
        headers={
            "X-API-Key": publishable_key,
            "X-Session-Token": session_token,
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen_with_retry(query_req, timeout=REQUEST_TIMEOUT) as resp:
            result = resp.read().decode()
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        log(f"Error: Data API query failed (HTTP {e.code}).")
        log(body)
        sys.exit(3)
    except urllib.error.URLError as e:
        log(f"Error: could not reach Data API: {e.reason}")
        sys.exit(3)
    except (TimeoutError, OSError) as e:
        log(f"Error: Data API timed out or unreachable: {e}")
        sys.exit(3)

    print(result)

    # Flag top-level GraphQL errors via exit code (HTTP 200 + {"errors": [...]}).
    # Matches introspect.py's behavior so callers can rely on $? for both transport
    # and GraphQL-level failures. The raw response is already printed to stdout.
    try:
        parsed = json.loads(result)
    except (json.JSONDecodeError, ValueError):
        return
    if isinstance(parsed, dict) and parsed.get("errors"):
        log("Error: GraphQL response contains errors (see stdout).")
        sys.exit(3)


if __name__ == "__main__":
    main()
