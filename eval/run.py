"""Run the evaluation cases through the real workflows with the configured model and score every model step.

A scripted reviewer answers each review stage from the answer key, the way a careful teacher or evaluator would, so later
stages are measured on correct inputs and earlier mistakes are counted where they happen. Results go to eval/results/.

Usage (model settings from B7_LLM_BASE_URL / B7_LLM_MODEL / B7_LLM_API_KEY):
  .venv/Scripts/python.exe -X utf8 -m eval.run [--repeat 3] [--cases A1,B1]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import time
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path

os.environ['B7_DATA_DIR'] = tempfile.mkdtemp(prefix='b7-eval-')  # never touch the user's workspace

from app import appraisal, appraisal_flow, documents, grades, model, scoring, store, workflow  # noqa: E402
from . import cases as C  # noqa: E402

RESULTS = C.ROOT / 'eval' / 'results'
TICKS = {'✓': '√', '✔': '√', 'v': '√', 'V': '√'}


def norm(value):
    value = re.sub(r'\s+', '', grades.text(value))
    return TICKS.get(value, value)


def occurrence(value):
    value = grades.text(value)
    date = re.fullmatch(r'(\d{1,2})\s*[-/.月]\s*(\d{1,2})\s*日?', value)
    return f'{int(date.group(1))}/{int(date.group(2))}' if date else value


def progress(state):
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / 'progress.json').write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')


def new_task(case, kind, request, files):
    tid = uuid.uuid4().hex
    directory = store.DATA / 'tasks' / tid / 'input'
    directory.mkdir(parents=True)
    stored = []
    for index, (path, name, role) in enumerate(files):
        target = directory / f'{index}{Path(path).suffix.lower()}'
        shutil.copyfile(path, target)
        stored.append({'name': name, 'path': str(target), 'role': role})
    store.create_task(f'评测 {case["id"]}', kind, request, stored, tid)
    with store.connect() as db:
        db.execute('DELETE FROM mappings')  # every run must exercise the model, not a mapping saved by an earlier run
    return tid


def model_seconds(tid):
    return round(sum((e.get('elapsed_ms') or 0) for e in store.get_task(tid)['events'] if e.get('mode') == 'model') / 1000, 1)


# ------------------------------------------------------------------ grades
def truth_tables(case):
    tables = []
    for f in case['files']:
        if f.get('role'):
            continue
        source = case['dir'] / (f.get('truth') or f['name'])
        if source.suffix.lower() == '.docx':
            tables += workflow.read_word_tables(source, f['name'])
        else:
            tables += grades.read_table(source, f['name'])
    return tables


def roster_of(case):
    item = next((f for f in case['files'] if f.get('role') == 'roster'), None)
    return grades.read_roster(case['dir'] / item['name'], item['name']) if item else []


def spec_matches(spec, issue):
    if spec['type'] != issue['type']:
        return False
    records = [issue['record']] if issue['type'] == 'row' else issue['records']
    return any(spec['name'] in r['student_name'] or spec['name'] == r['student_id'] for r in records)


def decide(spec, issue):
    if issue['type'] == 'conflict':
        chosen = next((r for r in issue['records'] if r.get('value') == spec['select'] or r.get('score') == spec['select']), None)
        return {'action': 'select', 'record_id': chosen['id']} if chosen else {'action': 'exclude', 'note': '评测：找不到预定的选项'}
    return dict(spec['decision'])


def expected(case):
    """Records and totals from the clean inputs, the confirmed mappings, the planted decisions and the confirmed rule."""
    tables, roster = truth_tables(case), roster_of(case)
    mappings = {t['id']: next(f['mapping'] for f in case['files'] if f['name'] == t['name']) for t in tables}
    decisions = {}
    for attempt in range(7):
        result = grades.merge(tables, mappings, case['request'], decisions, roster)
        if not result['issues']:
            break
        if attempt == 6:
            raise ValueError(f'{case["id"]} 的预定决定无法消除疑点：{[i["title"] for i in result["issues"]]}')
        for issue in result['issues']:
            spec = next((s for s in case['decisions'] if spec_matches(s, issue)), None)
            if spec is None:
                raise ValueError(f'{case["id"]} 的答案缺少对疑点的决定：{issue["title"]} · {issue.get("description")}')
            decisions[issue['id']] = decide(spec, issue)
    rule = scoring.normalize(case['rule'])
    errors, _ = scoring.check(rule, result['rows'])
    if errors:
        raise ValueError(f'{case["id"]} 的标准规则有误：{errors}')
    return result, scoring.compute(rule, result['rows'], roster), rule


def record_key(r):
    return (r['student_id'], r['assessment'], occurrence(r['occurrence']), r['attempt'])


def record_value(r):
    return r['status'] or ('√' if r.get('mark') else round(r.get('value', r['score']), 2))


def compare_records(got, want):
    a = {record_key(r): record_value(r) for r in got}
    b = {record_key(r): record_value(r) for r in want}
    right = sum(1 for k, v in b.items() if a.get(k) == v)
    return {'expected': len(b), 'correct': right, 'missing': sum(1 for k in b if k not in a), 'extra': sum(1 for k in a if k not in b),
            'wrong_value': sum(1 for k, v in b.items() if k in a and a[k] != v),
            'examples': [f'{k[0]} {k[1]} {k[2]}：应为 {b.get(k, "无")}，实际 {a.get(k, "无")}' for k in sorted(set(a) | set(b), key=str) if a.get(k) != b.get(k)][:8]}


def compare_totals(got, want):
    a = {t['student_id']: (t['outcome'], t['total']) for t in got}
    b = {t['student_id']: (t['outcome'], t['total']) for t in want}
    right = sum(1 for k, v in b.items() if a.get(k) == v)
    return {'expected': len(b), 'correct': right,
            'examples': [f'{k}：应为 {b[k][1] if b[k][0] == "ok" else scoring.OUTCOMES[b[k][0]]}，实际 {"无" if k not in a else a[k][1] if a[k][0] == "ok" else scoring.OUTCOMES[a[k][0]]}'
                         for k in b if a.get(k) != b[k]][:8]}


def ocr_score(tables, truth_path):
    """Cell-by-cell comparison with the clean CSV the picture was drawn from (by column position)."""
    want = grades.read_table(truth_path)[0]
    want_rows = [[norm(v) for v in r['values'].values()] for r in want['rows']]
    got_rows = [[norm(v) for v in r['values'].values()] for t in tables for r in t['rows']]
    cells = right = 0
    wrong = []
    for i, row in enumerate(want_rows):
        got = got_rows[i] if i < len(got_rows) else []
        for j, value in enumerate(row):
            cells += 1
            if j < len(got) and got[j] == value:
                right += 1
            elif len(wrong) < 6:
                wrong.append(f'第{i + 1}行“{want["headers"][j]}”：应为“{value}”，识别为“{got[j] if j < len(got) else "缺失"}”')
    return {'cells': cells, 'correct': right, 'rows_expected': len(want_rows), 'rows_read': len(got_rows), 'examples': wrong}


FIELDS = ('student_id', 'student_name', 'course_id', 'course_name', 'assessment', 'occurrence', 'attempt', 'score', 'max_score', 'status', 'remark')


def translate(mapping, truth_headers, headers):
    """A truth mapping refers to the clean CSV's headers; picture tables have whatever headers the model wrote."""
    if truth_headers == headers:
        return mapping
    if len(truth_headers) != len(headers):
        return None
    pos = {h: headers[i] for i, h in enumerate(truth_headers)}
    out = {k: pos[v] for k, v in mapping.items() if k in FIELDS}
    if mapping.get('item_columns'):
        out['item_columns'] = [pos[c] for c in mapping['item_columns']]
    if mapping.get('item_name'):
        out['item_name'] = mapping['item_name']
    return out


