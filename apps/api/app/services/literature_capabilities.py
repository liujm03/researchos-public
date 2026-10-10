"""Owner-visible adapter metadata; this directory never probes external services."""

from dataclasses import dataclass
from typing import Literal

from app.core.config import Settings
from app.errors import DomainError
from app.providers import registry
from app.services.configuration import configuration_report

ProviderKind = Literal["literature", "reference_manager", "author_identity"]
ImplementationStatus = Literal["implemented", "planned"]
ConfigurationStatus = Literal["configured", "disabled", "missing", "invalid", "not_implemented"]


@dataclass(frozen=True)
class ProviderDescriptor:
    provider_key: str
    label: str
    kind: ProviderKind
    implementation_status: ImplementationStatus
    configuration_status: ConfigurationStatus
    connectivity_status: Literal["not_tested"]
    capabilities: list[str]
    entrypoint: str | None
    description: str


_PLANNED: tuple[tuple[str, str, ProviderKind, str], ...] = (
    ("openalex", "OpenAlex", "literature", "开放文献搜索与候选导入尚在开发计划中。"),
    ("semantic_scholar", "Semantic Scholar", "literature", "引用、被引和相关论文接口尚在开发计划中。"),
    ("ieee", "IEEE Xplore", "literature", "官方授权 API 适配尚未实现。"),
    ("scopus", "Scopus", "literature", "仅计划在授权和官方 API 条件允许时接入。"),
    ("web_of_science", "Web of Science", "literature", "仅计划在授权和官方 API 条件允许时接入。"),
    ("orcid", "ORCID", "author_identity", "作者身份关联接口尚在开发计划中。"),
)
_REFERENCE_CAPABILITIES = (
    "search_items", "get_item", "list_collections", "list_attachments",
    "open_attachment", "get_indexed_fulltext", "list_updated_items",
)


def provider_directory(settings: Settings) -> list[ProviderDescriptor]:
    statuses = {check.key: check.status for check in configuration_report(settings).checks}
    result: list[ProviderDescriptor] = []
    for key, label, entrypoint, description in (
        ("crossref", "Crossref", "/papers/import/doi", "owner 主动发送 DOI，或在课题文献推荐中预览并确认分页检索；不自动查询、分析或下载 PDF。"),
        ("arxiv", "arXiv", "/papers/import/arxiv", "owner 主动发送论文 ID，预览具体版本后确认；不自动下载 PDF。"),
    ):
        status: ConfigurationStatus = statuses.get(key, "configured")
        try:
            provider = registry.literature_provider(key)
            if provider.provider_key != key:
                raise DomainError("CONFIGURATION_ERROR", "Provider identity mismatch", 503)
            capabilities = sorted(provider.capabilities) if status == "configured" else []
            implementation: ImplementationStatus = "implemented"
        except DomainError as exc:
            if exc.code == "CAPABILITY_UNAVAILABLE":
                implementation, status, capabilities = "planned", "not_implemented", []
            else:
                implementation, status, capabilities = "implemented", "invalid", []
        result.append(ProviderDescriptor(
            key, label, "literature", implementation, status, "not_tested", capabilities,
            entrypoint if implementation == "implemented" else None, description,
        ))

    zotero_status = statuses["zotero"]
    # These methods belong to the existing ReferenceManagerProvider, not the DOI port.
    result.append(ProviderDescriptor(
        "zotero", "Zotero", "reference_manager", "implemented", zotero_status, "not_tested",
        list(_REFERENCE_CAPABILITIES) if zotero_status == "configured" else [],
        "/integrations/zotero", "只读参考管理器接口；配置状态不证明本机或远端已连接。自动同步由 owner 单独开启。",
    ))
    result.extend(ProviderDescriptor(
        key, label, kind, "planned", "not_implemented", "not_tested", [], None, description,
    ) for key, label, kind, description in _PLANNED)
    return result
