import pytest

from app import appraisal, grades
from eval import cases as C
from eval import run


@pytest.mark.parametrize('case', C.GRADE_CASES, ids=lambda c: c['id'])
def test_grade_answer_keys_resolve_without_the_model(case):
    """Every planted problem has a decision and the confirmed rule is valid, so the evaluation measures the model only."""
    result, totals, _ = run.expected(case)
    assert result['rows'] and len(totals['totals']) >= 10


def test_answer_keys_match_hand_calculation():
    totals = lambda cid: {t['student_id']: t['total'] if t['outcome'] == 'ok' else t['outcome'] for t in run.expected(C.CASE_INDEX[cid])[1]['totals']}
    a2, a3, a4 = totals('A2'), totals('A3'), totals('A4')
    assert a2['2026104'] == 59.7  # (70 + 0 未交 + 72) / 3 × 30% + 65 × 70%
    assert a2['2026108'] == 64.1 and a2['2026110'] == 'exempt'  # the resit is not counted; 免修 is out of the total
    assert a3['2026103'] == 95 and a3['2026104'] == 65  # “张伟（1班）” 8/8 and “张伟（2班）” 6/8 attendance
    assert a4['0231003'] == 34 and a4['0231007'] == 'invalid'  # 缺考 on the exam only; 作弊 voids the total


def test_appraisal_answer_keys():
    for case in C.APPRAISAL_CASES:
        indicators = appraisal.normalize_scheme({'indicators': case['scheme']})['indicators']
        materials = run.truth_materials(case, indicators)
        judged = {k: {'score': v} for k, v in case['judgements'].items()}
        assert {p: appraisal.score_person(p, indicators, materials, judged)['total'] for p in case['people']} == {'王敏': 69, '李强': 38, '赵琳': 50.5}
        assert all((case['dir'] / name).exists() for name in case['materials'])


def wide(rows, headers):
    return grades.build_tables('t.csv', [('', [headers] + rows)])[0]


def test_note_in_wide_row_belongs_to_the_exam_column():
    table = wide([['1', '甲', '78', '', '缺考'], ['2', '乙', '60', '52', '考试作弊'], ['3', '丙', '', '80', '作业未交']],
                 ['学号', '姓名', '平时', '期末', '备注'])
    mapping = {'student_id': '学号', 'student_name': '姓名', 'remark': '备注', 'item_columns': ['平时', '期末']}
    rows = {(r['student_id'], r['assessment']): r['status'] or r['score'] for r in grades.merge([table], {table['id']: mapping}, {'course': 'x'})['rows']}
    assert rows[('1', '平时')] == 78 and rows[('1', '期末')] == '缺考'
    assert rows[('2', '平时')] == 60 and rows[('2', '期末')] == '作弊'
    assert rows[('3', '平时')] == '未交' and rows[('3', '期末')] == 80


def test_date_columns_take_the_item_name():
    assert grades.split_item_header('9/8') == ('', '9/8', None) and grades.split_item_header('第3周') == ('', '3', None)
    assert grades.split_item_header('平时(30%)') == ('平时', '', None)
    table = wide([['甲', '√', '', '√']], ['姓名', '9/1', '9/8', '9/15'])
    mapping = {'student_name': '姓名', 'item_columns': ['9/1', '9/8', '9/15']}
    assert not grades.mapping_complete(mapping, {'course': 'x'})
    roster = [{'student_id': '1', 'student_name': '甲'}]
    rows = grades.merge([table], {table['id']: {**mapping, 'item_name': '考勤'}}, {'course': 'x'}, roster=roster)['rows']
    assert [(r['assessment'], r['occurrence']) for r in rows] == [('考勤', '9/1'), ('考勤', '9/15')]


def test_teacher_choice_of_student_is_not_questioned_again():
    table = wide([['张伟（1班）', '√']], ['姓名', '答问'])
    mapping = {'student_name': '姓名', 'score': '答问'}
    roster = [{'student_id': '3', 'student_name': '张伟'}, {'student_id': '4', 'student_name': '张伟'}]
    first = grades.merge([table], {table['id']: mapping}, {'course': 'x'}, roster=roster)
    issue = first['issues'][0]
    second = grades.merge([table], {table['id']: mapping}, {'course': 'x'}, {issue['id']: {'action': 'correct', 'student_id': '3'}}, roster)
    assert not second['issues'] and second['rows'][0]['student_id'] == '3'
