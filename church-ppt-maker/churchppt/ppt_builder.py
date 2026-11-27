"""SlideSpec 목록 -> .pptx 파일.

두 가지 방식:
  * DesignBuilder : 프로그램의 '템플릿 편집'에서 만든 디자인으로 새 PPT 생성
  * SourceBuilder : 사용자가 가진 PPT 파일(소스)의 슬라이드를 복제해서 글자만 바꿔 넣음

두 방식 모두 PowerPoint 의 '구역(섹션)' 기능으로 Verse / Chorus / Bridge 등을 나눈다.
"""
from __future__ import annotations

import copy
import math
import re
import uuid
from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE, PP_PLACEHOLDER
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.shapes.group import GroupShape
from pptx.oxml.ns import qn
from pptx.util import Emu

from .design import TemplateDesign, TextStyle
from .models import KIND_BLANK, KIND_CONTENT, KIND_COVER, KIND_LYRICS, SlideSpec

SLIDE_SIZES = {"16:9": (Emu(12192000), Emu(6858000)), "4:3": (Emu(9144000), Emu(6858000))}
EMU_PER_PT = 12700

_ALIGN = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT}
_ANCHOR = {"top": MSO_ANCHOR.TOP, "middle": MSO_ANCHOR.MIDDLE, "bottom": MSO_ANCHOR.BOTTOM}

P14_NS = "http://schemas.microsoft.com/office/powerpoint/2010/main"
SECTION_EXT_URI = "{521415D9-36F7-43E2-AB2F-B90AF26B5E84}"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

# 소스 PPT 에서 쓰는 자리표시 글자
MARKERS = {
    "lyrics": ("{{가사}}", "{{lyrics}}"),
    "body": ("{{본문}}", "{{내용}}", "{{body}}"),
    "title": ("{{제목}}", "{{title}}"),
    "subtitle": ("{{부제}}", "{{부제목}}", "{{subtitle}}"),
    "label": ("{{섹션}}", "{{파트}}", "{{section}}"),
}
ALL_MARKERS = tuple(m for ms in MARKERS.values() for m in ms)


class BuildError(Exception):
    pass


# ---------------------------------------------------------------------------
# 글자 크기 자동 맞춤 (대략적인 글자 폭 계산)
# ---------------------------------------------------------------------------

def _char_em(ch: str) -> float:
    o = ord(ch)
    if ch == " ":
        return 0.28
    if (0x1100 <= o <= 0x11FF or 0x3130 <= o <= 0x318F or 0xAC00 <= o <= 0xD7AF
            or 0x4E00 <= o <= 0x9FFF or 0x3000 <= o <= 0x303F or 0xFF00 <= o <= 0xFFEF):
        return 0.95
    if ch.isupper():
        return 0.66
    if ch.isdigit():
        return 0.56
    if ch.isalpha():
        return 0.52
    return 0.36


def text_em(text: str) -> float:
    return sum(_char_em(c) for c in text)


def fit_scale(paras: list[tuple[str, float]], box_w_pt: float, box_h_pt: float,
              spacing: float, min_scale: float = 0.5) -> float:
    """문단들(글자, 크기pt)이 상자 안에 들어가는 배율(<=1)."""
    if box_w_pt <= 0 or box_h_pt <= 0:
        return 1.0

    def height(scale: float) -> float:
        h = 0.0
        for text, size in paras:
            s = size * scale
            width = text_em(text) * s * 1.08
            n = max(1, math.ceil(width / box_w_pt)) if text else 1
            h += n * s * spacing * 1.2
        return h

    scale = 1.0
    while scale > min_scale and height(scale) > box_h_pt:
        scale -= 0.03
    return max(scale, min_scale)


# ---------------------------------------------------------------------------
# 글자 서식
# ---------------------------------------------------------------------------

def _hex(color: str) -> str:
    c = (color or "#FFFFFF").lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    return c.upper()[:6].rjust(6, "0")


def _sub(parent, tag: str, **attrs):
    el = etree.SubElement(parent, qn(tag))
    for k, v in attrs.items():
        el.set(k, str(v))
    return el


