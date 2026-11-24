from churchppt.lyrics_format import (auto_structure, chunk_lines, is_header_line,
                                     label_abbrev, normalize_label, parse_order,
                                     parse_song_text, read_text_file,
                                     resolve_order, safe_filename, song_to_text,
                                     write_text_file)

SONG = """제목: 테스트 곡
아티스트: 누군가
순서: V1 C V2 C B C

[Verse 1]
하나
둘
셋

[Chorus]
후렴 하나
후렴 둘

[Verse 2]
이절 하나

이절 둘

[Bridge]
브릿지
"""


def test_normalize_labels():
    assert normalize_label("[1절]") == "Verse 1"
    assert normalize_label("V2") == "Verse 2"
    assert normalize_label("후렴") == "Chorus"
    assert normalize_label("Pre-Chorus:") == "Pre-Chorus"
    assert normalize_label("브릿지") == "Bridge"
    assert normalize_label("간주") == "Interlude"
    assert normalize_label("Spontaneous") == "Spontaneous"
    assert label_abbrev("Verse 1") == "V1"
    assert label_abbrev("Chorus") == "C"


def test_header_detection():
    assert is_header_line("[Verse 1]")
    assert is_header_line("Chorus:")
    assert is_header_line("2절")
    assert is_header_line("후렴")
    assert not is_header_line("C")            # 한 글자 약어는 대괄호 필요
    assert not is_header_line("주님 사랑해요")
    assert not is_header_line("")


def test_parse_order_variants():
    assert parse_order("V1 C V2 C B C") == ["Verse 1", "Chorus", "Verse 2", "Chorus", "Bridge", "Chorus"]
    assert parse_order("Verse 1, Chorus, Bridge") == ["Verse 1", "Chorus", "Bridge"]
    assert parse_order("Verse 1 Chorus") == ["Verse 1", "Chorus"]
    assert parse_order("1절 → 후렴 → 2절") == ["Verse 1", "Chorus", "Verse 2"]
    assert parse_order("") == []


def test_parse_and_roundtrip():
    song = parse_song_text(SONG)
    assert song.title == "테스트 곡"
    assert song.artist == "누군가"
    assert [s.label for s in song.sections] == ["Verse 1", "Chorus", "Verse 2", "Bridge"]
    assert song.sections[2].lines == ["이절 하나", "", "이절 둘"]
    again = parse_song_text(song_to_text(song))
    assert again == song


def test_resolve_order_and_missing():
    song = parse_song_text(SONG)
    seq, missing = resolve_order(song)
    assert [s.label for s in seq] == ["Verse 1", "Chorus", "Verse 2", "Chorus", "Bridge", "Chorus"]
    assert missing == []
    song.order = ["Verse 1", "Tag"]
    seq, missing = resolve_order(song)
    assert [s.label for s in seq] == ["Verse 1"] and missing == ["Tag"]


def test_unstructured_song():
    song = parse_song_text("제목: 쭉\n\n줄1\n줄2\n줄3")
    assert len(song.sections) == 1 and song.sections[0].label == ""
    assert not song.is_structured


def test_chunk_lines():
    assert chunk_lines(["a", "b", "c", "d", "e"], 2) == [["a", "b"], ["c", "d"], ["e"]]
    assert chunk_lines(["a", "b", "c"], 2) == [["a", "b"], ["c"]]
    assert chunk_lines(["a", "", "b", "c"], 4) == [["a"], ["b", "c"]]
    assert chunk_lines(["a", "b", "c", "d"], 3) == [["a", "b"], ["c", "d"]]


def test_auto_structure_detects_chorus():
    text = "일절 가사\n일절 둘\n\n후렴 가사\n후렴 둘\n\n이절 가사\n\n후렴 가사\n후렴 둘"
    sections, order = auto_structure(text)
    assert [s.label for s in sections] == ["Verse 1", "Chorus", "Verse 2"]
    assert order == ["Verse 1", "Chorus", "Verse 2", "Chorus"]


def test_auto_structure_without_repeats_stays_continuous():
    sections, order = auto_structure("가\n나\n\n다\n라")
    assert len(sections) == 1 and sections[0].label == ""
    assert sections[0].lines == ["가", "나", "", "다", "라"]
    assert order == []


def test_files(tmp_path):
    p = tmp_path / "곡.txt"
    write_text_file(p, "제목: 곡\n\n[Verse 1]\n가사")
    raw = p.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf") and b"\r\n" in raw
    assert parse_song_text(read_text_file(p)).sections[0].lines == ["가사"]
    old = tmp_path / "ansi.txt"
    old.write_bytes("제목: 옛날\n가사".encode("cp949"))
    assert parse_song_text(read_text_file(old)).title == "옛날"


def test_safe_filename():
    assert safe_filename('주 은혜/임을: "새"?') == "주 은혜 임을 새"
    assert safe_filename("   ") == "제목없음"


def test_clean_pasted_lyrics():
    from churchppt.lyrics_format import clean_pasted_lyrics
    raw = "G  D/F#  Em7\n주님의 사랑 (x2)\n\n\n\n출처: https://example.com\n찬양해 반복\nCopyright © 누군가"
    assert clean_pasted_lyrics(raw) == "주님의 사랑\n\n찬양해"


def test_auto_structure_hymn_style():
    text = "1. 첫째 절 가사\n이어지는 줄\n\n(후렴)\n후렴 가사\n\n2. 둘째 절 가사\n이어지는 줄"
    sections, order = auto_structure(text)
    assert [s.label for s in sections] == ["Verse 1", "Chorus", "Verse 2"]


def test_auto_structure_hymn_numbers_without_label():
    text = "1. 첫째 절\n줄\n\n후렴 같은 연\n줄\n\n2. 둘째 절\n줄"
    sections, order = auto_structure(text)
    assert [s.label for s in sections] == ["Verse 1", "Chorus", "Verse 2"]
    assert sections[0].lines[0] == "첫째 절"
    assert order == ["Verse 1", "Chorus", "Verse 2", "Chorus"]
