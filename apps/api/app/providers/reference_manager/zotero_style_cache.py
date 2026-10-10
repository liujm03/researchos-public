"""Read-only Ethereal Style publication cache; never inspect secrets or call its API."""

import configparser
import json
import os
import re
from pathlib import Path

_RANK_FIELDS = {"sciif", "sci", "sciBase", "sciUp", "sciUpSmall", "sciUpTop", "sciif5", "ccf"}


def _name(value: str) -> str:
    return " ".join(value.casefold().split())


class ZoteroStyleCache:
    def __init__(self, data_dir: Path | None = None, *, profile_root: Path | None = None) -> None:
        self.data_dir = data_dir
        self.profile_root = profile_root

    def _directory(self) -> Path | None:
        if self.data_dir is not None:
            return self.data_dir
        appdata = os.environ.get("APPDATA")
        if self.profile_root is None and not appdata:
            return None
        root = self.profile_root or Path(str(appdata)) / "Zotero" / "Zotero"
        ini = root / "profiles.ini"
        if not ini.is_file() or ini.stat().st_size > 65536:
            return None
        config = configparser.ConfigParser()
        config.read(ini, encoding="utf-8")
        entries = [section for section in config.sections() if section.startswith("Profile")]
        defaults = [
            section for section in entries if config.get(section, "Default", fallback="0") == "1"
        ]
        if len(defaults) == 1:
            entries = defaults
        if len(entries) != 1:
            return None  # Never guess which profile owns a library.
        path = config.get(entries[0], "Path", fallback="")
        if not path:
            return None
        profile = (
            root / path if config.get(entries[0], "IsRelative", fallback="1") == "1" else Path(path)
        )
        prefs = profile / "prefs.js"
        if not prefs.is_file() or prefs.stat().st_size > 2_097_152:
            return None
        text = prefs.read_text(encoding="utf-8")
        # Read only the data directory preference, never enumerate/emit other prefs.
        match = re.search(
            r'user_pref\("extensions\.zotero\.dataDir",\s*("(?:\\.|[^"\\])*")\s*\)', text
        )
        if match:
            value = json.loads(match[1])
            return Path(value) if isinstance(value, str) and value else None
        return Path.home() / "Zotero"

    def fields(self, publication_title: str) -> dict[str, str] | None:
        if not publication_title.strip():
            return {}
        try:
            directory = self._directory()
            if directory is None:
                return None
            path = directory / "zoterostyle.json"
            if not path.is_file():
                return None
            if path.stat().st_size > 8_388_608:
                return None
            raw = path.read_bytes()
            if len(raw) > 8_388_608:
                return None
            records = json.loads(raw)
            if not isinstance(records, dict) or len(records) > 20_000:
                return None
            wanted = _name(publication_title)
            exact: list[dict[str, object]] = []
            for title, record in records.items():
                if not isinstance(title, str) or not isinstance(record, dict):
                    continue
                aliases = [title]
                query = record.get("rankQuery")
                if isinstance(query, str) and len(query) < 8192:
                    try:
                        values = json.loads(query)
                        if isinstance(values, list):
                            # The first token names the service, not the journal.
                            aliases += [x for x in values[1:] if isinstance(x, str)]
                    except (json.JSONDecodeError, TypeError):
                        pass
                if wanted in {_name(alias) for alias in aliases}:
                    exact.append(record)
            fields: dict[str, str] = {}
            for index, record in enumerate(exact):
                rank = record.get("rank")
                if not isinstance(rank, dict):
                    continue
                for key in _RANK_FIELDS:
                    value = rank.get(key)
                    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                        rendered = str(value)
                        if not rendered or len(rendered) > 2000:
                            continue
                        name = f"plugin:zoterostyle:{key}"
                        if name in fields and fields[name] != rendered:
                            name += f" [duplicate {index + 1}]"
                        fields[name] = rendered
            if len(fields) > 40 or len(json.dumps(fields, ensure_ascii=False).encode()) > 16_000:
                return None
            return fields
        except (OSError, ValueError, configparser.Error):
            return None  # Unreadable is not an authoritative empty cache.
