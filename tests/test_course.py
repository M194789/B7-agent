from app import grades, scoring, store

FIXTURES = store.ROOT / 'fixtures'
REQUEST = {'course': '数据结构', 'term': '2026秋'}
# Teacher-confirmed rule for the sample; expected totals below were worked out by hand from the fixture values.
RULE = scoring.normalize({'components': [
    {'name': '课堂小测', 'assessments': ['小测'], 'weight': 20, 'aggregate': 'drop_lowest_mean', 'drop_lowest': 1, 'full_score': 10, 'missing': 'zero'},
    {'name': '作业', 'assessments': ['作业'], 'weight': 10, 'aggregate': 'mean', 'missing': 'zero'},
    {'name': '课堂答问', 'assessments': ['答问'], 'weight': 10, 'aggregate': 'count', 'full_count': 3, 'missing': 'zero'},
    {'name': '期中', 'assessments': ['期中'], 'weight': 20, 'aggregate': 'mean', 'missing': 'pending'},
    {'name': '期末', 'assessments': ['期末'], 'weight': 40, 'aggregate': 'mean', 'missing': 'pending'},
], 'status_policy': {'缺考': 'zero', '缓考': 'pending'}, 'rounding': {'digits': 0}})


def load():
    tables = []
    for name in ('学习通_小测与作业导出.xlsx', '教务_期中期末成绩.csv', '课堂答问记录_誊录.csv'):
        tables += grades.read_table(FIXTURES / name)
    roster = grades.read_roster(FIXTURES / '数据结构_课程名单.csv')
    return tables, {t['id']: grades.propose_mapping(t['headers']) for t in tables}, roster


def resolve(issues):
    decisions = {}
    for issue in issues:
        if issue['type'] == 'conflict':
            decisions[issue['id']] = {'action': 'select', 'record_id': next(o['value'] for o in issue['options'] if o['label'].startswith('94'))}
        elif issue['candidates'] and issue['record']['student_name'] == '张伟':
            decisions[issue['id']] = {'action': 'correct', 'student_id': '2026103'}
        elif issue['candidates']:
            decisions[issue['id']] = {'action': 'correct', 'student_id': issue['candidates'][0]['student_id']}
        elif issue.get('scope') == 'value':
            decisions[issue['id']] = {'action': 'correct', 'score': '10'}
        else:
            decisions[issue['id']] = {'action': 'exclude', 'note': '名单外学生'}
    return decisions


def test_wide_export_is_recognised_as_item_columns():
    tables, mappings, _ = load()
    wide = next(t for t in tables if t['name'].startswith('学习通'))
    assert mappings[wide['id']]['item_columns'] == ['小测1（10分）', '小测2（10分）', '小测3（10分）', '作业1', '作业2']
    assert grades.split_item_header('小测2（10分）') == ('小测', '2', 10.0)


def test_roster_checks_status_and_occurrences():
    tables, mappings, roster = load()
    result = grades.merge(tables, mappings, REQUEST, roster=roster)
    titles = [i['title'] for i in result['issues']]
    # One identity issue for the mistyped ID row in the wide export, not one per cell.
    assert sum('学号不在课程名单中' in t for t in titles) == 1
    assert any('2 名同名学生' in t for t in titles)
    assert any('没有这个姓名' in t for t in titles)
    assert any('分数 12 超出范围（满分 10）' in t for t in titles)
    assert sum(i['type'] == 'conflict' for i in result['issues']) == 1
    assert len(result['issues']) == 5
    statuses = {(r['student_id'], r['status']) for r in result['rows'] if r['status']}
    assert statuses == {('2026105', '缺考'), ('2026110', '缓考')}
    # Three quizzes stay three records; the duplicated final export merges.
    assert len([r for r in result['rows'] if r['student_id'] == '2026101' and r['assessment'] == '小测']) == 3
    final = next(r for r in result['rows'] if r['student_id'] == '2026101' and r['assessment'] == '期末')
    assert final['source_count'] == 2
    assert [m['student_id'] for m in result['missing_students']] == ['2026111']
    assert result['summary']['name_matched'] == 10  # 12 classroom notes minus the ambiguous 张伟 and the off-roster 李明


def test_totals_follow_confirmed_rule():
    tables, mappings, roster = load()
    first = grades.merge(tables, mappings, REQUEST, roster=roster)
    result = grades.merge(tables, mappings, REQUEST, resolve(first['issues']), roster)
    assert result['issues'] == []
    assert result['missing_students'] == [{'student_id': '2026111', 'student_name': '郑凯'}]
    errors, warnings = scoring.check(RULE, result['rows'])
    assert errors == [] and warnings == []
    totals = {t['student_id']: t for t in scoring.compute(RULE, result['rows'], roster)['totals']}
    # 王晨: 小测 (8,9,7 drop 7)=85*20% + 作业 87.5*10% + 答问 4/3 capped 100*10% + 期中 82*20% + 期末 88*40% = 87.35
    assert totals['2026101']['total'] == 87
    # 赵一凡: 缺考 final counts zero → 19 + 8.9 + 3.33 + 17.2 + 0 = 48.43
    assert totals['2026105']['total'] == 48
    # 张伟 2026104: blank 小测2/作业2 count as zero → 15 + 4.25 + 0 + 13.6 + 28.8 = 61.65
    assert totals['2026104']['total'] == 62
    assert any('缺少 小测第2次' in n for n in totals['2026104']['notes'])
    assert totals['2026110']['outcome'] == 'pending' and totals['2026110']['total'] is None
    assert totals['2026111']['outcome'] == 'pending'
    # 孙浩's mistyped ID was corrected to the roster ID, so platform scores join the exams.
    assert totals['2026108']['outcome'] == 'ok'
    assert {p['name'] for p in totals['2026108']['components'] if p['percent']} == {'课堂小测', '作业', '期中', '期末'}


def test_rule_check_catches_bad_weights_and_double_counting():
    rows = [{'assessment': '小测', 'occurrence': '1', 'student_id': '1', 'max_score': 10, 'mark': False}]
    rule = scoring.normalize({'components': [{'name': 'A', 'assessments': ['小测'], 'weight': 50},
                                             {'name': 'B', 'assessments': ['小测'], 'weight': 30}]})
    errors, _ = scoring.check(rule, rows)
    assert any('80' in e for e in errors) and any('重复计分' in e for e in errors)
