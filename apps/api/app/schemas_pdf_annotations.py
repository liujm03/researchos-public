import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PdfPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: float = Field(ge=0, le=1, allow_inf_nan=False)
    y: float = Field(ge=0, le=1, allow_inf_nan=False)


class PdfGeometry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    geometry_kind: Literal["RECT", "STROKE"]
    x: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    y: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    width: float | None = Field(default=None, gt=0, le=1, allow_inf_nan=False)
    height: float | None = Field(default=None, gt=0, le=1, allow_inf_nan=False)
    points: list[PdfPoint] = Field(default_factory=list, max_length=2000)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.geometry_kind == "RECT":
            if any(v is None for v in (self.x, self.y, self.width, self.height)) or self.points:
                raise ValueError("RECT requires x/y/width/height and no points")
            assert self.x is not None and self.y is not None
            assert self.width is not None and self.height is not None
            if self.x + self.width > 1.000001 or self.y + self.height > 1.000001:
                raise ValueError("Rectangle must remain inside its PDF page")
        elif len(self.points) < 2 or any(
            v is not None for v in (self.x, self.y, self.width, self.height)
        ):
            raise ValueError("STROKE requires at least two points and no rectangle")
        return self


class PdfAnnotationPut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_revision: int = Field(ge=0, le=1000000)
    kind: Literal["HIGHLIGHT", "UNDERLINE", "COMMENT", "INK"]
    page: int = Field(ge=1, le=2000)
    color: str = Field(default="#ffcc00", pattern=r"^#[a-fA-F0-9]{6}$")
    body: str = Field(default="", max_length=10000)
    geometries: list[PdfGeometry] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def shape_for_kind(self) -> Self:
        shape = "STROKE" if self.kind == "INK" else "RECT"
        if any(g.geometry_kind != shape for g in self.geometries):
            raise ValueError("Annotation geometry does not match annotation kind")
        if sum(len(g.points) for g in self.geometries) > 4000:
            raise ValueError("Too many stroke points")
        if self.kind == "COMMENT" and (len(self.geometries) != 1 or not self.body.strip()):
            raise ValueError("COMMENT requires text and one anchor rectangle")
        if "\x00" in self.body:
            raise ValueError("NUL is not valid annotation text")
        return self


class PdfAnnotationOut(BaseModel):
    id: uuid.UUID
    attachment_id: uuid.UUID
    source_sha256: str
    kind: Literal["HIGHLIGHT", "UNDERLINE", "COMMENT", "INK"]
    page: int
    color: str
    body: str
    revision: int
    geometries: list[PdfGeometry]
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class PdfAnnotationsOut(BaseModel):
    attachment_id: uuid.UUID
    source_sha256: str
    page_count: int
    annotations: list[PdfAnnotationOut]
