"""Display filenames shared by attachment producers and HTTP downloads."""

import unicodedata


def safe_attachment_filename(value: str | None) -> str:
    label = unicodedata.normalize("NFC", value or "artifact.bin")
    label = label.replace("\\", "/").rsplit("/", 1)[-1]
    label = "".join(
        char for char in label
        if not unicodedata.category(char).startswith("C") and char not in '<>:"|?*'
    ).strip(" .")
    return label[:320] or "artifact.bin"
