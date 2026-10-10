import json
import os
import re
from pathlib import Path
from typing import Literal, overload

from app.core.config import ROOT_DIR, get_settings
from app.domain.ai import AIProvider, AIProviderDescriptor
from app.domain.archive_catalog import ArchiveCatalogProvider
from app.domain.archive_execution import ArchiveExecutionProvider, ArchiveExecutionScope
from app.domain.baseline_runs import BaselineRunProvider
from app.domain.baselines import BaselineAssetProbeProvider
from app.domain.bibliography import BibliographyParser
from app.domain.code_changes import CodeFileProvider
from app.domain.codex import CodexProvider, CodexRuntimeCapabilities
from app.domain.evidence_bundles import EvidenceBundleRenderer
from app.domain.generated_file_deletion import GeneratedFileDeletionProvider
from app.domain.github_archive import ProjectArchiveProvider
from app.domain.latex_compilation import LatexCompilationProvider
from app.domain.literature import (
    DoiLookupProvider,
    LiteratureProvider,
    PaperIdLookupProvider,
    SearchLiteratureProvider,
)
from app.domain.literature_discovery import LiteratureDiscoveryLinksProvider
from app.domain.manuscript_templates import ManuscriptTemplateProvider
from app.domain.manuscripts import ManuscriptSourceRenderer
from app.domain.note_output import NoteOutputProvider
from app.domain.pdf_quotes import PDFQuoteProvider
from app.domain.pdf_reading import PDFVisualProvider, ReadingSkillProvider
from app.domain.project_sources import ProjectSourceScope, ProjectSourceWorkspaceProvider
from app.domain.provisioning import LocalProjectProvisionProvider
from app.domain.reference_manager import ReferenceManagerProvider
from app.domain.repositories import OpenSourceRepositoryProvider, RepositoryProviderDescriptor
from app.domain.repository_assets import RemoteAssetProvider
from app.domain.research_planning import PlanningSkillProvider, ResearchPlanningProvider
from app.domain.result_artifact_probe import ResultArtifactProbe
from app.domain.server_packages import ServerTaskPackageRenderer
from app.domain.server_results import ServerReceiptAuthentication, ServerResultBundleParser
from app.domain.skill_discovery import SkillDiscoveryProvider
from app.domain.storage import StorageProvider
from app.domain.writing_skills import WritingSkillProvider
from app.errors import DomainError
from app.providers.ai.codex_paper import CodexPaperProvider
from app.providers.ai.openai_responses import OpenAIResponsesProvider
from app.providers.codex.openai_codex_sdk import OpenAICodexSDKProvider
from app.providers.literature.arxiv import ArxivAdapter
from app.providers.literature.bibliography_file import BibliographyFileAdapter
from app.providers.literature.crossref import CrossrefAdapter
from app.providers.literature.discovery_links import OfficialDiscoveryLinksAdapter
from app.providers.pdf_visual import PDFiumVisualProvider
from app.providers.reference_manager.zotero_local import ZoteroLocalAdapter
from app.providers.reference_manager.zotero_style_cache import ZoteroStyleCache
from app.providers.reference_manager.zotero_web import ZoteroWebAdapter
from app.providers.server_packages.markdown_zip import MarkdownZipServerTaskPackageRenderer
from app.providers.server_results.hmac_receipt import HMACServerReceiptAuthentication
from app.providers.server_results.zip_json import ZipJSONServerResultBundleParser
from app.providers.storage.local import LocalStorageProvider


def evidence_bundle_renderer() -> EvidenceBundleRenderer:
    from app.providers.evidence_bundles import TextEvidenceBundleRenderer

    return TextEvidenceBundleRenderer()


def literature_discovery_links_provider() -> LiteratureDiscoveryLinksProvider:
    return OfficialDiscoveryLinksAdapter()


