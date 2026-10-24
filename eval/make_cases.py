"""Generate the files of the evaluation cases (all synthetic). Each picture or scan is drawn from a clean CSV that is
kept next to it as `<name>.truth.csv`, so the evaluation knows exactly what the model should have read.

Run: .venv/Scripts/python.exe -X utf8 -m eval.make_cases   (Windows; uses Edge to print text PDFs and the KaiTi font)
"""
import csv
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / 'eval' / 'cases'
FIXTURES = ROOT / 'fixtures'
sys.path.insert(0, str(ROOT / 'scripts'))
import make_document_fixtures as docs  # noqa: E402  (reuses the Word writer and Edge printing)

KAI = 'C:/Windows/Fonts/simkai.ttf'
EDGE = docs.EDGE


def write_csv(path, rows, encoding='utf-8-sig'):
    with path.open('w', encoding=encoding, newline='') as f:
        csv.writer(f).writerows(rows)


def fresh(case):
    folder = CASES / case
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    return folder


# ---------- A2: lab course from a scanned PDF and a legacy academic-system .xls ----------
def case_a2():
    out = fresh('A2')
    shutil.copy(FIXTURES / 'documents' / '实验成绩登记表_扫描件.pdf', out)
    write_csv(out / '实验成绩登记表_扫描件.pdf.truth.csv', [docs.HEAD] + docs.ROWS)
    finals = [['2026101', '王晨', '正考', '86', ''], ['2026102', '李思远', '正考', '79', ''], ['2026103', '张伟', '正考', '72', ''],
              ['2026104', '张伟', '正考', '65', ''], ['2026105', '赵一凡', '正考', '', '缺考'], ['2026106', '刘洋', '正考', '91', ''],
              ['2026107', '陈佳怡', '正考', '83', ''], ['2026108', '孙浩', '正考', '58', ''], ['2026108', '孙浩', '补考', '66', ''],
              ['2026109', '周雨桐', '正考', '88', ''], ['2026110', '吴迪', '正考', '', '免修'], ['2026111', '郑凯', '正考', '61', '']]
    head = ['学号', '姓名', '课程名称', '考试性质', '成绩', '备注']
    rows = ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in [r[0], r[1], '数据结构', r[2], r[3], r[4]]) + '</tr>' for r in finals)
    page = ('<html><head><meta http-equiv="Content-Type" content="text/html; charset=gb2312"></head><body><table border="1">'
            '<tr><td colspan="6">2026-2027学年第一学期 课程成绩单（期末）</td></tr><tr>' + ''.join(f'<td>{h}</td>' for h in head) + f'</tr>{rows}</table></body></html>')
    (out / '教务系统导出_期末成绩.xls').write_bytes(page.encode('gb18030'))
    shutil.copy(FIXTURES / '数据结构_课程名单.csv', out)


# ---------- A3: handwritten attendance register photographed at an angle ----------
DATES = ['9/1', '9/8', '9/15', '9/22', '9/29', '10/13', '10/20', '10/27']
ATTENDANCE = [('王晨', '11111111'), ('李思远', '11110111'), ('张伟（1班）', '11111111'), ('张伟（2班）', '10111011'),
              ('赵一凡', '11111110'), ('刘洋', '11111111'), ('陈佳怡', '11111111'), ('孙浩', '01101111'),
              ('周雨桐', '11111111'), ('吴迪', '11011111'), ('郑凯', '11100000'), ('李明', '00011100')]


def tick(draw, x, y, rng):
    """A hand-drawn tick: two strokes with jitter, not a font glyph."""
    a = (x + rng.randint(-3, 3), y + 18 + rng.randint(-3, 3))
    b = (x + 10 + rng.randint(-2, 2), y + 32 + rng.randint(-3, 3))
    c = (x + 30 + rng.randint(-4, 4), y + rng.randint(-4, 4))
    color = (20, 30, 90 + rng.randint(0, 40))
    draw.line([a, b], fill=color, width=4)
    draw.line([b, c], fill=color, width=4)


