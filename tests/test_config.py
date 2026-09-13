from uuid import UUID

import pytest

from ynab_mcp.config import ConfigError, Settings


def test_setup_mode_and_secret_repr() -> None:
    settings = Settings.from_env({"YNAB_PAT": "sentinel-secret"})

    assert settings.plan_id is None
    assert "sentinel-secret" not in repr(settings)


def test_read_only_false_fails() -> None:
    with pytest.raises(ConfigError, match="read-only"):
        Settings.from_env({"YNAB_PAT": "sentinel-secret", "YNAB_READ_ONLY": "false"})


def test_plan_alias_is_rejected() -> None:
    with pytest.raises(ConfigError):
        Settings.from_env({"YNAB_PAT": "sentinel-secret", "YNAB_PLAN_ID": "last-used"})


def test_configured_plan_is_parsed() -> None:
    plan_id = UUID("12345678-1234-5678-1234-567812345678")

    settings = Settings.from_env(
        {
            "YNAB_PAT": "  sentinel-secret  ",
            "YNAB_PLAN_ID": str(plan_id),
        }
    )

    assert settings == Settings(pat="sentinel-secret", plan_id=plan_id)


def test_log_level_is_rejected_instead_of_silently_ignored() -> None:
    with pytest.raises(ConfigError, match="LOG_LEVEL"):
        Settings.from_env({"YNAB_PAT": "sentinel-secret", "LOG_LEVEL": "DEBUG"})


def test_missing_or_blank_pat_fails() -> None:
    with pytest.raises(ConfigError, match="YNAB_PAT"):
        Settings.from_env({})
    with pytest.raises(ConfigError, match="YNAB_PAT"):
        Settings.from_env({"YNAB_PAT": "  "})


def test_malformed_plan_id_fails() -> None:
    with pytest.raises(ConfigError, match="YNAB_PLAN_ID"):
        Settings.from_env({"YNAB_PAT": "sentinel-secret", "YNAB_PLAN_ID": "invalid"})


def test_settings_are_immutable() -> None:
    settings = Settings.from_env({"YNAB_PAT": "sentinel-secret"})

    with pytest.raises((AttributeError, TypeError)):
        settings.pat = "other-secret"  # type: ignore[misc]
