"""Configuration diagnostics never disclose secrets or call external providers."""

import sys
from pathlib import Path
from secrets import token_urlsafe
from types import SimpleNamespace

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from app import doctor
from app.core.config import Settings
from app.services import configuration as configuration_service
from app.services.configuration import (
    configuration_checks,
    configuration_report,
    database_check,
    ensure_production_ready,
)

# Runtime-only offline fixture credentials; never usable host credentials.
BAD_SECRET_A = "-".join(['replace', 'with', 'long', 'random', 'secret'])
BAD_SECRET_B = "-".join(['replace', 'with', 'another', 'long', 'random', 'secret'])
BAD_SETUP = "-".join(['replace', 'with', 'one', 'time', 'random', 'token'])


def test_production_rejects_example_secrets() -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        database_url="postgresql+psycopg://researchos:change-me@localhost/researchos",
        session_secret=BAD_SECRET_A,
        csrf_secret=BAD_SECRET_B,
    )
    checks = {check.key: check for check in configuration_checks(settings)}
    assert checks["authentication_secrets"].status == "invalid"
    assert checks["database_url"].status == "invalid"
    assert not configuration_report(settings).ready
    try:
        ensure_production_ready(settings)
    except RuntimeError as exc:
        assert "authentication_secrets" in str(exc)
        assert "change-me" not in str(exc)
    else:
        raise AssertionError("Production accepted example secrets")


def test_optional_integrations_disabled_and_web_validation() -> None:
    settings = Settings(_env_file=None, database_url="sqlite+pysqlite://")
    checks = {check.key: check for check in configuration_checks(settings)}
    assert checks["zotero"].status == "disabled"
    assert checks["crossref"].status == "configured"
    assert checks["paper_ai"].status == "disabled"
    assert checks["codex"].status == "disabled"
    assert settings.analytical_writer_skill_path == ""
    assert settings.analytical_note_template_path == ""
    assert settings.analytical_note_root == "./data/analytical-notes"


def test_repository_credentials_are_optional_masked_and_never_network_probed() -> None:
    github_token = token_urlsafe(40)
    hf_token = token_urlsafe(40)
    settings = Settings(_env_file=None, github_api_token=github_token, huggingface_api_token=hf_token)
    report = configuration_report(settings)
    serialized = report.model_dump_json()
    assert github_token not in serialized and hf_token not in serialized
    checks = {check.key: check for check in report.checks}
    assert checks["github_repository_api"].status == "configured"
    assert checks["huggingface_repository_api"].status == "configured"
    anonymous = Settings(_env_file=None)
    checks = {check.key: check for check in configuration_checks(anonymous)}
    assert checks["github_repository_api"].status == "configured"
    invalid = Settings(_env_file=None, github_api_token="line1\nline2")
    check = next(check for check in configuration_checks(invalid) if check.key == "github_repository_api")
    assert check.status == "invalid" and "line1" not in check.detail
    settings.zotero_mode = "web"
    zotero_key = token_urlsafe(32)
    settings.zotero_web_api_key = zotero_key
    settings.zotero_web_library_id = "not-an-id"
    checks = {check.key: check for check in configuration_checks(settings)}
    assert checks["zotero"].status == "missing"
    assert zotero_key not in repr(checks)
    settings.crossref_contact_email = "bad contact"
    assert (
        next(check.status for check in configuration_checks(settings) if check.key == "crossref")
        == "invalid"
    )


def test_production_rejects_placeholder_setup_token_but_allows_it_removed() -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        database_url="postgresql+psycopg://researchos@localhost/researchos",
        session_secret=token_urlsafe(32),
        csrf_secret=token_urlsafe(32),
        initial_setup_token=BAD_SETUP,
    )
    assert (
        next(
            check.status
            for check in configuration_checks(settings)
            if check.key == "initial_setup_token"
        )
        == "invalid"
    )
    try:
        ensure_production_ready(settings)
    except RuntimeError as exc:
        assert "initial_setup_token" in str(exc)
    else:
        raise AssertionError("Production accepted an example setup token")
    settings.initial_setup_token = ""
    ensure_production_ready(settings)


def test_database_check_requires_current_migration() -> None:
    engine = create_engine("sqlite+pysqlite://")
    with engine.begin() as connection:
        assert database_check(connection).status == "invalid"
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        head = ScriptDirectory.from_config(
            Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        ).get_current_head()
        connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:head)"), {"head": head}
        )
        assert database_check(connection).status == "configured"
    engine.dispose()


def test_postgres_doctor_detects_missing_search_indexes(monkeypatch: object) -> None:
    class FakeConnection:
        dialect = SimpleNamespace(name="postgresql")

        def __init__(self) -> None:
            self.rows: list[tuple[str, str, str]] = []

        def execute(self, statement: object) -> list[tuple[str, str, str]]:
            return self.rows if "pg_indexes" in str(statement) else []

    monkeypatch.setattr(  # type: ignore[attr-defined]
        configuration_service.MigrationContext,
        "configure",
        lambda _connection: SimpleNamespace(get_current_revision=lambda: "a04920260930"),
    )
    monkeypatch.setattr(  # type: ignore[attr-defined]
        configuration_service.ScriptDirectory,
        "from_config",
        lambda _config: SimpleNamespace(get_current_head=lambda: "a04920260930"),
    )
    connection = FakeConnection()
    assert database_check(connection).status == "invalid"  # type: ignore[arg-type]
    connection.rows = [
        (table, name, "CREATE INDEX ... USING gin (to_tsvector('simple'::regconfig, ...))")
        for table, name in (
            ("papers", "ix_papers_search_simple_gin"),
            ("research_projects", "ix_research_projects_search_simple_gin"),
            ("tasks", "ix_tasks_search_simple_gin"),
            ("paper_notes", "ix_paper_notes_search_simple_gin"),
        )
    ]
    assert database_check(connection).status == "configured"  # type: ignore[arg-type]


def test_doctor_json_redacts_secret_values(monkeypatch: object, capsys: object) -> None:
    # pytest monkeypatch/capsys are duck-typed to keep production dependencies out of the test.
    session_secret, csrf_secret, zotero_key = (token_urlsafe(32) for _ in range(3))
    settings = Settings(
        _env_file=None,
        database_url="sqlite+pysqlite://",
        session_secret=session_secret,
        csrf_secret=csrf_secret,
        zotero_mode="web",
        zotero_web_api_key=zotero_key,
        zotero_web_library_id="12345",
    )
    monkeypatch.setattr(doctor, "get_settings", lambda: settings)  # type: ignore[attr-defined]
    monkeypatch.setattr(sys, "argv", ["doctor", "--json"])  # type: ignore[attr-defined]
    assert doctor.main() == 0
    output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert '"database_probed": false' in output
    assert session_secret not in output
    assert csrf_secret not in output
    assert zotero_key not in output


def test_doctor_redacts_invalid_environment_input(monkeypatch: object, capsys: object) -> None:
    private_value = token_urlsafe(32)

    def invalid_settings() -> Settings:
        return Settings(_env_file=None, session_ttl_hours=private_value)

    monkeypatch.setattr(doctor, "get_settings", invalid_settings)  # type: ignore[attr-defined]
    monkeypatch.setattr(sys, "argv", ["doctor", "--json"])  # type: ignore[attr-defined]
    assert doctor.main() == 1
    output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "session_ttl_hours" in output
    assert private_value not in output
