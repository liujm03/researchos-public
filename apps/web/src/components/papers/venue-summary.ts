import type { components } from "@/lib/generated";

type Assessment = components["schemas"]["VenueAssessmentOut"];
const authority = {
  OWNER_REPORTED: 0,
  OFFICIAL_CATALOG: 1,
  ZOTERO_METADATA: 2,
};

function newest(a: Assessment, b: Assessment) {
  return (b.metric_year ?? -1) - (a.metric_year ?? -1);
}
function provenance(a: Assessment, b: Assessment) {
  return (
    authority[a.source_kind] - authority[b.source_kind] ||
    (Date.parse(b.checked_at) || 0) - (Date.parse(a.checked_at) || 0) ||
    `${a.category}:${a.raw_field ?? ""}:${a.id ?? ""}`.localeCompare(
      `${b.category}:${b.raw_field ?? ""}:${b.id ?? ""}`,
    )
  );
}
function casCategory(row: Assessment) {
  if (/基础/.test(row.category)) return 4;
  if (/升级.*大类/.test(row.category)) return 0;
  if (/大类|major|broad/i.test(row.category)) return 1;
  if (/升级.*小类/.test(row.category)) return 2;
  return 3;
}

/** Reading summary only. Never choose the highest IF/best quartile or rewrite history. */
export function selectVenueSummary(records: Assessment[]) {
  const jcr = records.filter((row) => row.scheme === "JCR");
  const quarter = jcr
    .filter((row) => /^Q[1-4]$/.test(row.rank_value ?? ""))
    .sort((a, b) => newest(a, b) || provenance(a, b))[0];
  const impact = jcr
    .filter(
      (row) =>
        row.impact_factor != null &&
        (!quarter || row.metric_year === quarter.metric_year),
    )
    .sort((a, b) => newest(a, b) || provenance(a, b))[0];
  const cas = records
    .filter(
      (row) => row.scheme === "CAS" && /^[1-4]$/.test(row.rank_value ?? ""),
    )
    .sort(
      (a, b) =>
        newest(a, b) || casCategory(a) - casCategory(b) || provenance(a, b),
    )[0];
  const conference =
    !quarter && !impact && !cas
      ? records
          .filter(
            (row) =>
              (row.scheme === "CCF" && /^[ABC]$/.test(row.rank_value ?? "")) ||
              (row.scheme === "TOP_CONFERENCE" && row.is_top),
          )
          .sort((a, b) => newest(a, b) || provenance(a, b))[0]
      : undefined;
  return { quarter, impact, cas, conference };
}
