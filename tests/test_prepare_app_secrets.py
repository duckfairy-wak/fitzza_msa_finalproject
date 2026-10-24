import json

import pytest

from scripts.prepare_app_secrets import prepare
from scripts.validate_app_secrets import validate


def test_generated_credentials_match_contract_and_are_independent():
    first = prepare("fitzza_admin", "Test-only-password-2026!", "test-openai-key")
    second = prepare("fitzza_admin", "Test-only-password-2026!", "test-openai-key")
    assert validate(first) == first
    assert first["POSTGRES_PASSWORD"] == second["POSTGRES_PASSWORD"]
    generated = [key for key in first if key.endswith("_TOKEN") or key in {"JWT_SECRET", "REDIS_PASSWORD"}]
    assert len({first[key] for key in generated}) == len(generated)
    assert all(first[key] != second[key] for key in generated)
    assert len(json.dumps(first).encode()) <= 4096


@pytest.mark.parametrize("password", ["short", "a" * 129, "with spaces 123", 'with"quote123',
                                      "with/slash123", "with@sign123", "nonascii암호123", "newline123\n"])
def test_invalid_rds_password_rejected(password):
    with pytest.raises(ValueError):
        prepare("fitzza_admin", password, "test-openai-key")


def test_missing_openai_api_key_rejected():
    with pytest.raises(ValueError, match="OpenAI API key"):
        prepare("fitzza_admin", "Test-only-password-2026!", "")
