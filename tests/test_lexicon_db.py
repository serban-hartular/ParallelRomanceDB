"""Persistent storage and faithful, timestamped workbook exports."""

from datetime import datetime
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile
from zoneinfo import ZoneInfo

from openpyxl import Workbook, load_workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.styles import Font, PatternFill

from excel_export import export_timestamped, overwrite_sheet, workbook_bytes
from extract_sheet import excel_to_dataframe
from lexicon_db import EditConflict, FRAME_COLUMNS, LexiconDB
from main import create_app
from tests.auth_helpers import authenticate, save_edit
from tests.test_flask_app import Page


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / 'linguists.xlsx'
        self.database = self.root / 'linguists.sqlite3'
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = 'Lexicon'
        sheet.append([' LABEL ', 'LIMBA FRANCEZĂ', 'LIMBA ROMÂNĂ', ' NOTES  ', 'Empty heading'])
        sheet.append(['ETIMON/ CORESPONDENTE ROMANICE', 'café', None, '=1+2'])
        sheet['B2'] = CellRichText(' café ', TextBlock(InlineFont(b=True, u='double', color='FF123456'), 'rich'))
        sheet['B2'].font = Font(name='Times New Roman', sz=12)
        sheet['B2'].fill = PatternFill('solid', fgColor='AABBCC')
        sheet.append([None, None])
        sheet.append(['SENSURI DE BAZĂ', '  original\t text\n  ', None, 'a note'])
        sheet['A4'].fill = PatternFill('solid', fgColor='FFFFAA')
        sheet.append([None, 'continued'])
        sheet.append([' EXTENSIONS  ', None])
        sheet.append([None, 'after a label-only row'])
        sheet.row_dimensions[4].height = 25
        sheet.row_dimensions[4].font = Font(name='Arial', italic=True, color='FF778899')
        sheet.column_dimensions['B'].width = 35
        sheet.freeze_panes = 'B2'
        other = workbook.create_sheet('Other sheet')
        other['A1'] = 'untouched'
        other['B2'] = '=Lexicon!B2'
        other['A1'].font = Font(bold=True, color='FF990000')
        workbook.active = 1
        workbook.save(self.source)
        workbook.close()
        # An unrelated archive member must survive normal export byte-for-byte.
        with ZipFile(self.source, 'a') as archive:
            archive.writestr('customXml/unchanged.xml', '<original data="keep me"/>')
        self.original = self.source.read_bytes()
        self.store = self.open_store()

    def open_store(self, source=None):
        store = LexiconDB(self.database, source or self.source)
        self.addCleanup(store.close)
        return store

    def key(self, label='SENSURI DE BAZĂ', column='LIMBA FRANCEZĂ', number=1):
        return (1, label, number, column)

    def save(self, key, text, **kwargs):
        self.store.save_cell(key, self.store.cell(key)['revision'], [{'insert': text + '\n'}], **kwargs)

    def test_schema_and_import_retain_dataframe_fields_and_positions(self):
        fields = [row[1] for row in self.store.connection.execute('PRAGMA table_info(cells)')]
        self.assertTrue({'row_id','column_id','content','revision','line_height'}.issubset(fields))
        self.assertEqual(len(self.store.connection.execute('PRAGMA foreign_key_list(cells)').fetchall()),2)
        imported = excel_to_dataframe(self.source)
        stored = self.store.to_dataframe()
        self.assertEqual(list(stored.columns), list(FRAME_COLUMNS))
        self.assertEqual(stored.to_dict('records'), imported.to_dict('records'))
        self.assertEqual(stored.attrs['label_backgrounds'], imported.attrs['label_backgrounds'])
        positions = {tuple(row[:3]): row[3] for row in self.store.connection.execute(
            'SELECT etimon_number,label,label_number,sheet_row FROM row_metadata')}
        self.assertEqual(positions[self.key()[:3]], 4)
        self.assertEqual(positions[self.key(label=' EXTENSIONS  ')[:3]], 7)
        self.assertEqual(self.store.metadata['sheet_name'], 'Lexicon')

    def test_restart_reopens_database_without_reading_or_reimporting_workbook(self):
        key = self.key()
        identity = self.store.cell(key)['id']
        self.save(key, 'Prăjitură', line_height_provided=True, line_height=2)
        self.source.unlink()
        with patch('extract_sheet.excel_to_dataframe', side_effect=AssertionError('must not import')):
            reopened = self.open_store()
        self.assertEqual(reopened.cell(key)['id'], identity)
        self.assertEqual(reopened.cell(key)['revision'], 1)
        self.assertEqual(reopened.cell(key)['plaintext_content'], 'Prăjitură')
        self.assertEqual(reopened.cell(key)['line_height'], 2)
        self.assertEqual(reopened.matching_numbers('prajitura'), (1,))
        self.assertEqual(reopened.matching_numbers('original'), ())
        # The saved workbook template makes export independent of the source.
        workbook = load_workbook(BytesIO(workbook_bytes(reopened)), rich_text=True)
        self.addCleanup(workbook.close)
        self.assertEqual(str(workbook['Lexicon']['B4'].value), 'Prăjitură')

    def test_separate_connections_share_updates_and_reject_stale_saves(self):
        second = self.open_store()
        key = self.key()
        old_revision = second.cell(key)['revision']
        self.save(key, 'first edit')
        self.assertEqual(second.cell(key)['plaintext_content'], 'first edit')
        with self.assertRaises(EditConflict):
            second.save_cell(key, old_revision, [{'insert': 'stale edit\n'}])
        self.assertEqual(second.cell(key)['plaintext_content'], 'first edit')

    def test_search_keeps_literal_unicode_behavior(self):
        self.save(self.key(), 'Prăjitură Œ Æ ø ł l·l 100% a_b [x]')
        for query in ('PRAJITURA', 'oe', 'ae', 'o l ll', '%', '_', '[x]'):
            with self.subTest(query=query):
                self.assertEqual(self.store.matching_numbers(query), (1,))
        self.assertEqual(self.store.matching_numbers('a%b'), ())
        self.assertEqual(self.store.matching_numbers('prajitura', columns=[' NOTES  ']), ())

    def test_unchanged_export_is_exact_original_and_timestamp_collisions_are_safe(self):
        self.assertEqual(workbook_bytes(self.store), self.original)
        now = datetime(2026, 11, 5, 15, 4, 3, tzinfo=ZoneInfo('Europe/Bucharest'))
        first = export_timestamped(self.store, self.root / 'exports', now=now)
        second = export_timestamped(self.store, self.root / 'exports', now=now)
        self.assertNotEqual(first, second)
        self.assertIn('2026-11-05_15-04-03', first.name)
        self.assertEqual(first.read_bytes(), self.original)
        self.assertEqual(second.read_bytes(), self.original)
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_export_updates_rich_text_at_original_coordinates_and_preserves_archive(self):
        key = self.key()
        self.store.save_cell(key, 0, [
            {'insert': '  edited\t', 'attributes': {'bold': True, 'size': '18pt', 'color': '#123456', 'font': 'Arial'}},
            {'insert': '2', 'attributes': {'script': 'super'}},
            {'insert': '\nsecond line  \n'},
        ], line_height_provided=True, line_height=2)
        payload = workbook_bytes(self.store)
        workbook = load_workbook(BytesIO(payload), rich_text=True)
        self.addCleanup(workbook.close)
        sheet = workbook['Lexicon']
        self.assertEqual(workbook.sheetnames, ['Lexicon', 'Other sheet'])
        self.assertEqual(str(sheet['B4'].value), '  edited\t2\nsecond line  ')
        run = sheet['B4'].value[0]
        self.assertEqual(run.font.rFont, 'Arial')
        self.assertEqual(run.font.sz, 18)
        self.assertTrue(run.font.b)
        self.assertEqual(run.font.color.rgb, 'FF123456')
        self.assertEqual(sheet['B4'].value[1].font.vertAlign, 'superscript')
        self.assertEqual(sheet['A4'].value, 'SENSURI DE BAZĂ')
        self.assertIsNone(sheet['A5'].value)
        self.assertEqual(sheet['A4'].fill.fgColor.rgb, '00FFFFAA')
        self.assertEqual(sheet['D2'].value, '=1+2')
        self.assertEqual(sheet['D2'].data_type, 'f')
        self.assertEqual(sheet.freeze_panes, 'B2')
        self.assertGreater(sheet.row_dimensions[4].height, 25)
        with ZipFile(BytesIO(self.original)) as before, ZipFile(BytesIO(payload)) as after:
            self.assertEqual(before.namelist(), after.namelist())
            for name in before.namelist():
                if name != 'xl/worksheets/sheet1.xml':
                    self.assertEqual(before.read(name), after.read(name), name)

    def test_export_fills_and_clears_empty_cells_and_adds_a_missing_language(self):
        romanian = self.key(column='LIMBA ROMÂNĂ')
        self.save(romanian, 'new Romanian')
        identity = self.store.cell(romanian)['id']
        self.save(romanian, '')
        self.assertEqual(self.store.cell(romanian)['id'], identity)
        self.save(self.key(column='LIMBA ITALIANĂ'), 'italiano')
        workbook = load_workbook(BytesIO(workbook_bytes(self.store)), rich_text=True)
        self.addCleanup(workbook.close)
        sheet = workbook['Lexicon']
        self.assertFalse(sheet['C4'].value)
        self.assertEqual(sheet['F1'].value, 'LIMBA ITALIANĂ')
        self.assertEqual(str(sheet['F4'].value), 'italiano')
        self.assertEqual(sheet['D1'].value, ' NOTES  ')

    def test_edited_formula_like_text_is_exported_as_text(self):
        self.save(self.key(column=' NOTES  ', label='ETIMON/ CORESPONDENTE ROMANICE'), '=SUM(1,2)')
        workbook = load_workbook(BytesIO(workbook_bytes(self.store)), rich_text=True)
        self.addCleanup(workbook.close)
        cell = workbook['Lexicon']['D2']
        self.assertEqual(str(cell.value), '=SUM(1,2)')
        self.assertEqual(cell.data_type, 's')
        target = self.root / 'formula-target.xlsx'
        target.write_bytes(self.original)
        overwrite_sheet(self.store, target)
        overwritten = load_workbook(target, rich_text=True)
        self.addCleanup(overwritten.close)
        self.assertEqual(overwritten['Lexicon']['D2'].data_type, 's')

    def test_explicit_sheet_overwrite_preserves_other_sheet_data(self):
        self.save(self.key(), 'replacement')
        target = self.root / 'existing.xlsx'
        workbook = load_workbook(BytesIO(self.original), rich_text=True)
        workbook['Other sheet']['A1'] = 'local change in target'
        workbook.save(target)
        workbook.close()
        overwrite_sheet(self.store, target)
        result = load_workbook(target, rich_text=True)
        self.addCleanup(result.close)
        self.assertEqual(str(result['Lexicon']['B4'].value), 'replacement')
        self.assertEqual(result['Lexicon']['A4'].fill.fgColor.rgb, '00FFFFAA')
        self.assertEqual(result['Lexicon'].row_dimensions[4].font.name, 'Arial')
        self.assertEqual(result['Lexicon'].row_dimensions[4].font.color.rgb, 'FF778899')
        self.assertEqual(result['Other sheet']['A1'].value, 'local change in target')
        self.assertEqual(result['Other sheet']['B2'].value, '=Lexicon!B2')
        self.assertEqual(self.source.read_bytes(), self.original)
        before = target.read_bytes()
        with self.assertRaises(ValueError):
            overwrite_sheet(self.store, target, sheet_name='does not exist')
        self.assertEqual(target.read_bytes(), before)

    def test_app_restart_search_and_download_use_saved_database(self):
        options = {'TESTING': True, 'SECRET_KEY': 'persistent', 'EXPORT_DIRECTORY': str(self.root / 'downloads')}
        app = create_app(self.source, database_path=self.database, test_config=options)
        self.addCleanup(app.extensions['lexicon_store'].close)
        client = app.test_client()
        payload = authenticate(client)
        editor = payload['rows'][0]['editors']['content_0']
        client.post('/mode', json={'edit_mode': True}, headers={'X-CSRF-Token': payload['csrf']})
        result = save_edit(client,payload,[{'insert':'Saved headword\n'}],line_height=1.5)
        self.assertEqual(result.status_code, 200)
        self.source.unlink()
        reopened = create_app(self.source, database_path=self.database, test_config=options)
        self.addCleanup(reopened.extensions['lexicon_store'].close)
        client = reopened.test_client()
        self.assertEqual(Page(client.get('/?search=1&q=saved')).matches, [1])
        download = client.get('/export')
        self.addCleanup(download.close)
        self.assertEqual(download.status_code, 200)
        self.assertIn('attachment;', download.headers['Content-Disposition'])
        workbook = load_workbook(BytesIO(download.data), rich_text=True)
        self.addCleanup(workbook.close)
        self.assertEqual(str(workbook['Lexicon']['B2'].value), 'Saved headword')
        self.assertEqual(workbook['Other sheet']['A1'].value, 'untouched')
        self.assertEqual(len(list((self.root / 'downloads').glob('*.xlsx'))), 1)


if __name__ == '__main__':
    unittest.main()
