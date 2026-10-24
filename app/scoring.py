"""Course total rules: the model drafts a structured rule from the teacher's words, the teacher confirms it, this module computes."""
from __future__ import annotations

import csv
import io
import re
from collections import Counter, defaultdict
from decimal import ROUND_HALF_UP, Decimal

from .grades import SOURCE_SEP, occurrence_key, safe_cell, text

AGGREGATES = {
    'mean': '取平均', 'max': '取最高', 'min': '取最低', 'last': '取最后一次',
    'drop_lowest_mean': '去掉最低后取平均', 'sum': '累加后按总满分折算', 'count': '按次数折算',
}
MISSING = {'zero': '记 0 分', 'pending': '总评待定'}
STATUS_POLICIES = {'zero': '该项记 0 分', 'pending': '总评待定', 'invalid': '总评无效', 'exempt': '免修，不计总评'}
# Statuses a record can carry. How each is scored comes only from the user's rules; one the rules do not mention leaves
# the total pending and is pointed out, never filled in with a customary default.
STATUSES = ('缺考', '缓考', '作弊', '取消资格', '免修', '未交', '待批改')
RESIT = {'separate': '补考成绩不并入总评，单独标注', 'replace': '有补考的考核以补考成绩替代初考成绩（不封顶）', 'max': '有补考的考核取初考与补考中较高的一次'}
EXAM_WORDS = ('期末', '期中', '考试')

PARSE_INSTRUCTION = '''把老师用自然语言描述的课程总评规则，翻译成结构化规则。只返回JSON对象：
{"components":[{"name":"组成项名称","assessments":["数据中的考核项目名"],"weight":权重百分数,
"aggregate":"mean|max|min|last|drop_lowest_mean|sum|count","drop_lowest":去掉最低的次数,"full_score":每次满分或累加总满分或null,"full_count":满次数或null,
"parts":[{"assessments":["数据中的分项名"],"weight":分项权重百分数}]或[],
"grade_map":{"A":90,"B":85}或null,"occurrence_weights":{"HW01":10,"HW02":20}或null,"missing":"zero|pending"}],
"status_policy":{"缺考":"zero|pending|invalid","缓考":"zero|pending|invalid","作弊":"zero|pending|invalid","取消资格":"zero|pending|invalid","免修":"exempt|pending","未交":"zero|pending","待批改":"pending|zero"}（只写老师说了怎么处理的状态）,
"resit":"separate|replace|max","scope":{"courses":["只统计的课程代码或名称"],"terms":["只统计的学期"]},
"rounding":{"digits":保留小数位},"explanation":"逐条说明你如何理解老师的规则","unclear":["需要老师确认的地方"]}
要求：
- assessments 和 parts 里的名字只能从 observed_assessments 中选择；weight 为百分数，各组成项之和应为100。
- 平台成绩（学习通、慕课/MOOC/中国大学MOOC、雨课堂等，老师叫法可能不同，按含义对应）：observed_assessments 中名为“平台名”的项是平台导出的总评，“平台名·分项”是该平台的分项。
  老师给了分项权重、或明确说按明细/分项重算时，parts 列出每个分项和权重（即使有平台总评，它只用于核对）；
  老师没给分项权重、而数据中有平台总评时，直接用总评：assessments 填 ["平台名"]，parts 留空；
  只有分项、老师又没给分项权重时，assessments 和 parts 都留空，并在 unclear 写明“某平台只有分项，需要老师给出各分项权重”。不要把平台里的“在线作业”当成老师的课堂作业。
- 老师给了等级对应的分数（如 A=90）时写 grade_map，键用大写等级；数据中是等级（observed 的 grades）而老师没给对应分数时，在 unclear 说明。
- 各次权重不同（如 HW01 占10%、HW02 占20%）用 occurrence_weights，键是次序或考核项目名；各次等权就不填。
- “每次有效回答/出勤 X 分、最高 Y 分”用 count，full_count 填 Y/X。
- aggregate 默认 "mean"；只有老师说各次分数相加（累加）时才用 "sum"。
- missing 是“没有记录”的处理：老师说没有记录按 0 分（如“没回答过的学生此项为0”“未提交按0”）时填 "zero"；
  老师没说明、或说“缺项不按0”“没有记录要确认/待定”时填 "pending"：该生此项待定，系统会列出来请老师补录或说明，按原权重、不会把剩余权重重新归一，不要再写进 unclear。
- resit：老师说补考成绩替代/代替初考用 "replace"，取初考补考较高者用 "max"，没提或说补考单独记录用 "separate"。
- scope：老师说“只统计某课程/某学期”“别的课程或学期不计入”时，把课程代码或名称、学期写进 scope；没说就留空数组。
- 平台分项名称要和 observed_assessments 中“平台名·分项”逐一对应；老师对平台的叫法可能不同（超星=学习通，在线开放课/MOOC=慕课），按含义对应。
- 列名或说明里的单位换算（完成率0-1乘100、带百分号、满分20/50）系统已按列名换成百分制，不需要写进规则。
- status_policy 只写老师明确说了怎么处理的状态，不要按常见做法补上没提到的状态（系统会按待定处理并请老师说明）；老师没说保留几位小数时 digits 填 2。
unclear 只写老师真正需要看的，最多5条，最重要的在前：
1. 老师原话中这个规则表表达不了的要求（如“酌情加分”“低于某分按某分记”这类条件或人工判断），引用原话并说明需要老师在结果上单独处理，不要为它编造组成项或计算方式；
2. 会改变本数据中某些学生结果的不确定之处：observed_statuses 中出现、但老师没说怎么处理的状态；observed_assessments 中出现、但老师没提到的考核项目；只有分项却没给权重的平台；
不要列出数据中没有出现的状态的默认处理，也不要列出不影响结果的措辞问题。
下面这些系统已经自动检查并逐条请老师决定，不要写进 unclear：重复导出去重、同一记录的冲突、空白/负分/超满分/满分无效/非数字的成绩、
学号与姓名不符、不在名单的学号、同名无法确定、规则外的等级、平台总评与分项重算不一致、没有记录的项（会列出来请老师确认或补录）。'''


