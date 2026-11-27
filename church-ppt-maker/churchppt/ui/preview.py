"""슬라이드 미리보기 (QPainter 로 대략적인 모습을 그린다)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QListView, QListWidget, QListWidgetItem

from ..design import TemplateDesign, TextStyle
from ..models import KIND_BLANK, KIND_CONTENT, KIND_COVER, KIND_LYRICS, SlideSpec

_PIXMAP_CACHE: dict[str, QPixmap] = {}

_H_ALIGN = {"left": Qt.AlignLeft, "center": Qt.AlignHCenter, "right": Qt.AlignRight}


def slide_size_pt(design: TemplateDesign) -> tuple[float, float]:
    return (720.0, 540.0) if design.ratio == "4:3" and not design.uses_source else (960.0, 540.0)


def _pixmap(path: str) -> QPixmap | None:
    if not path or not Path(path).is_file():
        return None
    if path not in _PIXMAP_CACHE:
        pm = QPixmap(path)
        if pm.isNull():
            return None
        if pm.width() > 1600:
            pm = pm.scaledToWidth(1600, Qt.SmoothTransformation)
        _PIXMAP_CACHE[path] = pm
    return _PIXMAP_CACHE[path]


def _font(style: TextStyle, px: float) -> QFont:
    f = QFont(style.font)
    f.setPixelSize(max(1, int(round(px))))
    f.setBold(style.bold)
    return f


def _draw_styled(p: QPainter, rect: QRectF, flags, text: str, style: TextStyle, font: QFont, scale: float) -> None:
    p.setFont(font)
    if style.shadow:
        off = max(1.0, 2.0 * scale)
        p.setPen(QColor(0, 0, 0, 170))
        p.drawText(rect.translated(off, off), flags, text)
    if style.outline:
        w = max(1.0, style.outline_width * scale)
        p.setPen(QColor(style.outline_color))
        for dx, dy in ((-w, 0), (w, 0), (0, -w), (0, w), (-w, -w), (w, w), (-w, w), (w, -w)):
            p.drawText(rect.translated(dx, dy), flags, text)
    p.setPen(QColor(style.color))
    p.drawText(rect, flags, text)


def _draw_paras(p: QPainter, box: QRectF, paras, align: str, anchor: str, spacing: float,
                scale: float, shrink: bool) -> None:
    flags = _H_ALIGN.get(align, Qt.AlignHCenter) | Qt.AlignVCenter | Qt.TextWordWrap

    def layout(factor: float):
        items, total = [], 0.0
        for text, style, size in paras:
            font = _font(style, size * scale * factor)
            fm = QFontMetricsF(font)
            br = fm.boundingRect(QRectF(0, 0, box.width(), 1e6), int(flags), text or " ")
            n = max(1, round(br.height() / fm.lineSpacing()))
            h = n * fm.lineSpacing() * spacing
            items.append((text, style, font, h))
            total += h
        return items, total

    factor = 1.0
    items, total = layout(factor)
    while shrink and total > box.height() and factor > 0.5:
        factor -= 0.05
        items, total = layout(factor)
    if anchor == "top":
        y = box.top()
    elif anchor == "bottom":
        y = box.bottom() - total
    else:
        y = box.top() + (box.height() - total) / 2
    for text, style, font, h in items:
        _draw_styled(p, QRectF(box.left(), y, box.width(), h), flags, text, style, font, scale)
        y += h


def paint_slide(p: QPainter, rect: QRectF, spec: SlideSpec | None, design: TemplateDesign) -> None:
    d = design
    W, H = slide_size_pt(d)
    scale = rect.width() / W
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    p.setClipRect(rect)

    # --- 배경 ---
    if d.uses_source:
        p.fillRect(rect, QColor("#3A3D45"))
    else:
        p.fillRect(rect, QColor(d.bg_color))
        pm = _pixmap(d.bg_image)
        if pm:
            target_ratio = rect.width() / rect.height()
            src_ratio = pm.width() / pm.height()
            if src_ratio > target_ratio:
                sw = pm.height() * target_ratio
                src = QRectF((pm.width() - sw) / 2, 0, sw, pm.height())
            else:
                sh = pm.width() / target_ratio
                src = QRectF(0, (pm.height() - sh) / 2, pm.width(), sh)
            p.drawPixmap(rect, pm, src)
            if d.bg_dim:
                p.fillRect(rect, QColor(0, 0, 0, int(255 * min(90, d.bg_dim) / 100)))

    def R(x, y, w, h) -> QRectF:
        return QRectF(rect.left() + x * scale, rect.top() + y * scale, w * scale, h * scale)

    mx, my = W * d.margin, W * d.margin * 0.75
    X, Y, BW, BH = mx, my, W - 2 * mx, H - 2 * my

    if spec is not None and spec.kind != KIND_BLANK:
        if spec.kind == KIND_LYRICS:
            top = Y
            if spec.heading:
                hs = d.label_style
                _draw_paras(p, R(X, Y, BW, H * 0.1), [(spec.heading, hs, hs.size + 6)], "center", "top", 1.0, scale, True)
                top = Y + H * 0.1
            if d.show_label and spec.label:
                ls = d.label_style
                _draw_paras(p, R(mx * 0.4, my * 0.4, W * 0.3, H * 0.08), [(spec.label, ls, ls.size)],
                            "left", "top", 1.0, scale, False)
            paras = [(ln, d.lyrics, d.lyrics.size) for ln in spec.lines]
            _draw_paras(p, R(X, top, BW, Y + BH - top), paras, d.lyrics_align, d.lyrics_anchor,
                        d.line_spacing, scale, d.auto_shrink)
        elif spec.kind == KIND_COVER:
            paras = [(spec.heading, d.title_style, d.title_style.size)]
            paras += [(ln, d.body_style, d.body_style.size * 0.8) for ln in spec.subtitle.splitlines() if ln.strip()]
            _draw_paras(p, R(X, Y, BW, BH), paras, "center", "middle", 1.15, scale, d.auto_shrink)
        elif spec.kind == KIND_CONTENT:
            body_top = Y
            if spec.heading:
                hs = d.heading_style
                _draw_paras(p, R(X, Y, BW, BH * 0.17), [(spec.heading, hs, hs.size)], d.content_align, "middle",
                            1.0, scale, d.auto_shrink)
                body_top = Y + BH * 0.21
            paras = [(ln, d.body_style, d.body_style.size) for ln in spec.lines]
            _draw_paras(p, R(X, body_top, BW, Y + BH - body_top), paras, d.content_align,
                        "top" if spec.heading else "middle", d.line_spacing, scale, d.auto_shrink)

    if d.uses_source:
        badge = QFont()
        badge.setPixelSize(max(8, int(11 * rect.width() / 240)))
        p.setFont(badge)
        p.setPen(QColor(255, 255, 255, 150))
        p.drawText(rect.adjusted(4, 2, -4, -2), Qt.AlignRight | Qt.AlignTop, "소스 PPT 디자인")
    p.restore()


def render_thumbnail(spec: SlideSpec | None, design: TemplateDesign, width: int) -> QPixmap:
    W, H = slide_size_pt(design)
    height = int(width * H / W)
    pm = QPixmap(width, height)
    pm.fill(Qt.black)
    p = QPainter(pm)
    paint_slide(p, QRectF(0, 0, width, height), spec, design)
    p.end()
    return pm


_KIND_NAMES = {KIND_LYRICS: "가사", KIND_COVER: "제목", KIND_CONTENT: "내용", KIND_BLANK: "빈 화면"}


class SlidePreviewList(QListWidget):
    """슬라이드 썸네일 목록."""

    THUMB_W = 208
    MAX_SLIDES = 150

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListView.IconMode)
        self.setFlow(QListView.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setSpacing(6)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QListWidget.NoSelection)
        self.setIconSize(QSize(self.THUMB_W, int(self.THUMB_W * 9 / 16)))
        self.setStyleSheet("QListWidget { background:#2B2D31; color:#DDD; border:none; }")

    def show_slides(self, slides: list[SlideSpec], design: TemplateDesign) -> None:
        self.clear()
        W, H = slide_size_pt(design)
        self.setIconSize(QSize(self.THUMB_W, int(self.THUMB_W * H / W)))
        for i, spec in enumerate(slides[: self.MAX_SLIDES], start=1):
            pm = render_thumbnail(spec, design, self.THUMB_W)
            caption = f"{i}. {spec.label or _KIND_NAMES.get(spec.kind, '')}"
            item = QListWidgetItem(QIcon(pm), caption)
            item.setToolTip(f"구역: {spec.section_name}")
            item.setTextAlignment(Qt.AlignHCenter)
            self.addItem(item)
        if len(slides) > self.MAX_SLIDES:
            self.addItem(QListWidgetItem(f"... 외 {len(slides) - self.MAX_SLIDES}장"))
