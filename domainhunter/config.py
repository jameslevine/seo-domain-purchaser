"""Load config.yaml + .env into a single typed settings object."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Credentials:
    edn_username: str
    edn_password: str
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    email_from: str
    email_to: str


@dataclass
class Settings:
    raw: dict
    creds: Credentials

    # Convenience accessors --------------------------------------------------
    @property
    def list_slug(self) -> str:
        return self.raw.get("list_slug", "pendingdelete")

    @property
    def filter(self) -> dict:
        return self.raw.get("filter", {})

    @property
    def scoring(self) -> dict:
        return self.raw.get("scoring", {})

    @property
    def wayback(self) -> dict:
        return self.raw.get("wayback", {})

    @property
    def email(self) -> dict:
        return self.raw.get("email", {})

    @property
    def state(self) -> dict:
        return self.raw.get("state", {})

    def state_db_path(self) -> Path:
        p = Path(self.state.get("db_path", "state/seen_domains.sqlite3"))
        return p if p.is_absolute() else PROJECT_ROOT / p


def _require_env(name: str, default: str | None = None) -> str:
    val = os.environ.get(name, default)
    if val is None:
        raise RuntimeError(
            f"Missing required environment variable {name!r}. "
            f"Copy .env.example to .env and fill it in."
        )
    return val


def load_settings(config_path: str | Path | None = None, *, require_email: bool = True) -> Settings:
    """Load config.yaml and .env. If require_email is False, email creds may be blank
    (useful for --dry-run runs that don't send)."""
    load_dotenv(PROJECT_ROOT / ".env")

    path = Path(config_path) if config_path else PROJECT_ROOT / "config.yaml"
    raw = yaml.safe_load(path.read_text()) or {}

    # Email creds are only strictly required when actually sending.
    email_getter = _require_env if require_email else (lambda n, d="": os.environ.get(n, d))

    creds = Credentials(
        edn_username=_require_env("EDN_USERNAME"),
        edn_password=_require_env("EDN_PASSWORD"),
        smtp_host=os.environ.get("SMTP_HOST", "smtp.gmail.com"),
        smtp_port=int(os.environ.get("SMTP_PORT", "587")),
        smtp_username=email_getter("SMTP_USERNAME", ""),
        smtp_password=email_getter("SMTP_PASSWORD", ""),
        email_from=email_getter("EMAIL_FROM", ""),
        email_to=email_getter("EMAIL_TO", ""),
    )

    # Validate scoring weights sum to 100 so a typo doesn't silently skew rankings.
    weights = raw.get("scoring", {}).get("weights", {})
    if weights:
        total = sum(weights.values())
        if abs(total - 100) > 0.01:
            raise ValueError(f"scoring.weights must sum to 100, got {total}: {weights}")

    return Settings(raw=raw, creds=creds)