REVISE_INSTRUCTION = '''老师对当前的总评规则提出了修改意见（change）。在 current_rule 的基础上只改老师要求改的地方，其余保持不变，返回修改后的完整规则，格式与 current_rule 相同：
{"components":[...],"status_policy":{...},"rounding":{"digits":n},"explanation":"一句话说明改了什么","unclear":["修改意见里说不清、需要老师再确认的地方，没有就空数组"]}
要求：assessments、parts 中的名字只能从 observed_assessments 中选择；平台只有分项时，老师给的分项权重写进该组成项的 parts；
改了某项权重而老师没说其他项怎么变、导致合计不是100时，不要擅自调整其他项，在 unclear 中说明合计变成了多少；
老师的要求这个规则表表达不了时（如个别学生加分），不要编造，在 unclear 中说明需要在结果上单独处理。'''


def observed(rows):
    """Summarise the assessments present in merged records, so the model only refers to real names."""
    found = defaultdict(lambda: {'records': 0, 'occurrences': set(), 'students': set(), 'max_scores': set(), 'marks': 0, 'grades': set(), 'files': set()})
    for r in rows:
        item = found[r['assessment']]
        item['records'] += 1
        item['students'].add(r['student_id'])
        if r['occurrence']:
            item['occurrences'].add(r['occurrence'])
        if r.get('max_score'):
            item['max_scores'].add(r['max_score'])
        if r.get('grade'):
            item['grades'].add(r['grade'])
        item['marks'] += bool(r.get('mark'))
        item['files'].update(s['file'] for s in r.get('sources') or [r.get('source') or {}] if s.get('file'))
    return [{'assessment': name, 'records': v['records'], 'students': len(v['students']),
             'occurrences': sorted(v['occurrences'], key=occurrence_key)[:30], 'max_scores': sorted(v['max_scores']),
             'mark_records': v['marks'], 'grades': sorted(v['grades']), 'files': sorted(v['files'])} for name, v in sorted(found.items())]


def skeleton(rows):
    """Rule draft used when no model is available: one component per observed assessment, weights left to the teacher."""
    return normalize({'components': [{'name': o['assessment'], 'assessments': [o['assessment']], 'weight': 0,
                                      'aggregate': 'count' if o['mark_records'] == o['records'] else 'mean'} for o in observed(rows)],
                      'explanation': '未使用模型：已按数据中的考核项目列出组成项，请填写权重与计算方式。', 'unclear': ['各组成项的权重']})


def number(value, default=None):
    try:
        value = float(value)
        return value if value == value and abs(value) != float('inf') else default
    except (TypeError, ValueError):
        return default


def names_of(value):
    if isinstance(value, str):
        value = re.split(r'[,，、;；]\s*', value)
    return [text(x) for x in value or [] if text(x)][:20]


