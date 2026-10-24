import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

import pytest

from scripts.validate_app_secrets import REQUIRED_KEYS, validate


def valid_values():
    values = dict.fromkeys(REQUIRED_KEYS, "test-only-token-" * 3)
    values["POSTGRES_USER"] = "fitzza_admin"
    values["REDIS_PASSWORD"] = "test-only:p@ss/word"
    password = quote(values["REDIS_PASSWORD"], safe="")
    values["RECOMMENDATION_REDIS_URL"] = f"redis://:{password}@redis:6379/1"
    values["VTON_REDIS_URL"] = f"redis://:{password}@redis:6379/0"
    return values


def test_valid_secret_matches_documented_keys():
    values = valid_values()
    example = Path("infra/k8s/base/secret.example.yaml").read_text()
    documented = {
        line.strip().split(":", 1)[0]
        for line in example.split("stringData:\n", 1)[1].splitlines()
        if line.startswith("  ") and not line.strip().startswith("#")
    }
    assert set(REQUIRED_KEYS) == documented
    assert validate(values) == values


@pytest.mark.parametrize("key,value", [
    ("POSTGRES_PASSWORD", "CHANGE_ME"),
    ("OPENAI_API_KEY", ""),
    ("JWT_SECRET", "short"),
    ("ORDER_SERVICE_TOKEN", None),
    ("POSTGRES_PASSWORD", "x" * 4096),
    ("VTON_REDIS_URL", "redis://:wrong@redis:6379/0"),
    ("VTON_REDIS_URL", "redis://:password@public.example.com:6379/0"),
    ("RECOMMENDATION_REDIS_URL", "redis://:password@redis:invalid/1"),
])
def test_invalid_values_rejected(key, value):
    values = valid_values()
    values[key] = value
    with pytest.raises(ValueError):
        validate(values)


def test_missing_key_rejected():
    values = valid_values()
    del values["POSTGRES_PASSWORD"]
    with pytest.raises(ValueError):
        validate(values)


def test_escaped_unicode_output_over_limit_is_rejected():
    values = valid_values()
    values["JWT_SECRET"] = "한" * 700
    assert len(json.dumps(values, ensure_ascii=False).encode("utf-8")) < 4096
    assert len(json.dumps(values, ensure_ascii=True).encode("utf-8")) > 4096
    with pytest.raises(ValueError, match="4 KiB"):
        validate(values)


@pytest.mark.parametrize("size", [4096, 4097])
def test_actual_json_output_size_boundary(size):
    values = valid_values()
    values["JWT_SECRET"] = ""
    overhead = len(json.dumps(values, ensure_ascii=True).encode("utf-8"))
    values["JWT_SECRET"] = "x" * (size - overhead)
    assert len(json.dumps(values, ensure_ascii=True).encode("utf-8")) == size
    if size == 4096:
        assert validate(values) == values
    else:
        with pytest.raises(ValueError, match="4 KiB"):
            validate(values)


@pytest.mark.parametrize("payload,success", [(json.dumps(valid_values()), True),
                                            ('{"secret":"do-not-print-this"', False)])
def test_cli_does_not_echo_secrets(payload, success):
    result = subprocess.run([sys.executable, "scripts/validate_app_secrets.py"],
                            input=payload, capture_output=True, text=True)
    assert (result.returncode == 0) == success
    assert "test-only" not in result.stdout + result.stderr
    assert "do-not-print-this" not in result.stdout + result.stderr


def test_emit_manifest_matches_expected_secret():
    values = valid_values()
    result = subprocess.run(
        [sys.executable, "scripts/validate_app_secrets.py", "--emit-manifest"],
        input=json.dumps(values), capture_output=True, text=True, check=True,
    )
    manifest = json.loads(result.stdout)
    assert manifest["metadata"] == {"name": "fitzza-app-secrets", "namespace": "fitzza"}
    assert manifest["stringData"] == values
