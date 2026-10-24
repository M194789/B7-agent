import io
import time

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app import grades, model, scoring, store, workflow
from app.main import app


@pytest.fixture(scope='module')
def client():
    with TestClient(app) as client:
        yield client


def wait(client, task_id):
    for _ in range(300):
        task = client.get('/api/tasks/' + task_id).json()
        if task['status'] not in ('queued', 'running'):
            return task
        time.sleep(.03)
    raise AssertionError('Task did not settle')


def answer_all(issues, pick=lambda issue: None):
    decisions = {}
    for issue in issues:
        chosen = pick(issue)
        if chosen:
            decisions[issue['id']] = chosen
        elif issue['type'] == 'conflict':
            decisions[issue['id']] = {'action': 'select', 'record_id': issue['options'][0]['value']}
        else:
            decisions[issue['id']] = issue['suggestion'] or {'action': 'exclude'}
    return decisions


def test_one_page_confirmation_then_export(client):
    task_id = client.post('/api/demo/grades', json={}).json()['id']
    task = wait(client, task_id)
    pending = task['result']['pending']
    assert task['status'] == 'waiting_review' and pending['stage'] == 'confirm' and task['kind'] == 'grades'
    assert pending['detected']['kind'] == 'grades' and pending['rule'] is None  # no rules given: integration only
    assert all('suggestion' in i for i in pending['issues']) and pending['tables']
    first = pending['issues'][0]
    partial = client.post(f'/api/tasks/{task_id}/review', json={'decisions': {first['id']: {'action': 'exclude'}}})
    assert partial.status_code == 400 and '还有' in partial.json()['detail']  # everything is decided on the one page
    assert client.post(f'/api/tasks/{task_id}/review', json={'decisions': answer_all(pending['issues'])}).status_code == 200
    task = wait(client, task_id)
    assert task['status'] == 'completed', task
    assert task['result']['tables'] and any(e['mode'] == 'human' for e in task['events'])
    for filename in ('grades.csv', 'audit.json', 'report.html'):
        exported = client.get(f'/api/tasks/{task_id}/download/{filename}')
        assert exported.status_code == 200 and exported.content
    assert client.post(f'/api/tasks/{task_id}/review', json={'decisions': {}}).status_code == 409


def test_unreadable_table_asks_only_for_the_missing_columns(client):
    content = '账号,昵称,课程,分数\n001,张同学,数学,90\n'.encode('utf-8')
    tid = client.post('/api/tasks', files={'files': ('陌生表头.csv', content, 'text/csv')}).json()['id']
    task = wait(client, tid)
    assert task['result']['pending']['stage'] == 'mapping'
    table = task['result']['pending']['tables'][0]
    response = client.post(f'/api/tasks/{tid}/review', json={'mappings': {table['id']: {'student_id': '账号', 'student_name': '昵称', 'score': '分数'}}})
    assert response.status_code == 200
    task = wait(client, tid)
    assert task['status'] == 'completed', task
    assert task['result']['rows'][0]['student_id'] == '001'


def test_clean_table_needs_no_questions_and_bad_format_is_refused(client):
    wb = Workbook()
    wb.active.append(['学号', '课程代码', '成绩'])
    wb.active.append(['0009', 'CS001', 88])
    stream = io.BytesIO()
    wb.save(stream)
    task = wait(client, client.post('/api/tasks', files={'files': ('成绩.xlsx', stream.getvalue())}).json()['id'])
    assert task['status'] == 'completed' and task['result']['rows'][0]['student_id'] == '0009'
    assert client.post('/api/tasks', files={'files': ('bad.exe', b'bad')}).status_code == 400
    assert client.post('/api/tasks', data={'rules_text': 'x'}).status_code == 400


def test_roster_is_recognised_among_the_uploads(client):
    scores = '学号,姓名,课程名称,成绩\n1,甲,数学,90\n'.encode()
    roster = '学号,姓名,班级\n1,甲,一班\n2,乙,一班\n'.encode()
    tid = client.post('/api/tasks', files=[('files', ('成绩.csv', scores)), ('files', ('班级名单.csv', roster))]).json()['id']
    task = wait(client, tid)
    assert task['status'] == 'completed'
    assert task['result']['summary']['roster_size'] == 2 and task['result']['missing_students'] == [{'student_id': '2', 'student_name': '乙'}]


def test_key_never_returned_and_model_mapping_applied_without_a_form(client, monkeypatch):
    secret = 'test-key-not-a-real-credential'
    response = client.post('/api/settings/model', json={'base_url': 'https://model.invalid', 'model': 'test-only', 'api_key': secret})
    assert secret not in response.text and response.json()['key_configured']
    assert secret not in client.get('/api/config').text
    # Test stand-in for the model adapter; no real provider call is claimed.
    monkeypatch.setattr(model, 'ask_json', lambda instruction, payload, images=None: {'mapping': {'student_id': '账号'}})
    content = '账号,课程名称,成绩\n0001,数学,90\n'.encode()
    task = wait(client, client.post('/api/tasks', files={'files': ('模型建议.csv', content)}).json()['id'])
    assert task['status'] == 'completed' and task['result']['rows'][0]['student_id'] == '0001'
    assert '「账号」是学号' in task['result']['tables'][0]['text']  # the assumption is shown, not asked
    assert secret not in str(task)
    client.delete('/api/settings/model')


