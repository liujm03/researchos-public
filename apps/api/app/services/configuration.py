"""Read-only deployment diagnostics shared by the CLI and owner API."""

import json
import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings

CheckStatus = Literal["configured", "disabled", "missing", "invalid"]


class ConfigurationCheck(BaseModel):
    key: str
    status: CheckStatus
    detail: str
    required: bool = False


class ConfigurationReport(BaseModel):
    environment: str
    checks: list[ConfigurationCheck]
    ready: bool
    database_probed: bool


def _check(
    key: str, status: CheckStatus, detail: str, required: bool = False
) -> ConfigurationCheck:
    return ConfigurationCheck(key=key, status=status, detail=detail, required=required)


def _usable_secret(value: str) -> bool:
    stripped = value.strip()
    return len(stripped) >= 32 and not _placeholder(stripped)


def _placeholder(value: str) -> bool:
    return bool(
        re.search(
            r"replace|change-me|example|placeholder|your[-_ ]|test[-_ ]|secret[-_ ]here",
            value,
            re.IGNORECASE,
        )
    )


def configuration_checks(settings: Settings) -> list[ConfigurationCheck]:
    checks: list[ConfigurationCheck] = []
    production = settings.app_env == "production"
    checks.append(
        _check(
            "environment",
            "configured"
            if settings.app_env in {"development", "production", "test"}
            else "invalid",
            "运行模式已识别。"
            if settings.app_env in {"development", "production", "test"}
            else "APP_ENV 只能为 development、test 或 production。",
            True,
        )
    )
    try:
        db_url = make_url(settings.database_url)
        db_valid = db_url.drivername in {
            "postgresql",
            "postgresql+psycopg",
            "sqlite",
            "sqlite+pysqlite",
        }
        if production and not db_url.drivername.startswith("postgresql"):
            db_valid = False
        if production and db_url.password and _placeholder(db_url.password):
            db_valid = False
    except (ValueError, TypeError):
        db_valid = False
    checks.append(
        _check(
            "database_url",
            "configured" if db_valid else "invalid",
            "数据库地址格式有效；连接尚未验证。"
            if db_valid
            else "数据库地址无效；生产环境需要 PostgreSQL 和非示例密码。",
            True,
        )
    )
    session_ok = _usable_secret(settings.session_secret)
    csrf_ok = _usable_secret(settings.csrf_secret)
    distinct = settings.session_secret != settings.csrf_secret
    secrets_ok = session_ok and csrf_ok and distinct
    checks.append(
        _check(
            "authentication_secrets",
            "configured" if secrets_ok else ("invalid" if production else "missing"),
            "会话与 CSRF 密钥已分别配置。"
            if secrets_ok
            else "设置两个不同的随机密钥，每个至少 32 字符；示例值不可用于生产。",
            True,
        )
    )
    token_ok = _usable_secret(settings.initial_setup_token)
    checks.append(
        _check(
            "initial_setup_token",
            "configured"
            if token_ok
            else ("invalid" if settings.initial_setup_token.strip() else "missing"),
            "初始化令牌已配置；已有 owner 后可移除。"
            if token_ok
            else "首次建立 owner 前需配置一次性随机令牌；已有 owner 可保持为空。",
            False,
        )
    )
    storage_ok = settings.storage_provider == "local" and bool(settings.local_storage_root.strip())
    checks.append(
        _check(
            "storage",
            "configured" if storage_ok else "invalid",
            "本地存储已配置；目录读写尚未验证。"
            if storage_ok
            else "当前仅支持非空的 local 存储目录。",
            True,
        )
    )
    if settings.zotero_mode == "disabled":
        checks.append(_check("zotero", "disabled", "Zotero 连接未启用。"))
    elif settings.zotero_mode == "local":
        parsed = urlparse(settings.zotero_local_api_url)
        local_ok = parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        checks.append(
            _check(
                "zotero",
                "configured" if local_ok else "invalid",
                "本机 API 地址已配置；需与 Zotero Desktop 位于同一主机。"
                if local_ok
                else "Zotero Local 地址必须是本机 HTTP 地址。",
            )
        )
    elif settings.zotero_mode == "web":
        web_ok = (
            bool(settings.zotero_web_api_key.strip())
            and settings.zotero_web_library_type in {"user", "group"}
            and bool(re.fullmatch(r"[0-9]+", settings.zotero_web_library_id))
        )
        checks.append(
            _check(
                "zotero",
                "configured" if web_ok else "missing",
                "Web API 参数已配置；权限和连通性尚未验证。"
                if web_ok
                else "Zotero Web 需要 API Key、user/group 库类型和数字 Library ID。",
            )
        )
    else:
        checks.append(_check("zotero", "invalid", "未知的 ZOTERO_MODE。"))
    contact = settings.crossref_contact_email.strip()
    contact_ok = not contact or (
        len(contact) <= 254
        and "@" in contact
        and all(33 <= ord(character) <= 126 for character in contact)
    )
    checks.append(
        _check(
            "crossref",
            "configured" if contact_ok else "invalid",
            "开放 DOI 元数据查询可按需使用；连接尚未验证。"
            if contact_ok
            else "CROSSREF_CONTACT_EMAIL 格式无效。",
        )
    )
    for provider_key, token in (
        ("github_repository_api", settings.github_api_token),
        ("huggingface_repository_api", settings.huggingface_api_token),
    ):
        valid_token = not token or (
            len(token) <= 8192 and all(33 <= ord(char) <= 126 for char in token)
        )
        checks.append(_check(
            provider_key,
            "configured" if valid_token else "invalid",
            "公共仓库元数据可匿名读取；可选 Token 已配置，连通性尚未验证。"
            if token and valid_token
            else "公共仓库元数据可匿名读取；未配置可选 Token，连通性尚未验证。"
            if valid_token
            else "可选 Token 格式无效；请在服务端环境修正，不在网页中填写凭据。",
        ))
    if settings.ai_provider == "disabled":
        checks.append(_check("paper_ai", "disabled", "论文 AI 未启用；不会外发资料。"))
    elif settings.ai_provider == "openai":
        ai_ok = bool(settings.openai_api_key.strip() and settings.openai_model.strip())
        checks.append(
            _check(
                "paper_ai",
                "configured" if ai_ok else "missing",
                "AI 参数已配置；仍需 owner 授权外发范围与预算。"
                if ai_ok
                else "OpenAI 适配器需要 API Key 和模型名。",
            )
        )
    elif settings.ai_provider == "codex":
        ai_ok = bool(settings.codex_model.strip()) and settings.codex_paper_timeout_seconds > 0
        checks.append(
            _check(
                "paper_ai", "configured" if ai_ok else "missing",
                "Codex 论文模型已配置；需在 worker 所在主机验证登录与受限工具能力，并由 owner 设置外发范围和预算。"
                if ai_ok else "Codex 论文分析需要 CODEX_MODEL 和正数超时时间。",
            )
        )
    else:
        checks.append(_check("paper_ai", "invalid", "未知的 AI_PROVIDER。"))
    if settings.codex_provider == "disabled":
        checks.append(_check("codex", "disabled", "Codex 执行器未启用。"))
    elif settings.codex_provider == "openai_codex_sdk":
        try:
            workspaces = json.loads(settings.codex_workspaces_json)
            valid_workspaces = (
                isinstance(workspaces, list)
                and bool(workspaces)
                and all(
                    isinstance(row, dict)
                    and isinstance(row.get("id"), str)
                    and isinstance(row.get("path"), str)
                    and Path(row["path"]).is_absolute()
                    and isinstance(row.get("allowed_modes", ["read_only"]), list)
                    and bool(row.get("allowed_modes", ["read_only"]))
                    and set(row.get("allowed_modes", ["read_only"]))
                    <= {"read_only", "workspace_write"}
                    for row in workspaces
                )
            )
        except (ValueError, TypeError):
            valid_workspaces = False
        codex_ok = bool(settings.codex_model.strip()) and valid_workspaces
        checks.append(
            _check(
                "codex",
                "configured" if codex_ok else "missing",
                "静态参数已配置；SDK、认证及工作区仅能在实际执行主机验证。"
                if codex_ok
                else "Codex 需要模型和至少一个有效的绝对路径工作区；执行器须在工作区所在主机启动。",
            )
        )
    else:
        checks.append(_check("codex", "invalid", "未知的 CODEX_PROVIDER。"))
    return checks


