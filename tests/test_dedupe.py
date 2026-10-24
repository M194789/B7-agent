"""Same achievement or not: language-independent anchors read by the program, the model's grouping of all materials
at once, the two checked against each other into a confidence, and the scheme deciding how a work awarded twice counts."""
from app import appraisal, dedupe

ITEMS = appraisal.normalize_scheme({'indicators': [
    {'id': 'A', 'name': '竞赛获奖', 'max': 10, 'method': 'count', 'points': {'省级': 2, '国家级': 4}, 'cap': 10}]})['indicators']


def mat(mid, **extra):
    return {'id': mid, 'file': mid + '.pdf', 'person': '王敏', 'indicator': 'A', 'level': '省级', 'status': 'counted', 'excerpt': '', **extra}


def grouping(*achievements, unsure=()):
    def ask(instruction, payload):
        assert instruction == dedupe.GROUP_INSTRUCTION
        ids = {c['id'] for c in payload['cards']}
        return {'achievements': [{**a, 'awards': [[x for x in award if x in ids] for award in a['awards']]} for a in achievements],
                'unsure': [{'members': list(u), 'reason': '信息不足'} for u in unsure]}
    return ask


def test_names_and_grades_compare_across_languages():
    assert dedupe.name_keys('张三') & dedupe.name_keys('Zhang San') and dedupe.name_keys('张三') & dedupe.name_keys('San Zhang')
    assert dedupe.name_keys('单雨') & dedupe.name_keys('Shan Yu')  # a surname read differently from the common word
    assert not dedupe.name_keys('张三') & dedupe.name_keys('Zhang Shan')
    assert dedupe.award_code({'award': 'Second Prize'}) == dedupe.award_code({'award': '全国二等奖'}) == '二等奖'
    zh = mat('zh', students=['张三', '李四'], date='2026年5月', award='一等奖', project='能耗哨兵')
    en = mat('en', students=['Zhang San', 'Li Si'], date='May 2026', award='First Prize', project='Energy Sentinel')
    same, differ = dedupe.anchors(zh, en)
    assert '2 位学生或指导教师相同（按姓名拼音比对）' in same and not differ


def test_hard_evidence_decides_and_plainly_different_pairs_are_not_listed():
    pairs = dedupe.relate([
        mat('scan1', cert_no='HN-2026-0815', project='能耗监测'), mat('scan2', cert_no='HN2026 0815', project='能耗监测系统'),
        mat('stu1', contest='挑战杯', edition='第十届', project='智能分拣', award='一等奖', students=['甲'], cert_no='X1'),
        mat('stu2', contest='挑战杯', edition='第十届', project='智能分拣', award='一等奖', students=['乙'], cert_no='X2'),
        mat('other', contest='数学建模', project='共享单车调度', students=['丙'], date='2026'),
    ], ITEMS, ask=grouping())
    got = {r['key']: (r['relation'], r['by'], r['confidence']) for r in pairs}
    assert got == {'scan1.pdf|scan2.pdf': ('same_award', 'rule', 'certain'), 'stu1.pdf|stu2.pdf': ('same_award', 'rule', 'certain')}


def test_a_copy_in_another_language_is_found_even_when_the_model_misses_it():
    zh = mat('zh', students=['张三', '李四'], date='2026年5月', award='一等奖', project='能耗哨兵', excerpt='作品《能耗哨兵》一等奖')
    en = mat('en', students=['Zhang San', 'Li Si'], date='May 2026', award='First Prize', project='Energy Sentinel', excerpt='project "Energy Sentinel" First Prize')
    caught = dedupe.relate([zh, en], ITEMS, ask=grouping({'awards': [['zh', 'en']], 'reason': '同一团队同一作品', 'evidence': ['作品《能耗哨兵》一等奖']}))
    assert [(r['relation'], r['confidence']) for r in caught] == [('same_award', 'certain')]
    missed = dedupe.relate([zh, en], ITEMS, ask=grouping())  # the model says nothing: the anchors still raise it
    assert [(r['relation'], r['confidence']) for r in missed] == [('different', 'check')] and '拼音' in missed[0]['conflicts'][0]


def test_a_merge_the_anchors_contradict_is_shown_for_checking():
    a = mat('a', project='校园能耗监测', date='2025年', students=['张三'], excerpt='校园能耗监测')
    b = mat('b', project='校园能耗监测平台', date='2026年', students=['王五'], excerpt='校园能耗监测平台')
    pairs = dedupe.relate([a, b], ITEMS, ask=grouping({'awards': [['a', 'b']], 'reason': '题目相同', 'evidence': ['校园能耗监测']}))
    assert pairs[0]['relation'] == 'same_award' and pairs[0]['confidence'] == 'check' and any('年份不同' in c for c in pairs[0]['conflicts'])


def test_many_materials_are_all_seen_in_batches_and_linked_pairs_across_batches_asked_again(monkeypatch):
    monkeypatch.setattr(dedupe, 'BATCH', 3)
    calls = []

    def ask(instruction, payload):
        calls.append(instruction)
        if instruction == dedupe.GROUP_INSTRUCTION:
            return {'achievements': []}
        return {'relations': [{'a': x, 'b': y, 'relation': 'same_award', 'reason': '同一团队', 'evidence': []} for x, y in payload['pairs']]}
    names = ['张三', '李四', '王五', '赵六', '钱七']
    items = [mat(f'm{i}', project=f'作品{9 if i == 0 else i}', date='2026年', students=[names[i]], award='一等奖') for i in range(5)]
    items.append(mat('copy', project='Work Nine', date='2026', students=['Zhang San'], award='First Prize'))  # sorts into the other batch
    pairs = dedupe.relate(items, ITEMS, ask=ask)
    assert calls.count(dedupe.GROUP_INSTRUCTION) == 2 and dedupe.RELATE_INSTRUCTION in calls
    assert any(r['relation'] == 'same_award' and set(r['key'].split('|')) == {'m0.pdf', 'copy.pdf'} for r in pairs)


def test_no_answer_means_the_evaluator_decides():
    def failing(*_):
        raise ValueError('busy')
    materials = [mat('a', project='校园能耗监测'), mat('b', project='校园能耗监测平台', level='国家级')]
    pairs = dedupe.relate(materials, ITEMS, ask=failing)
    assert pairs[0]['relation'] == 'unsure' and pairs[0]['by'] == 'none'
    assert appraisal.score_person('王敏', ITEMS, materials, relations=pairs)['items'][0]['score'] is None
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
    assert not dedupe.questions(scheme, [], materials)  # nothing counted twice: nothing to ask
