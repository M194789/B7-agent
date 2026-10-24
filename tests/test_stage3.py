"""Appraisal material states, subjective items left to the evaluator, preferences and rule templates."""
import time

from fastapi.testclient import TestClient

from app import appraisal, model, understand, versions
from app.main import app
from tests.test_appraisal import fake_model

SCHEME = appraisal.normalize_scheme({'indicators': [
    {'id': 'A', 'name': '学生竞赛获奖', 'max': 10, 'method': 'count', 'points': {'省级及以上': 2}, 'cap': 10, 'conditions': ['本人为指导教师']},
    {'id': 'B', 'name': '工作记录', 'max': 10, 'method': 'checklist', 'required': ['工作日志'], 'deduct': 10},
    {'id': 'C', 'name': '育人成效', 'max': 10, 'method': 'judge'},
], 'period': {'start': '2026-01-01', 'end': '2026-12-31'}})


def mat(mid, **extra):
    base = {'id': mid, 'file': mid + '.png', 'person': '王敏', 'indicator': 'A', 'level': '省级', 'date': '2026年5月', 'project': mid,
            'conditions': [{'id': 'A', 'condition': '本人为指导教师', 'met': True, 'evidence': '指导教师：王敏'}], 'quotes': [], 'summary': ''}
    return {**base, **extra}


def states(materials):
    return {m['id']: (m['status'], m['reasons']) for m in appraisal.material_flags(materials, ['王敏', '李强'], SCHEME['indicators'], SCHEME)}


def test_four_states_follow_what_the_material_shows():
    got = states([
        mat('ok'), mat('nolevel', level=''), mat('school', level='校级'), mat('old', date='2025年11月'), mat('nodate', date=''),
        mat('vague', date='2026'), mat('notme', conditions=[{'id': 'A', 'condition': '本人为指导教师', 'met': False, 'evidence': '指导教师：李强'}]),
        mat('unsaid', conditions=[{'id': 'A', 'condition': '本人为指导教师', 'met': None, 'evidence': ''}]),
        mat('whose', person=''), mat('judged', indicator='C'), mat('checked', level='', accepted=True), mat('dropped', excluded=True, note='重复'),
        mat('log', indicator='B', doc_type='工作日志', date=''), mat('oldlog', indicator='B', doc_type='工作日志', date='2025年3月'), mat('wrongtype', indicator='B', doc_type='谈话记录'), mat('nothing', indicator=''),
    ])
    expect = {'ok': 'counted', 'nolevel': 'needs_proof', 'school': 'ineligible', 'old': 'ineligible', 'nodate': 'needs_proof', 'vague': 'counted',
              'notme': 'ineligible', 'unsaid': 'needs_proof', 'whose': 'needs_proof', 'judged': 'judge', 'checked': 'counted',
              'dropped': 'ineligible', 'log': 'counted', 'oldlog': 'ineligible', 'wrongtype': 'needs_proof', 'nothing': 'ineligible'}
    assert {k: v[0] for k, v in got.items()} == expect
    assert '指导教师：李强' in got['notme'][1][0] and '考核期' in got['old'][1][0]
    assert '0–10 分' in got['judged'][1][0]  # which indicator, why manual, and the range the scheme allows


def test_only_countable_materials_score_and_undecided_ones_hold_the_item():
    materials = appraisal.material_flags([mat('a'), mat('b', level=''), mat('c', level='校级')], ['王敏'], SCHEME['indicators'], SCHEME)
    item = appraisal.score_person('王敏', SCHEME['indicators'], materials)['items'][0]
    assert item['score'] is None and item['waiting'] == ['b'] and item['left_out'] == ['c'] and 'A' in appraisal.score_person('王敏', SCHEME['indicators'], materials)['pending']
    materials = appraisal.material_flags([mat('a'), mat('b', level='国家级', accepted=True), mat('c', level='校级')], ['王敏'], SCHEME['indicators'], SCHEME)
    item = appraisal.score_person('王敏', SCHEME['indicators'], materials)['items'][0]
    assert item['score'] == 4 and not item['waiting']


def test_judge_items_are_never_completed_by_the_system():
    result = appraisal.score_person('王敏', SCHEME['indicators'], [], suggestions={'王敏::C': {'level': '优秀', 'score': 10}})
    assert 'C' in result['pending'] and result['total'] is None


def test_similar_titles_are_pointed_out_and_multi_use_follows_the_scheme():
    got = states([mat('m1', project='智慧校园能耗监测系统'), mat('m2', project='能耗监测系统')])
    assert any('同一成果' in r for r in got['m1'][1])
    one = mat('m3', indicator='B', doc_type='工作日志', also=['A'])
    assert any('只计入' in r for r in states([one])['m3'][1])
    multi = {**SCHEME, 'allow_multi': True}
    flagged = appraisal.material_flags([dict(one)], ['王敏'], multi['indicators'], multi)
    assert any('也计入' in r for r in flagged[0]['reasons'])


