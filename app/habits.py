"""The user's own way of handling recurring problems, remembered across tasks and offered back as a preselection.

Only choices that do not depend on one particular record are kept: what a grade outside the rule's table was turned
into, whether records of a kind (a number not on the roster, a blank score) are left out or kept, which source wins
when two disagree, whether a possibly repeated record is one event, how a material that does not show a condition is
handled, how an achievement awarded twice counts. Which student a record belongs to is never a habit.

A habit only preselects. The page says it comes from earlier tasks (and how often), the user still confirms, and any
habit can be deleted; it never decides on its own. Choosing differently replaces it.
"""
from __future__ import annotations

import hashlib
import json
import re

from . import grades, store

PREFIX = 'habit:'


def enabled():
    return (store.pref_get('user') or {}).get('habits', True) is not False


def title_class(title):
    """'分数 116 超出范围（满分 100）' and '分数 108 超出范围（满分 100）' are one kind of problem."""
    return re.sub(r'“[^”]*”', '“”', re.sub(r'\d+(?:\.\d+)?', '#', grades.text(title)))


def base(assessment):
    return grades.text(assessment).split(grades.SOURCE_SEP)[0]


def source_label(source):
    """A source by what it is, not by this upload: '02_教务导出_0915.xlsx · 期末' -> '教务导出 · 期末'."""
    from .workflow import source_label as label
    return label({'name': source['file'], 'sheet': source.get('sheet') or ''}) or grades.text(source['file'])


def _key(*parts):
    return PREFIX + hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()[:20]


def issue_key(issue):
    """(key, what kind of problem it is in words) for a grades problem, or None when the choice is about one record."""
    if issue['type'] == 'row':
        r = issue['record']
        if issue['title'].startswith('等级“') and r.get('grade'):
            return _key('grade', r['grade'], base(r['assessment'])), f'{base(r["assessment"])}出现规则外的等级“{r["grade"]}”'
        return _key('row', title_class(issue['title'])), issue['title'] if '“' not in issue['title'] else title_class(issue['title']).replace('#', 'N')
    if issue['type'] == 'conflict':
        labels = sorted({source_label(r['source']) for r in issue['records']})
        if len(labels) < 2:
            return None
        return _key('conflict', base(issue['records'][0]['assessment']), labels), f'{base(issue["records"][0]["assessment"])}在 {" 与 ".join(labels)} 中不一致'
    if issue['type'] == 'duplicate':
        return _key('duplicate', base(issue['records'][0]['assessment'])), f'{base(issue["records"][0]["assessment"])}疑似同一条记录'
    return None


def remember(key, kind, choice, label):
    if not enabled():
        return
    old = store.pref_get(key) or {}
    count = old.get('count', 0) + 1 if old.get('choice') == choice else 1
    store.pref_put(key, {'key': key, 'kind': kind, 'choice': choice, 'label': label, 'count': count, 'at': store.now()})


def remember_issue(issue, choice):
    """After the user decided a problem: keep the choice when it is a habit (not a correction of one record)."""
    found = issue_key(issue)
    if not found:
        return
    key, kind = found
    action = choice.get('action')
    if issue['type'] == 'row':
        if action == 'correct' and issue['title'].startswith('等级“') and grades.text(choice.get('score')):
            remember(key, kind, {'action': 'correct', 'score': grades.text(choice['score'])}, f'改为 {grades.text(choice["score"])}')
        elif action in ('exclude', 'accept'):
            remember(key, kind, {'action': action}, '不计入' if action == 'exclude' else '原记录没错，保留')
    elif issue['type'] == 'conflict':
        if action == 'exclude':
            remember(key, kind, {'action': 'exclude'}, '都不采用')
        elif action == 'select':
            chosen = next((r for r in issue['records'] if r['id'] == choice.get('record_id')), None)
            if chosen:
                label = source_label(chosen['source'])
                remember(key, kind, {'action': 'select', 'source': label}, f'采用 {label} 的记录')
    elif issue['type'] == 'duplicate' and action in ('select', 'keep'):
        remember(key, kind, {'action': action}, '是同一次，只计一次' if action == 'select' else '不是同一次，都计入')


def suggest_issue(issue):
    """The preselection a habit gives this problem, or None."""
    if not enabled():
        return None
    found = issue_key(issue)
    habit = store.pref_get(found[0]) if found else None
    if not habit:
        return None
    choice, note = habit['choice'], f'按你以前的做法：{habit["label"]}（{habit["count"]} 次）'
    if choice['action'] == 'select' and issue['type'] == 'conflict':
        record = next((r for r in issue['records'] if source_label(r['source']) == choice.get('source')), None)
        return {'action': 'select', 'record_id': record['id'], 'label': note, 'habit': True} if record else None
    if choice['action'] == 'select' and issue['type'] == 'duplicate':
        return {'action': 'select', 'record_id': issue['options'][0]['value'], 'label': note, 'habit': True} if issue.get('options') else None
    return {**choice, 'label': note, 'habit': True}


def material_key(material, indicator):
    reason = title_class((material.get('reasons') or [''])[0]).split('（')[0]
    return _key('proof', indicator.get('name', ''), reason), f'“{indicator.get("name", "")}”的材料：{reason}'


def remember_material(material, indicator, change):
    key, kind = material_key(material, indicator)
    if change.get('excluded'):
        remember(key, kind, {'excluded': True}, '不计入')
    elif change.get('accepted'):
        remember(key, kind, {'accepted': True}, '已核实，计分')


def suggest_material(material, indicator):
    if not enabled():
        return None
    habit = store.pref_get(material_key(material, indicator)[0])
    return {**habit['choice'], 'label': f'按你以前的做法：{habit["label"]}（{habit["count"]} 次）'} if habit else None


def same_work_key(indicator):
    return _key('same_work', indicator.get('name', '')), f'“{indicator.get("name", "")}”中同一成果多次获奖或刊载'


def remember_same_work(indicator, policy, words):
    key, kind = same_work_key(indicator)
    remember(key, kind, {'policy': policy}, words.get(policy, policy))


def suggest_same_work(indicator):
    if not enabled():
        return None
    habit = store.pref_get(same_work_key(indicator)[0])
    return {'policy': habit['choice']['policy'], 'label': f'按你以前的做法：{habit["label"]}（{habit["count"]} 次）'} if habit else None


def listing():
    return sorted((h for h in store.prefs_like(PREFIX)), key=lambda h: h.get('at', ''), reverse=True)


def forget(key):
    if key.startswith(PREFIX):
        store.pref_drop(key)
