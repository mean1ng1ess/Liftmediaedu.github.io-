"""메인 창: 예배 순서 / 편집 / 미리보기 / 가사 보관함."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox,
                               QFileDialog, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem,
                               QMainWindow, QMenu, QMessageBox, QPushButton,
                               QSizePolicy, QSplitter, QStackedWidget,
                               QToolButton,
                               QVBoxLayout, QWidget)

from .. import APP_NAME, __version__
from ..ai import AIClient, AIError
from ..design import TemplateDesign, builtin_designs
from ..lyrics_format import (parse_song_text, read_text_file, safe_filename,
                             song_to_text, write_text_file)
from ..models import Song
from ..ppt_builder import BuildError, build_presentation
from ..service import (ITEM_COVER, ITEM_SCRIPTURE, ITEM_SERMON, ITEM_SONG,
                       ITEM_TEXT, Service, ServiceItem, item_slides,
                       item_to_song, service_to_slides, song_to_data)
from ..settings import AppSettings, config_dir
from .common import ask_yes_no, open_path
from .editors import EDITOR_CLASSES, korean_date, next_sunday
from .preview import SlidePreviewList
from .settings_dialog import SettingsDialog
from .template_editor import TemplateEditorDialog

WELCOME = """<h2>교회 PPT 메이커</h2>
<p style="font-size:11pt; line-height:150%">
<b>1.</b> 왼쪽 아래 <b>[+ 찬양]</b> 을 누르고 제목을 입력한 뒤 <b>[AI로 가사 찾기]</b><br>
&nbsp;&nbsp;&nbsp;&nbsp;· 가사를 붙여넣고 <b>[AI로 파트 나누기]</b> 를 하거나, <b>[악보 사진으로 만들기]</b> 도 됩니다<br>
&nbsp;&nbsp;&nbsp;&nbsp;· 가사는 자동으로 메모장(txt) 파일로 저장되고, 오른쪽 <b>가사 보관함</b>에서 다시 쓸 수 있습니다<br>
<b>2.</b> <b>[+ 성경]</b>, <b>[+ 설교]</b>, <b>[+ 광고]</b>, <b>[+ 표지]</b> 로 예배 순서를 채우세요 (끌어서 순서 변경)<br>
<b>3.</b> 위쪽에서 <b>템플릿</b>(디자인)을 고르거나 <b>[템플릿 편집]</b> 으로 꾸미세요<br>
&nbsp;&nbsp;&nbsp;&nbsp;· 가지고 있는 PPT 파일의 디자인을 그대로 쓸 수도 있습니다<br>
<b>4.</b> <b>[PPT 만들기]</b> — Verse / Chorus / Bridge 가 PowerPoint <b>구역(섹션)</b>으로 나뉘어 만들어집니다
</p>"""

APP_STYLE = """
QPushButton[primary="true"] { background:#2F6FEB; color:white; font-weight:bold;
    border:none; border-radius:6px; padding:6px 14px; }
