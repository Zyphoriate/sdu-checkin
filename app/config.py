from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .auth import normalize_admin_password_hash


def _root_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def _int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return int(raw_value)


def _float_env(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return float(raw_value)


def _bool_env(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} 必须是 true/false")


def _required_env(name: str) -> str:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        raise RuntimeError(f"{name} 未设置，服务拒绝启动")
    return raw_value.strip()


@dataclass(frozen=True)
class Settings:
    base_url: str
    data_dir: Path
    database_path: Path
    encryption_key_path: Path
    encryption_key: str | None
    admin_password_hash: str
    auth_cookie_name: str
    auth_session_ttl_seconds: int
    auth_cookie_secure: bool
    login_limit_max_attempts: int
    login_limit_window_seconds: int
    login_limit_block_seconds: int
    service_timezone: str
    scheduler_interval_seconds: int
    scheduler_retry_limit: int
    request_timeout_seconds: float


def load_settings() -> Settings:
    local_data_dir = _root_dir() / "data"
    data_dir = Path(os.getenv("CHECKIN_DATA_DIR", local_data_dir))
    return Settings(
        base_url=_required_env("CHECKIN_BASE_URL").rstrip("/"),
        data_dir=data_dir,
        database_path=data_dir / "checkin.db",
        encryption_key_path=data_dir / "fernet.key",
        encryption_key=os.getenv("CHECKIN_ENCRYPTION_KEY"),
        admin_password_hash=normalize_admin_password_hash(
            _required_env("CHECKIN_ADMIN_PASSWORD_HASH"),
        ),
        auth_cookie_name=os.getenv("CHECKIN_AUTH_COOKIE_NAME", "checkin_admin_session"),
        auth_session_ttl_seconds=_int_env("CHECKIN_AUTH_SESSION_TTL_SECONDS", 604800),
        auth_cookie_secure=_bool_env("CHECKIN_AUTH_COOKIE_SECURE", False),
        login_limit_max_attempts=_int_env("CHECKIN_LOGIN_LIMIT_MAX_ATTEMPTS", 5),
        login_limit_window_seconds=_int_env("CHECKIN_LOGIN_LIMIT_WINDOW_SECONDS", 300),
        login_limit_block_seconds=_int_env("CHECKIN_LOGIN_LIMIT_BLOCK_SECONDS", 900),
        service_timezone=os.getenv("CHECKIN_SERVICE_TIMEZONE", "Asia/Shanghai"),
        scheduler_interval_seconds=_int_env("CHECKIN_SCHEDULER_INTERVAL_SECONDS", 60),
        scheduler_retry_limit=_int_env("CHECKIN_SCHEDULER_RETRY_LIMIT", 3),
        request_timeout_seconds=_float_env("CHECKIN_REQUEST_TIMEOUT_SECONDS", 20.0),
    )


settings = load_settings()
