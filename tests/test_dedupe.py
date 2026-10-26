"""Same achievement or not: language-independent anchors read by the program, the model's grouping of all materials
at once, the two checked against each other into a confidence, and the scheme deciding how a work awarded twice counts."""
from app import appraisal, dedupe

ITEMS = appraisal.normalize_scheme({'indicators': [
    {'id': 'A', 'name': '竞赛获奖', 'max': 10, 'method': 'count', 'points': {'省级': 2, '国家级': 4}, 'cap': 10}]})['indicators']


def mat(mid, **extra):
    """A material whose text says what was read from it, unless the test gives the text (or a picture: origin image)."""
    m = {'id': mid, 'file': mid + '.pdf', 'person': '王敏', 'indicator': 'A', 'level': '省级', 'status': 'counted', **extra}
    if 'excerpt' not in m:
        m['excerpt'] = ' '.join(' '.join(v) if isinstance(v, list) else str(v) for k, v in extra.items() if k != 'origin')
    return m


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
    zh = mat('zh', students=['张三', '李四'], date='2026年5月', award='一等奖', project='能耗哨兵', excerpt='张三、李四 作品《能耗哨兵》一等奖 2026年5月')
    en = mat('en', students=['Zhang San', 'Li Si'], date='May 2026', award='First Prize', project='Energy Sentinel',
             excerpt='Zhang San, Li Si: project "Energy Sentinel" First Prize, May 2026')
    caught = dedupe.relate([zh, en], ITEMS, ask=grouping({'awards': [['zh', 'en']], 'reason': '同一团队同一作品',
                                                          'evidence': [{'id': 'zh', 'text': '作品《能耗哨兵》一等奖'}, {'id': 'en', 'text': 'project "Energy Sentinel" First Prize'}]}))
    assert [(r['relation'], r['confidence']) for r in caught] == [('same_award', 'certain')]
    one_sided = dedupe.relate([zh, en], ITEMS, ask=grouping({'awards': [['zh', 'en']], 'reason': '同一作品', 'evidence': [{'id': 'zh', 'text': '作品《能耗哨兵》一等奖'}]}))
    assert one_sided[0]['confidence'] == 'certain'  # the team's names, checked in both texts, stand for the English side
    missed = dedupe.relate([zh, en], ITEMS, ask=grouping())  # the model says nothing: the anchors raise it for the evaluator
    assert [(r['relation'], r['confidence']) for r in missed] == [('different', 'unsure')] and '拼音' in missed[0]['conflicts'][0]


def test_a_merge_the_anchors_contradict_goes_to_the_evaluator():
    a = mat('a', project='校园能耗监测', date='2025年', students=['张三'])
    b = mat('b', project='校园能耗监测平台', date='2026年', students=['王五'])
    pairs = dedupe.relate([a, b], ITEMS, ask=grouping({'awards': [['a', 'b']], 'reason': '题目相同', 'evidence': ['校园能耗监测']}))
    assert pairs[0]['relation'] == 'same_award' and pairs[0]['confidence'] == 'unsure' and any('年份不同' in c for c in pairs[0]['conflicts'])


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


def test_a_field_the_text_does_not_bear_out_is_not_evidence():
    # The model "read" the same number on both, but neither text has it: no rule fires, and nothing checked supports it.
    a = mat('a', cert_no='HN-2026-0815', project='能耗监测', excerpt='能耗监测 一等奖')
    b = mat('b', cert_no='HN-2026-0815', project='安全帽检测', excerpt='安全帽检测 三等奖')
    assert dedupe.checks(a) == {'cert_no': False, 'project': True}
    assert not dedupe.relate([a, b], ITEMS, ask=grouping())  # different works; the made-up number is not an anchor
    pairs = dedupe.relate([a, b], ITEMS, ask=grouping({'awards': [['a', 'b']], 'reason': '编号相同'}))
    assert pairs[0]['confidence'] == 'unsure' and '没有都能与原文核对的依据' in pairs[0]['conflicts'][-1]


