"""Evaluator workflow for work appraisal: scheme, materials and suggested levels are prepared automatically, then confirmed on one page."""
from __future__ import annotations

import html
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from . import appraisal, dedupe, documents, export_xlsx, grades, habits, model, store, versions
from .workflow import checkpointer, trace

TEXT_SUFFIXES = ('.txt', '.md')
TABLE_SUFFIXES = ('.csv', '.tsv', '.xlsx', '.xls')
EXCERPT = 4000


class AppraisalState(TypedDict, total=False):
    task_id: str
    request: dict
    files: list
    scheme: dict
    people: list
    rescan: bool
    materials: list
    suggestions: dict
    judgements: dict
    result: dict
    relations: list  # which materials are the same achievement, with the evidence
    relation_changes: dict  # the evaluator's corrections, keyed by the two file names
    material_changes: dict  # file name -> what the evaluator corrected, applied again when a version reads it anew
    judged_with: dict  # person::indicator -> the materials the score was given on
    baseline: dict
    changes: dict


def read_text(path):
    raw = Path(path).read_bytes()
    for encoding in ('utf-8-sig', 'gb18030', 'utf-16'):
        try:
            return raw.decode(encoding)
        except UnicodeError:
            continue
    raise ValueError('无法识别文本编码。')


def material_content(path, name):
    """(text, images, notes) for one material. The text is handed to the model and kept for quote checks;
    photos, scanned PDF pages and pictures inside Word files are sent as images."""
    suffix = Path(path).suffix.lower()
    if suffix in TEXT_SUFFIXES:
        return read_text(path)[:EXCERPT], [], []
    if suffix in TABLE_SUFFIXES:
        lines = []
        for table in grades.read_table(path, name):
            lines.append(' | '.join(table['headers']))
            lines += [' | '.join(r['values'].values()) for r in table['rows'][:40]]
            if len(table['rows']) > 40:
                lines.append(f'……共 {len(table["rows"])} 行')
        return '\n'.join(lines)[:EXCERPT], [], []
    doc = documents.load(path, render='scanned', max_images=4)
    notes = list(doc['notes'])
    if len(doc['text']) > EXCERPT:
        notes.append(f'文字较长，只读取了前 {EXCERPT} 字')
    return doc['text'][:EXCERPT], [i['data'] for i in doc['images']], notes

def draft_scheme(state: AppraisalState):
    tid, request = state['task_id'], state['request']
    if state.get('scheme'):
        return {'people': state.get('people') or request.get('people') or []}  # carried from the previous version
    template = request.get('template') or {}
    if template.get('scheme'):
        store.event(tid, 'scheme_template', f'沿用方案模板“{template["name"]}”', detail={'template': template['name']})
        return {'scheme': appraisal.normalize_scheme({**template['scheme'], 'source_text': request['scheme_text']}), 'people': request.get('people') or []}
    response = trace(tid, 'parse_scheme', '模型把考核方案拆成指标', lambda: model.ask_json(appraisal.SCHEME_INSTRUCTION, {'scheme': request['scheme_text']}), 'model')
    return {'scheme': appraisal.normalize_scheme({**response, 'source_text': request['scheme_text']}), 'people': request.get('people') or []}


