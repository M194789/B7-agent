"""Synthetic PDF / Word / messy Excel fixtures for document reading. Needs Pillow, openpyxl, pypdfium2 and Microsoft Edge
(used headless to print an HTML score sheet to a PDF with a real Chinese text layer)."""
import io
import random
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

import pypdfium2 as pdfium
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'fixtures' / 'documents'
EDGE = Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')
TITLE = '郑州大学 2026秋 《数据结构》实验成绩登记表'
INFO = '开课学院：计算机学院　　任课教师：（示例）　　满分：每次实验 100 分'
HEAD = ['学号', '姓名', '实验1', '实验2', '实验3']
ROWS = [
    ['2026101', '王晨', '92', '88', '95'], ['2026102', '李思远', '85', '90', '87'], ['2026103', '张伟', '78', '80', '76'],
    ['2026104', '张伟', '70', '未交', '72'], ['2026105', '赵一凡', '88', '85', '90'], ['2026106', '刘洋', '95', '93', '96'],
    ['2026107', '陈佳怡', '82', '79', '85'], ['2026108', '孙浩', '76', '81', '78'], ['2026109', '周雨桐', '90', '92', '89'],
    ['2026110', '吴迪', '免修', '免修', '免修'], ['2026111', '郑凯', '65', '70', '68'],
]
AVERAGE = ['平均分', '', '82.1', '84.2', '82.6']


def printed_pdf():
    """Two pages; the second page continues the table without repeating the header, as many 教务 printouts do."""
    cells = lambda r, tag='td': '<tr>' + ''.join(f'<{tag}>{c}</{tag}>' for c in r) + '</tr>'
    page = ('<!doctype html><meta charset="utf-8"><style>@page{size:A4;margin:22mm}body{font-family:"SimSun";font-size:15px}'
            'h1{font-size:20px;text-align:center}table{width:100%;border-collapse:collapse;margin-top:8px}td,th{border:1px solid #000;padding:12px 8px;text-align:center}'
            '.next{break-before:page}p{margin:6px 0}</style>'
            f'<h1>{TITLE}</h1><p>{INFO}</p><table>{cells(HEAD, "th")}{"".join(cells(r) for r in ROWS[:6])}</table>'
            f'<table class="next">{"".join(cells(r) for r in ROWS[6:])}{cells(AVERAGE)}</table>'
            '<p style="margin-top:30px">任课教师签字：__________　　　日期：2027 年 1 月 15 日</p>')
    with tempfile.TemporaryDirectory() as tmp:
        html = Path(tmp) / 'sheet.html'
        html.write_text(page, encoding='utf-8')
        target = OUT / '实验成绩登记表_教务打印.pdf'
        subprocess.run([str(EDGE), '--headless=new', '--disable-gpu', f'--user-data-dir={Path(tmp) / "profile"}', '--no-pdf-header-footer',
                        f'--print-to-pdf={target}', html.as_uri()], check=True, timeout=120, capture_output=True)
    return target


def scanned_pdf(source):
    """Render the printed sheet, then make it look scanned: grey, slightly rotated, blurred and noisy. No text layer."""
    random.seed(11)
    pdf = pdfium.PdfDocument(str(source))
    pages = []
    for index in range(len(pdf)):
        image = pdf[index].render(scale=150 / 72).to_pil().convert('L')
        image = image.rotate(random.choice([-0.9, 0.7]), expand=True, fillcolor=235).filter(ImageFilter.GaussianBlur(0.7))
        noise = Image.effect_noise(image.size, 18)
        pages.append(Image.blend(image, noise, 0.08).convert('RGB'))
    pdf.close()
    pages[0].save(OUT / '实验成绩登记表_扫描件.pdf', save_all=True, append_images=pages[1:], resolution=150)


def messy_xlsx():
    """Title rows, a merged two-level header and an average row, like a hand-made Excel sheet."""
    wb = Workbook()
    ws = wb.active
    ws.title = '实验成绩'
    ws.append([TITLE])
    ws.merge_cells('A1:F1')
    ws.append([INFO])
    ws.merge_cells('A2:F2')
    ws.append(['学号', '姓名', '实验成绩', None, None, '备注'])
    ws.merge_cells('C3:E3')
    ws.merge_cells('A3:A4')
    ws.merge_cells('B3:B4')
    ws.merge_cells('F3:F4')
    ws.append([None, None, '实验1', '实验2', '实验3', None])
    for row in ROWS:
        ws.append([row[0], row[1]] + [int(x) if x.isdigit() else x for x in row[2:]] + [''])
    ws.append(AVERAGE + [''])
    for cell in ws[1] + ws[3] + ws[4]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal='center')
    wb.save(OUT / '实验成绩_手工汇总表.xlsx')


