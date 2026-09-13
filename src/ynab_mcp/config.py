from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID


class ConfigError(ValueError):
    """Raised when startup configuration is invalid."""


@dataclass(frozen=True, repr=False)
class Settings:
    pat: str
    plan_id: UUID | None

    def __repr__(self) -> str:
        return f"Settings(pat=<redacted>, plan_id={self.plan_id})"

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "Settings":
        pat = env.get("YNAB_PAT", "").strip()
        if not pat:
            raise ConfigError("YNAB_PAT is required")
        if env.get("YNAB_READ_ONLY", "true").lower() != "true":
            raise ConfigError("Phase 1 is read-only")
        if "LOG_LEVEL" in env:
            raise ConfigError("LOG_LEVEL is not supported; logging remains WARNING")
        raw_id = env.get("YNAB_PLAN_ID", "").strip()
        try:
            plan_id = UUID(raw_id) if raw_id else None
        except ValueError:
            raise ConfigError("YNAB_PLAN_ID must be a UUID") from None
        return cls(pat=pat, plan_id=plan_id)
