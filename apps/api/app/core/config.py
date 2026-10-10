from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def _workspace_root() -> Path:
    source = Path(__file__).resolve()
    for parent in source.parents:
        if (parent / "compose.yaml").exists():
            return parent
    # In the API container, /app is the package root and config comes from env.
    return source.parents[2]


ROOT_DIR = _workspace_root()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_DIR / ".env", extra="ignore")

    app_env: str = "development"
    pdf_annotations_enabled: bool = False
    database_url: str = Field(default="postgresql+psycopg://localhost/researchos", repr=False)
    session_secret: str = Field(default="", repr=False)
    csrf_secret: str = Field(default="", repr=False)
    initial_setup_token: str = Field(default="", repr=False)
    session_ttl_hours: int = 168
    app_timezone: str = "Asia/Shanghai"
    cors_origins: str = "http://localhost:3000"
    zotero_mode: str = "disabled"
    zotero_local_api_url: str = "http://127.0.0.1:23119/api"
    zotero_style_cache_enabled: bool = True
    zotero_style_data_dir: str = ""
    zotero_web_api_key: str = Field(default="", repr=False)
    zotero_web_library_type: str = "user"
    zotero_web_library_id: str = ""
    crossref_contact_email: str = ""
    github_api_token: str = Field(default="", repr=False)
    github_gcm_account: str = ""
    huggingface_api_token: str = Field(default="", repr=False)
    storage_provider: str = "local"
    local_storage_root: str = "./data/attachments"
    max_upload_mb: int = 100
    server_result_max_upload_mb: int = Field(default=32, ge=1, le=32)
    server_result_server_id: str = ""
    server_result_hmac_key: SecretStr = Field(
        default=SecretStr(""), validation_alias="RESEARCHOS_SERVER_RESULT_HMAC_KEY", repr=False
    )
    max_pdf_pages: int = 250
    ai_provider: str = "disabled"
    openai_api_key: str = Field(default="", repr=False)
    openai_model: str = ""
    codex_provider: str = "disabled"
    codex_workspaces_json: str = "[]"
    codex_model: str = ""
    codex_reasoning_effort: str = "max"
    codex_paper_timeout_seconds: int = 900
    paper_reading_skills_root: str = "./data/reading-skills/ieee-skills/skills"
    analytical_writer_skill_path: str = ""
    analytical_note_template_path: str = ""
    analytical_note_root: str = "./data/analytical-notes"
    canonical_publication_auto_retry: bool = False
    codex_task_timeout_seconds: int = 1800
    codex_budget_mode: str = "PROVIDER_QUOTA"
    codex_max_tokens_per_task: int = 100_000
    skill_discovery_enabled: bool = False
    skill_discovery_roots_json: str = "[]"
    research_planning_enabled: bool = False
    research_planning_skills_root: str = ""
    writing_enabled: bool = False
    writing_skills_root: str = ""
    writing_ieee_skills_root: str = ""
    manuscript_builds_enabled: bool = False
    manuscript_templates_root: str = ""
    manuscript_private_templates_root: str = ""
    latex_docker_executable: str = ""
    latex_compiler_image_id: str = ""
    latex_scratch_root: str = "data/document-builds"
    repository_assets_enabled: bool = False
    repository_asset_max_bytes: int = 268435456
    repository_asset_max_files: int = 10000
    project_source_workspaces_enabled: bool = False
    baseline_runner_enabled: bool = False
    baseline_runner_docker_executable: str = ""
    baseline_runner_docker_host: str = ""
    baseline_runner_image_id: str = ""
    baseline_runner_daemon_id: str = ""
    baseline_runner_root: str = "data/runner"
    project_archive_catalog_enabled: bool = False
    project_archive_write_enabled: bool = False
    code_changes_enabled: bool = False
    project_archive_workspaces_json: str = "[]"
    project_provision_enabled: bool = False
    project_provision_managed_root: str = ""
    project_provision_github_owner: str = ""
    project_provision_github_owner_id: int = 0


@lru_cache
def get_settings() -> Settings:
    return Settings()
