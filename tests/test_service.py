from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.models import RunRecord, UserRecord
from app.service import CheckInService


class FakeRepository:
    def __init__(self, users: list[UserRecord]) -> None:
        self.users = {user.id: user for user in users}
        self.scheduler_attempts: dict[tuple[int, str], tuple[int, bool]] = {}
        self.created_runs: list[RunRecord] = []

    def list_users(self) -> list[UserRecord]:
        return list(self.users.values())

    def get_user(self, user_id: int) -> UserRecord | None:
        return self.users.get(user_id)

    def get_scheduler_attempt_summary(self, user_id: int, run_date: str) -> tuple[int, bool]:
        return self.scheduler_attempts.get((user_id, run_date), (0, False))

    def create_run(
        self,
        user_id: int,
        run_date: str,
        triggered_by: str,
        outcome: str,
        message: str,
        desired_payload: dict,
        remote_snapshot: dict,
        created_at: str,
    ) -> RunRecord:
        user = self.users[user_id]
        run = RunRecord(
            id=len(self.created_runs) + 1,
            user_id=user_id,
            user_label=user.label,
            student_no=user.student_no,
            run_date=run_date,
            triggered_by=triggered_by,
            outcome=outcome,
            message=message,
            desired_payload=desired_payload,
            remote_snapshot=remote_snapshot,
            created_at=created_at,
        )
        self.created_runs.append(run)
        return run


class FakeSecretBox:
    def decrypt(self, ciphertext: str) -> str:
        return ciphertext


class FakeClient:
    def __init__(self) -> None:
        self.today_status = None
        self.submitted_payloads: list[dict] = []

    def login(self, student_no: str, password: str) -> dict:
        return {"token": f"token-for-{student_no}"}

    def get_today_status(self, token: str):
        return self.today_status

    def submit_checkin(self, token: str, attendance_payload: dict):
        self.submitted_payloads.append(attendance_payload)
        return {"status": attendance_payload["status"], "token": token}


def make_user(**overrides) -> UserRecord:
    base = {
        "id": 1,
        "label": "测试账号",
        "student_no": "student-001",
        "password_ciphertext": "secret-password",
        "desired_status": "在校",
        "off_campus_city": "",
        "off_campus_district": "",
        "off_campus_reason": "",
        "schedule_time": "07:30",
        "overwrite_existing": False,
        "enabled": True,
        "created_at": "2026-04-14T00:00:00",
        "updated_at": "2026-04-14T00:00:00",
    }
    base.update(overrides)
    return UserRecord(**base)


class CheckInServiceTests(unittest.TestCase):
    def test_build_payload_for_off_campus_user(self) -> None:
        user = make_user(
            desired_status="不在校",
            off_campus_city="杭州市",
            off_campus_district="萧山区",
            off_campus_reason="外出学习",
        )
        repository = FakeRepository([user])
        service = CheckInService(repository, FakeSecretBox(), FakeClient(), "Asia/Shanghai", 3)
        now = datetime(2026, 4, 14, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

        payload = service.build_payload(user, now)

        self.assertEqual(payload["status"], "不在校")
        self.assertEqual(payload["off_campus_city"], "杭州市")
        self.assertEqual(payload["off_campus_district"], "萧山区")
        self.assertEqual(payload["off_campus_reason"], "外出学习")
        fingerprint = payload["_fp"]
        self.assertEqual(fingerprint["page_stay_ms"], 4862)
        self.assertEqual(len(fingerprint["mouse_points"]), 30)
        expected_start = int(now.timestamp() * 1000) - 4862
        self.assertEqual(fingerprint["mouse_points"][0]["t"], expected_start)
        self.assertEqual(fingerprint["mouse_points"][-1]["t"], expected_start + 4396)

    def test_manual_run_skips_when_today_already_matches(self) -> None:
        user = make_user(
            desired_status="不在校",
            off_campus_city="杭州市",
            off_campus_district="萧山区",
            off_campus_reason="外出学习",
        )
        repository = FakeRepository([user])
        client = FakeClient()
        client.today_status = {
            "status": "不在校",
            "off_campus_city": "杭州市",
            "off_campus_district": "萧山区",
            "off_campus_reason": "外出学习",
        }
        service = CheckInService(repository, FakeSecretBox(), client, "Asia/Shanghai", 3)

        run = service.run_user_now(1, datetime(2026, 4, 14, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai")))

        self.assertEqual(run.outcome, "skipped")
        self.assertEqual(client.submitted_payloads, [])

    def test_manual_run_submits_when_overwrite_enabled(self) -> None:
        user = make_user(
            desired_status="在校",
            overwrite_existing=True,
        )
        repository = FakeRepository([user])
        client = FakeClient()
        client.today_status = {
            "status": "不在校",
            "off_campus_city": "杭州市",
            "off_campus_district": "萧山区",
            "off_campus_reason": "外出学习",
        }
        service = CheckInService(repository, FakeSecretBox(), client, "Asia/Shanghai", 3)

        run = service.run_user_now(1, datetime(2026, 4, 14, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai")))

        self.assertEqual(run.outcome, "success")
        submitted_payload = client.submitted_payloads[0]
        self.assertEqual(submitted_payload["status"], "在校")
        self.assertIn("_fp", submitted_payload)
        mouse_points = submitted_payload["_fp"]["mouse_points"]
        self.assertEqual(mouse_points[1]["t"] - mouse_points[0]["t"], 150)
        self.assertEqual(mouse_points[-1]["t"] - mouse_points[0]["t"], 4396)

    def test_scheduler_runs_at_daily_randomized_time(self) -> None:
        user = make_user(schedule_time="08:30")
        repository = FakeRepository([user])
        client = FakeClient()
        service = CheckInService(repository, FakeSecretBox(), client, "Asia/Shanghai", 3)
        current_day = datetime(2026, 4, 14, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        scheduled_time = service._scheduled_time_for_day(user, current_day)

        runs = service.run_due_users(scheduled_time - timedelta(minutes=1))

        self.assertEqual(runs, [])
        self.assertEqual(client.submitted_payloads, [])

        runs = service.run_due_users(scheduled_time)

        self.assertEqual(len(runs), 1)
        self.assertEqual(client.submitted_payloads[0]["status"], "在校")

    def test_scheduler_offset_changes_by_day(self) -> None:
        user = make_user(schedule_time="08:30", student_no="student-randomized")
        repository = FakeRepository([user])
        service = CheckInService(repository, FakeSecretBox(), FakeClient(), "Asia/Shanghai", 3)

        day_one = service._scheduled_time_for_day(
            user,
            datetime(2026, 4, 14, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        day_two = service._scheduled_time_for_day(
            user,
            datetime(2026, 4, 15, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )

        self.assertNotEqual(day_one.strftime("%H:%M"), day_two.strftime("%H:%M"))
        self.assertGreaterEqual(day_one.strftime("%H:%M"), "08:30")
        self.assertGreaterEqual(day_two.strftime("%H:%M"), "08:30")


if __name__ == "__main__":
    unittest.main()