QPushButton[primary="true"]:hover { background:#2459C2; }
QPushButton[primary="true"]:disabled { background:#9DB5E8; }
QPushButton#makePpt { background:#1F9D55; color:white; font-weight:bold; font-size:12pt;
    border:none; border-radius:6px; padding:8px 22px; }
QPushButton#makePpt:hover { background:#17804A; }
QListWidget#orderList::item { padding:7px 4px; }
QListWidget#orderList::item:selected { background:#DCE8FF; color:#000; }
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = AppSettings.load()
        try:
            self.settings.ensure_dirs()
        except OSError:
            self.settings.data_dir = ""
            self.settings.ensure_dirs()
        self._ensure_templates()
        self.service = Service(name=f"{korean_date(next_sunday())} 주일예배")
        self.service_path: Path | None = None
        self.current_item: ServiceItem | None = None
        self._designs: dict[str, tuple[Path, TemplateDesign]] = {}

        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(1440, 900)
        self.setStyleSheet(APP_STYLE)
        self._build_toolbar()
        self._build_body()
        self.statusBar().showMessage("준비되었습니다.")

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(250)
        self._preview_timer.timeout.connect(self.refresh_preview)

        self.reload_templates()
        self.refresh_library()
        self._restore_last_session()

    # ==================================================================
    # 화면 구성
    # ==================================================================
    def _build_toolbar(self) -> None:
        tb = self.addToolBar("도구")
        tb.setMovable(False)
        tb.setIconSize(QSize(18, 18))
        tb.setToolButtonStyle(Qt.ToolButtonTextOnly)

        for text, slot in (("📄 새 예배", self.new_service), ("📂 예배 열기", self.open_service),
                           ("💾 예배 저장", self.save_service)):
            act = QAction(text, self)
            act.triggered.connect(slot)
            tb.addAction(act)
        tb.addSeparator()

        tb.addWidget(QLabel("  템플릿: "))
        self.template_combo = QComboBox()
        self.template_combo.setMinimumWidth(220)
        self.template_combo.currentTextChanged.connect(self.on_template_changed)
        tb.addWidget(self.template_combo)

        tmpl_btn = QToolButton()
        tmpl_btn.setText("🎨 템플릿 편집")
        tmpl_btn.setPopupMode(QToolButton.MenuButtonPopup)
        tmpl_btn.clicked.connect(self.edit_template)
        menu = QMenu(tmpl_btn)
        menu.addAction("현재 템플릿 편집", self.edit_template)
        menu.addAction("새 템플릿 만들기", self.new_template)
        menu.addAction("현재 템플릿 삭제", self.delete_template)
        menu.addSeparator()
        menu.addAction("템플릿 폴더 열기", lambda: open_path(self.settings.templates_dir))
        tmpl_btn.setMenu(menu)
        tb.addWidget(tmpl_btn)
        tb.addSeparator()

        act = QAction("⚙ 설정", self)
        act.triggered.connect(self.open_settings)
        tb.addAction(act)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)
        self.btn_make = QPushButton("▶  PPT 만들기")
        self.btn_make.setObjectName("makePpt")
        self.btn_make.clicked.connect(self.make_ppt)
        tb.addWidget(self.btn_make)

    def _build_body(self) -> None:
        splitter = QSplitter(Qt.Horizontal)
        self.setCentralWidget(splitter)

        # --- 왼쪽: 예배 순서 ---
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(QLabel("<b>예배 이름</b>"))
        self.service_name = QLineEdit(self.service.name)
        self.service_name.textChanged.connect(self._on_service_name)
        ll.addWidget(self.service_name)
        ll.addWidget(QLabel("<b>예배 순서</b> (끌어서 순서 바꾸기)"))
        self.order_list = QListWidget()
        self.order_list.setObjectName("orderList")
        self.order_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.order_list.setDefaultDropAction(Qt.MoveAction)
        self.order_list.currentRowChanged.connect(self.on_select_item)
        self.order_list.model().rowsMoved.connect(self._sync_order_from_list)
        ll.addWidget(self.order_list, 1)

        add_grid = QGridLayout()
        for i, (text, kind) in enumerate((("+ 찬양", ITEM_SONG), ("+ 성경", ITEM_SCRIPTURE),
                                          ("+ 설교", ITEM_SERMON), ("+ 광고/텍스트", ITEM_TEXT),
                                          ("+ 표지", ITEM_COVER))):
            b = QPushButton(text)
            b.setMinimumHeight(32)
            if kind == ITEM_SONG:
                b.setProperty("primary", True)
            b.clicked.connect(lambda _=False, k=kind: self.add_item(k))
            add_grid.addWidget(b, i // 2, i % 2)
        ll.addLayout(add_grid)
        move_row = QHBoxLayout()
        for text, slot in (("▲", lambda: self.move_item(-1)), ("▼", lambda: self.move_item(1)),
                           ("복제", self.duplicate_item), ("삭제", self.delete_item)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            move_row.addWidget(b)
        ll.addLayout(move_row)
        QShortcut(QKeySequence.Delete, self.order_list, self.delete_item, context=Qt.WidgetShortcut)
        splitter.addWidget(left)

        # --- 가운데: 편집 + 미리보기 ---
        center = QSplitter(Qt.Vertical)
        self.editor_stack = QStackedWidget()
        welcome = QLabel(WELCOME)
        welcome.setWordWrap(True)
        welcome.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        welcome.setContentsMargins(24, 16, 24, 16)
        self.editor_stack.addWidget(welcome)
        self.editors = {}
        for cls in EDITOR_CLASSES:
            ed = cls(self)
            ed.changed.connect(self.on_editor_changed)
            self.editors[cls.kind] = ed
            self.editor_stack.addWidget(ed)
        center.addWidget(self.editor_stack)

        prev = QWidget()
        pl = QVBoxLayout(prev)
        pl.setContentsMargins(0, 0, 0, 0)
        ph = QHBoxLayout()
        self.preview_title = QLabel("<b>미리보기</b>")
        self.preview_all = QCheckBox("예배 전체 보기")
        self.preview_all.toggled.connect(self.refresh_preview)
        ph.addWidget(self.preview_title)
        ph.addStretch(1)
        ph.addWidget(self.preview_all)
        pl.addLayout(ph)
        self.preview = SlidePreviewList()
        pl.addWidget(self.preview, 1)
        center.addWidget(prev)
        center.setStretchFactor(0, 3)
        center.setStretchFactor(1, 2)
        splitter.addWidget(center)

        # --- 오른쪽: 가사 보관함 ---
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.addWidget(QLabel("<b>가사 보관함</b> (메모장 파일)"))
        self.lib_search = QLineEdit()
        self.lib_search.setPlaceholderText("🔎 제목 검색")
        self.lib_search.textChanged.connect(self.refresh_library)
        rl.addWidget(self.lib_search)
        self.library = QListWidget()
        self.library.itemDoubleClicked.connect(lambda _: self.add_from_library())
        rl.addWidget(self.library, 1)
        b_add = QPushButton("➕ 예배에 추가")
        b_add.setProperty("primary", True)
        b_add.clicked.connect(self.add_from_library)
        rl.addWidget(b_add)
        lib_row = QHBoxLayout()
        b_folder = QPushButton("폴더 열기")
        b_folder.clicked.connect(lambda: open_path(self.settings.lyrics_dir))
        b_edit = QPushButton("메모장으로 열기")
        b_edit.clicked.connect(self.open_library_file)
        b_refresh = QPushButton("새로고침")
        b_refresh.clicked.connect(self.refresh_library)
        lib_row.addWidget(b_folder)
        lib_row.addWidget(b_edit)
        lib_row.addWidget(b_refresh)
        rl.addLayout(lib_row)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 6)
        splitter.setStretchFactor(2, 2)
        splitter.setSizes([300, 860, 280])

    # ==================================================================
    # editors 가 쓰는 기능
    # ==================================================================
    def status(self, msg: str) -> None:
        self.statusBar().showMessage(msg, 8000)

    def ai_client(self) -> AIClient | None:
        key = self.settings.effective_api_key()
        if not key:
            if ask_yes_no(self, "API 키 필요",
                          "AI 기능을 쓰려면 Claude API 키가 필요합니다.\n지금 설정 창을 열까요?"):
                self.open_settings()
                key = self.settings.effective_api_key()
            if not key:
                return None
        try:
            return AIClient(key, self.settings.model)
        except AIError as e:
            QMessageBox.warning(self, "알림", str(e))
            return None

    def current_design(self) -> TemplateDesign:
        name = self.template_combo.currentText() if hasattr(self, "template_combo") else ""
        if name in self._designs:
            return self._designs[name][1]
        return TemplateDesign()

    def save_song_txt(self, song: Song, auto: bool = False) -> Path | None:
        if not song.title:
            return None
        path = self.settings.lyrics_dir / f"{safe_filename(song.title)}.txt"
        text = song_to_text(song)
        if path.exists():
            try:
                same = read_text_file(path).replace("\r\n", "\n").strip() == text.strip()
            except OSError:
                same = False
            if same:
                return path
            q = ("가사 보관함에 같은 제목의 파일이 이미 있습니다.\n새 가사로 덮어쓸까요?" if auto
                 else f"'{path.name}' 파일이 이미 있습니다. 덮어쓸까요?")
            if not ask_yes_no(self, "메모장 파일 저장", q):
                return None
        try:
            write_text_file(path, text)
        except OSError as e:
            QMessageBox.warning(self, "저장 실패", f"파일을 저장하지 못했습니다:\n{e}")
            return None
        self.refresh_library()
        return path

    def build_items_ppt(self, items: list[ServiceItem], default_name: str) -> None:
        self._commit_editor()
        design = self.current_design()
        if design.uses_source and not Path(design.source_pptx).is_file():
            QMessageBox.warning(self, "템플릿 오류",
                                f"템플릿의 소스 PPT 파일을 찾을 수 없습니다:\n{design.source_pptx}\n\n"
                                "[템플릿 편집] 에서 다시 지정해 주세요.")
            return
        slides = service_to_slides(items, design)
        if not slides:
            QMessageBox.information(self, "알림", "만들 슬라이드가 없습니다.")
            return
        stamp = dt.date.today().strftime("%Y-%m-%d")
        default = self.settings.output_dir / f"{stamp}_{safe_filename(default_name)}.pptx"
        path, _ = QFileDialog.getSaveFileName(self, "PPT 저장", str(default), "PowerPoint (*.pptx)")
        if not path:
            return
        if not path.lower().endswith(".pptx"):
            path += ".pptx"
        QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            out = build_presentation(slides, design, path)
        except BuildError as e:
            QGuiApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "PPT 만들기 실패", str(e))
            return
        except Exception as e:
            QGuiApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "PPT 만들기 실패", f"예상하지 못한 오류가 발생했습니다:\n{e}")
            return
        QGuiApplication.restoreOverrideCursor()
        n_sections = len({s.section_id for s in slides})
        box = QMessageBox(self)
        box.setWindowTitle("완성!")
        box.setIcon(QMessageBox.Information)
        box.setText(f"PPT를 만들었습니다.\n\n슬라이드 {len(slides)}장 · 구역(섹션) {n_sections}개\n{out}")
        b_open = box.addButton("PPT 열기", QMessageBox.AcceptRole)
        b_folder = box.addButton("폴더 열기", QMessageBox.ActionRole)
        box.addButton("닫기", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is b_open:
            open_path(out)
        elif box.clickedButton() is b_folder:
            open_path(out.parent)

    # ==================================================================
    # 예배 순서
    # ==================================================================
    def _item_widget_text(self, item: ServiceItem) -> str:
        return item.display_name()

    def _rebuild_order_list(self, select: int | None = None) -> None:
        self.order_list.blockSignals(True)
        self.order_list.clear()
        for it in self.service.items:
            lw = QListWidgetItem(self._item_widget_text(it))
            lw.setData(Qt.UserRole, it)
            self.order_list.addItem(lw)
        self.order_list.blockSignals(False)
        if select is not None and 0 <= select < len(self.service.items):
            self.order_list.setCurrentRow(select)
        else:
            self.on_select_item(-1)

    def _sync_order_from_list(self, *args) -> None:
        self.service.items = [self.order_list.item(i).data(Qt.UserRole) for i in range(self.order_list.count())]
        self._schedule_preview()

    def _commit_editor(self) -> None:
        if self.current_item is not None:
            ed = self.editors[self.current_item.kind]
            ed.save_into(self.current_item)

    def add_item(self, kind: str, item: ServiceItem | None = None) -> None:
        self._commit_editor()
        if item is None:
            item = ServiceItem.new(kind)
            if kind == ITEM_SCRIPTURE:
                item.data["translation"] = self.settings.bible_translation
            if kind == ITEM_COVER:
                item.data["date"] = korean_date(next_sunday())
        row = self.order_list.currentRow()
        pos = row + 1 if row >= 0 else len(self.service.items)
        self.service.items.insert(pos, item)
        self._rebuild_order_list(select=pos)
        ed = self.editors[item.kind]
        focus = getattr(ed, "title", None) or getattr(ed, "reference", None)
        if focus is not None and not item.data.get("title") and not item.data.get("reference"):
            focus.setFocus()

    def move_item(self, delta: int) -> None:
        row = self.order_list.currentRow()
        new = row + delta
        if row < 0 or not (0 <= new < len(self.service.items)):
            return
        self._commit_editor()
        items = self.service.items
        items[row], items[new] = items[new], items[row]
        self._rebuild_order_list(select=new)

    def duplicate_item(self) -> None:
        row = self.order_list.currentRow()
        if row < 0:
            return
        self._commit_editor()
        src = self.service.items[row]
        self.service.items.insert(row + 1, ServiceItem(src.kind, json.loads(json.dumps(src.data))))
        self._rebuild_order_list(select=row + 1)

    def delete_item(self) -> None:
        row = self.order_list.currentRow()
        if row < 0:
            return
        item = self.service.items[row]
        if not ask_yes_no(self, "삭제", f"'{item.display_name()}' 항목을 예배 순서에서 뺄까요?"):
            return
        self.current_item = None
        del self.service.items[row]
        self._rebuild_order_list(select=min(row, len(self.service.items) - 1))

    def on_select_item(self, row: int) -> None:
        self._commit_editor()
        if row < 0 or row >= self.order_list.count():
            self.current_item = None
            self.editor_stack.setCurrentIndex(0)
            self.refresh_preview()
            return
        item = self.order_list.item(row).data(Qt.UserRole)
        self.current_item = item
        ed = self.editors[item.kind]
        ed.load(item)
        self.editor_stack.setCurrentWidget(ed)
        self.refresh_preview()

    def on_editor_changed(self) -> None:
        if self.current_item is None:
            return
        ed = self.editors[self.current_item.kind]
        ed.save_into(self.current_item)
        row = self.order_list.currentRow()
        if row >= 0:
            self.order_list.item(row).setText(self._item_widget_text(self.current_item))
        self._schedule_preview()

    def _schedule_preview(self) -> None:
        self._preview_timer.start()

    def refresh_preview(self) -> None:
        design = self.current_design()
        if self.preview_all.isChecked():
            slides = service_to_slides(self.service.items, design)
            self.preview_title.setText(f"<b>미리보기</b> — 예배 전체 {len(slides)}장")
        elif self.current_item is not None:
            slides = item_slides(self.current_item, design)
            self.preview_title.setText(f"<b>미리보기</b> — 선택한 항목 {len(slides)}장")
        else:
            slides = []
            self.preview_title.setText("<b>미리보기</b>")
        self.preview.show_slides(slides, design)
        if self.current_item is not None and self.current_item.kind == ITEM_SONG:
            self.editors[ITEM_SONG]._update_info()

    def _on_service_name(self, text: str) -> None:
        self.service.name = text.strip() or "예배"

    # ==================================================================
    # 예배 파일
    # ==================================================================
    def _set_service(self, service: Service, path: Path | None) -> None:
        self.current_item = None
        self.service = service
        self.service_path = path
        self.service_name.blockSignals(True)
        self.service_name.setText(service.name)
        self.service_name.blockSignals(False)
        self._rebuild_order_list(select=0 if service.items else None)

    def new_service(self) -> None:
        if self.service.items and not ask_yes_no(self, "새 예배", "지금 예배 순서를 지우고 새로 시작할까요?\n"
                                                              "(필요하면 먼저 [예배 저장] 하세요)"):
            return
        svc = Service(name=f"{korean_date(next_sunday())} 주일예배")
        svc.items.append(ServiceItem.new(ITEM_COVER, title="주일 예배", date=korean_date(next_sunday())))
        self._set_service(svc, None)

    def open_service(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "예배 순서 열기", str(self.settings.services_dir),
                                              "예배 순서 파일 (*.json)")
        if not path:
            return
        try:
            svc = Service.load(path)
        except Exception as e:
            QMessageBox.warning(self, "열기 실패", f"파일을 열 수 없습니다:\n{e}")
            return
        self._set_service(svc, Path(path))

    def save_service(self) -> None:
        self._commit_editor()
        default = self.service_path or self.settings.services_dir / f"{safe_filename(self.service.name)}.json"
        path, _ = QFileDialog.getSaveFileName(self, "예배 순서 저장", str(default), "예배 순서 파일 (*.json)")
        if not path:
            return
        self.service.save(path)
        self.service_path = Path(path)
        self.status(f"예배 순서를 저장했습니다: {path}")

    def make_ppt(self) -> None:
        self._commit_editor()
        if not self.service.items:
            QMessageBox.information(self, "알림", "예배 순서가 비어 있습니다.\n왼쪽 아래 [+ 찬양] 등으로 항목을 추가해 주세요.")
            return
        empty = [it.data.get("title") or "(제목 없음)" for it in self.service.items
                 if it.kind == ITEM_SONG and not item_to_song(it).sections]
        if empty and not ask_yes_no(self, "확인", "가사가 비어 있는 찬양이 있습니다:\n· " + "\n· ".join(empty) +
                                    "\n\n그래도 PPT를 만들까요?"):
            return
        self.build_items_ppt(self.service.items, self.service.name)

    def _last_session_path(self) -> Path:
        return config_dir() / "last_service.json"

    def _restore_last_session(self) -> None:
        p = self._last_session_path()
        svc = None
        if p.exists():
            try:
                svc = Service.load(p)
            except Exception:
                svc = None
        if svc is None:
            svc = Service(name=f"{korean_date(next_sunday())} 주일예배")
            svc.items.append(ServiceItem.new(ITEM_COVER, title="주일 예배", date=korean_date(next_sunday())))
        self._set_service(svc, None)

    def closeEvent(self, event) -> None:
        self._commit_editor()
        try:
            self.service.save(self._last_session_path())
            self.settings.save()
        except OSError:
            pass
        super().closeEvent(event)

    # ==================================================================
    # 가사 보관함
    # ==================================================================
    def refresh_library(self, *args) -> None:
        if not hasattr(self, "library"):
            return
        q = self.lib_search.text().strip().lower().replace(" ", "")
        self.library.clear()
        files = sorted(self.settings.lyrics_dir.glob("*.txt"), key=lambda p: p.stem)
        for f in files:
            if q and q not in f.stem.lower().replace(" ", ""):
                continue
            lw = QListWidgetItem(f"🎵 {f.stem}")
            lw.setData(Qt.UserRole, str(f))
            self.library.addItem(lw)

    def add_from_library(self) -> None:
        lw = self.library.currentItem()
        if lw is None:
            QMessageBox.information(self, "알림", "가사 보관함에서 곡을 선택해 주세요.")
            return
        path = Path(lw.data(Qt.UserRole))
        try:
            song = parse_song_text(read_text_file(path))
        except OSError as e:
            QMessageBox.warning(self, "열기 실패", str(e))
            return
        if not song.title:
            song.title = path.stem
        self.add_item(ITEM_SONG, ServiceItem(ITEM_SONG, song_to_data(song)))
        self.status(f"'{song.title}' 을(를) 예배 순서에 추가했습니다.")

    def open_library_file(self) -> None:
        lw = self.library.currentItem()
        if lw is not None:
            open_path(lw.data(Qt.UserRole))

    # ==================================================================
    # 템플릿
    # ==================================================================
    def _ensure_templates(self) -> None:
        tdir = self.settings.templates_dir
        if not any(tdir.glob("*.json")):
            for d in builtin_designs():
                d.save(tdir / f"{safe_filename(d.name)}.json")

    def reload_templates(self, select: str | None = None) -> None:
        self._designs.clear()
        for f in sorted(self.settings.templates_dir.glob("*.json")):
            try:
                d = TemplateDesign.load(f)
            except Exception:
                continue
            self._designs[d.name or f.stem] = (f, d)
        if not self._designs:
            self._ensure_templates()
            for d in builtin_designs():
                self._designs[d.name] = (self.settings.templates_dir / f"{safe_filename(d.name)}.json", d)
        want = select or self.settings.current_template
        self.template_combo.blockSignals(True)
        self.template_combo.clear()
        self.template_combo.addItems(list(self._designs))
        idx = self.template_combo.findText(want)
        self.template_combo.setCurrentIndex(max(0, idx))
        self.template_combo.blockSignals(False)
        self.settings.current_template = self.template_combo.currentText()
        self.refresh_preview()

    def on_template_changed(self, name: str) -> None:
        if not name:
            return
        self.settings.current_template = name
        self.settings.save()
        self.refresh_preview()

    def edit_template(self) -> None:
        self._open_template_editor(self.current_design())

    def new_template(self) -> None:
        base = TemplateDesign.from_dict(self.current_design().to_dict())
        base.name = f"{base.name} 복사본"
        self._open_template_editor(base)

    def _open_template_editor(self, design: TemplateDesign) -> None:
        dlg = TemplateEditorDialog(design, self.settings.templates_dir, self)
        if dlg.exec() and dlg.saved_name:
            # 이름을 바꿔 저장하면 새 템플릿이 생기고 원본은 그대로 남는다
            self.reload_templates(select=dlg.saved_name)
            self.status(f"템플릿 '{dlg.saved_name}' 을(를) 저장했습니다.")

    def delete_template(self) -> None:
        name = self.template_combo.currentText()
        if name not in self._designs or len(self._designs) <= 1:
            QMessageBox.information(self, "알림", "마지막 남은 템플릿은 지울 수 없습니다.")
            return
        if not ask_yes_no(self, "템플릿 삭제", f"'{name}' 템플릿을 삭제할까요?"):
            return
        try:
            self._designs[name][0].unlink()
        except OSError as e:
            QMessageBox.warning(self, "삭제 실패", str(e))
            return
        self.reload_templates()

    # ==================================================================
    def open_settings(self) -> None:
        old_dir = self.settings.root
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            if self.settings.root != old_dir:
                self._ensure_templates()
                self.reload_templates()
                self.refresh_library()
            self.status("설정을 저장했습니다.")