def normalize(rule):
    """Coerce a model or form draft into the rule shape; unknown keys and values are dropped, not trusted."""
    components = []
    for c in rule.get('components') or []:
        if not isinstance(c, dict):
            continue
        names = names_of(c.get('assessments'))
        name = text(c.get('name')) or '、'.join(names)
        aggregate = c.get('aggregate') if c.get('aggregate') in AGGREGATES else 'mean'
        parts = [{'assessments': names_of(p.get('assessments')), 'weight': number(p.get('weight'), 0)}
                 for p in c.get('parts') or [] if isinstance(p, dict) and names_of(p.get('assessments'))]
        grades = c.get('grade_map') if isinstance(c.get('grade_map'), dict) else {}
        weights = c.get('occurrence_weights') if isinstance(c.get('occurrence_weights'), dict) else {}
        if aggregate == 'sum' and (parts or grades or weights):
            aggregate = 'mean'  # weighted parts, grade tables and per-occurrence weights define the calculation themselves
        in_parts = {a for p in parts for a in p['assessments']}
        names = [a for a in names if a not in in_parts]  # listed again next to their weights: the same items, counted once
        components.append({
            'name': name[:40], 'assessments': names, 'weight': number(c.get('weight'), 0), 'aggregate': aggregate,
            'drop_lowest': int(number(c.get('drop_lowest'), 1 if aggregate == 'drop_lowest_mean' else 0) or 0),
            'full_score': number(c.get('full_score')), 'full_count': number(c.get('full_count')),
            'parts': parts,
            'grade_map': {text(k).upper(): number(v) for k, v in grades.items() if text(k) and number(v) is not None},
            'occurrence_weights': {text(k): number(v) for k, v in weights.items() if text(k) and number(v) is not None},
            # No record waits for the teacher unless the rules say it scores 0; it is never filled in with a guess.
            'missing': c.get('missing') if c.get('missing') in MISSING else 'pending',
        })
    policy = rule.get('status_policy') if isinstance(rule.get('status_policy'), dict) else {}
    given = (rule.get('rounding') or {}).get('digits') if isinstance(rule.get('rounding'), dict) else None
    digits = int(number(given, 2) if given is not None else 2)
    scope = rule.get('scope') if isinstance(rule.get('scope'), dict) else {}
    return {'components': components,
            'status_policy': {k: policy[k] for k in STATUSES if policy.get(k) in STATUS_POLICIES},
            'resit': rule.get('resit') if rule.get('resit') in RESIT else 'separate',
            'scope': {'courses': names_of(scope.get('courses')), 'terms': names_of(scope.get('terms'))},
            'rounding': {'digits': max(0, min(digits, 4))},
            'explanation': text(rule.get('explanation'))[:2000],
            'unclear': [text(x)[:300] for x in rule.get('unclear') or [] if text(x)][:20],
            'source_text': text(rule.get('source_text'))[:2000]}


def used_assessments(component):
    return component['assessments'] + [a for p in component['parts'] for a in p['assessments']]


def sub_items(source, present):
    return sorted(a for a in present if a.startswith(source + SOURCE_SEP))


