"""Grades by table, event logs, platform sub-items and totals, and the list of zeros: all computed without a model."""
from app import grades, scoring, workflow

ROSTER = [{'student_id': '001', 'student_name': '甲'}, {'student_id': '002', 'student_name': '乙'},
          {'student_id': '003', 'student_name': '李洋'}, {'student_id': '004', 'student_name': '李洋'}]
REQUEST = {'course': '数据素养'}


def table(name, headers, rows):
    return grades.build_tables(name, [('', [headers] + rows)])[0]


def merge(*pairs):
    tables = [t for t, _ in pairs]
    return grades.merge(tables, {t['id']: m for t, m in pairs}, REQUEST, roster=ROSTER)


def rule(*components, digits=2, statuses=None):
    return scoring.normalize({'components': list(components), 'rounding': {'digits': digits}, 'status_policy': statuses or {}})


def test_letter_grades_use_the_rules_table_and_unknown_grades_are_pointed_out():
    hw = table('作业.csv', ['学号', '作业编号', '等级', '提交状态'],
               [['001', 'HW01', 'a', '已交'], ['001', 'HW02', 'B', '已交'], ['002', 'HW01', 'D', '已交'], ['002', 'HW02', '95', '已交']])
    result = merge((hw, {'student_id': '学号', 'occurrence': '作业编号', 'score': '等级', 'status': '提交状态', 'assessment': '作业编号'}))
    assert not result['issues']  # letters are not “invalid scores” any more
    r = rule({'name': '作业', 'assessments': ['HW01', 'HW02'], 'weight': 100, 'grade_map': {'A': 90, 'B': 85, 'C': 80}})
    assert not scoring.check(r, result['rows'])[0]
    totals = {t['student_id']: t for t in scoring.compute(r, result['rows'], ROSTER)['totals']}
    assert totals['001']['total'] == 87.5  # (90 + 85) / 2, lower-case a normalised
    titles = [i['title'] for i in workflow.grade_issues(r, result['rows'])]
    assert any('“D”不在规则的等级' in t for t in titles) and any('填的是数字“95”' in t for t in titles)
    no_table = rule({'name': '作业', 'assessments': ['HW01', 'HW02'], 'weight': 100})
    assert any('请给出每个等级对应的分数' in e for e in scoring.check(no_table, result['rows'])[0])


def test_answer_log_counts_distinct_answers_and_needs_the_roster_for_names():
    log = table('问答.csv', ['日期', '题号', '记录内容'],
                [['9-7', 'Q1', '001'], ['9-7', 'Q1', '甲'], ['9-7', 'Q2', '甲'], ['9-14', 'Q1', '李洋'], ['9-14', 'Q3', '乙']])
    mapping = {'student': '记录内容', 'occurrence': '日期', 'question': '题号', 'events': True, 'item_name': '问答'}
    result = merge((log, mapping))
    counted = {(r['student_id'], r['occurrence']) for r in result['rows']}
    assert counted == {('001', '9-7 Q1'), ('001', '9-7 Q2'), ('002', '9-14 Q3')}  # 001 by number and by name is one answer
    assert any('2 名同名' in i['title'] for i in result['issues'])  # 李洋 cannot be assigned without the teacher
    r = rule({'name': '问答', 'assessments': ['问答'], 'weight': 100, 'aggregate': 'count', 'full_count': 10, 'missing': 'zero'})
    totals = {t['student_id']: t['total'] for t in scoring.compute(r, result['rows'], ROSTER)['totals']}
    assert totals['001'] == 20 and totals['002'] == 10 and totals['003'] == 0


def platform():
    return table('学习通导出.csv', ['学号', '视频', '测验', '平台总评'], [['001', '80', '90', '86'], ['002', '60', '', '30']])


PLATFORM_MAP = {'student_id': '学号', 'item_columns': ['视频', '测验'], 'total_column': '平台总评', 'source_name': '学习通'}


