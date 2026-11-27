"""템플릿(PPT 디자인) 편집 창."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog,
                               QDoubleSpinBox, QFileDialog, QFontComboBox,
                               QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPushButton,
                               QRadioButton, QScrollArea, QSlider, QSpinBox,
                               QTabWidget, QVBoxLayout, QWidget)

from ..design import TemplateDesign, TextStyle
from ..lyrics_format import safe_filename
from ..models import KIND_CONTENT, KIND_COVER, KIND_LYRICS, SlideSpec
from ..ppt_builder import MARKERS, make_sample_template
from .common import ColorButton, ask_yes_no, open_path
from .preview import paint_slide, slide_size_pt

ALIGNS = [("left", "왼쪽"), ("center", "가운데"), ("right", "오른쪽")]
ANCHORS = [("top", "위"), ("middle", "가운데"), ("bottom", "아래 (방송 하단 자막)")]


def _combo(pairs, current: str) -> QComboBox:
    c = QComboBox()
    for value, text in pairs:
        c.addItem(text, value)
    idx = c.findData(current)
    c.setCurrentIndex(max(0, idx))
    return c


class StyleEditor(QWidget):
    changed = Signal()

    def __init__(self, style: TextStyle, with_effects: bool = True, parent=None):
        super().__init__(parent)
        lay = QFormLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.font = QFontComboBox()
        self.font.setEditable(True)
        self.font.setCurrentText(style.font)
        self.size = QSpinBox()
        self.size.setRange(8, 200)
        self.size.setSuffix(" pt")
        self.size.setValue(style.size)
        self.color = ColorButton(style.color)
        self.bold = QCheckBox("굵게")
        self.bold.setChecked(style.bold)
        row = QHBoxLayout()
        row.addWidget(self.size)
        row.addWidget(self.color)
        row.addWidget(self.bold)
        row.addStretch(1)
        lay.addRow("글꼴", self.font)
        lay.addRow("크기 / 색", row)

        self.outline = QCheckBox("외곽선")
        self.outline.setChecked(style.outline)
        self.outline_color = ColorButton(style.outline_color)
        self.outline_width = QDoubleSpinBox()
        self.outline_width.setRange(0.25, 10)
        self.outline_width.setSingleStep(0.25)
        self.outline_width.setSuffix(" pt")
        self.outline_width.setValue(style.outline_width)
        self.shadow = QCheckBox("그림자")
        self.shadow.setChecked(style.shadow)
        if with_effects:
            eff = QHBoxLayout()
            for w in (self.outline, self.outline_color, self.outline_width, self.shadow):
                eff.addWidget(w)
            eff.addStretch(1)
            lay.addRow("효과", eff)

        self.font.currentTextChanged.connect(self.changed)
        self.size.valueChanged.connect(self.changed)
        self.color.changed.connect(self.changed)
        self.bold.toggled.connect(self.changed)
        self.outline.toggled.connect(self.changed)
        self.outline_color.changed.connect(self.changed)
        self.outline_width.valueChanged.connect(self.changed)
        self.shadow.toggled.connect(self.changed)

    def style(self) -> TextStyle:
        return TextStyle(font=self.font.currentText().strip() or "맑은 고딕", size=self.size.value(),
                         color=self.color.color(), bold=self.bold.isChecked(),
                         outline=self.outline.isChecked(), outline_color=self.outline_color.color(),
                         outline_width=self.outline_width.value(), shadow=self.shadow.isChecked())


class _Preview(QWidget):
    def __init__(self, spec: SlideSpec, parent=None):
        super().__init__(parent)
        self.spec = spec
        self.design = TemplateDesign()
        self.setMinimumSize(320, 180)

    def set_design(self, design: TemplateDesign) -> None:
        self.design = design
        self.update()

    def paintEvent(self, _event) -> None:
        W, H = slide_size_pt(self.design)
        w = self.width()
        h = w * H / W
        if h > self.height():
            h = self.height()
            w = h * W / H
        rect = QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)
        p = QPainter(self)
        paint_slide(p, rect, self.spec, self.design)
        p.end()


class TemplateEditorDialog(QDialog):
    def __init__(self, design: TemplateDesign, templates_dir: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("템플릿(PPT 디자인) 편집")
        self.resize(1180, 760)
        self.templates_dir = Path(templates_dir)
        self.original_name = design.name
        self.saved_name: str | None = None
        d = TemplateDesign.from_dict(design.to_dict())
        self.design = d

        root = QHBoxLayout(self)
        left = QVBoxLayout()
        root.addLayout(left, 5)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("템플릿 이름"))
        self.name = QLineEdit(d.name)
        name_row.addWidget(self.name, 1)
        left.addLayout(name_row)

        tabs = QTabWidget()
        left.addWidget(tabs, 1)
        tabs.addTab(self._scroll(self._build_background_tab()), "배경 / 소스 PPT")
        tabs.addTab(self._scroll(self._build_lyrics_tab()), "가사 글자")
        tabs.addTab(self._scroll(self._build_text_tab()), "제목·본문 글자")
        tabs.addTab(self._scroll(self._build_layout_tab()), "슬라이드 구성")

        btns = QHBoxLayout()
        btns.addStretch(1)
        b_cancel = QPushButton("취소")
        b_save = QPushButton("저장")
        b_save.setProperty("primary", True)
        b_save.setMinimumWidth(110)
        btns.addWidget(b_cancel)
        btns.addWidget(b_save)
        left.addLayout(btns)
        b_cancel.clicked.connect(self.reject)
        b_save.clicked.connect(self.on_save)

        right = QVBoxLayout()
        root.addLayout(right, 4)
        right.addWidget(QLabel("미리보기 (실제 PPT와 조금 다를 수 있습니다)"))
        self.previews = [
            _Preview(SlideSpec(KIND_LYRICS, "", 0, heading="곡 제목", label="Verse 1",
                               lines=["샘플 가사 첫 번째 줄입니다", "두 번째 줄 가사가 여기에"])),
            _Preview(SlideSpec(KIND_COVER, "", 0, heading="주일 예배", subtitle="2026년 11월 29일")),
            _Preview(SlideSpec(KIND_CONTENT, "", 0, heading="요한복음 3:16 (개역개정)", hint="scripture",
                               lines=["16 성경 본문이 이 자리에 표시됩니다. 한 장에 몇 절씩 넣을지 정할 수 있습니다."])),
        ]
        for pv in self.previews:
            right.addWidget(pv, 1)
        self._update_mode()
        self._refresh()

    # ------------------------------------------------------------------
    @staticmethod
    def _scroll(w: QWidget) -> QScrollArea:
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setWidget(w)
        return sa

    def _build_background_tab(self) -> QWidget:
        d = self.design
        w = QWidget()
        lay = QVBoxLayout(w)

        mode_box = QGroupBox("디자인 방식")
        ml = QVBoxLayout(mode_box)
        self.mode_design = QRadioButton("직접 디자인 (아래에서 배경·글꼴을 고릅니다)")
        self.mode_source = QRadioButton("가지고 있는 PPT 파일(소스)의 디자인 그대로 사용")
        grp = QButtonGroup(self)
        grp.addButton(self.mode_design)
        grp.addButton(self.mode_source)
        (self.mode_source if d.uses_source else self.mode_design).setChecked(True)
        ml.addWidget(self.mode_design)
        ml.addWidget(self.mode_source)
        lay.addWidget(mode_box)

        # --- 소스 PPT ---
        self.source_box = QGroupBox("소스 PPT 파일")
        sl = QFormLayout(self.source_box)
        prow = QHBoxLayout()
        self.source_path = QLineEdit(d.source_pptx)
        self.source_path.setReadOnly(True)
        b_browse = QPushButton("찾아보기...")
        b_open = QPushButton("PowerPoint로 열기")
        prow.addWidget(self.source_path, 1)
        prow.addWidget(b_browse)
        prow.addWidget(b_open)
        sl.addRow("파일", prow)

        def slide_spin(value: int) -> QSpinBox:
            s = QSpinBox()
            s.setRange(0, 200)
            s.setSpecialValueText("자동")
            s.setPrefix("")
            s.setSuffix(" 번 슬라이드")
            s.setValue(value)
            return s

        self.src_lyrics = slide_spin(d.source_lyrics_slide)
        self.src_cover = slide_spin(d.source_cover_slide)
        self.src_content = slide_spin(d.source_content_slide)
        sl.addRow("가사용 슬라이드", self.src_lyrics)
        sl.addRow("표지/제목용 슬라이드", self.src_cover)
        sl.addRow("성경·설교·광고용 슬라이드", self.src_content)
        self.source_info = QLabel()
        self.source_info.setWordWrap(True)
        sl.addRow(self.source_info)
        help_text = QLabel(
            "· 소스 PPT의 글상자에 <b>{{가사}}</b>, <b>{{제목}}</b>, <b>{{부제}}</b>, <b>{{본문}}</b>, "
            "<b>{{섹션}}</b> 이라고 써 두면 그 자리에 글자가 들어갑니다. 글꼴·색·위치는 소스 그대로 유지됩니다.<br>"
            "· 표시가 없으면 가장 큰 글상자에 가사를 넣습니다. 글상자가 없으면 '가사 글자' 탭 설정으로 새로 만듭니다.<br>"
            "· 처음이라면 아래 [견본 소스 PPT 만들기] 로 만든 파일을 PowerPoint에서 꾸며서 쓰면 쉽습니다.")
        help_text.setWordWrap(True)
        help_text.setTextFormat(Qt.RichText)
        help_text.setStyleSheet("color:#555;")
        sl.addRow(help_text)
        b_sample = QPushButton("📄 견본 소스 PPT 만들기 (현재 디자인으로)")
        sl.addRow(b_sample)
        lay.addWidget(self.source_box)

        # --- 직접 디자인 배경 ---
        self.bg_box = QGroupBox("배경 (직접 디자인)")
        bl = QFormLayout(self.bg_box)
        self.ratio = _combo([("16:9", "16:9 (와이드)"), ("4:3", "4:3")], d.ratio)
        bl.addRow("화면 비율", self.ratio)
        self.bg_color = ColorButton(d.bg_color)
        bl.addRow("배경색", self.bg_color)
        irow = QHBoxLayout()
        self.bg_image = QLineEdit(d.bg_image)
        self.bg_image.setReadOnly(True)
        self.bg_image.setPlaceholderText("(없음)")
        b_img = QPushButton("사진 선택...")
        b_img_clear = QPushButton("지우기")
        irow.addWidget(self.bg_image, 1)
        irow.addWidget(b_img)
        irow.addWidget(b_img_clear)
        bl.addRow("배경 사진", irow)
        self.bg_dim = QSlider(Qt.Horizontal)
        self.bg_dim.setRange(0, 90)
        self.bg_dim.setValue(d.bg_dim)
        self.bg_dim_label = QLabel(f"{d.bg_dim}%")
        drow = QHBoxLayout()
        drow.addWidget(self.bg_dim, 1)
        drow.addWidget(self.bg_dim_label)
        bl.addRow("사진 어둡게", drow)
        lay.addWidget(self.bg_box)
        lay.addStretch(1)

        self.mode_design.toggled.connect(self._update_mode)
        self.mode_source.toggled.connect(self._update_mode)
        b_browse.clicked.connect(self.on_browse_source)
        b_open.clicked.connect(lambda: self.source_path.text() and open_path(self.source_path.text()))
        b_sample.clicked.connect(self.on_make_sample)
        for s in (self.src_lyrics, self.src_cover, self.src_content):
            s.valueChanged.connect(self._refresh)
        self.ratio.currentIndexChanged.connect(self._refresh)
        self.bg_color.changed.connect(self._refresh)
        b_img.clicked.connect(self.on_pick_image)
        b_img_clear.clicked.connect(lambda: (self.bg_image.setText(""), self._refresh()))
        self.bg_dim.valueChanged.connect(lambda v: (self.bg_dim_label.setText(f"{v}%"), self._refresh()))
        self._update_source_info()
        return w

    def _build_lyrics_tab(self) -> QWidget:
        d = self.design
        w = QWidget()
        lay = QVBoxLayout(w)
        g = QGroupBox("가사 글자")
        gl = QVBoxLayout(g)
        self.lyrics_style = StyleEditor(d.lyrics)
        gl.addWidget(self.lyrics_style)
        form = QFormLayout()
        self.lyrics_align = _combo(ALIGNS, d.lyrics_align)
        self.lyrics_anchor = _combo(ANCHORS, d.lyrics_anchor)
        self.margin = QSpinBox()
        self.margin.setRange(0, 30)
        self.margin.setSuffix(" %")
        self.margin.setValue(int(round(d.margin * 100)))
        self.line_spacing = QDoubleSpinBox()
        self.line_spacing.setRange(0.8, 3.0)
        self.line_spacing.setSingleStep(0.05)
        self.line_spacing.setValue(d.line_spacing)
        form.addRow("가로 정렬", self.lyrics_align)
        form.addRow("세로 위치", self.lyrics_anchor)
        form.addRow("여백", self.margin)
        form.addRow("줄 간격", self.line_spacing)
        gl.addLayout(form)
        lay.addWidget(g)

        g2 = QGroupBox("곡 제목 / 파트 이름 표시")
        g2l = QVBoxLayout(g2)
        self.show_song_title = QCheckBox("곡의 첫 슬라이드 위쪽에 곡 제목을 작게 표시")
        self.show_song_title.setChecked(d.show_song_title)
        self.show_label = QCheckBox("슬라이드 왼쪽 위에 파트 이름(Verse 1, Chorus...) 작게 표시")
        self.show_label.setChecked(d.show_label)
        g2l.addWidget(self.show_song_title)
        g2l.addWidget(self.show_label)
        self.label_style = StyleEditor(d.label_style, with_effects=False)
        g2l.addWidget(self.label_style)
        lay.addWidget(g2)
        lay.addStretch(1)

        self.lyrics_style.changed.connect(self._refresh)
        self.label_style.changed.connect(self._refresh)
        for c in (self.lyrics_align, self.lyrics_anchor):
            c.currentIndexChanged.connect(self._refresh)
        self.margin.valueChanged.connect(self._refresh)
        self.line_spacing.valueChanged.connect(self._refresh)
        self.show_song_title.toggled.connect(self._refresh)
        self.show_label.toggled.connect(self._refresh)
        return w

    def _build_text_tab(self) -> QWidget:
        d = self.design
        w = QWidget()
        lay = QVBoxLayout(w)
        self.title_style = StyleEditor(d.title_style)
        self.heading_style = StyleEditor(d.heading_style)
        self.body_style = StyleEditor(d.body_style)
        for title, editor in (("표지 / 곡 제목 / 설교 제목", self.title_style),
                              ("성경·설교·광고의 제목줄", self.heading_style),
                              ("성경·설교·광고의 본문", self.body_style)):
            g = QGroupBox(title)
            QVBoxLayout(g).addWidget(editor)
            lay.addWidget(g)
            editor.changed.connect(self._refresh)
        form = QFormLayout()
        self.content_align = _combo(ALIGNS, d.content_align)
        self.content_align.currentIndexChanged.connect(self._refresh)
        form.addRow("본문 정렬", self.content_align)
        lay.addLayout(form)
        lay.addStretch(1)
        return w

    def _build_layout_tab(self) -> QWidget:
        d = self.design
        w = QWidget()
        lay = QFormLayout(w)
        self.lines_per_slide = QSpinBox()
        self.lines_per_slide.setRange(1, 10)
        self.lines_per_slide.setSuffix(" 줄")
        self.lines_per_slide.setValue(d.lines_per_slide)
        lay.addRow("가사 한 장에 최대", self.lines_per_slide)
        lay.addRow(QLabel("   (가사 파트 안에 빈 줄을 넣으면 그 자리에서 무조건 넘어갑니다)"))
        self.verses_per_slide = QSpinBox()
        self.verses_per_slide.setRange(1, 10)
        self.verses_per_slide.setSuffix(" 절")
        self.verses_per_slide.setValue(d.verses_per_slide)
        lay.addRow("성경 한 장에 최대", self.verses_per_slide)
        self.section_mode = _combo([("part", "파트마다 (Verse / Chorus / Bridge 별로)"),
                                    ("song", "곡마다 (한 곡 = 한 구역)")], d.section_mode)
        lay.addRow("PPT 구역(섹션) 나누기", self.section_mode)
        self.song_title_slide = QCheckBox("곡마다 제목 슬라이드를 먼저 넣기")
        self.song_title_slide.setChecked(d.song_title_slide)
        self.blank_after_song = QCheckBox("곡이 끝나면 빈 슬라이드(배경만) 넣기")
        self.blank_after_song.setChecked(d.blank_after_song)
        self.auto_shrink = QCheckBox("글자가 넘치면 자동으로 크기 줄이기")
        self.auto_shrink.setChecked(d.auto_shrink)
        lay.addRow(self.song_title_slide)
        lay.addRow(self.blank_after_song)
        lay.addRow(self.auto_shrink)
        for wgt in (self.lines_per_slide, self.verses_per_slide):
            wgt.valueChanged.connect(self._refresh)
        self.section_mode.currentIndexChanged.connect(self._refresh)
        for c in (self.song_title_slide, self.blank_after_song, self.auto_shrink):
            c.toggled.connect(self._refresh)
        return w

    # ------------------------------------------------------------------
    def _collect(self) -> TemplateDesign:
        d = self.design
        d.name = self.name.text().strip()
        d.source_pptx = self.source_path.text().strip() if self.mode_source.isChecked() else ""
        d.source_lyrics_slide = self.src_lyrics.value()
        d.source_cover_slide = self.src_cover.value()
        d.source_content_slide = self.src_content.value()
        d.ratio = self.ratio.currentData()
        d.bg_color = self.bg_color.color()
        d.bg_image = self.bg_image.text().strip()
        d.bg_dim = self.bg_dim.value()
        d.lyrics = self.lyrics_style.style()
        d.lyrics_align = self.lyrics_align.currentData()
        d.lyrics_anchor = self.lyrics_anchor.currentData()
        d.margin = self.margin.value() / 100
        d.line_spacing = round(self.line_spacing.value(), 2)
        d.show_song_title = self.show_song_title.isChecked()
        d.show_label = self.show_label.isChecked()
        d.label_style = self.label_style.style()
        d.title_style = self.title_style.style()
        d.heading_style = self.heading_style.style()
        d.body_style = self.body_style.style()
        d.content_align = self.content_align.currentData()
        d.lines_per_slide = self.lines_per_slide.value()
        d.verses_per_slide = self.verses_per_slide.value()
        d.section_mode = self.section_mode.currentData()
        d.song_title_slide = self.song_title_slide.isChecked()
        d.blank_after_song = self.blank_after_song.isChecked()
        d.auto_shrink = self.auto_shrink.isChecked()
        return d

    def _refresh(self, *args) -> None:
        if not hasattr(self, "previews"):
            return
        d = self._collect()
        self.previews[0].spec.heading = "곡 제목" if d.show_song_title else ""
        for pv in self.previews:
            pv.set_design(d)

    def _update_mode(self, *args) -> None:
        src = self.mode_source.isChecked()
        self.source_box.setEnabled(src)
        self.bg_box.setEnabled(not src)
        self._refresh()

    def _update_source_info(self) -> None:
        path = self.source_path.text().strip()
        if not path:
            self.source_info.setText("소스 PPT 파일을 선택해 주세요.")
            return
        try:
            from pptx import Presentation
            from ..ppt_builder import _slide_text
            prs = Presentation(path)
            slides = list(prs.slides)
            found = []
            for key, label in (("lyrics", "{{가사}}"), ("title", "{{제목}}"), ("body", "{{본문}}")):
                nums = [str(i) for i, s in enumerate(slides, 1) if any(m in _slide_text(s) for m in MARKERS[key])]
                if nums:
                    found.append(f"{label}: {', '.join(nums)}번")
            text = f"슬라이드 {len(slides)}장"
            text += (" · " + " / ".join(found)) if found else " · 자리표시({{가사}} 등) 없음 → 1번 슬라이드 디자인 사용"
            self.source_info.setText(text)
            for s in (self.src_lyrics, self.src_cover, self.src_content):
                s.setMaximum(max(0, len(slides)))
        except Exception as e:
            self.source_info.setText(f"⚠ 파일을 열 수 없습니다: {e}")

    # ------------------------------------------------------------------
    def on_browse_source(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "소스 PPT 선택", str(Path.home()),
                                              "PowerPoint (*.pptx);;모든 파일 (*.*)")
        if path:
            self.source_path.setText(path)
            self.mode_source.setChecked(True)
            self._update_source_info()
            self._refresh()

    def on_make_sample(self) -> None:
        default = self.templates_dir / f"{safe_filename(self.name.text() or '견본')}_소스.pptx"
        path, _ = QFileDialog.getSaveFileName(self, "견본 소스 PPT 저장", str(default), "PowerPoint (*.pptx)")
        if not path:
            return
        d = self._collect()
        try:
            make_sample_template(d, path)
        except Exception as e:
            QMessageBox.warning(self, "오류", f"견본을 만들지 못했습니다: {e}")
            return
        self.source_path.setText(path)
        self.mode_source.setChecked(True)
        self._update_source_info()
        if ask_yes_no(self, "견본 완성",
                      "견본 소스 PPT를 만들고 이 템플릿의 소스로 지정했습니다.\n\n"
                      "PowerPoint에서 열어 배경·글꼴·위치를 꾸미고 저장하면\n그 디자인 그대로 PPT가 만들어집니다.\n\n"
                      "지금 PowerPoint로 열까요?"):
            open_path(path)

    def on_pick_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "배경 사진 선택", str(Path.home()),
                                              "이미지 (*.jpg *.jpeg *.png *.bmp *.gif)")
        if path:
            self.bg_image.setText(path)
            self._refresh()

    def on_save(self) -> None:
        d = self._collect()
        if not d.name:
            QMessageBox.information(self, "알림", "템플릿 이름을 입력해 주세요.")
            return
        if self.mode_source.isChecked() and not d.source_pptx:
            QMessageBox.information(self, "알림", "소스 PPT 파일을 선택하거나 '직접 디자인'을 골라 주세요.")
            return
        path = self.templates_dir / f"{safe_filename(d.name)}.json"
        if d.name != self.original_name and path.exists():
            if not ask_yes_no(self, "덮어쓰기", f"'{d.name}' 템플릿이 이미 있습니다. 덮어쓸까요?"):
                return
        d.save(path)
        self.saved_name = d.name
        self.accept()
