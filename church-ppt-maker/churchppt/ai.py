"""Claude API 로 가사 찾기 / 가사 나누기 / 악보 읽기 / 성경 본문 / 설교 정리.

모든 함수는 시간이 걸리므로 화면(UI)에서는 백그라운드 스레드에서 호출한다.
"""
from __future__ import annotations

import base64
import io
import json
import re
from pathlib import Path

import anthropic

from .lyrics_format import normalize_label, parse_song_text
from .models import Section, Song

# 거절(refusal) 시 서버에서 다른 모델로 자동 재시도하는 기능을 지원하는 모델
_FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-2", "claude-fable-5-1", "claude-sonnet-5-5"}
_FALLBACK_BETA = "server-side-fallback-2026-07-01"
# 최신 웹 검색 도구(_20260209)를 지원하지 않는 모델
_BASIC_WEB_SEARCH_MODELS = {"claude-haiku-5-5", "claude-haiku-4-5"}

IMAGE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
               ".gif": "image/gif", ".webp": "image/webp"}
MAX_IMAGE_SIDE = 2400
MAX_IMAGE_BYTES = 4_500_000


class AIError(Exception):
    """사용자에게 그대로 보여줄 수 있는 한국어 오류."""


class NotFoundLyrics(AIError):
    pass


SECTION_LABEL_GUIDE = (
    "Section labels must be one of: Intro, Verse 1, Verse 2, Verse 3 ..., Pre-Chorus, Chorus, "
    "Chorus 2, Post-Chorus, Bridge, Interlude, Tag, Outro, Ending."
)

LINE_GUIDE = (
    "Break lines at natural phrase boundaries so each line reads well on a projected slide "
    "(about 8-18 Korean characters, or 3-8 English words, per line). Use correct Korean spacing (띄어쓰기)."
)

SONG_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "artist": {"type": "string"},
        "structured": {
            "type": "boolean",
            "description": "false when the song has no verse/chorus structure and is one continuous text",
        },
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string", "description": "empty string when structured is false"},
                    "lines": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["label", "lines"],
                "additionalProperties": False,
            },
        },
        "order": {
            "type": "array",
            "items": {"type": "string"},
            "description": "performance order as a list of section labels; repeats allowed",
        },
        "note": {"type": "string", "description": "short note to the user in Korean (uncertain parts etc.)"},
    },
    "required": ["title", "artist", "structured", "sections", "order", "note"],
    "additionalProperties": False,
}

SERMON_SCHEMA = {
    "type": "object",
    "properties": {
        "slides": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"lines": {"type": "array", "items": {"type": "string"}}},
                "required": ["lines"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["slides"],
    "additionalProperties": False,
}


def _song_from_json(data: dict) -> Song:
    sections = []
    for sec in data.get("sections", []):
        lines = [ln.strip() for ln in sec.get("lines", []) if ln and ln.strip()]
        if not lines:
            continue
        label = normalize_label(sec.get("label", "")) if data.get("structured", True) else ""
        sections.append(Section(label, lines))
    if not data.get("structured", True) and len(sections) > 1:
        merged: list[str] = []
        for sec in sections:
            if merged:
                merged.append("")
            merged.extend(sec.lines)
        sections = [Section("", merged)]
    order = [normalize_label(o) for o in data.get("order", []) if o.strip()] if any(s.label for s in sections) else []
    # 순서가 섹션을 한 번씩 그대로 나열한 것뿐이면 생략
    if order == [s.label for s in sections]:
        order = []
    return Song(title=data.get("title", "").strip(), artist=data.get("artist", "").strip(),
                order=order, sections=sections)


def _extract_tag(text: str, tag: str) -> str | None:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.S)
    return m.group(1).strip() if m else None


def _image_block(path: Path) -> dict:
    data = path.read_bytes()
    media = IMAGE_TYPES.get(path.suffix.lower())
    needs_resize = media is None or len(data) > MAX_IMAGE_BYTES
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            if max(im.size) > MAX_IMAGE_SIDE:
                needs_resize = True
            if needs_resize:
                im = im.convert("RGB")
                im.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
                buf = io.BytesIO()
                quality = 90
                while True:
                    buf.seek(0)
                    buf.truncate()
                    im.save(buf, "JPEG", quality=quality)
                    if buf.tell() <= MAX_IMAGE_BYTES or quality <= 50:
                        break
                    quality -= 10
                data, media = buf.getvalue(), "image/jpeg"
    except Exception as e:
        if media is None:
            raise AIError(f"이미지 파일을 읽을 수 없습니다: {path.name}") from e
    return {"type": "image",
            "source": {"type": "base64", "media_type": media, "data": base64.standard_b64encode(data).decode()}}