def same_mapping(got, want):
    core = lambda m: ({k: m.get(k) for k in FIELDS if m.get(k) and k != 'remark'}, sorted(m.get('item_columns') or []),
                      grades.text(m.get('item_name')) if any(not grades.split_item_header(c)[0] for c in m.get('item_columns') or []) else '')
    return core(got) == core(want)


def rule_score(draft, truth, rows):
    """Is the model's draft the rule the teacher meant? Compared per component, plus the statuses that occur in the data."""
    draft = scoring.normalize(draft)
    notes, ok = [], True
    for want in truth['components']:
        got = next((c for c in draft['components'] if set(c['assessments']) == set(want['assessments'])), None)
        if not got:
            ok = False
            notes.append(f'没有对应“{"、".join(want["assessments"])}”的组成项')
            continue
        checks = [('权重', got['weight'], want['weight']), ('计算方式', got['aggregate'], want['aggregate'])]
        if want['aggregate'] == 'drop_lowest_mean':
            checks.append(('去掉最低次数', got['drop_lowest'], want['drop_lowest']))
        if want['aggregate'] == 'count':
            checks.append(('满分次数', got['full_count'], want['full_count']))
        for label, a, b in checks:
            if a != b:
                ok = False
                notes.append(f'{want["name"]}的{label}：应为 {b}，草稿为 {a}')
    if len(draft['components']) != len(truth['components']):
        ok = False
        notes.append(f'组成项数量：应为 {len(truth["components"])}，草稿为 {len(draft["components"])}')
    for status in sorted({r['status'] for r in rows if r['status']}):
        if draft['status_policy'].get(status) != truth['status_policy'].get(status):
            ok = False
            notes.append(f'“{status}”的处理：应为 {scoring.STATUS_POLICIES[truth["status_policy"][status]]}，草稿为 {scoring.STATUS_POLICIES.get(draft["status_policy"].get(status), "无")}')
    if draft['rounding']['digits'] != truth['rounding']['digits']:
        ok = False
        notes.append(f'保留小数：应为 {truth["rounding"]["digits"]}，草稿为 {draft["rounding"]["digits"]}')
    return ok, notes, draft


