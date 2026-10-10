"""Atomic canonical Markdown persistence with explicit disk-hash conflict handling."""

import hashlib
import os
import uuid
from pathlib import Path

from app.domain.note_output import NoteFileState, SavedNoteFile
from app.errors import DomainError

MAX_NOTE_BYTES = 1_048_576


class LocalNoteOutputProvider:
    def __init__(self, root: Path) -> None:
        self.root = root.absolute()

    def _path(self, relative_path: str) -> Path:
        value = Path(relative_path)
        if (
            value.is_absolute()
            or value.suffix.lower() != ".md"
            or any(part in {"", ".", ".."} for part in value.parts)
        ):
            raise DomainError(
                "NOTE_PATH_INVALID", "Note must use an approved relative Markdown path", 422
            )
        if self.root.is_symlink():
            raise DomainError(
                "NOTE_PATH_INVALID", "Approved note root cannot be a symbolic link", 409
            )
        target = self.root / value
        if not target.resolve().is_relative_to(self.root.resolve()) or target.is_symlink():
            raise DomainError(
                "NOTE_PATH_INVALID", "Note path escapes its approved output root", 409
            )
        return target

    def inspect(self, relative_path: str) -> NoteFileState:
        target = self._path(relative_path)
        if not target.exists():
            return NoteFileState(str(target), None, 0)
        if not target.is_file() or target.stat().st_size > MAX_NOTE_BYTES:
            raise DomainError(
                "NOTE_OUTPUT_CONFLICT", "Existing note cannot be safely compared", 409
            )
        content = target.read_bytes()
        return NoteFileState(str(target), hashlib.sha256(content).hexdigest(), len(content))

    def save(
        self, relative_path: str, content: bytes, *, expected_current_sha256: str | None
    ) -> SavedNoteFile:
        if not content or len(content) > MAX_NOTE_BYTES:
            raise DomainError(
                "NOTE_OUTPUT_INVALID", "Canonical note exceeds its file size bound", 422
            )
        try:
            content.decode("utf-8")
        except UnicodeError:
            raise DomainError(
                "NOTE_OUTPUT_INVALID", "Canonical Markdown must be UTF-8", 422
            ) from None
        target = self._path(relative_path)
        state = self.inspect(relative_path)
        digest = hashlib.sha256(content).hexdigest()
        if state.sha256 == digest:
            return SavedNoteFile(str(target), digest, len(content))
        if state.sha256 != expected_current_sha256:
            raise DomainError(
                "NOTE_OUTPUT_CONFLICT",
                "Disk note differs from the owner's approved file version",
                409,
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.parent / f".researchos-{uuid.uuid4().hex}.tmp"
        revision_path: Path | None = None
        try:
            with temporary.open("xb") as writer:
                writer.write(content)
                writer.flush()
                os.fsync(writer.fileno())
            fresh = self.inspect(relative_path)
            if fresh.sha256 != state.sha256:
                raise DomainError(
                    "NOTE_OUTPUT_CONFLICT", "Note changed while preparing the approved write", 409
                )
            if state.sha256 is not None:
                revision_path = (
                    self.root / ".researchos-revisions" / state.sha256[:2] / f"{state.sha256}.md"
                )
                if (
                    not revision_path.resolve().is_relative_to(self.root.resolve())
                    or revision_path.is_symlink()
                ):
                    raise DomainError(
                        "NOTE_OUTPUT_CONFLICT",
                        "Prior note archive escapes the approved output root",
                        409,
                    )
                revision_path.parent.mkdir(parents=True, exist_ok=True)
                original = target.read_bytes()
                if hashlib.sha256(original).hexdigest() != state.sha256:
                    raise DomainError(
                        "NOTE_OUTPUT_CONFLICT",
                        "Note changed before saving its previous version",
                        409,
                    )
                try:
                    with revision_path.open("xb") as archive:
                        archive.write(original)
                        archive.flush()
                        os.fsync(archive.fileno())
                except FileExistsError:
                    if (
                        not revision_path.is_file()
                        or revision_path.stat().st_size > MAX_NOTE_BYTES
                        or hashlib.sha256(revision_path.read_bytes()).hexdigest() != state.sha256
                    ):
                        raise DomainError(
                            "NOTE_OUTPUT_CONFLICT", "Saved prior note revision has changed", 409
                        ) from None
                if self.inspect(relative_path).sha256 != state.sha256:
                    raise DomainError(
                        "NOTE_OUTPUT_CONFLICT",
                        "Note changed while archiving its previous version",
                        409,
                    )
                os.replace(temporary, target)
            else:
                # Create exclusively: an unmanaged note created during the write
                # cannot be replaced by an approval for an absent file.
                os.link(temporary, target)
            return SavedNoteFile(
                str(target),
                digest,
                len(content),
                state.sha256,
                str(revision_path) if revision_path else None,
            )
        except FileExistsError:
            raise DomainError(
                "NOTE_OUTPUT_CONFLICT", "A new note appeared after the owner approved creation", 409
            ) from None
        finally:
            temporary.unlink(missing_ok=True)