def test_cross_origin_changes_rejected(client):
    assert client.post('/api/settings/model', headers={'Origin': 'https://unrelated.example'}, json={'base_url': 'https://x.example', 'model': 'x'}).status_code == 403


def test_removed_module_cannot_run_or_expose_historical_tasks(client):
    tid = store.create_task('历史文献任务', 'references', {}, [])
    assert tid not in {t['id'] for t in client.get('/api/tasks').json()}
    assert store.get_task(tid) is not None
    assert client.get('/api/tasks/' + tid).status_code == 404
    assert client.post('/api/tasks/' + tid + '/review', json={}).status_code == 404
    assert client.post('/api/tasks/' + tid + '/retry').status_code == 404
    assert client.get(f'/api/tasks/{tid}/download/audit.json').status_code == 404
    assert client.get(f'/api/tasks/{tid}/sources/0').status_code == 404
    assert client.post('/api/demo/references', json={}).status_code == 404
    assert client.get('/api/fixtures/' + '参考文献样例.txt').status_code == 404


def test_photo_upload_requires_model(client):
    response = client.post('/api/tasks', files={'files': ('记录.png', b'\x89PNG fake')})
    assert response.status_code == 400 and '模型' in response.json()['detail']


def course_model(revised):
    """Test stand-in for the model: reads the photo as its transcription and returns the confirmed rule."""
    from tests.test_course import RULE

    def ask(instruction, payload, images=None):
        if instruction == workflow.OCR_INSTRUCTION:
            rows = [r.split(',') for r in (store.ROOT / 'fixtures' / '课堂答问记录_誊录.csv').read_text(encoding='utf-8-sig').strip().splitlines()]
            return {'headers': rows[0], 'rows': rows[1:], 'uncertain': []}
        if instruction == scoring.PARSE_INSTRUCTION:
            return {**{k: v for k, v in RULE.items() if k != 'source_text'}, 'unclear': []}
        if instruction == scoring.REVISE_INSTRUCTION:
            return revised(payload)
        return {}
    return ask


def test_course_demo_rule_edit_and_totals(client, monkeypatch):
    from tests.test_course import resolve
    edits = []

    def revised(payload):
        edits.append(payload['change'])
        rule = payload['current_rule']
        weights = {'期中': 30} if len(edits) == 1 else {'期中': 20}  # first edit breaks the 100% total, second restores it
        return {**rule, 'components': [{**c, 'weight': weights.get(c['name'], c['weight'])} for c in rule['components']]}
    monkeypatch.setattr(model, 'ask_json', course_model(revised))
    monkeypatch.setattr(model, 'status', lambda: {'configured': True, 'base_url': 'test', 'model': 'test', 'key_configured': True})
    tid = client.post('/api/demo/course', json={}).json()['id']
    task = wait(client, tid)
    pending = task['result']['pending']
    assert pending['stage'] == 'confirm' and pending['detected']['kind'] == 'grades'
    assert pending['rule_lines'] and pending['preview'] and pending['roster_size'] == 11
    edited = client.post(f'/api/tasks/{tid}/revise', json={'text': '期中改成30%'}).json()
    assert edited['errors'] and not edited['preview']
    assert client.post(f'/api/tasks/{tid}/review', json={'decisions': resolve(pending['issues'])}).status_code == 400
    assert client.post(f'/api/tasks/{tid}/revise', json={'text': '期中还是20%'}).json()['errors'] == []
    assert client.post(f'/api/tasks/{tid}/review', json={'decisions': resolve(pending['issues'])}).status_code == 200
    task = wait(client, tid)
    assert task['status'] == 'completed', task
    totals = {t['student_id']: t for t in task['result']['totals']}
    assert totals['2026101']['total'] == 87 and totals['2026110']['outcome'] == 'pending'
    assert client.get(f'/api/tasks/{tid}/download/totals.csv').status_code == 200


def test_wrong_guess_can_be_switched(client, monkeypatch):
    monkeypatch.setattr(model, 'ask_json', course_model(lambda payload: payload['current_rule']))
    monkeypatch.setattr(model, 'status', lambda: {'configured': True, 'base_url': 'test', 'model': 'test', 'key_configured': True})
    tid = client.post('/api/demo/course', json={}).json()['id']
    wait(client, tid)
    created = client.post(f'/api/tasks/{tid}/switch').json()
    assert created['kind'] == 'appraisal'
    assert client.get(f'/api/tasks/{tid}').json()['status'] == 'cancelled'
    wait(client, created['id'])
