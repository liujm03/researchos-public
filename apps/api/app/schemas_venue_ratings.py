import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RatingScheme = Literal["JCR", "CAS", "CCF", "INDEX", "TOP_CONFERENCE"]


class VenueAssessmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)
    request_key: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    scheme: RatingScheme
    metric_year: int = Field(ge=1900, le=2200)
    edition_year: int | None = Field(default=None, ge=1900, le=2200)
    category: str = Field(default="未指定学科", min_length=1, max_length=240)
    rank_value: str | None = Field(default=None, max_length=24)
    impact_factor: float | None = Field(default=None, ge=0, le=1000)
    is_top: bool | None = None
    source_url: str = Field(min_length=8, max_length=2000)
    source_label: str = Field(min_length=1, max_length=240)

    @field_validator("source_url")
    @classmethod
    def public_link(cls, value: str) -> str:
        parts = urlsplit(value)
        if (
            parts.scheme not in {"https", "http"}
            or not parts.hostname
            or parts.username
            or parts.password
        ):
            raise ValueError("来源须为不含凭据的HTTP/HTTPS链接")
        if any(ord(char) < 32 for char in value):
            raise ValueError("来源链接包含非法控制符")
        return value

    @model_validator(mode="after")
    def rating_consistency(self) -> Self:
        allowed: dict[str, set[str | None]] = {
            "JCR": {"Q1", "Q2", "Q3", "Q4", None},
            "CAS": {"1", "2", "3", "4"},
            "CCF": {"A", "B", "C"},
            "INDEX": {"SCIE", "SSCI", "ESCI", "AHCI"},
            "TOP_CONFERENCE": {None},
        }
        if self.rank_value not in allowed[self.scheme]:
            raise ValueError("等级与评价标准不一致")
        if self.impact_factor is not None and self.scheme != "JCR":
            raise ValueError("影响因子只记录JCR两年JIF，不能以其他指标代替")
        if self.impact_factor is not None:
            exponent = Decimal(str(self.impact_factor)).as_tuple().exponent
            if not isinstance(exponent, int) or exponent < -3:
                raise ValueError("影响因子最多保留三位小数，不能静默舍入原始值")
        if self.scheme == "JCR" and self.rank_value is None and self.impact_factor is None:
            raise ValueError("JCR至少需要分区或影响因子")
        if self.is_top is not None and self.scheme not in {"CAS", "TOP_CONFERENCE"}:
            raise ValueError("TOP标记只适用于中科院或明确的会议标记")
        if self.scheme == "TOP_CONFERENCE" and self.is_top is None:
            raise ValueError("会议标记需要明确是否顶会")
        current = datetime.now(UTC).year
        if self.metric_year > current or (
            self.edition_year is not None and self.edition_year > current
        ):
            raise ValueError("不能把未发布的未来年度标为已记录")
        return self


class VenueAssessmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID | None = None
    request_key: str | None = None
    scheme: RatingScheme
    metric_year: int | None
    edition_year: int | None = None
    category: str
    rank_value: str | None = None
    impact_factor: float | None = None
    is_top: bool | None = None
    source_url: str
    source_label: str
    source_kind: Literal["OFFICIAL_CATALOG", "OWNER_REPORTED", "ZOTERO_METADATA"]
    checked_at: datetime
    raw_field: str | None = None
    raw_value: str | None = None
    source_item_key: str | None = None
    source_version: int | None = None
