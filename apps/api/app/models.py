import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models_analytical import (
    CanonicalAnalyticalNote as CanonicalAnalyticalNote,
)
from app.models_analytical import (
    PaperReadingApproval as PaperReadingApproval,
)
from app.models_analytical import (
    PaperReadingApprovalPlan as PaperReadingApprovalPlan,
)
from app.models_archive_jobs import ProjectArchiveJob as ProjectArchiveJob
from app.models_archive_jobs import ProjectArchiveJobEvent as ProjectArchiveJobEvent
from app.models_baseline_runs import BaselineRunArtifact as BaselineRunArtifact
from app.models_baseline_runs import BaselineRunAttempt as BaselineRunAttempt
from app.models_baseline_runs import BaselineRunJob as BaselineRunJob
from app.models_baseline_runs import BaselineRunPermit as BaselineRunPermit
from app.models_baseline_runs import BaselineRunPlan as BaselineRunPlan
from app.models_baseline_runs import BaselineRunPlanInput as BaselineRunPlanInput
from app.models_baselines import Baseline as Baseline
from app.models_baselines import BaselineAsset as BaselineAsset
from app.models_baselines import BaselineAssetObservation as BaselineAssetObservation
from app.models_baselines import BaselineDatasetBinding as BaselineDatasetBinding
from app.models_baselines import BaselineMaterialCheck as BaselineMaterialCheck
from app.models_baselines import BaselineVersion as BaselineVersion
from app.models_claims import ClaimEvidence as ClaimEvidence
from app.models_claims import ClaimReview as ClaimReview
from app.models_claims import ClaimRevision as ClaimRevision
from app.models_claims import ResearchClaim as ResearchClaim
from app.models_code_changes import CodeChangeApplyAttempt as CodeChangeApplyAttempt
from app.models_code_changes import CodeChangeInputFile as CodeChangeInputFile
from app.models_code_changes import CodeChangePlan as CodeChangePlan
from app.models_code_changes import CodeChangeProposal as CodeChangeProposal
from app.models_code_changes import CodeChangeProposalFile as CodeChangeProposalFile
from app.models_evidence_bundles import EvidenceBundle as EvidenceBundle
from app.models_evidence_bundles import EvidenceBundleClaim as EvidenceBundleClaim
from app.models_evidence_bundles import EvidenceBundleFile as EvidenceBundleFile
from app.models_evidence_bundles import EvidenceBundleSaveAttempt as EvidenceBundleSaveAttempt
from app.models_experiments import (
    CodeRepository as CodeRepository,
)
from app.models_experiments import (
    Dataset as Dataset,
)
from app.models_experiments import (
    DatasetClass as DatasetClass,
)
from app.models_experiments import (
    DatasetLocation as DatasetLocation,
)
from app.models_experiments import (
    DatasetModality as DatasetModality,
)
from app.models_experiments import (
    DatasetSplit as DatasetSplit,
)
from app.models_experiments import (
    DatasetVersion as DatasetVersion,
)
from app.models_experiments import (
    Experiment as Experiment,
)
from app.models_experiments import (
    ExperimentArtifact as ExperimentArtifact,
)
from app.models_experiments import (
    ExperimentMetric as ExperimentMetric,
)
from app.models_experiments import (
    ExperimentParameter as ExperimentParameter,
)
from app.models_experiments import (
    ExperimentRun as ExperimentRun,
)
from app.models_experiments import (
    ExperimentRunDataset as ExperimentRunDataset,
)
from app.models_experiments import (
    ExperimentStatusEvent as ExperimentStatusEvent,
)
from app.models_experiments import (
    Hypothesis as Hypothesis,
)
from app.models_experiments import (
    MetricDefinition as MetricDefinition,
)
from app.models_experiments import (
    Modality as Modality,
)
from app.models_experiments import (
    Model as Model,
)
from app.models_experiments import (
    ModelComponent as ModelComponent,
)
from app.models_experiments import (
    ModelModality as ModelModality,
)
from app.models_experiments import (
    ModelVersion as ModelVersion,
)
from app.models_ideas import IdeaBriefAction as IdeaBriefAction
from app.models_ideas import IdeaRevision as IdeaRevision
from app.models_ideas import IdeaRevisionTag as IdeaRevisionTag
from app.models_ideas import IdeaSource as IdeaSource
from app.models_ideas import IdeaTaskAction as IdeaTaskAction
from app.models_ideas import ResearchBriefIdeaSource as ResearchBriefIdeaSource
from app.models_ideas import ResearchIdea as ResearchIdea
from app.models_literature_recommendations import (
    LiteratureRecommendationAuthor as LiteratureRecommendationAuthor,
)
from app.models_literature_recommendations import (
    LiteratureRecommendationBatch as LiteratureRecommendationBatch,
)
from app.models_literature_recommendations import (
    LiteratureRecommendationCandidate as LiteratureRecommendationCandidate,
)
from app.models_literature_recommendations import (
    LiteratureRecommendationTerm as LiteratureRecommendationTerm,
)
from app.models_literature_recommendations import (
    LiteratureRecommendationVenue as LiteratureRecommendationVenue,
)
from app.models_manuscript_builds import ManuscriptBuild as ManuscriptBuild
from app.models_manuscript_builds import ManuscriptBuildAttempt as ManuscriptBuildAttempt
from app.models_manuscript_builds import ManuscriptBuildFigure as ManuscriptBuildFigure
from app.models_manuscript_builds import ManuscriptBuildFile as ManuscriptBuildFile
from app.models_manuscript_builds import ManuscriptBuildMetric as ManuscriptBuildMetric
from app.models_manuscript_builds import ManuscriptBuildOperation as ManuscriptBuildOperation
from app.models_manuscript_builds import ManuscriptBuildTable as ManuscriptBuildTable
from app.models_note_deletion import NoteDeletionFile as NoteDeletionFile
from app.models_note_deletion import NoteDeletionMember as NoteDeletionMember
from app.models_note_deletion import NoteDeletionUsageReceipt as NoteDeletionUsageReceipt
from app.models_note_deletion import NotePermanentDeletion as NotePermanentDeletion
from app.models_note_projects import NoteProject as NoteProject
from app.models_note_projects import NoteProjectClassification as NoteProjectClassification
from app.models_note_trash import GeneratedFileSettings as GeneratedFileSettings
from app.models_note_trash import NoteTrashEntry as NoteTrashEntry
from app.models_note_trash import NoteTrashMember as NoteTrashMember
from app.models_note_trash import NoteTrashOperation as NoteTrashOperation
from app.models_pdf_annotations import PdfAnnotation as PdfAnnotation
from app.models_pdf_annotations import PdfAnnotationGeometry as PdfAnnotationGeometry
from app.models_pdf_annotations import PdfAnnotationPoint as PdfAnnotationPoint
from app.models_planning_brief_proposals import (
    PlanningBriefAdoptionReceipt as PlanningBriefAdoptionReceipt,
)
from app.models_planning_brief_proposals import PlanningBriefProposal as PlanningBriefProposal
from app.models_planning_brief_proposals import (
    PlanningBriefProposalSection as PlanningBriefProposalSection,
)
from app.models_project_archives import ProjectArchiveBinding as ProjectArchiveBinding
from app.models_project_archives import ProjectArchiveFile as ProjectArchiveFile
from app.models_project_archives import ProjectArchiveVersion as ProjectArchiveVersion
from app.models_project_sources import ProjectPathBinding as ProjectPathBinding
from app.models_project_sources import ProjectSourceFile as ProjectSourceFile
from app.models_project_sources import ProjectSourceJob as ProjectSourceJob
from app.models_project_sources import ProjectSourcePlan as ProjectSourcePlan
from app.models_project_sources import ProjectSourcePlanFile as ProjectSourcePlanFile
from app.models_provisioning import ProjectProvisionEvent as ProjectProvisionEvent
from app.models_provisioning import ProjectProvisionJob as ProjectProvisionJob
from app.models_provisioning import ProjectProvisionPlan as ProjectProvisionPlan
from app.models_publications import Publication as Publication
from app.models_publications import PublicationBinding as PublicationBinding
from app.models_publications import PublicationReview as PublicationReview
from app.models_publications import PublicationRevision as PublicationRevision
from app.models_publications import PublicationSection as PublicationSection
from app.models_publications import PublicationSource as PublicationSource
from app.models_reading_bindings import PaperReadingSkillFile as PaperReadingSkillFile
from app.models_repositories import RepositoryBinding as RepositoryBinding
from app.models_repositories import RepositoryImportPreview as RepositoryImportPreview
from app.models_repositories import RepositorySourceSnapshot as RepositorySourceSnapshot
from app.models_repository_assets import RepositoryAssetFile as RepositoryAssetFile
from app.models_repository_assets import RepositoryAssetJob as RepositoryAssetJob
from app.models_repository_assets import RepositoryAssetPlan as RepositoryAssetPlan
from app.models_repository_assets import RepositoryAssetPlanFile as RepositoryAssetPlanFile
from app.models_repository_assets import RepositoryAssetSnapshot as RepositoryAssetSnapshot
from app.models_reproduction_sources import (
    PaperReproductionCanonicalSource as PaperReproductionCanonicalSource,
)
from app.models_reproduction_sources import (
    PaperReproductionNoteExcerpt as PaperReproductionNoteExcerpt,
)
from app.models_research_briefs import ResearchBrief as ResearchBrief
from app.models_research_briefs import ResearchBriefCanonicalSource as ResearchBriefCanonicalSource
from app.models_research_briefs import ResearchBriefEvidence as ResearchBriefEvidence
from app.models_research_briefs import ResearchBriefReview as ResearchBriefReview
from app.models_research_briefs import ResearchBriefSection as ResearchBriefSection
from app.models_research_planning import ResearchExecutionPermit as ResearchExecutionPermit
from app.models_research_planning import ResearchPlanningAttempt as ResearchPlanningAttempt
from app.models_research_planning import ResearchPlanningJob as ResearchPlanningJob
from app.models_research_planning import ResearchPlanningResult as ResearchPlanningResult
from app.models_research_planning import ResearchStageGrant as ResearchStageGrant
from app.models_research_planning import ResearchStageSkillFile as ResearchStageSkillFile
from app.models_server_results import ServerResult as ServerResult
from app.models_server_results import ServerResultArtifact as ServerResultArtifact
from app.models_server_results import ServerResultBriefLink as ServerResultBriefLink
from app.models_server_results import ServerResultMetric as ServerResultMetric
from app.models_server_results import ServerResultReview as ServerResultReview
from app.models_server_results import ServerResultTaskAction as ServerResultTaskAction
from app.models_server_task_packages import ServerTaskPackage as ServerTaskPackage
from app.models_server_task_packages import ServerTaskPackageAsset as ServerTaskPackageAsset
from app.models_server_task_packages import (
    ServerTaskPackageExpectedArtifact as ServerTaskPackageExpectedArtifact,
)
from app.models_server_task_packages import ServerTaskPackageFile as ServerTaskPackageFile
from app.models_server_task_packages import (
    ServerTaskPackageSaveAttempt as ServerTaskPackageSaveAttempt,
)
from app.models_server_task_packages import ServerTaskPackageTask as ServerTaskPackageTask
from app.models_venue_ratings import VenueAssessment as VenueAssessment
from app.models_writing import WritingCandidate as WritingCandidate
from app.models_writing import WritingOperation as WritingOperation
from app.models_writing import WritingPlan as WritingPlan
from app.models_writing import WritingSkillFile as WritingSkillFile


