"""Prepare app credentials offline; stdout contains secrets only with --emit-json."""

from __future__ import annotations

import argparse
import getpass
import json
import secrets
import sys
from urllib.parse import quote

try:
    from scripts.validate_app_secrets import validate
except ModuleNotFoundError:
    from validate_app_secrets import validate


def prepare(username: str, password: str, openai_api_key: str) -> dict[str, str]:
    if not username or not username.strip():
        raise ValueError("A database username is required")
    # PostgreSQL RDS master passwords: 8–128 printable ASCII characters,
    # excluding '/', double quote, '@', and space.
    if not 8 <= len(password) <= 128 or any(
        ord(char) < 33 or ord(char) > 126 or char in '/"@' for char in password
    ):
        raise ValueError("Invalid RDS PostgreSQL password")
    if not openai_api_key or not openai_api_key.strip():
        raise ValueError("An OpenAI API key is required")
    values = {"POSTGRES_USER": username, "POSTGRES_PASSWORD": password,
              "OPENAI_API_KEY": openai_api_key,
              "REDIS_PASSWORD": secrets.token_urlsafe(32), "JWT_SECRET": secrets.token_urlsafe(48)}
    for service in ("COMMUNITY", "ORDER", "RECOMMENDATION", "VTON", "PRODUCT", "REVIEW"):
        values[f"{service}_SERVICE_TOKEN"] = secrets.token_urlsafe(32)
    redis_password = quote(values["REDIS_PASSWORD"], safe="")
    values["RECOMMENDATION_REDIS_URL"] = f"redis://:{redis_password}@redis:6379/1"
    values["VTON_REDIS_URL"] = f"redis://:{redis_password}@redis:6379/0"
    return validate(values)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", default="fitzza_admin")
    parser.add_argument("--emit-json", action="store_true",
                        help="Emit sensitive JSON for a protected stdin consumer; never log it")
    args = parser.parse_args()
    if not sys.stdin.isatty():
        print("Use an interactive terminal for hidden password input.", file=sys.stderr)
        return 1
    try:
        password = getpass.getpass("RDS password (must match the pinned SSM password version): ")
        confirmation = getpass.getpass("Confirm RDS password: ")
        if password != confirmation:
            raise ValueError("Password confirmation mismatch")
        openai_api_key = getpass.getpass("OpenAI API key: ")
        values = prepare(args.username, password, openai_api_key)
    except (ValueError, EOFError, KeyboardInterrupt):
        print("Credential preparation failed; no values emitted.", file=sys.stderr)
        return 1
    if args.emit_json:
        json.dump(values, sys.stdout, ensure_ascii=True)
    else:
        print("Credential contract validated; no values emitted or saved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