def answer_issue(case, issue, truth_by_file, state):
    """The reviewer: planted problems get the planted decision; anything else is checked against the original."""
    spec = next((s for s in case['decisions'] if spec_matches(s, issue)), None)
    if spec:
        return decide(spec, issue), spec
    if issue['type'] == 'conflict':
        trusted = next((r for r in issue['records'] if r['source'].get('origin') != 'image'), issue['records'][0])
        return {'action': 'select', 'record_id': trusted['id']}, None
    record = issue['record']
    source = record['source']
    truth = truth_by_file.get(source['file'])
    if source.get('origin') == 'image' and truth:
        index = source['row'] - 2
        if not 0 <= index < len(truth['rows']):
            return {'action': 'exclude', 'note': '评测：原件中没有这一行'}, None
        row = list(truth['rows'][index]['values'].values())
        table = next(t for t in state['tables'] if t['name'] == source['file'])
        position = {h: i for i, h in enumerate(table['headers'])}
        if issue.get('scope') == 'value':
            value = row[position[source['column']]] if source['column'] in position and position[source['column']] < len(row) else ''
            return ({'action': 'correct', 'score': value} if grades.text(value) else {'action': 'exclude', 'note': '评测：原件此格为空'}), None
        mapping = truth['mapping']
        want_id = grades.text(row[truth['headers'].index(mapping['student_id'])]) if mapping.get('student_id') else ''
        if not want_id and mapping.get('student_name'):
            name = grades.name_key(row[truth['headers'].index(mapping['student_name'])])
            ids = [r['student_id'] for r in state['roster'] if grades.name_key(r['student_name']) == name]
            want_id = ids[0] if len(ids) == 1 else ''
        return ({'action': 'correct', 'student_id': want_id} if want_id else {'action': 'exclude', 'note': '评测：无法从原件确认'}), None
    return {'action': 'exclude', 'note': '评测：意外疑点'}, None


