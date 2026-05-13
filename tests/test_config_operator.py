from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from vidi_pr.config.defaults import Strictness
from vidi_pr.config.operator import OperatorConfig, OperatorConfigError

_MINIMAL_YAML = """
github:
  app_id: 123456
  private_key_path: /etc/vidi-pr/private-key.pem

llm:
  provider: openai_compat
  base_url: http://ai01.lan:8080/v1
  model: qwen2.5-coder-32b

storage:
  db_path: /var/lib/vidi-pr/vidi-pr.db
"""


@pytest.fixture(autouse=True)
def _required_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIDI_PR_WEBHOOK_SECRET", "test-secret")
    monkeypatch.delenv("VIDI_PR_LLM_API_KEY", raising=False)
    monkeypatch.delenv("VIDI_PR_CONFIG", raising=False)


def _write(tmp_path: Path, yaml_text: str) -> Path:
    path = tmp_path / "config.yml"
    path.write_text(yaml_text)
    return path


def test_minimal_yaml_loads_with_defaults(tmp_path: Path) -> None:
    config = OperatorConfig.load(_write(tmp_path, _MINIMAL_YAML))

    assert config.github.app_id == 123456
    assert config.llm.provider == "openai_compat"
    assert config.llm.temperature == 0.2
    assert config.pipeline.max_files == 50
    assert config.defaults.strictness is Strictness.NORMAL
    assert config.server.host == "127.0.0.1"
    assert config.webhook_secret.get_secret_value() == "test-secret"
    assert config.llm_api_key is None


def test_missing_required_field_raises_validation_error(tmp_path: Path) -> None:
    yaml_text = _MINIMAL_YAML.replace("app_id: 123456\n", "")
    path = _write(tmp_path, yaml_text)

    with pytest.raises(ValidationError):
        OperatorConfig.load(path)


def test_missing_webhook_secret_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VIDI_PR_WEBHOOK_SECRET", raising=False)

    with pytest.raises(ValidationError):
        OperatorConfig.load(_write(tmp_path, _MINIMAL_YAML))


def test_llm_api_key_from_env_is_picked_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIDI_PR_LLM_API_KEY", "abc123")
    config = OperatorConfig.load(_write(tmp_path, _MINIMAL_YAML))

    assert config.llm_api_key is not None
    assert config.llm_api_key.get_secret_value() == "abc123"


def test_nested_env_override_wins_over_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VIDI_PR_LLM__MODEL", "override-model")
    config = OperatorConfig.load(_write(tmp_path, _MINIMAL_YAML))

    assert config.llm.model == "override-model"


def test_invalid_yaml_raises_operator_config_error(tmp_path: Path) -> None:
    path = tmp_path / "config.yml"
    path.write_text("github:\n  app_id: [unterminated\n")

    with pytest.raises(OperatorConfigError):
        OperatorConfig.load(path)


def test_yaml_must_be_a_mapping(tmp_path: Path) -> None:
    path = tmp_path / "config.yml"
    path.write_text("- just a list\n")

    with pytest.raises(OperatorConfigError):
        OperatorConfig.load(path)


def test_forwarded_allow_ips_parses_cidr(tmp_path: Path) -> None:
    yaml_text = (
        _MINIMAL_YAML
        + """
server:
  forwarded_allow_ips:
    - 172.18.0.0/16
    - 10.0.0.0/8
"""
    )
    config = OperatorConfig.load(_write(tmp_path, yaml_text))

    assert len(config.server.forwarded_allow_ips) == 2
    assert str(config.server.forwarded_allow_ips[0]) == "172.18.0.0/16"


def test_forwarded_allow_ips_rejects_malformed(tmp_path: Path) -> None:
    yaml_text = (
        _MINIMAL_YAML
        + """
server:
  forwarded_allow_ips:
    - "not a cidr"
"""
    )
    with pytest.raises(ValidationError):
        OperatorConfig.load(_write(tmp_path, yaml_text))


def test_load_respects_vidi_pr_config_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _write(tmp_path, _MINIMAL_YAML)
    monkeypatch.setenv("VIDI_PR_CONFIG", str(path))

    config = OperatorConfig.load()
    assert config.github.app_id == 123456


def test_unreadable_path_raises_operator_config_error(tmp_path: Path) -> None:
    missing = tmp_path / "nope.yml"

    with pytest.raises(OperatorConfigError):
        OperatorConfig.load(missing)
