"""Validate the app Secret contract from JSON stdin without AWS or cluster access."""

from __future__ import annotations

import argparse
import json
import sys
from urllib.parse import unquote, urlparse


REQUIRED_KEYS = (
    "POSTGRES_USER", "POSTGRES_PASSWORD", "REDIS_PASSWORD", "JWT_SECRET",
    "COMMUNITY_SERVICE_TOKEN", "ORDER_SERVICE_TOKEN", "RECOMMENDATION_SERVICE_TOKEN",
    "VTON_SERVICE_TOKEN", "PRODUCT_SERVICE_TOKEN", "REVIEW_SERVICE_TOKEN",
    "RECOMMENDATION_REDIS_URL", "VTON_REDIS_URL", "OPENAI_API_KEY",
)


def validate(values: object) -> dict[str, str]:
    if not isinstance(values, dict) or set(values) != set(REQUIRED_KEYS):
        raise ValueError("Secret must contain exactly the documented application keys")
    for key in REQUIRED_KEYS:
        value = values[key]
        if not isinstance(value, str) or not value.strip() or "CHANGE_ME" in value:
            raise ValueError(f"{key}: a non-placeholder string is required")
        if key == "JWT_SECRET" or key.endswith("_TOKEN"):
            if len(value.encode("utf-8")) < 32:
                raise ValueError(f"{key}: at least 32 UTF-8 bytes are required")
    for key, database in (("RECOMMENDATION_REDIS_URL", "/1"), ("VTON_REDIS_URL", "/0")):
        try:
            url = urlparse(values[key])
            valid = (
                url.scheme == "redis" and url.hostname == "redis" and url.port == 6379
                and url.path == database and not url.username
                and unquote(url.password or "") == values["REDIS_PASSWORD"]
                and not url.query and not url.fragment
            )
        except ValueError:
            valid = False
        if not valid:
            raise ValueError(f"{key}: Redis endpoint, database, or password does not match")
    if len(json.dumps(values, ensure_ascii=True).encode("utf-8")) > 4096:
        raise ValueError("JSON exceeds the 4 KiB SSM Standard parameter limit")
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emit-manifest", action="store_true",
                        help="Write sensitive Secret JSON to stdout for direct kubectl stdin only")
    args = parser.parse_args()
    try:
        values = validate(json.load(sys.stdin))
    except (ValueError, UnicodeError):
        # Parser exceptions can contain input fragments, so never echo their text.
        print("Invalid application Secret; check keys, values, token lengths, Redis URLs and size.",
              file=sys.stderr)
        return 1
    if args.emit_manifest:
        json.dump({"apiVersion": "v1", "kind": "Secret", "type": "Opaque",
                   "metadata": {"name": "fitzza-app-secrets", "namespace": "fitzza"},
                   "stringData": values}, sys.stdout)
    else:
        print("Application Secret validation passed (13 keys; values withheld).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
