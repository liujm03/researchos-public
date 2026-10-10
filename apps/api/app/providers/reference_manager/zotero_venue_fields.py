"""Bounded, auditable Zotero rating metadata, without network or metric guesses."""

import json
import math
import re
import unicodedata
from typing import Any

MAX_ENTRIES = 40
MAX_BYTES = 16_384
_YEAR = re.compile(r"(?<!\d)(19\d{2}|20\d{2}|21\d{2})(?!\d)")
_CHINESE_RANK = {"一": "1", "二": "2", "三": "3", "四": "4"}


def _normalized(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def _field_key(value: str) -> str:
    value = re.sub(r"^(?:extra|field|tag):", "", value)
    return re.sub(r" \[duplicate \d+\]$", "", value)


def _is_rating_key(key: str) -> bool:
    value = _normalized(key)
    return bool(
        re.search(
            r"jcr|quartile|impact.?factor|^if(?:\b|year|[_(（\d])|影响因子|中科院|cas(?:\b|year|partition|quartile)|"
            r"ccf|scie|ssci|esci|sci分区|sjr|scimago|citescore|评级年份|分区年份|指标年份|"
            r"publicationtag|rating.?year|^index$|索引|顶会",
            value,
        )
    )


def extract_venue_fields(data: dict[str, Any]) -> dict[str, str]:
    """Retain source keys/values; explicit origin prefixes disambiguate locations.

    A duplicate key gets a numbered suffix rather than overwriting an earlier
    conflicting value. Bounds apply to the serialized UTF-8 snapshot, including
    warnings. Oversized values are omitted, never partially parsed as facts.
    """
    fields: dict[str, str] = {}
    omitted = 0

    def add(key: str, value: str) -> None:
        nonlocal omitted
        actual_key = key
        duplicate = 2
        while actual_key in fields:
            actual_key = f"{key} [duplicate {duplicate}]"
            duplicate += 1
        candidate = {**fields, actual_key: value}
        if (
            len(fields) >= MAX_ENTRIES - 1
            or len(key.encode("utf-8")) > 480
            or len(value.encode("utf-8")) > 8_192
            or len(json.dumps(candidate, ensure_ascii=False).encode("utf-8")) > MAX_BYTES - 240
        ):
            omitted += 1
            return
        fields[actual_key] = value

    for key, value in data.items():
        if key in {"extra", "tags"} or not isinstance(key, str) or not _is_rating_key(key):
            continue
        if isinstance(value, str):
            add(f"field:{key}", value)
        elif isinstance(value, (bool, int, float)) and not (
            isinstance(value, float) and not math.isfinite(value)
        ):
            add(f"field:{key}", json.dumps(value, ensure_ascii=False, allow_nan=False))
    extra = data.get("extra")
    if isinstance(extra, str):
        for line in extra.splitlines():
            match = re.match(r"^\s*([^:：]{1,480})[:：](.*)$", line)
            if match and _is_rating_key(match[1]):
                add(f"extra:{match[1]}", match[2])
    tags = data.get("tags")
    if isinstance(tags, list):
        for tag in tags:
            text = tag.get("tag") if isinstance(tag, dict) else tag
            if not isinstance(text, str):
                continue
            match = re.match(r"^\s*([^:：]{1,480})[:：](.*)$", text)
            if match and _is_rating_key(match[1]):
                add(f"tag:{match[1]}", match[2])
    if omitted:
        fields["_warning:limits"] = f"Omitted {omitted} oversized or excess rating field(s)"
    return fields


def _scheme(key: str) -> str | None:
    value = _normalized(key)
    if re.search(r"sjr|scimago|citescore|5.?year|five.?year|五年|5年", value):
        return None
    if "jcr" in value or re.search(r"impact.?factor|^if(?:\b|year|[_(（\d])|影响因子", value):
        return "JCR"
    if "中科院" in value or re.search(r"^cas(?:\b|year|partition|quartile)", value):
        return "CAS"
    if re.search(r"^ccf(?:\b|rank|等级|评级|级别)", value):
        return "CCF"
    if re.fullmatch(r"(?:scie|ssci|esci|index|索引|收录索引)(?:\s*\([^)]*\))?", value):
        return "INDEX"
    return None


def _year(key: str, value: str) -> int | None:
    years = set(_YEAR.findall(f"{_normalized(key)} {_normalized(value)}"))
    return int(next(iter(years))) if len(years) == 1 else None


def _scoped_years(fields: dict[str, str]) -> tuple[dict[str, int | None], int | None]:
    values: dict[str, set[int]] = {}
    global_years: set[int] = set()
    for raw_key, raw_value in fields.items():
        key = _field_key(raw_key)
        normalized = _normalized(key)
        if not re.search(r"year|年份|年度", normalized):
            continue
        if re.search(r"edition|release|版年|发布", normalized):
            continue
        year = _year("", raw_value)
        if year is None:
            continue
        if normalized in {"评级年份", "分区年份", "指标年份", "rating year", "ratingyear"}:
            global_years.add(year)
        elif scheme := _scheme(key):
            values.setdefault(scheme, set()).add(year)
    scoped = {
        scheme: next(iter(years)) if len(years) == 1 else None for scheme, years in values.items()
    }
    return scoped, next(iter(global_years)) if len(global_years) == 1 else None


def _category(key: str, value: str, scheme: str) -> str:
    text = _normalized(key)
    if scheme != "CAS":
        return "Zotero字段（未指定学科）"
    label = "中科院大类" if "大类" in text else "中科院小类" if "小类" in text else "中科院"
    if "升级" in text:
        label += "升级版"
    # Explicit labeled subject only; unlabeled annotations remain raw audit data.
    match = re.search(r"(?:学科|category|subject)\s*[:：=]\s*([^;；\n]+)", value, re.I)
    if match:
        return f"{label}：{match[1].strip()}"
    # Subject text following an explicit large/small category field is authored
    # metadata, not inferred from a journal title or its subject area.
    if "大类" in text or "小类" in text:
        subject = re.sub(
            r"[1-4一二三四]\s*区|(?:19|20|21)\d{2}|升级版|基础版|top", "", value, flags=re.I
        )
        subject = subject.strip(" ()（）[]【】,，;；-：:")
        if subject and not re.fullmatch(r"[1-4]", subject):
            return f"{label}：{subject}"
    return f"{label}（未指定学科）"


def _publication_tag_ratings(raw_key: str, raw_value: str) -> list[dict[str, object]]:
    """Plugin labels are unverified metadata, including its ambiguous SCI Q label."""
    text = _normalized(raw_value)
    if re.search(r"sjr|scimago|citescore|5.?year|five.?year|五年|5年", text):
        return []
    rows: list[dict[str, object]] = []
    ranks = set(re.findall(r"\bsci\s+q([1-4])(?!\d)", text))
    numbers = re.findall(r"(?<![a-z])if\s*[:：]?\s*(\d+(?:\.\d{1,3})?)(?![\d.])", text)
    impacts: list[float | None] = [float(number) for number in numbers if float(number) <= 1000]
    if not impacts and ranks:
        impacts = [None]
    for impact in impacts:
        rows.append(
            {
                "scheme": "JCR",
                "rank_value": f"Q{next(iter(ranks))}" if len(ranks) == 1 else None,
                "impact_factor": impact,
                "is_top": None,
                "metric_year": _year("", text),
                "edition_year": None,
                "category": "Zotero插件SCI Q/IF标签（评价标准未核验）",
                "raw_field": raw_key,
                "raw_value": raw_value,
            }
        )
    for match in re.finditer(r"中科院\s*([^;；\n]{0,80}?)([1-4一二三四])\s*区", text):
        subject = match[1].strip(" :：,，()（）")
        rows.append(
            {
                "scheme": "CAS",
                "rank_value": _CHINESE_RANK.get(match[2], match[2]),
                "impact_factor": None,
                "is_top": None,
                "metric_year": _year("", text),
                "edition_year": None,
                "category": f"中科院：{subject}（插件未注明大/小类）"
                if subject
                else "中科院（插件未注明学科及大/小类）",
                "raw_field": raw_key,
                "raw_value": raw_value,
            }
        )
    return rows


def _style_cache_ratings(raw_key: str, raw_value: str) -> list[dict[str, object]]:
    """Only names verified in the installed Ethereal Style cache adapter contract."""
    key = re.sub(r" \[duplicate \d+\]$", "", raw_key)
    field = key.removeprefix("plugin:zoterostyle:")
    if field in {"sciif5", "jci"}:
        return []
    translated = {"sciif": "IF", "sci": "JCR", "ccf": "CCF"}.get(field)
    if translated is not None:
        facts = ratings_from_fields({translated: raw_value})
        for row in facts:
            row["raw_field"] = raw_key
            row["category"] = "Ethereal Style插件字段（评价标准及年度未核验）"
        return facts
    category = {
        "sciBase": "中科院基础版大类",
        "sciUp": "中科院升级版大类",
        "sciUpSmall": "中科院升级版小类",
    }.get(field)
    rows: list[dict[str, object]] = []
    metric_year = _year("", raw_value)
    parsed_value = re.sub(r"[（(](?:19|20|21)\d{2}[）)]", "", raw_value)
    if category is not None:
        for part in parsed_value.split("/"):
            match = re.fullmatch(r"\s*(.*?)\s*([1-4一二三四])\s*区[。.]?\s*", part)
            if match:
                subject = match[1].strip()
                rows.append(
                    {
                        "scheme": "CAS",
                        "rank_value": _CHINESE_RANK.get(match[2], match[2]),
                        "impact_factor": None,
                        "is_top": None,
                        "metric_year": metric_year,
                        "edition_year": None,
                        "category": f"{category}：{subject}"
                        if subject
                        else f"{category}（未指定学科）",
                        "raw_field": raw_key,
                        "raw_value": raw_value,
                    }
                )
    elif field == "sciUpTop":
        match = re.fullmatch(r"\s*(.*?)\s*TOP\s*", parsed_value, re.I)
        if match:
            rows.append(
                {
                    "scheme": "CAS",
                    "rank_value": None,
                    "impact_factor": None,
                    "is_top": True,
                    "metric_year": metric_year,
                    "edition_year": None,
                    "category": f"中科院升级版TOP：{match[1].strip() or '未指定学科'}",
                    "raw_field": raw_key,
                    "raw_value": raw_value,
                }
            )
    return rows


def ratings_from_fields(fields: dict[str, str]) -> list[dict[str, object]]:
    """Parse only explicitly named standards. Unknown years remain None.

    Conflicts remain separate records and never select the best rank or highest
    number. Publication dates and unqualified tags cannot supply rating years.
    """
    ratings: list[dict[str, object]] = []
    scoped, global_year = _scoped_years(fields)
    for raw_key, raw_value in fields.items():
        if raw_key.startswith("_warning:"):
            continue
        if raw_key.startswith("plugin:zoterostyle:"):
            ratings.extend(_style_cache_ratings(raw_key, raw_value))
            continue
        key = _field_key(raw_key)
        if "publicationtag" in _normalized(key):
            ratings.extend(_publication_tag_ratings(raw_key, raw_value))
            continue
        scheme = _scheme(key)
        if scheme is None or re.search(r"year|年份|年度", _normalized(key)):
            continue
        text = _normalized(raw_value)
        if re.search(r"sjr|scimago|citescore|5.?year|five.?year|五年|5年", text):
            continue
        rank: str | None = None
        impact: float | None = None
        if scheme == "JCR":
            ranks = set(re.findall(r"(?<!\w)q([1-4])(?!\w)", text))
            if len(ranks) == 1:
                rank = f"Q{next(iter(ranks))}"
            # Numeric values are JIF only for an explicit IF field/value label.
            if re.search(r"impact.?factor|^if(?:\b|[_(（\d])|影响因子", _normalized(key)):
                numeric = re.fullmatch(
                    r"\s*(\d+(?:\.\d{1,3})?)\s*(?:\((?:19|20|21)\d{2}\))?\s*", text
                )
                if numeric:
                    number = float(numeric[1])
                    if math.isfinite(number) and 0 <= number <= 1000:
                        impact = number
        elif scheme == "CAS":
            ranks = {
                _CHINESE_RANK.get(value, value)
                for value in re.findall(r"(?<![\d一二三四])([1-4一二三四])\s*区", text)
            }
            if len(ranks) == 1:
                rank = next(iter(ranks))
            elif re.fullmatch(r"[1-4]", text):
                rank = text
        elif scheme == "CCF":
            match = re.fullmatch(r"\s*([abc])\s*(?:类|级)?\s*(?:\((?:19|20|21)\d{2}\))?", text)
            if match:
                rank = match[1].upper()
        elif scheme == "INDEX":
            if text.upper() in {"SCIE", "SSCI", "ESCI", "AHCI"}:
                rank = text.upper()
        if rank is None and impact is None:
            continue
        explicit_year = _year(key, raw_value)
        metric_year = (
            explicit_year if explicit_year is not None else scoped.get(scheme, global_year)
        )
        # Multiple explicit years are ambiguous and must not fall back to global.
        if len(set(_YEAR.findall(_normalized(f"{key} {raw_value}")))) > 1:
            metric_year = None
        ratings.append(
            {
                "scheme": scheme,
                "rank_value": rank,
                "impact_factor": impact,
                "is_top": None,
                "metric_year": metric_year,
                "edition_year": None,
                "category": _category(key, raw_value, scheme),
                "raw_field": raw_key,
                "raw_value": raw_value,
            }
        )
    return ratings
