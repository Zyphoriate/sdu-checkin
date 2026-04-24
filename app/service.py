from __future__ import annotations

import hashlib
import random
import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .client import CheckInClient
from .crypto import SecretBox
from .db import Repository
from .models import RunRecord, UserRecord


_FINGERPRINT_PAGE_STAY_MS = 4862
_SCHEDULE_RANDOM_WINDOW_MINUTES = 20
_FINGERPRINT_MOUSE_POINTS_TEMPLATE: tuple[tuple[int, int, int], ...] = (
    (744, 178, 0),
    (743, 179, 150),
    (743, 179, 305),
    (743, 179, 455),
    (743, 182, 605),
    (743, 182, 755),
    (743, 182, 906),
    (709, 197, 1056),
    (513, 246, 1206),
    (484, 247, 1377),
    (481, 254, 1539),
    (465, 314, 1689),
    (465, 315, 1840),
    (465, 315, 1991),
    (465, 315, 2141),
    (465, 315, 2291),
    (465, 315, 2442),
    (465, 315, 2591),
    (465, 315, 2742),
    (465, 315, 2892),
    (465, 315, 3042),
    (465, 315, 3193),
    (465, 315, 3343),
    (465, 315, 3494),
    (487, 369, 3644),
    (502, 427, 3795),
    (506, 458, 3944),
    (510, 466, 4095),
    (510, 466, 4246),
    (510, 466, 4396),
)
_FINGERPRINT_STATIC_FIELDS: dict[str, Any] = {
    "click_offset_x": -8.4,
    "click_offset_y": 1.2,
    "screen_resolution": "1536x864",
    "timezone_offset": -480,
    "browser_lang": "zh-CN",
    "touch_points": 0,
    "has_mouse": 1,
    "canvas_hash": "a1b2c3d4",
    "webgl_renderer": "ANGLE (Intel, Intel(R) UHD Graphics 630, OpenGL 4.6)",
    "platform": "Win32",
    "device_memory": "8",
    "cpu_cores": "8",
    "color_depth": "24",
    "pixel_ratio": "1.25",
    "audio_hash": "35.7f1e8a2c",
    "math_hash": "4b6d2a1e",
    "webdriver": "0",
}


