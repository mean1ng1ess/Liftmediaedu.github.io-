"""화면 공통 도우미: 백그라운드 작업, 색 선택 버튼, 가사 강조 표시 등."""
from __future__ import annotations

import os
import subprocess
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import (QColorDialog, QMessageBox, QProgressDialog,
                               QPushButton, QWidget)

from ..ai import AIError
from ..lyrics_format import is_bracket_header


class _Worker(QThread):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, func, parent=None):
        super().__init__(parent)
        self._func = func

    def run(self) -> None:
        try:
            result = self._func()
        except AIError as e:
            self.failed.emit(str(e))
        except Exception as e:  # 예상 못한 오류도 프로그램이 죽지 않게
            traceback.print_exc()
            self.failed.emit(f"오류가 발생했습니다:\n{e}")
        else:
            self.done.emit(result)


def run_task(parent: QWidget, message: str, func, on_done, on_error=None) -> None:
    """func 을 백그라운드에서 실행하고, 끝나면 화면 스레드에서 on_done(결과) 호출."""
    dlg = QProgressDialog(message, None, 0, 0, parent)
    dlg.setWindowTitle("잠시만 기다려 주세요")
    dlg.setWindowModality(Qt.WindowModal)
    dlg.setMinimumDuration(0)
    dlg.setCancelButton(None)
    dlg.setMinimumWidth(380)
    dlg.show()

    worker = _Worker(func, parent)
    keep = parent.__dict__.setdefault("_running_workers", [])
    keep.append(worker)

    def finish():
        dlg.close()
        if worker in keep:
            keep.remove(worker)
        worker.deleteLater()

    def ok(result):
        finish()
        on_done(result)

    def fail(msg):
        finish()
        if on_error:
            on_error(msg)
        else:
            QMessageBox.warning(parent, "알림", msg)

    worker.done.connect(ok)
    worker.failed.connect(fail)
    worker.start()


def open_path(path: str | Path) -> None:
    p = str(path)
    if sys.platform.startswith("win"):
        os.startfile(p)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", p])
    else:
        subprocess.Popen(["xdg-open", p])


def open_web_search(query: str) -> None:
    """기본 브라우저로 네이버 검색 열기 (무료, 로그인 불필요)."""
    from urllib.parse import quote_plus
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    QDesktopServices.openUrl(QUrl("https://search.naver.com/search.naver?query=" + quote_plus(query)))


def ask_yes_no(parent, title: str, text: str) -> bool:
    return QMessageBox.question(parent, title, text, QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.Yes) == QMessageBox.Yes


class ColorButton(QPushButton):
    changed = Signal(str)

    def __init__(self, color: str = "#FFFFFF", parent=None):
        super().__init__(parent)
        self.setFixedWidth(70)
        self._color = color
        self.clicked.connect(self._pick)
        self._refresh()

    def color(self) -> str:
        return self._color

    def set_color(self, color: str) -> None:
        self._color = color
        self._refresh()

    def _refresh(self) -> None:
        c = QColor(self._color)
        text = "#000" if c.lightness() > 140 else "#FFF"
        self.setText(self._color.upper())
        self.setStyleSheet(f"QPushButton {{ background:{self._color}; color:{text}; "
                           f"border:1px solid #888; border-radius:4px; padding:3px; }}")

    def _pick(self) -> None:
        c = QColorDialog.getColor(QColor(self._color), self, "색 선택")
        if c.isValid():
            self._color = c.name().upper()
            self._refresh()
            self.changed.emit(self._color)


class LyricsHighlighter(QSyntaxHighlighter):
    """[Verse 1] 같은 머리말을 파란색 굵게."""

    def __init__(self, doc):
        super().__init__(doc)
        self.fmt = QTextCharFormat()
        self.fmt.setForeground(QColor("#1E6FD9"))
        self.fmt.setFontWeight(QFont.Bold)

    def highlightBlock(self, text: str) -> None:
        if is_bracket_header(text):
            self.setFormat(0, len(text), self.fmt)
