import type { components } from "@/lib/generated";

type ServerAnnotation = components["schemas"]["PdfAnnotationOut"];
export type AnnotationKind = ServerAnnotation["kind"];
export type AnnotationGeometry = components["schemas"]["PdfGeometry"] & {
  points: components["schemas"]["PdfPoint"][];
};
// Drafts have no timestamps until the server returns an actual persisted receipt.
export type PdfAnnotation = Omit<
  ServerAnnotation,
  "geometries" | "created_at" | "updated_at"
> & {
  geometries: AnnotationGeometry[];
  created_at?: string;
  updated_at?: string;
};
export type AnnotationCollection = Omit<
  components["schemas"]["PdfAnnotationsOut"],
  "annotations"
> & {
  annotations: PdfAnnotation[];
};
export type AnnotationWrite = components["schemas"]["PdfAnnotationPut"] & {
  color: string;
  body: string;
  geometries: AnnotationGeometry[];
};

/** Compare the receipt's business fields, not property order or timestamps. */
export function sameAnnotation(actual: PdfAnnotation, write: AnnotationWrite) {
  return (
    actual.kind === write.kind &&
    actual.page === write.page &&
    actual.color === write.color &&
    actual.body === write.body &&
    JSON.stringify(actual.geometries.map(normalizeGeometry)) ===
      JSON.stringify(write.geometries.map(normalizeGeometry))
  );
}
function normalizeGeometry(shape: AnnotationGeometry) {
  return {
    geometry_kind: shape.geometry_kind,
    x: shape.x ?? null,
    y: shape.y ?? null,
    width: shape.width ?? null,
    height: shape.height ?? null,
    points: shape.points,
  };
}
