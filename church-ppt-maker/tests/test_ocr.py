"""무료 악보 읽기 - OCR 결과(단어 위치) -> 가사 재구성 테스트. 실제 OCR 은 Windows 에서만."""
import sys

import pytest

from churchppt.ocr import OcrLine, OcrWord, OcrError, join_syllables, lines_to_song


def syll_line(text, y, x0=100, step=60, h=30, word_gap=None):
    """'주님의 사랑' -> 음표 밑에 한 글자씩 놓인 OCR 단어들. 띄어쓰기 자리는 word_gap 만큼 더 벌림."""
    words, x = [], x0
    for ch in text:
        if ch == " ":
            x += word_gap or 0
            continue
        words.append(OcrWord(ch, x, y, 28, h))
        x += step
    return OcrLine(words)


def test_join_syllables_glues_spaced_hangul():
    ln = syll_line("주님의 사랑", 0, word_gap=0)
    assert join_syllables(ln.words) == "주님의사랑"
    ln = syll_line("주님의 사랑", 0, word_gap=120)
    assert join_syllables(ln.words) == "주님의 사랑"


def test_join_keeps_normal_words():
    words = [OcrWord("주님의", 0, 0, 90, 30), OcrWord("사랑", 120, 0, 60, 30)]
    assert join_syllables(words) == "주님의 사랑"


def test_single_verse_sheet_with_title_and_noise():
    lines = [
        OcrLine([OcrWord("은혜의", 300, 40, 150, 70), OcrWord("강가로", 470, 40, 150, 70)]),  # 큰 제목
        OcrLine([OcrWord("작사:", 900, 130, 60, 20), OcrWord("홍길동", 970, 130, 60, 20)]),
        OcrLine([OcrWord("G", 100, 250, 20, 25), OcrWord("D/F#", 300, 250, 50, 25), OcrWord("Em7", 500, 250, 40, 25)]),
        syll_line("주님 나를 부르시네", 400),
        syll_line("은혜의 강가로", 700),
        OcrLine([OcrWord("©2020", 100, 1500, 80, 20), OcrWord("Copyright", 200, 1500, 100, 20)]),
    ]
    song = lines_to_song([(lines, 1600)])
    assert song.title == "은혜의 강가로"
    assert len(song.sections) == 1 and song.sections[0].label == ""
    assert song.sections[0].lines == ["주님나를부르시네", "은혜의강가로"]


def test_stacked_verses_become_verse_1_and_2():
    lines = [
        # 1단: 1절/2절이 겹쳐 있음
        OcrLine([OcrWord("1.", 50, 300, 20, 30)] + syll_line("첫절 하나", 300).words),
        OcrLine([OcrWord("2.", 50, 340, 20, 30)] + syll_line("둘절 하나", 340).words),
        # 2단
        syll_line("첫절 둘", 600),
        syll_line("둘절 둘", 640),
        # 3단: 한 줄짜리 = 후렴
        syll_line("후렴 가사", 900),
    ]
    song = lines_to_song([(lines, 1200)], title_hint="곡")
    labels = [s.label for s in song.sections]
    assert labels == ["Verse 1", "Chorus", "Verse 2"]
    assert song.sections[0].lines == ["첫절하나", "첫절둘"]
    assert song.sections[2].lines == ["둘절하나", "둘절둘"]
    assert song.order == ["Verse 1", "Chorus", "Verse 2", "Chorus"]


def test_no_lyrics_raises():
    with pytest.raises(OcrError):
        lines_to_song([([OcrLine([OcrWord("G", 0, 0, 10, 10)])], 100)])


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows OCR 전용")
def test_windows_ocr_english_smoke(tmp_path):
    from PIL import Image, ImageDraw, ImageFont
    from churchppt.ocr import ocr_image
    img = Image.new("L", (1600, 400), 255)
    ImageDraw.Draw(img).text((50, 120), "AMAZING GRACE HOW SWEET", fill=0, font=ImageFont.load_default(size=80))
    lines, _ = ocr_image(img, lang="en-US")
    text = " ".join(ln.text for ln in lines).upper()
    assert "GRACE" in text


def test_windows_ocr_splits_every_syllable_into_its_own_line():
    """실제 Windows OCR 결과 모양: 넓게 떨어진 글자마다 따로 '줄'로 나옴 (순서도 뒤섞임)."""
    raw = []
    for text, y in (("주님나를부르시네", 330), ("나의모든것드려요", 385),
                    ("은혜의강흘러가", 710), ("기쁨의노래부르리", 765), ("할렐루야주를찬양", 1090)):
        for i, ch in enumerate(text):
            raw.append(OcrLine([OcrWord(ch, 155 + i * 110, y + (i % 3), 38, 38)]))
    raw.insert(0, OcrLine([OcrWord("2.", 102, 385, 30, 34)]))
    raw.append(OcrLine([OcrWord("은혜의", 700, 50, 300, 80), OcrWord("강가로", 1010, 50, 250, 80)]))
    raw.reverse()
    song = lines_to_song([(raw, 1500)])
    assert song.title == "은혜의 강가로"
    assert [s.label for s in song.sections] == ["Verse 1", "Chorus", "Verse 2"]
    assert song.sections[0].lines == ["주님나를부르시네", "은혜의강흘러가"]
    assert song.sections[2].lines == ["나의모든것드려요", "기쁨의노래부르리"]
    assert song.sections[1].lines == ["할렐루야주를찬양"]