def run_grades(case):
    want, want_totals, rule = expected(case)
    roster = roster_of(case)
    files = [(case['dir'] / f['name'], f['name'], '') for f in case['files']]  # the roster is found among the uploads, as in the app
    request = {'goal': '评测', 'term': '2026秋', 'assessment': '期末', 'attempt': '初考', 'use_model': True, **case['request']}
    tid = new_task(case, 'grades', request, files)
    config = {'configurable': {'thread_id': tid}}
    out = {'case': case['id'], 'stages': {}}
    truth_by_file = {}
    for f in case['files']:
        if f.get('truth'):
            table = grades.read_table(case['dir'] / f['truth'])[0]
            truth_by_file[f['name']] = {'rows': table['rows'], 'headers': table['headers'], 'mapping': f['mapping']}
    resume, planted_hit, unexpected, rounds, fixes, targets = None, set(), [], 0, {}, {}
    started = time.perf_counter()
    while True:
        workflow.run(tid, resume)
        task = store.get_task(tid)
        if task['status'] != 'waiting_review':
            break
        rounds += 1
        if rounds > 8:
            out['error'] = '复核轮次过多，评测中止'
            break
        pending = task['result']['pending']
        state = workflow.graph.get_state(config).values
        if 'mapping' not in out['stages']:
            # Column meanings are applied automatically now; they are scored at the first pause, whatever it is.
            mapping_checks, targets = [], {}
            for f in case['files']:
                if f.get('role'):
                    continue
                mine = [t for t in state['tables'] if t['name'] == f['name']]
                if f.get('truth'):
                    out['stages'].setdefault('ocr', {})[f['name']] = ocr_score(mine, case['dir'] / f['truth'])
                for t in mine:
                    truth_headers = truth_by_file[f['name']]['headers'] if f.get('truth') else t['headers']
                    target = translate(f['mapping'], truth_headers, t['headers'])
                    proposed = state['mappings'][t['id']]
                    targets[t['id']] = target or proposed
                    mapping_checks.append({'table': t['name'] + (f' {t["sheet"]}' if t['sheet'] else ''), 'correct': bool(target) and same_mapping(proposed, target),
                                           'proposed': proposed, 'expected': target})
            out['stages']['mapping'] = {'tables': len(mapping_checks), 'correct': sum(c['correct'] for c in mapping_checks),
                                        'examples': [f'{c["table"]}：建议 {c["proposed"]}，应为 {c["expected"]}' for c in mapping_checks if not c['correct']][:4]}
            # The reviewer corrects a wrong column meaning on the confirmation page, as a teacher who looked would.
            fixes = {k: v for k, v in targets.items() if not same_mapping(state['mappings'][k], v)}
        if pending['stage'] == 'mapping':
            resume = {'mappings': {t['id']: targets.get(t['id']) or t['mapping'] for t in pending['tables']}}
            fixes = {}
            continue
        if fixes:
            resume, fixes = {'mappings': fixes, 'decisions': {}, 'rules': {k: v for k, v in rule.items() if k != 'source_text'}}, {}
            continue
        decisions = {}
        for issue in pending['issues']:
            choice, spec = answer_issue(case, issue, truth_by_file, {**state, 'roster': roster})
            decisions[issue['id']] = choice
            if spec:
                planted_hit.add(case['decisions'].index(spec))
            else:
                unexpected.append(f'{issue["title"]}（{issue.get("description", "")}）')
        if pending.get('rule') and 'rules' not in out['stages']:
            ok, notes, draft = rule_score(pending['rule'], rule, state['result']['rows'])
            if_confirmed = None
            # The rule alone is judged: its totals on the correctly resolved records (open problems are decided on the same page).
            if not scoring.check(draft, want['rows'])[0]:
                if_confirmed = compare_totals(scoring.compute(draft, want['rows'], roster)['totals'], want_totals['totals'])
            unclear = pending['rule'].get('unclear') or []
            out['stages']['rules'] = {'correct': ok, 'notes': notes, 'unclear': unclear, 'unclear_count': len(unclear), 'totals_if_confirmed': if_confirmed,
                                      'unclear_expected': case.get('expect_unclear'),
                                      'unclear_found': all(any(word in u for u in unclear for word in words) for words in case.get('expect_unclear', []))}
        resume = {'decisions': decisions, 'rules': {k: v for k, v in rule.items() if k != 'source_text'}}
    task = store.get_task(tid)
    out['status'] = task['status']
    out['error'] = out.get('error') or task.get('error')
    out['issues'] = {'planted': len(case['decisions']), 'caught': len(planted_hit), 'unexpected': len(unexpected), 'unexpected_examples': unexpected[:6]}
    if task['status'] == 'completed':
        result = task['result']
        out['records'] = compare_records(result['rows'], want['rows'])
        out['totals'] = compare_totals(result.get('totals', []), want_totals['totals'])
    out['seconds'] = round(time.perf_counter() - started, 1)
    out['model_seconds'] = model_seconds(tid)
    return out


# ------------------------------------------------------------------ appraisal
PROBE_LEVELS = ['国际级', '国家级', '省级', '市级', '校级', '核心期刊', 'CN期刊', '']


def same_number(a, b):
    return a is not None and b is not None and abs(float(a) - float(b)) < 0.01