def wait(client, tid):
    for _ in range(300):
        task = client.get('/api/tasks/' + tid).json()
        if task['status'] not in ('queued', 'running'):
            return task
        time.sleep(.03)
    raise AssertionError('Task did not settle')


def test_a_material_needing_proof_must_be_decided_before_confirming(monkeypatch):
    def reading(instruction, payload, images=None):
        found = fake_model(instruction, payload, images)
        if instruction == appraisal.MATERIAL_INSTRUCTION and '数学建模' in payload['file_name']:
            found = {**found, 'level': ''}  # the certificate does not say its level
        return found
    monkeypatch.setattr(model, 'ask_json', reading)
    monkeypatch.setattr(model, 'status', lambda: {'configured': True, 'base_url': 'test', 'model': 'test', 'key_configured': True})
    with TestClient(app) as client:
        tid = client.post('/api/demo/appraisal', json={}).json()['id']
        pending = wait(client, tid)['result']['pending']
        proof = [m for m in pending['materials'] if m['status'] == 'needs_proof']
        reasons = {m['file']: m['reasons'][0] for m in proof}
        assert '没写级别' in reasons.pop('王敏_获奖证书_数学建模国赛.png')
        assert reasons and all('多人申报' in r for r in reasons.values())  # the planted 挑战杯 project claimed by two people
        judgements = {f'{p}::I1': {'score': 8} for p in ('王敏', '李强', '赵琳')}
        refused = client.post(f'/api/tasks/{tid}/review', json={'judgements': judgements})
        assert refused.status_code == 400 and '补充证明' in refused.json()['detail']
        decided = {m['id']: {'accepted': True, 'note': '核对原件为国家级', 'level': '国家级'} if '数学建模' in m['file'] else
                   {'excluded': True, 'note': '项目归王敏'} if m['file'].startswith('李强') else {} for m in proof}
        assert client.post(f'/api/tasks/{tid}/review', json={'judgements': judgements, 'materials': decided}).status_code == 200
        task = wait(client, tid)
        assert task['status'] == 'completed'
        wang = next(r for r in task['result']['results'] if r['person'] == '王敏')
        assert next(i for i in wang['items'] if i['id'] == 'I5')['score'] == 4  # 挑战杯 (two certificates, one project) + 数学建模


def test_usual_flow_skips_the_guess_and_a_template_reuses_the_confirmed_rule(monkeypatch):
    from tests.test_stage2 import FINAL, USUAL, csv, decide, mocked, ROSTER
    calls = mocked(monkeypatch)
    plans = []
    real = model.ask_json

    def counting(instruction, payload, images=None, fresh=False):
        if instruction == understand.PLAN_INSTRUCTION:
            plans.append(1)
        return real(instruction, payload, images, fresh)
    monkeypatch.setattr(model, 'ask_json', counting)
    rules = '期末60%，平时40%，没有记录按0分。'
    with TestClient(app) as client:
        assert client.post('/api/prefs', json={'identity': '任课教师', 'flow': 'grades'}).json() == {'identity': '任课教师', 'flow': 'grades'}
        assert client.get('/api/config').json()['prefs']['flow'] == 'grades'
        files = [csv('名单.csv', ROSTER), csv('期末.csv', FINAL), csv('平时.csv', USUAL)]
        tid = client.post('/api/tasks', files=files, data={'kind': 'grades', 'kind_source': 'pref', 'rules_text': rules}).json()['id']
        task = wait(client, tid)
        assert task['request']['detected']['reason'] == '按你设置的常用流程'
        assert client.post(f'/api/tasks/{tid}/template', json={'name': '期末平时'}).status_code == 409  # not confirmed yet
        task = decide(client, tid, task)
        template = client.post(f'/api/tasks/{tid}/template', json={'name': '期末平时'}).json()['id']
        listed = client.get('/api/config').json()['templates']
        assert listed[0]['name'] == '期末平时' and versions.same_text(listed[0]['text'], rules) and 'totals' not in str(listed)
        parsed, planned = calls['parse'], len(plans)
        files = [csv('名单.csv', ROSTER), csv('期末.csv', FINAL.replace('80', '60')), csv('平时.csv', USUAL)]
        again = client.post('/api/tasks', files=files, data={'template': template, 'rules_text': rules}).json()['id']
        pending = wait(client, again)['result']['pending']
        assert calls['parse'] == parsed and len(plans) == planned  # the confirmed reading is reused, nothing asked again
        assert pending['rule']['template'] == '期末平时' and {t['student_id']: t['total'] for t in pending['preview']}['001'] == 70.0  # new data, new scores
        edited = client.post('/api/tasks', files=files, data={'template': template, 'rules_text': '期末70%，平时30%，没有记录按0分。'}).json()['id']
        wait(client, edited)
        assert calls['parse'] == parsed + 1  # changed rules are read again
        client.delete(f'/api/templates/{template}')
        client.post('/api/prefs', json={'identity': '', 'flow': ''})
