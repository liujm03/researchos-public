"""Conservative venue identities and explainable literal metadata matching."""

import hashlib
import json
import re
import unicodedata
from typing import Any

VENUES: dict[str, tuple[str, ...]] = {
    "CVPR": (
        "CVPR",
        "IEEE/CVF Conference on Computer Vision and Pattern Recognition",
        "IEEE Conference on Computer Vision and Pattern Recognition",
    ),
    "ICCV": (
        "ICCV",
        "IEEE/CVF International Conference on Computer Vision",
        "IEEE International Conference on Computer Vision",
    ),
    "ECCV": ("ECCV", "European Conference on Computer Vision"),
    "NeurIPS": ("NeurIPS", "Advances in Neural Information Processing Systems"),
    "ICML": ("ICML", "International Conference on Machine Learning"),
    "ICLR": ("ICLR", "International Conference on Learning Representations"),
    "TPAMI": ("TPAMI", "IEEE Transactions on Pattern Analysis and Machine Intelligence"),
    "TIP": ("TIP", "IEEE Transactions on Image Processing"),
    "TITS": ("TITS", "IEEE Transactions on Intelligent Transportation Systems"),
    "TSG": ("TSG", "IEEE Transactions on Smart Grid"),
    "TIE": ("TIE", "IEEE Transactions on Industrial Electronics"),
}
COVERAGE_NOTE = "Crossref 官方开放元数据候选；不覆盖全部学术库。场所名单不是质量认证，排名仅是标题/摘要的字面命中，发表信息需核对原始来源。"


def sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def classify_venue(value: str | None) -> tuple[str | None, str]:
    if not value or not value.strip():
        return None, "UNKNOWN"
    normalized = _normalized(value)
    # Crossref's conference container commonly has a leading publication year.
    normalized = re.sub(r"^\d{4}\s+", "", normalized)
    normalized = re.sub(r"^proceedings of (?:the )?", "", normalized)
    for key, aliases in VENUES.items():
        for alias in aliases:
            exact = _normalized(alias)
            if normalized == exact or normalized == f"{exact} ({key.casefold()})":
                return key, "MATCHED"
    return None, "OTHER"


def literal_matches(
    title: str | None, abstract: str | None, terms: list[str]
) -> tuple[int, list[str]]:
    reasons: list[str] = []
    score = 0
    for term in terms:
        needle = _normalized(term)
        for field, value, weight in (("title", title, 2), ("abstract", abstract, 1)):
            haystack = _normalized(value or "")
            pattern = re.escape(needle)
            if needle.isascii():
                pattern = rf"(?<!\w){pattern}(?!\w)"
            if needle and re.search(pattern, haystack):
                reasons.append(f"{field}: {term}")
                score += weight
    return score, reasons
