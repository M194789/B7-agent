from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get('B7_DATA_DIR', ROOT / 'data')).resolve()
DATA.mkdir(parents=True, exist_ok=True)
DB = DATA / 'workspace.sqlite3'


def now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='milliseconds')


def dump(value):
    return json.dumps(value, ensure_ascii=False, default=str)


def connect():
    db = sqlite3.connect(DB, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA busy_timeout=30000')
    return db


def init():
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS tasks (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
          status TEXT NOT NULL, step TEXT NOT NULL, created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL, request TEXT NOT NULL, files TEXT NOT NULL,
          result TEXT NOT NULL DEFAULT '{}', error TEXT, llm_used INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
          tool TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL,
          mode TEXT NOT NULL, detail TEXT NOT NULL, elapsed_ms INTEGER,
          created_at TEXT NOT NULL, UNIQUE(task_id,tool)
        );
        CREATE TABLE IF NOT EXISTS decisions (
          id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
          stage TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS cache (
          key TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS mappings (
          key TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS prefs (
          key TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS templates (
          id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS versions (
          task_id TEXT NOT NULL, number INTEGER NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL,
          PRIMARY KEY(task_id, number)
        );
        ''')


def create_task(name, kind, request, files, task_id=None):
    task_id = task_id or uuid.uuid4().hex
    stamp = now()
    with connect() as db:
        db.execute('INSERT INTO tasks(id,name,kind,status,step,created_at,updated_at,request,files) VALUES (?,?,?,?,?,?,?,?,?)',
                   (task_id, name, kind, 'queued', '等待执行', stamp, stamp, dump(request), dump(files)))
    return task_id


def update(task_id, **fields):
    allowed = {'status', 'step', 'result', 'error', 'llm_used', 'request', 'files'}
    if not fields.keys() <= allowed:
        raise ValueError('Unsupported task update')
    values = {k: dump(v) if k in ('result', 'request', 'files') else v for k, v in fields.items()}
    values['updated_at'] = now()
    with connect() as db:
        db.execute('UPDATE tasks SET ' + ','.join(f'{k}=?' for k in values) + ' WHERE id=?', [*values.values(), task_id])


def decode_task(row):
    item = dict(row)
    for key in ('request', 'files', 'result'):
        item[key] = json.loads(item[key])
    item['llm_used'] = bool(item['llm_used'])
    return item


def get_task(task_id, details=True):
    with connect() as db:
        row = db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
        if not row:
            return None
        item = decode_task(row)
        if details:
            item['events'] = [{**dict(x), 'detail': json.loads(x['detail'])} for x in db.execute('SELECT * FROM events WHERE task_id=? ORDER BY id', (task_id,))]
            item['decisions'] = [{**dict(x), 'payload': json.loads(x['payload'])} for x in db.execute('SELECT * FROM decisions WHERE task_id=? ORDER BY id', (task_id,))]
        return item


def list_tasks():
    with connect() as db:
        return [decode_task(row) for row in db.execute('SELECT * FROM tasks ORDER BY created_at DESC')]


def event(task_id, tool, title, status='completed', mode='rule', detail=None, elapsed_ms=None):
    with connect() as db:
        db.execute('''INSERT INTO events(task_id,tool,title,status,mode,detail,elapsed_ms,created_at)
        VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(task_id,tool) DO UPDATE SET
        title=excluded.title,status=excluded.status,mode=excluded.mode,detail=excluded.detail,
        elapsed_ms=excluded.elapsed_ms''', (task_id, tool, title, status, mode, dump(detail or {}), elapsed_ms, now()))


def decision(task_id, stage, payload):
    with connect() as db:
        db.execute('INSERT INTO decisions(task_id,stage,payload,created_at) VALUES (?,?,?,?)', (task_id, stage, dump(payload), now()))


def pref_get(key):
    with connect() as db:
        row = db.execute('SELECT payload FROM prefs WHERE key=?', (key,)).fetchone()
        return json.loads(row['payload']) if row else None


def pref_put(key, payload):
    with connect() as db:
        db.execute('INSERT OR REPLACE INTO prefs VALUES (?,?,?)', (key, dump(payload), now()))


def template_put(kind, name, payload):
    template_id = uuid.uuid4().hex[:12]
    with connect() as db:
        db.execute('INSERT INTO templates VALUES (?,?,?,?,?)', (template_id, kind, name, dump(payload), now()))
    return template_id


def templates():
    with connect() as db:
        return [{**dict(r), 'payload': json.loads(r['payload'])} for r in db.execute('SELECT * FROM templates ORDER BY created_at DESC')]


def template_get(template_id):
    return next((t for t in templates() if t['id'] == template_id), None)


def template_drop(template_id):
    with connect() as db:
        db.execute('DELETE FROM templates WHERE id=?', (template_id,))


def delete_task(task_id):
    with connect() as db:
        for table in ('events', 'decisions', 'versions'):
            db.execute(f'DELETE FROM {table} WHERE task_id=?', (task_id,))
        db.execute('DELETE FROM tasks WHERE id=?', (task_id,))


def version_put(task_id, number, payload):
    with connect() as db:
        db.execute('INSERT OR REPLACE INTO versions VALUES (?,?,?,?)', (task_id, number, dump(payload), now()))


def version_get(task_id, number):
    with connect() as db:
        row = db.execute('SELECT payload FROM versions WHERE task_id=? AND number=?', (task_id, number)).fetchone()
        return json.loads(row['payload']) if row else None


def version_drop(task_id, number):
    with connect() as db:
        db.execute('DELETE FROM versions WHERE task_id=? AND number>=?', (task_id, number))


def cache_get(key):
    with connect() as db:
        row = db.execute('SELECT payload FROM cache WHERE key=?', (key,)).fetchone()
        return json.loads(row['payload']) if row else None


def cache_put(key, payload):
    with connect() as db:
        db.execute('INSERT OR REPLACE INTO cache VALUES (?,?,?)', (key, dump(payload), now()))


def mapping_get(key):
    with connect() as db:
        row = db.execute('SELECT payload FROM mappings WHERE key=?', (key,)).fetchone()
        return json.loads(row['payload']) if row else None


def mapping_put(key, payload):
    with connect() as db:
        db.execute('INSERT OR REPLACE INTO mappings VALUES (?,?,?)', (key, dump(payload), now()))
