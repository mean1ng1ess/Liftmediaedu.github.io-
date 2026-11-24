"""무료 악보 가사 읽기 - Windows 기본 글자 인식(Windows.Media.Ocr) 사용.

인터넷 연결, 로그인, API 키가 필요 없다 (Windows 10/11, 한국어 OCR 기능 필요).

1) 사진/PDF -> 흑백·확대 -> 가로로 잘라(타일) OCR
2) 단어 위치로 줄 재구성: 음표 밑에 한 글자씩 떨어진 가사를 다시 붙이고
3) 오선 하나 밑에 1절/2절 가사가 겹쳐 있으면 Verse 1, Verse 2 로 나눈다.
"""
from __future__ import annotations

import importlib
import os
import re
import statistics
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .lyrics_format import _CHORD_TOKEN, _JUNK_LINE
from .models import Section, Song


class OcrError(Exception):
    pass


@dataclass
class OcrWord:
    text: str
    x: float
    y: float
    w: float
    h: float


@dataclass
class OcrLine:
    words: list[OcrWord] = field(default_factory=list)

    @property
    def top(self) -> float:
        return min(w.y for w in self.words)

    @property
    def bottom(self) -> float:
        return max(w.y + w.h for w in self.words)

    @property
    def height(self) -> float:
        return statistics.median(w.h for w in self.words)

    @property
    def cy(self) -> float:
        return (self.top + self.bottom) / 2

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


# ---------------------------------------------------------------------------
# 글자 정리 (Windows 없이도 테스트 가능한 순수 함수)
# ---------------------------------------------------------------------------

_HANGUL = re.compile(r"[가-힣]")
_VERSE_MARK = re.compile(r"^(\d)\s*[.)]$|^(\d)\s*[.)]?\s*절$")
_EXTRA_JUNK = re.compile(r"(작사|작곡|편곡|words|music|arr\.|ccli|capo|tempo|♩|bpm|ⓒ|저작권|성가대|=\s*\d+)", re.I)


def _is_noise_word(t: str) -> bool:
    s = t.strip()
    if not s:
        return True
    if _CHORD_TOKEN.match(s.strip("()[]")):
        return True
    letters = [c for c in s if c.isalpha()]
    return not letters  # 숫자/기호만


def _clean_line_words(line: OcrLine) -> tuple[list[OcrWord], int | None]:
    """잡음 단어 제거. 줄 앞 '1.' '2.' 같은 절 표시는 따로 돌려준다."""
    words = sorted(line.words, key=lambda w: w.x)
    verse = None
    if words:
        m = _VERSE_MARK.match(words[0].text.strip())
        if m:
            verse = int(m.group(1) or m.group(2))
            words = words[1:]
        else:
            m = re.match(r"^(\d)[.)](.+)$", words[0].text.strip())
            if m:
                verse = int(m.group(1))
                words = [OcrWord(m.group(2), *_xywh(words[0]))] + words[1:]
    return [w for w in words if not _is_noise_word(w.text)], verse


def _xywh(w: OcrWord):
    return w.x, w.y, w.w, w.h


def _is_lyric(words: list[OcrWord], korean: bool) -> bool:
    text = "".join(w.text for w in words)
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 2:
        return False
    if _JUNK_LINE.search(" ".join(w.text for w in words)) or _EXTRA_JUNK.search(text):
        return False
    hangul = len(_HANGUL.findall(text))
    return hangul / len(letters) >= 0.6 if korean else True


def join_syllables(words: list[OcrWord]) -> str:
    """음표마다 떨어진 글자('주 님 의 사 랑')를 이어 붙인다.

    대부분 한 글자씩이면 간격이 특히 넓은 곳만 띄어 쓰고 나머지는 붙인다.
    """
    if not words:
        return ""
    single = sum(1 for w in words if len(w.text) == 1 and _HANGUL.match(w.text))
    if single < max(2, len(words) * 0.6):
        return " ".join(w.text for w in words)
    gaps = [b.x - (a.x + a.w) for a, b in zip(words, words[1:])]
    char_w = statistics.median(w.w / max(1, len(w.text)) for w in words)
    med_gap = statistics.median(gaps) if gaps else 0
    threshold = max(char_w * 1.6, med_gap * 2.2)
    out = words[0].text
    for gap, w in zip(gaps, words[1:]):
        out += (" " if gap > threshold else "") + w.text
    return out


@dataclass
class _LyricLine:
    text: str
    top: float
    bottom: float
    height: float
    verse: int | None
    page: int


