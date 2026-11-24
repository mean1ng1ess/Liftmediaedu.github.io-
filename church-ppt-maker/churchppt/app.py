"""프로그램 시작점."""
from __future__ import annotations

import os
import sys


def _frozen_fixups() -> None:
    """PyInstaller 실행 파일에서 python-pptx 가 'pptx/oxml/../templates' 경로를 찾을 수 있게."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        os.makedirs(os.path.join(base, "pptx", "oxml"), exist_ok=True)


def selftest(out_path: str) -> int:
    """화면 없이 샘플 PPT 를 만들어 본다 (설치/빌드 확인용).  ChurchPPT.exe --selftest out.pptx"""
    from .design import TemplateDesign
    from .lyrics_format import parse_song_text
    from .ppt_builder import build_presentation, read_sections
    from .service import ITEM_COVER, ITEM_SONG, ServiceItem, service_to_slides, song_to_data

    song = parse_song_text("제목: 테스트\n순서: V1 C V1 C\n\n[Verse 1]\n첫 줄\n둘째 줄\n\n[Chorus]\n후렴\n")
    items = [ServiceItem.new(ITEM_COVER, title="테스트 예배"), ServiceItem(ITEM_SONG, song_to_data(song))]
    design = TemplateDesign()
    out = build_presentation(service_to_slides(items, design), design, out_path)
    return 0 if len(read_sections(out)) == 5 else 1


def ocrtest(image: str, out_path: str, lang: str = "ko") -> int:
    """화면 없이 악보 OCR 점검:  ChurchPPT.exe --ocrtest 악보.png 결과.txt [ko|en-US]"""
    from .lyrics_format import song_to_text, write_text_file
    from .ocr import _init_thread, available_languages, lines_to_song, load_pages, ocr_image
    raw = []
    try:
        _init_thread()
        pages = [ocr_image(img, lang) for img in load_pages([image])]
        for lines, _h in pages:
            for ln in lines:
                raw.append(f"y={ln.top:.0f} h={ln.height:.0f} | " + " | ".join(
                    f"{w.text}@{w.x:.0f}" for w in ln.words))
        text = song_to_text(lines_to_song(pages))
        code = 0
    except Exception as e:  # 결과 파일에 원인을 남긴다
        langs = ""
        try:
            langs = ", ".join(available_languages())
        except Exception:
            pass
        text, code = f"ERROR: {e}\nOCR languages: {langs}", 1
    write_text_file(out_path, text + "\n\n--- raw OCR ---\n" + "\n".join(raw))
    return code


def main() -> int:
    _frozen_fixups()
    if len(sys.argv) >= 3 and sys.argv[1] == "--selftest":
        return selftest(sys.argv[2])
    if len(sys.argv) >= 4 and sys.argv[1] == "--ocrtest":
        return ocrtest(sys.argv[2], sys.argv[3], *(sys.argv[4:5]))

    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QApplication

    from . import APP_ID, APP_NAME
    from .ui.main_window import MainWindow

    if sys.platform.startswith("win"):
        try:  # 작업 표시줄에 파이썬 아이콘 대신 프로그램으로 표시
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    families = set(QFontDatabase.families())
    for name in ("맑은 고딕", "Malgun Gothic", "Apple SD Gothic Neo", "Noto Sans CJK KR", "NanumGothic"):
        if name in families:
            app.setFont(QFont(name, 10))
            break

    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
