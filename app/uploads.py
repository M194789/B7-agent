"""What arrives in one upload: loose files, whole folders (relative paths) and .zip archives, plus the rules as a file.

A teacher's materials usually sit in a folder or come as a zip from a colleague; both are unpacked here into plain files
with short, unique, readable names. A rules or scheme document uploaded among the materials is recognised and used as
the rules when the rules box was left empty.
"""
from __future__ import annotations

import hashlib
import io
import re
import zipfile
from pathlib import PurePosixPath

from . import documents, grades

ZIP_MEMBERS = 200
ZIP_TOTAL_MB = 200
RULE_NAMES = ('规则', '方案', '给分', '算分', '评分', '计分', '考核办法', '细则', '评价标准', '说明')
RULE_WORDS = ('占', '%', '权重', '比例', '计', '换算', '缺考', '总评', '指标', '扣')
PROSE = ('.txt', '.md', '.docx')


def clean_path(name):
    """'测试A\\01 材料/问答.png' -> PurePosixPath; drops empty, '.' and '..' parts so nothing escapes the task folder."""
    parts = [p.strip() for p in str(name).replace('\\', '/').split('/') if p.strip() not in ('', '.', '..')]
    return PurePosixPath(*parts) if parts else PurePosixPath('未命名')


def zip_name(info):
    """Windows zips store Chinese names in GBK without the UTF-8 flag; Python then reads them as cp437."""
    if info.flag_bits & 0x800:
        return info.filename
    try:
        return info.filename.encode('cp437').decode('gb18030')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return info.filename


def hidden(path):
    return any(p.startswith(('.', '__MACOSX', '~$')) or p in ('Thumbs.db', 'desktop.ini') for p in path.parts)


def unpack_zip(name, content, suffixes, limit_mb):
    """(files, skipped): files are (relative path, bytes); a nested zip, an unsupported or oversized member is skipped with a reason."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise ValueError(f'“{name}”不是有效的 zip 压缩包。') from None
    members = [i for i in archive.infolist() if not i.is_dir()]
    if len(members) > ZIP_MEMBERS:
        raise ValueError(f'“{name}”里有 {len(members)} 个文件，超过 {ZIP_MEMBERS} 个，请只压缩需要处理的材料。')
    if sum(i.file_size for i in members) > ZIP_TOTAL_MB * 1024 * 1024:
        raise ValueError(f'“{name}”解压后超过 {ZIP_TOTAL_MB}MB。')
    root = PurePosixPath(clean_path(name).stem)
    files, skipped = [], []
    for info in members:
        path = clean_path(zip_name(info))
        if hidden(path):
            continue
        if info.flag_bits & 0x1:
            skipped.append(f'{path}（加密）')
        elif path.suffix.lower() not in suffixes:
            skipped.append(f'{path}（格式不支持）')
        elif info.file_size > limit_mb * 1024 * 1024 or not info.file_size:
            skipped.append(f'{path}（为空或超过 {limit_mb}MB）')
        else:
            files.append((str(root / path), archive.read(info)))
    return files, skipped


def short_names(paths):
    """The shortest tail of each path that is still unique: '问答登记_01.png', or 'A班/问答.png' next to 'B班/问答.png'."""
    parts = [clean_path(p).parts for p in paths]
    names = []
    for mine in parts:
        for depth in range(1, len(mine) + 1):
            tail = mine[-depth:]
            if sum(1 for other in parts if other[-depth:] == tail) == 1 or depth == len(mine):
                names.append('/'.join(tail))
                break
    return names


def looks_like_rules(name, body):
    """A short prose document named or worded like scoring rules (“给分说明”, “考核方案”, “期中占20%”)."""
    if not body or len(body) > 20000:
        return False
    named = any(w in PurePosixPath(name).stem for w in RULE_NAMES)
    worded = sum(body.count(w) for w in RULE_WORDS)
    return (named and worded >= 3) or worded >= 12


def find_rules(files):
    """Index of the uploaded file that holds the rules, or None. Only .txt/.md and table-free .docx are candidates;
    with several candidates the one that reads most like rules wins."""
    best, best_score = None, 0
    for index, f in enumerate(files):
        suffix = PurePosixPath(f['name']).suffix.lower()
        if suffix not in PROSE:
            continue
        if suffix == '.docx':
            try:
                doc = documents.load(f['path'], max_images=0)
            except ValueError:
                continue
            if doc['tables']:
                continue
            body = doc['text']
        else:
            with open(f['path'], 'rb') as handle:
                body = grades.decode_text(handle.read()) or ''
        if looks_like_rules(f['name'], body):
            score = sum(body.count(w) for w in RULE_WORDS) + (20 if any(w in f['name'] for w in RULE_NAMES) else 0)
            if score > best_score:
                best, best_score = (index, body), score
    return best


def read_rules_file(name, path):
    """Text of a rules document chosen with the “从文件读取” button: .txt/.md/.docx/.pdf with a text layer."""
    suffix = PurePosixPath(name).suffix.lower()
    if suffix in ('.txt', '.md'):
        with open(path, 'rb') as handle:
            body = grades.decode_text(handle.read())
        if body is None:
            raise ValueError('无法识别这个文本文件的编码，请另存为 UTF-8。')
        return body
    if suffix in ('.docx', '.pdf'):
        doc = documents.load(path, max_images=0)
        body = doc['text'] + ''.join('\n' + '\t'.join(row) for table in doc['tables'] for row in table)
        if documents.visible(body) < 10:
            raise ValueError('这个文件里没有可直接读取的文字（可能是扫描件），请把规则粘贴或打字进来。')
        return re.sub(r'【第\d+页】\n?', '', body).strip()
    raise ValueError('评分规则文件支持 TXT、Markdown、Word(.docx) 和带文字的 PDF。')


def digest(content):
    return hashlib.sha256(content).hexdigest()


def unique_contents(received):
    """(files kept, [(dropped name, kept name)]): byte-identical files are one material, whatever their names."""
    seen, kept, dropped = {}, [], []
    for name, content in received:
        digest_ = digest(content)
        if digest_ in seen:
            dropped.append((name, seen[digest_]))
        else:
            seen[digest_] = name
            kept.append((name, content))
    return kept, dropped