def new_id() -> uuid.UUID:
    return uuid.uuid4()


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("single_owner_key = 1", name="ck_users_single_owner"),
        UniqueConstraint("single_owner_key", name="uq_users_single_owner_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    single_owner_key: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str] = mapped_column(String(120))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai")
    password_hash: Mapped[str] = mapped_column(String(512))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UserSession(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CodexTask(Base):
    __tablename__ = "codex_tasks"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_codex_task_idempotency"),
        UniqueConstraint("id", "user_id", name="uq_codex_task_owner"),
        Index("ix_codex_tasks_owner_status", "user_id", "status"),
        CheckConstraint(
            "budget_mode IN ('LOCAL_LIMITS','PROVIDER_QUOTA') AND (budget_mode<>'PROVIDER_QUOTA' OR max_tokens IS NULL)",
            name="ck_codex_task_budget_mode",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    related_project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("research_projects.id")
    )
    related_research_question_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("research_questions.id")
    )
    title: Mapped[str] = mapped_column(String(240))
    prompt: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(32))
    mode: Mapped[str] = mapped_column(String(32))
    workspace_id: Mapped[str] = mapped_column(String(80))
    workspace_path_snapshot: Mapped[str] = mapped_column(String(2048))
    provider_key: Mapped[str] = mapped_column(String(64), default="openai_codex_sdk")
    model_key: Mapped[str] = mapped_column(String(128), default="default")
    reasoning_effort: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32), default="DRAFT")
    event_sequence: Mapped[int] = mapped_column(Integer, default=0)
    worker_lease_id: Mapped[str | None] = mapped_column(String(64))
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    request_sha256: Mapped[str] = mapped_column(String(64))
    codex_thread_id: Mapped[str | None] = mapped_column(String(128))
    codex_turn_id: Mapped[str | None] = mapped_column(String(128))
    base_commit: Mapped[str | None] = mapped_column(String(64))
    diff_summary: Mapped[str | None] = mapped_column(Text)
    diff_patch: Mapped[str | None] = mapped_column(Text)
    diff_truncated: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    final_response: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    max_tokens: Mapped[int | None] = mapped_column(Integer)
    budget_mode: Mapped[str] = mapped_column(
        String(24), default="LOCAL_LIMITS", server_default="LOCAL_LIMITS"
    )
    token_budget_exceeded: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CodexTaskEvent(Base):
    __tablename__ = "codex_task_events"
    __table_args__ = (UniqueConstraint("task_id", "sequence", name="uq_codex_event_sequence"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("codex_tasks.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(80))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PaperReproductionContext(Base):
    __tablename__ = "paper_reproduction_contexts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "user_id"],
            ["codex_tasks.id", "codex_tasks.user_id"],
            name="fk_reproduction_task_owner",
        ),
        UniqueConstraint("task_id", "user_id", name="uq_reproduction_context_owner"),
        UniqueConstraint(
            "task_id", "paper_id", "user_id", name="uq_reproduction_context_paper_owner"
        ),
        UniqueConstraint("task_id", "parsed_document_id", name="uq_reproduction_context_document"),
        CheckConstraint("stage IN ('PLAN','IMPLEMENT_CODE')", name="ck_reproduction_stage"),
        CheckConstraint(
            "source_scope IN ('METADATA_ONLY','ABSTRACT_ONLY','FULL_TEXT','DERIVED_NOTE')",
            name="ck_reproduction_scope",
        ),
        CheckConstraint(
            "stage <> 'IMPLEMENT_CODE' OR (context_version='paper-reproduction-v1' AND source_scope = 'FULL_TEXT' AND parsed_document_id IS NOT NULL) OR (context_version='canonical-note-reproduction-v2' AND source_scope='DERIVED_NOTE' AND parsed_document_id IS NULL)",
            name="ck_reproduction_implementation_source",
        ),
        CheckConstraint("paper_metadata_version > 0", name="ck_reproduction_metadata_version"),
        CheckConstraint(
            "(context_version='paper-reproduction-v1' AND length(context_text)<=30000) OR (context_version='canonical-note-reproduction-v2' AND length(context_text)<=524288)",
            name="ck_reproduction_context_size",
        ),
        CheckConstraint(
            "(context_version='paper-reproduction-v1' AND source_scope<>'DERIVED_NOTE') OR (context_version='canonical-note-reproduction-v2' AND source_scope='DERIVED_NOTE' AND parsed_document_id IS NULL AND note_id IS NULL)",
            name="ck_reproduction_context_kind",
        ),
    )

    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    paper_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("papers.id"), index=True)
    paper_title: Mapped[str] = mapped_column(String(2000))
    paper_metadata_version: Mapped[int] = mapped_column(Integer)
    stage: Mapped[str] = mapped_column(String(24))
    source_scope: Mapped[str] = mapped_column(String(24))
    goal: Mapped[str] = mapped_column(Text)
    instructions: Mapped[str] = mapped_column(Text, default="", server_default="")
    note_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("paper_research_notes.id"))
    note_revision: Mapped[int | None] = mapped_column(Integer)
    note_review_status: Mapped[str | None] = mapped_column(String(24))
    parsed_document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("parsed_documents.id")
    )
    pdf_sha256: Mapped[str | None] = mapped_column(String(64))
    parser_name: Mapped[str | None] = mapped_column(String(80))
    parser_version: Mapped[str | None] = mapped_column(String(80))
    parser_status: Mapped[str | None] = mapped_column(String(24))
    context_text: Mapped[str] = mapped_column(Text)
    context_sha256: Mapped[str] = mapped_column(String(64))
    context_version: Mapped[str] = mapped_column(
        String(64), default="paper-reproduction-v1", server_default="paper-reproduction-v1"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PaperReproductionSourceSection(Base):
    __tablename__ = "paper_reproduction_source_sections"
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "user_id"],
            ["paper_reproduction_contexts.task_id", "paper_reproduction_contexts.user_id"],
            name="fk_reproduction_section_owner",
        ),
        ForeignKeyConstraint(
            ["task_id", "parsed_document_id"],
            [
                "paper_reproduction_contexts.task_id",
                "paper_reproduction_contexts.parsed_document_id",
            ],
            name="fk_reproduction_section_context_document",
        ),
        ForeignKeyConstraint(
            ["parsed_document_id", "section_id"],
            ["parsed_sections.document_id", "parsed_sections.id"],
            name="fk_reproduction_selected_document",
        ),
        UniqueConstraint("task_id", "position", name="uq_reproduction_section_order"),
        CheckConstraint("position >= 0", name="ck_reproduction_section_position"),
    )

    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    section_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    parsed_document_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    position: Mapped[int] = mapped_column(Integer)