def style_run(run, style: TextStyle, size_pt: float) -> None:
    """run 의 rPr 을 스키마 순서대로 새로 만든다 (외곽선, 색, 그림자, 한글 글꼴)."""
    rPr = run._r.get_or_add_rPr()
    for child in list(rPr):
        rPr.remove(child)
    rPr.set("lang", "ko-KR")
    rPr.set("altLang", "en-US")
    rPr.set("sz", str(int(round(size_pt * 100))))
    rPr.set("b", "1" if style.bold else "0")
    if style.outline:
        ln = _sub(rPr, "a:ln", w=int(style.outline_width * EMU_PER_PT))
        fill = _sub(ln, "a:solidFill")
        _sub(fill, "a:srgbClr", val=_hex(style.outline_color))
    fill = _sub(rPr, "a:solidFill")
    _sub(fill, "a:srgbClr", val=_hex(style.color))
    if style.shadow:
        eff = _sub(rPr, "a:effectLst")
        sh = _sub(eff, "a:outerShdw", blurRad=50800, dist=25400, dir=2700000, algn="tl", rotWithShape=0)
        clr = _sub(sh, "a:srgbClr", val="000000")
        _sub(clr, "a:alpha", val=70000)
    for tag in ("a:latin", "a:ea", "a:cs"):
        _sub(rPr, tag, typeface=style.font)


def add_text_box(slide, x, y, w, h, paras, align: str, anchor: str, spacing: float,
                 auto_shrink: bool = True, name: str = "Text"):
    """paras: [(글자, TextStyle, 크기pt, [(앞부분글자, TextStyle, 크기pt)] 선택)]"""
    tb = slide.shapes.add_textbox(x, y, w, h)
    tb.name = name
    tf = tb.text_frame
    tf.word_wrap = True
    tf.auto_size = MSO_AUTO_SIZE.NONE
    tf.vertical_anchor = _ANCHOR.get(anchor, MSO_ANCHOR.MIDDLE)
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0

    scale = 1.0
    if auto_shrink:
        scale = fit_scale([(p[0] if len(p) < 4 or not p[3] else p[3][0] + " " + p[0], p[2]) for p in paras],
                          w / EMU_PER_PT, h / EMU_PER_PT, spacing)
    for i, para in enumerate(paras):
        text, style, size = para[0], para[1], para[2]
        prefix = para[3] if len(para) > 3 else None
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = _ALIGN.get(align, PP_ALIGN.CENTER)
        p.line_spacing = spacing
        if prefix:
            ptext, pstyle, psize = prefix
            r = p.add_run()
            r.text = ptext + " "
            style_run(r, pstyle, psize * scale)
        r = p.add_run()
        r.text = text
        style_run(r, style, size * scale)
    return tb


# ---------------------------------------------------------------------------
# PowerPoint 구역(섹션)
# ---------------------------------------------------------------------------

def apply_sections(prs, groups: list[tuple[str, list[int]]]) -> None:
    pres = prs.part._element
    ext_lst = pres.find(qn("p:extLst"))
    if ext_lst is None:
        ext_lst = etree.SubElement(pres, qn("p:extLst"))
    for ext in ext_lst.findall(qn("p:ext")):
        if ext.get("uri") == SECTION_EXT_URI:
            ext_lst.remove(ext)
    if not groups:
        return
    ext = etree.Element(qn("p:ext"))
    ext.set("uri", SECTION_EXT_URI)
    ext_lst.insert(0, ext)
    sec_lst = etree.SubElement(ext, f"{{{P14_NS}}}sectionLst", nsmap={"p14": P14_NS})
    for name, slide_ids in groups:
        sec = etree.SubElement(sec_lst, f"{{{P14_NS}}}section")
        sec.set("name", name or "구역")
        sec.set("id", "{" + str(uuid.uuid4()).upper() + "}")
        lst = etree.SubElement(sec, f"{{{P14_NS}}}sldIdLst")
        for sid in slide_ids:
            etree.SubElement(lst, f"{{{P14_NS}}}sldId").set("id", str(sid))


