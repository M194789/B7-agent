"""Draw the synthetic classroom note as a handwriting-style photo. Needs Pillow and a KaiTi font (Windows: simkai.ttf)."""
import csv
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FONT = Path('C:/Windows/Fonts/simkai.ttf')
rows = list(csv.reader((ROOT / 'fixtures' / '课堂答问记录_誊录.csv').open(encoding='utf-8-sig')))[1:]

random.seed(7)
width, line = 1100, 74
height = 220 + line * (len(rows) + 1)
image = Image.new('RGB', (width, height), (247, 243, 230))
draw = ImageDraw.Draw(image)
for y in range(150, height, line):
    draw.line([(40, y), (width - 40, y)], fill=(170, 190, 215), width=2)
draw.line([(110, 0), (110, height)], fill=(225, 150, 150), width=2)
title = ImageFont.truetype(str(FONT), 46)
hand = ImageFont.truetype(str(FONT), 40)
draw.text((150, 18), '数据结构  课堂答问记录（2026秋）', font=title, fill=(30, 40, 90))
columns = [150, 380, 640, 880]
for x, label in zip(columns, ['日期', '姓名', '事项', '登记']):
    draw.text((x, 150 - 58), label, font=hand, fill=(30, 40, 90))
for i, row in enumerate(rows):
    y = 150 + i * line + 14
    for x, value in zip(columns, row):
        draw.text((x + random.randint(-6, 6), y + random.randint(-5, 5)), value, font=hand, fill=(25 + random.randint(0, 25), 35, 95))
image = image.rotate(-1.2, expand=True, fillcolor=(90, 90, 90)).filter(ImageFilter.GaussianBlur(0.6))
image.save(ROOT / 'fixtures' / '课堂答问记录_拍照.png', optimize=True)
print('Classroom photo created.')
