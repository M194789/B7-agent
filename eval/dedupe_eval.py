"""How well “same achievement or not” is judged, on materials whose answer is known (eval/dedupe_cases).

Every material is read with the real model the way a task reads it, then related; every pair within one person and
one indicator is compared with the labelled answer. Two kinds of error are counted apart, since they cost differently:
two different achievements merged (the person loses points) and one achievement counted twice (gains points).
Usage (model from B7_LLM_BASE_URL / B7_LLM_MODEL / B7_LLM_API_KEY): python -m eval.dedupe_eval
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app import appraisal, appraisal_flow, dedupe

CASES = Path(__file__).parent / 'dedupe_cases'
SCHEME = appraisal.normalize_scheme({'indicators': [
    {'id': 'I5', 'group': '拔尖', 'name': '学生竞赛获奖', 'max': 10, 'method': 'count', 'points': {'省级及以上': 2}, 'cap': 10},
    {'id': 'I9', 'group': '队伍', 'name': '理论研究成果', 'max': 15, 'method': 'count', 'points': {'核心期刊': 5, 'CN期刊': 3}, 'cap': 15}]})
NAMES = {'same_award': '同一奖项', 'same_work': '同一作品不同奖项', 'different': '不同成果', 'unsure': '判断不了'}


def main():
    truth = json.loads((CASES / 'truth.json').read_text(encoding='utf-8'))
    files = sorted(p for p in CASES.glob('*.txt'))
    entries = [{'name': p.name, 'path': str(p)} for p in files]
    with ThreadPoolExecutor(max_workers=4) as pool:
        materials = list(pool.map(lambda pair: appraisal_flow.read_one(pair[0], pair[1], SCHEME['indicators'], ['王敏']), enumerate(entries)))
    for m in materials:
        print(f'{m["file"]:<22} 指标 {m["indicator"] or "—":<3} 编号 {m.get("cert_no", "")[:20]:<20} 比赛 {m.get("contest", "")[:24]:<24} 作品 {m.get("project", "")[:26]:<26} 等级 {m.get("award", "")}')
    relations = dedupe.relate(materials, SCHEME['indicators'])
    found = {r['key']: r for r in relations}
    expect = {}
    for kind in ('same_award', 'same_work'):
        for a, b in truth[kind]:
            expect['|'.join(sorted([a, b]))] = kind
    indicator_of = {m['file']: m['indicator'] for m in materials}
    want_indicator = {m['file']: 'I9' if m['file'].startswith('p') else 'I5' for m in materials}
    rows, tally = [], {'correct': 0, 'merged_wrongly': 0, 'counted_twice': 0, 'award_vs_work': 0, 'unsure': 0}
    names = sorted(m['file'] for m in materials)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if want_indicator[a] != want_indicator[b]:
                continue
            key = '|'.join([a, b])
            want = expect.get(key, 'different')
            r = found.get(key)
            got = r['relation'] if r else 'different'  # not listed: the program and the model both found them different
            if indicator_of[a] != indicator_of[b]:
                got = 'different'
            if got == want:
                tally['correct'] += 1
            elif got == 'unsure':
                tally['unsure'] += 1
            elif want == 'different':
                tally['merged_wrongly'] += 1
            elif got == 'different':
                tally['counted_twice'] += 1
            else:
                tally['award_vs_work'] += 1
            rows.append((key, NAMES[want], NAMES[got], (r or {}).get('by', '非候选'), (r or {}).get('reason', '')))
    print()
    for key, want, got, by, reason in rows:
        mark = '✓' if want == got else '✗'
        print(f'{mark} {key:<44} 答案 {want:<8} 判断 {got:<8} {by:<6} {reason[:60]}')
    total = len(rows)
    print(f'\n共 {total} 对：正确 {tally["correct"]}；把不同成果合并（少算分）{tally["merged_wrongly"]}；把同一成果算两次（多算分）{tally["counted_twice"]}；'
          f'同一奖项与同一作品不同奖项混淆 {tally["award_vs_work"]}；交给评分人判断 {tally["unsure"]}')
    tiers = {k: sum(1 for r in relations if r.get('confidence') == k) for k in dedupe.CONFIDENCE}
    print(f'列给评分人看的 {len(relations)} 对（其余 {total - len(relations)} 对确定是不同成果，不列出）：程序规则 {sum(1 for r in relations if r["by"] == "rule")} 对，'
          f'模型 {sum(1 for r in relations if r["by"] == "model")} 对；确定 {tiers["certain"]}，请核对 {tiers["check"]}，必须人工判断 {tiers["unsure"]}')
    for r in relations:
        if r.get('confidence') != 'certain':
            print('   需要看：', r['key'], NAMES[r['relation']], '|', '；'.join(r.get('conflicts') or []))


if __name__ == '__main__':
    main()
