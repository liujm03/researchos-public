"""Presentation of selected raw metrics; no aggregation or inferred scientific gains."""

import csv
import io
import math
import re
from typing import Any


def render_metric_tables(
    tables: tuple[dict[str, Any], ...], escape: Any
) -> tuple[dict[str, str], list[str], list[str]]:
    if len(tables) > 20:
        raise ValueError("Select at most 20 bounded metric tables")
    texts: dict[str, str] = {}
    includes, warnings = [], []
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    columns = [
        "result_id",
        "metric_id",
        "result_sha256",
        "name",
        "value",
        "unit",
        "split",
        "evaluation_protocol",
        "protocol_sha256",
        "dataset_sha256",
        "config_sha256",
        "git_commit",
    ]
    writer.writerow(["table_key", *columns])
    for table in tables:
        key, title, metrics = table["key"], table["title"], table["metrics"]
        if (
            not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key)
            or not isinstance(title, str)
            or not title.strip()
            or len(title) > 10000
            or not isinstance(metrics, list)
            or not 1 <= len(metrics) <= 100
            or "tables/" + key + ".tex" in texts
        ):
            raise ValueError("Invalid bounded metric table identity")
        lines = [
            "\\begin{table}[ht]\n\\centering\n\\caption{"
            + escape(title)
            + "}\n\\begin{tabular}{llll}\n\\hline\nMetric & Value & Unit & Split \\\\\n\\hline"
        ]
        contexts = set()
        for metric in metrics:
            value = metric["value"]
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not isinstance(metric["name"], str)
                or not metric["name"].strip()
            ):
                raise ValueError("Metric values must be original finite numeric facts")
            for identity in ("result_id", "metric_id"):
                if not re.fullmatch(r"[0-9a-fA-F-]{36}", str(metric.get(identity, ""))):
                    raise ValueError("Metric table needs exact result and metric identities")
            if not re.fullmatch(r"[0-9a-f]{64}", str(metric.get("result_sha256", ""))):
                raise ValueError("Metric table needs the exact result SHA")
            contexts.add(
                tuple(
                    str(metric.get(field))
                    for field in (
                        "unit",
                        "split",
                        "evaluation_protocol",
                        "protocol_sha256",
                        "dataset_sha256",
                    )
                )
            )
            if not metric.get("evaluation_protocol") or not metric.get("split"):
                warnings.append("TABLE_EVALUATION_CONTEXT_INCOMPLETE: " + key)
            cells = [
                metric["name"],
                str(value),
                metric.get("unit") or "Unspecified",
                metric.get("split") or "Unspecified",
            ]
            if (
                any(len(str(cell)) > 32 for cell in cells)
                or len(str(metric.get("evaluation_protocol", ""))) > 80
            ):
                warnings.append("TABLE_LAYOUT_REVIEW_LONG_SOURCE_FIELDS: " + key)
            lines.append(" & ".join(escape(cell) for cell in cells) + r" \\")
            row = [key, *(metric.get(column) for column in columns)]
            writer.writerow(
                [
                    value
                    if isinstance(value, (float, int))
                    else "'" + str(value)
                    if str(value).lstrip().startswith(("=", "+", "-", "@"))
                    else value
                    for value in row
                ]
            )
        if len(contexts) > 1:
            warnings.append("TABLE_MIXED_EVALUATION_CONTEXTS_NOT_AGGREGATED: " + key)
        lines.append("\\hline\n\\end{tabular}\n\\end{table}\n")
        path = "tables/" + key + ".tex"
        texts[path] = "\n".join(lines)
        includes.append("\\input{" + path + "}")
    texts["evidence/metrics.csv"] = output.getvalue()
    return texts, includes, warnings
