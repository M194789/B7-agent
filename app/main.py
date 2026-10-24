from __future__ import annotations

import json
import mimetypes
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import appraisal, appraisal_flow, dedupe, documents, export_xlsx, grades, intake, model, scoring, store, versions, workflow
from . import uploads as uploads_mod

pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='b7-task')
MAX_FILES = 40
UPLOAD_MB = 20
TABLE_SUFFIXES = ('.csv', '.tsv', '.xlsx', '.xls')
SUFFIXES = TABLE_SUFFIXES + appraisal_flow.TEXT_SUFFIXES + documents.IMAGE_SUFFIXES + documents.DOCUMENT_SUFFIXES
NEEDS_MODEL = documents.IMAGE_SUFFIXES + ('.pdf',)
EXPORTS = ('results.xlsx', 'grades.csv', 'totals.csv', 'summary.csv', 'audit.json', 'report.html')
FLOWS = {'grades': workflow, 'appraisal': appraisal_flow}
XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
FIXTURE_DIR = store.ROOT / 'fixtures'
DEMOS = {
    'course': {'name': '数据结构课程总评 · 合成样例', 'files': ['学习通_小测与作业导出.xlsx', '教务_期中期末成绩.csv', '课堂答问记录_拍照.png', '数据结构_课程名单.csv'],
               'rules_text': '平时成绩占40%：其中课堂小测20%（三次小测去掉最低一次再取平均，每次满分10分），作业10%（取平均），课堂答问10%（答问满3次得满分）；期中考试占20%，期末考试占40%。缺考按0分计，缓考的学生总评待定。总评四舍五入取整数。'},
    'appraisal': {'name': '辅导员年度考核评分 · 合成样例', 'dir': 'appraisal', 'scheme': '00_学院辅导员考核方案_示例.txt'},
    'grades': {'name': '多平台成绩归并 · 合成样例', 'files': ['平台A_教务成绩.csv', '平台B_课程考核.csv', '平台C_补充记录.csv'], 'rules_text': ''},
}
FIXTURES = {name for key in ('course', 'grades') for name in DEMOS[key]['files']}
_running, _running_lock = {}, threading.Lock()


def submit(task_id, resume=None):
    """Queue a run. Runs are serialised by the single worker; the callers check the task's status first, so a run that
    is just finishing (status already settled, thread not yet returned) does not block the next one."""
    with _running_lock:
        _running[task_id] = _running.get(task_id, 0) + 1
    def execute():
        try:
            task = store.get_task(task_id)
            if task and task['kind'] in FLOWS:
                FLOWS[task['kind']].run(task_id, resume)
        finally:
            with _running_lock:
                _running[task_id] -= 1
                if not _running[task_id]:
                    del _running[task_id]
    pool.submit(execute)


@asynccontextmanager
async def lifespan(app):
    global pool
    if pool._shutdown:
        # A previous app lifetime in the same process (e.g. a second test client) shut the worker down.
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='b7-task')
    store.init()
    for task in store.list_tasks():
        if task['kind'] in FLOWS and task['status'] in ('queued', 'running'):
            submit(task['id'])
    yield
    pool.shutdown(wait=True, cancel_futures=False)


app = FastAPI(title='知衡 · 教学数据工作台', version='0.2.0', lifespan=lifespan)


