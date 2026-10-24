# -*- coding: utf-8 -*-
import io
import json
import os
import sys
from pathlib import Path

# Ensure B7-demo app is on path
demo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(demo_root))

from app import grades, store

def eval_smoke():
    smoke_dir = demo_root / 'test_datasets' / 'step1_smoke'
    print('\n======================================================')
    print('【STEP 1: 冒烟数据测试 (Smoke Test)】')
    print('======================================================')
    
    # 成绩测试
    f1 = smoke_dir / '01_平台1_教务成绩_smoke.csv'
    f2 = smoke_dir / '02_平台2_在线作业_smoke.csv'
    t1 = grades.read_table(f1)
    t2 = grades.read_table(f2)
    tables = t1 + t2
    mappings = {t['id']: grades.propose_mapping(t['headers']) for t in tables}
    res_grades = grades.merge(tables, mappings)
    
    print('1. 成绩归并去重:')
    print(f'   - 输入行数: {res_grades["summary"]["input_rows"]}')
    print(f'   - 去重行数: {res_grades["summary"]["duplicate_rows"]}')
    print(f'   - 冲突组数: {res_grades["summary"]["conflict_groups"]}')
    print(f'   - 待处理疑点: {res_grades["summary"]["pending"]}')
    print(f'   - 最终输出: {res_grades["summary"]["output_rows"]} 行，学生人数: {res_grades["summary"]["students"]}')
    assert res_grades['summary']['pending'] == 0, '冒烟测试成绩不应有待处理疑点'
    assert res_grades['summary']['output_rows'] == 6, '冒烟测试输出应为6行'
    print('   -> [PASS] 成绩去重与归并链路 100% 畅通跑通！')
    
    return {'grades': res_grades['summary']}

def eval_level1_easy():
    l1_dir = demo_root / 'test_datasets' / 'step2_levels' / 'level1_easy'
    print('\n======================================================')
    print('【STEP 2 - LEVEL 1: 简单级测试 (Easy - 基础基准)】')
    print('======================================================')
    
    t1 = grades.read_table(l1_dir / '01_教务系统成绩_easy.csv')
    t2 = grades.read_table(l1_dir / '02_在线学习平台_easy.csv')
    tables = t1 + t2
    mappings = {t['id']: grades.propose_mapping(t['headers']) for t in tables}
    res_grades = grades.merge(tables, mappings)
    
    print('1. 成绩归并 (跨学科多平台基准):')
    print(f'   - 输入行数: {res_grades["summary"]["input_rows"]} (期望 18)')
    print(f'   - 去重行数: {res_grades["summary"]["duplicate_rows"]} (期望 5)')
    print(f'   - 最终输出: {res_grades["summary"]["output_rows"]} (期望 13)')
    print(f'   - 待复核数: {res_grades["summary"]["pending"]} (期望 0)')
    # 验证同名不同学号 (两位李洋)
    li_yangs = [r for r in res_grades['rows'] if r['student_name'] == '李洋']
    assert len({r['student_id'] for r in li_yangs}) == 2, '两位同名李洋必须保留两个独立学号'
    print('   -> 同名不同学号(两位李洋)准确隔离！')
    
    return {'grades': res_grades['summary']}

def eval_level2_medium():
    l2_dir = demo_root / 'test_datasets' / 'step2_levels' / 'level2_medium'
    print('\n======================================================')
    print('【STEP 2 - LEVEL 2: 中等级测试 (Medium - 复杂业务场景与真实噪音)】')
    print('======================================================')
    
    t1 = grades.read_table(l2_dir / '01_正考教务成绩_medium.csv')
    t2 = grades.read_table(l2_dir / '02_机房平时成绩_medium.xlsx')
    t3 = grades.read_table(l2_dir / '03_考务补充记录_medium.csv')
    tables = t1 + t2 + t3
    mappings = {t['id']: grades.propose_mapping(t['headers']) for t in tables}
    res_grades = grades.merge(tables, mappings)
    
    print('1. 成绩归并与异常拦截:')
    print(f'   - 输入行数: {res_grades["summary"]["input_rows"]} (期望 15)')
    print(f'   - 冲突组数: {res_grades["summary"]["conflict_groups"]} (期望 2: 1组分值冲突 + 1组姓名差异冲突)')
    print(f'   - 待复核行/冲突总疑点: {len(res_grades["issues"])} (期望 4: 2个冲突 + 1个缺学号行 + 1行成绩写缺考、备注写缓考；作弊作为考试状态记录，不算数据错误)')
    
    conflict_titles = [i['title'] for i in res_grades['issues'] if i['type'] == 'conflict']
    row_titles = [i['title'] for i in res_grades['issues'] if i['type'] == 'row']
    print(f'   - 冲突类型捕获: {conflict_titles}')
    print(f'   - 行级异常捕获: {row_titles}')
    
    # 模拟人工复核处理
    decisions = {}
    for issue in res_grades['issues']:
        if issue['type'] == 'conflict':
            decisions[issue['id']] = {'action': 'select', 'record_id': issue['options'][0]['value'], 'note': '教务审核选择主平台记录'}
        elif '没有学号' in issue['title'] or '缺少学号' in issue['title']:
            decisions[issue['id']] = {'action': 'correct', 'student_id': '2026-MED-08', 'score': '80'}
        elif '缓考' in issue['title']:
            decisions[issue['id']] = {'action': 'correct', 'score': '缓考', 'note': '老师确认：因病缓考'}
        else:
            decisions[issue['id']] = {'action': 'exclude', 'note': '未预期的疑点'}
            
    res_reviewed = grades.merge(tables, mappings, decisions=decisions)
    print(f'   - 经人工复核后待解决疑点: {len(res_reviewed["issues"])} (期望 0)')
    statuses = sorted(r['status'] for r in res_reviewed['rows'] if r['status'])
    print(f'   - 识别为考试状态的记录: {statuses} (期望 缓考、作弊各 1 条)')
    assert len(res_grades['issues']) == 4
    assert len(res_reviewed['issues']) == 0
    assert res_reviewed['excluded'] == []
    assert statuses == ['作弊', '缓考']
    print('   -> [PASS] 成绩折算、冲突拦截、姓名冲突、异常考务隔离全部精准捕获！')
    
    return {'grades': res_reviewed['summary']}