def _find_title(lines: list[OcrLine], page_h: float) -> OcrLine | None:
    top_lines = [ln for ln in lines if ln.cy < page_h * 0.22 and len(ln.text.strip()) >= 2
                 and not _EXTRA_JUNK.search(ln.text) and not _JUNK_LINE.search(ln.text)]
    if not top_lines:
        return None
    best = max(top_lines, key=lambda ln: ln.height)
    others = [ln.height for ln in lines if ln is not best] or [best.height]
    return best if best.height >= statistics.median(others) * 1.3 else None


def regroup_rows(lines: list[OcrLine]) -> list[OcrLine]:
    """OCR 이 줄을 잘게 쪼개 돌려줘도(넓게 떨어진 글자 하나하나가 각각 '줄'),
    단어들의 세로 위치로 같은 높이의 단어끼리 다시 한 줄로 묶는다."""
    words = [w for ln in lines for w in ln.words]
    if not words:
        return []
    words.sort(key=lambda w: w.y + w.h / 2)
    rows: list[list[OcrWord]] = []
    for w in words:
        cy = w.y + w.h / 2
        if rows:
            row = rows[-1]
            row_cy = statistics.median(x.y + x.h / 2 for x in row)
            row_h = statistics.median(x.h for x in row)
            if abs(cy - row_cy) < max(row_h, w.h) * 0.5:
                row.append(w)
                continue
        rows.append([w])
    return [OcrLine(sorted(r, key=lambda w: w.x)) for r in rows]


def lines_to_song(pages: list[tuple[list[OcrLine], float]], title_hint: str = "") -> Song:
    """[(페이지의 OCR 줄들, 페이지 높이)] -> Song"""
    pages = [(regroup_rows(lines), h) for lines, h in pages]
    all_words = [w.text for lines, _ in pages for ln in lines for w in ln.words]
    hangul = sum(len(_HANGUL.findall(t)) for t in all_words)
    letters = sum(sum(c.isalpha() for c in t) for t in all_words) or 1
    korean = hangul / letters > 0.3

    title = title_hint
    lyric: list[_LyricLine] = []
    for pi, (lines, page_h) in enumerate(pages):
        skip = None
        if pi == 0:
            skip = _find_title(lines, page_h)
            if skip is not None and not title:
                title = skip.text.strip()
        for ln in sorted(lines, key=lambda ln: ln.cy):
            if ln is skip:
                continue
            words, verse = _clean_line_words(ln)
            if not words or not _is_lyric(words, korean):
                continue
            text = join_syllables(words) if korean else " ".join(w.text for w in words)
            lyric.append(_LyricLine(text, min(w.y for w in words), max(w.y + w.h for w in words),
                                    statistics.median(w.h for w in words), verse, pi))

    if not lyric:
        raise OcrError("악보에서 가사를 찾지 못했습니다.\n더 밝고 선명하게, 정면에서 찍은 사진으로 다시 시도해 보세요.")

    # 오선(단) 하나 밑의 가사 줄들끼리 묶기: 줄 사이가 가까우면 같은 단
    groups: list[list[_LyricLine]] = [[lyric[0]]]
    for prev, cur in zip(lyric, lyric[1:]):
        gap = cur.top - prev.bottom
        if cur.page == prev.page and gap < max(prev.height, cur.height) * 1.2:
            groups[-1].append(cur)
        else:
            groups.append([cur])

    sizes = [len(g) for g in groups]
    stacked = [s for s in sizes if s >= 2]
    k = statistics.mode(stacked) if stacked else 1
    song = Song(title=title)
    if k >= 2 and len([s for s in sizes if s == k]) >= max(1, len(sizes) * 0.4):
        verses: list[list[str]] = [[] for _ in range(k)]
        chorus: list[str] = []
        for g in groups:
            if len(g) == k:
                # 절 번호가 적혀 있으면 그 순서를 따름
                order = sorted(range(k), key=lambda i: (g[i].verse or i + 1, i)) \
                    if any(x.verse for x in g) else list(range(k))
                for vi, li in enumerate(order):
                    verses[vi].append(g[li].text)
            else:
                chorus.extend(x.text for x in g)
        song.sections = [Section(f"Verse {i + 1}", v) for i, v in enumerate(verses) if v]
        if chorus:
            song.sections.insert(1, Section("Chorus", chorus))
            song.order = [x for i in range(k) for x in (f"Verse {i + 1}", "Chorus")]
    else:
        body: list[str] = []
        for g in groups:
            body.extend(x.text for x in g)
        song.sections = [Section("", body)]
    return song