def read_one(index, file, indicators, people, task_id=None):
    """One model call per material. Filename prefixes such as '王敏_' are only a hint, never a decision."""
    name, path = file['name'], file['path']
    if task_id:
        versions.check(task_id)
    hint = name.split('_')[0] if '_' in name else ''
    base = {'id': f'M{index + 1}', 'file': name, 'index': index}
    failed = {'person': hint if hint in people else '', 'indicator': '', 'summary': '', 'quotes': [], 'doc_type': '', 'title': name,
              'event': '', 'project': '', 'level': '', 'date': '', 'origin': 'text'}
    try:
        excerpt, images, notes = material_content(path, name)
    except ValueError as error:
        return {**base, **failed, 'excerpt': '', 'notes': [], 'uncertain': ['文件无法读取：' + str(error)[:120]]}
    base.update(origin='mixed' if images and excerpt else 'image' if images else 'text', notes=notes)
    payload = {'file_name': name, 'people': people, 'filename_hint': hint if hint in people else '',
               'indicators': [{'id': i['id'], 'group': i['group'], 'name': i['name'], 'method': appraisal.METHODS[i['method']],
                               'required': i['required'], 'unit': i['unit'], 'evidence_hint': i['evidence_hint'],
                               'conditions': i.get('conditions') or []} for i in indicators],
               'text': excerpt}
    try:
        response = model.ask_json(appraisal.MATERIAL_INSTRUCTION, payload, images=images or None)
    except ValueError as error:
        return {**base, **failed, 'origin': base['origin'], 'excerpt': excerpt, 'uncertain': ['模型未能读取：' + str(error)[:120]]}
    links = [x for x in response.get('indicators') or [] if isinstance(x, dict) and x.get('id') in {i['id'] for i in indicators}]
    person = grades.text(response.get('person'))
    uncertain = [grades.text(x)[:200] for x in response.get('uncertain') or [] if grades.text(x)][:5]
    if not person and hint in people:
        person = hint
        uncertain.append('材料内容未写明归属，按文件名判断为' + hint)
    quotes = [grades.text(q)[:300] for q in response.get('quotes') or [] if grades.text(q)][:3]
    known = {(i['id'], c) for i in indicators for c in i.get('conditions') or []}
    conditions = [{'id': c['id'], 'condition': grades.text(c['condition']), 'met': c.get('met') if c.get('met') in (True, False) else None,
                   'evidence': grades.text(c.get('evidence'))[:200]}
                  for c in response.get('conditions') or [] if isinstance(c, dict) and (c.get('id'), grades.text(c.get('condition'))) in known]
    linked = links[0]['id'] if links else ''
    # A condition of the linked indicator the model did not answer is not taken as met.
    answered = {(c['id'], c['condition']) for c in conditions}
    conditions += [{'id': i, 'condition': c, 'met': None, 'evidence': ''} for i, c in sorted(known) if i == linked and (i, c) not in answered]
    return {**base, 'person': person, 'doc_type': grades.text(response.get('doc_type'))[:40], 'title': grades.text(response.get('title'))[:120] or name,
            'event': grades.text(response.get('event'))[:120], 'project': grades.text(response.get('project'))[:120],
            'level': grades.text(response.get('level'))[:30], 'date': grades.text(response.get('date'))[:30],
            'role': grades.text(response.get('role'))[:60], 'conditions': conditions,
            **{k: grades.text(response.get(k))[:120] for k in ('cert_no', 'contest', 'edition', 'award', 'issuer', 'advisor')},
            'students': [grades.text(x)[:20] for x in response.get('students') or [] if grades.text(x)][:20] if isinstance(response.get('students'), list) else [],
            'indicator': links[0]['id'] if links else '', 'reason': grades.text(links[0].get('reason'))[:300] if links else '',
            'also': [x['id'] for x in links[1:]], 'summary': grades.text(response.get('summary'))[:200],
            'quotes': quote_checks(quotes, excerpt, bool(images)),
            'uncertain': uncertain, 'excerpt': excerpt}


def quote_checks(quotes, excerpt, has_images):
    """Quotes are checked against the text layer; one that is not there may come from a picture, which cannot be checked."""
    if not excerpt:
        return [{'text': q, 'verified': None} for q in quotes]
    checked = appraisal.verify_quotes(quotes, [excerpt])
    return [{**q, 'verified': None} if has_images and q['verified'] is False else q for q in checked]


def read_materials(state):
    tid = state['task_id']
    indicators, people = state['scheme']['indicators'], state.get('people') or []
    if not model.status()['configured']:
        raise ValueError('读取证明材料需要先在“模型设置”中连接支持图片的模型。')

    def run():
        with ThreadPoolExecutor(max_workers=4) as pool:
            items = list(pool.map(lambda pair: read_one(pair[0], pair[1], indicators, people, tid), enumerate(state['files'])))
        return {'items': items, '_trace': f'读取 {len(items)} 份材料'}
    materials = trace(tid, 'read_materials', f'模型逐份阅读 {len(state["files"])} 份证明材料', run, 'model')['items']
    if not people:
        # No list was given: the people are whoever the materials name, most frequent first; the page lets the user check them.
        people = [p for p, _ in Counter(m['person'] for m in materials if m['person']).most_common()][:50]
        store.event(tid, 'people', '从材料中识别被考核人：' + '、'.join(people), detail={'people': people})
    for m in materials:
        apply_change(m, (state.get('material_changes') or {}).get(m['file']) or {})  # corrections made in an earlier version
    return {'materials': materials, 'people': people}