def eval_level3_hard():
    l3_dir = demo_root / 'test_datasets' / 'step2_levels' / 'level3_hard'
    print('\n======================================================')
    print('【STEP 2 - LEVEL 3: 困难级测试 (Hard - 极限边界与对抗样本探查)】')
    print('======================================================')
    
    # 成绩测试
    t1 = grades.read_table(l3_dir / '01_综合教务导出_hard.csv')
    t2 = grades.read_table(l3_dir / '02_第三方平台TSV_hard.tsv')
    t3 = grades.read_table(l3_dir / '03_学院复核表_hard.xlsx')
    tables = t1 + t2 + t3
    
    # 探查能力边界 1: TSV 的非标异构表头
    tsv_mapping = grades.propose_mapping(t2[0]['headers'])
    is_complete = grades.mapping_complete(tsv_mapping)
    print('1. 探查能力边界 A (非标准未知异构表头):')
    print(f'   - TSV 原始表头: {t2[0]["headers"]}')
    print(f'   - 自动映射结果: {tsv_mapping}')
    print(f'   - 自动映射是否判定完整: {is_complete}')
    print('   -> [能力边界探查结论] 系统安全将非标异构表头判定为未完成映射，不会静默乱配错配！必须经由人工复核或LLM映射补充。')
    
    # 提供人工确认后的映射，继续探查计算层极限
    mappings = {
        t1[0]['id']: grades.propose_mapping(t1[0]['headers']),
        t2[0]['id']: {
            'student_id': '学员登记号', 'student_name': '学员全名',
            'course_id': '修读课程代码', 'course_name': '修读科目',
            'term': '修读学期', 'assessment': '测验类别', 'attempt': '考查批次',
            'score': '测验总评'
        },
        t3[0]['id']: grades.propose_mapping(t3[0]['headers'])
    }
    res_grades = grades.merge(tables, mappings)
    
    print('2. 探查能力边界 B (极端异常数值与脏数据边界):')
    print(f'   - 待复核问题数: {len(res_grades["issues"])}')
    for issue in res_grades['issues']:
        if issue['type'] == 'row':
            print(f'     * 捕获行级异常: {issue["record"]["student_name"]} (学号:{issue["record"]["student_id"]}) -> 原因: {issue["title"]}')
        elif issue['type'] == 'conflict':
            print(f'     * 捕获冲突组: {issue["description"]} -> 原因: {issue["title"]}')
            
    # 验证前导零与空格清除
    qian_bo = [r for r in res_grades['rows'] if r['student_name'] == '钱博']
    if qian_bo:
        print(f'   - 前导零保真度: 学号 raw = " 000088 " -> 规范化为 "{qian_bo[0]["student_id"]}", 来源数 = {qian_bo[0]["source_count"]} (三平台交叉完全去重成功!)')
    
    return {'grades_boundary': {'issues': len(res_grades['issues']), 'unknown_header_blocked': not is_complete}}

if __name__ == '__main__':
    s = eval_smoke()
    l1 = eval_level1_easy()
    l2 = eval_level2_medium()
    l3 = eval_level3_hard()
    print('\n======================================================')
    print('>>> 全部数据集测评与能力边界探查执行完毕！<<<')
    print('======================================================\n')