class ResearchEntity(Base):
    __tablename__ = "research_entities"
    __table_args__ = (UniqueConstraint("id", "user_id", name="uq_research_entity_owner"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ResearchProject(Base):
    __tablename__ = "research_projects"
    __table_args__ = (
        UniqueConstraint("user_id", "slug"),
        UniqueConstraint("id", "user_id", name="uq_research_project_owner"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("research_entities.id"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    parent_project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("research_projects.id")
    )
    name: Mapped[str] = mapped_column(String(240))
    slug: Mapped[str] = mapped_column(String(260))
    summary: Mapped[str | None] = mapped_column(Text)
    problem: Mapped[str | None] = mapped_column(Text)
    motivation: Mapped[str | None] = mapped_column(Text)
    research_gap: Mapped[str | None] = mapped_column(Text)
    method_overview: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="active")
    pipeline_stage: Mapped[str] = mapped_column(String(32), default="idea")
    started_on: Mapped[date | None] = mapped_column(Date)
    target_on: Mapped[date | None] = mapped_column(Date)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ResearchQuestion(Base):
    __tablename__ = "research_questions"
    __table_args__ = (UniqueConstraint("id", "project_id", name="uq_research_question_project"),)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("research_entities.id"), primary_key=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("research_projects.id"), index=True
    )
    parent_question_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("research_questions.id")
    )
    question: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="open")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Milestone(Base):
    __tablename__ = "milestones"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("research_entities.id"), primary_key=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("research_projects.id"), index=True
    )
    title: Mapped[str] = mapped_column(String(240))
    description: Mapped[str | None] = mapped_column(Text)
    due_on: Mapped[date | None] = mapped_column(Date)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24), default="planned")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Venue(Base):
    __tablename__ = "venues"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(320), unique=True)
    type: Mapped[str] = mapped_column(String(24), default="other")
    issn: Mapped[str | None] = mapped_column(String(32))
    publisher: Mapped[str | None] = mapped_column(String(240))


