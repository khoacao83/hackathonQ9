"""Command-line bridge client for assembly_line.llm.proxy_client.

Reads JSON from stdin, forwards it to a local HTTP LM bridge, and prints
JSON with a patch field to stdout.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def _ensure_utf8_stdio() -> None:
    """Force UTF-8 stdout/stderr on Windows consoles (cp1252 by default)."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            # Best effort: keep default stream config if reconfigure is unavailable.
            pass


def main() -> int:
    _ensure_utf8_stdio()

    bridge_url = os.environ.get("LM_BRIDGE_URL", "http://127.0.0.1:8765/patch").strip()
    timeout_seconds = float(os.environ.get("LM_BRIDGE_TIMEOUT", "90"))

    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(f"invalid stdin JSON: {exc}", file=sys.stderr)
        return 2

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        bridge_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(body or f"bridge HTTP {exc.code}", file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        return 4

    # Pass through bridge output. proxy_client accepts JSON with patch field.
    print(raw)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
