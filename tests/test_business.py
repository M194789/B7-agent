import csv
import io
import json
from pathlib import Path

import pytest

from app import grades, store


def sample_tables():
    tables = []
    for name in ('平台A_教务成绩.csv', '平台B_课程考核.csv', '平台C_补充记录.csv'):
        tables.extend(grades.read_table(store.ROOT / 'fixtures' / name))
    return tables, {t['id']: grades.propose_mapping(t['headers']) for t in tables}


def test_grades_do_not_merge_names_attempts_or_assessment():
    tables, mappings = sample_tables()
    result = grades.merge(tables, mappings)
    assert result['summary']['input_rows'] == 18
    assert result['summary']['duplicate_rows'] == 3
    assert result['summary']['conflict_groups'] == 1
    # 缺考 is a recognised exam status, not a data error: only the conflict and the missing ID need review.
    assert len(result['issues']) == 2
    assert next(r for r in result['rows'] if r['student_id'] == '2026011')['status'] == '缺考'
    assert {r['student_id'] for r in result['rows'] if r['student_name'] == '王芳'} == {'2026003', '2026004'}
    assert {(r['attempt'], r['score']) for r in result['rows'] if r['student_id'] == '2026006'} == {('初考', 55), ('补考', 68)}
    assert any(r['student_id'] == '2026001' and r['assessment'] == '平时' and r['score'] == 95 for r in result['rows'])


def test_review_recomputes_without_losing_provenance():
    tables, mappings = sample_tables()
    initial = grades.merge(tables, mappings)
    decisions = {}
    for issue in initial['issues']:
        if issue['type'] == 'conflict':
            record = next(r for r in issue['records'] if r['score'] == 90)
            decisions[issue['id']] = {'action': 'select', 'record_id': record['id'], 'note': '测试采用B平台记录'}
        elif not issue['record']['student_id']:
            decisions[issue['id']] = {'action': 'correct', 'student_id': '2026012', 'score': '73'}
        else:
            decisions[issue['id']] = {'action': 'exclude'}
    result = grades.merge(tables, mappings, decisions=decisions)
    assert result['issues'] == []
    assert result['summary']['output_rows'] == 14
    record = next(r for r in result['rows'] if r['student_id'] == '2026001' and r['assessment'] == '期末')
    assert record['score'] == 90 and record['source_count'] == 3
    assert result['excluded'] == []
    assert len(list(csv.reader(io.StringIO(grades.csv_bytes(result).decode('utf-8-sig'))))) == 15


def test_unknown_id_header_does_not_silently_become_student_id():
    mapping = grades.propose_mapping(['账号', '昵称', '课程', '分数'])
    assert not grades.mapping_complete(mapping)
    with pytest.raises(ValueError):
        grades.validate_mapping({'student_id': '不存在', 'score': '分数', 'course_name': '课程'}, ['账号', '昵称', '课程', '分数'])


def test_raw_text_and_leading_zero_preserved(tmp_path):
    file = tmp_path / '中文.csv'
    file.write_text('学号,姓名,课程名称,成绩\n001-02,王　芳,高等数学（上）,85\n', encoding='utf-8')
    tables = grades.read_table(file)
    result = grades.merge(tables, {tables[0]['id']: grades.propose_mapping(tables[0]['headers'])})
    assert result['rows'][0]['student_id'] == '001-02'
    assert result['rows'][0]['source']['raw']['姓名'] == '王　芳'
    assert result['rows'][0]['source']['raw']['课程名称'] == '高等数学（上）'










def test_absent_and_deferred_together_go_to_teacher(tmp_path):
    file = tmp_path / '状态.csv'
    file.write_text('学号,姓名,课程名称,成绩,备注\n001,甲,数学,缺考,因病缓考\n002,乙,数学,缓考,\n', encoding='utf-8')
    tables = grades.read_table(file)
    mappings = {tables[0]['id']: grades.propose_mapping(tables[0]['headers'])}
    result = grades.merge(tables, mappings)
    assert len(result['issues']) == 1 and '缺考' in result['issues'][0]['title'] and '缓考' in result['issues'][0]['title']
    assert [r['status'] for r in result['rows']] == ['缓考']
    fixed = grades.merge(tables, mappings, decisions={result['issues'][0]['id']: {'action': 'correct', 'score': '缓考'}})
    assert [r['status'] for r in fixed['rows']] == ['缓考', '缓考']