def check(rule, rows):
    """Return (errors, warnings). Errors block computation; warnings are shown to the teacher.

    These checks are deterministic: they are what makes the system ask for platform sub-item weights or a grade table
    instead of letting a guess through."""
    errors, warnings = [], []
    present = {o['assessment'] for o in observed(rows)}
    graded = {r['assessment'] for r in rows if r.get('grade')}
    if not rule['components']:
        errors.append('至少需要一个组成项。')
    total = sum(c['weight'] for c in rule['components'])
    if abs(total - 100) > 0.01:
        errors.append(f'各组成项权重之和为 {total:g}%，应为 100%。')
    claimed = defaultdict(list)
    for c in rule['components']:
        used = used_assessments(c)
        if c['weight'] < 0:
            errors.append(f'“{c["name"]}”的权重不能为负数。')
        subs = sub_items(c['name'], present) or [a for n in c['assessments'] for a in sub_items(n, present)]
        if not used or (not c['parts'] and any(a not in present and sub_items(a, present) for a in c['assessments'])):
            if subs:
                parts = '、'.join(a.split(SOURCE_SEP, 1)[1] for a in subs)
                errors.append(f'“{c["name"]}”只有分项数据（{parts}），没有平台算好的总评。请告诉我各分项的权重，比如“{c["name"]}：'
                              + '、'.join(f'{a.split(SOURCE_SEP, 1)[1]}{w}%' for a, w in zip(subs[:3], (20, 40, 40))) + '……”。')
            elif not used:
                errors.append(f'“{c["name"]}”没有对应任何考核项目。')
        if c['parts'] and abs(sum(p['weight'] for p in c['parts']) - 100) > 0.01:
            errors.append(f'“{c["name"]}”各分项权重之和为 {sum(p["weight"] for p in c["parts"]):g}%，应为 100%。')
        if c['aggregate'] == 'count' and not c['parts'] and not (c['full_count'] or 0) > 0:
            errors.append(f'“{c["name"]}”按次数折算，需要填写满分所需次数。')
        if c['aggregate'] == 'sum' and not (c['full_score'] or 0) > 0:
            errors.append(f'“{c["name"]}”累加计分，需要填写累加后的总满分。')
        letters = sorted({r['grade'] for r in rows if r.get('grade') and r['assessment'] in used})
        if letters and not c['grade_map']:
            errors.append(f'“{c["name"]}”的成绩是等级（{"、".join(letters)}），请给出每个等级对应的分数，比如“A=90，B=85，C=80”。')
        for name in used:
            claimed[name].append(c['name'])
            if name not in present and not sub_items(name, present):
                warnings.append(f'“{c["name"]}”引用的“{name}”在数据中不存在，该项所有学生都按没有记录处理。')
    unstated = sorted({r['status'] for r in rows if r.get('status')} - set(rule['status_policy']))
    if unstated:
        warnings.append(f'数据中有“{"、".join(unstated)}”记录，规则没说怎么处理，相关学生总评暂时待定。如需按 0 分或其他方式处理，请在下面用一句话说明。')
    for name, owners in claimed.items():
        if len(owners) > 1:
            errors.append(f'“{name}”同时计入了 {"、".join(owners)}，会被重复计分。')
    for name in sorted(present - claimed.keys()):
        source = name.split(SOURCE_SEP, 1)[0]
        if source in claimed or (SOURCE_SEP not in name and sub_items(name, claimed.keys())):
            continue  # a platform's sub-items when its own total is used, or the total kept only for checking
        warnings.append(f'数据中的“{name}”没有计入任何组成项，不影响总评。')
    return errors, warnings


def rounded(value, digits):
    return float(Decimal(str(value)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP))


def percent(record, component):
    if record.get('mark'):
        return None
    if record.get('grade'):
        return component['grade_map'].get(record['grade'])  # a grade outside the table is reported, never guessed
    limit = record.get('max_score') or (component['full_score'] if component['aggregate'] != 'sum' else None) or 100
    return min(record.get('value', record['score']) / limit * 100, 100)


def weight_key(record, weights=None):
    """Per-occurrence weights are keyed 'HW01' or '1'; the name may be in either the occurrence or the assessment."""
    if weights and record['occurrence'] not in weights and record['assessment'] in weights:
        return record['assessment']
    return record['occurrence'] or record['assessment']


def course_key(record):
    return record['course_id'] or record['course_name']


def scope_rows(rule, rows):
    """(rows counted, rows left out, why). The teacher's “只统计 SYN101 2026秋”, or when the teacher said nothing and
    one course and term hold at least 80% of the records, the stray rest (another course, an old term) is left out —
    and listed on the confirmation page, never dropped silently."""
    courses, terms = rule.get('scope', {}).get('courses') or [], rule.get('scope', {}).get('terms') or []
    if not courses and not terms and rows:
        top_course, n_course = Counter(course_key(r) for r in rows).most_common(1)[0]
        top_term, n_term = Counter(r['term'] for r in rows).most_common(1)[0]
        courses = [top_course] if n_course < len(rows) and n_course >= .8 * len(rows) else []
        terms = [top_term] if n_term < len(rows) and n_term >= .8 * len(rows) else []
    # A record whose course or term was only assumed (the Word homework list has no course column) is never left out for it.
    assumed = lambda r, i: bool((r.get('assumed') or [False, False])[i])
    keep = lambda r: (not courses or assumed(r, 0) or r['course_id'] in courses or r['course_name'] in courses) \
        and (not terms or assumed(r, 1) or r['term'] in terms)
    inside = [r for r in rows if keep(r)]
    return inside, [r for r in rows if not keep(r)], '、'.join(courses + terms)


