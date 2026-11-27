"""PPT 디자인(템플릿) 설정. JSON 파일로 저장/불러오기."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

DEFAULT_FONT = "맑은 고딕"


@dataclass
class TextStyle:
    font: str = DEFAULT_FONT
    size: int = 40               # pt
    color: str = "#FFFFFF"
    bold: bool = True
    outline: bool = False
    outline_color: str = "#000000"
    outline_width: float = 1.5   # pt
    shadow: bool = True


@dataclass
class TemplateDesign:
    name: str = "기본 - 검정 배경"

    # --- 'PPT 소스 파일' 모드 -------------------------------------------
    # 값이 있으면 이 PPT 파일의 슬라이드 디자인을 복제해서 사용한다.
    source_pptx: str = ""
    source_lyrics_slide: int = 0    # 1부터 시작, 0 = 자동 감지
    source_cover_slide: int = 0
    source_content_slide: int = 0

    # --- 직접 디자인 모드 ------------------------------------------------
    ratio: str = "16:9"              # "16:9" | "4:3"
    bg_color: str = "#000000"
    bg_image: str = ""
    bg_dim: int = 0                  # 배경 이미지 어둡게 (0~90 %)

    lyrics: TextStyle = field(default_factory=lambda: TextStyle(size=44))
    lyrics_align: str = "center"     # left | center | right
    lyrics_anchor: str = "middle"    # top | middle | bottom
    margin: float = 0.06             # 좌우/상하 여백 (슬라이드 폭 비율)
    line_spacing: float = 1.25

    show_label: bool = False         # 슬라이드 구석에 'Verse 1' 표시
    label_style: TextStyle = field(default_factory=lambda: TextStyle(size=16, bold=False, shadow=False, color="#BBBBBB"))
    show_song_title: bool = False    # 곡 첫 슬라이드 위쪽에 곡 제목 작게 표시

    title_style: TextStyle = field(default_factory=lambda: TextStyle(size=60))
    heading_style: TextStyle = field(default_factory=lambda: TextStyle(size=40, color="#FFE08A"))
    body_style: TextStyle = field(default_factory=lambda: TextStyle(size=34, bold=False))
    content_align: str = "left"

    # --- 슬라이드 구성 ----------------------------------------------------
    lines_per_slide: int = 2
    song_title_slide: bool = False   # 곡마다 제목 슬라이드 먼저
    blank_after_song: bool = True    # 곡 끝에 빈 슬라이드
    section_mode: str = "part"       # part = 파트마다 구역, song = 곡마다 구역
    verses_per_slide: int = 2        # 성경 본문 한 장당 절 수
    auto_shrink: bool = True         # 넘치는 글자 자동 축소

    @property
    def uses_source(self) -> bool:
        return bool(self.source_pptx)

    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TemplateDesign":
        d = cls()
        names = {f.name for f in fields(cls)}
        for key, value in data.items():
            if key not in names:
                continue
            current = getattr(d, key)
            if isinstance(current, TextStyle) and isinstance(value, dict):
                ts_names = {f.name for f in fields(TextStyle)}
                setattr(d, key, TextStyle(**{k: v for k, v in value.items() if k in ts_names}))
            else:
                setattr(d, key, value)
        return d

    def save(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "TemplateDesign":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def builtin_designs() -> list[TemplateDesign]:
    """처음 실행할 때 만들어 두는 기본 템플릿들."""
    black = TemplateDesign()

    lower = TemplateDesign(
        name="방송용 하단 자막",
        bg_color="#000000",
        lyrics=TextStyle(size=36, outline=True, outline_width=2.0, shadow=True),
        lyrics_anchor="bottom",
        margin=0.05,
        lines_per_slide=2,
        blank_after_song=True,
    )

    light = TemplateDesign(
        name="밝은 배경",
        bg_color="#F6F1E7",
        lyrics=TextStyle(size=44, color="#2B2B2B", shadow=False),
        label_style=TextStyle(size=16, bold=False, shadow=False, color="#8A8170"),
        title_style=TextStyle(size=60, color="#2B2B2B", shadow=False),
        heading_style=TextStyle(size=40, color="#7A4E1D", shadow=False),
        body_style=TextStyle(size=34, color="#2B2B2B", bold=False, shadow=False),
    )

    navy = TemplateDesign(
        name="네이비",
        bg_color="#16233F",
        lyrics=TextStyle(size=44, color="#FFFFFF"),
        heading_style=TextStyle(size=40, color="#9CC3FF"),
    )
    return [black, lower, light, navy]
