"""프로그램 전체에서 쓰는 데이터 구조."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Section:
    """곡의 한 부분 (Verse 1, Chorus, Bridge ...).

    label 이 빈 문자열이면 구분 없이 쭉 이어지는 가사라는 뜻.
    lines 안의 빈 문자열("")은 '여기서 슬라이드를 넘긴다'는 표시.
    """

    label: str
    lines: list[str] = field(default_factory=list)

    @property
    def text_lines(self) -> list[str]:
        return [ln for ln in self.lines if ln.strip()]


@dataclass
class Song:
    title: str = ""
    artist: str = ""
    key: str = ""
    order: list[str] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)

    @property
    def is_structured(self) -> bool:
        return any(s.label for s in self.sections)


# 슬라이드 종류
KIND_LYRICS = "lyrics"      # 찬양 가사
KIND_COVER = "cover"        # 표지 / 곡 제목 슬라이드
KIND_CONTENT = "content"    # 제목 + 본문 (성경, 설교, 광고)
KIND_BLANK = "blank"        # 배경만 있는 빈 슬라이드


@dataclass
class SlideSpec:
    """PPT 한 장에 들어갈 내용. 디자인과는 무관하다."""

    kind: str
    section_name: str           # PowerPoint '구역(섹션)' 이름
    section_id: int             # 같은 id 끼리 한 구역으로 묶인다
    heading: str = ""           # 곡 제목 / 성경 구절 / 설교 제목
    label: str = ""             # Verse 1, Chorus ...
    lines: list[str] = field(default_factory=list)
    subtitle: str = ""
    notes: str = ""             # 발표자 노트
    hint: str = ""              # "scripture" 이면 절 번호를 작게 표시
    song: str = ""              # 가사 슬라이드가 속한 곡 제목
