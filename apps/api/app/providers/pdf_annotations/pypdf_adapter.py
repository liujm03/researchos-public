import io

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    FloatObject,
    NameObject,
    NumberObject,
    TextStringObject,
)

from app.errors import DomainError
from app.schemas_pdf_annotations import PdfAnnotationOut

MAX_PDF_PAGES = 2000
MAX_EXPORT_BYTES = 128 * 1024 * 1024


def _array(values: list[float]) -> ArrayObject:
    return ArrayObject([FloatObject(value) for value in values])


class PypdfAnnotationProvider:
    def _read(self, source: bytes) -> PdfReader:
        try:
            reader = PdfReader(io.BytesIO(source), strict=True)
            if reader.is_encrypted:
                raise DomainError("PDF_ENCRYPTED", "Password-protected PDF cannot be marked", 422)
            count = len(reader.pages)
            if count < 1 or count > MAX_PDF_PAGES:
                raise DomainError("PDF_PAGE_LIMIT", "PDF must contain 1 to 2000 pages", 422)
            return reader
        except DomainError:
            raise
        except Exception as exc:
            raise DomainError(
                "PDF_INVALID", "PDF cannot be safely opened for annotations", 422
            ) from exc

    def page_count(self, source: bytes) -> int:
        return len(self._read(source).pages)

    def export(self, source: bytes, annotations: list[PdfAnnotationOut]) -> bytes:
        reader = self._read(source)
        writer = PdfWriter()
        # Copy pages only. Do not propagate document JavaScript, embedded files or OpenAction.
        for page in reader.pages:
            writer.add_page(page)
        for item in annotations:
            if item.deleted_at is not None:
                continue
            page = writer.pages[item.page - 1]
            crop, media = page.cropbox, page.mediabox
            # PDF.js page.view uses the positive MediaBox/CropBox intersection.
            x0 = max(float(crop.left), float(media.left))
            y0 = max(float(crop.bottom), float(media.bottom))
            x1 = min(float(crop.right), float(media.right))
            y1 = min(float(crop.top), float(media.top))
            if x1 <= x0 or y1 <= y0:
                x0, y0 = float(media.left), float(media.bottom)
                x1, y1 = float(media.right), float(media.top)
            width, height = x1 - x0, y1 - y0
            if width <= 0 or height <= 0:
                raise DomainError("PDF_PAGE_INVALID", "PDF page has invalid visible bounds", 422)
            rotation = int(page.rotation or 0) % 360
            if rotation not in (0, 90, 180, 270):
                rotation = 0  # PDF.js falls back to zero for non-quarter-turn Rotate.

            def point(
                u: float,
                v: float,
                rotation: int = rotation,
                x0: float = x0,
                y0: float = y0,
                width: float = width,
                height: float = height,
            ) -> tuple[float, float]:
                if rotation == 90:
                    return x0 + v * width, y0 + u * height
                if rotation == 180:
                    return x0 + (1 - u) * width, y0 + v * height
                if rotation == 270:
                    return x0 + (1 - v) * width, y0 + (1 - u) * height
                return x0 + u * width, y0 + (1 - v) * height

            rgb = [int(item.color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
            annotation = DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Annot"),
                    NameObject("/Subtype"): NameObject(
                        {
                            "HIGHLIGHT": "/Highlight",
                            "UNDERLINE": "/Underline",
                            "COMMENT": "/Text",
                            "INK": "/Ink",
                        }[item.kind]
                    ),
                    NameObject("/C"): _array(rgb),
                    NameObject("/Contents"): TextStringObject(item.body),
                    NameObject("/NM"): TextStringObject(str(item.id)),
                    NameObject("/F"): NumberObject(4),
                    NameObject("/T"): TextStringObject("ResearchOS"),
                }
            )
            coordinates: list[tuple[float, float]] = []
            quads: list[float] = []
            strokes = ArrayObject()
            underline_segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
            for geometry in item.geometries:
                if geometry.geometry_kind == "STROKE":
                    pts = [point(p.x, p.y) for p in geometry.points]
                    coordinates.extend(pts)
                    strokes.append(_array([value for p in pts for value in p]))
                else:
                    assert geometry.x is not None and geometry.y is not None
                    assert geometry.width is not None and geometry.height is not None
                    x, y, w, h = geometry.x, geometry.y, geometry.width, geometry.height
                    corners = [point(x, y), point(x + w, y), point(x, y + h), point(x + w, y + h)]
                    coordinates.extend(corners)
                    quads.extend(value for p in corners for value in p)
                    underline_segments.append((point(x, y + h), point(x + w, y + h)))
            xs, ys = [p[0] for p in coordinates], [p[1] for p in coordinates]
            annotation[NameObject("/Rect")] = _array([min(xs), min(ys), max(xs), max(ys)])
            if item.kind in ("HIGHLIGHT", "UNDERLINE"):
                annotation[NameObject("/QuadPoints")] = _array(quads)
                annotation[NameObject("/CA")] = FloatObject(0.35 if item.kind == "HIGHLIGHT" else 1)
                if item.kind == "UNDERLINE":
                    # Explicit appearance preserves the display-bottom edge on rotated pages.
                    left, bottom, right, top = min(xs) - 1, min(ys) - 1, max(xs) + 1, max(ys) + 1
                    annotation[NameObject("/Rect")] = _array([left, bottom, right, top])
                    appearance = DecodedStreamObject()
                    appearance.update(
                        {
                            NameObject("/Type"): NameObject("/XObject"),
                            NameObject("/Subtype"): NameObject("/Form"),
                            NameObject("/FormType"): NumberObject(1),
                            NameObject("/BBox"): _array([0, 0, right - left, top - bottom]),
                            NameObject("/Resources"): DictionaryObject(),
                        }
                    )
                    commands = ["q", f"{rgb[0]:.6f} {rgb[1]:.6f} {rgb[2]:.6f} RG", "1.5 w"]
                    for start, end in underline_segments:
                        commands.append(
                            f"{start[0] - left:.6f} {start[1] - bottom:.6f} m {end[0] - left:.6f} {end[1] - bottom:.6f} l S"
                        )
                    commands.append("Q")
                    appearance.set_data("\n".join(commands).encode("ascii"))
                    annotation[NameObject("/AP")] = DictionaryObject(
                        {NameObject("/N"): writer._add_object(appearance)}
                    )
            elif item.kind == "INK":
                # Vertical or horizontal strokes still need a nonempty appearance box.
                annotation[NameObject("/Rect")] = _array(
                    [min(xs) - 1, min(ys) - 1, max(xs) + 1, max(ys) + 1]
                )
                annotation[NameObject("/InkList")] = strokes
                annotation[NameObject("/BS")] = DictionaryObject(
                    {NameObject("/W"): FloatObject(1.5)}
                )
            else:
                annotation[NameObject("/Name")] = NameObject("/Comment")
            writer.add_annotation(item.page - 1, annotation)
        buffer = io.BytesIO()
        writer.write(buffer)
        result = buffer.getvalue()
        if len(result) > MAX_EXPORT_BYTES:
            raise DomainError("PDF_EXPORT_TOO_LARGE", "Annotated PDF exceeds export limit", 413)
        return result