def test_a_proof_issued_later_is_the_same_award_and_dated_by_the_event():
    original = mat('cert', project='能耗哨兵', contest='挑战杯', award='一等奖', students=['张三', '李四'], date='2026年5月20日')
    reissued = mat('proof', project='能耗哨兵', contest='挑战杯', award='一等奖', students=['张三', '李四'], date='2026年5月',
                   issue_date='2027年3月10日', doc_form='补开证明')
    same, differ = dedupe.anchors(dedupe.facts(original), dedupe.facts(reissued))
    assert any(x.startswith('年份相同') for x in same) and not differ  # 2027 is when the proof was written, not the award
    pairs = dedupe.relate([original, reissued], ITEMS, ask=grouping({'awards': [['cert', 'proof']], 'reason': '补开证明',
                                                                      'evidence': [{'id': 'cert', 'text': '能耗哨兵'}, {'id': 'proof', 'text': '能耗哨兵'}]}))
    assert [(r['relation'], r['confidence']) for r in pairs] == [('same_award', 'certain')]
    # In the period check the proof without the event's date needs proof of when it happened.
    scheme = {'period': {'start': '2026-09-01', 'end': '2027-08-31'}}
    item = {**ITEMS[0], 'id': 'A'}
    status, reasons = appraisal.material_status({**reissued, 'date': ''}, {'A': item}, ['王敏'], scheme, {})
    assert status == 'needs_proof' and '只写了开具日期“2027年3月10日”' in reasons[0]


def test_two_sessions_of_one_contest_are_not_one_award():
    spring = mat('s3', project='充电宝调度', contest='创客马拉松', edition='2026年', session='第3期', award='二等奖', students=['张三', '李四'], date='2026年4月12日')
    autumn = mat('s5', project='充电宝调度', contest='创客马拉松', edition='2026年', session='第5期', award='二等奖', students=['张三', '李四'], date='2026年9月20日')
    assert dedupe.by_rule(spring, autumn) is None  # all else equal, but another session
    merged = dedupe.relate([spring, autumn], ITEMS, ask=grouping({'awards': [['s3', 's5']], 'reason': '同一作品'}))
    assert merged[0]['relation'] == 'same_award' and merged[0]['confidence'] == 'unsure' and any('场次不同' in c for c in merged[0]['conflicts'])
    twice = dedupe.relate([spring, autumn], ITEMS, ask=grouping({'awards': [['s3'], ['s5']], 'reason': '同一作品两期分别获奖'}))
    assert [(r['relation'], r['confidence']) for r in twice] == [('same_work', 'certain')]


def test_contradicting_evidence_goes_to_the_evaluator():
    copy = mat('copy', cert_no='CUMCM2026-B-1188', project='共享单车调度', award='一等奖', date='2026年11月')
    cert = mat('cert', cert_no='CUMCM2026-B-1188', project='共享单车调度', award='二等奖', date='2026年11月')
    assert dedupe.by_rule(copy, cert) is None  # one number, two grades: not for a rule to settle
    for answer in ({'awards': [['copy', 'cert']], 'reason': '编号相同'}, ):
        assert dedupe.relate([copy, cert], ITEMS, ask=grouping(answer))[0]['confidence'] == 'unsure'
    apart = dedupe.relate([copy, cert], ITEMS, ask=grouping())  # "different" works sharing one certificate number
    assert [(r['relation'], r['confidence']) for r in apart] == [('different', 'unsure')]


def test_pictures_alone_are_not_enough_to_merge():
    a = mat('a', project='能耗监测', award='一等奖', origin='image', excerpt='')
    b = mat('b', project='能耗监测系统', award='一等奖', origin='image', excerpt='')
    assert dedupe.relate([a, b], ITEMS, ask=grouping({'awards': [['a', 'b']], 'reason': '同一作品'}))[0]['confidence'] == 'unsure'
    a2, b2 = {**a, 'cert_no': 'HN-0815'}, {**b, 'cert_no': 'HN 0815'}  # one number read alike from two photos
    pairs = dedupe.relate([a2, b2], ITEMS, ask=grouping())
    assert (pairs[0]['by'], pairs[0]['confidence']) == ('rule', 'check') and '图片' in pairs[0]['conflicts'][-1]
    c, d = {**a, 'contest': '挑战杯', 'edition': '第十届'}, {**b, 'project': '能耗监测', 'contest': '挑战杯', 'edition': '第十届'}  # two members' photos
    assert [(r['by'], r['confidence']) for r in dedupe.relate([c, d], ITEMS, ask=grouping())] == [('rule', 'check')]


def test_one_team_with_two_plainly_different_works_in_a_year_is_not_listed():
    a = mat('a', project='校园共享充电宝调度系统', students=['张三', '李四'], date='2026年4月', award='二等奖')
    b = mat('b', project='基于深度学习的校园能耗智能监测系统', students=['张三', '李四'], date='2026年5月', award='一等奖')
    assert dedupe.strongly_linked(a, b) and not dedupe.relate([a, b], ITEMS, ask=grouping())
    en = mat('en', project='Energy Sentinel', students=['Zhang San', 'Li Si'], date='May 2026', award='Second Prize')
    assert dedupe.relate([a, en], ITEMS, ask=grouping())[0]['confidence'] == 'unsure'  # titles in two languages: not comparable
