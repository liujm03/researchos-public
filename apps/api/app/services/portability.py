import hashlib
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import Session

from app.models import (
    AnalysisInputSnapshot,
    AnalysisSettings,
    Attachment,
    Author,
    CodexTask,
    CodexTaskEvent,
    EntityTag,
    InboxItem,
    LiteratureIngestCandidate,
    LiteratureIngestJob,
    Milestone,
    NoteReviewAction,
    Paper,
    PaperAnalysisJob,
    PaperAnalysisPart,
    PaperAttachment,
    PaperAuthor,
    PaperNote,
    PaperParseJob,
    PaperPDFReadingSource,
    PaperReading,
    PaperReproductionContext,
    PaperReproductionSourceSection,
    PaperResearchNote,
    PaperSource,
    ParsedBlock,
    ParsedDocument,
    ParsedSection,
    ParseWarning,
    PlanningBriefAdoptionReceipt,
    PlanningBriefProposal,
    PlanningBriefProposalSection,
    ProjectPaper,
    ResearchBrief,
    ResearchBriefCanonicalSource,
    ResearchBriefEvidence,
    ResearchBriefReview,
    ResearchBriefSection,
    ResearchEntity,
    ResearchEvent,
    ResearchExecutionPermit,
    ResearchJournal,
    ResearchNoteEvidence,
    ResearchNoteSection,
    ResearchPlanningAttempt,
    ResearchPlanningJob,
    ResearchPlanningResult,
    ResearchProject,
    ResearchQuestion,
    ResearchStageGrant,
    ResearchStageSkillFile,
    SyncJob,
    Tag,
    Task,
    TaskDependency,
    TimeEntry,
    User,
    Venue,
    ZoteroCollection,
    ZoteroItemCollection,
    ZoteroManualSyncCandidate,
    ZoteroManualSyncItem,
    ZoteroManualSyncJob,
    ZoteroSourceItem,
    ZoteroSyncCursor,
)
from app.models_analytical import (
    CanonicalAnalyticalNote,
    PaperReadingApproval,
    PaperReadingApprovalPlan,
)
from app.models_archive_jobs import ProjectArchiveJob, ProjectArchiveJobEvent
from app.models_baseline_runs import (
    BaselineRunArtifact,
    BaselineRunAttempt,
    BaselineRunJob,
    BaselineRunPermit,
    BaselineRunPlan,
    BaselineRunPlanInput,
)
from app.models_baselines import (
    Baseline,
    BaselineAsset,
    BaselineAssetObservation,
    BaselineDatasetBinding,
    BaselineMaterialCheck,
    BaselineVersion,
)
from app.models_claims import ClaimEvidence, ClaimReview, ClaimRevision, ResearchClaim
from app.models_code_changes import (
    CodeChangeApplyAttempt,
    CodeChangeInputFile,
    CodeChangePlan,
    CodeChangeProposal,
    CodeChangeProposalFile,
)
from app.models_evidence_bundles import (
    EvidenceBundle,
    EvidenceBundleClaim,
    EvidenceBundleFile,
    EvidenceBundleSaveAttempt,
)
from app.models_experiments import (
    CodeRepository,
    Dataset,
    DatasetClass,
    DatasetLocation,
    DatasetModality,
    DatasetSplit,
    DatasetVersion,
    Experiment,
    ExperimentArtifact,
    ExperimentMetric,
    ExperimentParameter,
    ExperimentRun,
    ExperimentRunDataset,
    ExperimentStatusEvent,
    Hypothesis,
    MetricDefinition,
    Modality,
    Model,
    ModelComponent,
    ModelModality,
    ModelVersion,
)
from app.models_literature_recommendations import (
    LiteratureRecommendationAuthor,
    LiteratureRecommendationBatch,
    LiteratureRecommendationCandidate,
    LiteratureRecommendationTerm,
    LiteratureRecommendationVenue,
)
from app.models_manuscript_builds import (
    ManuscriptBuild,
    ManuscriptBuildAttempt,
    ManuscriptBuildFigure,
    ManuscriptBuildFile,
    ManuscriptBuildMetric,
    ManuscriptBuildOperation,
    ManuscriptBuildTable,
)
from app.models_note_deletion import (
    NoteDeletionFile,
    NoteDeletionMember,
    NoteDeletionUsageReceipt,
    NotePermanentDeletion,
)
from app.models_note_projects import NoteProject, NoteProjectClassification
from app.models_note_trash import (
    GeneratedFileSettings,
    NoteTrashEntry,
    NoteTrashMember,
    NoteTrashOperation,
)
from app.models_pdf_annotations import PdfAnnotation, PdfAnnotationGeometry, PdfAnnotationPoint
from app.models_project_archives import (
    ProjectArchiveBinding,
    ProjectArchiveFile,
    ProjectArchiveVersion,
)
from app.models_project_sources import (
    ProjectPathBinding,
    ProjectSourceFile,
    ProjectSourceJob,
    ProjectSourcePlan,
    ProjectSourcePlanFile,
)
from app.models_provisioning import ProjectProvisionEvent, ProjectProvisionJob, ProjectProvisionPlan
from app.models_publications import (
    Publication,
    PublicationBinding,
    PublicationReview,
    PublicationRevision,
    PublicationSection,
    PublicationSource,
)
from app.models_reading_bindings import PaperReadingSkillFile
from app.models_repositories import (
    RepositoryBinding,
    RepositoryImportPreview,
    RepositorySourceSnapshot,
)
from app.models_repository_assets import (
    RepositoryAssetFile,
    RepositoryAssetJob,
    RepositoryAssetPlan,
    RepositoryAssetPlanFile,
    RepositoryAssetSnapshot,
)
from app.models_reproduction_sources import (
    PaperReproductionCanonicalSource,
    PaperReproductionNoteExcerpt,
)
from app.models_server_results import (
    ServerResult,
    ServerResultArtifact,
    ServerResultBriefLink,
    ServerResultMetric,
    ServerResultReview,
    ServerResultTaskAction,
)
from app.models_server_task_packages import (
    ServerTaskPackage,
    ServerTaskPackageAsset,
    ServerTaskPackageExpectedArtifact,
    ServerTaskPackageFile,
    ServerTaskPackageSaveAttempt,
    ServerTaskPackageTask,
)
from app.models_venue_ratings import VenueAssessment
from app.models_writing import WritingCandidate, WritingOperation, WritingPlan, WritingSkillFile


