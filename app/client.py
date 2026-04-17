from __future__ import annotations

from typing import Any

import httpx


_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/135.0.0.0 Safari/537.36"
)


class RemoteApiError(RuntimeError):
    """Raised when the remote check-in system rejects a request."""


class CheckInClient:
    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        self._origin = base_url.rstrip("/")
        self._base_url = f"{self._origin}/api"
        self._timeout = httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 10.0))

    def login(self, student_no: str, password: str) -> dict[str, Any]:
        payload = self._request(
            "POST",
            "/auth/login",
            json={"student_no": student_no, "password": password},
        )
        if not isinstance(payload, dict) or "token" not in payload:
            raise RemoteApiError("登录成功但未拿到令牌")
        return payload

    def get_today_status(self, token: str) -> dict[str, Any] | None:
        payload = self._request(
            "GET",
            "/attendance/today-status",
            headers=self._auth_headers(token),
        )
        if payload is None:
            return None
        if not isinstance(payload, dict):
            raise RemoteApiError("今日状态返回格式异常")
        return payload

    def submit_checkin(self, token: str, attendance_payload: dict[str, Any]) -> dict[str, Any]:
        payload = self._request(
            "POST",
            "/attendance/check-in",
            headers=self._auth_headers(token),
            json=attendance_payload,
        )
        if not isinstance(payload, dict):
            raise RemoteApiError("打卡返回格式异常")
        return payload

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        with httpx.Client(
            base_url=self._base_url,
            timeout=self._timeout,
            headers=self._default_headers(),
        ) as client:
            try:
                response = client.request(method, path, **kwargs)
                response.raise_for_status()
            except httpx.TimeoutException as exc:
                raise RemoteApiError("请求远程系统超时") from exc
            except httpx.HTTPStatusError as exc:
                raise RemoteApiError(f"远程系统返回 HTTP {exc.response.status_code}") from exc
            except httpx.RequestError as exc:
                raise RemoteApiError("远程系统网络请求失败") from exc
        try:
            body = response.json()
        except ValueError as exc:
            raise RemoteApiError("远程系统返回了无法解析的 JSON") from exc
        if body.get("code") != 200:
            raise RemoteApiError(body.get("message") or "远程系统返回错误")
        return body.get("data")

    def _default_headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Origin": self._origin,
            "Referer": f"{self._origin}/",
            "User-Agent": _BROWSER_USER_AGENT,
        }

    @staticmethod
    def _auth_headers(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}
