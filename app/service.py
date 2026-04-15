from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .client import CheckInClient
from .crypto import SecretBox
from .db import Repository
from .models import RunRecord, UserRecord


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
            if current_time.strftime("%H:%M") < user.schedule_time:
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

    def build_payload(self, user: UserRecord) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": user.desired_status}
        if user.desired_status == "不在校":
            payload["off_campus_city"] = user.off_campus_city
            payload["off_campus_district"] = user.off_campus_district
            payload["off_campus_reason"] = user.off_campus_reason
        return payload

    def _execute_checkin(self, user: UserRecord, triggered_by: str, now: datetime) -> RunRecord:
        run_date = now.date().isoformat()
        desired_payload = self.build_payload(user)
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
