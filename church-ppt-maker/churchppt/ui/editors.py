"""예배 순서 항목별 편집 화면 (찬양 / 성경 / 설교 / 광고 / 표지)."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPlainTextEdit,
                               QPushButton, QVBoxLayout, QWidget)

from ..lyrics_format import (auto_structure, format_order, parse_song_text,
                             read_text_file, resolve_order, sections_to_body)
from ..models import Song
from ..service import (ITEM_COVER, ITEM_SCRIPTURE, ITEM_SERMON, ITEM_SONG,
                       ITEM_TEXT, ServiceItem, item_slides, item_to_song)
from ..settings import BIBLE_TRANSLATIONS
from .common import LyricsHighlighter, ask_yes_no, run_task

SONG_PLACEHOLDER = """여기에 가사를 쓰거나 붙여넣으세요.

[Verse 1]
첫 번째 줄
두 번째 줄

[Chorus]
후렴 가사...

· [대괄호] 로 파트를 나눕니다 (Verse 1, Chorus, Bridge, Pre-Chorus, Tag ... / 1절, 후렴, 브릿지도 가능)
· 파트 안의 빈 줄 = 그 자리에서 슬라이드 넘김
· 파트 구분 없이 쓰면 그냥 쭉 이어지는 가사로 만들어집니다"""


def _hint(text: str) -> QLabel:
    lb = QLabel(text)
    lb.setWordWrap(True)
    lb.setStyleSheet("color:#666; font-size:9pt;")
    return lb


def _big_button(text: str, primary: bool = False) -> QPushButton:
    b = QPushButton(text)
    b.setMinimumHeight(34)
    if primary:
        b.setProperty("primary", True)
    return b


class ItemEditor(QWidget):
    changed = Signal()
    kind = ""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._loading = False

    def _emit(self, *args) -> None:
        if not self._loading:
            self.changed.emit()

    def load(self, item: ServiceItem) -> None:
        raise NotImplementedError

    def save_into(self, item: ServiceItem) -> None:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# 찬양
# ---------------------------------------------------------------------------

class SongEditor(ItemEditor):
    kind = ITEM_SONG

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        self._key = ""
        lay = QVBoxLayout(self)

        title_row = QHBoxLayout()
        self.title = QLineEdit()
        self.title.setPlaceholderText("찬양 제목 (예: 주 은혜임을)")
        self.title.setFont(QFont(self.title.font().family(), 13))
        self.artist = QLineEdit()
        self.artist.setPlaceholderText("아티스트 (선택)")
        self.artist.setMaximumWidth(220)
        self.btn_search = _big_button("🔍  AI로 가사 찾기", primary=True)
        title_row.addWidget(self.title, 3)
        title_row.addWidget(self.artist, 1)
        title_row.addWidget(self.btn_search)
        lay.addLayout(title_row)

        grid = QGridLayout()
        self.btn_structure = _big_button("✂️  붙여넣은 가사 AI로 파트 나누기")
        self.btn_sheet = _big_button("🎼  악보 사진으로 만들기")
        self.btn_auto = _big_button("⚡  AI 없이 자동 나누기")
        self.btn_open = _big_button("📂  메모장(txt) 불러오기")
        self.btn_save = _big_button("💾  메모장(txt)으로 저장")
        self.btn_ppt = _big_button("📄  이 곡만 PPT 만들기")
        for i, b in enumerate((self.btn_structure, self.btn_sheet, self.btn_auto,
                               self.btn_open, self.btn_save, self.btn_ppt)):
            grid.addWidget(b, i // 3, i % 3)
        lay.addLayout(grid)

        order_row = QHBoxLayout()
        order_row.addWidget(QLabel("순서(송폼):"))
        self.order = QLineEdit()
        self.order.setPlaceholderText("예: V1 C V2 C B C C   (비워두면 아래에 적힌 순서대로 한 번씩)")
        order_row.addWidget(self.order, 1)
        lay.addLayout(order_row)

        self.body = QPlainTextEdit()
        self.body.setPlaceholderText(SONG_PLACEHOLDER)
        self.body.setFont(QFont(self.body.font().family(), 12))
        self.highlighter = LyricsHighlighter(self.body.document())
        lay.addWidget(self.body, 1)

        self.info = QLabel()
        self.info.setStyleSheet("color:#2C6E2F;")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)

        for w in (self.title, self.artist, self.order):
            w.textChanged.connect(self._emit)
        self.body.textChanged.connect(self._emit)
        self.changed.connect(self._update_info)

        self.btn_search.clicked.connect(self.on_search)
        self.btn_structure.clicked.connect(self.on_structure)
        self.btn_sheet.clicked.connect(self.on_sheet)
        self.btn_auto.clicked.connect(self.on_auto)
        self.btn_open.clicked.connect(self.on_open_txt)
        self.btn_save.clicked.connect(self.on_save_txt)
        self.btn_ppt.clicked.connect(self.on_single_ppt)

    # --- 데이터 --------------------------------------------------------
    def load(self, item: ServiceItem) -> None:
        self._loading = True
        d = item.data
        self.title.setText(d.get("title", ""))
        self.artist.setText(d.get("artist", ""))
        self.order.setText(d.get("order", ""))
        self.body.setPlainText(d.get("body", ""))
        self._key = d.get("key", "")
        self._loading = False
        self._update_info()

    def save_into(self, item: ServiceItem) -> None:
        item.data.update({
            "title": self.title.text().strip(),
            "artist": self.artist.text().strip(),
            "order": self.order.text().strip(),
            "body": self.body.toPlainText(),
            "key": self._key,
        })

    def current_song(self) -> Song:
        item = ServiceItem(ITEM_SONG, {})
        self.save_into(item)
        return item_to_song(item)

    def apply_song(self, song: Song, replace_title: bool = True) -> None:
        self._loading = True
        if replace_title or not self.title.text().strip():
            self.title.setText(song.title)
        if song.artist:
            self.artist.setText(song.artist)
        self.order.setText(format_order(song.order))
        self.body.setPlainText(sections_to_body(song.sections))
        self._key = song.key
        self._loading = False
        self.changed.emit()

    def _update_info(self) -> None:
        song = self.current_song()
        if not song.sections:
            self.info.setText("")
            return
        item = ServiceItem(ITEM_SONG, {})
        self.save_into(item)
        n_slides = len([s for s in item_slides(item, self.ctx.current_design()) if s.kind != "blank"])
        if song.is_structured:
            parts = ", ".join(s.label or "(구분없음)" for s in song.sections)
            text = f"파트 {len(song.sections)}개: {parts}  ·  슬라이드 {n_slides}장"
            _, missing = resolve_order(song)
            if missing:
                text += f"\n⚠ 순서에 있지만 가사에 없는 파트: {', '.join(missing)}"
        else:
            text = f"구분 없이 쭉 이어지는 가사  ·  슬라이드 {n_slides}장"
        self.info.setText(text)

    def _confirm_replace(self) -> bool:
        if not self.body.toPlainText().strip():
            return True
        return ask_yes_no(self, "가사 바꾸기", "지금 입력되어 있는 가사를 새 결과로 바꿀까요?")

    def _after_ai(self, song: Song, note: str = "") -> None:
        self.apply_song(song)
        saved = self.ctx.save_song_txt(self.current_song(), auto=True)
        msg = "가사를 불러왔습니다."
        if saved:
            msg += f"\n메모장 파일로 저장됨: {saved}"
        if note:
            msg += f"\n\nAI 메모: {note}"
        msg += "\n\n⚠ AI 결과는 틀릴 수 있으니 PPT를 만들기 전에 가사를 한 번 확인해 주세요."
        QMessageBox.information(self, "완료", msg)

    # --- 버튼 ---------------------------------------------------------
    def on_search(self) -> None:
        title = self.title.text().strip()
        if not title:
            QMessageBox.information(self, "알림", "먼저 찬양 제목을 입력해 주세요.")
            self.title.setFocus()
            return
        if not self._confirm_replace():
            return
        client = self.ctx.ai_client()
        if client is None:
            return
        artist = self.artist.text().strip()

        def failed(msg: str) -> None:
            QMessageBox.warning(
                self, "가사를 찾지 못했어요",
                f"{msg}\n\n다른 방법:\n· 가사를 아래 칸에 붙여넣고 [AI로 파트 나누기]\n· [악보 사진으로 만들기]")

        run_task(self, f"'{title}' 가사를 인터넷에서 찾는 중입니다...\n(보통 20초 ~ 1분 걸립니다)",
                 lambda: client.search_lyrics(title, artist), lambda song: self._after_ai(song), failed)

    def on_structure(self) -> None:
        raw = self.body.toPlainText().strip()
        if not raw:
            QMessageBox.information(self, "알림", "아래 가사 칸에 가사를 먼저 붙여넣어 주세요.")
            return
        client = self.ctx.ai_client()
        if client is None:
            return
        title = self.title.text().strip()
        run_task(self, "AI가 가사를 Verse / Chorus / Bridge 로 나누는 중입니다...",
                 lambda: client.structure_lyrics(raw, title), lambda song: self._after_ai(song))

    def on_sheet(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "악보 사진 선택 (여러 장 선택 가능)", str(Path.home()),
            "악보 이미지/PDF (*.jpg *.jpeg *.png *.webp *.gif *.bmp *.pdf);;모든 파일 (*.*)")
        if not files:
            return
        if not self._confirm_replace():
            return
        client = self.ctx.ai_client()
        if client is None:
            return
        title = self.title.text().strip()
        run_task(self, f"악보 {len(files)}장을 분석하는 중입니다...\n(1분 정도 걸릴 수 있습니다)",
                 lambda: client.read_sheet_music(files, title), lambda song: self._after_ai(song))

    def on_auto(self) -> None:
        raw = self.body.toPlainText()
        if not raw.strip():
            QMessageBox.information(self, "알림", "아래 가사 칸에 가사를 먼저 붙여넣어 주세요.")
            return
        sections, order = auto_structure(raw)
        song = self.current_song()
        song.sections = sections
        song.order = order or song.order
        self.apply_song(song, replace_title=False)
        if any(s.label for s in sections):
            self.ctx.status("반복되는 부분을 후렴(Chorus)으로 나눴습니다. 필요하면 직접 고쳐 주세요.")
        else:
            self.ctx.status("반복되는 부분이 없어 쭉 이어지는 가사로 두었습니다. (빈 줄마다 슬라이드 넘김)")

    def on_open_txt(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "가사 메모장 파일 열기", str(self.ctx.settings.lyrics_dir),
                                              "텍스트 파일 (*.txt);;모든 파일 (*.*)")
        if not path:
            return
        if not self._confirm_replace():
            return
        song = parse_song_text(read_text_file(path))
        if not song.title:
            song.title = Path(path).stem
        self.apply_song(song)

    def on_save_txt(self) -> None:
        song = self.current_song()
        if not song.title:
            QMessageBox.information(self, "알림", "찬양 제목을 먼저 입력해 주세요.")
            return
        path = self.ctx.save_song_txt(song, auto=False)
        if path:
            self.ctx.status(f"저장했습니다: {path}")

    def on_single_ppt(self) -> None:
        item = ServiceItem(ITEM_SONG, {})
        self.save_into(item)
        if not item_to_song(item).sections:
            QMessageBox.information(self, "알림", "가사가 비어 있습니다.")
            return
        self.ctx.build_items_ppt([item], item.data.get("title") or "찬양")


# ---------------------------------------------------------------------------
# 성경 본문
# ---------------------------------------------------------------------------

class ScriptureEditor(ItemEditor):
    kind = ITEM_SCRIPTURE

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.reference = QLineEdit()
        self.reference.setPlaceholderText("예: 요한복음 3:16-18")
        self.translation = QComboBox()
        self.translation.setEditable(True)
        self.translation.addItems(BIBLE_TRANSLATIONS)
        form.addRow("본문 구절", self.reference)
        form.addRow("번역본", self.translation)
        lay.addLayout(form)

        self.btn_fetch = _big_button("📖  AI로 본문 가져오기", primary=True)
        lay.addWidget(self.btn_fetch)
        self.text = QPlainTextEdit()
        self.text.setFont(QFont(self.text.font().family(), 12))
        self.text.setPlaceholderText("16 하나님이 세상을 이처럼 사랑하사 ...\n17 하나님이 그 아들을 ...\n\n"
                                     "· 한 줄에 한 절씩 (앞에 절 번호)\n· 빈 줄 = 그 자리에서 슬라이드 넘김\n"
                                     "· 한 장에 몇 절씩 넣을지는 [템플릿 편집 > 슬라이드 구성] 에서")
        lay.addWidget(self.text, 1)
        lay.addWidget(_hint("※ AI가 가져온 본문은 틀릴 수 있으니 꼭 성경과 대조해 확인해 주세요."))

        self.reference.textChanged.connect(self._emit)
        self.translation.currentTextChanged.connect(self._emit)
        self.text.textChanged.connect(self._emit)
        self.btn_fetch.clicked.connect(self.on_fetch)

    def load(self, item: ServiceItem) -> None:
        self._loading = True
        d = item.data
        self.reference.setText(d.get("reference", ""))
        self.translation.setCurrentText(d.get("translation", "") or self.ctx.settings.bible_translation)
        self.text.setPlainText(d.get("text", ""))
        self._loading = False

    def save_into(self, item: ServiceItem) -> None:
        item.data.update({"reference": self.reference.text().strip(),
                          "translation": self.translation.currentText().strip(),
                          "text": self.text.toPlainText()})

    def on_fetch(self) -> None:
        ref = self.reference.text().strip()
        if not ref:
            QMessageBox.information(self, "알림", "본문 구절을 입력해 주세요. (예: 요한복음 3:16-18)")
            return
        if self.text.toPlainText().strip() and not ask_yes_no(self, "본문 바꾸기", "지금 입력된 본문을 바꿀까요?"):
            return
        client = self.ctx.ai_client()
        if client is None:
            return
        tr = self.translation.currentText().strip()
        self.ctx.settings.bible_translation = tr
        run_task(self, f"{ref} ({tr}) 본문을 찾는 중입니다...",
                 lambda: client.fetch_scripture(ref, tr), self.text.setPlainText)


# ---------------------------------------------------------------------------
# 설교
# ---------------------------------------------------------------------------

class _ManuscriptDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("설교 원고 붙여넣기")
        self.resize(640, 560)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("설교 원고나 메모를 붙여넣으면 AI가 요점 슬라이드로 정리합니다."))
        self.text = QPlainTextEdit()
        lay.addWidget(self.text, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("AI로 정리하기")
        bb.button(QDialogButtonBox.Cancel).setText("취소")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


class SermonEditor(ItemEditor):
    kind = ITEM_SERMON

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.title = QLineEdit()
        self.title.setPlaceholderText("설교 제목")
        self.preacher = QLineEdit()
        self.preacher.setPlaceholderText("예: 김OO 목사")
        self.reference = QLineEdit()
        self.reference.setPlaceholderText("예: 요한복음 3:16")
        form.addRow("설교 제목", self.title)
        form.addRow("설교자", self.preacher)
        form.addRow("본문", self.reference)
        lay.addLayout(form)
        self.btn_ai = _big_button("🧠  설교 원고를 AI로 요약해서 슬라이드 만들기", primary=True)
        lay.addWidget(self.btn_ai)
        self.body = QPlainTextEdit()
        self.body.setFont(QFont(self.body.font().family(), 12))
        self.body.setPlaceholderText("1. 하나님은 사랑이시다\n우리를 먼저 사랑하셨습니다\n\n2. 사랑은 행동입니다\n...\n\n"
                                     "· 빈 줄로 슬라이드를 나눕니다\n· 첫 장은 설교 제목/본문/설교자 표지로 자동 생성됩니다")
        lay.addWidget(self.body, 1)

        for w in (self.title, self.preacher, self.reference):
            w.textChanged.connect(self._emit)
        self.body.textChanged.connect(self._emit)
        self.btn_ai.clicked.connect(self.on_ai)

    def load(self, item: ServiceItem) -> None:
        self._loading = True
        d = item.data
        self.title.setText(d.get("title", ""))
        self.preacher.setText(d.get("preacher", ""))
        self.reference.setText(d.get("reference", ""))
        self.body.setPlainText(d.get("body", ""))
        self._loading = False

    def save_into(self, item: ServiceItem) -> None:
        item.data.update({"title": self.title.text().strip(), "preacher": self.preacher.text().strip(),
                          "reference": self.reference.text().strip(), "body": self.body.toPlainText()})

    def on_ai(self) -> None:
        dlg = _ManuscriptDialog(self)
        if dlg.exec() != QDialog.Accepted or not dlg.text.toPlainText().strip():
            return
        if self.body.toPlainText().strip() and not ask_yes_no(self, "내용 바꾸기", "지금 입력된 슬라이드 내용을 바꿀까요?"):
            return
        client = self.ctx.ai_client()
        if client is None:
            return
        notes = dlg.text.toPlainText()
        title, ref = self.title.text().strip(), self.reference.text().strip()
        run_task(self, "설교 내용을 슬라이드로 정리하는 중입니다...",
                 lambda: client.summarize_sermon(notes, title, ref), self.body.setPlainText)


# ---------------------------------------------------------------------------
# 광고 / 자유 텍스트
# ---------------------------------------------------------------------------

class TextEditor(ItemEditor):
    kind = ITEM_TEXT

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.title = QLineEdit()
        self.title.setPlaceholderText("예: 교회 소식, 사도신경, 주기도문, 헌금 기도")
        form.addRow("제목", self.title)
        lay.addLayout(form)
        self.body = QPlainTextEdit()
        self.body.setFont(QFont(self.body.font().family(), 12))
        self.body.setPlaceholderText("내용을 입력하세요.\n\n빈 줄로 슬라이드를 나눕니다.")
        lay.addWidget(self.body, 1)
        self.title.textChanged.connect(self._emit)
        self.body.textChanged.connect(self._emit)

    def load(self, item: ServiceItem) -> None:
        self._loading = True
        self.title.setText(item.data.get("title", ""))
        self.body.setPlainText(item.data.get("body", ""))
        self._loading = False

    def save_into(self, item: ServiceItem) -> None:
        item.data.update({"title": self.title.text().strip(), "body": self.body.toPlainText()})


# ---------------------------------------------------------------------------
# 표지
# ---------------------------------------------------------------------------

def next_sunday(today: dt.date | None = None) -> dt.date:
    today = today or dt.date.today()
    return today + dt.timedelta(days=(6 - today.weekday()) % 7)


def korean_date(d: dt.date) -> str:
    return f"{d.year}년 {d.month}월 {d.day}일"


class CoverEditor(ItemEditor):
    kind = ITEM_COVER

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.title = QLineEdit()
        self.title.setPlaceholderText("예: 주일 2부 예배")
        self.subtitle = QLineEdit()
        self.subtitle.setPlaceholderText("예: OO교회 / 오늘의 말씀 제목")
        date_row = QHBoxLayout()
        self.date = QLineEdit()
        btn_sunday = QPushButton("이번 주일")
        btn_today = QPushButton("오늘")
        date_row.addWidget(self.date, 1)
        date_row.addWidget(btn_sunday)
        date_row.addWidget(btn_today)
        form.addRow("제목", self.title)
        form.addRow("부제", self.subtitle)
        form.addRow("날짜", date_row)
        lay.addLayout(form)
        lay.addStretch(1)
        for w in (self.title, self.subtitle, self.date):
            w.textChanged.connect(self._emit)
        btn_sunday.clicked.connect(lambda: self.date.setText(korean_date(next_sunday())))
        btn_today.clicked.connect(lambda: self.date.setText(korean_date(dt.date.today())))

    def load(self, item: ServiceItem) -> None:
        self._loading = True
        self.title.setText(item.data.get("title", ""))
        self.subtitle.setText(item.data.get("subtitle", ""))
        self.date.setText(item.data.get("date", ""))
        self._loading = False

    def save_into(self, item: ServiceItem) -> None:
        item.data.update({"title": self.title.text().strip(), "subtitle": self.subtitle.text().strip(),
                          "date": self.date.text().strip()})


EDITOR_CLASSES = [SongEditor, ScriptureEditor, SermonEditor, TextEditor, CoverEditor]