def test_platform_total_is_used_directly_or_rebuilt_from_weighted_parts():
    rows = merge((platform(), PLATFORM_MAP))['rows']
    assert {r['assessment'] for r in rows} == {'学习通', '学习通·视频', '学习通·测验'}
    direct = rule({'name': '学习通', 'assessments': ['学习通'], 'weight': 100})
    assert not scoring.check(direct, rows)[0]
    assert {t['student_id']: t['total'] for t in scoring.compute(direct, rows, ROSTER[:2])['totals']} == {'001': 86, '002': 30}
    parts = rule({'name': '学习通', 'assessments': [], 'weight': 100, 'missing': 'zero',
                  'parts': [{'assessments': ['学习通·视频'], 'weight': 40}, {'assessments': ['学习通·测验'], 'weight': 60}]})
    totals = {t['student_id']: t for t in scoring.compute(parts, rows, ROSTER[:2])['totals']}
    assert totals['001']['total'] == 86 and not totals['001']['mismatches']
    assert totals['002']['total'] == 24 and totals['002']['mismatches']  # 测验 missing counts 0 (listed), and 30 ≠ 24 is reported
    zero = next(z for z in totals['002']['zeros'] if '测验' in z['text'])
    assert '没有记录' in zero['text'] and zero['fill'] == [{'assessment': '学习通·测验', 'occurrence': ''}]  # can be filled in


def test_numbered_platform_columns_stay_one_assessment_so_two_platforms_still_merge():
    xt = table('学习通.csv', ['学号', '小测1（10分）', '视频学习'], [['001', '8', '90']])
    yk = table('雨课堂.csv', ['学号', '小测1（10分）'], [['001', '8']])
    rows = merge((xt, {'student_id': '学号', 'item_columns': ['小测1（10分）', '视频学习'], 'source_name': '学习通'}),
                 (yk, {'student_id': '学号', 'item_columns': ['小测1（10分）'], 'source_name': '雨课堂'}))['rows']
    assert {r['assessment']: r['source_count'] for r in rows} == {'小测': 2, '学习通·视频学习': 1}


def test_only_sub_items_and_no_weights_asks_the_teacher():
    no_total = table('慕课导出.csv', ['学号', '视频得分', '单元测验'], [['001', '80', '90']])
    rows = merge((no_total, {'student_id': '学号', 'item_columns': ['视频得分', '单元测验'], 'source_name': '慕课'}))['rows']
    errors, _ = scoring.check(rule({'name': '慕课', 'assessments': ['慕课'], 'weight': 100}), rows)
    assert any('只有分项数据' in e and '请告诉我各分项的权重' in e for e in errors)


def test_every_zero_is_listed_and_a_teacher_change_is_recomputed():
    exams = table('期末.csv', ['学号', '成绩', '考务状态'], [['001', '0', '正常'], ['002', '', '缺考']])
    rows = merge((exams, {'student_id': '学号', 'score': '成绩', 'status': '考务状态'}))['rows']
    r = rule({'name': '期末', 'assessments': ['期末'], 'weight': 100, 'missing': 'zero'}, statuses={'缺考': 'zero'})
    totals = {t['student_id']: t for t in scoring.compute(r, rows, ROSTER[:3])['totals']}
    text = lambda sid: [z['text'] for z in totals[sid]['zeros']]
    assert text('001') == ['期末：成绩为 0'] and text('002') == ['期末：缺考']
    assert text('003') == ['期末没有记录'] and totals['003']['total'] == 0
    assert totals['003']['zeros'][0]['fill'] == [{'assessment': '期末', 'occurrence': ''}] and totals['002']['zeros'][0]['fill'] == []
    changed = {t['student_id']: t for t in scoring.compute(r, rows, ROSTER[:3], {'003::期末': {'value': 75, 'note': '补录'}})['totals']}
    assert changed['003']['total'] == 75 and changed['003']['zeros'] == [] and '原为 0' in changed['003']['components'][0]['how']