# ---------------------------------------------------------------------------
# 이미지 준비
# ---------------------------------------------------------------------------

def load_pages(paths: list[str | Path]):
    """이미지/PDF -> PIL 이미지 목록 (흑백)."""
    from PIL import Image, ImageOps
    pages = []
    for p in paths:
        p = Path(p)
        if p.suffix.lower() == ".pdf":
            try:
                import pypdfium2 as pdfium
            except ImportError as e:
                raise OcrError("PDF 를 읽으려면 pypdfium2 가 필요합니다. 사진(jpg/png)으로 넣어 주세요.") from e
            pdf = pdfium.PdfDocument(str(p))
            for i in range(len(pdf)):
                pages.append(pdf[i].render(scale=3).to_pil().convert("L"))
        else:
            with Image.open(p) as im:
                im = ImageOps.exif_transpose(im)
                pages.append(im.convert("L"))
    return pages


def _tiles(img, max_dim: int):
    """OCR 최대 크기에 맞게 폭을 맞추고 세로로 겹치게 잘라낸다. (이미지, y오프셋, 유효범위)"""
    from PIL import Image
    w, h = img.size
    target_w = min(max_dim, max(w, 2000))
    if w != target_w:
        img = img.resize((target_w, int(h * target_w / w)), Image.LANCZOS)
        w, h = img.size
    tile_h = min(max_dim, max(800, int(w * 0.6)))
    overlap = int(tile_h * 0.2)
    if h <= max_dim:
        return [(img, 0, (0, h))], img.size
    out, y = [], 0
    while y < h:
        y2 = min(h, y + tile_h)
        core_top = y if y == 0 else y + overlap // 2
        core_bottom = y2 if y2 == h else y2 - overlap // 2
        out.append((img.crop((0, y, w, y2)), y, (core_top, core_bottom)))
        if y2 == h:
            break
        y = y2 - overlap
    return out, img.size


def squeeze_lyrics(img):
    """오선(긴 가로줄)과 음표 기둥을 지우고, 글줄마다 글자 사이 넓은 빈칸을 좁혀
    '주   님   의' 처럼 떨어진 가사를 '주님의' 처럼 붙여 놓은 이미지를 만든다.
    글줄의 세로 위치는 그대로 둔다 (1절/2절 구분에 필요)."""
    import numpy as np
    from PIL import Image
    a = np.asarray(img.convert("L"))
    ink = a < 140
    H, W = ink.shape
    ink[ink.sum(axis=1) > W * 0.35, :] = False          # 오선, 마디 가로줄
    rows = ink.sum(axis=1) > 0
    bands, start = [], None
    for y in range(H + 1):
        on = y < H and rows[y]
        if on and start is None:
            start = y
        elif not on and start is not None:
            bands.append([start, y])
            start = None
    merged: list[list[int]] = []
    for b in bands:                                     # 받침 등 아주 가까운 띠는 합침
        if merged and b[0] - merged[-1][1] <= 3:
            merged[-1][1] = b[1]
        else:
            merged.append(b)
    out = Image.new("L", (W, H), 255)
    for y0, y1 in merged:
        bh = y1 - y0
        if bh < 8 or bh > H * 0.15:
            continue
        band = ink[y0:y1]
        cols = band.sum(axis=0) > 0   # (세로획 ㅣ 를 지우면 안 되므로 기둥 제거는 하지 않음)
        segs, s = [], None
        for x in range(W + 1):
            on = x < W and cols[x]
            if on and s is None:
                s = x
            elif not on and s is not None:
                segs.append([s, x])
                s = None
        glued: list[list[int]] = []
        for sg in segs:                                 # 한 글자 안의 틈(ㅣ, ㅏ)은 붙임
            if glued and sg[0] - glued[-1][1] < bh * 0.45:
                glued[-1][1] = sg[1]
            else:
                glued.append(sg)
        gap = max(2, int(bh * 0.3))
        x = int(bh)
        src = Image.fromarray(np.where(band, 0, 255).astype("uint8"))
        for i, (x0, x1) in enumerate(glued):
            if i and glued[i][0] - glued[i - 1][1] > bh * 3:  # 아주 멀면 띄어쓰기로
                x += gap * 2
            if x + (x1 - x0) >= W:
                break
            out.paste(src.crop((x0, 0, x1, bh)), (x, y0))
            x += (x1 - x0) + gap
    return out