def scheme_score(draft, truth):
    notes, correct = [], 0
    for index, want in enumerate(truth):
        got = draft[index] if index < len(draft) and (want['name'] in draft[index]['name'] or draft[index]['name'] in want['name']) else \
            next((d for d in draft if want['name'] in d['name'] or d['name'] in want['name']), None)
        if not got:
            notes.append(f'缺少指标“{want["name"]}”')
            continue
        problems = []
        if got['method'] != want['method']:
            problems.append(f'计分方式应为{appraisal.METHODS[want["method"]]}，草稿为{appraisal.METHODS[got["method"]]}')
        if not same_number(got['max'], want['max']):
            problems.append(f'满分应为 {want["max"]:g}')
        if want['method'] == 'count':
            if any(appraisal.level_points(got, level) != appraisal.level_points(want, level) for level in PROBE_LEVELS):
                problems.append(f'每项分值应为 {want["points"]}，草稿为 {got["points"]}')
            if not same_number(got['cap'] if got['cap'] is not None else got['max'], want['cap'] if want['cap'] is not None else want['max']):
                problems.append('上限不一致')
        if want['method'] == 'checklist':
            missing = [r for r in want['required'] if not any(r in g or g in r for g in got['required'])]
            if missing or len(got['required']) != len(want['required']):
                problems.append(f'必交材料应为 {want["required"]}，草稿为 {got["required"]}')
            if not same_number(got['deduct'], want['deduct']):
                problems.append(f'每缺一项扣分应为 {want["deduct"]:g}')
        if want['method'] == 'judge':
            if [(c['level'], c['score']) for c in got['criteria']] != [(c['level'], c['score']) for c in want['criteria']]:
                problems.append('评价等级或分值与方案不一致')
        if problems:
            notes.append(f'{want["name"]}：' + '；'.join(problems))
        else:
            correct += 1
    if len(draft) != len(truth):
        notes.append(f'指标数量：应为 {len(truth)}，草稿为 {len(draft)}')
    return {'indicators': len(truth), 'correct': correct, 'exact': correct == len(truth) and len(draft) == len(truth), 'examples': notes[:6]}


def truth_materials(case, indicators):
    items = []
    for name, t in case['materials'].items():
        items.append({'id': name, 'file': name, 'title': name, 'doc_type': t.get('doc_type', ''), 'event': t.get('event', ''),
                      'project': t.get('project', ''), 'level': t.get('level', ''), 'person': t['person'], 'indicator': t['indicator'],
                      'excluded': bool(t.get('excluded'))})
    return items


def item_scores(people, indicators, materials, judgements):
    return {(p, i['id']): i['score'] for p in people for i in appraisal.score_person(p, indicators, materials, judgements)['items']}


def materials_score(read, case, indicators):
    ids = {i['id']: i for i in indicators}
    truth = case['materials']
    person = indicator = level_ok = level_n = doc_ok = doc_n = 0
    wrong = []
    for m in read:
        t = truth[m['file']]
        should = t.get('read_person', t['person'])  # what can be read from the material itself
        person += m['person'] == should
        indicator += m['indicator'] == t['indicator']
        if m['person'] != should or m['indicator'] != t['indicator']:
            wrong.append(f'{m["file"]}：读为 {m["person"] or "未确定"}/{m["indicator"] or "无指标"}，应为 {should or "未确定"}/{t["indicator"]}')
        item = ids.get(t['indicator'])
        if item and item['method'] == 'count':
            level_n += 1
            level_ok += appraisal.level_points(item, m['level']) == appraisal.level_points(item, t.get('level', ''))
        if t.get('doc_type'):
            doc_n += 1
            doc_ok += bool(m['doc_type']) and (t['doc_type'] in m['doc_type'] or m['doc_type'] in t['doc_type'])
    # Same project read as one item, different projects kept apart (only among materials meant for counted items).
    counted = [m for m in read if ids.get(truth[m['file']]['indicator'], {}).get('method') == 'count']
    pairs = same = 0
    for i, a in enumerate(counted):
        for b in counted[i + 1:]:
            ta, tb = truth[a['file']], truth[b['file']]
            if ta['indicator'] != tb['indicator']:
                continue
            pairs += 1
            want_same = appraisal.event_key({**ta, 'id': a['file']}) == appraisal.event_key({**tb, 'id': b['file']})
            same += (appraisal.event_key(a) == appraisal.event_key(b)) == want_same
    flagged = {m['file'] for m in read if m['flags']}
    expected_flags = {name for name, t in truth.items() if t.get('flag')}
    return {'materials': len(read), 'person': person, 'indicator': indicator, 'level': level_ok, 'level_total': level_n,
            'doc_type': doc_ok, 'doc_type_total': doc_n, 'dedupe_pairs': pairs, 'dedupe_correct': same,
            'flags_expected': len(expected_flags), 'flags_caught': len(flagged & expected_flags), 'flags_extra': len(flagged - expected_flags),
            'flags_missed_examples': sorted(expected_flags - flagged)[:5], 'flags_extra_examples': sorted(flagged - expected_flags)[:5],
            'examples': wrong[:6]}