def read_sections(path: str | Path) -> list[tuple[str, int]]:
    """(구역 이름, 슬라이드 수) - 확인/테스트용."""
    prs = Presentation(str(path))
    pres = prs.part._element
    out = []
    for sec in pres.iter(f"{{{P14_NS}}}section"):
        out.append((sec.get("name"), len(sec.findall(f".//{{{P14_NS}}}sldId"))))
    return out


# ---------------------------------------------------------------------------
# 직접 디자인 방식
# ---------------------------------------------------------------------------

class DesignBuilder:
    def __init__(self, design: TemplateDesign, prs=None, layout=None):
        self.d = design
        if prs is None:
            prs = Presentation()
            w, h = SLIDE_SIZES.get(design.ratio, SLIDE_SIZES["16:9"])
            prs.slide_width, prs.slide_height = w, h
            layout = prs.slide_layouts[6]  # 빈 화면
            self.own_background = True
        else:
            self.own_background = False
        self.prs = prs
        self.layout = layout
        self.W = prs.slide_width
        self.H = prs.slide_height
        self._bg_crop = None

    # --- 배경 ---------------------------------------------------------
    def _background(self, slide) -> None:
        d = self.d
        fill = slide.background.fill
        fill.solid()
        fill.fore_color.rgb = RGBColor.from_string(_hex(d.bg_color))
        if d.bg_image and Path(d.bg_image).is_file():
            pic = slide.shapes.add_picture(d.bg_image, 0, 0, self.W, self.H)
            pic.name = "Background"
            self._cover_crop(pic, d.bg_image)
            if d.bg_dim > 0:
                rect = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, self.W, self.H)
                rect.name = "Dim"
                rect.line.fill.background()
                rect.fill.solid()
                rect.fill.fore_color.rgb = RGBColor(0, 0, 0)
                srgb = rect.fill._xPr.find(qn("a:solidFill")).find(qn("a:srgbClr"))
                _sub(srgb, "a:alpha", val=int(min(90, d.bg_dim) * 1000))

    def _cover_crop(self, pic, path: str) -> None:
        if self._bg_crop is None:
            try:
                from PIL import Image
                with Image.open(path) as im:
                    iw, ih = im.size
            except Exception:
                self._bg_crop = (0, 0, 0, 0)
            else:
                slide_ratio = self.W / self.H
                img_ratio = iw / ih
                if img_ratio > slide_ratio:  # 이미지가 더 넓음 -> 좌우 자르기
                    c = (1 - slide_ratio / img_ratio) / 2
                    self._bg_crop = (c, c, 0, 0)
                else:
                    c = (1 - img_ratio / slide_ratio) / 2
                    self._bg_crop = (0, 0, c, c)
        l, r, t, b = self._bg_crop
        pic.crop_left, pic.crop_right, pic.crop_top, pic.crop_bottom = l, r, t, b

    # --- 슬라이드 -----------------------------------------------------
    def new_slide(self):
        slide = self.prs.slides.add_slide(self.layout)
        for shp in list(slide.placeholders):
            shp._element.getparent().remove(shp._element)
        if self.own_background:
            self._background(slide)
        return slide

    def _margins(self):
        mx = int(self.W * self.d.margin)
        my = int(self.W * self.d.margin * 0.75)
        return mx, my

    def add(self, spec: SlideSpec):
        slide = self.new_slide()
        self.draw(slide, spec)
        return slide

    def draw(self, slide, spec: SlideSpec, box=None) -> None:
        d = self.d
        mx, my = self._margins()
        if box is None:
            X, Y, BW, BH = mx, my, self.W - 2 * mx, self.H - 2 * my
        else:
            X, Y, BW, BH = box

        if spec.kind == KIND_BLANK:
            return

        if spec.kind == KIND_LYRICS:
            top = Y
            if spec.heading:
                hs = d.label_style
                band = int(self.H * 0.1)
                add_text_box(slide, X, Y, BW, band, [(spec.heading, hs, hs.size + 6)],
                             "center", "top", 1.0, name="SongTitle")
                top = Y + band
            if d.show_label and spec.label:
                ls = d.label_style
                add_text_box(slide, int(mx * 0.4), int(my * 0.4), int(self.W * 0.3), int(self.H * 0.08),
                             [(spec.label, ls, ls.size)], "left", "top", 1.0, auto_shrink=False, name="Label")
            paras = [(ln, d.lyrics, d.lyrics.size) for ln in spec.lines]
            add_text_box(slide, X, top, BW, Y + BH - top, paras, d.lyrics_align, d.lyrics_anchor,
                         d.line_spacing, d.auto_shrink, name="Lyrics")
            return

        if spec.kind == KIND_COVER:
            paras = [(spec.heading, d.title_style, d.title_style.size)]
            for ln in spec.subtitle.splitlines():
                if ln.strip():
                    paras.append((ln.strip(), d.body_style, d.body_style.size * 0.8))
            add_text_box(slide, X, Y, BW, BH, paras, "center", "middle", 1.15, d.auto_shrink, name="Title")
            return

        # KIND_CONTENT
        body_top = Y
        if spec.heading:
            hh = int(BH * 0.17)
            hs = d.heading_style
            add_text_box(slide, X, Y, BW, hh, [(spec.heading, hs, hs.size)], d.content_align, "middle",
                         1.0, d.auto_shrink, name="Heading")
            body_top = Y + int(BH * 0.21)
        bs = d.body_style
        paras = []
        for ln in spec.lines:
            m = re.match(r"^(\d{1,3})\s+(.+)$", ln) if spec.hint == "scripture" else None
            if m:
                num_style = copy.copy(d.heading_style)
                num_style.outline = bs.outline
                paras.append((m.group(2), bs, bs.size, (m.group(1), num_style, bs.size * 0.65)))
            else:
                paras.append((ln, bs, bs.size))
        add_text_box(slide, X, body_top, BW, Y + BH - body_top, paras, d.content_align,
                     "top" if spec.heading else "middle", d.line_spacing, d.auto_shrink, name="Body")

    def finish(self) -> None:
        pass