def aggregate(component, records):
    """Return (percent 0-100 or None, explanation)."""
    method = component['aggregate']
    ordered = sorted(records, key=lambda r: occurrence_key(r['occurrence']))
    if method == 'count':
        n = len(records)
        return min(n / component['full_count'] * 100, 100), f'{n} 次 / 满分需 {component["full_count"]:g} 次'
    if method == 'sum':
        raw = sum(v for v in (r.get('value', r.get('score')) for r in records if not r.get('mark')) if v is not None)
        return min(raw / component['full_score'] * 100, 100), f'累计 {raw:g} / 总满分 {component["full_score"]:g}'
    values = [(r, percent(r, component)) for r in ordered]
    values = [(r, v) for r, v in values if v is not None]
    if not values:
        return None, '没有可计分的记录'
    scores = [v for _, v in values]
    weights = component.get('occurrence_weights') or {}
    if weights:
        pairs = [(v, weights.get(weight_key(r, weights))) for r, v in values if weights.get(weight_key(r, weights)) is not None]
        if pairs:
            total = sum(w for _, w in pairs)
            return sum(v * w for v, w in pairs) / total, '按各次权重加权：' + '、'.join(f'{weight_key(r, weights)}×{weights[weight_key(r, weights)]:g}%' for r, _ in values if weight_key(r, weights) in weights)
    if method == 'max':
        return max(scores), '取最高'
    if method == 'min':
        return min(scores), '取最低'
    if method == 'last':
        return scores[-1], f'取最后一次（{values[-1][0]["occurrence"] or "末条"}）'
    if method == 'drop_lowest_mean':
        drop = component['drop_lowest']
        if len(scores) > drop:
            kept = sorted(scores)[drop:]
            return sum(kept) / len(kept), f'{len(scores)} 次去掉最低 {drop} 次后平均'
        return sum(scores) / len(scores), f'只有 {len(scores)} 次，不足以去掉最低 {drop} 次，直接平均'
    return sum(scores) / len(scores), f'{len(scores)} 次平均'


def single(c, mine, held, course_key, rule):
    """Value of one component (or one platform sub-item) for one student: (percent or None, how, notes, zero reasons, pending)."""
    scored = [r for r in mine if not r['status']]
    zeroed = [r for r in mine if r['status'] and rule['status_policy'].get(r['status']) == 'zero']
    notes, zeros = [], []
    if not mine:
        if c['missing'] == 'zero':
            fill = [] if c['aggregate'] == 'count' else [{'assessment': a, 'occurrence': ''} for a in c['assessments']]
            zeros.append({'text': f'{c["name"]}没有记录', 'fill': fill})
            return 0.0, '没有记录，记 0 分', [f'“{c["name"]}”没有记录'], zeros, False
        fill = [] if c['aggregate'] == 'count' else [{'assessment': a, 'occurrence': ''} for a in c['assessments']]
        zeros.append({'text': f'{c["name"]}没有记录，总评待定', 'fill': fill, 'pending': True})
        return None, '没有记录，总评待定', [f'“{c["name"]}”没有记录'], zeros, True
    if zeroed and not scored:
        why = '、'.join(sorted({r['status'] for r in zeroed}))
        zeros.append({'text': f'{c["name"]}：{why}', 'fill': []})
        return 0.0, f'{why}，按规则记 0 分', notes, zeros, False
    # A status that scores zero takes part as a zero-score occurrence (never as an attendance count).
    extra = [] if c['aggregate'] == 'count' else [{**r, 'value': 0.0, 'score': 0.0, 'mark': False, 'grade': ''} for r in zeroed]
    gaps = [] if c['aggregate'] in ('count', 'sum') else [
        (name, occ) for name in c['assessments'] for occ in sorted(held[(course_key, name)], key=occurrence_key)
        if occ not in {r['occurrence'] for r in mine if r['assessment'] == name}]
    gap_text = '、'.join(f'{n}第{o}次' if o.isdigit() else f'{n} {o}' if o else n for n, o in gaps)
    if gaps and c['missing'] == 'pending':
        zeros.append({'text': f'{c["name"]}：{gap_text} 没有记录，总评待定', 'fill': [{'assessment': n, 'occurrence': o} for n, o in gaps], 'pending': True})
        return None, f'缺少 {gap_text}，总评待定', [f'“{c["name"]}”缺少 {gap_text}'], zeros, True
    extra += [{'value': 0.0, 'score': 0.0, 'mark': False, 'grade': '', 'max_score': None, 'occurrence': o, 'assessment': n, 'status': ''} for n, o in gaps]
    value, how = aggregate(c, scored + extra)
    if zeroed and extra:
        how += f'；其中 {len(zeroed)} 次因“{"、".join(sorted({r["status"] for r in zeroed}))}”按 0 分计'
        zeros.append({'text': f'{c["name"]}：{"、".join(sorted({r["status"] for r in zeroed}))} 按 0 分计', 'fill': []})
    if gaps:
        how += f'；缺少 {gap_text}，按 0 分计'
        notes.append(f'“{c["name"]}”缺少 {gap_text}，已按 0 分计')
        zeros.append({'text': f'{c["name"]}：{gap_text} 没有记录，按 0 分计', 'fill': [{'assessment': n, 'occurrence': o} for n, o in gaps]})
    unknown = sorted({r['grade'] for r in scored if r.get('grade') and r['grade'] not in c['grade_map']})
    if unknown:
        # Leaving the D out would quietly re-weight the other assignments; the item waits for the teacher instead.
        notes.append(f'“{c["name"]}”有规则外的等级 {"、".join(unknown)}，该项待定')
        return None, f'有规则外的等级 {"、".join(unknown)}，待老师确认', notes, zeros, True
    if value is None:
        return None, how, notes, zeros, True
    if value == 0 and not zeros:
        zeros.append({'text': f'{c["name"]}：成绩为 0', 'fill': []})
    return rounded(value, 2), how, notes, zeros, False


