"""설정 창 (Claude API 키, 모델, 저장 폴더)."""
from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QVBoxLayout)

from ..ai import AIClient
from ..settings import BIBLE_TRANSLATIONS, MODEL_CHOICES, AppSettings
from .common import open_path, run_task

API_KEY_URL = "https://console.anthropic.com/settings/keys"


class SettingsDialog(QDialog):
    def __init__(self, settings: AppSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("설정")
        self.setMinimumWidth(620)
        self.settings = settings
        lay = QVBoxLayout(self)

        intro = QLabel(
            "<b>API 키 없이도 모든 기본 기능은 무료로 쓸 수 있습니다.</b> "
            "(인터넷에서 가사 검색 → 복사 → 붙여넣기 → 자동 나누기 → PPT)<br><br>"
            "아래는 <b>선택 사항</b>입니다. Claude API 키를 넣으면 AI 가사 찾기·악보 사진 읽기·"
            "설교 요약이 추가되며, 사용한 만큼 요금이 부과됩니다. 필요 없으면 비워 두세요.")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        form = QFormLayout()
        key_row = QHBoxLayout()
        self.api_key = QLineEdit(settings.api_key)
        self.api_key.setEchoMode(QLineEdit.Password)
        self.api_key.setPlaceholderText("sk-ant-...")
        show = QCheckBox("보기")
        show.toggled.connect(lambda on: self.api_key.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
        get_key = QPushButton("키 발급받기")
        get_key.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(API_KEY_URL)))
        key_row.addWidget(self.api_key, 1)
        key_row.addWidget(show)
        key_row.addWidget(get_key)
        form.addRow("Claude API 키 (선택)", key_row)

        self.model = QComboBox()
        self.model.setEditable(True)
        for mid, label in MODEL_CHOICES:
            self.model.addItem(label, mid)
        idx = self.model.findData(settings.model)
        if idx >= 0:
            self.model.setCurrentIndex(idx)
        else:
            self.model.setEditText(settings.model)
        form.addRow("AI 모델", self.model)

        test_row = QHBoxLayout()
        b_test = QPushButton("연결 테스트")
        b_test.clicked.connect(self.on_test)
        test_row.addWidget(b_test)
        test_row.addStretch(1)
        form.addRow("", test_row)

        self.translation = QComboBox()
        self.translation.setEditable(True)
        self.translation.addItems(BIBLE_TRANSLATIONS)
        self.translation.setCurrentText(settings.bible_translation)
        form.addRow("기본 성경 번역본", self.translation)

        dir_row = QHBoxLayout()
        self.data_dir = QLineEdit(str(settings.root))
        b_dir = QPushButton("바꾸기...")
        b_open = QPushButton("열기")
        b_dir.clicked.connect(self.on_pick_dir)
        b_open.clicked.connect(lambda: open_path(self.data_dir.text()))
        dir_row.addWidget(self.data_dir, 1)
        dir_row.addWidget(b_dir)
        dir_row.addWidget(b_open)
        form.addRow("저장 폴더", dir_row)
        lay.addLayout(form)

        note = QLabel("저장 폴더 안에 '가사'(메모장 파일), '템플릿', '예배순서', '완성된PPT' 폴더가 만들어집니다.\n"
                      "API 키는 이 컴퓨터의 사용자 설정 폴더에만 저장됩니다.")
        note.setStyleSheet("color:#666;")
        note.setWordWrap(True)
        lay.addWidget(note)

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText("저장")
        bb.button(QDialogButtonBox.Cancel).setText("취소")
        bb.accepted.connect(self.on_accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _model_id(self) -> str:
        data = self.model.currentData()
        text = self.model.currentText().strip()
        if data and self.model.itemText(self.model.currentIndex()) == text:
            return data
        return text

    def on_pick_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "저장 폴더 선택", self.data_dir.text())
        if path:
            self.data_dir.setText(path)

    def on_test(self) -> None:
        key = self.api_key.text().strip()
        model = self._model_id()
        try:
            client = AIClient(key, model)
        except Exception as e:
            QMessageBox.warning(self, "연결 테스트", str(e))
            return
        run_task(self, "Claude 에 연결하는 중...", client.test_connection,
                 lambda _: QMessageBox.information(self, "연결 테스트", f"연결 성공! ({model})"),
                 lambda msg: QMessageBox.warning(self, "연결 테스트 실패", msg))

    def on_accept(self) -> None:
        s = self.settings
        s.api_key = self.api_key.text().strip()
        s.model = self._model_id() or s.model
        s.bible_translation = self.translation.currentText().strip() or s.bible_translation
        s.data_dir = self.data_dir.text().strip()
        try:
            s.ensure_dirs()
        except OSError as e:
            QMessageBox.warning(self, "오류", f"폴더를 만들 수 없습니다: {e}")
            return
        s.save()
        self.accept()