# ---------------------------------------------------------------------------
# 소스 PPT 방식
# ---------------------------------------------------------------------------

def _iter_text_shapes(shapes):
    for shp in shapes:
        if isinstance(shp, GroupShape):
            yield from _iter_text_shapes(shp.shapes)
        elif getattr(shp, "has_text_frame", False) and shp.has_text_frame:
            yield shp


def _slide_text(slide) -> str:
    return "\n".join(s.text_frame.text for s in _iter_text_shapes(slide.shapes))


def _has_marker(text: str, key: str) -> bool:
    return any(m in text for m in MARKERS[key])


def clone_slide(prs, src):
    """같은 PPT 안에서 슬라이드 복제 (배경, 그림, 도형, 전환효과 포함)."""
    new = prs.slides.add_slide(src.slide_layout)
    for shp in list(new.shapes):
        shp._element.getparent().remove(shp._element)

    rid_map: dict[str, str] = {}
    for rId, rel in src.part.rels.items():
        rt = rel.reltype
        if rt in (RT.SLIDE_LAYOUT, RT.NOTES_SLIDE) or rt.endswith("/comments"):
            continue
        if rel.is_external:
            rid_map[rId] = new.part.relate_to(rel.target_ref, rt, is_external=True)
        else:
            rid_map[rId] = new.part.relate_to(rel.target_part, rt)

    src_sld, new_sld = src._element, new._element
    src_csld, new_csld = src_sld.cSld, new_sld.cSld
    # 배경
    old_bg = new_csld.find(qn("p:bg"))
    if old_bg is not None:
        new_csld.remove(old_bg)
    src_bg = src_csld.find(qn("p:bg"))
    if src_bg is not None:
        new_csld.insert(0, copy.deepcopy(src_bg))
    # 도형
    tree = new_csld.spTree
    for child in src_csld.spTree.iterchildren():
        if child.tag in (qn("p:nvGrpSpPr"), qn("p:grpSpPr")):
            continue
        tree.append(copy.deepcopy(child))
    # 슬라이드 속성 (마스터 도형 숨김 등)
    for attr in ("showMasterSp", "show"):
        if src_sld.get(attr) is not None:
            new_sld.set(attr, src_sld.get(attr))
    # 색 매핑, 전환 효과
    for child in src_sld.iterchildren():
        if child.tag in (qn("p:cSld"), qn("p:timing"), qn("p:extLst")):
            continue
        existing = new_sld.find(child.tag)
        if existing is not None:
            new_sld.replace(existing, copy.deepcopy(child))
        else:
            ext = new_sld.find(qn("p:extLst"))
            if ext is not None:
                ext.addprevious(copy.deepcopy(child))
            else:
                new_sld.append(copy.deepcopy(child))
    # 관계 id 다시 연결
    for el in new_sld.iter():
        for attr, val in list(el.attrib.items()):
            if attr.startswith("{%s}" % R_NS) and val in rid_map:
                el.set(attr, rid_map[val])
    return new


