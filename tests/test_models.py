from __future__ import annotations

import unittest

from pydantic import ValidationError

from app.models import UserCreate, UserUpdate


class UserModelTests(unittest.TestCase):
    def test_user_create_rejects_none_password(self) -> None:
        with self.assertRaises(ValidationError):
            UserCreate(
                label="测试",
                student_no="student-001",
                password=None,
                desired_status="在校",
                off_campus_city="",
                off_campus_district="",
                off_campus_reason="",
                schedule_time="07:30",
                overwrite_existing=False,
                enabled=True,
            )

    def test_user_update_allows_empty_password_as_keep_existing(self) -> None:
        payload = UserUpdate(
            label="测试",
            student_no="student-001",
            password="",
            desired_status="在校",
            off_campus_city="",
            off_campus_district="",
            off_campus_reason="",
            schedule_time="07:30",
            overwrite_existing=False,
            enabled=True,
        )

        self.assertIsNone(payload.password)


if __name__ == "__main__":
    unittest.main()
