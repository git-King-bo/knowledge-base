import io
import unittest
from pathlib import Path

from openpyxl import Workbook
from pypdf import PdfWriter

import test_workspace as workspace


class FilePreviewTests(unittest.TestCase):
    setUp = workspace.WorkspaceTests.setUp
    tearDown = workspace.WorkspaceTests.tearDown
    base = workspace.WorkspaceTests.base

    def upload_file(self, base, filename, content):
        response = self.client.post(f'/api/knowledge/bases/{base}/upload',
            files={'file': (filename, content, 'application/octet-stream')})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()['source']['id']

    def test_spreadsheet_pagination_sheets_and_base_isolation(self):
        base = self.base()
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(['姓名', '简介', '数量', '启用'])
        for index in range(111):
            sheet.append([f'测试{index}', '两行\n简介', 0, False])
        workbook.create_sheet('另一表').append(['<script>alert(1)</script>'])
        output = io.BytesIO()
        workbook.save(output)
        workbook.close()
        source = self.upload_file(base, '名单.xlsx', output.getvalue())
        url = f'/api/knowledge/bases/{base}/sources/{source}'
        first = self.client.get(url + '/preview').json()
        self.assertEqual(first['total'], 112)
        self.assertEqual(len(first['rows']), 50)
        self.assertEqual(first['rows'][1]['cells'], ['测试0', '两行\n简介', '0', 'False'])
        last = self.client.get(url + '/preview?offset=100').json()
        self.assertEqual(len(last['rows']), 12)
        self.assertEqual(last['rows'][-1]['number'], 112)
        second = self.client.get(url + '/preview?sheet=1').json()
        self.assertEqual(second['rows'][0]['cells'], ['<script>alert(1)</script>'])
        self.assertEqual(self.client.get(url + '/preview?sheet=2').status_code, 400)
        self.assertEqual(self.client.get(url + '/preview?offset=-1').status_code, 422)
        other = self.base('其他知识库')
        for suffix in ('preview', 'file'):
            self.assertEqual(self.client.get(f'/api/knowledge/bases/{other}/sources/{source}/{suffix}').status_code, 404)
        self.client.delete(url)
        self.assertEqual(self.client.get(url + '/preview').status_code, 404)

    def test_csv_and_full_text_paging(self):
        base = self.base()
        source = self.upload_file(base, '数据.csv', '姓名,简介\n甲,"多行\n内容"\n'.encode())
        result = self.client.get(f'/api/knowledge/bases/{base}/sources/{source}/preview').json()
        self.assertEqual(result['total'], 2)
        self.assertEqual(result['rows'][1]['cells'], ['甲', '多行\n内容'])
        source = self.upload_file(base, '长文.md', ('文本' * 11000).encode())
        url = f'/api/knowledge/bases/{base}/sources/{source}/preview'
        first = self.client.get(url).json()
        last = self.client.get(url + '?offset=1').json()
        self.assertEqual(first['total'], 2)
        self.assertEqual(first['text'] + last['text'], '文本' * 11000)

    def test_pdf_original_preview_even_when_text_extraction_fails(self):
        base = self.base()
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        output = io.BytesIO()
        writer.write(output)
        response = self.client.post(f'/api/knowledge/bases/{base}/upload',
            files={'file': ('空白.pdf', output.getvalue(), 'application/pdf')})
        self.assertEqual(response.status_code, 400)
        source = self.client.get(f'/api/knowledge/bases/{base}/sources').json()[0]['id']
        url = f'/api/knowledge/bases/{base}/sources/{source}'
        self.assertEqual(self.client.get(url + '/preview').json()['kind'], 'pdf')
        response = self.client.get(url + '/file')
        self.assertEqual(response.content, output.getvalue())
        self.assertEqual(response.headers['content-type'], 'application/pdf')
        self.assertTrue(response.headers['content-disposition'].startswith('inline;'))
        for path in Path(self.temp.name).iterdir():
            path.unlink()
        self.assertEqual(self.client.get(url + '/preview').status_code, 404)