def delete_slide(prs, slide) -> None:
    sld_id_lst = prs.slides._sldIdLst
    for sld_id in list(sld_id_lst):
        if prs.part.related_part(sld_id.rId) is slide.part:
            rId = sld_id.rId
            sld_id_lst.remove(sld_id)
            prs.part.drop_rel(rId)
            return


def _make_paragraph(template_p, text: str):
    p = copy.deepcopy(template_p)
    rpr = None
    for r in template_p.findall(qn("a:r")):
        rpr = r.find(qn("a:rPr"))
        if rpr is not None:
            break
    for child in list(p):
        if child.tag in (qn("a:r"), qn("a:br"), qn("a:fld")):
            p.remove(child)
    if text:
        r = etree.Element(qn("a:r"))
        if rpr is not None:
            r.append(copy.deepcopy(rpr))
        t = etree.SubElement(r, qn("a:t"))
        t.text = text
        end = p.find(qn("a:endParaRPr"))
        if end is not None:
            end.addprevious(r)
        else:
            p.append(r)
    return p


def set_paragraph_lines(p_el, lines: list[str]) -> None:
    """문단 하나를 여러 줄(각각 문단)로 바꾼다. 서식은 원래 문단 그대로."""
    parent = p_el.getparent()
    idx = parent.index(p_el)
    template = copy.deepcopy(p_el)
    parent.remove(p_el)
    for i, line in enumerate(lines or [""]):
        parent.insert(idx + i, _make_paragraph(template, line))


def set_shape_lines(shape, lines: list[str]) -> None:
    txBody = shape.text_frame._txBody
    paras = txBody.findall(qn("a:p"))
    first = paras[0]
    for p in paras[1:]:
        txBody.remove(p)
    set_paragraph_lines(first, lines)


def _shrink_shape_to_fit(shape, spacing: float = 1.2) -> None:
    """글자 크기가 명시된 경우에만, 넘치면 줄인다."""
    try:
        w = shape.width / EMU_PER_PT
        h = shape.height / EMU_PER_PT
    except Exception:
        return
    runs = list(shape.text_frame._txBody.iter(qn("a:rPr")))
    sizes = [int(r.get("sz")) / 100 for r in runs if r.get("sz")]
    if not sizes or not w or not h:
        return
    size = max(sizes)
    paras = [(p.text, size) for p in shape.text_frame.paragraphs]
    scale = fit_scale(paras, w * 0.95, h * 0.95, spacing)
    if scale < 0.999:
        for r in runs:
            if r.get("sz"):
                r.set("sz", str(int(int(r.get("sz")) * scale)))


