from __future__ import annotations

import os
import unittest
from types import SimpleNamespace

from fastapi import HTTPException
from fastapi.responses import Response

import app.auth as auth_module
os.environ.setdefault("CHECKIN_ADMIN_PASSWORD_HASH", auth_module.hash_admin_password("test-admin-password"))
os.environ.setdefault("CHECKIN_BASE_URL", "https://attendance.example.com")
import app.main as main_module
from app.models import LoginRequest


class MainAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        auth_manager = auth_module.AuthManager(
            password_hash=auth_module.hash_admin_password("test-admin-password"),
            session_secret=b"test-session-secret",
            ttl_seconds=3600,
        )
        login_rate_limiter = auth_module.LoginRateLimiter(
            max_attempts=2,
            window_seconds=300,
            block_seconds=600,
        )
        repository = SimpleNamespace(count_users=lambda: 2)
        main_module.app.state.auth_manager = auth_manager
        main_module.app.state.login_rate_limiter = login_rate_limiter
        main_module.app.state.repository = repository
        self.request_without_session = SimpleNamespace(
            app=main_module.app,
            cookies={},
            client=SimpleNamespace(host="127.0.0.1"),
        )
        self.cookie_name = main_module.settings.auth_cookie_name

    def test_health_requires_login(self) -> None:
        with self.assertRaises(HTTPException) as context:
            main_module.health(self.request_without_session)

        self.assertEqual(context.exception.status_code, 401)
        self.assertEqual(context.exception.detail, "请先输入管理密码")

    def test_login_and_logout_control_session(self) -> None:
        with self.assertRaises(HTTPException) as context:
            main_module.login(
                LoginRequest(password="wrong"),
                self.request_without_session,
                Response(),
            )
        self.assertEqual(context.exception.status_code, 401)

        response = Response()
        login_result = main_module.login(
            LoginRequest(password="test-admin-password"),
            self.request_without_session,
            response,
        )
        self.assertEqual(login_result.authenticated, True)
        session_cookie = self._extract_cookie_value(response)

        request_with_session = SimpleNamespace(
            app=self.request_without_session.app,
            cookies={self.cookie_name: session_cookie},
        )
        health = main_module.health(request_with_session)
        self.assertEqual(health.status, "ok")
        self.assertEqual(health.user_count, 2)

        logout_response = Response()
        logout_result = main_module.logout(logout_response)
        self.assertEqual(logout_result.authenticated, False)
        self.assertIn(f"{self.cookie_name}=\"\"", logout_response.headers["set-cookie"])

    def test_login_rate_limit_blocks_repeated_failures(self) -> None:
        for _ in range(2):
            with self.assertRaises(HTTPException) as context:
                main_module.login(
                    LoginRequest(password="wrong"),
                    self.request_without_session,
                    Response(),
                )
            self.assertEqual(context.exception.status_code, 401)

        with self.assertRaises(HTTPException) as context:
            main_module.login(
                LoginRequest(password="test-admin-password"),
                self.request_without_session,
                Response(),
            )
        self.assertEqual(context.exception.status_code, 429)

    def _extract_cookie_value(self, response: Response) -> str:
        cookie_header = response.headers["set-cookie"]
        for fragment in cookie_header.split(";"):
            if fragment.startswith(f"{self.cookie_name}="):
                return fragment.split("=", 1)[1]
        raise AssertionError("session cookie not found")


if __name__ == "__main__":
    unittest.main()
