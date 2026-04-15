from __future__ import annotations

import base64
import hashlib
import hmac
import time
from dataclasses import dataclass, field
from threading import Lock


ADMIN_PASSWORD_SALT = b"sdu-checkin-admin"


def hash_admin_password(password: str) -> str:
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        ADMIN_PASSWORD_SALT,
        200_000,
    )
    return base64.urlsafe_b64encode(digest).decode("ascii")


def derive_session_secret(key_material: bytes, password_hash: str) -> bytes:
    return hashlib.sha256(key_material + password_hash.encode("utf-8")).digest()


def normalize_admin_password_hash(raw_hash: str) -> str:
    clean_hash = raw_hash.strip()
    if not clean_hash:
        raise ValueError("CHECKIN_ADMIN_PASSWORD_HASH 不能为空")
    try:
        decoded = base64.urlsafe_b64decode(clean_hash.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise ValueError("CHECKIN_ADMIN_PASSWORD_HASH 格式无效") from exc
    if len(decoded) != 32:
        raise ValueError("CHECKIN_ADMIN_PASSWORD_HASH 长度无效")
    return clean_hash


class LoginThrottledError(RuntimeError):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("登录尝试过于频繁")
        self.retry_after_seconds = retry_after_seconds


@dataclass(slots=True)
class LoginRateLimiter:
    max_attempts: int
    window_seconds: int
    block_seconds: int
    _attempts: dict[str, list[int]] = field(default_factory=dict)
    _blocked_until: dict[str, int] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def ensure_allowed(self, client_id: str, now: int | None = None) -> None:
        current_time = int(time.time()) if now is None else now
        with self._lock:
            blocked_until = self._blocked_until.get(client_id, 0)
            if blocked_until > current_time:
                raise LoginThrottledError(blocked_until - current_time)
            if blocked_until:
                self._blocked_until.pop(client_id, None)
            self._attempts[client_id] = self._recent_attempts(client_id, current_time)

    def record_failure(self, client_id: str, now: int | None = None) -> None:
        current_time = int(time.time()) if now is None else now
        with self._lock:
            attempts = self._recent_attempts(client_id, current_time)
            attempts.append(current_time)
            if len(attempts) >= self.max_attempts:
                self._blocked_until[client_id] = current_time + self.block_seconds
                self._attempts.pop(client_id, None)
                return
            self._attempts[client_id] = attempts

    def record_success(self, client_id: str) -> None:
        with self._lock:
            self._attempts.pop(client_id, None)
            self._blocked_until.pop(client_id, None)

    def _recent_attempts(self, client_id: str, current_time: int) -> list[int]:
        threshold = current_time - self.window_seconds
        return [ts for ts in self._attempts.get(client_id, []) if ts > threshold]


@dataclass(slots=True)
class AuthManager:
    password_hash: str
    session_secret: bytes
    ttl_seconds: int

    def verify_password(self, password: str) -> bool:
        candidate_hash = hash_admin_password(password.strip())
        return hmac.compare_digest(candidate_hash, self.password_hash)

    def create_session_value(self, issued_at: int | None = None) -> str:
        now = int(time.time()) if issued_at is None else issued_at
        expires_at = now + self.ttl_seconds
        signature = self._sign(expires_at)
        return f"{expires_at}.{signature}"

    def is_session_valid(self, session_value: str | None, now: int | None = None) -> bool:
        if not session_value:
            return False
        parts = session_value.split(".", 1)
        if len(parts) != 2 or not parts[0].isdigit():
            return False
        expires_at = int(parts[0])
        current_time = int(time.time()) if now is None else now
        if expires_at <= current_time:
            return False
        return hmac.compare_digest(parts[1], self._sign(expires_at))

    def _sign(self, expires_at: int) -> str:
        return hmac.new(
            self.session_secret,
            str(expires_at).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
