"""What the six office-format test groups needed: zip and folder uploads, rules as a file, platform names from sheet
names, ID-or-name columns read from values, resubmissions, units in column names, retakes and other courses."""
import io
import zipfile

from app import grades, scoring, uploads, workflow

ROSTER = [{'student_id': '001', 'student_name': '甲'}, {'student_id': '002', 'student_name': '乙'}, {'student_id': '003', 'student_name': '李 洋'}]
REQUEST = {'course': 'SYN101'}


def table(name, headers, rows, sheet=''):
    return grades.build_tables(name, [(sheet, [headers] + rows)])[0]


def merge(*pairs):
    return grades.merge([t for t, _ in pairs], {t['id']: m for t, m in pairs}, REQUEST, roster=ROSTER)


def rule(*components, **extra):
    return scoring.normalize({'components': list(components), **extra})


def test_zip_members_keep_chinese_names_and_skip_junk():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('测试A/课堂问答图片/问答_01.png', b'png')
        archive.writestr('测试A/__MACOSX/._x.png', b'junk')
        archive.writestr('测试A/说明.exe', b'x')
        archive.writestr('../escape.csv', b'a,b')
    files, skipped = uploads.unpack_zip('材料.zip', buffer.getvalue(), ('.png', '.csv'), 20)
    assert [p for p, _ in files] == ['材料/测试A/课堂问答图片/问答_01.png', '材料/escape.csv']  # '..' cannot leave the folder
    assert skipped == ['测试A/说明.exe（格式不支持）']


def test_short_names_are_unique_tails():
    assert uploads.short_names(['A班/问答/01.png', 'B班/问答/01.png', 'A班/名单.xlsx']) == ['A班/问答/01.png', 'B班/问答/01.png', '名单.xlsx']


def test_a_rules_document_among_the_materials_is_recognised(tmp_path):
    rules = tmp_path / '1.txt'
    rules.write_text('给分说明\n学习通成绩占20%。作业成绩占15%。期末占25%。缺考按0分。等级换算 A=95。', encoding='utf-8')
    log = tmp_path / '2.txt'
    log.write_text('9月3日 与学生谈话，了解学习情况。', encoding='utf-8')
    files = [{'name': '工作日志.txt', 'path': str(log)}, {'name': '02_给分与内部算分规则.txt', 'path': str(rules)}]
    index, body = uploads.find_rules(files)
    assert index == 1 and '学习通成绩占20%' in body


def test_platform_names_come_from_sheet_names_when_columns_clash():
    xt = table('平台.xlsx', ['账号', '观看得分', '阶段小测'], [['001', '80', '90']], sheet='学习通明细导出')
    mc = table('平台.xlsx', ['学生编号', '观看得分', '单元检验'], [['001', '70', '60']], sheet='慕课明细导出')
    mappings = {xt['id']: {'student_id': '账号', 'item_columns': ['观看得分', '阶段小测']},
                mc['id']: {'student_id': '学生编号', 'item_columns': ['观看得分', '单元检验']}}
    workflow.name_sources([xt, mc], mappings)
    rows = grades.merge([xt, mc], mappings, REQUEST, roster=ROSTER)
    assert not rows['issues']
    assert {r['assessment'] for r in rows['rows']} == {'学习通·观看得分', '学习通·阶段小测', '慕课·观看得分', '慕课·单元检验'}


def test_a_column_holding_ids_and_names_is_found_from_its_values():
    log = table('问答.png', ['记录号', '日期', '题号', '随手记录', '记的是'],
                [['Q1', '9-7', 'Q01', '００１', '学号'], ['Q2', '9-7', 'Q02', '乙', '姓名'], ['Q3', '9-14', 'Q01', '李洋', '姓名'], ['Q4', '9-14', 'Q02', '001', '学号']])
    mapping = workflow.identity_from_values(log, {'student_id': '记录号', 'occurrence': '日期', 'question': '题号', 'events': True, 'item_name': '问答'}, ROSTER)
    assert mapping['student'] == '随手记录' and 'student_id' not in mapping  # 记录号 holds no students
    counted = sorted((r['student_id'], r['occurrence']) for r in merge((log, mapping))['rows'])
    assert counted == [('001', '9-14 Q02'), ('001', '9-7 Q01'), ('002', '9-7 Q02'), ('003', '9-14 Q01')]  # full-width ID, spaced name


