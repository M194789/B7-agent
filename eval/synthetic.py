"""Synthetic course data in many shapes, for generalisation tests that need no model.

One class (roster, a platform export with three parts, letter-graded homework, an exam register with absences and a
question log that writes either the number or the name) is written out in a different shape for every seed: an
unfamiliar platform name, other words for every column, shuffled columns and rows, CSV, Excel (several sheets in one
workbook, in any order) or Word tables, neutral file names, full-width digits and stray spaces. The expected totals
are computed here from the class itself, independently of the application, so a variant is checked for being right,
not just for agreeing with another variant.

`truth(headers)` is what a model that understood the columns would answer; the tests hand it to the application in
place of the model, so what is tested is everything after the semantic step.
"""
from __future__ import annotations

import csv
import io
import random
import zipfile
from decimal import ROUND_HALF_UP, Decimal
from xml.sax.saxutils import escape

from openpyxl import Workbook

PLATFORMS = ['学习通', '雨课堂', '智慧树', '云课堂', '知行在线', '慧学平台']
WORDS = {
    'sid': ['学号', '学生编号', '学籍号', 'Student ID'],
    'name': ['姓名', '学生姓名', 'Name', '名字'],
    'watch': ['视频观看', '观看得分', '视频学习', '课程视频'],
    'quiz': ['章节测验', '单元测试', '随堂测', '测验得分'],
    'task': ['任务点', '学习任务', '在线任务', '任务完成'],
    'item': ['考核项目', '考试类型', '项目'],
    'score': ['成绩', '分数', '得分', '卷面成绩'],
    'remark': ['备注', '说明'],
    'hw': ['作业', 'HW', '课后作业'],
    'date': ['日期', '记录日期', '时间'],
    'who': ['学号/姓名', '回答人', '记录内容'],
    'question': ['题号', '问题编号', '问题'],
}
GRADES = {'A': 95, 'B': 85, 'C': 75}
PARTS = {'watch': 20, 'quiz': 50, 'task': 30}
WEIGHTS = {'平台': 30, '作业': 20, '问答': 10, '期中': 15, '期末': 25}
FULL_COUNT = 4
DAYS = ['9/8', '9/15', '9/22', '9/29', '10/6', '10/13']
FULL = str.maketrans('0123456789', '０１２３４５６７８９')


def make_class(n=24, seed=7):
    rnd = random.Random(seed)
    surnames, given = '赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦许何吕施张孔曹严', '伟芳娜敏静丽强磊军洋勇艳杰涛明超秀霞平刚桂英华'
    people, used = [], set()
    while len(people) < n:
        name = rnd.choice(surnames) + rnd.choice(given) + rnd.choice(given)
        if name not in used:
            used.add(name)
            people.append({'sid': f'00261{len(people) + 1:03d}', 'name': name})
    for i, p in enumerate(people):
        p.update(watch=rnd.randint(40, 100), quiz=rnd.randint(30, 100), task=rnd.randint(50, 100),
                 hw=[rnd.choice('ABC') for _ in range(4)], answers=rnd.randint(0, 6),
                 mid=rnd.randint(35, 98), final=rnd.randint(30, 99), mid_status='', final_status='')
    people[4]['final_status'] = '缺考'
    people[6]['mid_status'] = '缓考'
    return people


def money(value):
    return Decimal(value).quantize(Decimal('0.01'), ROUND_HALF_UP)


def expected(people):
    """Totals by the rule, computed here: 平台 30% (视频 20、测验 50、任务 30), 作业 20% (A95 B85 C75 的平均), 问答 10% (4 次满分),
    期中 15%, 期末 25%; 缺考 0 分, 缓考 总评待定; two decimals, half up."""
    out = {}
    for p in people:
        if p['mid_status'] == '缓考' or p['final_status'] == '缓考':
            out[p['sid']] = None
            continue
        platform = money(sum(Decimal(p[k]) * w for k, w in PARTS.items()) / 100)
        hw = sum(Decimal(GRADES[g]) for g in p['hw']) / len(p['hw'])
        qa = Decimal(min(p['answers'], FULL_COUNT)) / FULL_COUNT * 100
        mid = Decimal(0 if p['mid_status'] == '缺考' else p['mid'])
        final = Decimal(0 if p['final_status'] == '缺考' else p['final'])
        parts = {'平台': platform, '作业': hw, '问答': qa, '期中': mid, '期末': final}
        out[p['sid']] = float(money(sum(parts[k] * w for k, w in WEIGHTS.items()) / 100))
    return out