def apply_resits(rule, first, resits):
    """(records counted, resits still listed apart, notes). With “补考替代初考” the retake of an assessment takes the place
    of every first-attempt record of it (a 缺考 included); with “取较高” it does so only when it scores higher."""
    if rule.get('resit', 'separate') == 'separate' or not resits:
        return first, resits, []
    notes, kept = [], []
    for name in sorted({r['assessment'] for r in resits}):
        again = [r for r in resits if r['assessment'] == name]
        before = [r for r in first if r['assessment'] == name]
        usable = [r for r in again if not r['status'] and r.get('score') is not None]
        if rule['resit'] == 'max' and usable and before:
            old = max((r['score'] for r in before if not r['status'] and r.get('score') is not None), default=-1)
            if max(r['score'] for r in usable) <= old:
                kept += again
                notes.append(f'{name}补考 {max(r["score"] for r in usable):g} 不高于初考，按初考计')
                continue
        if not usable and not any(r['status'] for r in again):
            kept += again
            continue
        first = [r for r in first if r['assessment'] != name] + [{**r, 'attempt': '初考', 'resit_used': True} for r in again]
        shown = '、'.join(r['status'] or f'{r["score"]:g}' for r in again)
        notes.append(f'{name}按补考 {shown} 计（{RESIT[rule["resit"]]}）')
    return first, kept, notes


def touches(component, assessment):
    """Whether a record of `assessment` feeds this component (a platform's row feeds it through any of its sub-items)."""
    used = used_assessments(component) + [component['name']]
    return assessment in used or assessment.split(SOURCE_SEP)[0] in {u.split(SOURCE_SEP)[0] for u in used}