def _hangul_count(lines: list[OcrLine]) -> int:
    return sum(len(_HANGUL.findall(w.text)) for ln in lines for w in ln.words)


# ---------------------------------------------------------------------------
# Windows OCR
# ---------------------------------------------------------------------------

def _require_windows() -> None:
    if not sys.platform.startswith("win"):
        raise OcrError("무료 악보 읽기는 Windows 10/11 에서만 동작합니다.")
    try:
        importlib.import_module("winrt.windows.media.ocr")
    except ImportError as e:
        raise OcrError("Windows 글자 인식 구성요소(winrt)를 불러오지 못했습니다.\n"
                       "run.bat 으로 실행 중이면 .venv 폴더를 지우고 다시 실행해 주세요.") from e


def _engine(lang: str):
    from winrt.windows.globalization import Language
    from winrt.windows.media.ocr import OcrEngine
    language = Language(lang)
    if OcrEngine.is_language_supported(language):
        return OcrEngine.try_create_from_language(language)
    return None


KOREAN_OCR_HELP = (
    "이 PC에 한국어 글자 인식 기능이 없습니다.\n\n"
    "설정 → 시간 및 언어 → 언어 및 지역 → '한국어' 추가(또는 한국어 옵션에서 '광학 문자 인식' 설치) 후 다시 시도하세요.\n"
    "(한국어 Windows 라면 보통 이미 설치되어 있습니다)")


def available_languages() -> list[str]:
    _require_windows()
    from winrt.windows.media.ocr import OcrEngine
    return [lang.language_tag for lang in OcrEngine.available_recognizer_languages]


async def _recognize_file(engine, path: str) -> list[OcrLine]:
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.storage import FileAccessMode, StorageFile
    file = await StorageFile.get_file_from_path_async(path)
    stream = await file.open_async(FileAccessMode.READ)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    result = await engine.recognize_async(bitmap)
    lines = []
    for line in result.lines:
        words = []
        for word in line.words:
            r = word.bounding_rect
            words.append(OcrWord(word.text, r.x, r.y, r.width, r.height))
        if words:
            lines.append(OcrLine(words))
    return lines


def ocr_image(img, lang: str = "ko") -> tuple[list[OcrLine], float]:
    """원본과 '글자 간격 좁힌' 이미지를 둘 다 읽어 한글이 더 많이 나온 쪽을 쓴다."""
    plain = _ocr_raw(img, lang)
    try:
        squeezed = _ocr_raw(squeeze_lyrics(img), lang)
    except Exception:
        return plain
    if _hangul_count(squeezed[0]) > _hangul_count(plain[0]):
        # 제목 등은 원본에서 (간격 좁힌 이미지는 큰 글자 줄을 그대로 두지만 안전하게 합침)
        return squeezed
    return plain


def _ocr_raw(img, lang: str = "ko") -> tuple[list[OcrLine], float]:
    """PIL 이미지 하나를 OCR. (줄 목록, 이미지 높이)"""
    import asyncio
    from winrt.windows.media.ocr import OcrEngine
    _require_windows()
    engine = _engine(lang)
    if engine is None:
        raise OcrError(KOREAN_OCR_HELP if lang.startswith("ko") else f"'{lang}' 글자 인식을 쓸 수 없습니다.")
    max_dim = int(OcrEngine.max_image_dimension or 2600)
    tiles, (_, full_h) = _tiles(img, max_dim)
    lines: list[OcrLine] = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, (tile, offset, (core_top, core_bottom)) in enumerate(tiles):
            path = os.path.join(tmp, f"tile{i}.png")
            tile.save(path)
            for ln in asyncio.run(_recognize_file(engine, path)):
                for w in ln.words:
                    w.y += offset
                if core_top <= ln.cy < core_bottom:
                    lines.append(ln)
    return lines, float(full_h)


def _init_thread() -> None:
    """백그라운드 스레드에서 WinRT 를 쓰기 위한 COM 초기화 (이미 돼 있으면 무시)."""
    try:
        from winrt.runtime import ApartmentType, init_apartment
        init_apartment(ApartmentType.MULTI_THREADED)
    except Exception:
        pass


def read_sheet_music_free(paths: list[str | Path], title_hint: str = "", lang: str = "ko") -> Song:
    _require_windows()
    _init_thread()
    pages = [ocr_image(img, lang) for img in load_pages(paths)]
    return lines_to_song(pages, title_hint)