def _record(row: Any) -> dict[str, Any]:
    return {column.key: getattr(row, column.key) for column in inspect(row).mapper.column_attrs}


def export_user_data(db: Session, user: User) -> dict[str, Any]:
    project_rows = list(
        db.scalars(select(ResearchProject).where(ResearchProject.user_id == user.id))
    )
    paper_rows = list(db.scalars(select(Paper).where(Paper.user_id == user.id)))
    task_rows = list(db.scalars(select(Task).where(Task.user_id == user.id)))
    project_ids = {row.id for row in project_rows}
    paper_ids = {row.id for row in paper_rows}
    task_ids = {row.id for row in task_rows}
    ingest_job_ids = set(
        db.scalars(select(LiteratureIngestJob.id).where(LiteratureIngestJob.user_id == user.id))
    )
    codex_task_rows = list(db.scalars(select(CodexTask).where(CodexTask.user_id == user.id)))
    codex_task_ids = {row.id for row in codex_task_rows}
    entity_ids = set(db.scalars(select(ResearchEntity.id).where(ResearchEntity.user_id == user.id)))
    author_ids = set(db.scalars(select(Author.id).where(Author.user_id == user.id)))
    tag_ids = set(db.scalars(select(Tag.id).where(Tag.user_id == user.id)))
    venue_ids = {row.venue_id for row in paper_rows if row.venue_id is not None}
    zotero_item_ids = set(
        db.scalars(select(ZoteroSourceItem.id).where(ZoteroSourceItem.user_id == user.id))
    )
    attachment_ids = set(db.scalars(select(Attachment.id).where(Attachment.user_id == user.id)))
    parsed_ids = set(
        db.scalars(select(ParsedDocument.id).where(ParsedDocument.paper_id.in_(paper_ids)))
    )
    parsed_section_ids = set(
        db.scalars(select(ParsedSection.id).where(ParsedSection.document_id.in_(parsed_ids)))
    )
    analysis_job_ids = set(
        db.scalars(select(PaperAnalysisJob.id).where(PaperAnalysisJob.user_id == user.id))
    )
    research_note_ids = set(
        db.scalars(select(PaperResearchNote.id).where(PaperResearchNote.user_id == user.id))
    )
    note_section_ids = set(
        db.scalars(
            select(ResearchNoteSection.id).where(ResearchNoteSection.note_id.in_(research_note_ids))
        )
    )

    tables: dict[str, list[dict[str, Any]]] = {
        "research_entities": [
            _record(row)
            for row in db.scalars(select(ResearchEntity).where(ResearchEntity.user_id == user.id))
        ],
        "research_projects": [_record(row) for row in project_rows],
        "research_questions": [
            _record(row)
            for row in db.scalars(
                select(ResearchQuestion).where(ResearchQuestion.project_id.in_(project_ids))
            )
        ],
        "milestones": [
            _record(row)
            for row in db.scalars(select(Milestone).where(Milestone.project_id.in_(project_ids)))
        ],
        "papers": [_record(row) for row in paper_rows],
        "venues": [
            _record(row) for row in db.scalars(select(Venue).where(Venue.id.in_(venue_ids)))
        ],
        "authors": [
            _record(row) for row in db.scalars(select(Author).where(Author.id.in_(author_ids)))
        ],
        "paper_authors": [
            _record(row)
            for row in db.scalars(select(PaperAuthor).where(PaperAuthor.paper_id.in_(paper_ids)))
        ],
        "paper_readings": [
            _record(row)
            for row in db.scalars(
                select(PaperReading).where(
                    PaperReading.user_id == user.id, PaperReading.paper_id.in_(paper_ids)
                )
            )
        ],
        "paper_sources": [
            _record(row)
            for row in db.scalars(select(PaperSource).where(PaperSource.user_id == user.id))
        ],
        "zotero_source_items": [
            _record(row)
            for row in db.scalars(
                select(ZoteroSourceItem).where(ZoteroSourceItem.id.in_(zotero_item_ids))
            )
        ],
        "zotero_collections": [
            _record(row)
            for row in db.scalars(
                select(ZoteroCollection).where(ZoteroCollection.user_id == user.id)
            )
        ],
        "zotero_item_collections": [
            _record(row)
            for row in db.scalars(
                select(ZoteroItemCollection).where(
                    ZoteroItemCollection.source_item_id.in_(zotero_item_ids)
                )
            )
        ],
        "zotero_sync_cursors": [
            _record(row)
            for row in db.scalars(
                select(ZoteroSyncCursor).where(ZoteroSyncCursor.user_id == user.id)
            )
        ],
        "sync_jobs": [
            _record(row) for row in db.scalars(select(SyncJob).where(SyncJob.user_id == user.id))
        ],
        "zotero_manual_sync_jobs": [
            _record(row)
            for row in db.scalars(
                select(ZoteroManualSyncJob).where(ZoteroManualSyncJob.user_id == user.id)
            )
        ],
        "zotero_manual_sync_items": [
            _record(row)
            for row in db.scalars(
                select(ZoteroManualSyncItem).where(ZoteroManualSyncItem.user_id == user.id)
            )
        ],
        "zotero_manual_sync_candidates": [
            _record(row)
            for row in db.scalars(
                select(ZoteroManualSyncCandidate).where(
                    ZoteroManualSyncCandidate.user_id == user.id
                )
            )
        ],
        "attachments": [
            _record(row)
            for row in db.scalars(select(Attachment).where(Attachment.id.in_(attachment_ids)))
        ],
        "paper_attachments": [
            _record(row)
            for row in db.scalars(
                select(PaperAttachment).where(PaperAttachment.paper_id.in_(paper_ids))
            )
        ],
        "paper_parse_jobs": [
            _record(row)
            for row in db.scalars(select(PaperParseJob).where(PaperParseJob.user_id == user.id))
        ],
        "literature_ingest_jobs": [
            _record(row)
            for row in db.scalars(
                select(LiteratureIngestJob).where(LiteratureIngestJob.user_id == user.id)
            )
        ],
        "literature_ingest_candidates": [
            _record(row)
            for row in db.scalars(
                select(LiteratureIngestCandidate).where(
                    LiteratureIngestCandidate.job_id.in_(ingest_job_ids)
                )
            )
        ],
        "parsed_documents": [
            _record(row)
            for row in db.scalars(select(ParsedDocument).where(ParsedDocument.id.in_(parsed_ids)))
        ],
        "parsed_sections": [
            _record(row)
            for row in db.scalars(
                select(ParsedSection).where(ParsedSection.id.in_(parsed_section_ids))
            )
        ],
        "parsed_blocks": [
            _record(row)
            for row in db.scalars(
                select(ParsedBlock).where(ParsedBlock.document_id.in_(parsed_ids))
            )
        ],
        "parse_warnings": [
            _record(row)
            for row in db.scalars(
                select(ParseWarning).where(ParseWarning.document_id.in_(parsed_ids))
            )
        ],
        "analysis_settings": [
            _record(row)
            for row in db.scalars(
                select(AnalysisSettings).where(AnalysisSettings.user_id == user.id)
            )
        ],
        "paper_analysis_jobs": [
            _record(row)
            for row in db.scalars(
                select(PaperAnalysisJob).where(PaperAnalysisJob.id.in_(analysis_job_ids))
            )
        ],
        "paper_analysis_parts": [
            _record(row)
            for row in db.scalars(
                select(PaperAnalysisPart).where(
                    PaperAnalysisPart.user_id == user.id,
                    PaperAnalysisPart.job_id.in_(analysis_job_ids),
                )
            )
        ],
        "analysis_input_snapshots": [
            _record(row)
            for row in db.scalars(
                select(AnalysisInputSnapshot).where(
                    AnalysisInputSnapshot.job_id.in_(analysis_job_ids)
                )
            )
        ],
        "paper_research_notes": [
            _record(row)
            for row in db.scalars(
                select(PaperResearchNote).where(PaperResearchNote.id.in_(research_note_ids))
            )
        ],
        "research_note_sections": [
            _record(row)
            for row in db.scalars(
                select(ResearchNoteSection).where(ResearchNoteSection.id.in_(note_section_ids))
            )
        ],
        "research_note_evidence": [
            _record(row)
            for row in db.scalars(
                select(ResearchNoteEvidence).where(
                    ResearchNoteEvidence.section_id.in_(note_section_ids)
                )
            )
        ],
        "note_review_actions": [
            _record(row)
            for row in db.scalars(
                select(NoteReviewAction).where(NoteReviewAction.note_id.in_(research_note_ids))
            )
        ],
        "inbox_items": [
            _record(row)
            for row in db.scalars(select(InboxItem).where(InboxItem.user_id == user.id))
        ],
        "research_events": [
            _record(row)
            for row in db.scalars(select(ResearchEvent).where(ResearchEvent.user_id == user.id))
        ],
        "paper_notes": [
            _record(row)
            for row in db.scalars(select(PaperNote).where(PaperNote.user_id == user.id))
        ],
        "project_papers": [
            _record(row)
            for row in db.scalars(
                select(ProjectPaper).where(ProjectPaper.project_id.in_(project_ids))
            )
        ],
        "tags": [_record(row) for row in db.scalars(select(Tag).where(Tag.id.in_(tag_ids)))],
        "entity_tags": [
            _record(row)
            for row in db.scalars(select(EntityTag).where(EntityTag.entity_id.in_(entity_ids)))
        ],
        "tasks": [_record(row) for row in task_rows],
        "codex_tasks": [_record(row) for row in codex_task_rows],
        "paper_reproduction_contexts": [
            _record(row)
            for row in db.scalars(
                select(PaperReproductionContext).where(
                    PaperReproductionContext.user_id == user.id,
                    PaperReproductionContext.task_id.in_(codex_task_ids),
                )
            )
        ],
        "paper_reproduction_source_sections": [
            _record(row)
            for row in db.scalars(
                select(PaperReproductionSourceSection).where(
                    PaperReproductionSourceSection.user_id == user.id,
                    PaperReproductionSourceSection.task_id.in_(codex_task_ids),
                )
            )
        ],
        "codex_task_events": [
            _record(row)
            for row in db.scalars(
                select(CodexTaskEvent).where(
                    CodexTaskEvent.user_id == user.id,
                    CodexTaskEvent.task_id.in_(codex_task_ids),
                )
            )
        ],
        "task_dependencies": [
            _record(row)
            for row in db.scalars(
                select(TaskDependency).where(TaskDependency.task_id.in_(task_ids))
            )
        ],
        "research_journals": [
            _record(row)
            for row in db.scalars(select(ResearchJournal).where(ResearchJournal.user_id == user.id))
        ],
        "time_entries": [
            _record(row)
            for row in db.scalars(select(TimeEntry).where(TimeEntry.user_id == user.id))
        ],
    }
    from app.models_ideas import (
        IdeaBriefAction,
        IdeaRevision,
        IdeaRevisionTag,
        IdeaSource,
        IdeaTaskAction,
        ResearchBriefIdeaSource,
        ResearchIdea,
    )

    for model in (
        ResearchClaim,
        ClaimRevision,
        ClaimEvidence,
        ClaimReview,
        ResearchIdea,
        IdeaRevision,
        IdeaRevisionTag,
        IdeaSource,
        IdeaTaskAction,
        IdeaBriefAction,
        ResearchBriefIdeaSource,
        CodeChangePlan,
        CodeChangeInputFile,
        CodeChangeProposal,
        CodeChangeProposalFile,
        CodeChangeApplyAttempt,
        PaperPDFReadingSource,
        Modality,
        Dataset,
        DatasetModality,
        DatasetVersion,
        DatasetClass,
        DatasetSplit,
        DatasetLocation,
        Model,
        ModelModality,
        ModelVersion,
        ModelComponent,
        CodeRepository,
        Hypothesis,
        Experiment,
        ExperimentRun,
        ExperimentRunDataset,
        ExperimentParameter,
        MetricDefinition,
        ExperimentMetric,
        ExperimentArtifact,
        ExperimentStatusEvent,
        CanonicalAnalyticalNote,
        NotePermanentDeletion,
        NoteDeletionMember,
        NoteDeletionFile,
        NoteDeletionUsageReceipt,
        GeneratedFileSettings,
        NoteTrashEntry,
        NoteTrashMember,
        NoteTrashOperation,
        NoteProjectClassification,
        NoteProject,
        PaperReproductionCanonicalSource,
        PaperReproductionNoteExcerpt,
        PaperReadingApproval,
        PaperReadingApprovalPlan,
        RepositoryBinding,
        RepositoryImportPreview,
        RepositorySourceSnapshot,
        RepositoryAssetPlan,
        RepositoryAssetPlanFile,
        RepositoryAssetJob,
        RepositoryAssetFile,
        RepositoryAssetSnapshot,
        ProjectPathBinding,
        ProjectSourcePlan,
        ProjectSourcePlanFile,
        ProjectSourceJob,
        ProjectSourceFile,
        Baseline,
        BaselineVersion,
        BaselineAsset,
        BaselineDatasetBinding,
        BaselineMaterialCheck,
        BaselineAssetObservation,
        BaselineRunPlan,
        BaselineRunPlanInput,
        BaselineRunJob,
        BaselineRunPermit,
        BaselineRunAttempt,
        BaselineRunArtifact,
        ProjectArchiveBinding,
        ProjectArchiveVersion,
        ProjectArchiveFile,
        ProjectArchiveJob,
        ProjectArchiveJobEvent,
        ProjectProvisionPlan,
        ProjectProvisionJob,
        ProjectProvisionEvent,
        PaperReadingSkillFile,
        ResearchBrief,
        ResearchBriefCanonicalSource,
        ResearchBriefSection,
        ResearchBriefEvidence,
        ResearchBriefReview,
        ResearchStageGrant,
        ResearchStageSkillFile,
        ResearchPlanningJob,
        ResearchExecutionPermit,
        ResearchPlanningAttempt,
        ResearchPlanningResult,
        PlanningBriefProposal,
        PlanningBriefProposalSection,
        PlanningBriefAdoptionReceipt,
        LiteratureRecommendationBatch,
        LiteratureRecommendationTerm,
        LiteratureRecommendationVenue,
        LiteratureRecommendationCandidate,
        LiteratureRecommendationAuthor,
        ServerTaskPackage,
        ServerTaskPackageFile,
        ServerTaskPackageAsset,
        ServerTaskPackageExpectedArtifact,
        ServerTaskPackageTask,
        ServerTaskPackageSaveAttempt,
        ServerResult,
        ServerResultMetric,
        ServerResultArtifact,
        ServerResultReview,
        ServerResultTaskAction,
        ServerResultBriefLink,
        EvidenceBundle,
        EvidenceBundleClaim,
        EvidenceBundleFile,
        EvidenceBundleSaveAttempt,
        Publication,
        PublicationRevision,
        PublicationSection,
        PublicationSource,
        PublicationBinding,
        PublicationReview,
        WritingPlan,
        WritingSkillFile,
        WritingCandidate,
        WritingOperation,
        ManuscriptBuild,
        ManuscriptBuildFile,
        ManuscriptBuildFigure,
        ManuscriptBuildTable,
        ManuscriptBuildMetric,
        ManuscriptBuildAttempt,
        ManuscriptBuildOperation,
        VenueAssessment,
        PdfAnnotation,
        PdfAnnotationGeometry,
        PdfAnnotationPoint,
    ):
        tables[model.__tablename__] = [
            _record(row)
            for row in db.scalars(
                select(model).where(model.user_id == user.id),
            )
        ]
    data = {
        "schema_version": 1,
        "exported_at": datetime.now(UTC),
        "user": {
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "timezone": user.timezone,
        },
        "tables": tables,
    }
    canonical = json.dumps(data, default=str, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {
        **data,
        "manifest": {
            "table_counts": {name: len(rows) for name, rows in tables.items()},
            "sha256": hashlib.sha256(canonical).hexdigest(),
        },
    }


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, (datetime, uuid.UUID)):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
