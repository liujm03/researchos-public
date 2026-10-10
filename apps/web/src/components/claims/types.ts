import type { components } from "@/lib/generated";
export type Claim = components["schemas"]["ClaimOut"];
export type Revision = components["schemas"]["ClaimRevisionOut"];
export type ClaimPage = components["schemas"]["ClaimPage"];
export type RevisionPage = components["schemas"]["ClaimRevisionPage"];
export type Evidence = components["schemas"]["ClaimEvidenceSelection"];
export type EvidenceOut = components["schemas"]["ClaimEvidenceOut"];
export type Fields = Omit<
  components["schemas"]["ClaimCreate"],
  "project_id" | "idempotency_key" | "evidence"
>;
export type ResultSources = components["schemas"]["ClaimResultSourcePage"];
export type ServerResult = components["schemas"]["ServerResultOut"];
export const kinds = [
  ["HYPOTHESIS", "待验证假设"],
  ["FINDING", "研究发现"],
  ["LIMITATION", "局限"],
  ["RESEARCH_GAP", "研究缺口"],
] as const;
export const relations = [
  ["SUPPORTS", "支持"],
  ["REFUTES", "反证"],
  ["CONTEXT", "背景"],
] as const;
export const message = (cause: unknown) =>
  cause instanceof Error ? cause.message : "读取或保存失败";
export function inherited(row: EvidenceOut): Evidence {
  const common = {
    source_kind: row.source_kind,
    relation: row.relation,
    rationale: row.rationale,
  };
  if (row.source_kind === "RESULT_METRIC")
    return {
      ...common,
      result_id: row.result_id,
      expected_result_sha256: row.result_sha256,
      metric_id: row.metric_id,
    };
  if (row.source_kind === "RESULT_ARTIFACT")
    return {
      ...common,
      result_id: row.result_id,
      expected_result_sha256: row.result_sha256,
      artifact_id: row.artifact_id,
    };
  if (row.source_kind === "CANONICAL_QUOTE")
    return {
      ...common,
      canonical_note_id: row.canonical_note_id,
      expected_note_sha256: row.note_sha256,
      start_offset: row.start_offset,
      end_offset: row.end_offset,
      exact_quote: row.exact_quote,
    };
  return { ...common, observation: row.observation };
}
