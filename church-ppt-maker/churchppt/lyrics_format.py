"""가사 텍스트(메모장 .txt) 형식 읽기/쓰기와 섹션 처리.

메모장 파일 형식 예시::

    제목: 주 은혜임을
    아티스트: 홍길동
    순서: V1, C, V2, C, B, C

    [Verse 1]
    첫 번째 줄
    두 번째 줄

    세 번째 줄          <- 섹션 안의 빈 줄 = 여기서 슬라이드 넘김

    [Chorus]
    ...

[대괄호] 머리말이 하나도 없으면 '구분 없이 쭉 이어지는 가사'로 처리한다.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

from .models import Section, Song

# ---------------------------------------------------------------------------
# 섹션 이름 정규화
# ---------------------------------------------------------------------------

# 소문자 이름 -> (표준 이름, 약어)
_LABEL_TABLE: dict[str, tuple[str, str]] = {}


def _register(names: list[str], canonical: str, abbrev: str) -> None:
    for n in names:
        _LABEL_TABLE[n] = (canonical, abbrev)


_register(["verse", "v", "벌스", "절"], "Verse", "V")
_register(["chorus", "c", "코러스", "후렴", "refrain", "후렴구"], "Chorus", "C")
_register(["pre-chorus", "prechorus", "pre chorus", "pc", "pre", "프리코러스",
           "프리 코러스", "프리-코러스", "프리"], "Pre-Chorus", "PC")
_register(["post-chorus", "postchorus", "post chorus", "psc", "포스트코러스"],
          "Post-Chorus", "PSC")
_register(["bridge", "b", "브릿지", "브리지"], "Bridge", "B")
_register(["intro", "i", "인트로", "전주"], "Intro", "I")
_register(["outro", "o", "아웃트로", "후주"], "Outro", "O")
_register(["ending", "e", "엔딩"], "Ending", "E")
_register(["tag", "t", "태그"], "Tag", "T")
_register(["interlude", "it", "간주"], "Interlude", "IT")
_register(["vamp", "vp", "뱀프"], "Vamp", "VP")

# 대괄호 없이 한 줄에 단독으로 써도 머리말로 인정하는 이름 (한 글자 약어 제외)
_PLAIN_HEADER_NAMES = {k for k in _LABEL_TABLE if len(k) > 2 or not k.isascii()}
_PLAIN_HEADER_NAMES.discard("절")
_PLAIN_HEADER_NAMES.discard("프리")

_LABEL_RE = re.compile(r"^(?P<name>[^\d]+?)\s*(?P<num>\d+)?$")
_KOREAN_VERSE_RE = re.compile(r"^(?P<num>\d+)\s*절$")


def _clean_label(text: str) -> str:
    t = text.strip()
    if t.startswith("[") and t.endswith("]"):
        t = t[1:-1]
    t = t.strip().rstrip(":：").strip()
    return re.sub(r"\s+", " ", t)


def _lookup(text: str) -> tuple[str, str, str] | None:
    """(표준이름, 약어, 번호) 또는 None."""
    t = _clean_label(text)
    if not t:
        return None
    m = _KOREAN_VERSE_RE.match(t)
    if m:
        return "Verse", "V", m.group("num")
    m = _LABEL_RE.match(t)
    if not m:
        return None
    name = m.group("name").strip().lower()
    num = m.group("num") or ""
    if name in _LABEL_TABLE:
        canonical, abbrev = _LABEL_TABLE[name]
        return canonical, abbrev, num
    return None


def normalize_label(text: str) -> str:
    """'1절' -> 'Verse 1', 'V2' -> 'Verse 2', '후렴' -> 'Chorus'. 모르는 이름은 그대로."""
    found = _lookup(text)
    if not found:
        return _clean_label(text)
    canonical, _, num = found
    return f"{canonical} {num}" if num else canonical


def label_abbrev(label: str) -> str:
    """'Verse 1' -> 'V1', 'Chorus' -> 'C'."""
    found = _lookup(label)
    if not found:
        return _clean_label(label)
    _, abbrev, num = found
    return f"{abbrev}{num}"


def is_bracket_header(line: str) -> bool:
    s = line.strip()
    return s.startswith("[") and s.endswith("]") and len(s) > 2


def is_header_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    if is_bracket_header(s):
        return True
    # 대괄호 없는 머리말: 'Verse 1', 'Chorus:', '후렴', '2절' 등
    t = _clean_label(s)
    if _KOREAN_VERSE_RE.match(t):
        return True
    m = _LABEL_RE.match(t)
    if m and m.group("name").strip().lower() in _PLAIN_HEADER_NAMES:
        return True
    return False


# ---------------------------------------------------------------------------
# 순서(송폼)
# ---------------------------------------------------------------------------

def parse_order(text: str) -> list[str]:
    """'V1 C V2 C B C' 또는 'Verse 1, Chorus, Bridge' -> 표준 이름 목록."""
    if not text or not text.strip():
        return []
    s = text
    for sep in ("→", "->", ">", "|", "/", "、", "，"):
        s = s.replace(sep, ",")
    s = re.sub(r"\s+-\s+", ",", s)
    if "," in s:
        raw = [t.strip(" -") for t in s.split(",")]
    else:
        raw = []
        for tok in s.split():
            tok = tok.strip(" -")
            if raw and tok.isdigit():
                raw[-1] = f"{raw[-1]} {tok}"
            else:
                raw.append(tok)
    return [normalize_label(t) for t in raw if t]


def format_order(order: list[str]) -> str:
    return ", ".join(order)


def _label_key(label: str) -> str:
    return normalize_label(label).lower()


def resolve_order(song: Song) -> tuple[list[Section], list[str]]:
    """순서대로 섹션 목록을 만든다. (찾지 못한 순서 항목들도 함께 돌려줌)"""
    if not song.order:
        return list(song.sections), []
    by_key: dict[str, Section] = {}
    by_abbrev: dict[str, Section] = {}
    for sec in song.sections:
        if sec.label:
            by_key.setdefault(_label_key(sec.label), sec)
            by_abbrev.setdefault(label_abbrev(sec.label).lower(), sec)
    result: list[Section] = []
    missing: list[str] = []
    for token in song.order:
        key = _label_key(token)
        sec = by_key.get(key) or by_abbrev.get(label_abbrev(token).lower())
        if sec is None:
            # 'Chorus' 를 썼는데 섹션 이름이 'Chorus 1' 인 경우 등
            for k, candidate in by_key.items():
                if k.startswith(key + " ") or key.startswith(k + " "):
                    sec = candidate
                    break
        if sec is None:
            missing.append(token)
        else:
            result.append(sec)
    if not result:
        return list(song.sections), missing
    return result, missing


# ---------------------------------------------------------------------------
# 텍스트 <-> Song
# ---------------------------------------------------------------------------

_META_RE = re.compile(
    r"^\s*(제목|곡명|아티스트|가수|작곡|순서|송폼|키|title|artist|order|key)\s*[:：]\s*(.*)$",
    re.IGNORECASE,
)
_META_FIELD = {
    "제목": "title", "곡명": "title", "title": "title",
    "아티스트": "artist", "가수": "artist", "작곡": "artist", "artist": "artist",
    "순서": "order", "송폼": "order", "order": "order",
    "키": "key", "key": "key",
}


def _trim_blank_markers(lines: list[str]) -> list[str]:
    out: list[str] = []
    for ln in lines:
        if ln == "" and (not out or out[-1] == ""):
            continue
        out.append(ln)
    while out and out[-1] == "":
        out.pop()
    return out


def parse_body(text: str) -> list[Section]:
    """[머리말] 로 나뉜 가사 본문을 섹션 목록으로.

    [대괄호] 머리말이 하나라도 있으면 대괄호 줄만 머리말로 본다
    (가사 중에 '후렴' 같은 단어만 있는 줄을 머리말로 착각하지 않도록).
    """
    lines = text.splitlines()
    header = is_bracket_header if any(is_bracket_header(ln) for ln in lines) else is_header_line
    sections: list[Section] = []
    current: Section | None = None
    for raw in lines:
        line = raw.rstrip()
        if header(line):
            current = Section(normalize_label(line), [])
            sections.append(current)
            continue
        if current is None:
            if not line.strip():
                continue
            current = Section("", [])
            sections.append(current)
        current.lines.append(line.strip() if line.strip() else "")
    for sec in sections:
        sec.lines = _trim_blank_markers(sec.lines)
    return [s for s in sections if s.lines or s.label]


def parse_song_text(text: str) -> Song:
    song = Song()
    body_lines: list[str] = []
    in_meta = True
    for raw in text.splitlines():
        if in_meta:
            m = _META_RE.match(raw)
            if m:
                field = _META_FIELD[m.group(1).lower()]
                value = m.group(2).strip()
                if field == "order":
                    song.order = parse_order(value)
                else:
                    setattr(song, field, value)
                continue
            if raw.strip():
                in_meta = False
        body_lines.append(raw)
    song.sections = parse_body("\n".join(body_lines))
    return song


def sections_to_body(sections: list[Section]) -> str:
    blocks: list[str] = []
    for sec in sections:
        lines = [ln for ln in sec.lines]
        block = "\n".join(lines)
        if sec.label:
            block = f"[{sec.label}]\n{block}" if block else f"[{sec.label}]"
        blocks.append(block)
    return "\n\n".join(blocks).strip() + "\n" if blocks else ""


def song_to_text(song: Song) -> str:
    head = [f"제목: {song.title}"]
    if song.artist:
        head.append(f"아티스트: {song.artist}")
    if song.key:
        head.append(f"키: {song.key}")
    if song.order:
        head.append(f"순서: {format_order(song.order)}")
    return "\n".join(head) + "\n\n" + sections_to_body(song.sections)


# ---------------------------------------------------------------------------
# AI 없이 하는 자동 나누기
# ---------------------------------------------------------------------------

def _stanzas(text: str) -> list[list[str]]:
    stanzas: list[list[str]] = []
    cur: list[str] = []
    for raw in text.splitlines():
        if raw.strip():
            cur.append(raw.strip())
        elif cur:
            stanzas.append(cur)
            cur = []
    if cur:
        stanzas.append(cur)
    return stanzas


def auto_structure(text: str) -> tuple[list[Section], list[str]]:
    """머리말이 있으면 그대로, 없으면 반복되는 연을 후렴으로 추정.

    반복되는 부분이 없으면 '쭉 이어지는 가사'(라벨 없음)로 둔다.
    """
    if any(is_header_line(ln) for ln in text.splitlines()):
        return parse_body(text), []
    stanzas = _stanzas(text)
    if not stanzas:
        return [], []
    keys = ["\n".join(s).replace(" ", "") for s in stanzas]
    counts: dict[str, int] = {}
    for k in keys:
        counts[k] = counts.get(k, 0) + 1
    if len(stanzas) == 1 or max(counts.values()) < 2:
        lines: list[str] = []
        for st in stanzas:
            if lines:
                lines.append("")
            lines.extend(st)
        return [Section("", lines)], []

    labels: dict[str, str] = {}
    sections: list[Section] = []
    order: list[str] = []
    verse_no = chorus_no = 0
    repeated = [k for k in dict.fromkeys(keys) if counts[k] >= 2]
    for k, st in zip(keys, stanzas):
        if k not in labels:
            if counts[k] >= 2:
                chorus_no += 1
                labels[k] = "Chorus" if chorus_no == 1 else f"Chorus {chorus_no}"
            else:
                verse_no += 1
                labels[k] = f"Verse {verse_no}"
            sections.append(Section(labels[k], list(st)))
        order.append(labels[k])
    if len(repeated) == 0:
        order = []
    return sections, order


# ---------------------------------------------------------------------------
# 슬라이드 나누기
# ---------------------------------------------------------------------------

def chunk_lines(lines: list[str], per_slide: int) -> list[list[str]]:
    """빈 줄 표시("")는 강제 넘김, 나머지는 per_slide 줄씩 고르게 나눈다."""
    per_slide = max(1, per_slide)
    groups: list[list[str]] = [[]]
    for ln in lines:
        if ln == "":
            if groups[-1]:
                groups.append([])
        else:
            groups[-1].append(ln)
    slides: list[list[str]] = []
    for g in groups:
        if not g:
            continue
        n_slides = math.ceil(len(g) / per_slide)
        base, extra = divmod(len(g), n_slides)
        idx = 0
        for i in range(n_slides):
            size = base + (1 if i < extra else 0)
            slides.append(g[idx: idx + size])
            idx += size
    return slides


# ---------------------------------------------------------------------------
# 파일
# ---------------------------------------------------------------------------

_BAD_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]')


def safe_filename(name: str, default: str = "제목없음") -> str:
    s = _BAD_CHARS.sub(" ", name).strip().strip(".")
    s = re.sub(r"\s+", " ", s)
    return (s[:80] or default)


def read_text_file(path: str | Path) -> str:
    data = Path(path).read_bytes()
    for enc in ("utf-8-sig", "cp949", "utf-16"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def write_text_file(path: str | Path, text: str) -> None:
    """메모장에서 바로 열리도록 UTF-8(BOM) + 윈도우 줄바꿈으로 저장."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write(text.replace("\r\n", "\n"))