def docx_bytes(rows):
    cell = lambda v: f'<w:tc><w:p><w:r><w:t xml:space="preserve">{escape(str(v))}</w:t></w:r></w:p></w:tc>'
    table = '<w:tbl>' + ''.join('<w:tr>' + ''.join(cell(v) for v in r) + '</w:tr>' for r in rows) + '</w:tbl>'
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           f'<w:body><w:p><w:r><w:t>登记表</w:t></w:r></w:p>{table}</w:body></w:document>')
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as z:
        z.writestr('[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" '
                   'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr('word/document.xml', doc)
    return stream.getvalue()


def csv_bytes(rows):
    stream = io.StringIO(newline='')
    csv.writer(stream).writerows(rows)
    return stream.getvalue().encode('utf-8-sig')


def xlsx_bytes(sheets):
    book = Workbook()
    book.remove(book.active)
    for title, rows in sheets:
        ws = book.create_sheet(title)
        for r in rows:
            ws.append([str(v) for v in r])
    stream = io.BytesIO()
    book.save(stream)
    return stream.getvalue()


def variant(people, seed, anomalies=()):
    """(files as [(name, bytes)], truth mappings by header tuple, the names of the assessments as the application will see them)."""
    rnd = random.Random(seed)
    w = {k: rnd.choice(v) for k, v in WORDS.items()}
    platform = rnd.choice(PLATFORMS)
    sid = lambda p: p['sid'].translate(FULL) if rnd.random() < .15 else p['sid']  # full-width digits now and then
    name = lambda p: p['name'][0] + ' ' + p['name'][1:] if rnd.random() < .1 else p['name']
    tables, truth = {}, {}

    def put(key, headers, rows, mapping, order=True):
        index = list(range(len(headers)))
        if order:
            rnd.shuffle(index)
        rows = list(rows)
        rnd.shuffle(rows)
        headers = [headers[i] for i in index]
        tables[key] = [headers] + [[r[i] for i in index] for r in rows]
        truth[tuple(headers)] = mapping

    extra = rnd.random() < .5  # a roster exported with class and term columns
    roster = [[p['sid'], p['name']] + (['2023级1班', '2026秋'] if extra else []) for p in people]
    put('roster', [w['sid'], w['name']] + (['班级', '学期'] if extra else []), roster, {'student_id': w['sid'], 'student_name': w['name']})
    cols = {k: w[k] for k in PARTS}
    rows = [[sid(p), name(p), p['watch'], p['quiz'], p['task']] for p in people]
    if 'out_of_range' in anomalies:
        rows[1][2] = 130
    put('platform', [w['sid'], w['name'], cols['watch'], cols['quiz'], cols['task']], rows,
        {'student_id': w['sid'], 'student_name': w['name'], 'item_columns': list(cols.values()), 'source_name': platform})
    hw = [f'{w["hw"]}{i}' for i in range(1, 5)]
    put('homework', [w['sid'], w['name'], *hw], [[sid(p), name(p), *p['hw']] for p in people],
        {'student_id': w['sid'], 'student_name': w['name'], 'item_columns': hw, 'item_name': '作业'})
    exam = []
    for p in people:
        for item, score, status in (('期中', p['mid'], p['mid_status']), ('期末', p['final'], p['final_status'])):
            exam.append([sid(p), name(p), rnd.choice([item, item + '考试']), '' if status else score, status])
    if 'unknown_id' in anomalies:
        exam[2 * 2][0] = '00261099'  # the third student's 期中 under a number nobody has
    exam_map = {'student_id': w['sid'], 'student_name': w['name'], 'assessment': w['item'], 'score': w['score'], 'remark': w['remark']}
    put('exam', [w['sid'], w['name'], w['item'], w['score'], w['remark']], exam, exam_map)
    log = []
    for p in people:
        for k in range(p['answers']):
            who = p['name'] if rnd.random() < .4 else p['sid']
            log.append([DAYS[k], who, f'Q{k + 1}'])
            if rnd.random() < .15:
                log.append([DAYS[k], who, f'Q{k + 1}'])  # the same answer written down twice
    put('log', [w['date'], w['who'], w['question']], log,
        {'occurrence': w['date'], 'student': w['who'], 'question': w['question'], 'events': True, 'item_name': '问答'})
    files = []
    layout = rnd.choice(['separate', 'workbook'])
    formats = {k: rnd.choice(['csv', 'xlsx', 'docx']) for k in tables}
    formats['roster'] = rnd.choice(['csv', 'xlsx'])
    names = iter(rnd.sample(['导出1', '数据表', 'data_0915', '材料A', '登记', '汇总表', 'sheet导出', '附件3', '表格2', 'export'], 6))
    if layout == 'workbook':
        sheets = [(f'{platform}导出', tables.pop('platform')), ('作业登记', tables.pop('homework'))]
        rnd.shuffle(sheets)
        files.append((next(names) + '.xlsx', xlsx_bytes(sheets)))
    for key, rows in tables.items():
        fmt = formats[key]
        base = next(names)
        files.append((f'{base}.{fmt}', csv_bytes(rows) if fmt == 'csv' else xlsx_bytes([('Sheet1', rows)]) if fmt == 'xlsx' else docx_bytes(rows)))
    if 'copy' in anomalies:
        files.append(('exam_copy.csv', csv_bytes(tables['exam'] if 'exam' in tables else [])))
    if 'conflict' in anomalies:
        other = [[w['sid'], w['name'], w['item'], w['score'], w['remark']], [people[3]['sid'], people[3]['name'], '期末', people[3]['final'] + 5, '']]
        files.append(('补登.csv', csv_bytes(other)))
        truth[tuple(other[0])] = exam_map
    rnd.shuffle(files)
    assessments = {'parts': {k: f'{platform}·{cols[k]}' for k in PARTS}, 'hw': w['hw']}
    return files, truth, assessments


def rule(assessments):
    """The rule as a model that read “平台30%（视频20、测验50、任务30）……” against these data would state it."""
    return {'components': [
        {'name': '平台', 'weight': 30, 'parts': [{'assessments': [a], 'weight': PARTS[k]} for k, a in assessments['parts'].items()], 'missing': 'zero'},
        {'name': '作业', 'weight': 20, 'assessments': [assessments['hw']], 'grade_map': GRADES, 'missing': 'zero'},
        {'name': '问答', 'weight': 10, 'assessments': ['问答'], 'aggregate': 'count', 'full_count': FULL_COUNT, 'missing': 'zero'},
        {'name': '期中', 'weight': 15, 'assessments': ['期中'], 'missing': 'zero'},
        {'name': '期末', 'weight': 25, 'assessments': ['期末'], 'missing': 'zero'}],
        'status_policy': {'缺考': 'zero', '缓考': 'pending'}, 'rounding': {'digits': 2}}
