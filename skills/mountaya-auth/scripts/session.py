#!/usr/bin/env python3
"""
session.py — Create a Mountaya session token.

Reads MOUNTAYA_SECRET_KEY and MOUNTAYA_PUBLISHABLE_KEY from the environment,
creates a session token (or reuses a cached one that is still valid), and
prints it to stdout.

Usage:
  python3 scripts/session.py
  python3 scripts/session.py --no-cache
  python3 scripts/session.py --help

Environment variables:
  MOUNTAYA_SECRET_KEY        Secret key (sk_...) for session token creation.
  MOUNTAYA_PUBLISHABLE_KEY   Publishable key (pk_...) to bind the token to.
  MOUNTAYA_SESSION_BASE_URL  Override session base URL (default: https://internal.mountaya.com).
  MOUNTAYA_CACHE_DIR         Override cache directory (default: ~/.cache/mountaya).

Exit codes:
  0  Success
  1  Missing environment variables
  2  Session token creation failed
"""

import hashlib
import json
import os
import stat
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime

SESSION_BASE_URL = os.environ.get("MOUNTAYA_SESSION_BASE_URL", "https://internal.mountaya.com")
SESSION_ENDPOINT = SESSION_BASE_URL.rstrip("/") + "/v1/sessions"
CACHE_DIR = os.environ.get("MOUNTAYA_CACHE_DIR", os.path.join(os.path.expanduser("~"), ".cache", "mountaya"))
REQUEST_TIMEOUT = 30  # seconds
CACHE_SAFETY_MARGIN = 60  # re-mint if the cached token expires in less than this many seconds

# Retry/backoff policy (matches SKILL.md "Rate limiting" sections).
RETRY_429_WAITS = [2, 4, 8]         # between attempts 1→2, 2→3, 3→4 (max 4 attempts on 429)
RETRY_AFTER_CAP_SECONDS = 15        # clamp Retry-After header to this
RETRY_5XX_WAIT = 2                  # single retry after 2s on 5xx

HELP = """\
Usage: python3 scripts/session.py [--no-cache]

Create (or reuse) a Mountaya session token and print it to stdout.

The script exchanges your secret key and publishable key for a short-lived
session token (5-minute TTL). Tokens are cached on disk per publishable key
and reused until 1 minute before expiry. The token is printed to stdout with
no extra formatting, making it easy to capture in scripts or subprocesses.

Options:
  --no-cache    Skip the cache and always mint a fresh token.
  --help, -h    Show this help.

Environment variables (required):
  MOUNTAYA_SECRET_KEY        Secret key (sk_...) for session token creation
  MOUNTAYA_PUBLISHABLE_KEY   Publishable key (pk_...) to bind the token to

Environment variables (optional):
  MOUNTAYA_SESSION_BASE_URL  Override session base URL (default: https://internal.mountaya.com)
  MOUNTAYA_CACHE_DIR         Override cache directory (default: ~/.cache/mountaya)

Examples:
  # Print a session token (from cache when possible)
  python3 scripts/session.py

  # Capture in a variable
  TOKEN=$(python3 scripts/session.py)

  # Force a fresh token
  python3 scripts/session.py --no-cache

Exit codes:
  0  Success
  1  Missing environment variables
  2  Session token creation failed"""


def log(message):
    print(message, file=sys.stderr)


def urlopen_with_retry(req, timeout):
    """urlopen with retry on 429 (up to 4 attempts) and 5xx (one retry after 2s).

    Matches the backoff policy documented in the mountaya-auth and mountaya-data-api
    SKILL.md "Rate limiting" sections. Retry-After, when numeric, is honored and
    clamped to RETRY_AFTER_CAP_SECONDS. Other 4xx failures (400/401/403) are not
    retried.
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
    # Unreachable: loop always either returns or raises.
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


def cache_path(publishable_key):
    """Return the cache file path for this publishable key at the current base URL."""
    # Hash key + base URL so different environments (staging vs prod) don't collide,
    # and the publishable key is never written in plaintext as a filename.
    digest = hashlib.sha256(f"{SESSION_ENDPOINT}\0{publishable_key}".encode()).hexdigest()[:16]
    return os.path.join(CACHE_DIR, f"session-{digest}.json")


def read_cached_token(publishable_key):
    """Return a cached token if it's still valid, otherwise None."""
    path = cache_path(publishable_key)
    try:
        with open(path, "r") as f:
            entry = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None

    token = entry.get("token")
    expires_at_epoch = entry.get("expires_at_epoch")
    if not token or not isinstance(expires_at_epoch, (int, float)):
        return None

    if time.time() >= expires_at_epoch - CACHE_SAFETY_MARGIN:
        return None

    return token


def write_cached_token(publishable_key, token, expires_at_iso):
    """Persist token + expiry. Silent on failure (cache is an optimization)."""
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        os.chmod(CACHE_DIR, stat.S_IRWXU)  # 0o700
    except OSError:
        return

    try:
        # Normalize the API's ISO-8601 string into a Unix epoch for cheap comparisons.
        # Accept both "Z" and "+00:00" suffixes.
        iso = expires_at_iso.replace("Z", "+00:00") if expires_at_iso else ""
        expires_at_epoch = datetime.fromisoformat(iso).timestamp() if iso else time.time() + 240
    except (TypeError, ValueError):
        # Fall back to a conservative 4 minutes from now if the API didn't return a parseable expiry.
        expires_at_epoch = time.time() + 240

    path = cache_path(publishable_key)
    try:
        # Write to a temp file and rename for atomicity.
        tmp_path = path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump({"token": token, "expires_at_epoch": expires_at_epoch}, f)
        os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
        os.replace(tmp_path, path)
    except OSError:
        pass


def create_session_token(secret_key, publishable_key):
    """Create and return a (token, expires_at_iso) tuple, or exit with code 2 on failure."""
    log("Creating session token...")
    body = json.dumps({"publishable_key": publishable_key}).encode()
    req = urllib.request.Request(
        SESSION_ENDPOINT,
        data=body,
        headers={
            "X-API-Key": secret_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen_with_retry(req, timeout=REQUEST_TIMEOUT) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode(errors="replace")
        log(f"Error: session token creation failed (HTTP {e.code}).")
        log(error_body)
        sys.exit(2)
    except urllib.error.URLError as e:
        log(f"Error: could not reach session endpoint: {e.reason}")
        sys.exit(2)
    except (TimeoutError, OSError) as e:
        log(f"Error: session endpoint timed out or unreachable: {e}")
        sys.exit(2)
    except json.JSONDecodeError as e:
        log(f"Error: session endpoint returned non-JSON payload: {e}")
        sys.exit(2)

    data = payload.get("data") if isinstance(payload, dict) else None
    token = data.get("token") if isinstance(data, dict) else None
    if not token:
        log("Error: session endpoint response missing data.token.")
        log(json.dumps(payload)[:500])
        sys.exit(2)

    log("Session token created.")
    return token, (data.get("expires_at") if isinstance(data, dict) else None)


def main():
    args = sys.argv[1:]
    if any(a in ("--help", "-h") for a in args):
        print(HELP)
        sys.exit(0)

    use_cache = "--no-cache" not in args

    secret_key, publishable_key = require_env_keys()

    if use_cache:
        cached = read_cached_token(publishable_key)
        if cached:
            log("Using cached session token.")
            print(cached)
            return

    token, expires_at_iso = create_session_token(secret_key, publishable_key)
    if use_cache:
        write_cached_token(publishable_key, token, expires_at_iso)
    print(token)


if __name__ == "__main__":
    main()
