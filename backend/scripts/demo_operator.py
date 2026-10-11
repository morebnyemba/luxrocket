"""Act as an external operator: sign a session request and print the launch URL.

Usage:
  uv run python scripts/demo_operator.py --player alice [--api http://localhost:8000]
The key file is produced by `manage.py seed_demo` (first line kid, second base64 raw key).
"""

import argparse
import base64
import hashlib
import json
import secrets
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def sign(key: Ed25519PrivateKey, method: str, path: str, body: bytes) -> dict[str, str]:
    ts = str(int(time.time()))
    nonce = secrets.token_hex(16)
    digest = hashlib.sha256(body).hexdigest()
    message = f"LR1\n{method}\n{path}\n{ts}\n{nonce}\n{digest}".encode()
    signature = base64.urlsafe_b64encode(key.sign(message)).decode().rstrip("=")
    return {"LR-Timestamp": ts, "LR-Nonce": nonce, "LR-Signature": f"ed25519={signature}"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument(
        "--key", default=str(Path(__file__).resolve().parents[2] / ".demo-operator.key")
    )
    parser.add_argument("--player", default="demo-player-1")
    parser.add_argument("--alias", default="")
    parser.add_argument("--country", default="ZW")
    parser.add_argument("--currency", default="USD")
    parser.add_argument("--json", action="store_true", help="print the full response")
    args = parser.parse_args()

    kid, key_b64 = Path(args.key).read_text().split()
    key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(key_b64))
    payload = {
        "player": {
            "id": args.player,
            "country": args.country,
            "alias": args.alias or args.player[:24],
        },
        "currency": args.currency,
        "game": "lux-rocket",
        "mode": "SANDBOX",
        "locale": "en",
    }
    body = json.dumps(payload).encode()
    path = "/operator/v1/sessions"
    headers = {
        "Content-Type": "application/json",
        "LR-Key-Id": kid,
        "Idempotency-Key": str(uuid.uuid4()),
        **sign(key, "POST", path, body),
    }
    request = urllib.request.Request(args.api + path, data=body, headers=headers, method="POST")  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            data = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code}: {exc.read().decode()}", file=sys.stderr)
        return 1
    print(json.dumps(data, indent=2) if args.json else data["fragment_launch_url"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
