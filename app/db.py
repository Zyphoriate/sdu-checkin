from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import Lock

from .models import RunRecord, UserCreate, UserRecord, UserUpdate


class Repository:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._lock = Lock()

    def init(self) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL;")
            connection.execute("PRAGMA foreign_keys=ON;")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    label TEXT NOT NULL DEFAULT '',
                    student_no TEXT NOT NULL UNIQUE,
                    password_ciphertext TEXT NOT NULL,
                    desired_status TEXT NOT NULL,
                    off_campus_city TEXT NOT NULL DEFAULT '',
                    off_campus_district TEXT NOT NULL DEFAULT '',
                    off_campus_reason TEXT NOT NULL DEFAULT '',
                    schedule_time TEXT NOT NULL,
                    overwrite_existing INTEGER NOT NULL DEFAULT 0,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    run_date TEXT NOT NULL,
                    triggered_by TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    message TEXT NOT NULL,
                    desired_payload TEXT NOT NULL,
                    remote_snapshot TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_runs_user_created_at
                ON runs (user_id, created_at DESC);

                CREATE INDEX IF NOT EXISTS idx_runs_date_triggered
                ON runs (run_date, triggered_by);
                """
            )

    def count_users(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM users").fetchone()
        return int(row["count"])

    def list_users(self) -> list[UserRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    label,
                    student_no,
                    password_ciphertext,
                    desired_status,
                    off_campus_city,
                    off_campus_district,
                    off_campus_reason,
                    schedule_time,
                    overwrite_existing,
                    enabled,
                    created_at,
                    updated_at
                FROM users
                ORDER BY id DESC
                """
            ).fetchall()
        return [self._row_to_user(row) for row in rows]

    def get_user(self, user_id: int) -> UserRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    id,
                    label,
                    student_no,
                    password_ciphertext,
                    desired_status,
                    off_campus_city,
                    off_campus_district,
                    off_campus_reason,
                    schedule_time,
                    overwrite_existing,
                    enabled,
                    created_at,
                    updated_at
                FROM users
                WHERE id = ?
                """,
                (user_id,),
            ).fetchone()
        return self._row_to_user(row) if row else None

    def create_user(
        self,
        payload: UserCreate,
        password_ciphertext: str,
        now_iso: str,
    ) -> UserRecord:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO users (
                    label,
                    student_no,
                    password_ciphertext,
                    desired_status,
                    off_campus_city,
                    off_campus_district,
                    off_campus_reason,
                    schedule_time,
                    overwrite_existing,
                    enabled,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.label,
                    payload.student_no,
                    password_ciphertext,
                    payload.desired_status,
                    payload.off_campus_city,
                    payload.off_campus_district,
                    payload.off_campus_reason,
                    payload.schedule_time,
                    int(payload.overwrite_existing),
                    int(payload.enabled),
                    now_iso,
                    now_iso,
                ),
            )
            user_id = int(cursor.lastrowid)
        user = self.get_user(user_id)
        if user is None:
            raise RuntimeError("用户创建后读取失败")
        return user

    def update_user(
        self,
        user_id: int,
        payload: UserUpdate,
        password_ciphertext: str | None,
        now_iso: str,
    ) -> UserRecord | None:
        existing = self.get_user(user_id)
        if existing is None:
            return None
        final_password = password_ciphertext or existing.password_ciphertext
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE users
                SET
                    label = ?,
                    student_no = ?,
                    password_ciphertext = ?,
                    desired_status = ?,
                    off_campus_city = ?,
                    off_campus_district = ?,
                    off_campus_reason = ?,
                    schedule_time = ?,
                    overwrite_existing = ?,
                    enabled = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    payload.label,
                    payload.student_no,
                    final_password,
                    payload.desired_status,
                    payload.off_campus_city,
                    payload.off_campus_district,
                    payload.off_campus_reason,
                    payload.schedule_time,
                    int(payload.overwrite_existing),
                    int(payload.enabled),
                    now_iso,
                    user_id,
                ),
            )
        return self.get_user(user_id)

    def delete_user(self, user_id: int) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return cursor.rowcount > 0

    def list_recent_runs(self, limit: int = 100) -> list[RunRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    runs.id,
                    runs.user_id,
                    runs.run_date,
                    runs.triggered_by,
                    runs.outcome,
                    runs.message,
                    runs.desired_payload,
                    runs.remote_snapshot,
                    runs.created_at,
                    users.label AS user_label,
                    users.student_no AS student_no
                FROM runs
                JOIN users ON users.id = runs.user_id
                ORDER BY runs.created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_run(row) for row in rows]

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
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO runs (
                    user_id,
                    run_date,
                    triggered_by,
                    outcome,
                    message,
                    desired_payload,
                    remote_snapshot,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    run_date,
                    triggered_by,
                    outcome,
                    message,
                    json.dumps(desired_payload, ensure_ascii=False),
                    json.dumps(remote_snapshot, ensure_ascii=False),
                    created_at,
                ),
            )
            run_id = int(cursor.lastrowid)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    runs.id,
                    runs.user_id,
                    runs.run_date,
                    runs.triggered_by,
                    runs.outcome,
                    runs.message,
                    runs.desired_payload,
                    runs.remote_snapshot,
                    runs.created_at,
                    users.label AS user_label,
                    users.student_no AS student_no
                FROM runs
                JOIN users ON users.id = runs.user_id
                WHERE runs.id = ?
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("运行日志写入后读取失败")
        return self._row_to_run(row)

    def get_scheduler_attempt_summary(self, user_id: int, run_date: str) -> tuple[int, bool]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    COUNT(*) AS attempt_count,
                    MAX(CASE WHEN outcome IN ('success', 'skipped') THEN 1 ELSE 0 END) AS has_terminal_outcome
                FROM runs
                WHERE user_id = ? AND run_date = ? AND triggered_by = 'scheduler'
                """,
                (user_id, run_date),
            ).fetchone()
        attempt_count = int(row["attempt_count"])
        has_terminal_outcome = bool(row["has_terminal_outcome"])
        return attempt_count, has_terminal_outcome

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON;")
        return connection

    @staticmethod
    def _row_to_user(row: sqlite3.Row) -> UserRecord:
        return UserRecord(
            id=int(row["id"]),
            label=row["label"],
            student_no=row["student_no"],
            password_ciphertext=row["password_ciphertext"],
            desired_status=row["desired_status"],
            off_campus_city=row["off_campus_city"],
            off_campus_district=row["off_campus_district"],
            off_campus_reason=row["off_campus_reason"],
            schedule_time=row["schedule_time"],
            overwrite_existing=bool(row["overwrite_existing"]),
            enabled=bool(row["enabled"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_run(row: sqlite3.Row) -> RunRecord:
        return RunRecord(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            user_label=row["user_label"] or "",
            student_no=row["student_no"],
            run_date=row["run_date"],
            triggered_by=row["triggered_by"],
            outcome=row["outcome"],
            message=row["message"],
            desired_payload=json.loads(row["desired_payload"]),
            remote_snapshot=json.loads(row["remote_snapshot"]),
            created_at=row["created_at"],
        )
