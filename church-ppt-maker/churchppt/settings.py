"""프로그램 설정 (API 키, 저장 폴더 등)."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from . import APP_ID

DEFAULT_MODEL = "claude-opus-5-5"
MODEL_CHOICES = [
    ("claude-opus-5-5", "Claude Opus 5.5 (추천 · 가장 정확)"),
    ("claude-sonnet-5-5", "Claude Sonnet 5.5 (빠르고 저렴)"),
    ("claude-haiku-5-5", "Claude Haiku 5.5 (가장 저렴)"),
]
BIBLE_TRANSLATIONS = ["개역개정", "개역한글", "새번역", "쉬운성경", "현대인의성경", "공동번역", "NIV", "ESV", "KJV"]


def config_dir() -> Path:
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP_ID


def default_data_dir() -> Path:
    docs = Path.home() / "Documents"
    if not docs.exists():
        docs = Path.home()
    return docs / "교회PPT"


@dataclass
class AppSettings:
    api_key: str = ""
    model: str = DEFAULT_MODEL
    data_dir: str = ""
    current_template: str = "기본 - 검정 배경"
    bible_translation: str = "개역개정"
    church_name: str = ""

    # --- 폴더 ---------------------------------------------------------
    @property
    def root(self) -> Path:
        return Path(self.data_dir) if self.data_dir else default_data_dir()

    @property
    def lyrics_dir(self) -> Path:
        return self.root / "가사"

    @property
    def templates_dir(self) -> Path:
        return self.root / "템플릿"

    @property
    def services_dir(self) -> Path:
        return self.root / "예배순서"

    @property
    def output_dir(self) -> Path:
        return self.root / "완성된PPT"

    def ensure_dirs(self) -> None:
        for d in (self.lyrics_dir, self.templates_dir, self.services_dir, self.output_dir):
            d.mkdir(parents=True, exist_ok=True)

    def effective_api_key(self) -> str:
        return self.api_key.strip() or os.environ.get("ANTHROPIC_API_KEY", "").strip()

    # --- 저장 ---------------------------------------------------------
    @staticmethod
    def path() -> Path:
        return config_dir() / "settings.json"

    @classmethod
    def load(cls) -> "AppSettings":
        s = cls()
        try:
            data = json.loads(cls.path().read_text(encoding="utf-8"))
            names = {f.name for f in fields(cls)}
            for k, v in data.items():
                if k in names:
                    setattr(s, k, v)
        except (OSError, ValueError):
            pass
        return s

    def save(self) -> None:
        p = self.path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