def quote_stats(items):
    counts = defaultdict(int)
    for q in items:
        counts[{True: 'verified', False: 'not_found', None: 'unchecked'}[q.get('verified')]] += 1
    return dict(counts)


def run_appraisal(case):
    indicators = appraisal.normalize_scheme({'indicators': case['scheme']})['indicators']
    judgements = {k: {'score': v} for k, v in case['judgements'].items()}
    want_materials = truth_materials(case, indicators)
    want_items = item_scores(case['people'], indicators, want_materials, judgements)
    want_totals = {p: appraisal.score_person(p, indicators, want_materials, judgements)['total'] for p in case['people']}
    scheme_text = ((case.get('scheme_dir') or case['dir']) / case['scheme_file']).read_text(encoding='utf-8')
    files = [(case['dir'] / name, name, 'material') for name in case['materials']]
    tid = new_task(case, 'appraisal', {'scheme_text': scheme_text, 'people': case['people'], 'use_model': True}, files)
    out = {'case': case['id'], 'stages': {}}
    resume, rounds, started = None, 0, time.perf_counter()
    while True:
        appraisal_flow.run(tid, resume)
        task = store.get_task(tid)
        if task['status'] != 'waiting_review':
            break
        rounds += 1
        if rounds > 6:
            out['error'] = '复核轮次过多，评测中止'
            break
        pending = task['result']['pending']
        if 'scheme' not in out['stages']:
            out['stages']['scheme'] = {**scheme_score(pending['scheme']['indicators'], indicators), 'unclear': len(pending.get('unclear') or [])}
            if not out['stages']['scheme']['exact']:
                # The reviewer fixes the indicators (in the app: one sentence on the confirmation page); materials are read again.
                resume = {'scheme': {'indicators': case['scheme']}}
                continue
        read = pending['materials']
        # Measured on the materials as read against the scheme that is finally used.
        out['stages']['materials'] = materials_score(read, case, indicators)
        out['stages']['materials']['quotes'] = quote_stats([q for m in read for q in m['quotes']])
        got_items = item_scores(case['people'], indicators, [{**m, 'excluded': False} for m in read], judgements)
        methods = {i['id']: i['method'] for i in indicators}
        computed = [k for k in want_items if methods[k[1]] != 'judge']
        out['stages']['materials']['computed_items_unreviewed'] = {'total': len(computed), 'correct': sum(1 for k in computed if same_number(got_items[k], want_items[k]))}
        changes, corrected = {}, 0
        for m in read:
            t = case['materials'][m['file']]
            changes[m['id']] = {'person': t['person'], 'indicator': t['indicator'], 'excluded': bool(t.get('excluded')), 'note': '评测'}
            # Like a real reviewer, the reading itself is only corrected where the system pointed at it.
            if any(f.startswith('材料类型') for f in m['flags']) and t.get('doc_type'):
                changes[m['id']]['doc_type'] = t['doc_type']
                corrected += 1
            if any(f.startswith('级别') for f in m['flags']) and t.get('level') and not t.get('flag'):
                changes[m['id']]['level'] = t['level']
                corrected += 1
        out['stages']['materials']['reviewer_corrections'] = corrected
        suggestions = {j['key']: j['suggestion'] for j in pending['judge']}
        levels = [{'key': key, 'want': want['level'], 'got': (suggestions.get(key) or {}).get('level') or '', 'debatable': bool(want.get('debatable'))}
                  for key, want in case['levels'].items()]
        quotes = [q for x in suggestions.values() if x for q in x.get('quotes') or []]
        silent = [k for k, x in suggestions.items() if k not in case['levels'] and x and x.get('score') is not None]
        out['stages']['suggestions'] = {'expected': len(levels), 'agree': sum(1 for x in levels if x['got'] == x['want']),
                                        'agree_clear': sum(1 for x in levels if x['got'] == x['want'] and not x['debatable']),
                                        'clear': sum(1 for x in levels if not x['debatable']),
                                        'details': levels, 'unwarranted': silent, 'quotes': quote_stats(quotes)}
        resume = {'scheme': {'indicators': pending['scheme']['indicators']}, 'materials': changes, 'judgements': judgements}
    task = store.get_task(tid)
    out['status'], out['error'] = task['status'], out.get('error') or task.get('error')
    if task['status'] == 'completed':
        got = {r['person']: r for r in task['result']['results']}
        pairs = [(p, i['id'], i['score'], want_items[(p, i['id'])]) for p in case['people'] for i in got[p]['items']]
        out['final_items'] = {'total': len(pairs), 'correct': sum(1 for *_, a, b in pairs if same_number(a, b)),
                              'examples': [f'{p} {i}：应为 {b}，实际 {a}' for p, i, a, b in pairs if not same_number(a, b)][:6]}
        out['totals'] = {'expected': len(case['people']), 'correct': sum(1 for p in case['people'] if same_number(got[p]['total'], want_totals[p])),
                         'want': want_totals, 'got': {p: got[p]['total'] for p in case['people']}}
    out['seconds'] = round(time.perf_counter() - started, 1)
    out['model_seconds'] = model_seconds(tid)
    return out


