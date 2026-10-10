import asyncio
import tempfile
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import ROOT_DIR, get_settings
from app.domain.paper_parser import PaperParser
from app.domain.storage import StorageProvider
from app.errors import DomainError
from app.models import (
    Attachment,
    PaperAttachment,
    ParsedBlock,
    ParsedDocument,
    ParsedSection,
    ParseWarning,
)
from app.services.papers import get_paper


async def parse_attachment(
    db: Session,
    user_id: uuid.UUID,
    paper_id: uuid.UUID,
    attachment_id: uuid.UUID,
    storage: StorageProvider,
    parser: PaperParser,
    *,
    commit: bool = True,
) -> ParsedDocument:
    get_paper(db, user_id, paper_id)
    attachment = db.scalar(
        select(Attachment).where(Attachment.id == attachment_id, Attachment.user_id == user_id)
    )
    linked = db.scalar(
        select(PaperAttachment.id).where(
            PaperAttachment.paper_id == paper_id,
            PaperAttachment.attachment_id == attachment_id,
        )
    )
    if attachment is None or linked is None:
        raise DomainError("NOT_FOUND", "Paper PDF attachment not found", 404)
    existing = db.scalar(
        select(ParsedDocument).where(
            ParsedDocument.attachment_id == attachment_id,
            ParsedDocument.parser_name == parser.parser_name,
            ParsedDocument.parser_version == parser.parser_version,
            ParsedDocument.file_sha256 == attachment.sha256,
        )
    )
    if existing is not None:
        return existing

    temp_root = ROOT_DIR / "data" / "tmp"
    temp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=temp_root) as temp_dir:
        path = Path(temp_dir) / "paper.pdf"
        with path.open("wb") as file:
            async for chunk in storage.load(attachment.object_key):
                await asyncio.to_thread(file.write, chunk)
        result = await asyncio.to_thread(parser.parse, path, max_pages=get_settings().max_pdf_pages)

    document = ParsedDocument(
        id=uuid.uuid4(),
        paper_id=paper_id,
        attachment_id=attachment_id,
        parser_name=parser.parser_name,
        parser_version=parser.parser_version,
        file_sha256=attachment.sha256,
        page_count=result.page_count,
        extracted_characters=result.extracted_characters,
        status=result.status,
    )
    db.add(document)
    # These models have foreign keys but no ORM relationships to order inserts.
    db.flush()
    section_ids: dict[str, uuid.UUID] = {}
    keys = [section.section_key for section in result.sections]
    if len(keys) != len(set(keys)):
        raise DomainError("PARSE_INVALID_OUTLINE", "Parser returned duplicate section keys", 422)
    parents = {
        section.section_key: getattr(section, "parent_section_key", None)
        for section in result.sections
    }
    for key in keys:
        visited: set[str] = set()
        current: str | None = key
        while current is not None:
            if current in visited or current not in parents:
                raise DomainError(
                    "PARSE_INVALID_OUTLINE", "Parser returned invalid section hierarchy", 422
                )
            visited.add(current)
            current = parents[current]
    records: dict[str, ParsedSection] = {}
    for order, section in enumerate(result.sections):
        section_id = uuid.uuid4()
        section_ids[section.section_key] = section_id
        record = ParsedSection(
            id=section_id,
            document_id=document.id,
            section_key=section.section_key,
            title=section.title,
            start_page=section.start_page,
            end_page=section.end_page,
            coverage_status=section.coverage_status,
            text=section.text,
            semantic_key=getattr(section, "semantic_key", None),
            heading_level=getattr(section, "heading_level", None),
            section_order=order,
        )
        records[section.section_key] = record
        db.add(record)
    db.flush()
    for key, parent in parents.items():
        if parent is not None:
            records[key].parent_section_id = section_ids[parent]
    db.flush()
    for block in result.blocks:
        db.add(
            ParsedBlock(
                id=uuid.uuid4(),
                document_id=document.id,
                section_id=section_ids.get(block.section_key),
                block_index=block.block_index,
                page_number=block.page_number,
                text=block.text,
            )
        )
    for warning in result.warnings:
        db.add(
            ParseWarning(
                id=uuid.uuid4(),
                document_id=document.id,
                code=warning.code,
                message=warning.message,
                page_number=warning.page_number,
            )
        )
    if commit:
        db.commit()
        db.refresh(document)
    else:
        db.flush()
    return document
