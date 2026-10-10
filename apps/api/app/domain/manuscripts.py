"""Editable internal manuscript source ports; never execute research or TeX."""

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from app.domain.manuscript_templates import FrozenManuscriptTemplate


@dataclass(frozen=True)
class ManuscriptSourceFile:
    path: str
    content: bytes
    sha256: str


@dataclass(frozen=True)
class ManuscriptSourceRequest:
    revision: dict[str, Any]
    evidence_snapshots: tuple[dict[str, Any], ...]
    figures: tuple[ManuscriptSourceFile, ...] = ()
    figure_provenance: tuple[dict[str, Any], ...] = ()
    template: FrozenManuscriptTemplate | None = None
    variant: str | None = None
    font_profile: Literal["ENGLISH", "CJK_COMPAT"] = "ENGLISH"
    table_provenance: tuple[dict[str, Any], ...] = ()
    tex_overrides: tuple[ManuscriptSourceFile, ...] = ()
    submission_id: str = ""


@dataclass(frozen=True)
class ManuscriptSourceProject:
    files: tuple[ManuscriptSourceFile, ...]
    source_sha256: str
    warnings: tuple[str, ...]
    template: str = "RESEARCHOS_INTERNAL_ARTICLE_V1"
    engine: str = "xelatex"
    compiled: bool = False


class ManuscriptSourceRenderer(Protocol):
    def render(self, request: ManuscriptSourceRequest) -> ManuscriptSourceProject: ...

    def pack(self, project: ManuscriptSourceProject, *, build_outputs: bool = False) -> bytes: ...

    def compile_files(
        self, project: ManuscriptSourceProject
    ) -> tuple[ManuscriptSourceFile, ...]: ...