class SourceBuilder:
    def __init__(self, design: TemplateDesign):
        self.d = design
        path = Path(design.source_pptx)
        if not path.is_file():
            raise BuildError(f"소스 PPT 파일을 찾을 수 없습니다:\n{path}")
        try:
            self.prs = Presentation(str(path))
        except Exception as e:  # 손상/암호 파일 등
            raise BuildError(f"소스 PPT 파일을 열 수 없습니다: {e}") from e
        self.templates = list(self.prs.slides)
        self.fallback = None
        if not self.templates:
            layouts = self.prs.slide_layouts
            layout = layouts[6] if len(layouts) > 6 else layouts[len(layouts) - 1]
            self.fallback = DesignBuilder(design, self.prs, layout)
            return
        texts = [_slide_text(s) for s in self.templates]

        def pick(setting: int, predicate, default):
            if 1 <= setting <= len(self.templates):
                return self.templates[setting - 1]
            for s, t in zip(self.templates, texts):
                if predicate(t):
                    return s
            return default

        self.lyrics_tpl = pick(design.source_lyrics_slide, lambda t: _has_marker(t, "lyrics"), self.templates[0])
        self.content_tpl = pick(design.source_content_slide, lambda t: _has_marker(t, "body"), self.lyrics_tpl)
        self.cover_tpl = pick(
            design.source_cover_slide,
            lambda t: _has_marker(t, "title") and not _has_marker(t, "lyrics") and not _has_marker(t, "body"),
            self.content_tpl if _has_marker(_slide_text(self.content_tpl), "title") else self.lyrics_tpl,
        )
        self._helper = DesignBuilder(design, self.prs, self.templates[0].slide_layout)

    def add(self, spec: SlideSpec):
        if self.fallback:
            return self.fallback.add(spec)
        tpl = {KIND_COVER: self.cover_tpl, KIND_CONTENT: self.content_tpl}.get(spec.kind, self.lyrics_tpl)
        slide = clone_slide(self.prs, tpl)
        self._fill(slide, spec)
        return slide

    def _fill(self, slide, spec: SlideSpec) -> None:
        if spec.kind == KIND_LYRICS:
            main = spec.lines
        elif spec.kind == KIND_CONTENT:
            main = spec.lines
        elif spec.kind == KIND_COVER:
            main = [spec.heading] + [ln for ln in spec.subtitle.splitlines() if ln.strip()]
        else:
            main = []
        values = {
            "lyrics": main,
            "body": main,
            "title": [spec.heading] if spec.heading else [],
            "subtitle": [ln for ln in spec.subtitle.splitlines() if ln.strip()],
            "label": [spec.label] if spec.label else [],
        }
        if spec.kind == KIND_LYRICS and spec.song:
            values["title"] = [spec.song]   # 가사 템플릿에 {{제목}}이 있으면 곡 제목을 매번 표시
        if spec.kind == KIND_BLANK:
            values = {k: [] for k in values}

        shapes = list(_iter_text_shapes(slide.shapes))
        slide_text = "\n".join(s.text_frame.text for s in shapes)
        has_any_marker = any(m in slide_text for m in ALL_MARKERS)
        if spec.kind == KIND_COVER and _has_marker(slide_text, "title"):
            values["lyrics"] = values["body"] = values["subtitle"]
        if spec.kind == KIND_CONTENT and spec.heading and not _has_marker(slide_text, "title"):
            # 내용용 슬라이드가 따로 없어 가사 슬라이드를 쓰는 경우: 제목(성경 구절 등)을 첫 줄로
            values["lyrics"] = values["body"] = [spec.heading] + main

        if has_any_marker:
            for shp in shapes:
                self._replace_markers(shp, values)
            if self.d.auto_shrink:
                for shp in shapes:
                    _shrink_shape_to_fit(shp, self.d.line_spacing)
            return

        # 표시 글자가 없는 템플릿: 가장 큰 글상자에 내용, 제목 칸에 제목
        if not shapes:
            if spec.kind != KIND_BLANK:
                self._helper.draw(slide, spec)
            return
        title_shape = None
        for shp in shapes:
            if shp.is_placeholder and shp.placeholder_format.type in (
                    PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE):
                title_shape = shp
                break
        others = [s for s in shapes if s is not title_shape]
        main_shape = max(others, key=lambda s: (s.width or 0) * (s.height or 0)) if others else None
        if main_shape is None:
            main_shape, title_shape = title_shape, None
        if title_shape is not None:
            set_shape_lines(title_shape, [] if spec.kind == KIND_BLANK else
                            ([spec.heading] if spec.heading else []))
            if spec.kind == KIND_COVER:
                main = values["subtitle"]
        elif spec.kind == KIND_CONTENT and spec.heading:
            main = [spec.heading] + main
        set_shape_lines(main_shape, main)
        if self.d.auto_shrink:
            _shrink_shape_to_fit(main_shape, self.d.line_spacing)

    @staticmethod
    def _replace_markers(shape, values: dict[str, list[str]]) -> None:
        txBody = shape.text_frame._txBody
        for p in list(txBody.findall(qn("a:p"))):
            text = "".join(t.text or "" for t in p.iter(qn("a:t")))
            if not any(m in text for m in ALL_MARKERS):
                continue
            stripped = text.strip()
            whole = None
            for key, ms in MARKERS.items():
                if stripped in ms:
                    whole = key
            if whole is not None:
                set_paragraph_lines(p, values[whole])
                continue
            new = text
            for key, ms in MARKERS.items():
                for m in ms:
                    new = new.replace(m, " · ".join(values[key]))
            replacement = _make_paragraph(p, new.strip())
            p.addprevious(replacement)
            p.getparent().remove(p)

    def finish(self) -> None:
        if self.fallback:
            return
        for tpl in self.templates:
            delete_slide(self.prs, tpl)


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------

