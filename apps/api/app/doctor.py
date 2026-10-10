"""Read-only ResearchOS configuration check: python -m app.doctor [--connect] [--json]."""

import argparse
import json

from pydantic import ValidationError
from pydantic_settings import SettingsError
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.services.configuration import (
    ConfigurationCheck,
    configuration_report,
    database_check,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connect", action="store_true", help="Probe database and Alembic version")
    parser.add_argument("--json", action="store_true", help="Emit a machine-readable report")
    args = parser.parse_args()
    try:
        settings = get_settings()
    except (ValidationError, SettingsError) as exc:
        fields = sorted(
            {".".join(str(part) for part in error["loc"]) for error in exc.errors()}
            if isinstance(exc, ValidationError)
            else {"environment"}
        )
        detail = "环境变量格式无效；检查字段：" + ", ".join(fields)
        failed = {
            "environment": "unknown",
            "checks": [
                {"key": "environment", "status": "invalid", "detail": detail, "required": True}
            ],
            "ready": False,
            "database_probed": False,
        }
        if args.json:
            print(json.dumps(failed, ensure_ascii=False))
        else:
            print("ResearchOS configuration: " + detail)
        return 1
    runtime: ConfigurationCheck | None = None
    if args.connect:
        try:
            url = make_url(settings.database_url)
            if url.drivername.startswith("postgresql"):
                # A freshly started Windows PostgreSQL process can need longer
                # than three seconds to complete its first authenticated probe.
                # Keep the check bounded without rejecting a usable local server.
                url = url.update_query_dict({"connect_timeout": "10"})
            engine = create_engine(url, pool_pre_ping=True)
            try:
                with engine.connect() as connection:
                    runtime = database_check(connection)
            finally:
                engine.dispose()
        except (SQLAlchemyError, ValueError, OSError):
            runtime = ConfigurationCheck(
                key="database_runtime",
                status="invalid",
                detail="数据库连接失败；检查服务、地址、凭据和网络。",
                required=True,
            )
    report = configuration_report(settings, runtime)
    if args.json:
        print(json.dumps(report.model_dump(), ensure_ascii=False))
    else:
        print(f"ResearchOS configuration ({report.environment})")
        for check in report.checks:
            print(f"{check.key}: {check.status} — {check.detail}")
        if not args.connect:
            print("数据库未探测；使用 --connect 检查连通性与迁移。")
        print("核心配置就绪" if report.ready else "核心配置未就绪")
    return 0 if report.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
