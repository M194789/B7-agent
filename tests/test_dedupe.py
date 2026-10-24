"""Same achievement or not: hard evidence decides directly, the rest is the model's call with checked quotes, the
evaluator can change any of it, and the scheme decides how a work awarded twice is counted."""
from app import appraisal, dedupe

ITEMS = appraisal.normalize_scheme({'indicators': [
    {'id': 'A', 'name': '竞赛获奖', 'max': 10, 'method': 'count', 'points': {'省级': 2, '国家级': 4}, 'cap': 10}]})['indicators']


def mat(mid, **extra):
    return {'id': mid, 'file': mid + '.pdf', 'person': '王敏', 'indicator': 'A', 'level': '省级', 'status': 'counted', 'excerpt': '', **extra}


def never(*_):
    raise AssertionError('the model should not be asked')


def test_hard_evidence_decides_without_the_model():
    asked = []
    pairs = dedupe.relate([
        mat('scan1', cert_no='HN-2026-0815', project='能耗监测'), mat('scan2', cert_no='HN2026 0815', project='能耗监测系统'),  # one certificate scanned twice
        mat('stu1', contest='挑战杯', edition='第十届', project='智能分拣', award='一等奖', students=['甲'], cert_no='X1'),
        mat('stu2', contest='挑战杯', edition='第十届', project='智能分拣', award='一等奖', students=['乙'], cert_no='X2'),  # a team's two certificates
        mat('other', contest='数学建模', project='共享单车调度'),
    ], ITEMS, ask=lambda _, payload: asked.append(payload['pairs']) or {'relations': [{'a': x, 'b': y, 'relation': 'different', 'reason': '无关'} for x, y in payload['pairs']]})
    got = {r['key']: (r['relation'], r['by']) for r in pairs}
    assert {k: v for k, v in got.items() if v[1] == 'rule'} == {'scan1.pdf|scan2.pdf': ('same_award', 'rule'), 'stu1.pdf|stu2.pdf': ('same_award', 'rule')}
    assert len(asked) == 1 and ['scan1', 'scan2'] not in asked[0] and ['stu1', 'stu2'] not in asked[0]  # decided pairs are not asked
    assert all(v == ('different', 'model') for v in got.values() if v[1] != 'rule')
    assert '团队' in next(r['reason'] for r in pairs if r['key'] == 'stu1.pdf|stu2.pdf')


def test_the_model_judges_the_rest_and_its_quotes_are_checked():
    asked = []

    def model(instruction, payload):
        asked.append(payload['pairs'])
        return {'relations': [{'a': 'p', 'b': 'n', 'relation': 'same_work', 'reason': '同一作品先获省奖后获国奖',
                               'evidence': ['作品《能耗哨兵》获全国二等奖', '原文里没有的一句']}]}
    pairs = dedupe.relate([mat('p', contest='省赛', project='基于深度学习的校园能耗智能监测系统', excerpt='作品《能耗哨兵》获省一等奖'),
                           mat('n', contest='国赛', project='能耗哨兵：校园能耗智能监测', excerpt='作品《能耗哨兵》获全国二等奖', level='国家级')], ITEMS, ask=model)
    assert asked == [[['p', 'n']]] and pairs[0]['relation'] == 'same_work' and pairs[0]['by'] == 'model'
    assert [q['verified'] for q in pairs[0]['evidence']] == [True, False]


def test_no_answer_means_the_evaluator_decides():
    def failing(*_):
        raise ValueError('busy')
    pairs = dedupe.relate([mat('a', project='校园能耗监测'), mat('b', project='校园能耗监测平台', level='国家级')], ITEMS, ask=failing)
    assert pairs[0]['relation'] == 'unsure' and pairs[0]['by'] == 'none'
    materials = [mat('a', project='校园能耗监测'), mat('b', project='校园能耗监测平台', level='国家级')]
    result = appraisal.score_person('王敏', ITEMS, materials, relations=pairs)
    assert result['items'][0]['score'] is None and 'A' in result['pending']
    decided = dedupe.effective(pairs, {pairs[0]['key']: 'different'})
    assert appraisal.score_person('王敏', ITEMS, materials, relations=decided)['items'][0]['score'] == 6
    assert decided[0]['by'] == 'evaluator' and decided[0]['model_relation'] == 'unsure'


def test_a_work_awarded_twice_is_counted_as_the_scheme_says_and_asked_when_it_is_silent():
    materials = [mat('p', project='能耗哨兵'), mat('n', project='能耗哨兵', level='国家级')]
    same = [{'key': 'n.pdf|p.pdf', 'a': 'p', 'b': 'n', 'relation': 'same_work', 'by': 'model', 'reason': '', 'evidence': []}]
    score = lambda policy: appraisal.score_person('王敏', [{**ITEMS[0], 'same_work': policy}], materials, relations=same)['items'][0]['score']
    assert score('highest') == 4 and score('each') == 6 and score('') is None
    scheme = {'indicators': ITEMS}
    assert dedupe.questions(scheme, same, materials)[0]['id'] == 'A'
    assert not dedupe.questions({'indicators': [{**ITEMS[0], 'same_work': 'each'}]}, same, materials)
    assert not dedupe.questions(scheme, [], materials)  # nothing awarded twice: nothing to ask
