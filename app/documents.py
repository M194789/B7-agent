"""Turn uploaded documents into what the model can read: text, page images and (for Word) tables.

PDF pages that carry a text layer are read as text; scanned pages are rendered to pictures. Photos are
rotated by their EXIF orientation and shrunk before they are sent, so a phone picture is not 8MB of base64.
"""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from PIL import Image, ImageOps

IMAGE_SUFFIXES = ('.jpg', '.jpeg', '.png', '.webp')
DOCUMENT_SUFFIXES = ('.pdf', '.docx')
LONG_EDGE = 2000
SCANNED_CHARS = 20  # a PDF page with fewer visible characters than this is treated as a scan
MAX_PAGES = 30
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def image_jpeg(source):
    """A path or raw bytes -> upright RGB JPEG bytes no longer than LONG_EDGE on either side."""
    try:
        with Image.open(source if not isinstance(source, bytes) else io.BytesIO(source)) as image:
            image = ImageOps.exif_transpose(image)
            if image.mode not in ('RGB', 'L'):
                background = Image.new('RGB', image.size, 'white')
                background.paste(image, mask=image.convert('RGBA').split()[-1])
                image = background
            image.thumbnail((LONG_EDGE, LONG_EDGE))
            out = io.BytesIO()
            image.convert('RGB').save(out, 'JPEG', quality=85)
            return out.getvalue()
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        raise ValueError('无法打开图片：' + type(error).__name__) from None


def visible(value):
    return len(re.sub(r'\s+', '', value or ''))


def read_pdf(path, render='scanned', max_images=6):
    """render='scanned' renders only pages without a text layer; render='all' renders every page (tables)."""
    import pypdfium2 as pdfium
    try:
        pdf = pdfium.PdfDocument(str(path))
    except pdfium.PdfiumError:
        raise ValueError('无法打开 PDF（可能已加密或已损坏）。') from None
    try:
        count = len(pdf)
        if count > MAX_PAGES:
            raise ValueError(f'PDF 共 {count} 页，单份最多 {MAX_PAGES} 页，请拆分后上传。')
        texts, images, scanned, skipped = [], [], [], []
        for index in range(count):
            page = pdf[index]
            try:
                textpage = page.get_textpage()
                value = textpage.get_text_bounded().replace('\r\n', '\n').strip()
                textpage.close()
                texts.append(value)
                if visible(value) < SCANNED_CHARS:
                    scanned.append(index + 1)
                if render == 'all' or visible(value) < SCANNED_CHARS:
                    if len(images) >= max_images:
                        skipped.append(index + 1)
                        continue
                    width, height = page.get_size()
                    scale = min(3.0, LONG_EDGE / max(width, height, 1))
                    bitmap = page.render(scale=scale)
                    out = io.BytesIO()
                    bitmap.to_pil().convert('RGB').save(out, 'JPEG', quality=85)
                    images.append({'page': index + 1, 'data': out.getvalue()})
            finally:
                page.close()
    finally:
        pdf.close()
    notes = []
    if scanned:
        notes.append(f'第 {pages_label(scanned)} 页没有文字层，按扫描件识别')
    if skipped:
        notes.append(f'第 {pages_label(skipped)} 页超出单份识别页数上限，未送模型识别')
    text = '\n\n'.join(f'【第{i + 1}页】\n{t}' if count > 1 else t for i, t in enumerate(texts) if t)
    return {'kind': 'pdf', 'pages': count, 'text': text, 'page_texts': texts, 'images': images, 'tables': [], 'notes': notes}


def pages_label(pages):
    return '、'.join(str(p) for p in pages[:8]) + ('等' if len(pages) > 8 else '')


def cell_text(element):
    parts = []
    for node in element.iter():
        if node.tag == W + 't' and node.text:
            parts.append(node.text)
        elif node.tag in (W + 'tab',):
            parts.append('\t')
        elif node.tag in (W + 'br', W + 'cr'):
            parts.append('\n')
        elif node.tag == W + 'p' and parts and parts[-1] != '\n':
            parts.append('\n')
    return ''.join(parts).strip()


def read_docx(path, max_images=4):
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise ValueError('无法打开 Word 文件。旧版 .doc 请另存为 .docx 或 PDF 后上传。') from None
    with archive:
        try:
            root = ElementTree.fromstring(archive.read('word/document.xml'))
        except (KeyError, ElementTree.ParseError):
            raise ValueError('Word 文件内容无法解析。') from None
        lines, tables = [], []
        body = root.find(W + 'body')
        for block in body if body is not None else []:
            if block.tag == W + 'p':
                value = cell_text(block)
                if value:
                    lines.append(value)
            elif block.tag == W + 'tbl':
                rows = []
                for tr in block.iter(W + 'tr'):
                    cells = []
                    for tc in tr.findall(W + 'tc'):
                        span = tc.find(f'{W}tcPr/{W}gridSpan')
                        value = cell_text(tc)
                        # Like a merged Excel cell: the value sits in the first column, the spanned columns stay empty.
                        cells += [value] + [''] * ((int(span.get(W + 'val', 1)) if span is not None else 1) - 1)
                    rows.append(cells)
                if rows:
                    tables.append(rows)
                    lines += [' | '.join(r) for r in rows]
        images, skipped = [], 0
        for name in sorted(n for n in archive.namelist() if n.startswith('word/media/') and Path(n).suffix.lower() in IMAGE_SUFFIXES):
            if len(images) >= max_images:
                skipped += 1
                continue
            try:
                images.append({'page': None, 'data': image_jpeg(archive.read(name))})
            except ValueError:
                skipped += 1
    notes = [f'文档中插入了 {len(images)} 张图片，已一并识别'] if images else []
    if skipped:
        notes.append(f'另有 {skipped} 张图片未送模型识别')
    return {'kind': 'docx', 'pages': None, 'text': '\n'.join(lines), 'page_texts': [], 'images': images, 'tables': tables, 'notes': notes}


def load(path, render='scanned', max_images=6):
    """Unified reader for PDF, Word and photos. Returned images are dicts {'page', 'data': JPEG bytes}."""
    suffix = Path(path).suffix.lower()
    if suffix == '.pdf':
        return read_pdf(path, render, max_images)
    if suffix == '.docx':
        return read_docx(path, min(max_images, 4))
    if suffix in IMAGE_SUFFIXES:
        return {'kind': 'image', 'pages': 1, 'text': '', 'page_texts': [], 'images': [{'page': 1, 'data': image_jpeg(path)}], 'tables': [], 'notes': []}
    if suffix == '.doc':
        raise ValueError('旧版 .doc 文件请另存为 .docx 或 PDF 后上传。')
    raise ValueError('不支持的文档格式：' + suffix)
