"""Evaluation cases and their answer keys. Everything here is synthetic.

Policy since 2026-10-22: a missing record counts as 0 and is listed for the teacher to confirm, unless the rule says otherwise.

A grades case lists its files with the field mapping a teacher would confirm; pictures and scans also name the clean CSV
they were drawn from. `decisions` are what the teacher decides for the problems planted in the data. The expected records
and totals are not typed in by hand: the runner derives them by running the deterministic engine on the clean inputs with
these mappings, decisions and the `rule`, so the evaluation measures what the model adds or loses.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'fixtures'
CASES = ROOT / 'eval' / 'cases'

COURSE_RULE_A1 = {'components': [
    {'name': '课堂小测', 'assessments': ['小测'], 'weight': 20, 'aggregate': 'drop_lowest_mean', 'drop_lowest': 1, 'full_score': 10, 'missing': 'zero'},
    {'name': '作业', 'assessments': ['作业'], 'weight': 10, 'aggregate': 'mean', 'missing': 'zero'},
    {'name': '课堂答问', 'assessments': ['答问'], 'weight': 10, 'aggregate': 'count', 'full_count': 3, 'missing': 'zero'},
    {'name': '期中', 'assessments': ['期中'], 'weight': 20, 'aggregate': 'mean', 'missing': 'zero'},
    {'name': '期末', 'assessments': ['期末'], 'weight': 40, 'aggregate': 'mean', 'missing': 'zero'},
], 'status_policy': {'缺考': 'zero', '缓考': 'pending'}, 'rounding': {'digits': 0}}

OS_RULE = {'components': [
    {'name': '平时', 'assessments': ['平时'], 'weight': 20, 'aggregate': 'mean', 'missing': 'zero'},
    {'name': '期末', 'assessments': ['期末卷面'], 'weight': 60, 'aggregate': 'mean', 'missing': 'zero'},
    {'name': 'Quiz', 'assessments': ['Quiz'], 'weight': 20, 'aggregate': 'mean', 'missing': 'zero'},
], 'status_policy': {'缺考': 'zero', '作弊': 'invalid'}, 'rounding': {'digits': 0}}
OS_FILES = [
    {'name': '操作系统_成绩汇总.xlsx', 'mapping': {'student_id': 'XH', 'student_name': 'XM', 'remark': '备注', 'item_columns': ['平时(30%)', '期末卷面(70%)']}},
    {'name': '雨课堂_Quiz导出.csv', 'mapping': {'student_id': 'Student No.', 'student_name': 'Name', 'item_columns': ['Quiz 1 (10)', 'Quiz 2 (10)', 'Quiz 3 (10)']}},
]
OS_RULES_TEXT = '期末卷面占六成；平时占两成，平时那栏已经是百分制；雨课堂的三次 Quiz 占两成，取平均。缺考的按零分，作弊的总评作废，四舍五入到整数。'
ROSTER = {'name': '数据结构_课程名单.csv', 'role': 'roster'}

GRADE_CASES = [
    {'id': 'A1', 'title': '数据结构课程总评（演示样例）', 'level': '基础',
     'about': '学习通宽表 + 教务长表 + 手记照片 + 课程名单；同名、录错学号、超满分、名单外学生、分数冲突。',
     'dir': FIXTURES, 'files': [
         {'name': '学习通_小测与作业导出.xlsx', 'mapping': {'student_id': '学号', 'student_name': '姓名', 'item_columns': ['小测1（10分）', '小测2（10分）', '小测3（10分）', '作业1', '作业2']}},
         {'name': '教务_期中期末成绩.csv', 'mapping': {'student_id': '学号', 'student_name': '姓名', 'course_name': '课程名称', 'assessment': '考核项目', 'score': '成绩', 'remark': '备注'}},
         {'name': '课堂答问记录_拍照.png', 'truth': '课堂答问记录_誊录.csv', 'mapping': {'student_name': '姓名', 'assessment': '记录类型', 'occurrence': '日期', 'score': '得分'}},
         ROSTER],
     'request': {'course': '数据结构', 'term': '2026秋', 'compute_total': True,
                 'rules_text': '平时成绩占40%：其中课堂小测20%（三次小测去掉最低一次再取平均，每次满分10分），作业10%（取平均），课堂答问10%（答问满3次得满分）；期中考试占20%，期末考试占40%。缺考按0分计，缓考的学生总评待定。总评四舍五入取整数。'},
     'decisions': [
         {'type': 'conflict', 'name': '张伟', 'select': 94},
         {'type': 'row', 'name': '张伟', 'decision': {'action': 'correct', 'student_id': '2026103'}},
         {'type': 'row', 'name': '孙浩', 'decision': {'action': 'correct', 'student_id': '2026108'}},
         {'type': 'row', 'name': '周雨桐', 'decision': {'action': 'correct', 'score': '10'}},
         {'type': 'row', 'name': '李明', 'decision': {'action': 'exclude', 'note': '名单外学生'}}],
     'rule': COURSE_RULE_A1},
    {'id': 'A2', 'title': '实验课：扫描版 PDF + 教务系统 .xls', 'level': '格式',
     'about': '两页扫描 PDF（第 2 页无表头、带平均分行）+ HTML 冒充的 .xls（标题行、补考、缺考、免修）+ 名单；无预设疑点。',
     'dir': CASES / 'A2', 'files': [
         {'name': '实验成绩登记表_扫描件.pdf', 'truth': '实验成绩登记表_扫描件.pdf.truth.csv', 'mapping': {'student_id': '学号', 'student_name': '姓名', 'item_columns': ['实验1', '实验2', '实验3']}},
         {'name': '教务系统导出_期末成绩.xls', 'mapping': {'student_id': '学号', 'student_name': '姓名', 'course_name': '课程名称', 'attempt': '考试性质', 'score': '成绩', 'remark': '备注'}},
         ROSTER],
     'request': {'course': '数据结构', 'term': '2026秋', 'assessment': '期末', 'compute_total': True,
                 'rules_text': '实验成绩占30%，三次实验取平均，哪次没交就按0分算；期末考试占70%。期末缺考的按0分处理，免修的学生不计算总评。总评保留一位小数。'},
     'decisions': [],
     'rule': {'components': [
         {'name': '实验', 'assessments': ['实验'], 'weight': 30, 'aggregate': 'mean', 'missing': 'zero'},
         {'name': '期末', 'assessments': ['期末'], 'weight': 70, 'aggregate': 'mean', 'missing': 'zero'}],
         'status_policy': {'缺考': 'zero', '免修': 'exempt', '未交': 'zero'}, 'rounding': {'digits': 1}}},
    {'id': 'A3', 'title': '手写考勤表照片（斜拍、手画勾）', 'level': '照片',
     'about': '列名只有日期的手写考勤照片，同名学生写了班级、名单外学生；期末成绩表；考勤按次数折算。',
     'dir': CASES / 'A3', 'files': [
         {'name': '课堂考勤登记表_手写.jpg', 'truth': '课堂考勤登记表_手写.jpg.truth.csv',
          'mapping': {'student_name': '姓名', 'item_columns': ['9/1', '9/8', '9/15', '9/22', '9/29', '10/13', '10/20', '10/27'], 'item_name': '考勤'}},
         {'name': '期末成绩.csv', 'mapping': {'student_id': '学号', 'student_name': '姓名', 'score': '期末成绩'}},
         ROSTER],
     'request': {'course': '数据结构', 'term': '2026秋', 'assessment': '期末', 'compute_total': True,
                 'rules_text': '考勤占20%：本学期一共点名8次，按到课次数折算，全勤得满分；期末考试占80%。总评取整数。'},
     'decisions': [
         {'type': 'row', 'name': '1班', 'decision': {'action': 'correct', 'student_id': '2026103'}},
         {'type': 'row', 'name': '2班', 'decision': {'action': 'correct', 'student_id': '2026104'}},
         {'type': 'row', 'name': '李明', 'decision': {'action': 'exclude', 'note': '旁听，不在名单'}}],
     'rule': {'components': [
         {'name': '考勤', 'assessments': ['考勤'], 'weight': 20, 'aggregate': 'count', 'full_count': 8, 'missing': 'zero'},
         {'name': '期末', 'assessments': ['期末'], 'weight': 80, 'aggregate': 'mean', 'missing': 'zero'}],
         'rounding': {'digits': 0}}},
    {'id': 'A4', 'title': '陌生表头 + 口语化规则', 'level': '表述',
     'about': '拼音首字母表头、英文平台导出、表头里写权重、备注里写缺考/作弊、前导零学号，没有名单；规则用“六成”“两成”。',
     'dir': CASES / 'A4', 'files': OS_FILES,
     'request': {'course': '操作系统', 'term': '2026秋', 'compute_total': True, 'rules_text': OS_RULES_TEXT},
     'decisions': [], 'rule': OS_RULE},
    {'id': 'A5', 'title': '规则里有系统做不到的要求', 'level': '边界',
     'about': '同 A4 数据，规则多了“酌情加分”和“期末不到40分按期末记”：模型应指出这些说法需要老师处理，而不是编造计算。',
     'dir': CASES / 'A5', 'files': OS_FILES,
     'request': {'course': '操作系统', 'term': '2026秋', 'compute_total': True,
                 'rules_text': OS_RULES_TEXT + '课堂表现特别好的同学可以酌情加1到3分；期末卷面不到40分的，总评直接按期末卷面分记。'},
     'decisions': [], 'rule': OS_RULE, 'expect_unclear': [('表现', '加分', '酌情'), ('40',)]},
]

COUNSELOR_SCHEME = [
    {'id': 'I1', 'group': '学生党建和思想政治教育', 'name': '学生党建工作', 'max': 10, 'method': 'judge', 'criteria': [
        {'level': '优秀', 'score': 10, 'description': '党员发展有年度计划且程序记录完整，全年组织党员教育活动不少于3次并有记录'},
        {'level': '良好', 'score': 8, 'description': '有发展计划，组织党员教育活动1至2次'},
        {'level': '一般', 'score': 6, 'description': '只有零散记录，没有发展计划'},
        {'level': '较差', 'score': 3, 'description': '基本没有可证明的材料'}]},
    {'id': 'I2', 'group': '学生党建和思想政治教育', 'name': '思想政治教育', 'max': 10, 'method': 'judge'},
    {'id': 'I3', 'group': '学生日常管理', 'name': '工作记录', 'max': 15, 'method': 'checklist', 'required': ['辅导员工作日志', '谈话记录', '值班记录'], 'deduct': 5},
    {'id': 'I4', 'group': '学生日常管理', 'name': '安全稳定与宿舍管理', 'max': 15, 'method': 'judge'},
    {'id': 'I5', 'group': '拔尖人才培养', 'name': '学生竞赛获奖', 'max': 10, 'method': 'count', 'points': {'省级及以上': 2}, 'cap': 10},
    {'id': 'I6', 'group': '拔尖人才培养', 'name': '科技创新讲座', 'max': 10, 'method': 'count', 'points': 2.5, 'cap': 10},
    {'id': 'I7', 'group': '心理健康教育', 'name': '心理工作队伍', 'max': 5, 'method': 'checklist', 'required': ['年级心理委员名单', '心理健康普测组织材料'], 'deduct': 3},
    {'id': 'I8', 'group': '心理健康教育', 'name': '心理健康工作规范', 'max': 10, 'method': 'judge', 'criteria': [
        {'level': '优秀', 'score': 10, 'description': '开展心理辅导有工作记录，危机信息按流程及时上报'},
        {'level': '良好', 'score': 7, 'description': '有辅导记录，但上报记录不完整'},
        {'level': '一般', 'score': 4, 'description': '仅有零散记录'}]},
    {'id': 'I9', 'group': '队伍建设', 'name': '理论研究成果', 'max': 15, 'method': 'count', 'points': {'核心期刊': 5, 'CN期刊': 3}, 'cap': 15},
]

CHALLENGE = {'event': '第十九届“挑战杯”河南省大学生课外学术科技作品竞赛', 'project': '智慧校园能耗监测系统', 'level': '省级'}
PAPER = '新时代高校辅导员谈心谈话工作的实践路径'
# Original file -> what the evaluator should end up with. `flag` marks the materials the system is expected to point out.
COUNSELOR_MATERIALS = {
    '王敏_党员发展计划与教育活动记录.txt': {'person': '王敏', 'indicator': 'I1'},
    '王敏_思政主题教育记录.txt': {'person': '王敏', 'indicator': 'I2'},
    '王敏_辅导员工作日志_节选.txt': {'person': '王敏', 'indicator': 'I3', 'doc_type': '辅导员工作日志'},
    '王敏_谈话记录汇总.txt': {'person': '王敏', 'indicator': 'I3', 'doc_type': '谈话记录'},
    '王敏_值班记录.csv': {'person': '王敏', 'indicator': 'I3', 'doc_type': '值班记录'},
    '王敏_宿舍检查与安全教育.txt': {'person': '王敏', 'indicator': 'I4'},
    '王敏_获奖证书_挑战杯省赛_学生1.png': {'person': '王敏', 'indicator': 'I5', **CHALLENGE, 'flag': '多人申报'},
    '王敏_获奖证书_挑战杯省赛_学生2.png': {'person': '王敏', 'indicator': 'I5', **CHALLENGE, 'flag': '多人申报'},
    '王敏_获奖证书_数学建模国赛.png': {'person': '王敏', 'indicator': 'I5', 'event': '全国大学生数学建模竞赛', 'project': '共享单车动态调度模型', 'level': '国家级'},
    '王敏_科技讲座通知_第1期.txt': {'person': '王敏', 'indicator': 'I6', 'event': '科技创新系列讲座第1期'},
    '王敏_科技讲座通知_第2期.txt': {'person': '王敏', 'indicator': 'I6', 'event': '科技创新系列讲座第2期'},
    '王敏_心理委员名单.csv': {'person': '王敏', 'indicator': 'I7', 'doc_type': '年级心理委员名单'},
    '王敏_心理工作记录.txt': {'person': '王敏', 'indicator': 'I8'},
    '李强_工作日志.txt': {'person': '李强', 'indicator': 'I3', 'doc_type': '辅导员工作日志'},
    '李强_值班记录.csv': {'person': '李强', 'indicator': 'I3', 'doc_type': '值班记录'},
    '李强_党建活动记录.txt': {'person': '李强', 'indicator': 'I1'},
    '李强_主题班会记录.txt': {'person': '李强', 'indicator': 'I2'},
    '李强_获奖证书_挑战杯省赛.png': {'person': '李强', 'indicator': 'I5', **CHALLENGE, 'flag': '多人申报', 'excluded': True},
    '李强_获奖证书_校程序设计赛.png': {'person': '李强', 'indicator': 'I5', 'event': '示例大学程序设计竞赛', 'level': '校级', 'flag': '计分范围'},
    '李强_论文_核心期刊.txt': {'person': '李强', 'indicator': 'I9', 'project': PAPER, 'level': '核心期刊'},
    '李强_论文_CN期刊转载.txt': {'person': '李强', 'indicator': 'I9', 'project': PAPER, 'level': 'CN期刊'},
    '赵琳_工作日志.txt': {'person': '赵琳', 'indicator': 'I3', 'doc_type': '辅导员工作日志'},
    '赵琳_谈话记录.txt': {'person': '赵琳', 'indicator': 'I3', 'doc_type': '谈话记录'},
    '赵琳_值班记录.csv': {'person': '赵琳', 'indicator': 'I3', 'doc_type': '值班记录'},
    '赵琳_宿舍安全检查记录.txt': {'person': '赵琳', 'indicator': 'I4'},
    '赵琳_科技讲座通知.txt': {'person': '赵琳', 'indicator': 'I6', 'event': '大学生创新创业训练计划项目经验交流会'},
    '赵琳_心理委员名单.csv': {'person': '赵琳', 'indicator': 'I7', 'doc_type': '年级心理委员名单'},
    '赵琳_心理普测通知.txt': {'person': '赵琳', 'indicator': 'I7', 'doc_type': '心理健康普测组织材料'},
    '赵琳_心理辅导与危机上报工作记录.txt': {'person': '赵琳', 'indicator': 'I8'},
    '活动照片说明_未署名.txt': {'person': '', 'indicator': 'I4', 'flag': '属于哪位', 'excluded': True},
}
# Scores the evaluator gives for judged items, and the level an expert reading the criteria would pick
# (王敏 I1 is debatable: the plan claims the procedure was followed, but the records themselves are not attached).
COUNSELOR_JUDGEMENTS = {'王敏::I1': 10, '王敏::I2': 9, '王敏::I4': 14, '王敏::I8': 10, '李强::I1': 6, '李强::I2': 7, '李强::I4': 10,
                        '李强::I8': 0, '赵琳::I1': 0, '赵琳::I2': 6, '赵琳::I4': 12, '赵琳::I8': 10}
COUNSELOR_LEVELS = {'王敏::I1': {'level': '优秀', 'debatable': True}, '李强::I1': {'level': '一般'}, '王敏::I8': {'level': '优秀'}, '赵琳::I8': {'level': '优秀'}}


def renamed(mapping):
    from .make_cases import B3_FORMAT
    return {B3_FORMAT[k][0]: dict(v) for k, v in mapping.items()}


APPRAISAL_CASES = [
    {'id': 'B1', 'title': '辅导员年度考核（演示样例）', 'level': '基础',
     'about': '9 项指标、3 人 30 份材料；同一项目两张证书、两人申报同一项目、同一论文两刊、校级奖、未署名材料、缺材料。文件名带姓名。',
     'dir': FIXTURES / 'appraisal', 'scheme_file': '00_学院辅导员考核方案_示例.txt', 'people': ['王敏', '李强', '赵琳'],
     'scheme': COUNSELOR_SCHEME, 'materials': COUNSELOR_MATERIALS, 'judgements': COUNSELOR_JUDGEMENTS, 'levels': COUNSELOR_LEVELS},
    {'id': 'B3', 'title': '辅导员考核：文件名无姓名 + 混合格式', 'level': '格式',
     'about': '同 B1 的材料，改成“扫描文档_01.pdf”“新建文档.docx”“IMG_0412.jpg”这类文件名，部分转成 PDF/Word/扫描件，只能靠内容判断归属。',
     'dir': CASES / 'B3', 'scheme_dir': FIXTURES / 'appraisal', 'scheme_file': '00_学院辅导员考核方案_示例.txt', 'people': ['王敏', '李强', '赵琳'],
     'scheme': COUNSELOR_SCHEME, 'materials': None, 'judgements': COUNSELOR_JUDGEMENTS, 'levels': COUNSELOR_LEVELS},
]
APPRAISAL_CASES[1]['materials'] = renamed(COUNSELOR_MATERIALS)
# Without the name in the file name these two lists name no counselor at all: “undecided” plus a flag is the right reading.
for _name in ('心理委员名单.csv', '心理委员名单(1).csv'):
    APPRAISAL_CASES[1]['materials'][_name].update(read_person='', flag='属于哪位')
CASE_INDEX = {c['id']: c for c in GRADE_CASES + APPRAISAL_CASES}