def apply_change(m, change):
    if 'person' in change:
        m['person'] = grades.text(change['person'])
    if 'indicator' in change:
        m['indicator'] = grades.text(change['indicator'])
    for field, limit in (('doc_type', 40), ('level', 30), ('project', 120)):
        if field in change and grades.text(change[field]) != m.get(field):
            m.setdefault('corrected', []).append(field)  # kept in the audit: what the evaluator changed in the model's reading
            m[field] = grades.text(change[field])[:limit]
    if 'excluded' in change:
        m['excluded'] = bool(change['excluded'])
        m['note'] = grades.text(change.get('note'))[:300]
    if 'accepted' in change:
        m['accepted'] = bool(change['accepted']) and not m.get('excluded')  # the evaluator checked what the material did not show
        if m['accepted']:
            m['note'] = grades.text(change.get('note'))[:300]


def undecided(pending, changes):
    """Materials still needing proof once the evaluator's changes are applied: these must be checked or left out."""
    materials = [dict(m) for m in pending['materials']]
    for m in materials:
        apply_change(m, changes.get(m['id']) or {})
    flagged = appraisal.material_flags(materials, pending['people'], pending['scheme']['indicators'], pending['scheme'])
    return [m for m in flagged if m['status'] == 'needs_proof']


def linked_files(materials, key):
    person, indicator = key.split('::', 1)
    return sorted(m['file'] for m in materials if m['person'] == person and m['indicator'] == indicator and not m.get('excluded'))


def relate(state):
    tid = state['task_id']
    found = trace(tid, 'relate', '判断哪些材料是同一成果', lambda: {'items': dedupe.relate(state['materials'], state['scheme']['indicators']),
                                                                   '_trace': '按证书编号、比赛、作品与获奖等级核对'}, 'model')['items']
    return {'relations': found}


def relations_of(state):
    return dedupe.effective(state.get('relations') or [], state.get('relation_changes'))


def public(materials):
    return [{k: v for k, v in m.items() if k != 'excerpt'} for m in materials]


def suggest(state):
    """Suggested levels only for judge items whose criteria the evaluator supplied."""
    tid, people = state['task_id'], state['people']
    targets = [i for i in state['scheme']['indicators'] if i['method'] == 'judge' and i['criteria']]
    if not targets:
        return {'suggestions': {}}
    jobs = []
    for person in people:
        for item in targets:
            linked = [m for m in state['materials'] if m.get('person') == person and m.get('indicator') == item['id'] and not m.get('excluded')]
            jobs.append((person, item, linked))

    def ask(job):
        person, item, linked = job
        if not linked:
            return f'{person}::{item["id"]}', {'level': '', 'score': None, 'reason': '没有对应材料，系统不给建议，请直接评价。', 'quotes': []}
        sources = [m['excerpt'] for m in linked] + [q['text'] for m in linked for q in m['quotes']] + [m['summary'] for m in linked]
        response = model.ask_json(appraisal.JUDGE_INSTRUCTION, {
            'indicator': {'name': item['name'], 'max': item['max'], 'criteria': item['criteria']},
            'materials': [{'file': m['file'], 'doc_type': m['doc_type'], 'summary': m['summary'], 'quotes': [q['text'] for q in m['quotes']],
                           'text': m['excerpt'][:1500]} for m in linked]})
        level = grades.text(response.get('level'))
        match = next((c for c in item['criteria'] if c['level'] == level), None)
        return f'{person}::{item["id"]}', {'level': level if match else '', 'score': match['score'] if match else None,
                                           'reason': grades.text(response.get('reason'))[:800], 'missing': grades.text(response.get('missing'))[:300],
                                           'quotes': appraisal.verify_quotes(response.get('quotes'), sources)}

    def run():
        with ThreadPoolExecutor(max_workers=4) as pool:
            return {'items': dict(pool.map(ask, jobs)), '_trace': f'{len(jobs)} 项建议'}
    try:
        suggestions = trace(tid, 'suggest_levels', '模型按方案中的评价标准给出建议等级', run, 'model')['items']
    except ValueError:
        suggestions = {}
    return {'suggestions': suggestions}


