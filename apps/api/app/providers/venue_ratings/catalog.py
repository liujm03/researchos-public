"""Small verified public-source snapshot. No network or licensed-data scraping.

See docs/VENUE_RATING_SOURCES.md before extending names or facts. In particular,
JCR quartiles are not CAS divisions and a conference name is not paper eligibility.
"""

import re
import unicodedata
from dataclasses import dataclass

CHECKED_AT = "2026-10-09T06:03:13+00:00"
IEEE_SOURCE = "https://open.ieee.org/wp-content/uploads/IEEE-Title-List-September-2026.pdf"
CCFCV_SOURCE = (
    "https://tc.ccf.org.cn/upload/resources/file/2025/05/17/0c3609a2bf25cf601cdc0f209e19fe6a.pdf"
)
ML_SOURCE = (
    "https://tc.ccf.org.cn/upload/resources/file/2023/03/28/de8f23c2a54dbaf03da495399515a4da.pdf"
)


@dataclass(frozen=True)
class JournalFact:
    title: str
    aliases: tuple[str, ...]
    impact_factor: float
    quartile: str | None
    category: str = "出版社汇总（未列学科）"
    metric_year: int = 2025
    edition_year: int | None = 2026
    source_url: str = IEEE_SOURCE
    source_label: str = "IEEE Title List（2026-09）；2025 JCR，2026-06发布"
    index: str | None = "SCIE"


# First numeric column is two-year JIF, not the adjacent five-year JIF/CiteScore.
JOURNALS = (
    JournalFact(
        "IEEE Transactions on Pattern Analysis and Machine Intelligence",
        ("TPAMI", "T-PAMI", "IEEE TPAMI"),
        20.4,
        "Q1",
    ),
    JournalFact("IEEE Transactions on Image Processing", ("TIP", "T-IP", "IEEE TIP"), 15.3, "Q1"),
    JournalFact(
        "IEEE Transactions on Neural Networks and Learning Systems",
        ("TNNLS", "T-NNLS", "IEEE TNNLS"),
        9.7,
        "Q1",
    ),
    JournalFact("IEEE Transactions on Power Systems", ("TPWRS", "T-PWRS", "IEEE TPWRS"), 8.7, "Q1"),
    JournalFact("IEEE Transactions on Smart Grid", ("TSG", "T-SG", "IEEE TSG"), 10.1, "Q1"),
    JournalFact(
        "IEEE Transactions on Power Delivery", ("TPWRD", "T-PWRD", "IEEE TPWRD"), 4.7, "Q2"
    ),
    JournalFact(
        "IEEE Transactions on Power Electronics", ("TPEL", "T-PEL", "IEEE TPEL"), 7.1, "Q1"
    ),
    JournalFact("IEEE Transactions on Multimedia", ("TMM", "T-MM", "IEEE TMM"), 9.9, "Q1"),
    JournalFact(
        "IEEE Transactions on Circuits and Systems for Video Technology",
        ("TCSVT", "T-CSVT", "IEEE TCSVT"),
        10.8,
        "Q1",
    ),
    JournalFact(
        "IEEE Transactions on Industrial Electronics", ("TIE", "T-IE", "IEEE TIE"), 7.4, "Q1"
    ),
    JournalFact(
        "IEEE Transactions on Industrial Informatics", ("TII", "T-IINF", "IEEE TII"), 9.8, "Q1"
    ),
    JournalFact("IEEE Access", (), 4.2, "Q2"),
    JournalFact(
        "International Journal of Computer Vision",
        ("IJCV",),
        10.3,
        None,
        category="出版社JIF（未列学科/分区）",
        edition_year=None,
        source_url="https://link.springer.com/journal/11263",
        source_label="Springer Nature 官方期刊页；Journal Impact Factor 2025",
        index=None,
    ),
    JournalFact(
        "Optics Express",
        ("Opt Express",),
        3.4,
        None,
        category="Optics（来源未列分区）",
        source_url="https://opg.optica.org/content/author/portal/item/style-metrics/",
        source_label="Optica Publishing Group；2026 JCR发布页，2025 Impact Factor",
        index=None,
    ),
)


@dataclass(frozen=True)
class ConferenceFact:
    aliases: tuple[str, ...]
    category: str
    metric_year: int
    source_url: str
    source_label: str


