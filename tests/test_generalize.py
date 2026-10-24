"""Generalisation without a model: the same class written in many shapes must give the totals computed independently
from the class (eval/synthetic.py). The column meanings a model would give are supplied from the generator's truth, so
everything after the semantic step is what is tested: reading formats, joining sheets, identities, dedup, statuses,
counting, platform parts, grade tables, rounding."""
import io
import time

import pytest
from fastapi.testclient import TestClient

from app import model, scoring, understand, workflow
from app.main import app
from eval import synthetic

CONFIGURED = {'configured': True, 'base_url': 'test', 'model': 'test', 'key_configured': True}
PEOPLE = synthetic.make_class()
EXPECTED = synthetic.expected(PEOPLE)


def run(monkeypatch, seed, anomalies=()):
    files, truth, names = synthetic.variant(PEOPLE, seed, anomalies)

    def ask(instruction, payload, images=None, fresh=False):
        if instruction == understand.PLAN_INSTRUCTION:
            return {'questions': []}
        if instruction == scoring.PARSE_INSTRUCTION:
            return synthetic.rule(names)
        if instruction.startswith(workflow.MAPPING_INSTRUCTION):
            return {'mapping': {k: v for k, v in truth[tuple(payload['headers'])].items() if k not in ('item_columns', 'source_name', 'events', 'item_name')},
                    'item_columns': truth[tuple(payload['headers'])].get('item_columns', []), 'events': truth[tuple(payload['headers'])].get('events', False),
                    'item_name': truth[tuple(payload['headers'])].get('item_name', ''), 'source_name': truth[tuple(payload['headers'])].get('source_name', '')}
        raise AssertionError('unexpected model call')
    monkeypatch.setattr(model, 'ask_json', ask)
    monkeypatch.setattr(model, 'status', lambda: CONFIGURED)
    with TestClient(app) as client:
        created = client.post('/api/tasks', files=[('files', (n, io.BytesIO(b))) for n, b in files],
                              data={'kind': 'grades', 'rules_text': '平台30%（视频20、测验50、任务30），作业20%（A95 B85 C75），问答10%（4次满分），期中15%，期末25%。缺考0分，缓考待定。'})
        assert created.status_code == 201, created.text
        tid = created.json()['id']
        for _ in range(400):
            task = client.get('/api/tasks/' + tid).json()
            if task['status'] not in ('queued', 'running'):
                break
            time.sleep(.03)
    assert task['status'] == 'waiting_review', (seed, task.get('error'))
    return task['result']['pending'], files


@pytest.mark.parametrize('seed', range(8))
def test_every_shape_gives_the_independently_computed_totals(monkeypatch, seed):
    pending, files = run(monkeypatch, seed)
    got = {t['student_id']: t['total'] for t in pending['preview']}
    assert not pending['issues'], [(i['title'], i['description']) for i in pending['issues']]
    assert got == EXPECTED, (sorted(n for n, _ in files), {k: (got.get(k), v) for k, v in EXPECTED.items() if got.get(k) != v})


def test_anomalies_are_flagged_and_everyone_else_is_unchanged(monkeypatch):
    pending, _ = run(monkeypatch, 3, anomalies=('out_of_range', 'unknown_id', 'conflict', 'copy'))
    titles = [i['title'] for i in pending['issues']]
    assert any('超出' in t or '范围' in t for t in titles), titles
    assert any('不在课程名单' in t for t in titles), titles
    assert any('不一致' in t for t in titles), titles
    assert len(titles) == 3, titles  # the copied register adds nothing new to decide
    assert any(i.get('also') for i in pending['issues'])  # the wrong number in the register and its copy is asked once
    got = {t['student_id']: t['total'] for t in pending['preview']}
    touched = {PEOPLE[1]['sid'], PEOPLE[2]['sid'], PEOPLE[3]['sid']}
    assert all(got[s] is None for s in touched)  # held until the teacher decides, not guessed
    assert {k: v for k, v in got.items() if k not in touched} == {k: v for k, v in EXPECTED.items() if k not in touched}
