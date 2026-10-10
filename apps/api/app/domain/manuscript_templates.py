"""Frozen venue-template resources; selection is not venue or submission approval."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ManuscriptTemplateVariant:
    key: str
    options: tuple[str, ...]
    anonymous: bool
    note: str


@dataclass(frozen=True)
class ManuscriptTemplateDescriptor:
    key: str
    family: str
    version: str
    official_url: str
    license: str
    resource_status: str
    variants: tuple[ManuscriptTemplateVariant, ...]
    manifest_sha256: str
    use_scope: str = "OPEN_TEMPLATE_RESOURCE"
    target_year: int | None = None
    permission_purpose: str = ""


@dataclass(frozen=True)
class ManuscriptTemplateFile:
    path: str
    content: bytes
    sha256: str


@dataclass(frozen=True)
class FrozenManuscriptTemplate:
    descriptor: ManuscriptTemplateDescriptor
    files: tuple[ManuscriptTemplateFile, ...]
    private_use_approved: bool = False


class ManuscriptTemplateProvider(Protocol):
    def descriptors(self) -> tuple[ManuscriptTemplateDescriptor, ...]: ...
    def load_resources(
        self, key: str, expected_manifest_sha256: str, *, private_use_approved: bool = False
    ) -> FrozenManuscriptTemplate: ...
