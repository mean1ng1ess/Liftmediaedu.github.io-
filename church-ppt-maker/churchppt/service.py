"""예배 순서(찬양, 말씀, 설교, 광고...)와 슬라이드 목록 변환."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .design import TemplateDesign
from .lyrics_format import (chunk_lines, format_order, parse_body, parse_order,
                            resolve_order, sections_to_body)
from .models import (KIND_BLANK, KIND_CONTENT, KIND_COVER, KIND_LYRICS,
                     SlideSpec, Song)

ITEM_COVER = "cover"
ITEM_SONG = "song"
ITEM_SCRIPTURE = "scripture"
ITEM_SERMON = "sermon"
ITEM_TEXT = "text"

ITEM_LABELS = {
    ITEM_COVER: "표지",
    ITEM_SONG: "찬양",
    ITEM_SCRIPTURE: "성경 본문",
    ITEM_SERMON: "설교",
    ITEM_TEXT: "광고/텍스트",
}

ITEM_ICONS = {
    ITEM_COVER: "🏠",
    ITEM_SONG: "🎵",
    ITEM_SCRIPTURE: "📖",
    ITEM_SERMON: "🎤",
    ITEM_TEXT: "📝",
}


def default_data(kind: str) -> dict:
    return {
        ITEM_COVER: {"title": "주일 예배", "subtitle": "", "date": ""},
        ITEM_SONG: {"title": "", "artist": "", "key": "", "order": "", "body": ""},
        ITEM_SCRIPTURE: {"reference": "", "translation": "개역개정", "text": ""},
        ITEM_SERMON: {"title": "", "preacher": "", "reference": "", "body": ""},
        ITEM_TEXT: {"title": "", "body": ""},
    }[kind].copy()


@dataclass
class ServiceItem:
    kind: str
    data: dict = field(default_factory=dict)

    @classmethod
    def new(cls, kind: str, **values) -> "ServiceItem":
        d = default_data(kind)
        d.update(values)
        return cls(kind, d)

    def display_name(self) -> str:
        d = self.data
        if self.kind == ITEM_SONG:
            name = d.get("title") or "(제목 없는 찬양)"
        elif self.kind == ITEM_SCRIPTURE:
            name = d.get("reference") or "(본문 미입력)"
        elif self.kind == ITEM_SERMON:
            name = d.get("title") or "(설교 제목 없음)"
        elif self.kind == ITEM_COVER:
            name = d.get("title") or "표지"
        else:
            name = d.get("title") or "(제목 없음)"
        return f"{ITEM_ICONS[self.kind]} {ITEM_LABELS[self.kind]} · {name}"


# ---------------------------------------------------------------------------
# 찬양 <-> 항목 데이터
# ---------------------------------------------------------------------------

def item_to_song(item: ServiceItem) -> Song:
    d = item.data
    return Song(
        title=d.get("title", "").strip(),
        artist=d.get("artist", "").strip(),
        key=d.get("key", "").strip(),
        order=parse_order(d.get("order", "")),
        sections=parse_body(d.get("body", "")),
    )


def song_to_data(song: Song) -> dict:
    return {
        "title": song.title,
        "artist": song.artist,
        "key": song.key,
        "order": format_order(song.order),
        "body": sections_to_body(song.sections),
    }


# ---------------------------------------------------------------------------
# 예배 파일
# ---------------------------------------------------------------------------

@dataclass
class Service:
    name: str = "새 예배"
    items: list[ServiceItem] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(
            {"version": 1, "name": self.name,
             "items": [{"kind": it.kind, "data": it.data} for it in self.items]},
            ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, text: str) -> "Service":
        raw = json.loads(text)
        items = []
        for it in raw.get("items", []):
            kind = it.get("kind")
            if kind not in ITEM_LABELS:
                continue
            data = default_data(kind)
            data.update(it.get("data", {}))
            items.append(ServiceItem(kind, data))
        return cls(raw.get("name", "예배"), items)

    def save(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "Service":
        return cls.from_json(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 슬라이드 목록 만들기
# ---------------------------------------------------------------------------

def _blocks(text: str) -> list[list[str]]:
    """빈 줄로 나뉜 덩어리들."""
    blocks: list[list[str]] = []
    cur: list[str] = []
    for raw in text.splitlines():
        if raw.strip():
            cur.append(raw.strip())
        elif cur:
            blocks.append(cur)
            cur = []
    if cur:
        blocks.append(cur)
    return blocks


def _lines_with_breaks(text: str) -> list[str]:
    out: list[str] = []
    for raw in text.splitlines():
        out.append(raw.strip())
    return out


class _Ids:
    def __init__(self) -> None:
        self.value = 0

    def next(self) -> int:
        self.value += 1
        return self.value


def song_slides(song: Song, design: TemplateDesign, ids: _Ids) -> list[SlideSpec]:
    title = song.title or "찬양"
    seq, _ = resolve_order(song)
    slides: list[SlideSpec] = []
    by_song = design.section_mode == "song"
    song_id = ids.next()

    if design.song_title_slide:
        slides.append(SlideSpec(KIND_COVER, title, song_id, heading=title,
                                subtitle=song.artist, notes=f"{title} | 제목"))
    first = True
    last_name, last_id = title, song_id
    for i, sec in enumerate(seq):
        if by_song:
            name, sid = title, song_id
        else:
            name = f"{title} - {sec.label}" if sec.label else title
            sid = song_id if (i == 0 and not design.song_title_slide) else ids.next()
        for chunk in chunk_lines(sec.lines, design.lines_per_slide):
            slides.append(SlideSpec(
                KIND_LYRICS, name, sid,
                heading=title if (first and design.show_song_title) else "",
                label=sec.label, lines=chunk, song=title,
                notes=f"{title} | {sec.label}" if sec.label else title,
            ))
            first = False
        last_name, last_id = name, sid
    if design.blank_after_song and slides:
        slides.append(SlideSpec(KIND_BLANK, last_name, last_id, notes=f"{title} 끝"))
    return slides


def item_slides(item: ServiceItem, design: TemplateDesign, ids: _Ids | None = None) -> list[SlideSpec]:
    ids = ids or _Ids()
    d = item.data
    if item.kind == ITEM_SONG:
        return song_slides(item_to_song(item), design, ids)

    if item.kind == ITEM_COVER:
        sub = [x for x in (d.get("subtitle", ""), d.get("date", "")) if x.strip()]
        return [SlideSpec(KIND_COVER, "표지", ids.next(), heading=d.get("title", ""),
                          subtitle="\n".join(sub))]

    if item.kind == ITEM_SCRIPTURE:
        ref = d.get("reference", "").strip() or "성경 본문"
        tr = d.get("translation", "").strip()
        heading = f"{ref} ({tr})" if tr else ref
        sid = ids.next()
        chunks = chunk_lines(_lines_with_breaks(d.get("text", "")), design.verses_per_slide)
        if not chunks:
            return [SlideSpec(KIND_COVER, f"말씀 - {ref}", sid, heading=heading)]
        return [SlideSpec(KIND_CONTENT, f"말씀 - {ref}", sid, heading=heading, lines=c,
                          notes=heading, hint="scripture") for c in chunks]

    if item.kind == ITEM_SERMON:
        title = d.get("title", "").strip() or "설교"
        sid = ids.next()
        sub = [x.strip() for x in (d.get("reference", ""), d.get("preacher", "")) if x.strip()]
        slides = [SlideSpec(KIND_COVER, f"설교 - {title}", sid, heading=title,
                            subtitle="\n".join(sub), notes=title)]
        for block in _blocks(d.get("body", "")):
            slides.append(SlideSpec(KIND_CONTENT, f"설교 - {title}", sid, heading=title,
                                    lines=block, notes=title))
        return slides

    # ITEM_TEXT
    title = d.get("title", "").strip()
    sid = ids.next()
    blocks = _blocks(d.get("body", ""))
    name = title or "안내"
    if not blocks:
        return [SlideSpec(KIND_COVER, name, sid, heading=title)]
    return [SlideSpec(KIND_CONTENT, name, sid, heading=title, lines=b) for b in blocks]


def service_to_slides(items: list[ServiceItem], design: TemplateDesign) -> list[SlideSpec]:
    ids = _Ids()
    slides: list[SlideSpec] = []
    for item in items:
        slides.extend(item_slides(item, design, ids))
    return slides
