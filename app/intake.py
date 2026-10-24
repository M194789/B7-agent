"""One entrance for every user: decide from the rules text and the files whether this is a course total or a work appraisal.

Both are the same job (gather, de-duplicate, score by the user's weights, point out errors); they differ only in what a
"record" is, so the user never has to pick a module. The guess is shown on the confirmation page and can be switched.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from . import grades, model

KINDS = {'grades': '课程成绩总评', 'appraisal': '工作考核评分'}
GRADE_WORDS = ('期末', '期中', '小测', '测验', '作业', '平时', '考勤', '答问', '点名', '实验', '总评', '卷面', '学生', 'quiz')
APPRAISAL_WORDS = ('指标', '考核方案', '辅导员', '教师', '每项', '每篇', '每次计', '扣', '证书', '论文', '获奖', '工作量', '年度考核',
                   '评价标准', '材料', '优秀', '良好', '项目')
TABLES = ('.csv', '.tsv', '.xlsx', '.xls')
PROSE = ('.txt', '.md', '.docx')
CLASSIFY_INSTRUCTION = ('判断用户要做哪种工作：grades=把学生在各平台的成绩（测验、作业、考勤、期中期末等）整合后按权重算课程总评；'
                        'appraisal=按考核方案的指标给被考核人（辅导员、教师等）的证明材料计分。'
                        '返回 {"kind":"grades|appraisal","reason":"一句话依据"}。')


def classify(rules_text, names):
    """(kind, reason). Word counts in the rules plus the kind of files; the model only breaks a close call."""
    text = (rules_text or '').lower()
    grade_hits = [w for w in GRADE_WORDS if w in text]
    appraisal_hits = [w for w in APPRAISAL_WORDS if w in text]
    suffixes = Counter(Path(n).suffix.lower() for n in names)
    tables, prose = sum(suffixes[s] for s in TABLES), sum(suffixes[s] for s in PROSE)
    score = len(appraisal_hits) - len(grade_hits) + (2 if prose > tables else 0) + (1 if len(names) > 12 else 0) - (1 if tables and not prose else 0)
    if abs(score) < 2 and model.status()['configured']:
        try:
            answer = model.ask_json(CLASSIFY_INSTRUCTION, {'rules': (rules_text or '')[:1500], 'files': names[:40]})
            if answer.get('kind') in KINDS:
                return answer['kind'], grades.text(answer.get('reason'))[:120] or '由模型根据规则和文件判断'
        except ValueError:
            pass
    kind = 'appraisal' if score > 0 else 'grades'
    words = appraisal_hits if kind == 'appraisal' else grade_hits
    why = []
    if words:
        why.append('规则里有“' + '”“'.join(words[:3]) + '”')
    why.append(f'{tables} 个表格、{prose} 份文档、{len(names) - tables - prose} 份图片或 PDF')
    return kind, '；'.join(why)


ROSTER_WORDS = ('名单', '花名册', '名册', 'roster')
ROSTER_HEADERS = {grades.header_key(h) for h in ('学号', '姓名', '班级', '性别', '专业', '序号', '学院', '年级', '行政班', '备注', '学生编号', '学生姓名')}


def is_roster(table):
    """A table that only lists students (no score columns) is a course roster, wherever it was uploaded."""
    mapping = grades.propose_mapping(table['headers'])
    if mapping.get('score') or mapping.get('item_columns'):
        return False
    if not (mapping.get('student_id') and mapping.get('student_name')):
        return roster_columns(table) is not None
    named = any(w in table['name'].lower() for w in ROSTER_WORDS)
    return named or all(grades.header_key(h) in ROSTER_HEADERS for h in table['headers']) or roster_columns(table) is not None


NAME = re.compile(r'[一-鿿·]{2,6}')


def roster_columns(table):
    """(学号 column, 姓名 column) when the values show a list of students, whatever the headings say: one column of
    distinct student numbers, one of names, and otherwise only columns with a handful of values (班级, 学期, 课程).
    A score sheet repeats numbers or has many distinct values elsewhere; None then."""
    rows = table['rows']
    if len(rows) < 3:
        return None
    columns = {h: [grades.text(r['values'].get(h)) for r in rows] for h in table['headers']}
    ids = [h for h, v in columns.items() if sum(1 for x in v if grades.ID_LIKE.fullmatch(x.replace(' ', '')) and any(c.isdigit() for c in x)) >= .9 * len(v)
           and len(set(v)) == len(v)]
    names = [h for h, v in columns.items() if h not in ids and sum(1 for x in v if NAME.fullmatch(x.replace(' ', ''))) >= .9 * len(v) and len(set(v)) >= .8 * len(v)]
    if len(ids) != 1 or len(names) != 1:
        return None
    others = [v for h, v in columns.items() if h not in (ids[0], names[0])]
    if any(len({x for x in v if x}) > max(5, len(rows) // 10) for v in others):
        return None
    if any(sum(1 for x in v if grades.is_number(x) or grades.grade_of(x)) > len(v) / 2 for v in others):
        return None  # grades or scores: a score sheet with one row per student
    return ids[0], names[0]


GENERIC = {'材料', '通知', '证书', '活动', '记录', '说明', '日志', '论文', '名单', '附件', '扫描', '图片', '新建', '文档', '微信', '工作'}


def people_from_names(names):
    """'王敏_获奖证书.png' -> 王敏, when at least two files start with the same 2–4 character name."""
    found = Counter()
    for name in names:
        head = re.split(r'[_\-—\s（(]', Path(name).stem)[0]
        if re.fullmatch(r'[一-龥]{2,4}', head) and head not in GENERIC:
            found[head] += 1
    return [p for p, n in found.most_common() if n >= 2]


def people_from_text(value):
    return list(dict.fromkeys(grades.text(x) for x in re.split(r'[\n,，、;；\s]+', value or '') if grades.text(x)))[:50]
