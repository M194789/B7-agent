"""Changing a task after it started: add or remove materials, change the rules, revoke a decision, go back one version, stop.

Every change makes a new version of the task. A version runs on its own checkpoint thread from the start of the flow,
seeded with what the earlier version already settled (decisions, the confirmed rule, answers, fills). Nothing is read
twice: photos, tables and rule readings come from the content cache, so a new version costs model calls only for new
or changed content. Each carried decision is checked against the problem it answered and dropped when that problem
changed; the change report lists what was kept, what lapsed and whose totals moved.

The superseded version is kept as a snapshot (files, request, status, result) so “撤回到上一版” restores it exactly.
"""
from __future__ import annotations

import re
import threading
import unicodedata
import uuid

from . import store

_stopping, _lock = set(), threading.Lock()


class Stopped(Exception):
    """The user asked to stop; raised between steps, never in the middle of writing a result."""


def request_stop(task_id):
    with _lock:
        _stopping.add(task_id)


def clear_stop(task_id):
    with _lock:
        _stopping.discard(task_id)


def stopping(task_id):
    with _lock:
        return task_id in _stopping


def check(task_id):
    if stopping(task_id):
        raise Stopped('已按你的要求中止')


def same_text(a, b):
    """Rules that differ only in spacing or line breaks (a text box sends Windows line ends) are the same rules."""
    norm = lambda x: re.sub(r'\s+', '', unicodedata.normalize('NFKC', x or ''))
    return norm(a) == norm(b)


def number(task):
    return task['request'].get('version') or 1


def thread(task):
    return task['request'].get('thread') or task['id']


def config(task, limit=None):
    value = {'configurable': {'thread_id': thread(task)}}
    if limit:
        value['recursion_limit'] = limit
    return value


def seed(task):
    """What the earlier version settled, handed to the first step of this version."""
    return store.cache_get('seed:' + thread(task)) or {}


def start(task, files, request, carried, title):
    """Keep the current version as a snapshot and make the next one current; the caller queues it."""
    n = number(task)
    store.version_put(task['id'], n, {k: task[k] for k in ('files', 'request', 'status', 'step', 'result', 'error')})
    thread_id = f'{task["id"]}@{n + 1}.{uuid.uuid4().hex[:6]}'  # a version made again after an undo starts clean
    store.cache_put('seed:' + thread_id, carried)
    request = {**request, 'version': n + 1, 'thread': thread_id}
    store.update(task['id'], files=files, request=request, status='queued', step=f'第 {n + 1} 版：等待处理', error=None,
                 result={'kind': task['kind'], 'version': n + 1})
    store.event(task['id'], f'version:{n + 1}', f'第 {n + 1} 版：{title}', mode='human')
    clear_stop(task['id'])
    return n + 1


def undo(task):
    """Back to the previous version exactly as it was left (its checkpoint thread is still there)."""
    n = number(task)
    previous = store.version_get(task['id'], n - 1) if n > 1 else None
    if not previous:
        raise ValueError('这已经是第一版，没有可以撤回的修改。')
    store.update(task['id'], **previous)
    store.version_drop(task['id'], n - 1)
    store.event(task['id'], f'undo:{n}', f'撤回第 {n} 版的修改，回到第 {n - 1} 版', mode='human')
    return previous


def result_state(task):
    """Which of the three the result is: still being processed by the system, processed but with things the user has
    to decide, or confirmed by the user. A confirmed result with undecided totals says so; it is not a complete result."""
    status, result = task['status'], task['result']
    pending = result.get('pending') or {}
    if status in ('queued', 'running'):
        return {'code': 'processing', 'text': '系统正在处理'}
    if status == 'waiting_review':
        if pending.get('stage') != 'confirm':
            return {'code': 'needs_review', 'text': '处理前需要你说明几处' if pending.get('stage') == 'understand' else '需要你指明学生或成绩列'}
        open_items = len(pending.get('issues') or []) + len(pending.get('errors') or []) + sum(1 for j in pending.get('judge') or [] if not j.get('decided'))
        waiting = sum(1 for t in pending.get('preview') or [] if t.get('outcome') == 'pending' or t.get('pending'))
        if open_items:
            return {'code': 'needs_review', 'text': f'系统已处理完，仍有 {open_items} 项待你确认', 'open': open_items, 'waiting': waiting}
        return {'code': 'system_done', 'text': '系统已处理完，没有待决定的问题，等你核对后确认', 'open': 0, 'waiting': waiting}
    if status == 'completed':
        summary = result.get('totals_summary') or {}
        waiting = (summary.get('pending') or 0) + (summary.get('invalid') or 0)
        if waiting:
            return {'code': 'confirmed_partial', 'text': f'你已确认；其中 {waiting} 人的总评仍未确定，不是正式成绩', 'waiting': waiting}
        return {'code': 'confirmed', 'text': '你已确认，结果完整'}
    if status == 'stopped':
        return {'code': 'stopped', 'text': '已中止'}
    return {'code': status, 'text': task['step']}
