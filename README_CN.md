# 自动考勤打卡

[English](./README.md) | [简体中文](./README_CN.md)

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](#)
[![FastAPI](https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white)](#)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)](#)
[![SQLite](https://img.shields.io/badge/SQLite-local%20storage-003B57?logo=sqlite&logoColor=white)](#)

一个可自托管的多用户自动考勤打卡服务，提供简洁的 Web 管理台、独立账号调度、手动执行、运行日志和 Docker 部署能力。

## 特性

- 支持多账号独立管理与调度
- 支持手动执行和定时执行
- 支持“已有当日记录时是否覆盖”的策略配置
- 使用 Fernet 对本地存储的账号密码进行加密
- 使用管理台会话登录保护后台
- 对管理员登录做基础限流
- 适合 Docker 自托管部署

## 技术栈

- 后端：FastAPI
- 存储：SQLite
- 调度：进程内轮询调度器
- 前端：原生 HTML / CSS / JavaScript
- 部署：Docker / docker compose

## 快速开始

### 1. 准备环境变量

复制示例配置文件并填写你自己的值：

```bash
cp .env.example .env
```

生成管理员密码哈希：

```bash
python3 -c "from app.auth import hash_admin_password; print(hash_admin_password('替换成你的管理密码'))"
```

把输出结果写入 `.env` 的 `CHECKIN_ADMIN_PASSWORD_HASH`。

### 2. 使用 Docker 运行

创建 `docker-compose.yml`：

```yaml
services:
  auto-checkin:
    image: ghcr.io/zyphoriate/sdu-checkin:main
    container_name: auto-checkin
    restart: unless-stopped
    ports:
      - "${CHECKIN_BIND_IP:-127.0.0.1}:18081:8080"
    environment:
      CHECKIN_ADMIN_PASSWORD_HASH: "${CHECKIN_ADMIN_PASSWORD_HASH:?set CHECKIN_ADMIN_PASSWORD_HASH}"
      CHECKIN_AUTH_COOKIE_SECURE: "${CHECKIN_AUTH_COOKIE_SECURE:-false}"
      CHECKIN_BASE_URL: "${CHECKIN_BASE_URL:?set CHECKIN_BASE_URL}"
      CHECKIN_DATA_DIR: /data
      CHECKIN_LOGIN_LIMIT_BLOCK_SECONDS: 900
      CHECKIN_LOGIN_LIMIT_MAX_ATTEMPTS: 5
      CHECKIN_LOGIN_LIMIT_WINDOW_SECONDS: 300
      CHECKIN_SERVICE_TIMEZONE: Asia/Shanghai
      CHECKIN_SCHEDULER_INTERVAL_SECONDS: 60
      CHECKIN_SCHEDULER_RETRY_LIMIT: 3
      CHECKIN_REQUEST_TIMEOUT_SECONDS: 20
    volumes:
      - ./data:/data
```

然后启动服务：

```bash
docker compose --env-file .env up -d
```

打开 `http://127.0.0.1:18081/`。

### 3. 本地直接运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
set -a
source .env
set +a
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

打开 `http://127.0.0.1:8080/`。

## 配置项

| 变量 | 是否必填 | 说明 |
| --- | --- | --- |
| `CHECKIN_BASE_URL` | 是 | 上游考勤系统根地址 |
| `CHECKIN_ADMIN_PASSWORD_HASH` | 是 | 通过 `app.auth.hash_admin_password()` 生成的管理员密码哈希 |
| `CHECKIN_DATA_DIR` | 否 | SQLite 数据库和 Fernet 密钥目录 |
| `CHECKIN_BIND_IP` | 否 | Docker 端口发布绑定地址，默认 `127.0.0.1` |
| `CHECKIN_AUTH_COOKIE_SECURE` | 否 | 服务放在 HTTPS 后面时应设置为 `true` |
| `CHECKIN_AUTH_SESSION_TTL_SECONDS` | 否 | 管理台会话有效期 |
| `CHECKIN_LOGIN_LIMIT_MAX_ATTEMPTS` | 否 | 单个来源 IP 在窗口期内允许的最大失败登录次数 |
| `CHECKIN_LOGIN_LIMIT_WINDOW_SECONDS` | 否 | 登录失败计数窗口时长 |
| `CHECKIN_LOGIN_LIMIT_BLOCK_SECONDS` | 否 | 超过阈值后的临时封禁时长 |
| `CHECKIN_SERVICE_TIMEZONE` | 否 | 调度器时区 |
| `CHECKIN_SCHEDULER_INTERVAL_SECONDS` | 否 | 调度扫描周期 |
| `CHECKIN_SCHEDULER_RETRY_LIMIT` | 否 | 每日定时执行失败后的最大重试次数 |
| `CHECKIN_REQUEST_TIMEOUT_SECONDS` | 否 | 请求上游系统的超时时间 |
| `CHECKIN_ENCRYPTION_KEY` | 否 | 可选固定 Fernet 密钥；不填则首次启动自动生成 |

安全模板见 [.env.example](./.env.example)。

## 安全说明

- 这个项目适合自托管，不建议直接暴露到公网。
- 默认 Docker 仅绑定到 `127.0.0.1`。
- 如果你需要让其他机器访问，请放在 HTTPS 反代后面，并设置 `CHECKIN_AUTH_COOKIE_SECURE=true`。
- 只应在你有权自动化操作的系统上使用本项目。

## 目录结构

```text
app/
  auth.py         管理员鉴权、会话签名、登录限流
  client.py       上游系统 HTTP 客户端
  config.py       基于环境变量的配置加载
  crypto.py       Fernet 加密封装
  db.py           SQLite 仓储层
  main.py         FastAPI 应用与路由
  scheduler.py    进程内调度循环
  service.py      打卡执行编排逻辑
  static/         管理台前端资源
tests/
  test_main_auth.py
  test_models.py
  test_service.py
data/
  .gitkeep
```

## 验证

```bash
python3 -m compileall app tests
python3 -m unittest discover -s tests
```

## 运维说明

- 如果要把服务迁移到新机器，并且希望保留已加密的账号凭据，需要同时迁移数据库和 Fernet 密钥。
- 当前调度器运行在应用进程内；如果没有额外的 leader election 或锁，不要让多个活动实例同时连接同一个数据库。

## 更新日志

### 2026-04-24

- **滑块验证绕过**：上游系统新增滑块验证环节，在提交打卡前必须完成验证。新增 `slider_challenge` / `slider_verify` 接口调用，并模拟人类拖拽轨迹。
- **扩展浏览器指纹**：`_fp` 字段新增 canvas hash、WebGL 渲染器、平台、设备内存、CPU 核心数、色深、像素比、音频哈希、数学哈希、webdriver 标志等，以适配上游最新的检测机制。
