"""The user's way with recurring problems is remembered across tasks and offered back as a preselection, never as a
decision; one-record choices are not remembered; habits can be switched off and forgotten."""
import io
import time

from fastapi.testclient import TestClient

from app import appraisal, habits, model, scoring, understand
from app.main import app
from tests.test_appraisal import fake_model

CONFIGURED = {'configured': True, 'base_url': 'test', 'model': 'test', 'key_configured': True}
ROSTER = '学号,姓名\n001,甲\n002,乙\n'
RULE = {'components': [{'name': '作业', 'assessments': ['作业'], 'weight': 50, 'grade_map': {'A': 95, 'B': 85}, 'missing': 'zero'},
                       {'name': '期末', 'assessments': ['期末'], 'weight': 50, 'missing': 'zero'}], 'rounding': {'digits': 1}}


def csv(name, body):
    return ('files', (name, io.BytesIO(body.encode('utf-8')), 'text/csv'))


def wait(client, tid):
    for _ in range(400):
        task = client.get('/api/tasks/' + tid).json()
        if task['status'] not in ('queued', 'running'):
            return task
        time.sleep(.03)
    raise AssertionError('Task did not settle')


def grades_task(client, final_extra='001,甲,期末,82\n'):
    files = [csv('名单.csv', ROSTER), csv('作业登记.csv', '学号,姓名,考核项目,成绩\n001,甲,作业,A\n002,乙,作业,D\n'),
             csv('教务导出.csv', '学号,姓名,考核项目,成绩\n001,甲,期末,80\n002,乙,期末,90\n'), csv('平台导出.csv', '学号,姓名,考核项目,成绩\n' + final_extra)]
    tid = client.post('/api/tasks', files=files, data={'kind': 'grades', 'rules_text': '作业50%（A95 B85），期末50%。'}).json()['id']
    return tid, wait(client, tid)['result']['pending']


def mocked(monkeypatch):
    def ask(instruction, payload, images=None, fresh=False):
        if instruction == understand.PLAN_INSTRUCTION:
            return {'questions': []}
        if instruction == scoring.PARSE_INSTRUCTION:
            return RULE
        return {}
    monkeypatch.setattr(model, 'ask_json', ask)
    monkeypatch.setattr(model, 'status', lambda: CONFIGURED)


def test_a_grades_habit_is_offered_next_time_and_only_preselects(monkeypatch):
    mocked(monkeypatch)
    with TestClient(app) as client:
        tid, pending = grades_task(client)
        grade = next(i for i in pending['issues'] if i['title'].startswith('等级“D”'))
        conflict = next(i for i in pending['issues'] if i['type'] == 'conflict')
        assert not grade['suggestion'] and not (conflict['suggestion'] or {}).get('habit')  # nothing learnt yet
        teacher = next(o['value'] for o in conflict['options'] if '教务导出' in o['label'])
        decisions = {grade['id']: {'action': 'correct', 'score': '70'}, conflict['id']: {'action': 'select', 'record_id': teacher}}
        assert client.post(f'/api/tasks/{tid}/review', json={'decisions': decisions}).status_code == 200
        wait(client, tid)
        kinds = {h['kind']: h for h in client.get('/api/config').json()['habits']}
        assert {h['label'] for h in kinds.values()} == {'改为 70', '采用 教务 的记录'}

        # Another task, other students' numbers, the same kinds of problem: the earlier choices come back preselected.
        _, pending = grades_task(client, final_extra='001,甲,期末,85\n')
        grade = next(i for i in pending['issues'] if i['title'].startswith('等级“D”'))
        conflict = next(i for i in pending['issues'] if i['type'] == 'conflict')
        assert grade['suggestion'] == {'action': 'correct', 'score': '70', 'label': '按你以前的做法：改为 70（1 次）', 'habit': True}
        chosen = next(r for r in conflict['records'] if r['id'] == conflict['suggestion']['record_id'])
        assert chosen['source']['file'] == '教务导出.csv' and conflict['suggestion']['habit']
        assert pending['issues'] and client.get('/api/tasks').json()[0]['status'] == 'waiting_review'  # still waits for the user


def test_a_choice_about_one_record_is_not_a_habit_and_habits_can_be_off_or_forgotten(monkeypatch):
    mocked(monkeypatch)
    issue = {'type': 'row', 'title': '学号不在课程名单中（可能录错或不属于本课程）', 'record': {'assessment': '期末', 'grade': ''}, 'id': 'row:x'}
    habits.remember_issue(issue, {'action': 'correct', 'student_id': '002'})  # “this is student 002”: about one record
    assert not habits.listing()
    habits.remember_issue(issue, {'action': 'exclude'})
    habits.remember_issue(issue, {'action': 'exclude'})
    assert habits.suggest_issue(issue)['label'] == '按你以前的做法：不计入（2 次）'
    habits.remember_issue(issue, {'action': 'accept'})  # chose differently: the habit follows
    assert habits.suggest_issue(issue)['action'] == 'accept' and habits.listing()[0]['count'] == 1
    with TestClient(app) as client:
        client.post('/api/prefs', json={'identity': '', 'flow': '', 'habits': False})
        assert habits.suggest_issue(issue) is None
        client.post('/api/prefs', json={'identity': '', 'flow': '', 'habits': True})
        client.delete('/api/habits/' + habits.listing()[0]['key'])
        assert habits.suggest_issue(issue) is None and not client.get('/api/config').json()['habits']


def test_an_appraisal_habit_preselects_a_material_needing_proof(monkeypatch):
    def reading(instruction, payload, images=None):
        found = fake_model(instruction, payload, images)
        if instruction == appraisal.MATERIAL_INSTRUCTION and '数学建模' in payload['file_name']:
            found = {**found, 'level': ''}
        return found
    monkeypatch.setattr(model, 'ask_json', reading)
    monkeypatch.setattr(model, 'status', lambda: CONFIGURED)
    judgements = {f'{p}::I1': {'score': 8} for p in ('王敏', '李强', '赵琳')}
    with TestClient(app) as client:
        tid = client.post('/api/demo/appraisal', json={}).json()['id']
        proof = next(m for m in wait(client, tid)['result']['pending']['materials'] if m['status'] == 'needs_proof')
        assert not proof.get('habit')
        change = {proof['id']: {'excluded': True, 'note': '没有级别，不计'}}
        assert client.post(f'/api/tasks/{tid}/review', json={'judgements': judgements, 'materials': change, 'scheme_answers': {'I9': 'highest'}}).status_code == 200
        wait(client, tid)
        again = client.post('/api/demo/appraisal', json={}).json()['id']
        pending = wait(client, again)['result']['pending']
        proof = next(m for m in pending['materials'] if m['status'] == 'needs_proof')
        assert proof['habit']['excluded'] and '不计入（1 次）' in proof['habit']['label']
        assert pending['questions'][0]['habit']['policy'] == 'highest'