def compute(rule, rows, roster=None, overrides=None, waiting=()):
    """Apply a confirmed rule. Only first-attempt records count; resit records are listed separately as the school requires them marked.

    Platform sub-items are combined first (each value rounded to 2 decimals), then the course weights apply. `overrides`
    holds values the teacher changed after seeing the result: {'学号::组成项': {'value': 88, 'note': ...}}. `waiting` lists
    (学号, 考核项目) pairs of records still waiting for a decision on the confirmation page; those items show as pending."""
    digits, overrides = rule['rounding']['digits'], overrides or {}
    rows, outside, _ = scope_rows(rule, rows)
    people = {}
    for r in roster or []:
        people[r['student_id']] = {'name': r['student_name'], 'courses': defaultdict(list)}
    course_names = set()
    for r in rows:
        person = people.setdefault(r['student_id'], {'name': r['student_name'], 'courses': defaultdict(list)})
        person['name'] = person['name'] or r['student_name']
        course = (r['course_id'] or r['course_name'], r['course_name'], r['term'])
        course_names.add(course)
        person['courses'][course].append(r)
    if not course_names:
        return {'totals': [], 'summary': {}}
    # Occurrences the class actually had, so a student's blank quiz is not silently left out of an average.
    held = defaultdict(set)
    for r in rows:
        if r['attempt'] != '补考' and not r.get('mark'):
            held[(r['course_id'] or r['course_name'], r['assessment'])].add(r['occurrence'])
    totals = []
    for sid, person in sorted(people.items()):
        courses = person['courses'] or {next(iter(sorted(course_names))): []}
        for (course_key, course_name, term), records in courses.items():
            first = [r for r in records if r['attempt'] != '补考']
            resits = [r for r in records if r['attempt'] == '补考']
            first, resits, resit_notes = apply_resits(rule, first, resits)
            statuses = sorted({r['status'] for r in first if r['status']})
            outcome, notes, parts, total, zeros, mismatches = 'ok', resit_notes, [], Decimal(0), [], []
            for status in statuses:
                policy = rule['status_policy'].get(status, 'pending')
                if policy in ('invalid', 'exempt', 'pending'):
                    outcome = {'invalid': 'invalid', 'exempt': 'exempt', 'pending': 'pending'}[policy] if outcome == 'ok' else outcome
                    notes.append(f'存在“{status}”记录：{STATUS_POLICIES[policy]}')
            for c in rule['components']:
                if c['parts']:
                    values, hows, pending = [], [], False
                    for p in c['parts']:
                        sub = {**c, 'name': '、'.join(p['assessments']), 'assessments': p['assessments'], 'parts': []}
                        v, how, n, z, wait = single(sub, [r for r in first if r['assessment'] in p['assessments']], held, course_key, rule)
                        notes += n
                        zeros += [{**x, 'text': f'{c["name"]} · {x["text"].split(SOURCE_SEP)[-1]}'} for x in z]
                        pending = pending or wait
                        values.append((v, p['weight']))
                        hows.append(f'{sub["name"].split(SOURCE_SEP)[-1]} {"—" if v is None else f"{v:g}"}×{p["weight"]:g}%')
                    value = None if pending else rounded(sum(v * w for v, w in values) / sum(w for _, w in values), 2)
                    how = '分项加权：' + '，'.join(hows)
                    exported = [r for r in first if r['assessment'] == c['name'] or r['assessment'] in {a.split(SOURCE_SEP)[0] for p in c['parts'] for a in p['assessments']}]
                    exported = [r for r in exported if not r['status'] and r.get('score') is not None]
                    if value is not None and exported and abs(exported[0]['score'] - value) > 0.051:
                        mismatches.append(f'{c["name"]}：平台导出 {exported[0]["score"]:g}，按分项重算 {value:g}')
                        how += f'；平台导出的总评是 {exported[0]["score"]:g}，与重算不一致，按重算值计'
                else:
                    value, how, n, z, pending = single(c, [r for r in first if r['assessment'] in c['assessments']], held, course_key, rule)
                    notes += n
                    zeros += z
                asked = sorted({a for s, a in waiting if s == sid and touches(c, a)})
                if asked:
                    # An undecided record (whose answer is this? which of two scores?) may change this item: it waits.
                    value, pending = None, True
                    how = f'有待你确认的记录（{"、".join(a.split(SOURCE_SEP)[-1] for a in asked)}），确认后再算'
                    zeros = [x for x in zeros if not x['text'].startswith(c['name'])]
                key = f'{sid}::{c["name"]}'
                if key in overrides:
                    old = value
                    value = number(overrides[key].get('value'))
                    how = f'已手动改为 {value:g}（原为 {"—" if old is None else old}）' + (f'：{overrides[key]["note"]}' if overrides[key].get('note') else '')
                    pending = value is None
                    zeros = [x for x in zeros if not x['text'].startswith(c['name'])]
                if pending and outcome == 'ok':
                    outcome = 'pending'
                weighted = None if value is None else value * c['weight'] / 100
                if weighted is not None:
                    total += Decimal(str(value)) * Decimal(str(c['weight'])) / 100  # exact: 60.965 must not round to 60.96
                mine = [r for r in first if r['assessment'] in used_assessments(c)]
                parts.append({'name': c['name'], 'weight': c['weight'], 'percent': None if value is None else round(value, 2),
                              'weighted': None if weighted is None else round(weighted, 2), 'how': how, 'overridden': key in overrides,
                              'records': [{'id': r['id'], 'assessment': r['assessment'], 'occurrence': r['occurrence'],
                                           'shown': r['status'] or ('√' if r.get('mark') else r['grade'] if r.get('grade') else f"{r['score']:g}"),
                                           'sources': r['sources']} for r in mine]})
            claimed = {a for c in rule['components'] for a in used_assessments(c)}
            unused = sorted({r['assessment'] for r in first if r['assessment'] not in claimed and r['assessment'].split(SOURCE_SEP)[0] not in claimed
                             and not any(a.startswith(r['assessment'] + SOURCE_SEP) for a in claimed)})
            totals.append({'student_id': sid, 'student_name': person['name'], 'course': course_name or course_key, 'term': term,
                           'components': parts, 'outcome': outcome,
                           'total': rounded(total, digits) if outcome == 'ok' else None,
                           'notes': notes + ([f'未计入总评的记录：{"、".join(unused)}'] if unused else []),
                           'zeros': zeros, 'mismatches': mismatches,
                           'resits': [{'assessment': r['assessment'], 'shown': r['status'] or (r['grade'] if r.get('grade') else f"{r['score']:g}")} for r in resits]})
    counts = defaultdict(int)
    for t in totals:
        counts[t['outcome']] += 1
    return {'totals': totals, 'outside': outside, 'summary': {'students': len(totals), 'computed': counts['ok'], 'pending': counts['pending'],
                                          'invalid': counts['invalid'], 'exempt': counts['exempt'],
                                          'zeros': sum(1 for t in totals for z in t['zeros'] if not z.get('pending')), 'mismatches': sum(len(t['mismatches']) for t in totals)}}


