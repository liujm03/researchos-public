"""Owner-scoped paper classification and synchronized Zotero provenance views."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ZoteroCollectionSegmentOut(BaseModel):
    key: str
    name: str


class ZoteroCollectionPathOut(BaseModel):
    collection_id: uuid.UUID
    collection_key: str
    segments: list[ZoteroCollectionSegmentOut]
    path: str
    status: Literal["COMPLETE", "MISSING_PARENT", "CYCLE", "METADATA_INCOMPLETE"]
    missing_parent_key: str | None = None


class ZoteroPaperSourceOut(BaseModel):
    source_item_id: uuid.UUID
    server_id: str
    library_type: str
    library_id: str
    item_key: str
    item_version: int
    last_synced_at: datetime
    collection_status: Literal["KNOWN", "NO_MEMBERSHIP_RECORDED", "INVALID_SCOPE"]
    collections: list[ZoteroCollectionPathOut] = Field(default_factory=list)


class LiteratureProjectOut(BaseModel):
    id: uuid.UUID
    name: str


class PaperLiteratureContextOut(BaseModel):
    zotero_status: Literal["LINKED", "UNLINKED"] = "UNLINKED"
    zotero_sources: list[ZoteroPaperSourceOut] = Field(default_factory=list)
    projects: list[LiteratureProjectOut] = Field(default_factory=list)
    classification_status: Literal["CLASSIFIED", "UNCLASSIFIED"] = "UNCLASSIFIED"


class ZoteroClassificationOptionOut(BaseModel):
    collection_id: uuid.UUID
    server_id: str
    library_type: str
    library_id: str
    collection_key: str
    path: str
    status: Literal["COMPLETE", "MISSING_PARENT", "CYCLE", "METADATA_INCOMPLETE"]


class LiteratureClassificationOptionsOut(BaseModel):
    projects: list[LiteratureProjectOut] = Field(default_factory=list)
    collections: list[ZoteroClassificationOptionOut] = Field(default_factory=list)


class ZoteroCollectionsRefreshOut(BaseModel):
    provider_key: str
    server_id: str
    library_type: str
    library_id: str
    created: int
    updated: int
    unchanged: int
    total: int
    refreshed_at: datetime