# ------------------------------------------------------------------ summary
def ratio(items, num, den):
    a, b = sum(x[num] for x in items), sum(x[den] for x in items)
    return {'value': a / b if b else None, 'num': a, 'den': b}


def summarize(runs):
    """Aggregate per metric over all runs (and cases), keeping each run's own value to show how stable it is."""
    by = defaultdict(list)
    for run in runs:
        by[run['case']].append(run)
    grade = [r for r in runs if r['case'].startswith('A')]
    appr = [r for r in runs if r['case'].startswith('B')]
    m = {}
    ocr = [v for r in grade for v in r['stages'].get('ocr', {}).values()]
    if ocr:
        m['ocr_cells'] = ratio(ocr, 'correct', 'cells')
    maps = [r['stages']['mapping'] for r in grade if 'mapping' in r['stages']]
    if maps:
        m['mapping_tables'] = ratio(maps, 'correct', 'tables')
    rules = [r['stages']['rules'] for r in grade if 'rules' in r['stages']]
    if rules:
        m['rules_exact'] = {'value': sum(x['correct'] for x in rules) / len(rules), 'num': sum(x['correct'] for x in rules), 'den': len(rules)}
        m['rules_unclear_per_draft'] = {'value': sum(x['unclear_count'] for x in rules) / len(rules), 'num': sum(x['unclear_count'] for x in rules), 'den': len(rules)}
        flagged = [x for x in rules if x.get('unclear_expected')]
        if flagged:
            m['rules_unsupported_pointed_out'] = {'value': sum(x['unclear_found'] for x in flagged) / len(flagged), 'num': sum(x['unclear_found'] for x in flagged), 'den': len(flagged)}
        confirmed = [x['totals_if_confirmed'] for x in rules if x['totals_if_confirmed']]
        if confirmed:
            m['totals_if_rule_confirmed'] = ratio(confirmed, 'correct', 'expected')
    issues = [r['issues'] for r in grade]
    if issues:
        m['planted_caught'] = ratio(issues, 'caught', 'planted')
        m['unexpected_issues_per_run'] = {'value': sum(x['unexpected'] for x in issues) / len(issues), 'num': sum(x['unexpected'] for x in issues), 'den': len(issues)}
    for key, num, den, name in [('records', 'correct', 'expected', 'final_records'), ('totals', 'correct', 'expected', 'final_totals')]:
        items = [r[key] for r in grade if key in r]
        if items:
            m[name] = ratio(items, num, den)
    schemes = [r['stages']['scheme'] for r in appr if 'scheme' in r['stages']]
    if schemes:
        m['scheme_indicators'] = ratio(schemes, 'correct', 'indicators')
    mats = [r['stages']['materials'] for r in appr if 'materials' in r['stages']]
    if mats:
        m['material_person'] = ratio(mats, 'person', 'materials')
        m['material_indicator'] = ratio(mats, 'indicator', 'materials')
        m['material_level'] = ratio(mats, 'level', 'level_total')
        m['material_doc_type'] = ratio(mats, 'doc_type', 'doc_type_total')
        m['dedupe_pairs'] = ratio(mats, 'dedupe_correct', 'dedupe_pairs')
        m['flags_caught'] = ratio(mats, 'flags_caught', 'flags_expected')
        m['flags_extra_per_run'] = {'value': sum(x['flags_extra'] for x in mats) / len(mats), 'num': sum(x['flags_extra'] for x in mats), 'den': len(mats)}
        m['computed_items_unreviewed'] = ratio([x['computed_items_unreviewed'] for x in mats], 'correct', 'total')
        quotes = defaultdict(int)
        for x in mats:
            for k, v in x['quotes'].items():
                quotes[k] += v
        checked = quotes['verified'] + quotes['not_found']
        m['quotes_found_in_text'] = {'value': quotes['verified'] / checked if checked else None, 'num': quotes['verified'], 'den': checked}
    sugg = [r['stages']['suggestions'] for r in appr if 'suggestions' in r['stages']]
    if sugg:
        m['suggestions_agree_clear'] = ratio(sugg, 'agree_clear', 'clear')
        m['suggestions_agree_all'] = ratio(sugg, 'agree', 'expected')
    for key, name in [('final_items', 'appraisal_final_items'), ('totals', 'appraisal_totals')]:
        items = [r[key] for r in appr if key in r]
        if items:
            m[name] = ratio(items, 'correct', 'total' if key == 'final_items' else 'expected')
    m['failed_runs'] = {'value': sum(r['status'] != 'completed' for r in runs), 'num': sum(r['status'] != 'completed' for r in runs), 'den': len(runs)}
    return m


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repeat', type=int, default=1)
    parser.add_argument('--cases', default='')
    args = parser.parse_args()
    if not model.status()['configured']:
        sys.exit('请先设置 B7_LLM_BASE_URL、B7_LLM_MODEL、B7_LLM_API_KEY。')
    store.init()
    chosen = [C.CASE_INDEX[c] for c in args.cases.split(',') if c] if args.cases else list(C.CASE_INDEX.values())
    started_at = datetime.now().astimezone().isoformat(timespec='seconds')
    runs, total = [], len(chosen) * args.repeat
    for repeat in range(args.repeat):
        for case in chosen:
            progress({'running': True, 'done': len(runs), 'total': total, 'current': f'{case["id"]} 第{repeat + 1}轮', 'started_at': started_at})
            print(f'[{len(runs) + 1}/{total}] {case["id"]} 第{repeat + 1}轮 …', flush=True)
            try:
                result = run_grades(case) if case['id'].startswith('A') else run_appraisal(case)
            except Exception as error:  # a broken run is reported, not hidden
                result = {'case': case['id'], 'status': 'error', 'error': f'{type(error).__name__}: {error}', 'stages': {}, 'seconds': 0,
                          'issues': {'planted': 0, 'caught': 0, 'unexpected': 0}}
            result['repeat'] = repeat + 1
            runs.append(result)
            print('   ', result['status'], result.get('error') or '', f'{result.get("seconds", 0)}s', flush=True)
    report = {'started_at': started_at, 'finished_at': datetime.now().astimezone().isoformat(timespec='seconds'),
              'model': model.status()['model'], 'base_url': model.status()['base_url'], 'repeat': args.repeat,
              'cases': [{k: c[k] for k in ('id', 'title', 'level', 'about')} for c in chosen],
              'metrics': summarize(runs), 'per_case': {c['id']: summarize([r for r in runs if r['case'] == c['id']]) for c in chosen},
              'per_repeat': [summarize([r for r in runs if r['repeat'] == k + 1]) for k in range(args.repeat)],
              'runs': runs, 'synthetic': True}
    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    (RESULTS / f'eval_{stamp}.json').write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    (RESULTS / 'latest.json').write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    progress({'running': False, 'done': len(runs), 'total': total, 'finished_at': report['finished_at'], 'file': f'eval_{stamp}.json'})
    print(json.dumps(report['metrics'], ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