def results_of(state, judgements=None, materials=None):
    scheme = state['scheme']
    judgements = state.get('judgements', {}) if judgements is None else judgements
    relations = relations_of(state) if 'relations' in state else None
    materials = appraisal.material_flags([dict(m) for m in materials or state['materials']], state['people'], scheme['indicators'], scheme, relations)
    return [appraisal.score_person(p, scheme['indicators'], materials, judgements, state.get('suggestions'), scheme.get('allow_multi'), relations)
            for p in state['people']]


def scheme_view(scheme):
    errors, warnings = appraisal.check_scheme(scheme)
    warnings = [w for w in warnings if '没有评价标准' not in w]  # already said in that indicator's sentence
    return {'scheme': scheme, 'scheme_lines': [appraisal.describe_indicator(i) for i in scheme['indicators']],
            'errors': errors, 'warnings': warnings, 'unclear': scheme.get('unclear', [])}


def core(scheme):
    """What decides the scores; a changed wording does not force the materials to be read again."""
    keep = ('name', 'max', 'method', 'points', 'cap', 'required', 'deduct', 'criteria')
    return [{k: i[k] for k in keep} for i in scheme['indicators']]


def confirm(state):
    """One page: how the scheme was understood, the materials that need a look, and the judged items to score."""
    tid, scheme, people = state['task_id'], state['scheme'], state['people']
    relations = relations_of(state)
    materials = appraisal.material_flags([dict(m) for m in state['materials']], people, scheme['indicators'], scheme, relations)
    judgements, judged_with, lapsed = dict(state.get('judgements', {})), state.get('judged_with') or {}, []
    names = {i['id']: i['name'] for i in scheme['indicators']}
    for key in list(judgements):
        # A score given on other materials than the ones linked now (one added, removed or moved) is asked again.
        if key in judged_with and judged_with[key] != linked_files(materials, key):
            person, indicator = key.split('::', 1)
            lapsed.append({'id': key, 'label': f'{person} 的{names.get(indicator, indicator)}：原来评 {judgements.pop(key).get("score")} 分，对应的材料变了'})
    provisional = {**{k: {'score': s['score']} for k, s in (state.get('suggestions') or {}).items() if s.get('score') is not None}, **judgements}
    judge = [{'key': f'{p}::{i["id"]}', 'person': p, 'id': i['id'], 'name': i['name'], 'max': i['max'], 'has_criteria': bool(i['criteria']),
              'suggestion': (state.get('suggestions') or {}).get(f'{p}::{i["id"]}'), 'decided': judgements.get(f'{p}::{i["id"]}'),
              'materials': [m['id'] for m in materials if m['person'] == p and m['indicator'] == i['id'] and not m.get('excluded')]}
             for p in people for i in scheme['indicators'] if i['method'] == 'judge']
    by_id = {m['id']: m for m in materials}
    indicators = {i['id']: i for i in scheme['indicators']}
    for m in materials:
        if m['status'] == 'needs_proof' and m.get('indicator') in indicators:
            m['habit'] = habits.suggest_material(m, indicators[m['indicator']])
    questions = [{**q, 'habit': habits.suggest_same_work(indicators[q['id']])} for q in dedupe.questions(scheme, relations, materials)]
    preview = results_of(state, provisional, materials)
    pending = {'stage': 'confirm', 'kind': 'appraisal', 'detected': state['request'].get('detected'), 'people': people,
               'source_text': scheme.get('source_text', ''), **scheme_view(scheme), 'materials': public(materials), 'judge': judge,
               'preview': preview, 'methods': appraisal.METHODS, 'version': state['request'].get('version') or 1,
               'relations': sorted([{**r, 'pair': [dedupe.view(by_id[r['a']]), dedupe.view(by_id[r['b']])]} for r in relations if r['a'] in by_id and r['b'] in by_id],
                                   key=lambda r: ['unsure', 'check', 'certain'].index(r.get('confidence', 'certain'))),
               'confidence_words': dedupe.CONFIDENCE,
               'questions': questions, 'relation_words': dedupe.RELATIONS, 'same_work_words': dedupe.SAME_WORK,
               'changes': change_report(state, preview, lapsed) if state.get('baseline') else None}
    store.update(tid, step='请确认', result={'kind': 'appraisal', 'pending': pending, 'scheme': scheme,
                                             'summary': {'pending': sum(1 for m in materials if m['flags']) + sum(1 for j in judge if not j['decided']),
                                                         'materials': len(materials)}})
    response = interrupt(pending)
    revised = appraisal.normalize_scheme({**(response.get('scheme') or scheme), 'source_text': scheme.get('source_text', '')})
    if core(revised) != core(scheme):
        store.event(tid, 'confirm', '指标已修改，按新指标重新整理材料', mode='human')
        return {'scheme': revised, 'rescan': True, 'judgements': {}}
    answers = {k: v for k, v in (response.get('scheme_answers') or {}).items() if v in dedupe.SAME_WORK}
    for iid, policy in answers.items():
        if iid in indicators:
            habits.remember_same_work(indicators[iid], policy, dedupe.SAME_WORK)
    for m in materials:
        change = (response.get('materials') or {}).get(m['id']) or {}
        if m['status'] == 'needs_proof' and m.get('indicator') in indicators and (change.get('accepted') or change.get('excluded')):
            habits.remember_material(m, indicators[m['indicator']], change)
    if answers:
        scheme = {**scheme, 'indicators': [{**i, 'same_work': answers.get(i['id'], i.get('same_work', ''))} for i in scheme['indicators']]}
    relation_changes = {**(state.get('relation_changes') or {}), **{k: v for k, v in (response.get('relations') or {}).items() if v in dedupe.RELATIONS}}
    changes = response.get('materials') or {}
    remembered = dict(state.get('material_changes') or {})
    for m in materials:
        change = changes.get(m['id'], {})
        apply_change(m, change)
        if change:
            remembered[m['file']] = change
    materials = appraisal.material_flags(materials, people, scheme['indicators'], scheme,
                                         dedupe.effective(state.get('relations') or [], relation_changes))
    judgements = {**judgements, **(response.get('judgements') or {})}
    judged_with = {**{k: v for k, v in judged_with.items() if k in judgements},
                   **{k: linked_files(materials, k) for k in response.get('judgements') or {}}}
    store.event(tid, 'confirm', '评分人已确认', mode='human', detail={'materials_changed': sum(1 for c in changes.values() if c), 'judged': len(response.get('judgements') or {})})
    return {'materials': materials, 'judgements': judgements, 'judged_with': judged_with, 'material_changes': remembered, 'rescan': False,
            'scheme': scheme, 'relation_changes': relation_changes}