def build_presentation(slides: list[SlideSpec], design: TemplateDesign, out_path: str | Path) -> Path:
    if not slides:
        raise BuildError("만들 슬라이드가 없습니다. 예배 순서에 항목을 추가해 주세요.")
    builder = SourceBuilder(design) if design.uses_source else DesignBuilder(design)
    groups: list[tuple[int, str, list[int]]] = []
    for spec in slides:
        slide = builder.add(spec)
        if spec.notes:
            slide.notes_slide.notes_text_frame.text = spec.notes
        if groups and groups[-1][0] == spec.section_id:
            groups[-1][2].append(slide.slide_id)
        else:
            groups.append((spec.section_id, spec.section_name, [slide.slide_id]))
    builder.finish()
    apply_sections(builder.prs, [(name, ids) for _, name, ids in groups])
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        builder.prs.save(str(out))
    except PermissionError as e:
        raise BuildError(f"파일을 저장할 수 없습니다. PowerPoint 에서 열려 있다면 닫고 다시 시도하세요.\n{out}") from e
    return out


def make_sample_template(design: TemplateDesign, out_path: str | Path) -> Path:
    """{{제목}} {{가사}} 같은 자리표시가 들어간 '소스 PPT' 견본을 만든다.

    PowerPoint 에서 열어 배경/글꼴을 마음대로 꾸민 뒤, 템플릿 편집에서
    'PPT 소스 파일'로 지정하면 그 디자인 그대로 PPT 가 만들어진다.
    """
    d = TemplateDesign.from_dict(design.to_dict())
    d.source_pptx = ""
    d.show_label = True
    d.auto_shrink = False
    b = DesignBuilder(d)
    specs = [
        (SlideSpec(KIND_COVER, "", 0, heading="{{제목}}", subtitle="{{부제}}"),
         "표지/곡 제목 슬라이드: {{제목}} {{부제}} 자리에 글자가 들어갑니다."),
        (SlideSpec(KIND_LYRICS, "", 0, label="{{섹션}}", lines=["{{가사}}"]),
         "가사 슬라이드: {{가사}} 자리에 가사가, {{섹션}} 자리에 Verse/Chorus 이름이 들어갑니다. "
         "{{섹션}} 상자는 지워도 됩니다."),
        (SlideSpec(KIND_CONTENT, "", 0, heading="{{제목}}", lines=["{{본문}}"]),
         "성경/설교/광고 슬라이드: {{제목}} 에 제목, {{본문}} 에 내용이 들어갑니다."),
    ]
    for spec, note in specs:
        slide = b.add(spec)
        slide.notes_slide.notes_text_frame.text = note
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    b.prs.save(str(out))
    return out