def archive_catalog_workspaces() -> dict[str, tuple[str, Path]]:
    """Fixed, host-configured project roots; never accept arbitrary client paths."""
    try:
        raw = json.loads(get_settings().project_archive_workspaces_json)
        if not isinstance(raw, list) or len(raw) > 100:
            raise ValueError
        result: dict[str, tuple[str, Path]] = {}
        paths: set[str] = set()
        for row in raw:
            if not isinstance(row, dict) or set(row) != {"key", "label", "path"}:
                raise ValueError
            key, label, path = row["key"], row["label"], row["path"]
            if (
                not isinstance(key, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", key)
                or key in result
            ):
                raise ValueError
            if (
                not isinstance(label, str)
                or not 1 <= len(label.strip()) <= 120
                or any(ord(character) < 32 for character in label)
            ):
                raise ValueError
            if (
                not isinstance(path, str)
                or not Path(path).is_absolute()
                or any(ord(character) < 32 for character in path)
            ):
                raise ValueError
            canonical = os.path.normcase(os.path.abspath(path))
            if canonical in paths:
                raise ValueError
            paths.add(canonical)
            # Preserve un-resolved path so the local adapter detects junctions.
            result[key] = (label.strip(), Path(path))
        return result
    except (ValueError, TypeError, OSError, KeyError):
        raise DomainError(
            "ARCHIVE_CONFIGURATION_INVALID", "Invalid fixed archive workspace configuration", 503
        ) from None


def archive_catalog(
    workspace_key: str,
    *,
    managed_folder_name: str | None = None,
    managed_root_fingerprint: str | None = None,
) -> ArchiveCatalogProvider:
    if not get_settings().project_archive_catalog_enabled:
        raise DomainError(
            "ARCHIVE_CATALOG_DISABLED",
            "Archive inventory imports are disabled on this execution host",
            503,
        )
    from app.providers.project_archives.catalog import LocalArchiveCatalogProvider

    return LocalArchiveCatalogProvider(
        archive_workspace_path(
            workspace_key,
            managed_folder_name=managed_folder_name,
            managed_root_fingerprint=managed_root_fingerprint,
        )
    )


def archive_remote(expected_login: str) -> ProjectArchiveProvider:
    from app.providers.project_archives.credentials import github_credential
    from app.providers.project_archives.github import GitHubProjectArchiveAdapter

    settings = get_settings()
    if not settings.project_archive_catalog_enabled:
        raise DomainError(
            "ARCHIVE_CATALOG_DISABLED",
            "Archive inventory imports are disabled on this execution host",
            503,
        )
    configured = settings.github_api_token
    if not configured:
        configured = github_credential(expected_login).get_secret_value()
    return GitHubProjectArchiveAdapter(token=configured)


def archive_workspace_path(
    workspace_key: str,
    *,
    managed_folder_name: str | None = None,
    managed_root_fingerprint: str | None = None,
) -> Path:
    if managed_folder_name is not None:
        from app.domain.provisioning import managed_root_fingerprint as fingerprint

        settings = get_settings()
        root = Path(settings.project_provision_managed_root)
        if (
            not root.is_absolute()
            or fingerprint(root) != managed_root_fingerprint
            or not re.fullmatch(r"provision-[a-f0-9]{32}", workspace_key)
            or managed_folder_name in {".", ".."}
            or not managed_folder_name
            or any(character in "/\\:" or ord(character) < 32 for character in managed_folder_name)
        ):
            raise DomainError(
                "ARCHIVE_SCOPE_CHANGED",
                "Managed project directory differs from its approved root",
                409,
            )
        return root / managed_folder_name
    entry = archive_catalog_workspaces().get(workspace_key)
    if entry is None:
        raise DomainError(
            "ARCHIVE_WORKSPACE_NOT_ALLOWED", "Archive workspace is not configured on this host", 422
        )
    return entry[1]


def archive_workspace_fingerprint(
    workspace_key: str,
    *,
    managed_folder_name: str | None = None,
    managed_root_fingerprint: str | None = None,
) -> str:
    import hashlib

    path = archive_workspace_path(
        workspace_key,
        managed_folder_name=managed_folder_name,
        managed_root_fingerprint=managed_root_fingerprint,
    )
    return hashlib.sha256(os.path.normcase(os.path.abspath(path)).encode("utf-8")).hexdigest()


def archive_execution_provider(
    scope: "ArchiveExecutionScope", *, readonly: bool = False
) -> "ArchiveExecutionProvider":
    from app.providers.project_archives.execution import HostArchiveExecutionProvider

    if not readonly and not get_settings().project_archive_write_enabled:
        raise DomainError("ARCHIVE_WRITE_DISABLED", "Host archive writes are disabled", 503)
    if (
        archive_workspace_fingerprint(
            scope.workspace_key,
            managed_folder_name=scope.managed_folder_name,
            managed_root_fingerprint=scope.managed_root_fingerprint,
        )
        != scope.workspace_fingerprint
    ):
        raise DomainError(
            "ARCHIVE_SCOPE_CHANGED",
            "Configured project path differs from the frozen execution scope",
            409,
        )
    root = archive_workspace_path(
        scope.workspace_key,
        managed_folder_name=scope.managed_folder_name,
        managed_root_fingerprint=scope.managed_root_fingerprint,
    )
    return HostArchiveExecutionProvider(root, scope, archive_remote(scope.repository.owner_login))


def code_file_provider(scope: ArchiveExecutionScope) -> CodeFileProvider:
    from app.providers.code_changes.local import LocalCodeFileProvider
    from app.providers.project_archives.catalog import LocalArchiveCatalogProvider

    if not get_settings().code_changes_enabled:
        raise DomainError(
            "CODE_CHANGES_DISABLED", "Bounded code changes are disabled on this host", 503
        )
    actual = archive_workspace_fingerprint(
        scope.workspace_key,
        managed_folder_name=scope.managed_folder_name,
        managed_root_fingerprint=scope.managed_root_fingerprint,
    )
    if actual != scope.workspace_fingerprint:
        raise DomainError("CODE_CHANGE_SCOPE_CHANGED", "Bound project root changed", 409)
    root = archive_workspace_path(
        scope.workspace_key,
        managed_folder_name=scope.managed_folder_name,
        managed_root_fingerprint=scope.managed_root_fingerprint,
    )
    project_id, repository = LocalArchiveCatalogProvider(root)._bound()
    if project_id != scope.local_project_id or repository != scope.repository:
        raise DomainError("CODE_CHANGE_SCOPE_CHANGED", "Local private project binding changed", 409)
    return LocalCodeFileProvider(root)


def provision_local() -> LocalProjectProvisionProvider:
    from app.providers.project_archives.provisioning import ManagedProjectProvisionProvider

    settings = get_settings()
    if not settings.project_provision_enabled or not settings.project_archive_write_enabled:
        raise DomainError(
            "PROVISION_DISABLED", "Project initialization is disabled on this host", 503
        )
    root = Path(settings.project_provision_managed_root)
    if not root.is_absolute():
        raise DomainError(
            "PROVISION_CONFIGURATION_INVALID",
            "Managed project root must be an absolute configured path",
            503,
        )
    return ManagedProjectProvisionProvider(root)


def project_source_workspace_provider(
    scope: ProjectSourceScope, *, readonly: bool = False
) -> ProjectSourceWorkspaceProvider:
    """Resolve only an already bound project under the owner-configured research root."""
    from app.domain.provisioning import managed_root_fingerprint

    settings = get_settings()
    if not readonly and not settings.project_source_workspaces_enabled:
        raise DomainError(
            "PROJECT_SOURCE_WORKSPACES_DISABLED", "Project source copying is disabled", 503
        )
    managed = Path(settings.project_provision_managed_root)
    root = archive_workspace_path(
        scope.workspace_key,
        managed_folder_name=scope.managed_folder_name,
        managed_root_fingerprint=scope.managed_root_fingerprint,
    )
    if (
        not managed.is_absolute()
        or managed_root_fingerprint(managed) != scope.source_root_fingerprint
        or managed_root_fingerprint(root) != scope.root_fingerprint
        or root == managed
        or not root.is_relative_to(managed)
    ):
        raise DomainError(
            "PROJECT_SOURCE_SCOPE_CHANGED", "Configured research project path changed", 409
        )
    from app.providers.project_sources import LocalProjectSourceWorkspaceProvider

    return LocalProjectSourceWorkspaceProvider(
        root,
        managed_root=managed,
        max_bytes=settings.repository_asset_max_bytes,
        max_files=settings.repository_asset_max_files,
    )


def baseline_asset_probe_provider() -> BaselineAssetProbeProvider:
    """Read only frozen files in owner-approved project source scopes."""
    from app.providers.baselines import LocalBaselineAssetProbeProvider
    from app.providers.project_sources import LocalProjectSourceWorkspaceProvider

    def resolve(scope: ProjectSourceScope) -> LocalProjectSourceWorkspaceProvider:
        adapter = project_source_workspace_provider(scope, readonly=True)
        if not isinstance(adapter, LocalProjectSourceWorkspaceProvider):
            raise DomainError(
                "BASELINE_PROBE_UNAVAILABLE", "This host has no readonly baseline file adapter", 503
            )
        return adapter

    return LocalBaselineAssetProbeProvider(resolve)


def baseline_run_provider() -> BaselineRunProvider:
    """Fixed host configuration; the service separately fences every execution grant."""
    from app.providers.baseline_runs import (
        LocalDockerBaselineRunProvider,
        UnconfiguredBaselineRunProvider,
    )
    from app.providers.project_sources import LocalProjectSourceWorkspaceProvider

    def resolve(scope: ProjectSourceScope) -> LocalProjectSourceWorkspaceProvider:
        adapter = project_source_workspace_provider(scope, readonly=True)
        if not isinstance(adapter, LocalProjectSourceWorkspaceProvider):
            raise DomainError(
                "BASELINE_RUN_SOURCE_UNAVAILABLE", "Local source adapter unavailable", 503
            )
        return adapter

    settings = get_settings()
    if not all(
        (
            settings.baseline_runner_docker_executable,
            settings.baseline_runner_docker_host,
            settings.baseline_runner_image_id,
            settings.baseline_runner_daemon_id,
        )
    ):
        return UnconfiguredBaselineRunProvider(resolve, reason="RUNNER_NOT_CONFIGURED")
    run_root = Path(settings.baseline_runner_root)
    if not run_root.is_absolute():
        run_root = ROOT_DIR / run_root
    return LocalDockerBaselineRunProvider(
        docker_executable=Path(settings.baseline_runner_docker_executable),
        docker_host=settings.baseline_runner_docker_host,
        image_id=settings.baseline_runner_image_id,
        daemon_id=settings.baseline_runner_daemon_id,
        run_root=run_root,
        source_resolver=resolve,
    )


def reference_manager() -> ReferenceManagerProvider:
    settings = get_settings()
    if settings.zotero_mode == "local":
        cache = ZoteroStyleCache(Path(settings.zotero_style_data_dir) if settings.zotero_style_data_dir else None) if settings.zotero_style_cache_enabled else None
        return ZoteroLocalAdapter(settings.zotero_local_api_url, venue_cache=cache)
    if settings.zotero_mode == "disabled":
        raise DomainError("CAPABILITY_UNAVAILABLE", "Zotero integration is disabled", 503)
    if settings.zotero_mode == "web":
        return ZoteroWebAdapter(
            api_key=settings.zotero_web_api_key,
            library_type=settings.zotero_web_library_type,
            library_id=settings.zotero_web_library_id,
        )
    raise DomainError("CONFIGURATION_ERROR", "Unknown Zotero mode", 503)


def bibliography_parser() -> BibliographyParser:
    return BibliographyFileAdapter()


@overload
def literature_provider(provider_key: Literal["crossref"] = "crossref") -> DoiLookupProvider: ...


@overload
def literature_provider(provider_key: Literal["arxiv"]) -> PaperIdLookupProvider: ...


@overload
def literature_provider(provider_key: str) -> LiteratureProvider: ...


def literature_provider(provider_key: str = "crossref") -> LiteratureProvider:
    if provider_key == "crossref":
        settings = get_settings()
        return CrossrefAdapter(contact_email=settings.crossref_contact_email.strip() or None)
    if provider_key == "arxiv":
        return ArxivAdapter()
    raise DomainError("CAPABILITY_UNAVAILABLE", "Unknown literature provider", 501)


def server_result_bundle_parser() -> ServerResultBundleParser:
    return ZipJSONServerResultBundleParser()


def server_receipt_authentication() -> ServerReceiptAuthentication:
    settings = get_settings()
    try:
        return HMACServerReceiptAuthentication(
            server_id=settings.server_result_server_id.strip() or None,
            key=settings.server_result_hmac_key
            if settings.server_result_hmac_key.get_secret_value()
            else None,
        )
    except ValueError:
        raise DomainError(
            "SERVER_RECEIPT_CONFIGURATION_INVALID",
            "Server receipt identity/key configuration is invalid",
            503,
        ) from None


def server_task_package_renderer() -> ServerTaskPackageRenderer:
    """Data-only file renderer; never executes command text or model code."""
    return MarkdownZipServerTaskPackageRenderer()


def literature_search_provider_keys() -> tuple[str, ...]:
    """Implemented search registrations only; no HTTP or model readiness probe."""
    return ("crossref",)


def literature_search_provider(provider_key: str = "crossref") -> SearchLiteratureProvider:
    """Search ports remain replaceable independently of DOI/ID lookup capabilities."""
    if provider_key == "crossref":
        settings = get_settings()
        return CrossrefAdapter(contact_email=settings.crossref_contact_email.strip() or None)
    raise DomainError("CAPABILITY_UNAVAILABLE", "Literature search provider is unavailable", 501)


def storage_provider(provider_key: str | None = None) -> StorageProvider:
    settings = get_settings()
    selected = settings.storage_provider if provider_key is None else provider_key
    if selected != "local":
        raise DomainError("CAPABILITY_UNAVAILABLE", "Storage provider is not implemented", 501)
    root = Path(settings.local_storage_root)
    if not root.is_absolute():
        root = ROOT_DIR / root
    try:
        return LocalStorageProvider(root)
    except OSError as exc:
        raise DomainError("STORAGE_UNAVAILABLE", "Local storage is unavailable", 503) from exc


def result_artifact_probe() -> ResultArtifactProbe:
    from app.providers.result_artifact_probe import LocalResultArtifactProbe

    return LocalResultArtifactProbe()


def ai_provider() -> AIProvider:
    settings = get_settings()
    if settings.ai_provider == "openai":
        return OpenAIResponsesProvider(
            api_key=settings.openai_api_key,
            model_key=settings.openai_model,
        )
    if settings.ai_provider == "codex":
        return CodexPaperProvider(
            model_key=settings.codex_model,
            timeout_seconds=settings.codex_paper_timeout_seconds,
            reasoning_effort=settings.codex_reasoning_effort,
        )
    if settings.ai_provider == "disabled":
        raise DomainError("CAPABILITY_UNAVAILABLE", "AI provider is disabled", 503)
    raise DomainError("CAPABILITY_UNAVAILABLE", "AI provider is not implemented", 501)


def ai_provider_descriptor() -> AIProviderDescriptor:
    settings = get_settings()
    if settings.ai_provider == "openai":
        configured = bool(settings.openai_api_key.strip() and settings.openai_model.strip())
        return AIProviderDescriptor(
            "openai",
            settings.openai_model or None,
            configured,
            configured,
            None if configured else "AI_NOT_CONFIGURED",
            None if configured else "Configure OPENAI_API_KEY and OPENAI_MODEL",
        )
    if settings.ai_provider == "codex":
        return CodexPaperProvider(
            model_key=settings.codex_model,
            timeout_seconds=settings.codex_paper_timeout_seconds,
            reasoning_effort=settings.codex_reasoning_effort,
        ).descriptor()
    return AIProviderDescriptor(
        settings.ai_provider,
        None,
        False,
        False,
        "AI_NOT_CONFIGURED",
        "Select an implemented paper AI provider",
    )


def codex_provider() -> CodexProvider:
    if get_settings().codex_provider == "openai_codex_sdk":
        return OpenAICodexSDKProvider()
    raise DomainError("CAPABILITY_UNAVAILABLE", "Codex provider is disabled or unknown", 503)


def codex_runtime_capabilities() -> CodexRuntimeCapabilities:
    return OpenAICodexSDKProvider().probe()


def reading_skill_provider() -> ReadingSkillProvider:
    from app.providers.analytical_skill import ZoteroAnalyticalWriterSkillProvider

    settings = get_settings()
    return ZoteroAnalyticalWriterSkillProvider(
        Path(settings.analytical_writer_skill_path), Path(settings.analytical_note_template_path)
    )


def pdf_visual_provider() -> PDFVisualProvider:
    return PDFiumVisualProvider()


def pdf_quote_provider() -> PDFQuoteProvider:
    from app.providers.pdf_quotes import PDFiumQuoteProvider

    return PDFiumQuoteProvider()


def _github_metadata_token() -> str | None:
    settings = get_settings()
    if settings.github_api_token:
        return settings.github_api_token
    if settings.github_gcm_account:
        from app.providers.project_archives.credentials import github_credential

        return github_credential(settings.github_gcm_account).get_secret_value()
    return None


def repository_provider(provider_key: str) -> OpenSourceRepositoryProvider:
    """Repository vendor credentials remain in the server-side composition root."""
    settings = get_settings()
    if provider_key == "github":
        from app.providers.repositories.github import GitHubRepositoryAdapter

        return GitHubRepositoryAdapter(token=_github_metadata_token())
    if provider_key == "huggingface":
        from app.providers.repositories.huggingface import HuggingFaceRepositoryAdapter

        return HuggingFaceRepositoryAdapter(token=settings.huggingface_api_token or None)
    raise DomainError("CAPABILITY_UNAVAILABLE", "Repository provider is not implemented", 501)


def repository_asset_provider(provider_key: str) -> RemoteAssetProvider:
    from app.providers.repository_assets import GitHubAssetProvider, HuggingFaceAssetProvider

    settings = get_settings()
    if provider_key == "github":
        return GitHubAssetProvider(
            token=_github_metadata_token(), max_files=settings.repository_asset_max_files
        )
    if provider_key == "huggingface":
        return HuggingFaceAssetProvider(
            token=settings.huggingface_api_token or None,
            max_files=settings.repository_asset_max_files,
        )
    raise DomainError("CAPABILITY_UNAVAILABLE", "Repository asset provider is not implemented", 501)


def repository_provider_catalog() -> tuple[RepositoryProviderDescriptor, ...]:
    settings = get_settings()
    return (
        RepositoryProviderDescriptor(
            "github",
            "GitHub",
            ("code",),
            True,
            True,
            True,
            bool(settings.github_api_token.strip() or settings.github_gcm_account.strip()),
        ),
        RepositoryProviderDescriptor(
            "huggingface",
            "Hugging Face",
            ("model", "dataset", "space"),
            True,
            True,
            True,
            bool(settings.huggingface_api_token.strip()),
        ),
    )


def note_output_provider(root: str | None = None) -> NoteOutputProvider:
    from app.providers.note_output import LocalNoteOutputProvider

    configured = Path(get_settings().analytical_note_root).absolute()
    if root is not None and Path(root).absolute() != configured:
        raise DomainError(
            "NOTE_OUTPUT_POLICY_CHANGED",
            "Approved note destination differs from current server configuration",
            409,
        )
    return LocalNoteOutputProvider(configured)


def generated_storage_deletion_root() -> str:
    configured = Path(get_settings().local_storage_root)
    return str((configured if configured.is_absolute() else ROOT_DIR / configured).absolute())


def generated_file_deletion_provider(
    root: str, kind: Literal["markdown", "storage"]
) -> GeneratedFileDeletionProvider:
    from app.providers.generated_file_deletion import FixedRootFileDeletionProvider

    configured = (
        Path(get_settings().analytical_note_root).absolute()
        if kind == "markdown"
        else Path(generated_storage_deletion_root())
    )
    if Path(root).absolute() != configured:
        raise DomainError(
            "NOTE_OUTPUT_POLICY_CHANGED",
            "Frozen file root differs from current server configuration",
            409,
        )
    return FixedRootFileDeletionProvider(configured, kind=kind)


def skill_discovery_provider() -> SkillDiscoveryProvider:
    from app.providers.skills.codex_discovery import CodexSkillDiscoveryProvider

    return CodexSkillDiscoveryProvider()


def research_planning_skill_provider() -> PlanningSkillProvider:
    from app.providers.planning_skills import InstalledPlanningSkillProvider

    configured = get_settings().research_planning_skills_root
    if not configured.strip():
        raise DomainError(
            "PLANNING_SKILLS_NOT_CONFIGURED", "Configure the explicit planning Skill root", 503
        )
    return InstalledPlanningSkillProvider(Path(configured))


def research_planning_provider() -> ResearchPlanningProvider:
    from app.providers.research_planning import CodexResearchPlanningProvider

    settings = get_settings()
    if settings.codex_provider != "openai_codex_sdk":
        raise DomainError(
            "PLANNING_PROVIDER_NOT_CONFIGURED", "Enable the configured Codex account provider", 503
        )
    return CodexResearchPlanningProvider(
        model_key=settings.codex_model,
        reasoning_effort=settings.codex_reasoning_effort,
    )


def skill_discovery_capability() -> tuple[str | None, bool, list[str]]:
    from app.providers.skills.codex_discovery import (
        LIMITATIONS,
        installed_sdk_version,
        runtime_installed,
    )

    return installed_sdk_version(), runtime_installed(), list(LIMITATIONS)


def writing_skill_provider() -> WritingSkillProvider:
    from app.providers.writing_skills import InstalledWritingSkillProvider

    configured = get_settings().writing_skills_root or get_settings().research_planning_skills_root
    if not configured.strip():
        raise DomainError(
            "WRITING_SKILLS_NOT_CONFIGURED", "Configure the actual writing Skill root", 503
        )
    ieee_configured = get_settings().writing_ieee_skills_root
    return InstalledWritingSkillProvider(
        Path(configured), ieee_root=Path(ieee_configured) if ieee_configured.strip() else None
    )


def manuscript_template_provider() -> ManuscriptTemplateProvider:
    from app.providers.manuscript_templates import LocalManuscriptTemplateProvider

    configured = get_settings().manuscript_templates_root
    if not configured.strip():
        raise DomainError(
            "MANUSCRIPT_TEMPLATES_NOT_CONFIGURED",
            "Configure the actual offline template catalog",
            503,
        )
    private = get_settings().manuscript_private_templates_root
    return LocalManuscriptTemplateProvider(
        Path(configured), private_root=Path(private) if private.strip() else None
    )


def manuscript_source_renderer() -> ManuscriptSourceRenderer:
    from app.providers.manuscripts import InternalManuscriptSourceRenderer

    return InternalManuscriptSourceRenderer()


def latex_compilation_provider() -> LatexCompilationProvider:
    from app.providers.latex.docker import DockerLatexCompilationProvider

    settings = get_settings()
    if not settings.latex_docker_executable.strip() or not settings.latex_compiler_image_id.strip():
        raise DomainError(
            "LATEX_COMPILER_NOT_CONFIGURED",
            "Configure the verified Docker executable and immutable document compiler image",
            503,
        )
    return DockerLatexCompilationProvider(
        docker_executable=Path(settings.latex_docker_executable),
        image_id=settings.latex_compiler_image_id,
        scratch_root=Path(settings.latex_scratch_root)
        if Path(settings.latex_scratch_root).is_absolute()
        else ROOT_DIR / settings.latex_scratch_root,
    )