OUTCOMES = {'ok': '', 'pending': '待定', 'invalid': '无效', 'exempt': '免修'}


def describe(rule, statuses=None):
    """The rule in plain sentences. With `statuses` (those present in the data) only relevant status handling is listed."""
    lines = []
    for c in rule['components']:
        if c['parts']:
            how = '由分项加权：' + '、'.join(f'{"、".join(a.split(SOURCE_SEP)[-1] for a in p["assessments"])} {p["weight"]:g}%' for p in c['parts'])
        elif c['occurrence_weights']:
            how = '各次加权：' + '、'.join(f'{k} {v:g}%' for k, v in c['occurrence_weights'].items())
        else:
            how = {'drop_lowest_mean': f'去掉最低 {c["drop_lowest"]} 次后取平均',
                   'count': f'按次数折算，{c["full_count"]:g} 次得满分' if c['full_count'] else '按次数折算',
                   'sum': f'各次相加，按总满分 {c["full_score"]:g} 折算' if c['full_score'] else '各次相加',
                   'mean': '各次等权取平均'}.get(c['aggregate'], AGGREGATES[c['aggregate']])
        if c['grade_map']:
            how += '；等级换算 ' + '、'.join(f'{k}={v:g}' for k, v in c['grade_map'].items())
        source = '、'.join(c['assessments'])
        source = f'（数据中的“{source}”）' if source and source != c['name'] else ''
        lines.append(f'{c["name"]}占 {c["weight"]:g}%{source}，{how}；缺少记录时{MISSING[c["missing"]]}。')
    shown = [k for k in rule['status_policy'] if statuses is None or k in statuses]
    if shown:
        lines.append('；'.join(f'{k}的{"总评" if rule["status_policy"][k] != "zero" else "该项"}' + {'zero': '记 0 分', 'pending': '待定', 'invalid': '无效', 'exempt': '不计算（免修）'}[rule['status_policy'][k]] for k in shown) + '。')
    unstated = sorted(set(statuses or ()) - set(rule['status_policy']))
    if unstated:
        lines.append(f'数据中有“{"、".join(unstated)}”记录，规则没说怎么处理，这些学生的总评暂时待定。')
    scope = rule.get('scope') or {}
    if scope.get('courses') or scope.get('terms'):
        lines.append('只统计 ' + '、'.join(scope.get('courses', []) + scope.get('terms', [])) + ' 的记录，其他课程或学期的记录不计入（会列出来）。')
    lines.append(f'总评保留 {rule["rounding"]["digits"]} 位小数，四舍五入；{RESIT[rule.get("resit", "separate")]}。')
    return lines


def totals_csv(rule, computed):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    names = [c['name'] for c in rule['components']]
    writer.writerow(['学号', '姓名', '课程', '学期', *[f'{n}（{c["weight"]:g}%）' for n, c in zip(names, rule['components'])], '总评', '状态', '说明', '补考成绩'])
    for t in computed['totals']:
        parts = ['' if p['percent'] is None else p['percent'] for p in t['components']]
        writer.writerow([safe_cell(x) for x in [t['student_id'], t['student_name'], t['course'], t['term'], *parts,
                                                 '' if t['total'] is None else t['total'], OUTCOMES[t['outcome']] or '已计算',
                                                 '；'.join(t['notes']), '；'.join(f"{r['assessment']} {r['shown']}" for r in t['resits'])]])
    return stream.getvalue().encode('utf-8-sig')
