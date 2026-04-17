from __future__ import annotations

import unittest
from typing import Any

import app.client as client_module


class FakeResponse:
    def __init__(self, body: Any, status_code: int = 200) -> None:
        self._body = body
        self.status_code = status_code

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._body


class RecordingClient:
    last_instance: "RecordingClient | None" = None
    response_body: Any = {"code": 200, "data": {"token": "token-123"}}

    def __init__(self, *, base_url: str, timeout: Any, headers: dict[str, str]) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self.headers = headers
        self.requests: list[tuple[str, str, dict[str, Any]]] = []
        RecordingClient.last_instance = self

    def __enter__(self) -> "RecordingClient":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        return False

    def request(self, method: str, path: str, **kwargs: Any) -> FakeResponse:
        self.requests.append((method, path, kwargs))
        return FakeResponse(self.response_body)


class CheckInClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_client = client_module.httpx.Client
        client_module.httpx.Client = RecordingClient

    def tearDown(self) -> None:
        client_module.httpx.Client = self.original_client
        RecordingClient.last_instance = None
        RecordingClient.response_body = {"code": 200, "data": {"token": "token-123"}}

    def test_login_uses_browser_like_headers(self) -> None:
        client = client_module.CheckInClient("http://attendance.example.com", 20.0)

        login_data = client.login("202200460046", "secret-password")

        self.assertEqual(login_data, {"token": "token-123"})
        recorded = RecordingClient.last_instance
        self.assertIsNotNone(recorded)
        assert recorded is not None
        self.assertEqual(recorded.base_url, "http://attendance.example.com/api")
        self.assertEqual(
            recorded.headers,
            {
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Origin": "http://attendance.example.com",
                "Referer": "http://attendance.example.com/",
                "User-Agent": client_module._BROWSER_USER_AGENT,
            },
        )
        self.assertEqual(
            recorded.requests,
            [
                (
                    "POST",
                    "/auth/login",
                    {"json": {"student_no": "202200460046", "password": "secret-password"}},
                )
            ],
        )

    def test_submit_checkin_preserves_fingerprint_payload_and_bearer_token(self) -> None:
        RecordingClient.response_body = {"code": 200, "data": {"status": "在校"}}
        client = client_module.CheckInClient("http://attendance.example.com", 20.0)
        payload = {
            "status": "在校",
            "_fp": {
                "page_stay_ms": 4862,
                "mouse_points": [{"x": 744, "y": 178, "t": 1776411793860}],
            },
        }

        result = client.submit_checkin("token-456", payload)

        self.assertEqual(result, {"status": "在校"})
        recorded = RecordingClient.last_instance
        self.assertIsNotNone(recorded)
        assert recorded is not None
        method, path, kwargs = recorded.requests[0]
        self.assertEqual(method, "POST")
        self.assertEqual(path, "/attendance/check-in")
        self.assertEqual(kwargs["json"], payload)
        self.assertEqual(kwargs["headers"], {"Authorization": "Bearer token-456"})


if __name__ == "__main__":
    unittest.main()