class Paper(Base):
    __tablename__ = "papers"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_paper_owner"),
        Index("ix_papers_user_doi", "user_id", "normalized_doi", unique=True),
        Index("ix_papers_user_arxiv", "user_id", "arxiv_id", unique=True),
        Index("ix_papers_user_normalized_arxiv", "user_id", "normalized_arxiv_id", unique=True),
        Index("ix_papers_user_pmid", "user_id", "pmid", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("research_entities.id"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(600))
    normalized_title: Mapped[str] = mapped_column(String(600), index=True)
    year: Mapped[int | None] = mapped_column(Integer)
    venue_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("venues.id"))
    doi: Mapped[str | None] = mapped_column(String(300))
    normalized_doi: Mapped[str | None] = mapped_column(String(300))
    arxiv_id: Mapped[str | None] = mapped_column(String(100))
    normalized_arxiv_id: Mapped[str | None] = mapped_column(String(100))
    pmid: Mapped[str | None] = mapped_column(String(40))
    abstract: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(2000))
    pdf_url: Mapped[str | None] = mapped_column(String(2000))
    citation_count: Mapped[int | None] = mapped_column(Integer)
    reference_count: Mapped[int | None] = mapped_column(Integer)
    counts_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PaperSource(Base):
    __tablename__ = "paper_sources"
    __table_args__ = (
        UniqueConstraint("user_id", "provider_key", "provider_id", name="uq_paper_source_identity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    paper_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("papers.id"), index=True)
    provider_key: Mapped[str] = mapped_column(String(64))
    provider_id: Mapped[str] = mapped_column(String(320))
    source_version: Mapped[int | None] = mapped_column(Integer)
    source_url: Mapped[str | None] = mapped_column(String(2000))
    payload_sha256: Mapped[str | None] = mapped_column(String(64))
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Author(Base):
    __tablename__ = "authors"
    __table_args__ = (Index("ix_authors_user_orcid", "user_id", "orcid", unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("research_entities.id"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    display_name: Mapped[str] = mapped_column(String(240))
    orcid: Mapped[str | None] = mapped_column(String(40))


class PaperAuthor(Base):
    __tablename__ = "paper_authors"
    __table_args__ = (UniqueConstraint("paper_id", "position"),)

    paper_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("papers.id"), primary_key=True)
    author_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("authors.id"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer)
    is_corresponding: Mapped[bool] = mapped_column(default=False)


class PaperReading(Base):
    __tablename__ = "paper_readings"
    __table_args__ = (
        UniqueConstraint("paper_id", "user_id"),
        CheckConstraint("importance IS NULL OR importance BETWEEN 1 AND 5"),
        CheckConstraint("relevance IS NULL OR relevance BETWEEN 0 AND 100"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    paper_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("papers.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    reading_status: Mapped[str] = mapped_column(String(24), default="unread")
    importance: Mapped[int | None] = mapped_column(Integer)
    relevance: Mapped[int | None] = mapped_column(Integer)
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PaperNote(Base):
    __tablename__ = "paper_notes"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("research_entities.id"), primary_key=True
    )
    paper_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("papers.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    title: Mapped[str | None] = mapped_column(String(240))
    body_markdown: Mapped[str] = mapped_column(Text)
    note_type: Mapped[str] = mapped_column(String(32), default="general")
    source_locator: Mapped[str | None] = mapped_column(String(240))
    is_ai_draft: Mapped[bool] = mapped_column(default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProjectPaper(Base):
    __tablename__ = "project_papers"

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("research_projects.id"), primary_key=True
    )
    paper_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("papers.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(32), primary_key=True, default="related")
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("user_id", "normalized_name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(80))
    normalized_name: Mapped[str] = mapped_column(String(80))


class EntityTag(Base):
    __tablename__ = "entity_tags"

    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("research_entities.id"), primary_key=True
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tags.id"), primary_key=True)


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_task_owner"),
        UniqueConstraint("id", "project_id", "user_id", name="uq_task_project_owner"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("research_entities.id"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("research_projects.id"))
    parent_task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("tasks.id"))
    title: Mapped[str] = mapped_column(String(320))
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(24), default="research")
    priority: Mapped[str] = mapped_column(String(16), default="medium")
    status: Mapped[str] = mapped_column(String(24), default="todo")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    estimated_minutes: Mapped[int | None] = mapped_column(Integer)
    actual_minutes: Mapped[int | None] = mapped_column(Integer)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TaskDependency(Base):
    __tablename__ = "task_dependencies"
    __table_args__ = (CheckConstraint("task_id <> depends_on_task_id"),)

    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tasks.id"), primary_key=True)
    depends_on_task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tasks.id"), primary_key=True
    )


class ResearchJournal(Base):
    __tablename__ = "research_journals"
    __table_args__ = (UniqueConstraint("user_id", "journal_date"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    journal_date: Mapped[date] = mapped_column(Date)
    completed: Mapped[str | None] = mapped_column(Text)
    papers_read: Mapped[str | None] = mapped_column(Text)
    experiments: Mapped[str | None] = mapped_column(Text)
    learning: Mapped[str | None] = mapped_column(Text)
    problems: Mapped[str | None] = mapped_column(Text)
    new_ideas: Mapped[str | None] = mapped_column(Text)
    tomorrow_plan: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TimeEntry(Base):
    __tablename__ = "time_entries"
    __table_args__ = (CheckConstraint("ended_at > started_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("research_projects.id"))
    task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("tasks.id"))
    category: Mapped[str] = mapped_column(String(24))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)


class ZoteroSourceItem(Base):
    __tablename__ = "zotero_source_items"
    __table_args__ = (
        UniqueConstraint(
            "server_id", "library_type", "library_id", "item_key", name="uq_zotero_item_identity"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    paper_source_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("paper_sources.id"), unique=True
    )
    server_id: Mapped[str] = mapped_column(String(100))
    library_type: Mapped[str] = mapped_column(String(16), default="user")
    library_id: Mapped[str] = mapped_column(String(80), default="0")
    item_key: Mapped[str] = mapped_column(String(16))
    item_version: Mapped[int] = mapped_column(Integer)
    sync_status: Mapped[str] = mapped_column(String(24), default="SYNCED")
    attachment_status: Mapped[str] = mapped_column(String(24), default="UNKNOWN")
    analysis_status: Mapped[str] = mapped_column(String(24), default="NOT_ANALYZED")
    venue_fields: Mapped[dict[str, str] | None] = mapped_column(JSON)
    venue_fields_sha256: Mapped[str | None] = mapped_column(String(64))
    venue_fields_version: Mapped[int | None] = mapped_column(BigInteger)
    venue_fields_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ZoteroCollection(Base):
    __tablename__ = "zotero_collections"
    __table_args__ = (
        UniqueConstraint(
            "server_id", "library_type", "library_id", "collection_key", name="uq_zotero_collection"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    server_id: Mapped[str] = mapped_column(String(100))
    library_type: Mapped[str] = mapped_column(String(16))
    library_id: Mapped[str] = mapped_column(String(80))
    collection_key: Mapped[str] = mapped_column(String(16))
    parent_collection_key: Mapped[str | None] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(320))
    source_version: Mapped[int | None] = mapped_column(Integer)
    last_synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ZoteroItemCollection(Base):
    __tablename__ = "zotero_item_collections"

    source_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("zotero_source_items.id"), primary_key=True
    )
    collection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("zotero_collections.id"), primary_key=True
    )


class ZoteroSyncCursor(Base):
    __tablename__ = "zotero_sync_cursors"
    __table_args__ = (UniqueConstraint("user_id", "server_id", "library_type", "library_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    server_id: Mapped[str] = mapped_column(String(100))
    library_type: Mapped[str] = mapped_column(String(16))
    library_id: Mapped[str] = mapped_column(String(80))
    cursor: Mapped[str | None] = mapped_column(String(120))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class SyncJob(Base):
    __tablename__ = "sync_jobs"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_sync_job_idempotency"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    provider_key: Mapped[str] = mapped_column(String(64))
    job_type: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(24), default="QUEUED")
    cursor_before: Mapped[str | None] = mapped_column(String(120))
    cursor_after: Mapped[str | None] = mapped_column(String(120))
    scanned_count: Mapped[int] = mapped_column(Integer, default=0)
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ZoteroManualSyncJob(Base):
    __tablename__ = "zotero_manual_sync_jobs"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_zotero_manual_sync_key"),
        UniqueConstraint("id", "user_id", name="uq_zotero_manual_sync_owner"),
        Index("ix_zotero_manual_sync_queue", "status", "queued_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    provider_key: Mapped[str] = mapped_column(String(64))
    server_id: Mapped[str] = mapped_column(String(100))
    library_type: Mapped[str] = mapped_column(String(16))
    library_id: Mapped[str] = mapped_column(String(80))
    item_key: Mapped[str | None] = mapped_column(String(80))
    job_type: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(24), default="QUEUED")
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    cursor_before: Mapped[str | None] = mapped_column(String(120))
    cursor_after: Mapped[str | None] = mapped_column(String(120))
    snapshot_version: Mapped[int | None] = mapped_column(BigInteger)
    discovery_complete: Mapped[bool] = mapped_column(default=False, server_default="0")
    total_items: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    scanned_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    updated_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    skipped_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    failed_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ZoteroManualSyncItem(Base):
    __tablename__ = "zotero_manual_sync_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["job_id", "user_id"],
            ["zotero_manual_sync_jobs.id", "zotero_manual_sync_jobs.user_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("job_id", "item_key", name="uq_zotero_manual_sync_item"),
        UniqueConstraint("id", "user_id", name="uq_zotero_manual_sync_item_owner"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    item_key: Mapped[str] = mapped_column(String(80))
    item_version: Mapped[int] = mapped_column(BigInteger)
    source_payload: Mapped[dict[str, object]] = mapped_column(JSON)
    attachment_changed: Mapped[bool] = mapped_column(default=False, server_default="0")
    status: Mapped[str] = mapped_column(String(24), default="PENDING")
    paper_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("papers.id"))
    content_changed: Mapped[bool] = mapped_column(default=False, server_default="0")
    content_change_unknown: Mapped[bool] = mapped_column(default=False, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ZoteroManualSyncCandidate(Base):
    __tablename__ = "zotero_manual_sync_candidates"
    __table_args__ = (
        ForeignKeyConstraint(
            ["item_id", "user_id"],
            ["zotero_manual_sync_items.id", "zotero_manual_sync_items.user_id"],
            ondelete="CASCADE",
        ),
    )

    item_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    paper_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("papers.id"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)


class Attachment(Base):
    __tablename__ = "attachments"
    __table_args__ = (UniqueConstraint("id", "user_id", name="uq_attachment_owner"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    storage_provider: Mapped[str] = mapped_column(String(64))
    object_key: Mapped[str] = mapped_column(String(320), unique=True)
    original_filename: Mapped[str] = mapped_column(String(320))
    mime_type: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PaperAttachment(Base):
    __tablename__ = "paper_attachments"
    __table_args__ = (
        UniqueConstraint(
            "source_item_id", "attachment_key", "source_version", name="uq_paper_source_attachment"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    paper_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("papers.id"), index=True)
    source_item_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("zotero_source_items.id")
    )
    attachment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("attachments.id"))
    attachment_key: Mapped[str | None] = mapped_column(String(16))
    source_version: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="AVAILABLE")
    source_url: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ParsedDocument(Base):
    __tablename__ = "parsed_documents"
    __table_args__ = (
        UniqueConstraint("attachment_id", "parser_name", "parser_version", "file_sha256"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    paper_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("papers.id"), index=True)
    attachment_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("attachments.id"))
    parser_name: Mapped[str] = mapped_column(String(80))
    parser_version: Mapped[str] = mapped_column(String(80))
    file_sha256: Mapped[str] = mapped_column(String(64))
    page_count: Mapped[int | None] = mapped_column(Integer)
    extracted_characters: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(24), default="PARSING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PaperParseJob(Base):
    __tablename__ = "paper_parse_jobs"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_paper_parse_idempotency"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    paper_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("papers.id"), index=True)
    attachment_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("attachments.id"))
    parsed_document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("parsed_documents.id")
    )
    parser_name: Mapped[str] = mapped_column(String(80))
    parser_version: Mapped[str] = mapped_column(String(80))
    idempotency_key: Mapped[str] = mapped_column(String(64))
    suppress_auto_analysis: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    status: Mapped[str] = mapped_column(String(24), default="QUEUED")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LiteratureIngestJob(Base):
    __tablename__ = "literature_ingest_jobs"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_literature_ingest_idempotency"),
        Index("ix_literature_ingest_owner_status", "user_id", "status"),
        CheckConstraint("analysis_mode IN ('FAST', 'STANDARD', 'DEEP')", name="ck_ingest_mode"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    provider_key: Mapped[str] = mapped_column(String(64))
    server_id: Mapped[str] = mapped_column(String(100))
    library_type: Mapped[str] = mapped_column(String(16))
    library_id: Mapped[str] = mapped_column(String(80))
    item_key: Mapped[str] = mapped_column(String(16))
    item_title: Mapped[str] = mapped_column(String(2000), default="", server_default="")
    source_version: Mapped[int] = mapped_column(Integer)
    attachment_fingerprint: Mapped[str | None] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(64))
    copy_pdf: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    request_analysis: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    analysis_mode: Mapped[str] = mapped_column(String(16), default="STANDARD")
    status: Mapped[str] = mapped_column(String(32), default="QUEUED")
    stage: Mapped[str] = mapped_column(String(16), default="SYNC")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paper_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("papers.id"))
    attachment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("attachments.id"))
    parse_job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("paper_parse_jobs.id"))
    analysis_job_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("paper_analysis_jobs.id")
    )
    inbox_item_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("inbox_items.id"))
    warning_code: Mapped[str | None] = mapped_column(String(80))
    warning_message: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LiteratureIngestCandidate(Base):
    __tablename__ = "literature_ingest_candidates"

    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("literature_ingest_jobs.id"), primary_key=True
    )
    paper_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("papers.id"), primary_key=True)


class ParsedSection(Base):
    __tablename__ = "parsed_sections"
    __table_args__ = (
        UniqueConstraint("document_id", "section_key"),
        UniqueConstraint("document_id", "id", name="uq_parsed_section_document_id"),
        ForeignKeyConstraint(
            ["document_id", "parent_section_id"],
            ["parsed_sections.document_id", "parsed_sections.id"],
            name="fk_parsed_section_parent_document",
        ),
        CheckConstraint(
            "heading_level IS NULL OR heading_level > 0", name="ck_parsed_section_level"
        ),
        CheckConstraint(
            "section_order IS NULL OR section_order >= 0", name="ck_parsed_section_order"
        ),
        CheckConstraint(
            "parent_section_id IS NULL OR parent_section_id <> id",
            name="ck_parsed_section_not_self",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("parsed_documents.id"), index=True
    )
    section_key: Mapped[str] = mapped_column(String(48))
    title: Mapped[str | None] = mapped_column(Text)
    semantic_key: Mapped[str | None] = mapped_column(String(48))
    heading_level: Mapped[int | None] = mapped_column(Integer)
    parent_section_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    section_order: Mapped[int | None] = mapped_column(Integer)
    start_page: Mapped[int | None] = mapped_column(Integer)
    end_page: Mapped[int | None] = mapped_column(Integer)
    coverage_status: Mapped[str] = mapped_column(String(24), default="MISSING")
    text: Mapped[str | None] = mapped_column(Text)


class ParsedBlock(Base):
    __tablename__ = "parsed_blocks"
    __table_args__ = (UniqueConstraint("document_id", "block_index"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("parsed_documents.id"), index=True
    )
    section_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("parsed_sections.id"))
    block_index: Mapped[int] = mapped_column(Integer)
    page_number: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)


class ParseWarning(Base):
    __tablename__ = "parse_warnings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("parsed_documents.id"), index=True
    )
    code: Mapped[str] = mapped_column(String(80))
    message: Mapped[str] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column(Integer)


class AnalysisSettings(Base):
    __tablename__ = "analysis_settings"
    __table_args__ = (
        CheckConstraint(
            "cloud_scope IN ('NONE', 'METADATA_ONLY', 'ABSTRACT_ONLY', 'FULL_TEXT')",
            name="ck_analysis_cloud_scope",
        ),
        CheckConstraint(
            "budget_mode IN ('LOCAL_LIMITS', 'PROVIDER_QUOTA')",
            name="ck_analysis_budget_mode",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), primary_key=True)
    cloud_scope: Mapped[str] = mapped_column(String(24), default="NONE", server_default="NONE")
    budget_mode: Mapped[str] = mapped_column(
        String(24), default="LOCAL_LIMITS", server_default="LOCAL_LIMITS"
    )
    auto_sync_zotero: Mapped[bool] = mapped_column(default=False, server_default="0")
    auto_copy_pdf: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    auto_analyze_paper: Mapped[bool] = mapped_column(default=False, server_default="0")
    auto_sync_interval_minutes: Mapped[int] = mapped_column(
        Integer, default=60, server_default="60"
    )
    auto_sync_next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auto_sync_last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auto_sync_last_error: Mapped[str | None] = mapped_column(Text)
    daily_analysis_limit: Mapped[int] = mapped_column(Integer, default=5, server_default="5")
    monthly_token_limit: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_papers_per_sync: Mapped[int] = mapped_column(Integer, default=20, server_default="20")
    max_concurrent_jobs: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    max_input_tokens_per_job: Mapped[int] = mapped_column(
        Integer, default=12000, server_default="12000"
    )
    max_output_tokens_per_job: Mapped[int] = mapped_column(
        Integer, default=4000, server_default="4000"
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PaperAnalysisJob(Base):
    __tablename__ = "paper_analysis_jobs"
    __table_args__ = (
        UniqueConstraint("id", "paper_id", "user_id", name="uq_analysis_job_paper_owner"),
        UniqueConstraint("user_id", "idempotency_key", name="uq_paper_analysis_idempotency"),
        Index("ux_paper_analysis_jobs_id_user", "id", "user_id", unique=True),
        CheckConstraint(
            "analysis_scope IN ('METADATA_ONLY', 'ABSTRACT_ONLY', 'FULL_TEXT')",
            name="ck_analysis_scope",
        ),
        CheckConstraint("analysis_mode IN ('FAST', 'STANDARD', 'DEEP')", name="ck_analysis_mode"),
        CheckConstraint("source_type IN ('TEXT', 'PDF')", name="ck_analysis_source_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    paper_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("papers.id"), index=True)
    parsed_document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("parsed_documents.id")
    )
    idempotency_key: Mapped[str] = mapped_column(String(64))
    input_sha256: Mapped[str] = mapped_column(String(64))
    source_version: Mapped[str | None] = mapped_column(String(120))
    analysis_scope: Mapped[str] = mapped_column(String(24))
    analysis_mode: Mapped[str] = mapped_column(String(16))
    source_type: Mapped[str] = mapped_column(String(8), default="TEXT", server_default="TEXT")
    provider_key: Mapped[str] = mapped_column(String(64))
    model_key: Mapped[str] = mapped_column(String(160))
    reasoning_effort: Mapped[str | None] = mapped_column(String(16))
    analysis_version: Mapped[str] = mapped_column(String(32))
    prompt_version: Mapped[str] = mapped_column(String(32))
    schema_version: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24), default="QUEUED")
    priority: Mapped[str] = mapped_column(String(16), default="NORMAL")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    reserved_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    part_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    parts_completed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_estimate: Mapped[Decimal | None] = mapped_column(Numeric(16, 8))
    cost_currency: Mapped[str | None] = mapped_column(String(12))
    pricing_version: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)


class PaperPDFReadingSource(Base):
    __tablename__ = "paper_pdf_reading_sources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["job_id", "user_id"],
            ["paper_analysis_jobs.id", "paper_analysis_jobs.user_id"],
            name="fk_pdf_reading_job_owner",
        ),
        ForeignKeyConstraint(
            ["attachment_id", "user_id"],
            ["attachments.id", "attachments.user_id"],
            name="fk_pdf_reading_attachment_owner",
        ),
        CheckConstraint("page_count > 0", name="ck_pdf_reading_page_count"),
        CheckConstraint(
            "note_output_contract IN ('PAPER_ANALYSIS_V1','CANONICAL_MARKDOWN_V2')",
            name="ck_pdf_reading_output_contract",
        ),
    )
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    attachment_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("attachments.id"), index=True)
    sha256: Mapped[str] = mapped_column(String(64))
    page_count: Mapped[int] = mapped_column(Integer)
    skill_key: Mapped[str] = mapped_column(String(80))
    skill_version: Mapped[str] = mapped_column(String(80))
    skill_instructions: Mapped[str] = mapped_column(Text)
    skill_sha256: Mapped[str] = mapped_column(String(64))
    render_version: Mapped[str] = mapped_column(String(160))
    note_output_contract: Mapped[str] = mapped_column(
        String(32), default="PAPER_ANALYSIS_V1", server_default="PAPER_ANALYSIS_V1"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PaperAnalysisPart(Base):
    __tablename__ = "paper_analysis_parts"
    __table_args__ = (
        UniqueConstraint("job_id", "part_index", name="uq_paper_analysis_part_position"),
        ForeignKeyConstraint(
            ["job_id", "user_id"],
            ["paper_analysis_jobs.id", "paper_analysis_jobs.user_id"],
            name="fk_paper_analysis_part_owner_job",
        ),
        CheckConstraint("part_index >= 1", name="ck_paper_analysis_part_index"),
        CheckConstraint("attempt_count >= 0", name="ck_paper_analysis_part_attempts"),
        CheckConstraint(
            "status IN ('QUEUED', 'ANALYZING', 'COMPLETED', 'RETRY_WAIT', "
            "'FAILED', 'NEEDS_ATTENTION')",
            name="ck_paper_analysis_part_status",
        ),
        Index("ix_paper_analysis_parts_user_job", "user_id", "job_id"),
        Index("ix_paper_analysis_parts_job_status", "job_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    part_index: Mapped[int] = mapped_column(Integer)
    section_key: Mapped[str] = mapped_column(String(80))
    request_payload: Mapped[dict[str, object]] = mapped_column(JSON)
    request_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="QUEUED", server_default="QUEUED")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    response_payload: Mapped[dict[str, object] | None] = mapped_column(JSON)
    provider_response_id: Mapped[str | None] = mapped_column(String(200))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AnalysisInputSnapshot(Base):
    __tablename__ = "analysis_input_snapshots"

    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("paper_analysis_jobs.id"), primary_key=True
    )
    payload: Mapped[dict[str, object]] = mapped_column(JSON)
    input_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PaperResearchNote(Base):
    __tablename__ = "paper_research_notes"
    __table_args__ = (
        UniqueConstraint("paper_id", "revision"),
        UniqueConstraint("id", "user_id", name="uq_paper_research_note_owner"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("research_entities.id"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    paper_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("papers.id"), index=True)
    analysis_job_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("paper_analysis_jobs.id")
    )
    parent_note_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("paper_research_notes.id")
    )
    revision: Mapped[int] = mapped_column(Integer)
    summary: Mapped[str | None] = mapped_column(Text)
    analysis_scope: Mapped[str] = mapped_column(String(24))
    analysis_mode: Mapped[str] = mapped_column(String(16))
    created_by: Mapped[str] = mapped_column(String(24))
    review_status: Mapped[str] = mapped_column(String(24), default="UNREVIEWED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResearchNoteSection(Base):
    __tablename__ = "research_note_sections"
    __table_args__ = (UniqueConstraint("note_id", "section_key"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    note_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("paper_research_notes.id"), index=True
    )
    section_key: Mapped[str] = mapped_column(String(48))
    body_markdown: Mapped[str | None] = mapped_column(Text)
    origin_type: Mapped[str] = mapped_column(String(24), default="AI_INTERPRETATION")
    review_status: Mapped[str] = mapped_column(String(24), default="UNREVIEWED")
    uncertainty: Mapped[str | None] = mapped_column(Text)


class ResearchNoteEvidence(Base):
    __tablename__ = "research_note_evidence"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    section_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("research_note_sections.id"), index=True
    )
    claim_type: Mapped[str] = mapped_column(String(24))
    source_section: Mapped[str | None] = mapped_column(String(80))
    source_page: Mapped[int | None] = mapped_column(Integer)
    source_block_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("parsed_blocks.id"))
    evidence_text: Mapped[str | None] = mapped_column(Text)
    locator: Mapped[str | None] = mapped_column(String(320))


class NoteReviewAction(Base):
    __tablename__ = "note_review_actions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    note_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("paper_research_notes.id"), index=True
    )
    section_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("research_note_sections.id")
    )
    reviewer_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(24))
    comment: Mapped[str | None] = mapped_column(Text)
    reviewed_revision: Mapped[int] = mapped_column(Integer)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class InboxItem(Base):
    __tablename__ = "inbox_items"
    __table_args__ = (UniqueConstraint("item_type", "note_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    item_type: Mapped[str] = mapped_column(String(32), default="AI_NOTE")
    note_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("paper_research_notes.id"))
    status: Mapped[str] = mapped_column(String(24), default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))


class ResearchEvent(Base):
    __tablename__ = "research_events"
    __table_args__ = (UniqueConstraint("event_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(80))
    schema_version: Mapped[str] = mapped_column(String(16), default="1.0")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(100))
    paper_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("papers.id"))
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    payload: Mapped[dict[str, object]] = mapped_column(JSON)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
