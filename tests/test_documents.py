import io
import zipfile

import pytest
from PIL import Image

from app import appraisal, appraisal_flow, documents, grades, model, scoring, store, workflow

DOCS = store.ROOT / 'fixtures' / 'documents'
REQUEST = {'course': '数据结构', 'term': '2026秋'}


def test_printed_pdf_is_read_as_text_and_scanned_pdf_as_pages():
    printed = documents.load(DOCS / '实验成绩登记表_教务打印.pdf')
    assert printed['pages'] == 2 and printed['images'] == []
    assert '2026104 张伟 70 未交 72' in printed['text'] and '【第2页】' in printed['text']
    assert len(documents.load(DOCS / '实验成绩登记表_教务打印.pdf', render='all')['images']) == 2
    scanned = documents.load(DOCS / '实验成绩登记表_扫描件.pdf')
    assert scanned['text'] == '' and [i['page'] for i in scanned['images']] == [1, 2]
    assert '没有文字层' in scanned['notes'][0]


def test_photo_is_turned_upright_and_shrunk():
    image = Image.new('RGB', (3000, 1000), 'white')
    exif = image.getexif()
    exif[0x0112] = 6  # taken with the phone turned: needs a 90° turn
    raw = io.BytesIO()
    image.save(raw, 'JPEG', exif=exif)
    with Image.open(io.BytesIO(documents.image_jpeg(raw.getvalue()))) as result:
        assert result.size == (667, 2000)


def test_word_table_with_two_level_header():
    table = workflow.read_word_tables(DOCS / '实验成绩登记表_Word版.docx', '实验成绩登记表_Word版.docx')[0]
    assert table['headers'] == ['学号', '姓名', '实验1', '实验2', '实验3', '备注']
    assert len(table['rows']) == 11 and any('平均分' in n for n in table['notes'])
    word = documents.load(DOCS / '李强_年度工作总结.docx')
    assert '智慧校园能耗监测系统' in word['text'] and len(word['images']) == 1


def test_messy_excel_header_title_and_average_row():
    table = grades.read_table(DOCS / '实验成绩_手工汇总表.xlsx')[0]
    assert table['headers'] == ['学号', '姓名', '实验1', '实验2', '实验3', '备注']
    assert table['rows'][0]['row_number'] == 5 and len(table['rows']) == 11
    assert '实验成绩登记表' in table['preamble'][0]
    mapping = grades.propose_mapping(table['headers'])
    result = grades.merge([table], {table['id']: mapping}, REQUEST)
    statuses = sorted(r['status'] for r in result['rows'] if r['status'])
    assert statuses == ['免修'] * 3 + ['未交']
    assert len(result['rows']) == 33


@pytest.mark.parametrize('name', ['实验成绩_Excel97格式.xls', '教务系统导出_实验成绩.xls'])
def test_legacy_xls_real_and_html_disguised(name):
    table = grades.read_table(DOCS / name, name)[0]
    assert table['headers'][:5] == ['学号', '姓名', '实验1', '实验2', '实验3']
    assert len(table['rows']) == 11 and table['rows'][0]['values']['学号'] == '2026101'
    assert table['rows'][3]['values']['实验2'] == '未交'


def test_unsubmitted_counts_as_zero_when_the_rules_say_so():
    table = grades.read_table(DOCS / '实验成绩_手工汇总表.xlsx')[0]
    result = grades.merge([table], {table['id']: grades.propose_mapping(table['headers'])}, REQUEST)
    rule = scoring.normalize({'components': [{'name': '实验', 'assessments': ['实验'], 'weight': 100, 'aggregate': 'mean', 'missing': 'zero'}],
                             'status_policy': {'未交': 'zero', '免修': 'exempt'}})
    totals = {(t['student_id']): t for t in scoring.compute(rule, result['rows'])['totals']}
    assert totals['2026104']['total'] == 47.33  # (70 + 0 + 72) / 3, two decimals by default
    assert totals['2026110']['outcome'] == 'exempt'


def test_unsupported_documents_are_explained(tmp_path):
    old = tmp_path / '总结.doc'
    old.write_bytes(b'\xd0\xcf\x11\xe0 old word')
    with pytest.raises(ValueError, match='另存为'):
        documents.load(old)
    broken = tmp_path / '坏.pdf'
    broken.write_bytes(b'not a pdf')
    with pytest.raises(ValueError, match='PDF'):
        documents.load(broken)
    no_table = tmp_path / '无表格.docx'
    with zipfile.ZipFile(no_table, 'w') as z:
        z.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>只有文字</w:t></w:r></w:p></w:body></w:document>')
    with pytest.raises(ValueError, match='没有找到成绩表格'):
        workflow.read_word_tables(no_table, '无表格.docx')


def test_pdf_pages_are_joined_when_page_two_continues_the_table(monkeypatch):
    """Test stand-in for the vision model: page 1 has the header, page 2 is a continuation."""
    calls = []

    def fake(instruction, payload, images=None):
        calls.append(payload)
        assert isinstance(images[0], bytes)
        if payload['page'] == 1:
            return {'headers': ['学号', '姓名', '实验1'], 'rows': [['2026101', '王晨', '92'], ['2026102', '李思远', '85']], 'uncertain': []}
        return {'headers': payload['previous_headers'], 'rows': [['2026107', '陈佳怡', '82']],
                'uncertain': [{'row': 1, 'column': '实验1', 'reason': '模糊'}]}
    monkeypatch.setattr(model, 'ask_json', fake)
    tables = workflow.read_image(DOCS / '实验成绩登记表_扫描件.pdf', '实验成绩登记表_扫描件.pdf')
    assert len(tables) == 1 and len(tables[0]['rows']) == 3 and tables[0]['sheet'] == '第1-2页'
    assert tables[0]['rows'][2]['uncertain'] == ['实验1'] and tables[0]['rows'][2]['values']['姓名'] == '陈佳怡'
    assert calls[1]['previous_headers'] == ['学号', '姓名', '实验1'] and 'text_layer' not in calls[1]
    assert '没有文字层' in tables[0]['ocr_notes']


def test_word_material_sends_text_and_picture(monkeypatch):
    seen = {}

    def fake(instruction, payload, images=None):
        seen['images'] = images
        return {'person': '李强', 'doc_type': '年度工作总结', 'indicators': [{'id': 'I5', 'reason': '证书'}], 'level': '省级',
                'quotes': ['获省级二等奖（证书附后）', '辅导员：李强']}
    monkeypatch.setattr(model, 'ask_json', fake)
    indicators = appraisal.normalize_scheme({'indicators': [{'id': 'I5', 'name': '竞赛', 'max': 10, 'method': 'count', 'points': 2, 'cap': 10}]})['indicators']
    item = appraisal_flow.read_one(0, {'name': '李强_年度工作总结.docx', 'path': str(DOCS / '李强_年度工作总结.docx')}, indicators, ['李强', '王敏'])
    assert len(seen['images']) == 1 and item['origin'] == 'mixed'
    # The first quote is in the Word text; the second is only on the pasted certificate picture.
    assert [q['verified'] for q in item['quotes']] == [True, None]