def change_report(state, preview, lapsed):
    base = state['baseline']
    before = base.get('totals') or {}
    moved = [{'student_id': r['person'], 'student_name': '', 'before': [before[r['person']][0], 'ok'] if r['person'] in before else None,
              'after': [r['total'], 'ok']} for r in preview if r['person'] not in before or before[r['person']][0] != r['total']]
    return {**(state.get('changes') or {}), 'previous': base.get('version'), 'was_confirmed': base.get('confirmed', False),
            'lapsed': lapsed, 'totals_moved': moved, 'totals_same': len(preview) - len(moved)}


def after_confirm(state):
    if state.get('rescan'):
        return 'read_materials'
    return 'confirm' if any(r['pending'] for r in results_of(state)) else 'export'


def revise(task_id, text):
    """Change the indicators from a sentence; the page shows the new reading before anything is final."""
    task = store.get_task(task_id)
    pending = task['result']['pending']
    current = {'indicators': [{k: v for k, v in i.items() if k != 'evidence_hint'} for i in pending['scheme']['indicators']]}
    response = trace(task_id, 'revise_scheme', '按文字修改指标：' + text[:40],
                     lambda: model.ask_json(appraisal.REVISE_INSTRUCTION, {'current': current, 'change': text}), 'model', keep_status=True)
    scheme = appraisal.normalize_scheme({**response, 'source_text': pending['scheme'].get('source_text', '')})
    pending.update(scheme_view(scheme))
    pending['scheme_changed'] = True
    pending['revisions'] = pending.get('revisions', []) + [{'text': text, 'explanation': scheme['explanation'], 'at': store.now()}]
    store.update(task_id, result={**task['result'], 'pending': pending, 'scheme': scheme})
    return pending