@app.middleware('http')
async def local_origin(request: Request, call_next):
    origin = request.headers.get('origin')
    if origin and origin not in (f'http://{request.headers.get("host")}', f'https://{request.headers.get("host")}'):
        return JSONResponse({'detail': '此本地工作台不接受跨来源请求。'}, status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    if not request.url.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-cache'  # the page script changes with each update; always check for a new one
    return response


@app.exception_handler(ValueError)
async def invalid_value(request, error):
    return JSONResponse({'detail': str(error)}, status_code=400)


def require_task(task_id):
    task = store.get_task(task_id)
    if not task or task['kind'] not in FLOWS:
        raise HTTPException(404, '没有找到此任务。')
    return task


@app.get('/api/health')
def health():
    return {'status': 'ok', 'name': '知衡', 'version': '0.2.0', 'model': model.status()}


@app.get('/api/config')
def config():
    return {'model': model.status(), 'fields': grades.FIELDS, 'kinds': intake.KINDS, 'methods': appraisal.METHODS,
            'presets': {
                'deepseek': {'base_url': 'https://api.deepseek.com', 'model': 'deepseek-flash', 'docs': 'https://api-docs.deepseek.com/'},
                'qwen': {'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'model': 'qwen3.8-max', 'docs': 'https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope'},
            }, 'limits': {'upload_mb': UPLOAD_MB, 'files': MAX_FILES, 'table_rows': 10000},
            'demos': {k: {'name': v['name']} for k, v in DEMOS.items()},
            'prefs': store.pref_get('user') or {'identity': '', 'flow': ''}, 'identities': IDENTITIES,
            'templates': [{'id': t['id'], 'kind': t['kind'], 'name': t['name'], 'created_at': t['created_at'], 'text': t['payload']['text']}
                          for t in store.templates()]}


IDENTITIES = ['任课教师', '辅导员', '研究生导师', '教学秘书 / 教务', '考核小组成员', '其他']


class Prefs(BaseModel):
    identity: str = Field(default='', max_length=20)
    flow: str = Field(default='', max_length=20)


@app.post('/api/prefs')
def save_prefs(value: Prefs):
    """“我是辅导员，平时做考核评分”: the usual flow is preselected next time (the model is not asked which flow it is),
    and can still be changed for any one task. The identity alone never decides the flow."""
    if value.flow not in ('', *intake.KINDS):
        raise ValueError('没有这个流程。')
    prefs = {'identity': value.identity.strip(), 'flow': value.flow}
    store.pref_put('user', prefs)
    return prefs


class TemplateName(BaseModel):
    name: str = Field(min_length=1, max_length=60)


@app.post('/api/tasks/{task_id}/template', status_code=201)
def save_template(task_id: str, value: TemplateName):
    """Keep the rule this task ended with (as confirmed, with its edits), to start a later task from it. Only the rule
    is kept: no score, decision or material goes into a template."""
    task = require_task(task_id)
    if task['status'] != 'completed':
        raise HTTPException(409, '任务完成、规则经你确认后才能保存为模板。')
    result = task['result']
    if task['kind'] == 'grades':
        if not result.get('rule'):
            raise ValueError('这个任务没有评分规则。')
        payload = {'text': workflow.rules_now(task), 'rule': {k: v for k, v in result['rule'].items() if k != 'source_text'}}
    else:
        payload = {'text': appraisal_flow.rules_now(task), 'scheme': {k: v for k, v in result['scheme'].items() if k != 'source_text'}}
    return {'id': store.template_put(task['kind'], value.name.strip(), payload)}


@app.delete('/api/templates/{template_id}')
def delete_template(template_id: str):
    store.template_drop(template_id)
    return {'ok': True}


class ModelConfig(BaseModel):
    base_url: str = Field(max_length=500)
    model: str = Field(max_length=150)
    api_key: str = Field(default='', max_length=1000)


@app.post('/api/settings/model')
def save_model(value: ModelConfig):
    model.configure(value.base_url, value.model, value.api_key)
    return model.status()


@app.delete('/api/settings/model')
def clear_model():
    model.clear()
    return model.status()


@app.post('/api/settings/model/test')
def test_model():
    result = model.ask_json('返回 {"ok":true}。', {'task': '连接测试'})
    if result.get('ok') is not True:
        raise ValueError('服务可以访问，但未返回预期的JSON结构。')
    return {'ok': True, 'model': model.status()['model']}


@app.get('/api/tasks')
def tasks():
    return [{'id': t['id'], 'name': t['name'], 'kind': t['kind'], 'status': t['status'], 'step': t['step'],
             'created_at': t['created_at'], 'updated_at': t['updated_at'], 'summary': t['result'].get('summary', {}),
             'llm_used': t['llm_used'], 'error': t['error']} for t in store.list_tasks() if t['kind'] in FLOWS]


@app.get('/api/tasks/{task_id}')
def task_detail(task_id: str):
    task = require_task(task_id)
    task['version'] = versions.number(task)
    task['state'] = versions.result_state(task)
    if task['status'] not in ('queued', 'running', 'cancelled'):
        try:
            task['rules_now'] = FLOWS[task['kind']].rules_now(task)
        except Exception:  # an old task without a checkpoint
            task['rules_now'] = task['request'].get('rules_text') or task['request'].get('scheme_text', '')
    # Filesystem paths are kept server-side. Only names and file indexes are returned.
    task['files'] = [{'name': f['name'], 'index': i, 'role': f.get('role', '')} for i, f in enumerate(task['files'])]
    return task


def start_task(kind, name, rules_text, files, course='', people=None, reason='', tid=None, sample=False, notes=(), report=None):
    """Create and queue a task of the detected kind. `files` are already stored under the task's input folder."""
    configured = model.status()['configured']
    rules_text = grades.text(rules_text)[:6000]
    detected = {'kind': kind, 'label': intake.KINDS[kind], 'reason': reason}
    if kind == 'appraisal':
        if not rules_text:
            raise ValueError('工作考核需要考核方案：请把方案原文粘贴到“评分规则”中。')
        if not configured:
            raise ValueError('阅读证明材料需要模型，请先在“模型设置”中连接模型。')
        people = people or intake.people_from_names([f['name'] for f in files])
        request = {'scheme_text': rules_text, 'people': people, 'use_model': True, 'detected': detected}
    else:
        if not configured and (rules_text or any(Path(f['path']).suffix.lower() in NEEDS_MODEL for f in files)):
            raise ValueError('理解评分规则、识别照片和 PDF 需要模型，请先在“模型设置”中连接模型。')
        request = {'rules_text': rules_text, 'course': grades.text(course)[:100], 'term': '2026秋', 'assessment': '期末', 'attempt': '初考',
                   'use_model': configured, 'detected': detected}
    if sample:
        request['synthetic_sample'] = True
    if report:
        request['upload_report'] = {k: v for k, v in report.items() if k != 'template'}
        if report.get('template'):
            request['template'] = report['template']
    store.create_task(name or ('工作考核评分' if kind == 'appraisal' else '成绩整合'), kind, request, files, tid)
    for index, note in enumerate(notes):
        store.event(tid, f'upload_note:{index}', note)
    submit(tid)
    return {'id': tid, 'kind': kind}


@app.post('/api/tasks', status_code=201)
async def create(request: Request):
    """The single entrance: any mix of tables, photos, PDFs and documents plus the user's rules in their own words."""
    form = await request.form()
    uploads = [f for f in form.getlist('files') if hasattr(f, 'read') and f.filename]
    if not uploads:
        raise ValueError('请上传材料：成绩表、照片、PDF、证明材料都可以。')
    received, skipped = await read_uploads(uploads)
    # The same file twice (dragged in again, or also inside the zip) is read and counted once.
    received, duplicates = uploads_mod.unique_contents(received)
    if len(received) > MAX_FILES:
        raise ValueError(f'每个任务最多 {MAX_FILES} 个文件（压缩包和文件夹按里面的文件计），这次有 {len(received)} 个。')
    if len({p for p, _ in received}) < len(received):
        raise ValueError('上传文件存在相同文件名，请分别重命名以便保留清晰的来源。')
    tid = uuid.uuid4().hex
    directory = store.DATA / 'tasks' / tid / 'input'
    directory.mkdir(parents=True)
    files = []
    for index, (name, (_, content)) in enumerate(zip(uploads_mod.short_names([p for p, _ in received]), received)):
        path = directory / f'{index}{Path(name).suffix.lower()}'
        path.write_bytes(content)
        files.append({'name': name[:180], 'path': str(path), 'role': ''})
    rules_text, notes, rules_file = str(form.get('rules_text', '')), [], ''
    if not grades.text(rules_text):
        found = uploads_mod.find_rules(files)
        if found:
            index, rules_text = found
            rules_file = files.pop(index)['name']
            notes.append(f'把“{rules_file}”当作评分规则（规则框是空的）')
    if skipped:
        notes.append('压缩包中未处理：' + '、'.join(skipped[:10]) + ('等' if len(skipped) > 10 else ''))
    for copy, original in duplicates:
        notes.append(f'“{copy}”与“{original}”内容完全相同，只处理一次')
    report = {'duplicates': [{'name': c, 'same_as': o} for c, o in duplicates], 'skipped': skipped,
              'rules_file': rules_file}
    kind = str(form.get('kind', ''))
    template = store.template_get(str(form.get('template', ''))) if form.get('template') else None
    if template and kind not in intake.KINDS:
        kind = template['kind']
    if template and template['kind'] != kind:
        template = None
    if template and versions.same_text(template['payload']['text'], rules_text):
        # The same rules as a confirmed template: its confirmed reading is the draft (checked again against this data).
        report['template'] = {'id': template['id'], 'name': template['name'], **{k: template['payload'][k] for k in ('rule', 'scheme') if k in template['payload']}}
    if kind in intake.KINDS:
        reason = {'pref': '按你设置的常用流程', 'template': '按所选规则模板'}.get(str(form.get('kind_source', '')), '由你指定')
    else:
        kind, reason = intake.classify(rules_text, [f['name'] for f in files])
    return start_task(kind, str(form.get('name', '')).strip()[:100], rules_text, files, str(form.get('course', '')),
                      intake.people_from_text(str(form.get('people', ''))), reason, tid, notes=notes, report=report)


async def read_uploads(uploads):
    """(path, bytes) of every file sent. Loose files keep the folder path the browser sent
    ('测试A/课堂问答图片/问答登记_01.png'); zips are unpacked."""
    received, skipped = [], []
    for upload in uploads:
        path = uploads_mod.clean_path(upload.filename)
        suffix = path.suffix.lower()
        if suffix != '.zip' and suffix not in SUFFIXES:
            raise ValueError(f'不支持“{path.name}”的格式。支持表格（CSV/XLS/XLSX）、照片（JPG/PNG）、PDF、Word(.docx)、TXT 和 zip 压缩包。旧版 .doc 请另存为 .docx 或 PDF。')
        limit = (uploads_mod.ZIP_TOTAL_MB if suffix == '.zip' else UPLOAD_MB) * 1024 * 1024
        content = await upload.read(limit + 1)
        if not content or len(content) > limit:
            raise ValueError(f'“{path.name}”为空或超过 {limit // 1024 // 1024}MB。')
        if suffix == '.zip':
            inner, passed = uploads_mod.unpack_zip(str(path), content, SUFFIXES, UPLOAD_MB)
            received += inner
            skipped += passed
        else:
            received.append((str(path), content))
    if not received:
        raise ValueError('压缩包里没有可处理的材料：' + '、'.join(skipped[:5]))
    return received, skipped


def changeable(task):
    if task['status'] in ('queued', 'running'):
        raise HTTPException(409, '任务正在处理。要修改，请先点“中止”，等它停下后再改。')
    if task['status'] == 'cancelled':
        raise HTTPException(409, '这个任务已改为另一种流程处理，请到新任务中修改。')


@app.post('/api/tasks/{task_id}/modify', status_code=202)
async def modify(task_id: str, request: Request):
    """Add, replace or remove materials, change the rules, or take back decisions, at any stage. A new version is
    processed from what is still valid: unchanged files are not read again, earlier decisions are kept while the
    problem they answered is the same, and a confirmed result is marked as replaced until the new one is confirmed."""
    task = require_task(task_id)
    changeable(task)
    form = await request.form()
    try:
        remove = {int(i) for i in json.loads(str(form.get('remove') or '[]'))}
        revoke = [str(x) for x in json.loads(str(form.get('revoke') or '[]'))][:50]
    except (ValueError, TypeError):
        raise ValueError('修改内容的格式不正确。') from None
    rules_text = form.get('rules_text')
    rules_text = None if rules_text is None else grades.text(str(rules_text))[:6000]
    uploads = [f for f in form.getlist('files') if hasattr(f, 'read') and f.filename]
    received, skipped = await read_uploads(uploads) if uploads else ([], [])
    kept = [f for i, f in enumerate(task['files']) if i not in remove]
    removed = [f['name'] for i, f in enumerate(task['files']) if i in remove]
    hashes = {uploads_mod.digest(Path(f['path']).read_bytes()): f['name'] for f in kept}
    added, replaced, same = [], [], []
    directory = store.DATA / 'tasks' / task_id / 'input'
    received, copies = uploads_mod.unique_contents(received)
    for name, content in zip(uploads_mod.short_names([p for p, _ in received]), [c for _, c in received]):
        name = name[:180]
        digest = uploads_mod.digest(content)
        if digest in hashes:
            same.append({'name': name, 'same_as': hashes[digest]})
            continue
        old = next((f for f in kept if f['name'] == name), None)
        if old:
            kept.remove(old)  # the same name with new content: the new file replaces the old one
            replaced.append(name)
        path = directory / f'{uuid.uuid4().hex[:10]}{Path(name).suffix.lower()}'
        path.write_bytes(content)
        kept.append({'name': name, 'path': str(path), 'role': ''})
        hashes[digest] = name
        if name not in replaced:
            added.append(name)
    if not kept:
        raise ValueError('删除后没有材料了。要换一批材料，请新建任务。')
    if len(kept) > MAX_FILES:
        raise ValueError(f'每个任务最多 {MAX_FILES} 个文件，修改后有 {len(kept)} 个。')
    flow = FLOWS[task['kind']]
    seed, rules, rules_changed = flow.carry(task, rules_text, revoke)
    if not (added or replaced or removed or rules_changed or revoke or form.get('reopen')):
        raise ValueError('没有发现修改：' + ('上传的文件与已有材料内容相同。' if same else '请添加或删除材料、修改规则，或撤回一项处理。'))
    report = dict(task['request'].get('upload_report') or {})
    names = {f['name'] for f in kept}
    report['duplicates'] = [d for d in report.get('duplicates') or [] if d['same_as'] in names] + same + [{'name': c, 'same_as': o} for c, o in copies]
    report['skipped'] = (report.get('skipped') or []) + skipped
    seed['changes'] = {**seed.get('changes', {}), 'files_added': added, 'files_replaced': replaced, 'files_removed': removed, 'files_same': same}
    key = 'rules_text' if task['kind'] == 'grades' else 'scheme_text'
    if task['kind'] == 'grades' and not model.status()['configured'] and (grades.text(rules) or any(Path(f['path']).suffix.lower() in NEEDS_MODEL for f in kept)):
        raise ValueError('理解评分规则、识别照片和 PDF 需要模型，请先在“模型设置”中连接模型。')
    request_value = {**task['request'], key: rules, 'upload_report': report}
    parts = ([f'新增 {"、".join(added)}'] if added else []) + ([f'替换 {"、".join(replaced)}'] if replaced else []) \
        + ([f'删除 {"、".join(removed)}'] if removed else []) + (['修改了规则'] if rules_changed else []) \
        + ([f'撤回 {len(revoke)} 项处理'] if revoke else []) or ['重新打开确认']
    number = versions.start(task, kept, request_value, seed, '；'.join(parts)[:300])
    submit(task_id)
    return {'ok': True, 'version': number}


@app.post('/api/tasks/{task_id}/undo')
def undo(task_id: str):
    task = require_task(task_id)
    changeable(task)
    previous = versions.undo(task)
    if previous['status'] == 'completed':
        # The outputs on disk belong to the version just undone; write the restored version's again.
        restored = store.get_task(task_id)
        if task['kind'] == 'grades':
            workflow.write_exports(task_id, restored['result'])
            workflow.write_audit(task_id, restored['result'])
        else:
            appraisal_flow.write_exports(task_id, restored['result'])
        export_xlsx.write(restored)
    return {'ok': True, 'version': versions.number(store.get_task(task_id))}


@app.post('/api/tasks/{task_id}/stop')
def stop(task_id: str):
    """Stop after the step in progress (a model call already sent is waited for); finished steps stay valid."""
    task = require_task(task_id)
    if task['status'] not in ('queued', 'running'):
        raise HTTPException(409, '任务没有在处理。')
    versions.request_stop(task_id)
    store.update(task_id, step='正在中止：当前这一步完成后停下')
    return {'ok': True}


@app.post('/api/rules/extract')
async def extract_rules(request: Request):
    """The “从文件读取” button next to the rules box: the text goes into the box, where the user can still edit it."""
    form = await request.form()
    upload = form.get('file')
    if not (hasattr(upload, 'read') and upload.filename):
        raise ValueError('请选择规则文件。')
    suffix = Path(upload.filename).suffix.lower()
    content = await upload.read(UPLOAD_MB * 1024 * 1024 + 1)
    if not content or len(content) > UPLOAD_MB * 1024 * 1024:
        raise ValueError(f'规则文件为空或超过 {UPLOAD_MB}MB。')
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / f'rules{suffix}'
        path.write_bytes(content)
        body = uploads_mod.read_rules_file(upload.filename, path)
    return {'text': body[:6000], 'truncated': len(body) > 6000}


@app.post('/api/tasks/{task_id}/switch', status_code=201)
def switch(task_id: str):
    """The guess was wrong: run the same files and rules as the other kind; the old task is kept but marked as replaced."""
    task = require_task(task_id)
    if task['status'] in ('queued', 'running'):
        raise HTTPException(409, '任务正在执行，请稍候再切换。')
    other = 'appraisal' if task['kind'] == 'grades' else 'grades'
    rules = task['request'].get('rules_text') or task['request'].get('scheme_text', '')
    tid = uuid.uuid4().hex
    directory = store.DATA / 'tasks' / tid / 'input'
    directory.mkdir(parents=True)
    files = []
    for index, f in enumerate(f for f in task['files'] if f.get('role') != grades.ROSTER_ROLE or other == 'grades'):
        target = directory / f'{index}{Path(f["path"]).suffix.lower()}'
        shutil.copyfile(f['path'], target)
        files.append({**f, 'path': str(target)})
    created = start_task(other, task['name'], rules, files, task['request'].get('course', ''), task['request'].get('people'), '由你切换', tid)
    store.update(task_id, status='cancelled', step=f'已改为按“{intake.KINDS[other]}”处理')
    return created


def copy_fixtures(names, folder):
    tid = uuid.uuid4().hex
    directory = store.DATA / 'tasks' / tid / 'input'
    directory.mkdir(parents=True)
    files = []
    for index, name in enumerate(names):
        target = directory / f'{index}{Path(name).suffix.lower()}'
        shutil.copyfile(folder / name, target)
        files.append({'name': name, 'path': str(target), 'role': ''})
    return tid, files


@app.post('/api/demo/{kind}', status_code=201)
def demo(kind: str):
    """Built-in samples go through the same entrance as an upload, including the automatic choice of kind."""
    if kind not in DEMOS:
        raise HTTPException(404, '不存在此演示。')
    sample = DEMOS[kind]
    if kind == 'appraisal':
        folder = FIXTURE_DIR / sample['dir']
        names = sorted(p.name for p in folder.iterdir() if p.name != sample['scheme'] and p.suffix.lower() in SUFFIXES)
        rules = (folder / sample['scheme']).read_text(encoding='utf-8')
    else:
        folder, names, rules = FIXTURE_DIR, sample['files'], sample['rules_text']
    tid, files = copy_fixtures(names, folder)
    detected, reason = intake.classify(rules, names)
    return start_task(detected, sample['name'], rules, files, reason=reason, tid=tid, sample=True)


class Fill(BaseModel):
    student_id: str = Field(min_length=1, max_length=60)
    assessment: str = Field(min_length=1, max_length=80)
    occurrence: str = Field(default='', max_length=80)
    value: str = Field(min_length=1, max_length=20)


class ReviewPayload(BaseModel):
    mappings: dict = Field(default_factory=dict)
    decisions: dict = Field(default_factory=dict)
    fills: list[Fill] = Field(default_factory=list)
    materials: dict = Field(default_factory=dict)
    judgements: dict = Field(default_factory=dict)
    relations: dict = Field(default_factory=dict)
    scheme_answers: dict = Field(default_factory=dict)
    answers: list[str] = Field(default_factory=list, max_length=10)
    note: str = Field(default='', max_length=1000)


def check_grades_confirm(request, pending, value):
    issues = {i['id']: i for i in pending['issues']}
    if value.decisions.keys() - issues.keys():
        raise ValueError('提交了不存在的问题。')
    missing = [i['title'] for key, i in issues.items() if key not in value.decisions]
    if missing:
        raise ValueError(f'还有 {len(missing)} 个问题没有选择处理方式。')
    allowed = {'conflict': ('select', 'exclude'), 'row': ('correct', 'accept', 'exclude'), 'duplicate': ('select', 'keep')}
    for key, choice in value.decisions.items():
        if not isinstance(choice, dict) or choice.get('action') not in allowed[issues[key]['type']]:
            raise ValueError('有问题的处理方式不正确。')
        if choice['action'] == 'select' and choice.get('record_id') not in {x['value'] for x in issues[key]['options']}:
            raise ValueError('请从冲突的记录中选择一条。')
    tables = {t['id']: t for t in pending.get('tables', [])}
    for table_id, mapping in value.mappings.items():
        if table_id not in tables:
            raise ValueError('修改了不存在的表格。')
        grades.validate_mapping(mapping, tables[table_id]['headers'], request)
    if pending.get('rule') and pending.get('errors'):
        raise ValueError('评分规则还有问题：' + '；'.join(pending['errors']) + '。请在规则下方用一句话修改。')
    allowed = {(z['student_id'], f['assessment'], f['occurrence']) for z in pending.get('zeros') or [] for item in z['items'] for f in item.get('fill') or []}
    if any((f.student_id, f.assessment, f.occurrence) not in allowed for f in value.fills):
        raise ValueError('只能为列出的“没有记录”的位置补录成绩。')


def check_appraisal_confirm(task, pending, value):
    if pending.get('scheme_changed'):
        if pending.get('errors'):
            raise ValueError('考核指标还有问题：' + '；'.join(pending['errors']))
        return  # the materials will be read again with the new indicators; scores are asked for afterwards
    if pending.get('errors'):
        raise ValueError('考核指标还有问题：' + '；'.join(pending['errors']) + '。请在指标下方用一句话修改。')
    known = {m['id'] for m in pending['materials']}
    indicators = {i['id'] for i in pending['scheme']['indicators']} | {''}
    for mid, change in value.materials.items():
        if mid not in known or not isinstance(change, dict):
            raise ValueError('材料确认数据格式不正确。')
        if change.get('indicator', '') not in indicators or change.get('person', '') not in set(pending['people']) | {''}:
            raise ValueError('请从名单和指标中选择材料归属。')
        if any(not isinstance(change.get(f, ''), str) for f in ('doc_type', 'level', 'project', 'note')) or not isinstance(change.get('accepted', False), bool):
            raise ValueError('材料确认数据格式不正确。')
    limits = {j['key']: j['max'] for j in pending['judge']}
    for key, choice in value.judgements.items():
        score = appraisal.number(choice.get('score')) if isinstance(choice, dict) else None
        if key not in limits or score is None or not 0 <= score <= limits[key]:
            raise ValueError('评分必须在该指标的满分范围内。')
    asked = {q['id'] for q in pending.get('questions') or []}
    if value.scheme_answers.keys() - asked or any(v not in dedupe.SAME_WORK for v in value.scheme_answers.values()):
        raise ValueError('计分方式的回答不正确。')
    if asked - value.scheme_answers.keys():
        raise ValueError('请先选择“同一作品多次获奖”的计分方式。')
    pairs = {r['key']: r for r in pending.get('relations') or []}
    if value.relations.keys() - pairs.keys() or any(v not in dedupe.RELATIONS for v in value.relations.values()):
        raise ValueError('材料关系的修改不正确。')
    unsure = [r for k, r in pairs.items() if value.relations.get(k, r['relation']) == 'unsure']
    if unsure:
        raise ValueError(f'还有 {len(unsure)} 组材料是否重复需要你判断：' + '、'.join(r['key'].replace('|', ' 与 ') for r in unsure[:3]))
    waiting = appraisal_flow.undecided(pending, value.materials)
    if waiting:
        raise ValueError(f'还有 {len(waiting)} 份材料需要补充证明或核实：' + '、'.join(m['file'] for m in waiting[:4]) + ('等' if len(waiting) > 4 else '')
                         + '。请勾选“已核实，计分”或“不计入”。')
    missing = [j for j in pending['judge'] if not j.get('decided') and j['key'] not in value.judgements]
    if missing:
        raise ValueError(f'还有 {len(missing)} 项需要你打分：' + '、'.join(f'{j["person"]}的{j["name"]}' for j in missing[:4]) + ('等' if len(missing) > 4 else ''))


@app.post('/api/tasks/{task_id}/review')
def review_task(task_id: str, value: ReviewPayload):
    task = require_task(task_id)
    if task['status'] != 'waiting_review':
        raise HTTPException(409, '任务当前不处于待确认状态。')
    pending = task['result']['pending']
    payload = value.model_dump()
    request = {**task['request'], 'course': pending.get('course') or task['request'].get('course')}
    if pending['stage'] == 'understand':
        if len(value.answers) > len(pending['plan']['questions']) or any(len(a) > 500 for a in value.answers):
            raise ValueError('回答的数量或长度不正确。')
    elif pending['stage'] == 'mapping':
        for table in pending['tables']:
            grades.validate_mapping({**table['mapping'], **value.mappings.get(table['id'], {})}, table['headers'], request)
    elif task['kind'] == 'grades':
        check_grades_confirm(request, pending, value)
        if pending.get('rule'):
            payload['rules'] = {k: v for k, v in pending['rule'].items() if k != 'source_text'}  # the rule as last shown, including edits
            payload['revisions'] = pending.get('revisions') or []
    else:
        check_appraisal_confirm(task, pending, value)
        payload['scheme'] = {'indicators': pending['scheme']['indicators']}
    store.decision(task_id, pending['stage'], payload)
    store.update(task_id, status='queued', step='已确认，继续处理')
    submit(task_id, payload)
    return {'ok': True}


class Revision(BaseModel):
    text: str = Field(min_length=1, max_length=500)


@app.post('/api/tasks/{task_id}/revise')
def revise(task_id: str, value: Revision):
    """“期中改成30%” / “科技讲座每次改为2分”: the model edits the rule, the page shows the new reading and its effect."""
    task = require_task(task_id)
    if task['status'] != 'waiting_review' or task['result'].get('pending', {}).get('stage') != 'confirm':
        raise HTTPException(409, '只有在确认页才能修改规则。')
    if task['kind'] == 'grades' and not task['result']['pending'].get('rule'):
        raise ValueError('这个任务没有评分规则。')
    if not model.status()['configured']:
        raise ValueError('用文字修改规则需要模型，请先在“模型设置”中连接模型。')
    return FLOWS[task['kind']].revise(task_id, value.text.strip())


@app.post('/api/tasks/{task_id}/reparse')
def reparse(task_id: str):
    task = require_task(task_id)
    if task['kind'] != 'grades' or task['status'] != 'waiting_review' or task['result'].get('pending', {}).get('stage') != 'confirm':
        raise HTTPException(409, '只有在课程总评的确认页才能重新理解规则。')
    return workflow.reparse(task_id)


class Rounding(BaseModel):
    digits: int = Field(ge=0, le=4)


@app.post('/api/tasks/{task_id}/rounding')
def rounding(task_id: str, value: Rounding):
    """Decimal places of the total, chosen directly on the confirmation page (no model involved)."""
    task = require_task(task_id)
    pending = task['result'].get('pending') or {}
    if task['kind'] != 'grades' or task['status'] != 'waiting_review' or not pending.get('rule'):
        raise HTTPException(409, '只有在确认页才能修改小数位。')
    return workflow.set_digits(task_id, value.digits)


class Adjustment(BaseModel):
    student_id: str = Field(min_length=1, max_length=60)
    component: str = Field(min_length=1, max_length=60)
    value: float | None = None
    note: str = Field(default='', max_length=200)


@app.post('/api/tasks/{task_id}/adjust')
def adjust(task_id: str, value: Adjustment):
    """After the result is out the teacher can still change one student's component; the program recomputes."""
    task = require_task(task_id)
    if task['kind'] != 'grades' or task['status'] != 'completed' or not task['result'].get('rule'):
        raise HTTPException(409, '只有已完成、带总评规则的任务可以修改单项。')
    result = workflow.adjust(task_id, value.student_id, value.component, value.value, value.note)
    return {'totals': result['totals'], 'totals_summary': result['totals_summary'], 'overrides': result['overrides']}


@app.post('/api/tasks/{task_id}/retry')
def retry_task(task_id: str):
    task = require_task(task_id)
    if task['status'] not in ('failed', 'stopped'):
        raise HTTPException(409, '只有失败或已中止的任务可以继续。')
    versions.clear_stop(task_id)
    store.update(task_id, status='queued', step='等待继续处理' if task['status'] == 'stopped' else '等待重试', error=None)
    submit(task_id)
    return {'ok': True}


@app.get('/api/tasks/{task_id}/download/{filename}')
def download(task_id: str, filename: str):
    task = require_task(task_id)
    if filename == 'results.xlsx' and task['status'] == 'waiting_review' and (task['result'].get('pending') or {}).get('stage') == 'confirm':
        return Response(export_xlsx.build(task), media_type=XLSX,
                        headers={'Content-Disposition': "attachment; filename*=UTF-8''" + quote(f'暂定结果_未确认_{task["name"]}.xlsx')})
    if filename not in EXPORTS or task['status'] != 'completed':
        raise HTTPException(404, '文件尚未生成。')
    path = store.DATA / 'tasks' / task_id / 'output' / filename
    if filename == 'results.xlsx' and not path.is_file():
        export_xlsx.write(task)  # a task finished before the workbook existed
    if not path.is_file():
        raise HTTPException(404, '该类型的导出文件不存在。')
    media = XLSX if filename.endswith('.xlsx') else mimetypes.guess_type(filename)[0] or 'application/octet-stream'
    return FileResponse(path, filename=f'结果_{task["name"]}.xlsx' if filename == 'results.xlsx' else filename, media_type=media)


@app.get('/api/tasks/{task_id}/locate')
def locate(task_id: str, file: str, sheet: str = '', row: int = 0, where: str = ''):
    """Where a record sits in the material it came from: the rows around it for a table, the page of a PDF, the photo."""
    task = require_task(task_id)
    index = next((i for i, f in enumerate(task['files']) if f['name'] == file), None)
    if index is None:
        raise HTTPException(404, '这条记录不来自上传的文件（例如老师在确认页补录的值）。')
    return export_xlsx.locate(task['files'][index], index, sheet, row, where)


@app.get('/api/tasks/{task_id}/sources/{index}')
def source_file(task_id: str, index: int, inline: bool = False):
    task = require_task(task_id)
    if not 0 <= index < len(task['files']):
        raise HTTPException(404, '不存在此原始文件。')
    item = task['files'][index]
    suffix = Path(item['path']).suffix.lower()
    image_type = model.IMAGE_TYPES.get(suffix) or ('application/pdf' if suffix == '.pdf' else 'text/plain; charset=utf-8' if suffix in ('.txt', '.md', '.csv', '.tsv') else None)
    if inline and image_type:
        # Images and plain text are shown inline so the reviewer can compare a material with what was extracted from it.
        return FileResponse(item['path'], filename=item['name'], media_type=image_type, content_disposition_type='inline')
    return FileResponse(item['path'], filename=item['name'], media_type='application/octet-stream')


EVAL_RESULTS = store.ROOT / 'eval' / 'results'
_evaluation = {'process': None}


def read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def eval_cases():
    from eval import cases
    return cases.GRADE_CASES + cases.APPRAISAL_CASES


@app.get('/api/evaluation')
def evaluation(file: str = ''):
    """The latest (or a chosen) evaluation report and the progress of a run in progress."""
    history = sorted((p.name for p in EVAL_RESULTS.glob('eval_*.json')), reverse=True)[:20]
    name = file if file in history else 'latest.json'
    process = _evaluation['process']
    progress_file = EVAL_RESULTS / 'progress.json'
    progress = read_json(progress_file) or {}
    spawned = process is not None and process.poll() is None
    # A run started from the command line only leaves its progress file; trust it while it keeps being updated.
    external = bool(progress.get('running')) and progress_file.is_file() and time.time() - progress_file.stat().st_mtime < 900
    return {'report': read_json(EVAL_RESULTS / name), 'history': history, 'running': spawned or external, 'progress': progress,
            'cases': [{k: c[k] for k in ('id', 'title', 'level', 'about')} for c in eval_cases()]}


class EvaluationOptions(BaseModel):
    repeat: int = Field(default=1, ge=1, le=3)
    cases: list[str] = Field(default_factory=list)


@app.post('/api/evaluation/run', status_code=202)
def run_evaluation(options: EvaluationOptions):
    process = _evaluation['process']
    if process is not None and process.poll() is None:
        raise HTTPException(409, '评测正在运行，请等待完成。')
    if not model.status()['configured']:
        raise ValueError('评测需要真实模型，请先在“模型设置”中连接模型。')
    known = {c['id'] for c in eval_cases()}
    if any(c not in known for c in options.cases):
        raise ValueError('选择了不存在的评测用例。')
    command = [sys.executable, '-X', 'utf8', '-m', 'eval.run', '--repeat', str(options.repeat)]
    if options.cases:
        command += ['--cases', ','.join(options.cases)]
    EVAL_RESULTS.mkdir(parents=True, exist_ok=True)
    log = (EVAL_RESULTS / 'last_run.log').open('w', encoding='utf-8')
    # The key travels only in the child's environment; the runner keeps its own temporary data folder.
    _evaluation['process'] = subprocess.Popen(command, cwd=store.ROOT, env={**os.environ, **model.environment(), 'PYTHONIOENCODING': 'utf-8'},
                                              stdout=log, stderr=subprocess.STDOUT)
    return {'ok': True}


@app.get('/api/fixtures/{filename}')
def fixture(filename: str):
    if filename not in FIXTURES:
        raise HTTPException(404)
    return FileResponse(FIXTURE_DIR / filename, filename=filename)


app.mount('/', StaticFiles(directory=store.ROOT / 'web', html=True), name='web')
