import os
import secrets
from dataclasses import dataclass, field

# Load `.env` from the project root before any os.getenv call below.
# python-dotenv was already a dependency; nothing in the codebase
# invoked it until now. Without this, BOOTSTRAP_ADMIN_* etc. set via
# .env never reach the Settings dataclass.
try:
    from dotenv import load_dotenv

    load_dotenv()  # silently no-ops if no .env is present
except ImportError:  # pragma: no cover — dep is always present in production
    pass


def _parse_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:3001")
    return [o.strip() for o in raw.split(",") if o.strip()]


def _jwt_secret() -> str:
    """JWT signing secret.

    Required in production. In dev/test we accept the env var being unset and
    synthesise a per-process random secret so importing the module never fails
    — but tokens won't survive a restart, which is exactly what we want
    locally. See ``app/auth/tokens.py`` for the consumer.
    """
    explicit = os.getenv("JWT_SECRET_KEY")
    if explicit:
        return explicit
    env = os.getenv("ENVIRONMENT", "development").lower()
    if env == "production":
        raise RuntimeError(
            "JWT_SECRET_KEY must be set in production. Generate one with "
            "`python -c 'import secrets; print(secrets.token_urlsafe(48))'`."
        )
    return secrets.token_urlsafe(48)


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    app_name: str = "LawFlow API"
    version: str = "0.1.0"
    description: str = "AI-Powered Indian Legal Intelligence Platform"

    environment: str = field(
        default_factory=lambda: os.getenv("ENVIRONMENT", "development")
    )
    debug: bool = field(
        default_factory=lambda: os.getenv("DEBUG", "false").lower() == "true"
    )
    cors_origins: list[str] = field(default_factory=_parse_origins)

    # ── LLM / vector store (existing) ────────────────────────────────────────
    openai_api_key: str | None = field(
        default_factory=lambda: os.getenv("OPENAI_API_KEY")
    )
    anthropic_api_key: str | None = field(
        default_factory=lambda: os.getenv("ANTHROPIC_API_KEY")
    )
    groq_api_key: str | None = field(
        default_factory=lambda: os.getenv("GROQ_API_KEY")
    )
    groq_model: str = field(
        default_factory=lambda: os.getenv(
            "GROQ_MODEL", "llama-3.3-70b-versatile"
        )
    )
    vector_store_url: str | None = field(
        default_factory=lambda: os.getenv("VECTOR_STORE_URL")
    )

    # ── Auth / persistence ───────────────────────────────────────────────────
    # SQLite path is relative to backend/. Override with DATABASE_URL for
    # Postgres etc. The +aiosqlite driver is required for async sessions.
    database_url: str = field(
        default_factory=lambda: os.getenv(
            "DATABASE_URL", "sqlite+aiosqlite:///./lawflow.db"
        )
    )
    jwt_secret_key: str = field(default_factory=_jwt_secret)
    jwt_algorithm: str = field(
        default_factory=lambda: os.getenv("JWT_ALGORITHM", "HS256")
    )
    access_token_expire_minutes: int = field(
        default_factory=lambda: _int_env("ACCESS_TOKEN_EXPIRE_MINUTES", 30)
    )
    refresh_token_expire_days: int = field(
        default_factory=lambda: _int_env("REFRESH_TOKEN_EXPIRE_DAYS", 14)
    )
    # Cookie flags for the refresh-token cookie. Set COOKIE_SECURE=true behind
    # HTTPS; COOKIE_SAMESITE defaults to "lax" so the cookie still flows on
    # top-level navigations from the SPA but cross-site POSTs are blocked.
    cookie_secure: bool = field(
        default_factory=lambda: _bool_env("COOKIE_SECURE", False)
    )
    cookie_samesite: str = field(
        default_factory=lambda: os.getenv("COOKIE_SAMESITE", "lax").lower()
    )
    cookie_domain: str | None = field(
        default_factory=lambda: os.getenv("COOKIE_DOMAIN") or None
    )
    # Optional bootstrap admin — created on first startup when no admin
    # exists for this email. Lets ops stand up a fresh deployment without
    # running a separate script. See app/auth/bootstrap.py for the
    # idempotency + no-mutation guarantees.
    bootstrap_admin_email: str | None = field(
        default_factory=lambda: os.getenv("BOOTSTRAP_ADMIN_EMAIL") or None
    )
    bootstrap_admin_password: str | None = field(
        default_factory=lambda: os.getenv("BOOTSTRAP_ADMIN_PASSWORD") or None
    )


settings = Settings()