def database_check(connection: Connection) -> ConfigurationCheck:
    try:
        connection.execute(text("SELECT 1"))
        current = MigrationContext.configure(connection).get_current_revision()
        config_path = Path(__file__).resolve().parents[2] / "alembic.ini"
        head = ScriptDirectory.from_config(Config(str(config_path))).get_current_head()
        if current != head:
            return _check(
                "database_runtime",
                "invalid",
                "数据库可连接，但 Alembic 版本不是当前 head；先运行迁移。",
                True,
            )
        if connection.dialect.name == "postgresql":
            expected = {
                ("papers", "ix_papers_search_simple_gin"),
                ("research_projects", "ix_research_projects_search_simple_gin"),
                ("tasks", "ix_tasks_search_simple_gin"),
                ("paper_notes", "ix_paper_notes_search_simple_gin"),
            }
            rows = connection.execute(
                text(
                    "SELECT tablename, indexname, indexdef FROM pg_indexes "
                    "WHERE schemaname = current_schema() "
                    "AND indexname IN ("
                    "'ix_papers_search_simple_gin', "
                    "'ix_research_projects_search_simple_gin', "
                    "'ix_tasks_search_simple_gin', "
                    "'ix_paper_notes_search_simple_gin')"
                )
            )
            present = {
                (str(table), str(name))
                for table, name, definition in rows
                if "using gin" in str(definition).lower()
                and "to_tsvector" in str(definition).lower()
                and "simple" in str(definition).lower()
            }
            if present != expected:
                return _check(
                    "database_runtime",
                    "invalid",
                    "数据库迁移为当前 head，但全文索引缺失或定义不符。",
                    True,
                )
        return _check(
            "database_runtime", "configured", "数据库可连接，Alembic 版本为当前 head。", True
        )
    except SQLAlchemyError:
        return _check("database_runtime", "invalid", "数据库查询或迁移版本读取失败。", True)


def configuration_report(
    settings: Settings, runtime_check: ConfigurationCheck | None = None
) -> ConfigurationReport:
    checks = configuration_checks(settings)
    if runtime_check is not None:
        checks.append(runtime_check)
    return ConfigurationReport(
        environment=settings.app_env,
        checks=checks,
        ready=all(check.status == "configured" for check in checks if check.required),
        database_probed=runtime_check is not None,
    )


def ensure_production_ready(settings: Settings) -> None:
    if settings.app_env not in {"development", "test", "production"}:
        raise RuntimeError("APP_ENV must be development, test, or production")
    if settings.app_env != "production":
        return
    checks = configuration_checks(settings)
    blocked = [check.key for check in checks if check.required and check.status != "configured"]
    if any(check.key == "initial_setup_token" and check.status == "invalid" for check in checks):
        blocked.append("initial_setup_token")
    if blocked:
        raise RuntimeError("Production configuration invalid: " + ", ".join(blocked))
