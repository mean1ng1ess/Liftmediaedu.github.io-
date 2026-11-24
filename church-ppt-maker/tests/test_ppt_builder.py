import pytest
from pptx import Presentation
from pptx.util import Emu

from churchppt.design import TemplateDesign
from churchppt.lyrics_format import parse_song_text
from churchppt.ppt_builder import (BuildError, P14_NS, build_presentation,
                                   fit_scale, make_sample_template,
                                   read_sections)
from churchppt.service import (ITEM_COVER, ITEM_SCRIPTURE, ITEM_SERMON,
                               ITEM_SONG, ITEM_TEXT, Service, ServiceItem,
                               service_to_slides, song_to_data)

SONG = parse_song_text("""제목: 곡
순서: V1 C V2 C

[Verse 1]
일 일
일 이
일 삼

[Chorus]
후 일
후 이

[Verse 2]
이 일
""")


def items():
    return [
        ServiceItem.new(ITEM_COVER, title="주일 예배", date="2026년 11월 29일"),
        ServiceItem(ITEM_SONG, song_to_data(SONG)),
        ServiceItem.new(ITEM_SCRIPTURE, reference="요한복음 3:16", text="16 본문\n17 본문 둘\n18 본문 셋"),
        ServiceItem.new(ITEM_SERMON, title="설교", body="요점1\n\n요점2"),
        ServiceItem.new(ITEM_TEXT, title="광고", body="하나\n\n둘"),
    ]


def all_text(slide):
    return "\n".join(s.text_frame.text for s in slide.shapes if s.has_text_frame)


def test_slide_specs_follow_song_order():
    d = TemplateDesign(lines_per_slide=2, blank_after_song=True)
    slides = service_to_slides(items(), d)
    names = [s.section_name for s in slides]
    assert names[0] == "표지"
    lyric = [s for s in slides if s.kind == "lyrics"]
    assert [s.label for s in lyric] == ["Verse 1", "Verse 1", "Chorus", "Verse 2", "Chorus"]
    assert lyric[0].lines == ["일 일", "일 이"] and lyric[1].lines == ["일 삼"]
    assert any(s.kind == "blank" for s in slides)


def test_song_section_mode():
    d = TemplateDesign(section_mode="song")
    slides = service_to_slides([ServiceItem(ITEM_SONG, song_to_data(SONG))], d)
    assert len({s.section_id for s in slides}) == 1


def test_build_design_with_sections(tmp_path):
    d = TemplateDesign()
    slides = service_to_slides(items(), d)
    out = build_presentation(slides, d, tmp_path / "out.pptx")
    prs = Presentation(str(out))
    assert len(prs.slides) == len(slides)
    secs = read_sections(out)
    assert [n for n, _ in secs][:5] == ["표지", "곡 - Verse 1", "곡 - Chorus", "곡 - Verse 2", "곡 - Chorus"]
    assert sum(c for _, c in secs) == len(slides)
    # 섹션 확장은 extLst 안에, 모든 slide id 가 실제로 존재
    ids = {s.slide_id for s in prs.slides}
    sec_ids = {int(e.get("id")) for e in prs.part._element.iter(f"{{{P14_NS}}}sldId")}
    assert sec_ids == ids
    # 한글 글꼴(ea) 지정
    xml = prs.slides[1].shapes[0]._element.xml
    assert 'typeface="맑은 고딕"' in xml and "<a:ea" in xml
    assert "일 일" in all_text(prs.slides[1])
    assert prs.slides[1].has_notes_slide


def test_build_43_and_background_image(tmp_path):
    from PIL import Image
    img = tmp_path / "bg.png"
    Image.new("RGB", (400, 100), "navy").save(img)
    d = TemplateDesign(ratio="4:3", bg_image=str(img), bg_dim=40)
    out = build_presentation(service_to_slides(items()[:2], d), d, tmp_path / "o.pptx")
    prs = Presentation(str(out))
    assert prs.slide_width == Emu(9144000)
    pic = prs.slides[0].shapes[0]
    assert pic.name == "Background" and pic.crop_left > 0.3


def test_source_template_roundtrip(tmp_path):
    sample = make_sample_template(TemplateDesign(), tmp_path / "sample.pptx")
    d = TemplateDesign(source_pptx=str(sample))
    slides = service_to_slides(items(), d)
    out = build_presentation(slides, d, tmp_path / "src.pptx")
    prs = Presentation(str(out))
    assert len(prs.slides) == len(slides)          # 견본 슬라이드 3장은 제거됨
    texts = [all_text(s) for s in prs.slides]
    assert not any("{{" in t for t in texts)
    assert "주일 예배" in texts[0]
    assert "일 일" in texts[1] and "Verse 1" in texts[1]
    scripture = next(t for t in texts if "16 본문" in t)
    assert "요한복음 3:16" in scripture
    assert read_sections(out)[1][0] == "곡 - Verse 1"


def test_source_with_only_lyrics_marker_keeps_headings(tmp_path):
    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[6])
    s.shapes.add_textbox(Emu(500000), Emu(1000000), Emu(8000000), Emu(4000000)).text_frame.text = "{{가사}}"
    src = tmp_path / "lyrics_only.pptx"
    prs.save(str(src))
    d = TemplateDesign(source_pptx=str(src))
    out = build_presentation(service_to_slides(items(), d), d, tmp_path / "o.pptx")
    texts = [all_text(sl) for sl in Presentation(str(out)).slides]
    assert texts[0].startswith("주일 예배")
    assert any(t.startswith("요한복음 3:16") and "16 본문" in t for t in texts)


def test_source_template_without_markers(tmp_path):
    # 마커 없는 일반 PPT: 가장 큰 글상자에 가사가 들어간다
    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[6])
    s.shapes.add_textbox(Emu(100000), Emu(100000), Emu(200000), Emu(100000)).text_frame.text = "교회 이름"
    big = s.shapes.add_textbox(Emu(500000), Emu(1000000), Emu(8000000), Emu(4000000))
    big.text_frame.text = "샘플"
    src = tmp_path / "plain.pptx"
    prs.save(str(src))
    d = TemplateDesign(source_pptx=str(src))
    out = build_presentation(service_to_slides([ServiceItem(ITEM_SONG, song_to_data(SONG))], d), d,
                             tmp_path / "o.pptx")
    first = Presentation(str(out)).slides[0]
    texts = [sh.text_frame.text for sh in first.shapes if sh.has_text_frame]
    assert "교회 이름" in texts and "일 일\n일 이" in texts


def test_missing_source_and_empty():
    with pytest.raises(BuildError):
        build_presentation([], TemplateDesign(), "x.pptx")
    d = TemplateDesign(source_pptx="/nope/none.pptx")
    with pytest.raises(BuildError):
        build_presentation(service_to_slides(items(), d), d, "x.pptx")


def test_fit_scale_shrinks_long_text():
    assert fit_scale([("짧은 가사", 44)], 800, 400, 1.2) == 1.0
    assert fit_scale([("아주 긴 가사 " * 40, 44)], 800, 400, 1.2) < 1.0


def test_service_json_roundtrip(tmp_path):
    svc = Service("예배", items())
    p = tmp_path / "s.json"
    svc.save(p)
    again = Service.load(p)
    assert [i.kind for i in again.items] == [i.kind for i in svc.items]
    assert again.items[1].data["body"] == svc.items[1].data["body"]


def test_design_json_roundtrip(tmp_path):
    d = TemplateDesign(name="테스트", lines_per_slide=3)
    d.lyrics.color = "#FF0000"
    d.save(tmp_path / "t.json")
    again = TemplateDesign.load(tmp_path / "t.json")
    assert again == d