class CheckInService:
    def __init__(
        self,
        repository: Repository,
        secret_box: SecretBox,
        client: CheckInClient,
        service_timezone: str,
        scheduler_retry_limit: int,
    ) -> None:
        self._repository = repository
        self._secret_box = secret_box
        self._client = client
        self._timezone = ZoneInfo(service_timezone)
        self._scheduler_retry_limit = scheduler_retry_limit

    @property
    def service_timezone(self) -> str:
        return str(self._timezone)

    def run_due_users(self, now: datetime | None = None) -> list[RunRecord]:
        current_time = self._now(now)
        run_date = current_time.date().isoformat()
        due_users: list[UserRecord] = []
        for user in self._repository.list_users():
            if not user.enabled:
                continue
            if current_time < self._scheduled_time_for_day(user, current_time):
                continue
            attempt_count, has_terminal = self._repository.get_scheduler_attempt_summary(
                user.id,
                run_date,
            )
            if has_terminal or attempt_count >= self._scheduler_retry_limit:
                continue
            due_users.append(user)
        return [self._execute_checkin(user, "scheduler", current_time) for user in due_users]

    def run_user_now(self, user_id: int, now: datetime | None = None) -> RunRecord:
        user = self._repository.get_user(user_id)
        if user is None:
            raise LookupError("用户不存在")
        return self._execute_checkin(user, "manual", self._now(now))

    def build_payload(self, user: UserRecord, now: datetime | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": user.desired_status,
            "_fp": self._build_fingerprint(self._now(now)),
        }
        if user.desired_status == "不在校":
            payload["off_campus_city"] = user.off_campus_city
            payload["off_campus_district"] = user.off_campus_district
            payload["off_campus_reason"] = user.off_campus_reason
        return payload

    def _execute_checkin(self, user: UserRecord, triggered_by: str, now: datetime) -> RunRecord:
        run_date = now.date().isoformat()
        desired_payload = self.build_payload(user, now)
        created_at = now.isoformat()
        try:
            password = self._secret_box.decrypt(user.password_ciphertext)
            login_data = self._client.login(user.student_no, password)
            token = str(login_data["token"])
            today_status = self._client.get_today_status(token)
            if today_status is not None:
                if self._matches_desired(today_status, desired_payload):
                    return self._repository.create_run(
                        user_id=user.id,
                        run_date=run_date,
                        triggered_by=triggered_by,
                        outcome="skipped",
                        message="今日已是目标状态，无需重复提交",
                        desired_payload=desired_payload,
                        remote_snapshot=today_status,
                        created_at=created_at,
                    )
                if not user.overwrite_existing:
                    return self._repository.create_run(
                        user_id=user.id,
                        run_date=run_date,
                        triggered_by=triggered_by,
                        outcome="skipped",
                        message="今日已有打卡记录，当前配置不覆盖已有记录",
                        desired_payload=desired_payload,
                        remote_snapshot=today_status,
                        created_at=created_at,
                    )
            nonce = self._client.slider_challenge(token)
            trajectories = self._generate_slider_trajectories()
            self._client.slider_verify(token, trajectories, nonce)
            result = self._client.submit_checkin(token, desired_payload)
            return self._repository.create_run(
                user_id=user.id,
                run_date=run_date,
                triggered_by=triggered_by,
                outcome="success",
                message="打卡提交成功",
                desired_payload=desired_payload,
                remote_snapshot=result,
                created_at=created_at,
            )
        except Exception as exc:
            return self._repository.create_run(
                user_id=user.id,
                run_date=run_date,
                triggered_by=triggered_by,
                outcome="failed",
                message=str(exc),
                desired_payload=desired_payload,
                remote_snapshot={},
                created_at=created_at,
            )

    def _now(self, now: datetime | None) -> datetime:
        if now is not None:
            return now.astimezone(self._timezone)
        return datetime.now(self._timezone)

    @staticmethod
    def _matches_desired(existing_status: dict[str, Any], desired_payload: dict[str, Any]) -> bool:
        if existing_status.get("status") != desired_payload.get("status"):
            return False
        if desired_payload["status"] != "不在校":
            return True
        return (
            (existing_status.get("off_campus_city") or "").strip()
            == (desired_payload.get("off_campus_city") or "").strip()
            and (existing_status.get("off_campus_district") or "").strip()
            == (desired_payload.get("off_campus_district") or "").strip()
            and (existing_status.get("off_campus_reason") or "").strip()
            == (desired_payload.get("off_campus_reason") or "").strip()
        )

    def _build_fingerprint(self, now: datetime) -> dict[str, Any]:
        submit_time_ms = int(now.timestamp() * 1000)
        page_start_ms = submit_time_ms - _FINGERPRINT_PAGE_STAY_MS
        mouse_points = [
            {
                "x": x,
                "y": y,
                "t": page_start_ms + offset_ms,
            }
            for x, y, offset_ms in _FINGERPRINT_MOUSE_POINTS_TEMPLATE
        ]
        return {
            "page_stay_ms": _FINGERPRINT_PAGE_STAY_MS,
            "mouse_points": mouse_points,
            **_FINGERPRINT_STATIC_FIELDS,
        }

    def _scheduled_time_for_day(self, user: UserRecord, current_time: datetime) -> datetime:
        hour_text, minute_text = user.schedule_time.split(":")
        scheduled_time = current_time.replace(
            hour=int(hour_text),
            minute=int(minute_text),
            second=0,
            microsecond=0,
        )
        base_minutes = int(hour_text) * 60 + int(minute_text)
        max_offset = min(_SCHEDULE_RANDOM_WINDOW_MINUTES, (23 * 60 + 59) - base_minutes)
        offset_minutes = self._daily_schedule_offset_minutes(user, scheduled_time.date().isoformat(), max_offset)
        return scheduled_time + timedelta(minutes=offset_minutes)

    @staticmethod
    def _generate_slider_trajectories() -> list[dict[str, int]]:
        rng = random.Random(time.monotonic_ns())
        target = rng.randint(87, 96)
        now_ms = int(time.time() * 1000)
        points: list[dict[str, int]] = [{"x": 0, "t": now_ms}]
        x = 0
        t = 0
        while x < target:
            remaining = target - x
            step = max(1, min(remaining, rng.randint(2, 8)))
            if remaining <= 5:
                step = remaining
            x += step
            t += rng.randint(25, 70)
            points.append({"x": x, "t": now_ms + t})
        points.append({"x": target, "t": now_ms + t + rng.randint(30, 80)})
        return points

    @staticmethod
    def _daily_schedule_offset_minutes(user: UserRecord, run_date: str, max_offset: int) -> int:
        seed = f"{user.student_no}:{run_date}".encode("utf-8")
        digest = hashlib.sha256(seed).digest()
        return int.from_bytes(digest[:4], "big") % (max_offset + 1)
