"""Application settings, loaded from environment variables / `.env`."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_prefix="NIDHISEC_",
        extra="ignore",
    )

    app_name: str = "NidhiSec API"
    app_description: str = "AICTE Security Deposit / FDR Management Portal"
    environment: str = "development"
    api_prefix: str = "/api"

    # Relative SQLite paths are resolved against the backend directory so the
    # database location does not depend on the current working directory.
    database_url: str = "sqlite:///./data/nidhisec.db"

    # Stored as a comma-separated string so it can be set from a plain env var.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Signing key for access tokens. There is deliberately no default: set it in
    # `.env` (`python -m app.cli init-env` generates one). In development only, a
    # random per-process key is used when it is missing; see app/core/security.py.
    jwt_secret: SecretStr | None = None
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = Field(default=60, ge=5, le=24 * 60)

    # Private document storage. Relative paths resolve against the backend
    # directory; this must never be inside a publicly served folder.
    document_storage_dir: str = "./storage/documents"
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024)

    # Lifecycle (prototype rules; not official AICTE policy). Dates use Indian Standard Time.
    # Days before maturity at which institutions are reminded (largest first is fine).
    maturity_alert_days: str = "30,15,7"
    # Window at or below which AICTE officials are also alerted.
    aicte_maturity_alert_days: int = Field(default=7, ge=0, le=365)
    # A renewal may be requested this many days before maturity, or any time after it.
    renewal_window_days: int = Field(default=90, ge=0, le=3650)
    # Release requires the FDR to have matured unless this is turned off.
    release_requires_maturity: bool = True
    # Completing a renewal/replacement requires the successor FDR to be ACCEPTED by AICTE.
    lifecycle_require_successor_acceptance: bool = True

    # Failed-login throttling (per email address, in-process).
    login_max_failures: int = Field(default=5, ge=1)
    login_lockout_minutes: int = Field(default=15, ge=1)

    @field_validator("database_url")
    @classmethod
    def resolve_sqlite_path(cls, value: str) -> str:
        prefix = "sqlite:///./"
        if value.startswith(prefix):
            db_path = BACKEND_DIR / value.removeprefix(prefix)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            return f"sqlite:///{db_path.as_posix()}"
        return value

    @field_validator("jwt_secret", mode="before")
    @classmethod
    def blank_secret_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("jwt_secret")
    @classmethod
    def check_secret_strength(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and len(value.get_secret_value()) < 32:
            raise ValueError("NIDHISEC_JWT_SECRET must be at least 32 characters")
        return value

    @property
    def document_storage_path(self) -> Path:
        path = Path(self.document_storage_dir)
        return path if path.is_absolute() else (BACKEND_DIR / path).resolve()

    @property
    def maturity_alert_windows(self) -> list[int]:
        """Alert windows in ascending order, e.g. [7, 15, 30]. Invalid entries are ignored."""
        windows = {int(part) for part in self.maturity_alert_days.split(",") if part.strip().isdigit()}
        return sorted(w for w in windows if 0 <= w <= 3650)

    @property
    def is_development(self) -> bool:
        return self.environment.lower() == "development"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