CONFERENCES = (
    ConferenceFact(
        (
            "CVPR",
            "IEEE/CVF Conference on Computer Vision and Pattern Recognition",
            "IEEE Conference on Computer Vision and Pattern Recognition",
            "Conference on Computer Vision and Pattern Recognition",
        ),
        "计算机视觉（领域顶会；会场级）",
        2024,
        CCFCV_SOURCE,
        "CCFCV 专委会简报 2024年第4期，物理第37页",
    ),
    ConferenceFact(
        (
            "ICCV",
            "IEEE/CVF International Conference on Computer Vision",
            "IEEE International Conference on Computer Vision",
            "International Conference on Computer Vision",
        ),
        "计算机视觉（领域顶会；会场级）",
        2024,
        CCFCV_SOURCE,
        "CCFCV 专委会简报 2024年第4期，物理第37页",
    ),
    ConferenceFact(
        ("ECCV", "European Conference on Computer Vision"),
        "计算机视觉（领域顶会；会场级）",
        2024,
        CCFCV_SOURCE,
        "CCFCV 专委会简报 2024年第4期，物理第37页",
    ),
    ConferenceFact(
        ("AAAI", "AAAI Conference on Artificial Intelligence"),
        "人工智能（领域顶会；会场级）",
        2024,
        CCFCV_SOURCE,
        "CCFCV 专委会简报 2024年第4期，物理第37页",
    ),
    ConferenceFact(
        (
            "NeurIPS",
            "NIPS",
            "Conference on Neural Information Processing Systems",
            "Advances in Neural Information Processing Systems",
            "Neural Information Processing Systems",
        ),
        "机器学习（领域顶会；会场级）",
        2023,
        ML_SOURCE,
        "CCFCV 专委会简报 2023年第1期，NeurIPS 2022 顶会观察",
    ),
    ConferenceFact(
        ("ICML", "International Conference on Machine Learning"),
        "机器学习（领域顶会；会场级）",
        2023,
        ML_SOURCE,
        "CCFCV 专委会简报 2023年第1期，NeurIPS 2022 顶会观察",
    ),
    ConferenceFact(
        ("ICLR", "International Conference on Learning Representations"),
        "机器学习（领域顶会；会场级）",
        2023,
        ML_SOURCE,
        "CCFCV 专委会简报 2023年第1期，NeurIPS 2022 顶会观察",
    ),
)


def _normalize(name: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", name).casefold().split())


def _conference_name(name: str) -> str:
    """Only discard a year at either boundary; never strip arbitrary subtitles."""
    value = _normalize(name)
    value = re.sub(r"^(?:19|20)\d{2}\s+", "", value)
    value = re.sub(r"\s+(?:19|20)\d{2}$", "", value)
    return value


def _conference_aliases(conference: ConferenceFact) -> set[str]:
    aliases = set(map(_normalize, conference.aliases))
    acronym = _normalize(conference.aliases[0])
    # Zotero often retains the publisher's full name followed by its acronym.
    # Only the reviewed alias's own acronym is allowed, not arbitrary suffixes.
    aliases.update(
        f"{_normalize(alias)} ({acronym})" for alias in conference.aliases[1:] if len(alias) > 10
    )
    return aliases


def _fact(
    scheme: str,
    metric_year: int,
    edition_year: int | None,
    category: str,
    rank_value: str | None,
    impact_factor: float | None,
    is_top: bool | None,
    source_url: str,
    source_label: str,
) -> dict[str, object]:
    return {
        "id": None,
        "request_key": None,
        "scheme": scheme,
        "metric_year": metric_year,
        "edition_year": edition_year,
        "category": category,
        "rank_value": rank_value,
        "impact_factor": impact_factor,
        "is_top": is_top,
        "source_url": source_url,
        "source_label": source_label,
        "source_kind": "OFFICIAL_CATALOG",
        "checked_at": CHECKED_AT,
    }


class OfficialVenueCatalog:
    """Exact, reviewed aliases only. Every call returns fresh dictionaries."""

    def lookup(self, name: str, venue_type: str) -> list[dict[str, object]]:
        normalized = _normalize(name)
        if venue_type.upper() == "JOURNAL":
            for journal in JOURNALS:
                if normalized in {_normalize(journal.title), *map(_normalize, journal.aliases)}:
                    facts = [
                        _fact(
                            "JCR",
                            journal.metric_year,
                            journal.edition_year,
                            journal.category,
                            journal.quartile,
                            journal.impact_factor,
                            None,
                            journal.source_url,
                            journal.source_label,
                        )
                    ]
                    if journal.index is not None:
                        facts.append(
                            _fact(
                                "INDEX",
                                journal.metric_year,
                                journal.edition_year,
                                "出版社索引列",
                                journal.index,
                                None,
                                None,
                                journal.source_url,
                                journal.source_label,
                            )
                        )
                    return facts
            return []
        if venue_type.upper() != "CONFERENCE":
            return []
        # Reject companion/nonregular papers even if a parent acronym occurs.
        if re.search(
            r"\b(workshops?|short paper|demo|findings|preprint|arxiv)\b|\bcvprw\b|\biccvw\b",
            normalized,
        ):
            return []
        normalized = _conference_name(name)
        for conference in CONFERENCES:
            if normalized in _conference_aliases(conference):
                return [
                    _fact(
                        "TOP_CONFERENCE",
                        conference.metric_year,
                        None,
                        conference.category,
                        None,
                        None,
                        True,
                        conference.source_url,
                        conference.source_label,
                    )
                ]
        return []


catalog = OfficialVenueCatalog()