def case_a3():
    out = fresh('A3')
    rng = random.Random(23)
    col, line, left = 112, 70, 60
    width, height = left + 210 + col * len(DATES) + 40, 200 + line * (len(ATTENDANCE) + 1)
    image = Image.new('RGB', (width, height), (246, 242, 228))
    draw = ImageDraw.Draw(image)
    title, hand = ImageFont.truetype(KAI, 44), ImageFont.truetype(KAI, 36)
    draw.text((left, 30), '数据结构 课堂考勤（2026秋）', font=title, fill=(30, 40, 90))
    top = 120
    for r in range(len(ATTENDANCE) + 2):
        draw.line([(left, top + r * line), (width - 40, top + r * line)], fill=(120, 120, 140), width=2)
    xs = [left, left + 210] + [left + 210 + col * (i + 1) for i in range(len(DATES))]
    for x in xs:
        draw.line([(x, top), (x, top + line * (len(ATTENDANCE) + 1))], fill=(120, 120, 140), width=2)
    draw.text((left + 50, top + 16), '姓名', font=hand, fill=(30, 40, 90))
    for i, d in enumerate(DATES):
        draw.text((left + 222 + col * i + rng.randint(-4, 4), top + 16 + rng.randint(-3, 3)), d, font=hand, fill=(30, 40, 90))
    for r, (name, marks) in enumerate(ATTENDANCE, 1):
        y = top + r * line + 14
        size = rng.choice([34, 36, 38])
        draw.text((left + 12 + rng.randint(-5, 5), y + rng.randint(-4, 4)), name, font=ImageFont.truetype(KAI, size), fill=(25, 35, 100))
        for i, m in enumerate(marks):
            if m == '1':
                tick(draw, left + 248 + col * i, y, rng)
    # Uneven light, a slight perspective and blur, then JPEG like a phone picture.
    shade = Image.linear_gradient('L').resize(image.size).point(lambda v: 205 + v // 5)
    image = Image.composite(image, Image.new('RGB', image.size, (150, 145, 130)), shade)
    w, h = image.size
    image = image.transform((w, h), Image.QUAD, (18, 10, 0, h - 4, w - 6, h, w - 26, 0), resample=Image.BICUBIC, fillcolor=(90, 90, 90))
    image = image.rotate(1.6, expand=True, fillcolor=(90, 90, 90)).filter(ImageFilter.GaussianBlur(0.8))
    image.save(out / '课堂考勤登记表_手写.jpg', quality=82)
    write_csv(out / '课堂考勤登记表_手写.jpg.truth.csv', [['姓名'] + DATES] + [[n] + ['√' if m == '1' else '' for m in marks] for n, marks in ATTENDANCE])
    finals = [['2026101', '王晨', '88'], ['2026102', '李思远', '76'], ['2026103', '张伟', '94'], ['2026104', '张伟', '62'],
              ['2026105', '赵一凡', '70'], ['2026106', '刘洋', '85'], ['2026107', '陈佳怡', '91'], ['2026108', '孙浩', '67'],
              ['2026109', '周雨桐', '80'], ['2026110', '吴迪', '73'], ['2026111', '郑凯', '55']]
    write_csv(out / '期末成绩.csv', [['学号', '姓名', '期末成绩']] + finals)
    shutil.copy(FIXTURES / '数据结构_课程名单.csv', out)


# ---------- A4 / A5: unfamiliar headers (pinyin initials, English export), leading-zero IDs, no roster ----------
OS_STUDENTS = [('0231001', '高远'), ('0231002', '林小雨'), ('0231003', '马骁'), ('0231004', '黄思琪'), ('0231005', '何俊'),
               ('0231006', '罗晓燕'), ('0231007', '梁宇'), ('0231008', '宋佳'), ('0231009', '谢天'), ('0231010', '韩冰')]


def os_files(out):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(['XH', 'XM', '平时(30%)', '期末卷面(70%)', '备注'])
    scores = [(92, 81, ''), (85, 77, ''), (78, None, '缺考'), (88, 90, ''), (70, 45, ''), (95, 88, ''), (60, 52, '考试作弊'),
              (82, 79, ''), (75, 68, ''), (90, 93, '')]
    for (sid, name), (usual, final, note) in zip(OS_STUDENTS, scores):
        ws.append([sid, name, usual, final, note])
    for row in ws.iter_rows(min_row=2, max_col=1):
        row[0].number_format = '@'
    wb.save(out / '操作系统_成绩汇总.xlsx')
    quiz = [[8, 9, 7], [6, 8, 9], [9, 9, 10], [7, 7, 8], [5, 6, 7], [10, 9, 9], [6, 5, 7], [8, 8, 9], [7, 6, 8], [9, 10, 10]]
    write_csv(out / '雨课堂_Quiz导出.csv', [['Student No.', 'Name', 'Quiz 1 (10)', 'Quiz 2 (10)', 'Quiz 3 (10)']]
              + [[sid, name] + q for (sid, name), q in zip(OS_STUDENTS, quiz)])


def case_a4():
    os_files(fresh('A4'))


def case_a5():
    os_files(fresh('A5'))


# ---------- B3: the counselor materials with uninformative file names and mixed formats ----------
B3_FORMAT = {  # original name -> (new name, format)
    '王敏_党员发展计划与教育活动记录.txt': ('扫描文档_01.pdf', 'pdf'), '王敏_思政主题教育记录.txt': ('新建文档.docx', 'docx'),
    '王敏_辅导员工作日志_节选.txt': ('材料03.txt', 'txt'), '王敏_谈话记录汇总.txt': ('材料04.docx', 'docx'),
    '王敏_宿舍检查与安全教育.txt': ('扫描文档_05.pdf', 'pdf'), '王敏_科技讲座通知_第1期.txt': ('通知.txt', 'txt'),
    '王敏_科技讲座通知_第2期.txt': ('通知(1).txt', 'txt'), '王敏_心理工作记录.txt': ('材料08.docx', 'docx'),
    '李强_工作日志.txt': ('日志.txt', 'txt'), '李强_论文_核心期刊.txt': ('论文信息.pdf', 'pdf'),
    '李强_论文_CN期刊转载.txt': ('论文信息(2).txt', 'txt'), '李强_党建活动记录.txt': ('材料12.docx', 'docx'),
    '李强_主题班会记录.txt': ('材料13.txt', 'txt'), '赵琳_工作日志.txt': ('日志(1).txt', 'txt'),
    '赵琳_谈话记录.txt': ('材料15.pdf', 'pdf'), '赵琳_心理普测通知.txt': ('关于普测的通知.txt', 'txt'),
    '赵琳_心理辅导与危机上报工作记录.txt': ('材料17.docx', 'docx'), '赵琳_科技讲座通知.txt': ('通知(2).txt', 'txt'),
    '赵琳_宿舍安全检查记录.txt': ('材料19.txt', 'txt'), '活动照片说明_未署名.txt': ('说明.txt', 'txt'),
    '王敏_值班记录.csv': ('值班表A.csv', 'copy'), '李强_值班记录.csv': ('值班表B.csv', 'copy'), '赵琳_值班记录.csv': ('值班表C.csv', 'copy'),
    '王敏_心理委员名单.csv': ('心理委员名单.csv', 'copy'), '赵琳_心理委员名单.csv': ('心理委员名单(1).csv', 'copy'),
    '王敏_获奖证书_挑战杯省赛_学生1.png': ('IMG_20260512_101233.jpg', 'jpg'), '王敏_获奖证书_挑战杯省赛_学生2.png': ('IMG_20260512_101240.jpg', 'jpg'),
    '王敏_获奖证书_数学建模国赛.png': ('证书扫描.pdf', 'imgpdf'), '李强_获奖证书_挑战杯省赛.png': ('微信图片_20260520.jpg', 'jpg'),
    '李强_获奖证书_校程序设计赛.png': ('IMG_0412.jpg', 'jpg'),
}


def text_pdf(text, target):
    page = '<!doctype html><meta charset="utf-8"><style>body{font-family:SimSun;font-size:16px;line-height:1.8;margin:30mm}</style>' + \
        ''.join(f'<p>{line}</p>' for line in text.splitlines())
    with tempfile.TemporaryDirectory() as tmp:
        html = Path(tmp) / 'doc.html'
        html.write_text(page, encoding='utf-8')
        subprocess.run([str(EDGE), '--headless=new', '--disable-gpu', f'--user-data-dir={Path(tmp) / "p"}', '--no-pdf-header-footer',
                        f'--print-to-pdf={target}', html.as_uri()], check=True, timeout=120, capture_output=True)


def case_b3():
    out = fresh('B3')
    source = FIXTURES / 'appraisal'
    for original, (name, kind) in B3_FORMAT.items():
        path = source / original
        if kind == 'copy' or kind == 'txt':
            shutil.copy(path, out / name)
        elif kind == 'pdf':
            text_pdf(path.read_text(encoding='utf-8'), out / name)
        elif kind == 'docx':
            body = ''.join(docs.para(line) for line in path.read_text(encoding='utf-8').splitlines())
            docs.write_docx(out / name, body)
        elif kind == 'jpg':
            image = Image.open(path).convert('RGB').rotate(random.Random(name).choice([-2, -1, 1, 2]), expand=True, fillcolor=(200, 200, 200))
            image.save(out / name, quality=80)
        elif kind == 'imgpdf':
            Image.open(path).convert('L').rotate(-1, expand=True, fillcolor=235).convert('RGB').save(out / name, resolution=150)


if __name__ == '__main__':
    for build in (case_a2, case_a3, case_a4, case_a5, case_b3):
        build()
        print('built', build.__name__)
