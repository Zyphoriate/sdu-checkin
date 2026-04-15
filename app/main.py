from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
import logging
import sqlite3
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from fastapi import Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .auth import AuthManager, LoginRateLimiter, LoginThrottledError, derive_session_secret
from .client import CheckInClient
from .config import settings
from .crypto import SecretBox
from .db import Repository
from .models import (
    HealthResponse,
    LoginRequest,
    RunResponse,
    SessionResponse,
    UserCreate,
    UserResponse,
    UserUpdate,
)
from .scheduler import SchedulerLoop
from .service import CheckInService


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

ROOT_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT_DIR / "app" / "static"
SERVICE_ZONE = ZoneInfo(settings.service_timezone)


def _now_iso() -> str:
    return datetime.now(SERVICE_ZONE).isoformat()


def _to_user_response(record) -> UserResponse:
    return UserResponse(
        id=record.id,
        label=record.label,
        student_no=record.student_no,
        desired_status=record.desired_status,
        off_campus_city=record.off_campus_city,
        off_campus_district=record.off_campus_district,
        off_campus_reason=record.off_campus_reason,
        schedule_time=record.schedule_time,
        overwrite_existing=record.overwrite_existing,
        enabled=record.enabled,
        created_at=record.created_at,
        updated_at=record.updated_at,
        has_password=True,
    )


def _to_run_response(record) -> RunResponse:
    return RunResponse(
        id=record.id,
        user_id=record.user_id,
        user_label=record.user_label,
        student_no=record.student_no,
        run_date=record.run_date,
        triggered_by=record.triggered_by,
        outcome=record.outcome,
        message=record.message,
        desired_payload=record.desired_payload,
        remote_snapshot=record.remote_snapshot,
        created_at=record.created_at,
    )


def _is_authenticated(request: Request) -> bool:
    auth_manager: AuthManager = request.app.state.auth_manager
    session_value = request.cookies.get(settings.auth_cookie_name)
    return auth_manager.is_session_valid(session_value)


def _require_authenticated(request: Request) -> None:
    if not _is_authenticated(request):
        raise HTTPException(status_code=401, detail="请先输入管理密码")


def _client_identifier(request: Request) -> str:
    if request.client is not None and request.client.host:
        return request.client.host
    return "unknown"


@asynccontextmanager
async def lifespan(app: FastAPI):
    repository = Repository(settings.database_path)
    repository.init()
    secret_box = SecretBox(settings.encryption_key_path, settings.encryption_key)
    auth_manager = AuthManager(
        password_hash=settings.admin_password_hash,
        session_secret=derive_session_secret(
            secret_box.key_material,
            settings.admin_password_hash,
        ),
        ttl_seconds=settings.auth_session_ttl_seconds,
    )
    login_rate_limiter = LoginRateLimiter(
        max_attempts=settings.login_limit_max_attempts,
        window_seconds=settings.login_limit_window_seconds,
        block_seconds=settings.login_limit_block_seconds,
    )
    client = CheckInClient(settings.base_url, settings.request_timeout_seconds)
    service = CheckInService(
        repository=repository,
        secret_box=secret_box,
        client=client,
        service_timezone=settings.service_timezone,
        scheduler_retry_limit=settings.scheduler_retry_limit,
    )
    scheduler = SchedulerLoop(service, settings.scheduler_interval_seconds)
    app.state.repository = repository
    app.state.secret_box = secret_box
    app.state.auth_manager = auth_manager
    app.state.login_rate_limiter = login_rate_limiter
    app.state.service = service
    app.state.scheduler = scheduler
    await scheduler.start()
    yield
    await scheduler.stop()


app = FastAPI(
    title="Multi-user Auto Check-in",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def disable_cache_for_ui(request: Request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/session", response_model=SessionResponse)
def get_session_status(request: Request) -> SessionResponse:
    return SessionResponse(authenticated=_is_authenticated(request))


@app.post("/api/session/login", response_model=SessionResponse)
def login(payload: LoginRequest, request: Request, response: Response) -> SessionResponse:
    auth_manager: AuthManager = request.app.state.auth_manager
    login_rate_limiter: LoginRateLimiter = request.app.state.login_rate_limiter
    client_id = _client_identifier(request)
    try:
        login_rate_limiter.ensure_allowed(client_id)
    except LoginThrottledError as exc:
        raise HTTPException(
            status_code=429,
            detail=f"登录失败次数过多，请在 {exc.retry_after_seconds} 秒后重试",
        ) from exc
    if not auth_manager.verify_password(payload.password):
        login_rate_limiter.record_failure(client_id)
        raise HTTPException(status_code=401, detail="管理密码错误")
    login_rate_limiter.record_success(client_id)
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=auth_manager.create_session_value(),
        max_age=settings.auth_session_ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.auth_cookie_secure,
    )
    return SessionResponse(authenticated=True)


@app.post("/api/session/logout", response_model=SessionResponse)
def logout(response: Response) -> SessionResponse:
    response.delete_cookie(
        settings.auth_cookie_name,
        samesite="lax",
        secure=settings.auth_cookie_secure,
    )
    return SessionResponse(authenticated=False)


@app.get("/api/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    _require_authenticated(request)
    repository: Repository = app.state.repository
    return HealthResponse(
        status="ok",
        user_count=repository.count_users(),
        timezone=settings.service_timezone,
        base_url=settings.base_url,
    )


@app.get("/api/users", response_model=list[UserResponse])
def list_users(request: Request) -> list[UserResponse]:
    _require_authenticated(request)
    repository: Repository = app.state.repository
    return [_to_user_response(record) for record in repository.list_users()]


@app.post("/api/users", response_model=UserResponse, status_code=201)
def create_user(payload: UserCreate, request: Request) -> UserResponse:
    _require_authenticated(request)
    repository: Repository = app.state.repository
    secret_box: SecretBox = app.state.secret_box
    try:
        record = repository.create_user(
            payload=payload,
            password_ciphertext=secret_box.encrypt(payload.password),
            now_iso=_now_iso(),
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="学号已存在") from exc
    return _to_user_response(record)


@app.put("/api/users/{user_id}", response_model=UserResponse)
def update_user(user_id: int, payload: UserUpdate, request: Request) -> UserResponse:
    _require_authenticated(request)
    repository: Repository = app.state.repository
    secret_box: SecretBox = app.state.secret_box
    encrypted_password = secret_box.encrypt(payload.password) if payload.password else None
    try:
        record = repository.update_user(
            user_id=user_id,
            payload=payload,
            password_ciphertext=encrypted_password,
            now_iso=_now_iso(),
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="学号已存在") from exc
    if record is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return _to_user_response(record)


@app.delete("/api/users/{user_id}", status_code=204)
def delete_user(user_id: int, request: Request) -> Response:
    _require_authenticated(request)
    repository: Repository = app.state.repository
    deleted = repository.delete_user(user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="用户不存在")
    return Response(status_code=204)


@app.get("/api/runs", response_model=list[RunResponse])
def list_runs(request: Request, limit: int = 100) -> list[RunResponse]:
    _require_authenticated(request)
    repository: Repository = app.state.repository
    safe_limit = max(1, min(limit, 500))
    return [_to_run_response(record) for record in repository.list_recent_runs(safe_limit)]


@app.post("/api/users/{user_id}/run", response_model=RunResponse)
def run_user(user_id: int, request: Request) -> RunResponse:
    _require_authenticated(request)
    service: CheckInService = app.state.service
    try:
        record = service.run_user_now(user_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="用户不存在") from exc
    return _to_run_response(record)
