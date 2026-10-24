"""Cache, duplicate files, understanding the task before processing, statuses the rules do not mention, possible duplicates."""
import io
import json
import time

import httpx
from fastapi.testclient import TestClient

from app import grades, model, scoring, store, understand, uploads, workflow
from app.main import app

ROSTER = [{'student_id': '001', 'student_name': '甲'}, {'student_id': '002', 'student_name': '乙'}]
CONFIGURED = {'configured': True, 'base_url': 'test', 'model': 'test', 'key_configured': True}


def table(name, headers, rows):
    return grades.build_tables(name, [('', [headers] + rows)])[0]


def wait(client, task_id):
    for _ in range(300):
        task = client.get('/api/tasks/' + task_id).json()
        if task['status'] not in ('queued', 'running'):
            return task
        time.sleep(.03)
    raise AssertionError('Task did not settle')


def test_same_question_about_same_content_is_asked_once(monkeypatch):
    store.init()
    monkeypatch.setenv('B7_MODEL_CACHE', '1')
    calls = []
    real_client = httpx.Client

    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({'n': len(calls)})}}]})
    monkeypatch.setattr(model.httpx, 'Client', lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    try:
        model.configure('https://model.invalid/v1', 'cache-test-model', 'unit-test-only')
        payload = {'headers': ['账号', '成绩'], 'nonce': time.time()}
        assert model.ask_json('识别表头。', payload) == {'n': 1}
        assert model.ask_json('识别表头。', payload) == {'n': 1} and len(calls) == 1  # answered from the cache
        assert model.ask_json('识别表头。', payload, images=[b'photo-a']) == {'n': 2}  # a different photo is a new question
        assert model.ask_json('识别表头。', payload, images=[b'photo-a']) == {'n': 2} and len(calls) == 2
        assert model.ask_json('识别表头。', payload, fresh=True) == {'n': 3}  # “重新理解” asks again
    finally:
        model.clear()


def test_identical_files_are_kept_once_whatever_their_names():
    kept, dropped = uploads.unique_contents([('a/成绩.csv', b'x,1'), ('b/成绩副本.csv', b'x,1'), ('名单.csv', b'y')])
    assert [n for n, _ in kept] == ['a/成绩.csv', '名单.csv'] and dropped == [('b/成绩副本.csv', 'a/成绩.csv')]


def test_upload_lists_duplicates_and_what_was_imported():
    with TestClient(app) as client:
        body = '学号,姓名,期末\n001,甲,80\n002,乙,90\n'.encode('utf-8')
        files = [('files', ('期末.csv', io.BytesIO(body), 'text/csv')), ('files', ('期末(1).csv', io.BytesIO(body), 'text/csv'))]
        created = client.post('/api/tasks', files=files, data={'kind': 'grades'})
        assert created.status_code == 201, created.text
        task = wait(client, created.json()['id'])
        materials = {m['name']: m for m in task['result']['materials']}  # no rules, no problems: finished directly
        assert materials['期末.csv']['status'] == 'imported' and '2 行' in materials['期末.csv']['text']
        assert materials['期末(1).csv']['status'] == 'duplicate'
        assert task['result']['summary']['input_rows'] == 2  # the copy was not read again


def test_overview_reads_headers_and_samples_without_a_model(tmp_path):
    (tmp_path / '名单.csv').write_text('学号,姓名\n001,甲\n002,乙\n', encoding='utf-8')
    (tmp_path / '平台.csv').write_text('学号,观看,小测\n001,80,90\n', encoding='utf-8')
    (tmp_path / '问答.png').write_bytes(b'not read here')
    files = [{'name': n, 'path': str(tmp_path / n), 'role': ''} for n in ('名单.csv', '平台.csv', '问答.png')]
    seen, people = understand.overview(files)
    assert people == 2
    assert [s['kind'] for s in seen] == ['课程名单', '表格', '照片']
    assert seen[1]['headers'] == ['学号', '观看', '小测'] and seen[1]['sample_rows'] == [['001', '80', '90']]
    plan = understand.normalize({'questions': [{'question': '慕课怎么算', 'why': '影响15%', 'options': ['用平台总评', '']}]}, None)
    assert plan['questions'][0]['options'] == ['用平台总评'] and '无法判断谁完全没有记录' in plan['baseline_note']
    text = understand.answered_rules('期末100%。', plan, ['用平台总评'], '小数保留1位')
    assert text.endswith('问：慕课怎么算\n答：用平台总评\n补充：小数保留1位')


def test_questions_come_before_processing_and_answers_join_the_rules(monkeypatch):
    seen = {}

    def ask(instruction, payload, images=None, fresh=False):
        if instruction == understand.PLAN_INSTRUCTION:
            return {'subject': '课程学生', 'questions': [{'question': '规则没说缓考怎么处理，怎么办？', 'why': '影响缓考学生的总评',
                                                         'options': ['总评待定', '按0分']}]}
        if instruction == scoring.PARSE_INSTRUCTION:
            seen['rules'] = payload['teacher_rules']
            return {'components': [{'name': '期末', 'assessments': ['期末'], 'weight': 100}], 'status_policy': {'缓考': 'pending'}}
        return {}
    monkeypatch.setattr(model, 'ask_json', ask)
    monkeypatch.setattr(model, 'status', lambda: CONFIGURED)
    with TestClient(app) as client:
        body = '学号,姓名,期末,备注\n001,甲,80,\n002,乙,,缓考\n'.encode('utf-8')
        tid = client.post('/api/tasks', files=[('files', ('期末.csv', io.BytesIO(body), 'text/csv'))],
                          data={'kind': 'grades', 'rules_text': '期末占100%。'}).json()['id']
        task = wait(client, tid)
        pending = task['result']['pending']
        assert pending['stage'] == 'understand' and pending['plan']['questions'][0]['options'] == ['总评待定', '按0分']
        assert not any(e['tool'].startswith('merge_grades') for e in task['events'])  # nothing processed yet
        assert client.post(f'/api/tasks/{tid}/review', json={'answers': ['总评待定']}).status_code == 200
        task = wait(client, tid)
        assert task['result']['pending']['stage'] == 'confirm'
        assert seen['rules'].endswith('答：总评待定') and task['result']['pending']['plan']['answers'] == ['总评待定']


def test_a_status_the_rules_do_not_mention_waits_instead_of_a_default():
    rows = grades.merge([t := table('期末.csv', ['学号', '期末', '备注'], [['001', '80', ''], ['002', '', '缓考']])],
                        {t['id']: {'student_id': '学号', 'score': '期末', 'remark': '备注'}}, {'course': '课'}, roster=ROSTER)['rows']
    rule = scoring.normalize({'components': [{'name': '期末', 'assessments': ['期末'], 'weight': 100}]})
    assert rule['status_policy'] == {} and rule['components'][0]['missing'] == 'pending'
    totals = {t['student_id']: t for t in scoring.compute(rule, rows, ROSTER)['totals']}
    assert totals['001']['total'] == 80 and totals['002']['outcome'] == 'pending'
    assert any('规则没说怎么处理' in w for w in scoring.check(rule, rows)[1])
    assert any('规则没说怎么处理' in line for line in scoring.describe(rule, {'缓考'}))
    stated = scoring.normalize({**rule, 'status_policy': {'缓考': 'zero'}})
    assert {t['student_id']: t['total'] for t in scoring.compute(stated, rows, ROSTER)['totals']}['002'] == 0


def test_no_record_is_pending_unless_the_rules_say_zero():
    rows = grades.merge([t := table('期末.csv', ['学号', '期末'], [['001', '80']])], {t['id']: {'student_id': '学号', 'score': '期末'}},
                        {'course': '课'}, roster=ROSTER)['rows']
    base = {'components': [{'name': '期末', 'assessments': ['期末'], 'weight': 100}]}
    assert {t['student_id']: t['outcome'] for t in scoring.compute(scoring.normalize(base), rows, ROSTER)['totals']}['002'] == 'pending'
    zero = scoring.normalize({'components': [{**base['components'][0], 'missing': 'zero'}]})
    assert {t['student_id']: t['total'] for t in scoring.compute(zero, rows, ROSTER)['totals']}['002'] == 0


def answer_log(decisions=None):
    photo = table('问答照片.png', ['日期', '题号', '学号'], [['9-8', 'Q3', '001'], ['9-8', 'Q4', '001']])
    sheet = table('问答登记.xlsx', ['日期', '学号'], [['9-8', '001'], ['9-15', '001']])
    events = {'occurrence': '日期', 'student_id': '学号', 'events': True, 'item_name': '问答'}
    return grades.merge([photo, sheet], {photo['id']: {**events, 'question': '题号'}, sheet['id']: events}, {'course': '课'}, decisions, ROSTER)


def test_one_event_in_two_sources_is_asked_not_counted_twice_or_dropped():
    result = answer_log()
    dups = [i for i in result['issues'] if i['type'] == 'duplicate']
    # “9-8” in the register may be the 9-8 Q3 or the 9-8 Q4 answer of the photo; 9-15 matches nothing; Q3 and Q4 differ.
    assert len(dups) == 1 and len(result['rows']) == 4
    assert {r['occurrence'] for r in dups[0]['records']} == {'9-8', '9-8 Q3', '9-8 Q4'}
    rule = scoring.normalize({'components': [{'name': '问答', 'assessments': ['问答'], 'weight': 100, 'aggregate': 'count', 'full_count': 5, 'missing': 'zero'}]})
    waiting = workflow.rule_view(rule, result['rows'], ROSTER, result['issues'])
    assert next(t for t in waiting['preview'] if t['student_id'] == '001')['outcome'] == 'pending'  # the count waits for the answer
    assert len(dups[0]['options']) == 2  # it is the Q3 answer, or the Q4 answer (or a third one: “keep”)
    merged = answer_log({dups[0]['id']: {'action': 'select', 'record_id': dups[0]['options'][0]['value']}})
    assert len(merged['rows']) == 3 and not [i for i in merged['issues'] if i['type'] == 'duplicate']
    kept = next(r for r in merged['rows'] if r['occurrence'] == '9-8 Q3')
    assert {s['file'] for s in kept['sources']} == {'问答照片.png', '问答登记.xlsx'}  # both places it was found are kept
    both = answer_log({dups[0]['id']: {'action': 'keep'}})
    assert len(both['rows']) == 4 and not [i for i in both['issues'] if i['type'] == 'duplicate']


def test_a_service_refusing_the_large_output_budget_gets_the_common_one(monkeypatch):
    sent = []
    real_client = httpx.Client

    def handler(request):
        body = json.loads(request.content)
        sent.append(body['max_tokens'])
        if body['max_tokens'] > model.FALLBACK_TOKENS:
            return httpx.Response(400, json={'error': 'max_tokens too large'})
        return httpx.Response(200, json={'choices': [{'message': {'content': '{"ok": true}'}}]})
    monkeypatch.setattr(model.httpx, 'Client', lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    try:
        model.configure('https://model.invalid/v1', 'small-model', 'unit-test-only')
        assert model.ask_json('测试。', {'x': 1}) == {'ok': True}
        assert sent[0] == model.MAX_TOKENS and sent[-1] == model.FALLBACK_TOKENS
    finally:
        model.clear()
