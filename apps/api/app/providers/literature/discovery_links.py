"""Pure URL construction for official sites. No HTTP, credentials or account access."""

from urllib.parse import urlencode

from app.domain.literature_discovery import DiscoveryGroup, DiscoveryVenue

_CATALOG = (
    (
        "vision",
        "视觉与多模态",
        (
            (
                "CVPR",
                "CVPR",
                "IEEE/CVF",
                "https://openaccess.thecvf.com/",
                "IEEE/CVF Conference on Computer Vision and Pattern Recognition",
                "ieee",
            ),
            (
                "ICCV",
                "ICCV",
                "IEEE/CVF",
                "https://openaccess.thecvf.com/",
                "IEEE/CVF International Conference on Computer Vision",
                "ieee",
            ),
            ("ECCV", "ECCV", "ECVA", "https://www.ecva.net/papers.php", "", "home"),
            (
                "TPAMI",
                "IEEE Transactions on Pattern Analysis and Machine Intelligence",
                "IEEE",
                "https://www.computer.org/csdl/journal/tp",
                "IEEE Transactions on Pattern Analysis and Machine Intelligence",
                "ieee",
            ),
            (
                "TIP",
                "IEEE Transactions on Image Processing",
                "IEEE",
                "https://signalprocessingsociety.org/publications-resources/ieee-transactions-image-processing",
                "IEEE Transactions on Image Processing",
                "ieee",
            ),
            (
                "PR",
                "Pattern Recognition",
                "Elsevier",
                "https://www.sciencedirect.com/journal/pattern-recognition",
                "Pattern Recognition",
                "elsevier",
            ),
            (
                "IF",
                "Information Fusion",
                "Elsevier",
                "https://www.sciencedirect.com/journal/information-fusion",
                "Information Fusion",
                "elsevier",
            ),
        ),
    ),
    (
        "deep_learning",
        "深度学习与人工智能",
        (
            ("NeurIPS", "NeurIPS", "NeurIPS", "https://papers.nips.cc/", "", "home"),
            ("ICML", "ICML", "PMLR", "https://proceedings.mlr.press/", "", "home"),
            (
                "ICLR",
                "ICLR",
                "ICLR / OpenReview",
                "https://openreview.net/group?id=ICLR.cc",
                "",
                "home",
            ),
            (
                "TNNLS",
                "IEEE Transactions on Neural Networks and Learning Systems",
                "IEEE",
                "https://cis.ieee.org/publications/t-neural-networks-and-learning-systems",
                "IEEE Transactions on Neural Networks and Learning Systems",
                "ieee",
            ),
            (
                "NN",
                "Neural Networks",
                "Elsevier",
                "https://www.sciencedirect.com/journal/neural-networks",
                "Neural Networks",
                "elsevier",
            ),
        ),
    ),
    (
        "power_systems",
        "电力系统与电力人工智能",
        (
            (
                "TPWRS",
                "IEEE Transactions on Power Systems",
                "IEEE",
                "https://ieee-pes.org/publications/transactions-on-power-systems/",
                "IEEE Transactions on Power Systems",
                "ieee",
            ),
            (
                "TPD",
                "IEEE Transactions on Power Delivery",
                "IEEE",
                "https://ieee-pes.org/publications/transactions-on-power-delivery/",
                "IEEE Transactions on Power Delivery",
                "ieee",
            ),
            (
                "TSG",
                "IEEE Transactions on Smart Grid",
                "IEEE",
                "https://ieee-pes.org/publications/transactions-on-smart-grid/",
                "IEEE Transactions on Smart Grid",
                "ieee",
            ),
            (
                "TSE",
                "IEEE Transactions on Sustainable Energy",
                "IEEE",
                "https://ieee-pes.org/publications/transactions-on-sustainable-energy/",
                "IEEE Transactions on Sustainable Energy",
                "ieee",
            ),
            (
                "AE",
                "Applied Energy",
                "Elsevier",
                "https://www.sciencedirect.com/journal/applied-energy",
                "Applied Energy",
                "elsevier",
            ),
            (
                "EPSR",
                "Electric Power Systems Research",
                "Elsevier",
                "https://www.sciencedirect.com/journal/electric-power-systems-research",
                "Electric Power Systems Research",
                "elsevier",
            ),
        ),
    ),
)


class OfficialDiscoveryLinksAdapter:
    def links(self, query: str, from_year: int, until_year: int) -> tuple[DiscoveryGroup, ...]:
        groups = []
        for key, label, venues in _CATALOG:
            items = []
            for venue_key, name, publisher, homepage, title, kind in venues:
                if kind == "ieee":
                    # Quote the literal user text so it cannot change the publication expression.
                    literal = query.replace('"', " ").replace("\\", " ")
                    url = "https://ieeexplore.ieee.org/search/searchresult.jsp?" + urlencode(
                        {
                            "queryText": f'("All Metadata":"{literal}") AND ("Publication Title":"{title}")',
                            "ranges": f"{from_year}_{until_year}_Year",
                            "sortType": "newest",
                        }
                    )
                    note = f"已附关键词、发表场所和{from_year}–{until_year}年份；请在IEEE Xplore确认筛选。"
                elif kind == "elsevier":
                    url = "https://www.sciencedirect.com/search?" + urlencode(
                        {
                            "qs": query,
                            "pub": title,
                            "date": f"{from_year}-{until_year}",
                        }
                    )
                    note = f"已附关键词、期刊和{from_year}–{until_year}年份；请在ScienceDirect确认筛选。"
                else:
                    url = homepage
                    note = (
                        f"官方论文集入口；进入后选择{from_year}–{until_year}，使用当前关键词检索。"
                    )
                items.append(DiscoveryVenue(venue_key, name, publisher, homepage, url, note))
            groups.append(DiscoveryGroup(key, label, tuple(items)))
        return tuple(groups)
