"""Excel run formatting must match the editor, including unformatted text."""

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from xml.etree import ElementTree
from zipfile import ZipFile

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font

from excel_export import workbook_bytes
from lexicon_db import LexiconDB


class ExcelRunTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.source = Path(directory.name) / 'colors.xlsx'
        book = Workbook()
        sheet = book.active
        sheet.append(['Label', 'LIMBA ROMÂNĂ'])
        sheet.append(['ETIMON/', 'original red text'])
        sheet['B2'].font = Font(name='Times New Roman', sz=11, color='FFFF0000',
                                b=True, i=True, strike=True, u='double',
                                vertAlign='superscript')
        book.save(self.source)
        book.close()
        self.store = LexiconDB(':memory:', self.source)
        self.addCleanup(self.store.close)
        self.key = (1, 'ETIMON/', 1, 'LIMBA ROMÂNĂ')

    def export(self, ops):
        self.store.save_cell(self.key, 0, ops)
        payload = workbook_bytes(self.store)
        book = load_workbook(BytesIO(payload), rich_text=True)
        self.addCleanup(book.close)
        with ZipFile(BytesIO(payload)) as archive:
            xml = ElementTree.fromstring(archive.read('xl/worksheets/sheet1.xml'))
        ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        cell = xml.find('.//s:c[@r="B2"]', ns)
        return book.active['B2'], cell, ns

    def test_added_text_uses_editor_defaults_instead_of_original_red_font(self):
        cell, xml, ns = self.export([
            {'insert': 'red', 'attributes': {'color': '#ff0000', 'font': 'Times New Roman', 'size': '11pt'}},
            {'insert': '\nnew default text'},
            {'insert': ' blue', 'attributes': {'color': 'rgb(0, 0, 255)', 'size': '18pt'}},
            {'insert': '\n'},
        ])
        self.assertEqual(str(cell.value), 'red\nnew default text blue')
        self.assertEqual(cell.value[0].font.color.rgb, 'FFFF0000')
        default = cell.value[1].font
        self.assertEqual(default.color.rgb, 'FF253B35')
        self.assertEqual(default.rFont, 'Segoe UI')
        self.assertEqual(default.sz, 9)
        self.assertFalse(default.b)
        self.assertFalse(default.i)
        self.assertFalse(default.strike)
        self.assertIsNone(default.u)
        self.assertEqual(default.vertAlign, 'baseline')
        self.assertEqual(cell.value[2].font.color.rgb, 'FF0000FF')
        self.assertEqual(cell.value[2].font.sz, 18)
        # Explicit resets are essential: omitted properties inherit the old
        # cell's bold/italic/underline/script in Excel.
        for properties in xml.findall('s:is/s:r/s:rPr', ns):
            for name, setting in [('b', '0'), ('i', '0'), ('strike', '0'),
                                  ('u', 'none'), ('vertAlign', 'baseline')]:
                self.assertEqual(properties.find(f's:{name}', ns).get('val'), setting)

    def test_newline_and_space_only_runs_have_explicit_whitespace_preservation(self):
        text = ' red\n\n\t  blue  \n'
        cell, xml, ns = self.export([
            {'insert': ' red', 'attributes': {'color': '#f00'}},
            {'insert': '\n\n\t  '},
            {'insert': 'blue  ', 'attributes': {'color': '#00f'}},
            {'insert': '\n\n'},
        ])
        self.assertEqual(str(cell.value), text)
        nodes = xml.findall('s:is/s:r/s:t', ns)
        self.assertTrue(any(node.text.isspace() for node in nodes))
        for node in nodes:
            self.assertEqual(node.get('{http://www.w3.org/XML/1998/namespace}space'), 'preserve')
            self.assertTrue(node.text)

    def test_clearing_cell_does_not_emit_empty_rich_text_run(self):
        cell, xml, ns = self.export([{'insert': '\n'}])
        self.assertFalse(cell.value)
        self.assertEqual(xml.findall('s:is/s:r', ns), [])


if __name__ == '__main__':
    unittest.main()