def test_latest_graded_submission_counts_and_same_batch_disagreement_is_asked():
    hw = table('作业.docx', ['学号', '任务编号', '提交批次', '登记时间', '评定', '状态'],
               [['001', 'HW01', '1', '2026-09-04 09:00', 'C', '已批改'], ['001', 'HW01', '2', '2026-10-02 09:00', 'A', '已批改'],
                ['002', 'HW01', '1', '2026-09-04 09:00', 'B', '已批改'], ['002', 'HW01', '2', '2026-10-03 09:00', '', '待批改'],
                ['003', 'HW01', '2', '2026-10-04 09:00', 'A', '已批改'], ['003', 'HW01', '2', '2026-10-04 09:00', 'B', '已批改'],
                ['003', 'HW01', '1', '2026-09-04 09:00', 'C', '已批改']])
    mapping = workflow.without_timestamp_occurrence(hw, {'student_id': '学号', 'assessment': '任务编号', 'version': '提交批次',
                                                         'occurrence': '登记时间', 'score': '评定', 'status': '状态'})
    assert 'occurrence' not in mapping
    result = merge((hw, mapping))
    kept = {r['student_id']: r['grade'] for r in result['rows']}
    assert kept == {'001': 'A', '002': 'B'}  # batch 2 replaces 1; a batch still being graded leaves the graded one
    assert len(result['issues']) == 1 and result['issues'][0]['type'] == 'conflict' and '001' not in result['issues'][0]['description']
    assert {o['label'].split(' · ')[0] for o in result['issues'][0]['options']} == {'等级 A', '等级 B'}  # batch 1 does not hide it


def test_units_in_column_names_become_percent():
    assert grades.split_item_header('视频学习(完成率0-1)') == ('视频学习', '', 1.0)
    assert grades.split_item_header('阶段小测(满分20)') == ('阶段小测', '', 20.0)
    assert grades.split_item_header('学习完成率(百分号)') == ('学习完成率', '', 100.0)
    xt = table('超星.xlsx', ['账号', '视频学习(完成率0-1)', '阶段小测(满分20)', '学习完成率(百分号)'],
               [['001', '0.85', '14', '90%'], ['002', '85', '25', '']])
    result = merge((xt, {'student_id': '账号', 'item_columns': ['视频学习(完成率0-1)', '阶段小测(满分20)', '学习完成率(百分号)'], 'source_name': '超星'}))
    scores = {(r['student_id'], r['assessment']): r['score'] for r in result['rows']}
    assert scores == {('001', '超星·视频学习'): 85.0, ('001', '超星·阶段小测'): 70.0, ('001', '超星·学习完成率'): 90.0}
    assert sorted(i['title'] for i in result['issues']) == ['分数 25 超出范围（满分 20）', '分数 85 超出范围（满分 1）']  # never cut to full marks


def test_retake_replaces_first_sitting_when_the_rule_says_so():
    exams = table('考试.pdf', ['学号', '项目', '考试批次', '得分', '考务状态'],
                  [['001', '期末', '初考', '40', '正常'], ['001', '期末', '补考', '68', '正常'], ['002', '期末', '初考', '', '缺考'], ['002', '期末', '补考', '75', '正常']])
    rows = merge((exams, {'student_id': '学号', 'assessment': '项目', 'attempt': '考试批次', 'score': '得分', 'status': '考务状态'}))['rows']
    exam = {'name': '期末', 'assessments': ['期末'], 'weight': 100}
    separate = {t['student_id']: t for t in scoring.compute(rule(exam), rows, ROSTER[:2])['totals']}
    assert separate['001']['total'] == 40 and separate['001']['resits']
    replace = {t['student_id']: t for t in scoring.compute(rule(exam, resit='replace'), rows, ROSTER[:2])['totals']}
    assert replace['001']['total'] == 68 and replace['002']['total'] == 75 and not replace['001']['resits']
    assert any('按补考 68' in n for n in replace['001']['notes'])


def test_records_of_another_course_or_term_are_left_out_and_listed():
    exams = table('考试.pdf', ['学号', '课程', '学期', '项目', '得分'],
                  [['001', 'SYN101', '2026秋', '期中', '60'], ['002', 'SYN101', '2026秋', '期中', '70'], ['003', 'SYN101', '2026秋', '期中', '80'],
                   ['001', 'SYN101', '2026春', '期中', '100'], ['002', 'OTHER201', '2026秋', '期中', '90']])
    rows = merge((exams, {'student_id': '学号', 'course_id': '课程', 'term': '学期', 'assessment': '项目', 'score': '得分'}))['rows']
    told = rule({'name': '期中', 'assessments': ['期中'], 'weight': 100}, scope={'courses': ['SYN101'], 'terms': ['2026秋']})
    computed = scoring.compute(told, rows, ROSTER)
    assert {t['student_id']: t['total'] for t in computed['totals']} == {'001': 60, '002': 70, '003': 80}
    assert len(computed['outside']) == 2
    view = workflow.rule_view(told, rows, ROSTER)
    assert len(view['outside']) == 2 and 'OTHER201' in ' '.join(o['text'] for o in view['outside'])


def test_assignment_weights_apply_when_the_number_is_the_assessment():
    hw = table('作业.docx', ['学号', '任务编号', '评定'], [['001', 'HW01', 'A'], ['001', 'HW02', 'C']])
    rows = merge((hw, {'student_id': '学号', 'assessment': '任务编号', 'score': '评定'}))['rows']
    r = rule({'name': '作业', 'assessments': ['HW01', 'HW02'], 'weight': 100, 'grade_map': {'A': 100, 'C': 60}, 'occurrence_weights': {'HW01': 25, 'HW02': 75}})
    assert scoring.compute(r, rows, ROSTER[:1])['totals'][0]['total'] == 70
