"""AI 모듈 테스트 - 실제 API 대신 가짜 응답을 사용한다."""
import json
from types import SimpleNamespace as NS

import pytest

from churchppt.ai import AIClient, AIError, NotFoundLyrics


def text_block(text):
    return NS(type="text", text=text)


def response(blocks, stop="end_turn"):
    return NS(content=blocks, stop_reason=stop)


class FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def make_client(responses, model="claude-opus-5-5"):
    c = AIClient("sk-test", model)
    fake = FakeMessages(responses)
    c.client = NS(beta=NS(messages=fake))
    return c, fake


def test_requires_key():
    with pytest.raises(AIError):
        AIClient("", "claude-opus-5-5")


def test_search_lyrics_parses_song_block():
    text = ("검색해 보겠습니다.\n<song>\n제목: 테스트\n아티스트: 가수\n순서: Verse 1, Chorus, Verse 1, Chorus\n\n"
            "[Verse 1]\n첫 줄\n둘째 줄\n\n[Chorus]\n후렴\n</song>")
    c, fake = make_client([response([text_block(text)])])
    song = c.search_lyrics("테스트")
    assert song.title == "테스트" and song.artist == "가수"
    assert [s.label for s in song.sections] == ["Verse 1", "Chorus"]
    assert song.order == ["Verse 1", "Chorus", "Verse 1", "Chorus"]
    call = fake.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["tools"][0]["type"] == "web_search_20260209"
    assert call["fallbacks"] == "default" and call["betas"] == ["server-side-fallback-2026-07-01"]
    assert "thinking" not in call and "temperature" not in call


def test_search_lyrics_not_found():
    c, _ = make_client([response([text_block("<not_found>정확한 가사를 찾지 못했습니다</not_found>")])])
    with pytest.raises(NotFoundLyrics, match="정확한 가사"):
        c.search_lyrics("없는 곡")


def test_pause_turn_is_resumed():
    first = response([NS(type="server_tool_use", text=None)], stop="pause_turn")
    second = response([text_block("<song>\n제목: 곡\n\n줄 하나\n</song>")])
    c, fake = make_client([first, second])
    song = c.search_lyrics("곡")
    assert len(fake.calls) == 2
    assert fake.calls[1]["messages"][-1]["role"] == "assistant"
    assert song.sections[0].label == "" and song.sections[0].lines == ["줄 하나"]


def test_haiku_uses_basic_web_search_and_no_fallbacks():
    c, fake = make_client([response([text_block("<song>\n제목: 곡\n\n가사\n</song>")])], model="claude-haiku-5-5")
    c.search_lyrics("곡")
    call = fake.calls[0]
    assert call["tools"][0]["type"] == "web_search_20250305"
    assert "fallbacks" not in call


def test_structure_lyrics_json():
    data = {"title": "", "artist": "", "structured": True,
            "sections": [{"label": "1절", "lines": ["가", "나"]}, {"label": "후렴", "lines": ["다"]}],
            "order": ["1절", "후렴", "후렴"], "note": ""}
    c, fake = make_client([response([text_block(json.dumps(data, ensure_ascii=False))])])
    song = c.structure_lyrics("가\n나\n다\n다", title="곡")
    assert song.title == "곡"
    assert [s.label for s in song.sections] == ["Verse 1", "Chorus"]
    assert song.order == ["Verse 1", "Chorus", "Chorus"]
    fmt = fake.calls[0]["output_config"]["format"]
    assert fmt["type"] == "json_schema" and fmt["schema"]["additionalProperties"] is False


def test_structure_unstructured_merges_sections():
    data = {"title": "t", "artist": "", "structured": False,
            "sections": [{"label": "", "lines": ["가"]}, {"label": "", "lines": ["나"]}],
            "order": [], "note": ""}
    c, _ = make_client([response([text_block(json.dumps(data))])])
    song = c.structure_lyrics("가\n나")
    assert len(song.sections) == 1 and song.sections[0].lines == ["가", "", "나"]


def test_refusal_becomes_friendly_error():
    c, _ = make_client([response([], stop="refusal")])
    with pytest.raises(AIError, match="직접 붙여넣"):
        c.structure_lyrics("가사")


def test_sheet_music_sends_image(tmp_path):
    from PIL import Image
    img = tmp_path / "score.png"
    Image.new("RGB", (3000, 1000), "white").save(img)
    data = {"title": "악보곡", "artist": "", "structured": True,
            "sections": [{"label": "Verse 1", "lines": ["가사"]}], "order": [], "note": ""}
    c, fake = make_client([response([text_block(json.dumps(data))])])
    song = c.read_sheet_music([img])
    assert song.title == "악보곡"
    content = fake.calls[0]["messages"][0]["content"]
    assert content[0]["type"] == "image" and content[0]["source"]["media_type"] == "image/jpeg"
    assert fake.calls[0]["output_config"]["effort"] == "high"


def test_scripture_and_sermon():
    c, _ = make_client([response([text_block("<scripture>\n16 본문\n\n17 본문2\n</scripture>")])])
    assert c.fetch_scripture("요한복음 3:16-17", "개역개정") == "16 본문\n17 본문2"
    data = {"slides": [{"lines": ["1. 요점", "설명"]}, {"lines": ["2. 요점"]}]}
    c, _ = make_client([response([text_block(json.dumps(data, ensure_ascii=False))])])
    assert c.summarize_sermon("원고") == "1. 요점\n설명\n\n2. 요점"