def write_exports(tid, result):
    output = store.DATA / 'tasks' / tid / 'output'
    output.mkdir(parents=True, exist_ok=True)
    task = store.get_task(tid)
    indicators, results, materials = result['scheme']['indicators'], result['results'], {m['id']: m for m in result['materials']}
    (output / 'summary.csv').write_bytes(appraisal.summary_csv(indicators, results))
    escape = lambda x: html.escape(str(x))
    doc = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>知衡 · 考核评分报告</title><style>body{font:15px/1.7 system-ui;margin:40px;color:#173047}table{border-collapse:collapse;width:100%;margin:10px 0 26px}td,th{border:1px solid #ddd;padding:7px 9px;text-align:left;vertical-align:top;overflow-wrap:anywhere}th{background:#eef5f3}small{color:#667}.warn{color:#9a5b00}h2{margin-top:36px}</style>'
    doc += f"<h1>{escape(task['name'])}</h1><small>任务 {tid} · 导出时间 {escape(store.now())} · 计数与材料齐全度由程序计算，评价类指标由评分人评定</small>"
    doc += '<h2>考核指标（评分人确认）</h2><ul>' + ''.join(f'<li>{escape(appraisal.describe_indicator(i))}</li>' for i in indicators) + '</ul>'
    head = ''.join(f'<th>{escape(i["name"])}<br><small>{i["max"]:g}</small></th>' for i in indicators)
    body = ''.join('<tr><td>' + escape(r['person']) + '</td>' + ''.join(f'<td>{"" if i["score"] is None else i["score"]}</td>' for i in r['items'])
                   + f'<td><b>{"" if r["total"] is None else r["total"]}</b></td></tr>' for r in results)
    doc += f'<h2>汇总</h2><table><thead><tr><th>被考核人</th>{head}<th>总分</th></tr></thead><tbody>{body}</tbody></table>'
    for r in results:
        doc += f'<h2>{escape(r["person"])} · 材料与评分依据</h2><table><thead><tr><th>指标</th><th>得分</th><th>依据</th><th>材料</th></tr></thead><tbody>'
        for i in r['items']:
            files = '<br>'.join(escape(f'{materials[m]["file"]}：{materials[m]["summary"]}') for m in i['materials'])
            doc += f'<tr><td>{escape(i["group"])} / {escape(i["name"])}<br><small>满分 {i["max"]:g} · {escape(appraisal.METHODS[i["method"]])}</small></td><td>{"" if i["score"] is None else i["score"]}</td><td>{escape(i["how"])}</td><td>{files or "<span class=warn>无</span>"}</td></tr>'
        doc += '</tbody></table>'
    excluded = [m for m in result['materials'] if m.get('excluded')]
    if excluded:
        doc += '<h2>评分人排除的材料</h2><ul>' + ''.join(f'<li>{escape(m["file"])}：{escape(m.get("note") or "未填写原因")}</li>' for m in excluded) + '</ul>'
    doc += '<p><small>评价类指标的“建议等级”只供评分人参考，最终分数以评分人评定为准。完整记录见 audit.json。</small></p></html>'
    (output / 'report.html').write_text(doc, encoding='utf-8')
    audit = {'task': {'id': tid, 'name': task['name'], 'llm_used': task['llm_used']}, 'request': task['request'], 'result': result,
             'events': task['events'], 'human_decisions': task['decisions']}
    (output / 'audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')


def export(state):
    tid = state['task_id']
    results = results_of(state)
    result = {'kind': 'appraisal', 'scheme': state['scheme'], 'materials': public(state['materials']), 'results': results, 'people': state['people'],
              'relations': relations_of(state),
              'agreement': appraisal.agreement(results), 'detected': state['request'].get('detected'),
              'summary': {'people': len(results), 'materials': len(state['materials']), 'pending': 0,
                          'excluded': sum(1 for m in state['materials'] if m.get('excluded')),
                          'merged': sum(len(e['materials']) - 1 for r in results for i in r['items'] for e in i['events'] if len(e['materials']) > 1)},
              'version': state['request'].get('version') or 1, 'scheme_lines': [appraisal.describe_indicator(i) for i in state['scheme']['indicators']]}
    if state.get('baseline'):
        result['changes'] = change_report(state, results, [])
    store.update(tid, status='running', step='生成评分汇总与材料报告', result=result)
    trace(tid, 'export_results', '导出评分汇总与材料报告', lambda: write_exports(tid, result))
    store.update(tid, status='completed', step='任务已完成', result=result)
    export_xlsx.write(store.get_task(tid))
    return {'result': result}


builder = StateGraph(AppraisalState)
for name, fn in [('draft_scheme', draft_scheme), ('read_materials', read_materials), ('relate', relate), ('suggest', suggest), ('confirm', confirm), ('export', export)]:
    builder.add_node(name, fn)
builder.add_edge(START, 'draft_scheme')
builder.add_edge('draft_scheme', 'read_materials')
builder.add_edge('read_materials', 'relate')
builder.add_edge('relate', 'suggest')
builder.add_edge('suggest', 'confirm')
builder.add_conditional_edges('confirm', after_confirm)
builder.add_edge('export', END)
graph = builder.compile(checkpointer=checkpointer)

STAGE_STEPS = {'confirm': '请确认'}


def run(task_id, resume=None):
    try:
        task = store.get_task(task_id)
        if not task or task['kind'] != 'appraisal':
            return
        config = versions.config(task, 60)
        store.update(task_id, status='running', step='正在恢复任务' if resume is not None else '正在准备处理')
        if resume is not None:
            value = Command(resume=resume)
        elif graph.get_state(config).values:
            value = None
        else:
            value = {'task_id': task_id, 'request': task['request'], 'files': task['files'], 'judgements': {}, **versions.seed(task)}
        output = graph.invoke(value, config)
        if output.get('__interrupt__'):
            store.update(task_id, status='waiting_review', step='请确认')
    except versions.Stopped:
        versions.clear_stop(task_id)
        store.update(task_id, status='stopped', step='已中止：已读完的材料会保留，可以继续处理，或修改材料、方案后再处理')
        store.event(task_id, 'stopped', '已按你的要求中止', mode='human')
    except Exception as error:
        store.update(task_id, status='failed', step='处理未完成，可检查后重试', error=str(error)[:1000])
        store.event(task_id, 'failure', '任务遇到问题', status='failed', detail={'error': str(error)[:1000]})


def rules_now(task):
    return graph.get_state(versions.config(task)).values.get('request', task['request']).get('scheme_text', '')


def carry(task, rules_text=None, revoke=()):
    """What a new version starts from: the confirmed indicators (unless the scheme text changed), the evaluator's
    corrections by file name, and the scores given, each checked again against the materials it was given on."""
    values, result = graph.get_state(versions.config(task)).values, task['result']
    current = rules_now(task)
    changed = rules_text is not None and not versions.same_text(rules_text, current)
    seed = {k: values[k] for k in ('judgements', 'judged_with', 'material_changes', 'relation_changes') if values.get(k)}
    if not changed and values.get('scheme'):
        seed['scheme'] = (result.get('pending') or {}).get('scheme') or values['scheme']
        seed['people'] = values.get('people') or []
    totals = result.get('results') if task['status'] == 'completed' else (result.get('pending') or {}).get('preview')
    seed['baseline'] = {'version': versions.number(task), 'confirmed': task['status'] == 'completed',
                        'totals': {r['person']: [r['total'], 'ok'] for r in totals or []}}
    seed['changes'] = {'rules_changed': changed, 'revoked': []}
    return seed, (rules_text if changed else current), changed
