"""Offline exact template loader: fixed local catalog, no downloads or compilation."""

import hashlib
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Any

from app.domain.manuscript_templates import (
    FrozenManuscriptTemplate,
    ManuscriptTemplateDescriptor,
    ManuscriptTemplateFile,
    ManuscriptTemplateVariant,
)


def _plain(path: Path) -> None:
    for member in (path, *path.parents):
        value = member.lstat()
        if stat.S_ISLNK(value.st_mode) or getattr(value, "st_file_attributes", 0) & 0x400:
            raise ValueError("Template catalog must not contain links or reparse points")


def _read_plain(path: Path, bound: int) -> bytes:
    _plain(path)
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > bound:
        raise ValueError("Template resource is not a bounded plain file")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError("Template resource identity changed during opening")
        raw = stream.read(bound + 1)
        after = os.fstat(stream.fileno())
    _plain(path)
    current = path.stat()
    if (
        len(raw) > bound
        or before.st_size != len(raw)
        or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        or (after.st_dev, after.st_ino) != (current.st_dev, current.st_ino)
    ):
        raise ValueError("Template resource bytes or identity changed during reading")
    return raw


class LocalManuscriptTemplateProvider:
    provider_key = "local_verified_venue_templates"

    def __init__(self, root: Path, private_root: Path | None = None):
        self.root = root
        self.private_root = private_root

    def _catalog(self, root: Path | None = None) -> tuple[dict[str, Any], str]:
        selected_root = root or self.root
        _plain(selected_root)
        target = selected_root / "manifest.json"
        _plain(target)
        raw = _read_plain(target, 128 * 1024)
        value = json.loads(raw)
        if value.get("contract") != "researchos-template-resources-v1" or not isinstance(
            value.get("templates"), list
        ):
            raise ValueError("Template catalog contract differs")
        entries = value["templates"]
        if not 1 <= len(entries) <= 20 or len({row["key"] for row in entries}) != len(entries):
            raise ValueError("Template catalog keys differ")
        return value, hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _descriptor(row: dict[str, Any], digest: str) -> ManuscriptTemplateDescriptor:
        return ManuscriptTemplateDescriptor(
            key=row["key"],
            family=row["family"],
            version=row["version"],
            official_url=row["official_url"],
            license=row["license"],
            resource_status=row["resource_status"],
            manifest_sha256=digest,
            use_scope=row.get("use_scope", "OPEN_TEMPLATE_RESOURCE"),
            target_year=row.get("target_year"),
            permission_purpose=row.get("permission_purpose", ""),
            variants=tuple(
                ManuscriptTemplateVariant(
                    key=v["key"],
                    options=tuple(v["options"]),
                    anonymous=v["anonymous"],
                    note=v["note"],
                )
                for v in row["variants"]
            ),
        )

    def descriptors(self) -> tuple[ManuscriptTemplateDescriptor, ...]:
        catalog, digest = self._catalog()
        entries = [self._descriptor(row, digest) for row in catalog["templates"]]
        if self.private_root is not None and (self.private_root / "manifest.json").is_file():
            private, private_digest = self._catalog(self.private_root)
            entries.extend(self._descriptor(row, private_digest) for row in private["templates"])
        if len({row.key for row in entries}) != len(entries):
            raise ValueError("Public and private template keys must be distinct")
        return tuple(entries)

    def load_resources(
        self, key: str, expected_manifest_sha256: str, *, private_use_approved: bool = False
    ) -> FrozenManuscriptTemplate:
        catalog, digest = self._catalog()
        chosen_root = self.root
        private_selection = False
        row = next((item for item in catalog["templates"] if item["key"] == key), None)
        if row is None and self.private_root is not None:
            catalog, digest = self._catalog(self.private_root)
            row = next((item for item in catalog["templates"] if item["key"] == key), None)
            chosen_root = self.private_root
            private_selection = True
        if (
            not re.fullmatch(r"[0-9a-f]{64}", expected_manifest_sha256)
            or digest != expected_manifest_sha256
        ):
            raise ValueError("Template manifest changed; select its exact current version")
        if row is None:
            raise ValueError("Unknown template catalog key")
        if private_selection:
            if (
                row.get("use_scope") != "PRIVATE_AUTHOR_USE_ONLY"
                or row["resource_status"]
                != "PRIVATE_AUTHOR_RESOURCES_AVAILABLE_LICENSE_UNCONFIRMED"
                or not private_use_approved
            ):
                raise ValueError(
                    "Private author-use template requires the owner's explicit scope approval"
                )
        elif row["resource_status"] != "RESOURCE_AVAILABLE_NOT_VENUE_APPROVAL":
            raise ValueError(
                "Template redistribution/resources are not verified; official link only"
            )
        resources = row["runtime_files"]
        if not isinstance(resources, list) or not 1 <= len(resources) <= 10:
            raise ValueError("Template runtime inventory differs")
        files = []
        for item in resources:
            relative = PurePosixPath(item["source_path"])
            destination = item["destination_path"]
            if (
                not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./-]{0,239}", item["source_path"])
                or relative.is_absolute()
                or ".." in relative.parts
                or str(relative) != item["source_path"]
                or "\\" in item["source_path"]
                or any(part in {"", ".", ".."} for part in item["source_path"].split("/"))
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\.(cls|sty|bst)", destination)
            ):
                raise ValueError("Template resource path is invalid")
            path = chosen_root / relative
            content = _read_plain(path, 1024 * 1024)
            if (
                hashlib.sha256(content).hexdigest() != item["sha256"]
                or len(content) != item["size_bytes"]
            ):
                raise ValueError("Template resource bytes differ from the fixed manifest")
            files.append(ManuscriptTemplateFile(destination, content, item["sha256"]))
        if not files or len(files) > 10 or len({file.path for file in files}) != len(files):
            raise ValueError("Template runtime inventory differs")
        return FrozenManuscriptTemplate(
            self._descriptor(row, digest),
            tuple(files),
            private_use_approved=private_selection and private_use_approved,
        )
