"""CI 점검용 가짜 한글 악보 이미지 만들기 (제목 + 오선 + 음표 밑 1절/2절 가사 + 후렴).

python tests/make_sample_sheet.py out.png
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = [r"C:\Windows\Fonts\malgun.ttf", "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"]


def font(size):
    for f in FONT_CANDIDATES:
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    return ImageFont.load_default(size=size)


def staff(d, y, w):
    for i in range(5):
        d.line((80, y + i * 16, w - 80, y + i * 16), fill=0, width=2)
    for x in range(160, w - 100, 110):
        d.ellipse((x, y + 20, x + 22, y + 36), fill=0)
        d.line((x + 21, y + 28, x + 21, y - 30), fill=0, width=2)


def lyric(d, text, y, x0=150, step=110, f=None):
    x = x0
    for ch in text:
        if ch == " ":
            continue
        d.text((x, y), ch, fill=0, font=f)
        x += step


def main(out):
    W, H = 2000, 1500
    img = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(img)
    d.text((700, 40), "은혜의 강가로", fill=0, font=font(80))
    d.text((1500, 150), "작사 작곡 홍길동", fill=0, font=font(26))
    f = font(40)
    d.text((100, 300), "1.", fill=0, font=f)
    staff(d, 220, W)
    lyric(d, "주님 나를 부르시네", 320, f=f)
    d.text((100, 375), "2.", fill=0, font=f)
    lyric(d, "나의 모든 것 드려요", 375, f=f)
    staff(d, 600, W)
    lyric(d, "은혜의 강 흘러가", 700, f=f)
    lyric(d, "기쁨의 노래 부르리", 755, f=f)
    staff(d, 980, W)
    lyric(d, "할렐루야 주를 찬양", 1080, f=f)
    d.text((100, 1400), "Copyright 2020 Sample", fill=0, font=font(24))
    img.save(out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "sample_sheet.png")