def _pdf_block(path: Path) -> dict:
    data = path.read_bytes()
    if len(data) > 30_000_000:
        raise AIError(f"PDF 파일이 너무 큽니다 (30MB 이하): {path.name}")
    return {"type": "document",
            "source": {"type": "base64", "media_type": "application/pdf",
                       "data": base64.standard_b64encode(data).decode()}}


class AIClient:
    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise AIError("Claude API 키가 없습니다.\n[설정] 에서 API 키를 입력해 주세요.")
        self.client = anthropic.Anthropic(api_key=api_key, max_retries=3, timeout=600.0)
        self.model = model

    # ------------------------------------------------------------------
    def _web_search_tool(self, max_uses: int = 6) -> dict:
        tool_type = "web_search_20250305" if self.model in _BASIC_WEB_SEARCH_MODELS else "web_search_20260209"
        return {"type": tool_type, "name": "web_search", "max_uses": max_uses,
                "user_location": {"type": "approximate", "country": "KR", "timezone": "Asia/Seoul"}}

    def _request(self, *, system: str, content: list | str, effort: str = "medium",
                 tools: list | None = None, schema: dict | None = None, max_tokens: int = 16000) -> str:
        output_config: dict = {"effort": effort}
        if schema:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        messages: list = [{"role": "user", "content": content}]
        kwargs: dict = dict(model=self.model, max_tokens=max_tokens, system=system,
                            output_config=output_config)
        if tools:
            kwargs["tools"] = tools
        if self.model in _FALLBACK_MODELS:
            kwargs["betas"] = [_FALLBACK_BETA]
            kwargs["fallbacks"] = "default"

        assistant_blocks: list = []
        try:
            for _ in range(6):
                convo = messages + ([{"role": "assistant", "content": assistant_blocks}] if assistant_blocks else [])
                resp = self.client.beta.messages.create(messages=convo, **kwargs)
                assistant_blocks = assistant_blocks + list(resp.content)
                if resp.stop_reason != "pause_turn":
                    break
        except anthropic.AuthenticationError as e:
            raise AIError("API 키가 올바르지 않습니다. [설정] 에서 키를 다시 확인해 주세요.") from e
        except anthropic.PermissionDeniedError as e:
            raise AIError("이 API 키로는 해당 기능을 쓸 수 없습니다.\n"
                          "(웹 검색은 Claude Console 에서 사용 설정이 필요할 수 있습니다)\n" + str(e.message)) from e
        except anthropic.NotFoundError as e:
            raise AIError(f"AI 모델을 찾을 수 없습니다: {self.model}\n[설정] 에서 다른 모델을 골라 보세요.") from e
        except anthropic.RateLimitError as e:
            raise AIError("요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.") from e
        except anthropic.BadRequestError as e:
            msg = str(e.message)
            if "credit" in msg.lower() or "billing" in msg.lower():
                raise AIError("API 사용 잔액(크레딧)이 부족합니다. Claude Console 에서 결제 상태를 확인해 주세요.") from e
            raise AIError(f"AI 요청 오류: {msg}") from e
        except anthropic.APIStatusError as e:
            raise AIError(f"AI 서버 오류 ({e.status_code}). 잠시 후 다시 시도해 주세요.") from e
        except anthropic.APIConnectionError as e:
            raise AIError("인터넷 연결을 확인해 주세요. (AI 서버에 연결할 수 없습니다)") from e

        if resp.stop_reason == "refusal":
            raise AIError("AI가 이 요청에 답하지 않았습니다.\n가사를 직접 붙여넣거나 악보 사진을 이용해 주세요.")
        if resp.stop_reason == "max_tokens":
            raise AIError("AI 응답이 너무 길어서 잘렸습니다. 내용을 나눠서 다시 시도해 주세요.")
        if schema:
            # 구조화 출력은 마지막 응답의 텍스트가 JSON
            return "".join(b.text for b in resp.content if b.type == "text")
        return "".join(getattr(b, "text", "") for b in assistant_blocks if b.type == "text")

    def _request_json(self, **kwargs) -> dict:
        text = self._request(**kwargs)
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise AIError("AI 응답을 해석하지 못했습니다. 다시 시도해 주세요.") from e

    # ------------------------------------------------------------------
    # 1) 제목으로 가사 찾기
    # ------------------------------------------------------------------
    def search_lyrics(self, title: str, artist: str = "") -> Song:
        system = (
            "You help a Korean church media team prepare lyric slides for their worship service. "
            "Use web search to find the lyrics of the requested worship song from reliable lyric pages. "
            "Accuracy matters more than anything: copy the lyrics exactly as published, and never invent, "
            "guess, paraphrase or fill in missing words. If you cannot find the complete lyrics with "
            "confidence, answer with <not_found>reason in Korean</not_found> instead.\n\n"
            "When you find them, reply with exactly one <song>...</song> block in this plain-text format:\n"
            "<song>\n제목: (title)\n아티스트: (artist/composer, if known)\n순서: (performance order, "
            "comma separated, e.g. Verse 1, Chorus, Verse 2, Chorus, Bridge, Chorus)\n\n"
            "[Verse 1]\nline\nline\n\n[Chorus]\nline\nline\n</song>\n\n"
            "Rules:\n"
            f"- {SECTION_LABEL_GUIDE} Korean hymns: 1절 -> Verse 1, 후렴 -> Chorus.\n"
            "- Write each distinct section only once and express repetition in the 순서 line, following "
            "the commonly sung arrangement (e.g. the original recording).\n"
            "- If the song has no verse/chorus structure (one continuous text), omit the [labels] and the "
            "순서 line and just write the lines.\n"
            f"- {LINE_GUIDE}\n"
            "- If several songs share the title, choose the best-known Korean worship song with that title "
            "(or the one matching the artist given) and name the artist.\n"
            "- Keep the original language. Do not add chords, translations or commentary inside <song>."
        )
        query = f"찬양 제목: {title}"
        if artist:
            query += f"\n아티스트/작곡가: {artist}"
        text = self._request(system=system, content=query, effort="medium", tools=[self._web_search_tool()])
        nf = _extract_tag(text, "not_found")
        body = _extract_tag(text, "song")
        if body is None:
            raise NotFoundLyrics(nf or "가사를 찾지 못했습니다. 가사를 직접 붙여넣고 [AI로 파트 나누기]를 눌러 주세요.")
        song = parse_song_text(body)
        if not song.sections:
            raise NotFoundLyrics("가사를 찾지 못했습니다. 가사를 직접 붙여넣어 주세요.")
        if not song.title:
            song.title = title
        return song

    # ------------------------------------------------------------------
    # 2) 붙여넣은 가사를 파트별로 나누기
    # ------------------------------------------------------------------
    def structure_lyrics(self, raw_text: str, title: str = "") -> Song:
        system = (
            "You organize worship song lyrics into sections for church lyric slides. "
            "The user pastes raw lyrics. Do not change, add or remove any words - only organize them.\n"
            f"- {SECTION_LABEL_GUIDE}\n"
            "- Identify verses, chorus, bridge etc. from repetition and position. Put each distinct section "
            "in `sections` once, and the full sung sequence (with repeats, as the pasted text implies) in `order`.\n"
            "- If the text has no verse/chorus structure (e.g. a continuous prayer or a through-composed song), "
            "set structured=false, return a single section with an empty label, and leave order empty.\n"
            f"- {LINE_GUIDE} You may re-break overly long lines, but keep every word.\n"
            "- Remove chord symbols (e.g. G, Am7, D/F#) and markers like 'x2' from the lyric lines; "
            "reflect 'x2' as repetition in order.\n"
            "- note: Korean, one short sentence, only if something was ambiguous; otherwise empty."
        )
        content = f"제목: {title}\n\n가사:\n{raw_text}" if title else f"가사:\n{raw_text}"
        data = self._request_json(system=system, content=content, effort="low", schema=SONG_SCHEMA)
        song = _song_from_json(data)
        if not song.sections:
            raise AIError("가사를 나누지 못했습니다. 입력한 가사를 확인해 주세요.")
        song.title = song.title or title
        return song

    # ------------------------------------------------------------------
    # 3) 악보 사진/PDF 에서 가사 읽기
    # ------------------------------------------------------------------
    def read_sheet_music(self, paths: list[str | Path], title_hint: str = "") -> Song:
        blocks: list = []
        for p in paths:
            path = Path(p)
            if path.suffix.lower() == ".pdf":
                blocks.append(_pdf_block(path))
            else:
                blocks.append(_image_block(path))
        system = (
            "You read sheet music (lead sheets / scores, often Korean worship songs) and extract the lyrics "
            "for church lyric slides.\n"
            "- Read every page in order. Extract only lyrics, not chords, tempo, composer credits or copyright lines "
            "(but use the printed title and composer for title/artist).\n"
            "- Lyrics under notes are split into syllables; join them into normal words with correct Korean "
            "spacing (띄어쓰기). Hyphens between syllables join a word.\n"
            "- When several lyric lines are stacked under the same staff (1절/2절/3절 or 1./2./3.), each stacked "
            "line belongs to a different verse: output Verse 1, Verse 2, ... separately.\n"
            "- Use section marks printed on the music (Verse, Chorus, 후렴, Bridge, Pre-Chorus, Tag, Ending) and "
            "musical structure. Follow repeat signs, 1st/2nd endings, D.S./D.C./Coda/Fine to build the full "
            "performance `order` (repeats allowed).\n"
            f"- {SECTION_LABEL_GUIDE}\n"
            f"- {LINE_GUIDE}\n"
            "- If the song has no verse/chorus structure, set structured=false with one unlabeled section.\n"
            "- Never invent words. If some lyrics are unreadable, keep what you can read and mention it in note "
            "(Korean)."
        )
        hint = f"곡 제목(참고): {title_hint}\n" if title_hint else ""
        blocks.append({"type": "text", "text": hint + "이 악보의 가사를 파트별로 정리해 주세요."})
        data = self._request_json(system=system, content=blocks, effort="high", schema=SONG_SCHEMA)
        song = _song_from_json(data)
        if not song.sections:
            raise AIError("악보에서 가사를 찾지 못했습니다. 더 선명한 사진으로 다시 시도해 주세요.")
        song.title = song.title or title_hint
        return song

    # ------------------------------------------------------------------
    # 4) 성경 본문 가져오기
    # ------------------------------------------------------------------
    def fetch_scripture(self, reference: str, translation: str) -> str:
        system = (
            "You fetch Bible passages for church worship slides. Use web search to find the exact text of the "
            "requested passage in the requested translation and copy it exactly, verse by verse. "
            "Do not paraphrase, summarize, or mix translations. Reply with exactly one block:\n"
            "<scripture>\n16 verse text\n17 verse text\n</scripture>\n"
            "One verse per line, each line starting with the verse number and a space. If the passage spans "
            "chapters, write the chapter as '4:1 verse text' for verses of the new chapter. "
            "If you cannot find the exact text, reply <not_found>reason in Korean</not_found>."
        )
        text = self._request(system=system, content=f"본문: {reference}\n번역본: {translation}",
                             effort="low", tools=[self._web_search_tool(4)])
        body = _extract_tag(text, "scripture")
        if not body:
            raise AIError(_extract_tag(text, "not_found") or "본문을 찾지 못했습니다. 직접 붙여넣어 주세요.")
        return "\n".join(ln.strip() for ln in body.splitlines() if ln.strip())

    # ------------------------------------------------------------------
    # 5) 설교 원고 -> 슬라이드 요점
    # ------------------------------------------------------------------
    def summarize_sermon(self, notes: str, title: str = "", reference: str = "") -> str:
        system = (
            "You turn a pastor's sermon notes or manuscript into projection slides for the congregation, in Korean.\n"
            "- Follow the sermon's own outline (서론, 대지 1/2/3, 결론, 적용) in order.\n"
            "- Each slide: 1-4 short lines. Key points as short headings (e.g. '1. 하나님은 사랑이시다'), "
            "supporting lines short. Keep quoted Bible verses with their references.\n"
            "- Use the preacher's own wording and key phrases; do not add new content, theology or illustrations.\n"
            "- Usually 4-12 slides."
        )
        head = "\n".join(x for x in (f"설교 제목: {title}" if title else "", f"본문: {reference}" if reference else "") if x)
        data = self._request_json(system=system, content=f"{head}\n\n설교 원고/메모:\n{notes}",
                                  effort="medium", schema=SERMON_SCHEMA)
        blocks = []
        for slide in data.get("slides", []):
            lines = [ln.strip() for ln in slide.get("lines", []) if ln.strip()]
            if lines:
                blocks.append("\n".join(lines))
        if not blocks:
            raise AIError("설교 내용을 정리하지 못했습니다.")
        return "\n\n".join(blocks)

    # ------------------------------------------------------------------
    def test_connection(self) -> str:
        text = self._request(system="Reply with the single word OK.", content="ping", effort="low", max_tokens=2000)
        return text.strip() or "OK"
