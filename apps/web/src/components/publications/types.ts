import type { components } from "@/lib/generated";
export type Section = Required<
  components["schemas"]["PublicationSectionInput"]
>;
export type Binding = Required<
  components["schemas"]["PublicationBindingInput"]
>;
export type Fields = Omit<
  Required<components["schemas"]["PublicationFields"]>,
  "sections" | "bindings"
> & { sections: Section[]; bindings: Binding[] };
export type Publication = components["schemas"]["PublicationOut"];
export type Revision = components["schemas"]["PublicationRevisionOut"];
export type PublicationPage = components["schemas"]["PublicationPage"];
export type RevisionPage = components["schemas"]["PublicationRevisionPage"];
export type Preview = components["schemas"]["PublicationPreview"];
export type Bundle = components["schemas"]["EvidenceBundleOut"];
export type BundlePage = components["schemas"]["EvidenceBundlePage"];
export const message = (cause: unknown) =>
  cause instanceof Error ? cause.message : "读取或保存失败";
export const skeleton = [
  ["background", "研究背景"],
  ["limitations", "现有局限"],
  ["key_idea", "关键想法"],
  ["challenges", "关键挑战"],
  ["method", "方法路线"],
  ["contributions", "预期贡献"],
] as const;
export const manuscript = [
  ["abstract", "摘要"],
  ["introduction", "Introduction"],
  ["related_work", "Related Work"],
  ["proposed_method", "Method"],
  ["experiments", "Experiments"],
  ["results", "Results"],
  ["discussion", "Discussion"],
  ["conclusion", "Conclusion"],
] as const;
export function blank(): Fields {
  return {
    title: "",
    target_venue: "",
    stage: "DRAFT",
    sources: [],
    bindings: [],
    sections: [
      ...skeleton.map(([key, title]) => ({
        key,
        title,
        kind: "SKELETON" as const,
        markdown: "",
        status: "NOT_STARTED" as const,
      })),
      ...manuscript.map(([key, title]) => ({
        key,
        title,
        kind: "MANUSCRIPT" as const,
        markdown: "",
        status: "NOT_STARTED" as const,
      })),
    ],
  };
}
export function fields(row: Revision): Fields {
  return {
    title: row.title,
    target_venue: row.target_venue ?? "",
    stage: row.stage ?? "DRAFT",
    sections: row.sections.map(({ key, title, kind, markdown, status }) => ({
      key,
      title,
      kind,
      markdown: markdown ?? "",
      status: status ?? "DRAFT",
    })),
    sources: (row.sources ?? []).map(
      ({ bundle_id, expected_bundle_sha256 }) => ({
        bundle_id,
        expected_bundle_sha256,
      }),
    ),
    bindings: (row.bindings ?? []).map(
      ({
        section_key,
        start_offset,
        end_offset,
        exact_quote,
        bundle_id,
        claim_id,
        claim_revision_id,
        expected_claim_sha256,
        relation,
        paper_id,
        format_check,
        metadata_check,
        support_check,
        note,
      }) => ({
        section_key,
        start_offset,
        end_offset,
        exact_quote,
        bundle_id,
        claim_id,
        claim_revision_id,
        expected_claim_sha256,
        relation: relation ?? "SUPPORTS",
        paper_id: paper_id ?? null,
        format_check: format_check ?? "UNCHECKED",
        metadata_check: metadata_check ?? "UNCHECKED",
        support_check: support_check ?? "UNCHECKED",
        note: note ?? "",
      }),
    ),
  };
}