def legacy_xls():
    """Two kinds of “.xls”: a real Excel 97-2003 file (saved by Excel itself, Windows only) and the HTML page in GBK
    that many academic systems hand out with an .xls extension."""
    real = OUT / '实验成绩_Excel97格式.xls'
    script = (f"$x = New-Object -ComObject Excel.Application; $x.DisplayAlerts = $false; $w = $x.Workbooks.Open('{OUT / '实验成绩_手工汇总表.xlsx'}'); "
              f"$w.SaveAs('{real}', 56); $w.Close($false); $x.Quit()")
    subprocess.run(['powershell', '-NoProfile', '-Command', script], check=True, timeout=120)
    rows = ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in r) + '</tr>' for r in ROWS)
    page = (f'<html><head><meta http-equiv="Content-Type" content="text/html; charset=gb2312"></head><body><table border="1">'
            f'<tr><td colspan="5">{TITLE}</td></tr><tr>' + ''.join(f'<td>{h}</td>' for h in HEAD) + f'</tr>{rows}</table></body></html>')
    (OUT / '教务系统导出_实验成绩.xls').write_bytes(page.encode('gb18030'))


W_NS ='xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" ' \
       'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" ' \
       'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"'


def para(text, bold=False):
    run = '<w:rPr><w:b/></w:rPr>' if bold else ''
    return f'<w:p><w:r>{run}<w:t xml:space="preserve">{text}</w:t></w:r></w:p>'


def cell(text, span=1, vmerge=None):
    props = (f'<w:gridSpan w:val="{span}"/>' if span > 1 else '') + (f'<w:vMerge w:val="{vmerge}"/>' if vmerge == 'restart' else '<w:vMerge/>' if vmerge else '')
    return f'<w:tc><w:tcPr>{props}</w:tcPr>{para(text)}</w:tc>'


def picture(rel, cx=4800000, cy=3400000):
    return (f'<w:p><w:r><w:drawing><wp:inline><wp:extent cx="{cx}" cy="{cy}"/><wp:docPr id="1" name="证书"/><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            f'<pic:pic><pic:nvPicPr><pic:cNvPr id="1" name="证书"/><pic:cNvPicPr/></pic:nvPicPr><pic:blipFill><a:blip r:embed="{rel}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>')


def write_docx(path, body, images=()):
    rels = ''.join(f'<Relationship Id="img{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image{i}.png"/>'
                   for i in range(1, len(images) + 1))
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
                   '<Default Extension="png" ContentType="image/png"/>'
                   '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr('_rels/.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr('word/_rels/document.xml.rels', f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{rels}</Relationships>')
        z.writestr('word/document.xml', f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {W_NS}><w:body>{body}<w:sectPr/></w:body></w:document>')
        for i, image in enumerate(images, 1):
            z.writestr(f'word/media/image{i}.png', image)


def word_table():
    grid = '<w:tblGrid>' + '<w:gridCol w:w="1500"/>' * 6 + '</w:tblGrid>'
    border = '<w:tblPr><w:tblBorders>' + ''.join(f'<w:{s} w:val="single" w:sz="4"/>' for s in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV')) + '</w:tblBorders></w:tblPr>'
    head1 = '<w:tr>' + cell('学号', vmerge='restart') + cell('姓名', vmerge='restart') + cell('实验成绩', span=3) + cell('备注', vmerge='restart') + '</w:tr>'
    head2 = '<w:tr>' + cell('', vmerge=True) + cell('', vmerge=True) + cell('实验1') + cell('实验2') + cell('实验3') + cell('', vmerge=True) + '</w:tr>'
    body = ''.join('<w:tr>' + ''.join(cell(c) for c in r + ['']) + '</w:tr>' for r in ROWS)
    body += '<w:tr>' + ''.join(cell(c) for c in AVERAGE + ['']) + '</w:tr>'
    document = para(TITLE, bold=True) + para(INFO) + f'<w:tbl>{border}{grid}{head1}{head2}{body}</w:tbl>' + para('任课教师签字：__________')
    write_docx(OUT / '实验成绩登记表_Word版.docx', document)


def appraisal_documents():
    """A scanned certificate PDF and a Word summary with a certificate picture pasted in."""
    source = ROOT / 'fixtures' / 'appraisal'
    image = Image.open(source / '王敏_获奖证书_数学建模国赛.png').convert('L').rotate(-1.1, expand=True, fillcolor=240)
    image.filter(ImageFilter.GaussianBlur(0.6)).convert('RGB').save(OUT / '王敏_获奖证书_数学建模国赛_扫描.pdf', resolution=150)
    certificate = io.BytesIO()
    Image.open(source / '李强_获奖证书_挑战杯省赛.png').save(certificate, 'PNG')
    body = (para('2026年度个人工作总结', bold=True) + para('姓名：李强　　岗位：2024级辅导员')
            + para('一、学生竞赛指导：指导学生团队参加第十九届“挑战杯”河南省大学生课外学术科技作品竞赛，作品《智慧校园能耗监测系统》获省级二等奖（证书附后）。')
            + para('二、日常管理：全年开展谈心谈话 96 人次，完成值班 24 次，组织宿舍安全检查 10 次。')
            + para('三、不足：年级心理委员培训次数偏少，明年计划每学期组织 2 次。')
            + para('附：获奖证书扫描件') + picture('img1'))
    write_docx(OUT / '李强_年度工作总结.docx', body, [certificate.getvalue()])


if __name__ == '__main__':
    OUT.mkdir(exist_ok=True)
    printed = printed_pdf()
    scanned_pdf(printed)
    messy_xlsx()
    legacy_xls()
    word_table()
    appraisal_documents()
    print('Document fixtures created in', OUT)
