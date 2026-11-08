"""Edit-mode boundaries, numbering, row placement, and Excel round trips."""

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation

from config import ROW_BACKGROUND_COLORS
from df_search import LABEL_ORDER
from excel_export import workbook_bytes
from lexicon_db import LexiconDB
from main import create_app
from tests.auth_helpers import authenticate
from tests.test_flask_app import Page


class CreationTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.source = self.root / 'creation.xlsx'
        self.database = self.root / 'creation.sqlite3'
        book = Workbook()
        sheet = book.active
        sheet.title = 'Lexicon'
        sheet.append(['Label', 'LIMBA FRANCEZĂ', 'LIMBA ROMÂNĂ', 'Notes'])
        sheet.append([LABEL_ORDER[0], 'first', 'romanian'])
        sheet.append([LABEL_ORDER[1], 'sense one'])
        sheet.append([None, 'sense two'])
        sheet.append([LABEL_ORDER[2], 'extension'])
        sheet.append([LABEL_ORDER[3], 'special', None, '=B7'])
        sheet.append([LABEL_ORDER[0], 'second'])
        sheet.append([LABEL_ORDER[1], 'another sense'])
        sheet['A4'].fill = PatternFill('solid', fgColor='FFFFAA')
        sheet['B4'].fill = PatternFill('solid', fgColor='CCFFCC')
        sheet['B4'].font = Font(name='Arial', sz=14, color='FF0000FF')
        sheet.row_dimensions[4].height = 55
        sheet.merge_cells('C3:D3')
        validation = DataValidation(type='custom', formula1='B7<>""')
        validation.add('B3:B8')
        sheet.add_data_validation(validation)
        sheet.print_area = 'A1:D8'
        other = book.create_sheet('Other')
        other['A1'] = 'keep this'
        other['B1'] = '=Lexicon!$B$7'
        other['C1'] = '=B7'
        other['D1'] = '=lexicon!b7'
        other['E1'] = '="Lexicon!B7"'
        book.save(self.source)
        book.close()
        with ZipFile(self.source, 'a') as archive:
            archive.writestr('customXml/keep.xml', '<keep/>')
        self.original = self.source.read_bytes()
        self.store = LexiconDB(self.database, self.source)
        self.addCleanup(self.store.close)

    def open_app(self, **config):
        app = create_app(self.source, database_path=self.database, test_config={'DEFAULT_UI_LANGUAGE':'en',
            'TESTING': True, 'SECRET_KEY': 'creation', **config,
        })
        self.addCleanup(app.extensions['lexicon_store'].close)
        return app

    def test_row_numbering_placement_style_and_full_excel_round_trip(self):
        row = self.store.add_row(1, LABEL_ORDER[1], 'new French sense')
        self.assertEqual(row, {'etimon': 1, 'label': LABEL_ORDER[1], 'label_number': 3})
        new = self.store.add_etymon('new headword')
        self.assertEqual(new['etimon'], 3)
        self.assertEqual(new['label_number'], 1)
        # A subsequent cell edit still addresses the original row after shifts.
        self.store.save_cell((2, LABEL_ORDER[0], 1, 'LIMBA FRANCEZĂ'), 0, [{'insert': 'second edited\n'}])
        payload = workbook_bytes(self.store)
        book = load_workbook(BytesIO(payload), rich_text=True)
        self.addCleanup(book.close)
        sheet = book['Lexicon']
        self.assertEqual(str(sheet['B5'].value), 'new French sense')
        self.assertEqual(sheet['A5'].value, LABEL_ORDER[1])
        self.assertEqual(sheet['B5'].fill.fgColor.rgb, 'FFF7CAAC')
        self.assertEqual(sheet['A5'].fill.fgColor.rgb, 'FFF7CAAC')
        self.assertEqual(sheet['A4'].fill.fgColor.rgb, '00FFFFAA')
        self.assertEqual(sheet['B4'].fill.fgColor.rgb, '00CCFFCC')
        self.assertEqual(sheet.row_dimensions[5].height, 55)
        self.assertEqual(sheet['D7'].value, '=B8')
        self.assertEqual(book['Other']['B1'].value, '=Lexicon!$B$8')
        self.assertEqual(book['Other']['C1'].value, '=B7')
        self.assertEqual(book['Other']['D1'].value, '=lexicon!b8')
        self.assertEqual(book['Other']['E1'].value, '="Lexicon!B7"')
        self.assertEqual(str(sheet['B8'].value), 'second edited')
        self.assertEqual(str(sheet['B10'].value), 'new headword')
        self.assertEqual(str(sheet.data_validations.dataValidation[0].sqref), 'B3:B9')
        self.assertEqual(sheet.data_validations.dataValidation[0].formula1, 'B8<>""')
        self.assertEqual(str(sheet.merged_cells), 'C3:D3')
        self.assertIn('$D$9', str(sheet.print_area))
        exported = self.root / 'updated.xlsx'
        exported.write_bytes(payload)
        reopened = LexiconDB(self.root / 'reimport.sqlite3', exported)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.cell((1, LABEL_ORDER[1], 3, 'LIMBA FRANCEZĂ'))['plaintext_content'], 'new French sense')
        self.assertEqual(reopened.entries()[3]['form'], 'new headword')
        self.assertEqual(self.source.read_bytes(), self.original)
        with ZipFile(BytesIO(payload)) as archive:
            self.assertEqual(archive.read('customXml/keep.xml'), b'<keep/>')

    def test_missing_types_number_independently_and_empty_text_is_atomic(self):
        first = self.store.add_row(2, LABEL_ORDER[3], 'special second etymon')
        second = self.store.add_row(2, LABEL_ORDER[2], 'extension second etymon')
        self.assertEqual(first['label_number'], 1)
        self.assertEqual(second['label_number'], 1)
        before = [dict(row) for row in self.store.connection.execute('SELECT * FROM row_metadata')]
        for text in ('', '  \n\t', None, 42):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    self.store.add_row(1, LABEL_ORDER[1], text)
                with self.assertRaises(ValueError):
                    self.store.add_etymon(text)
        self.assertEqual(before, [dict(row) for row in self.store.connection.execute('SELECT * FROM row_metadata')])
        with self.assertRaises(ValueError):
            self.store.add_row(1, LABEL_ORDER[0], 'forbidden')
        with self.assertRaises(ValueError):
            self.store.add_row(999, LABEL_ORDER[1], 'missing')

    def test_new_rows_have_complete_borders_without_changing_original_cells(self):
        book = load_workbook(self.source)
        sheet = book['Lexicon']
        thin = Side(style='thin', color='FF112233')
        medium = Side(style='medium', color='FF334455')
        sheet['A4'].border = Border(left=medium, right=thin, bottom=thin)
        sheet['B4'].border = Border(left=thin, right=thin, top=thin, bottom=thin)
        sheet['C4'].border = Border()
        sheet['D4'].border = Border(left=thin, right=medium, bottom=thin)
        book.save(self.source)
        book.close()
        original = self.source.read_bytes()
        store = LexiconDB(':memory:', self.source)
        self.addCleanup(store.close)
        store.add_row(1, LABEL_ORDER[1], 'new sense')
        store.add_etymon('third')
        exported = load_workbook(BytesIO(workbook_bytes(store)))
        self.addCleanup(exported.close)
        sheet = exported['Lexicon']
        for number in (5, 10):
            for column in range(1, 5):
                for name in ('left', 'right', 'top', 'bottom'):
                    self.assertTrue(getattr(sheet.cell(number, column).border, name).style,
                                    (number, column, name))
        self.assertEqual(sheet['A5'].border.left.style, 'medium')
        self.assertEqual(sheet['D5'].border.right.style, 'medium')
        self.assertEqual(sheet['D5'].border.top.color.rgb, 'FF112233')
        self.assertEqual(sheet['B5'].fill.fgColor.rgb, 'FFF7CAAC')
        self.assertIsNone(sheet['A4'].border.top)
        self.assertIsNone(sheet['C4'].border.left)
        self.assertEqual(self.source.read_bytes(), original)

    def test_export_large_worksheet_after_adding_rows_does_not_recurse_through_dom(self):
        source = self.root / 'large.xlsx'
        book = Workbook()
        sheet = book.active
        sheet.append(['Label', 'LIMBA FRANCEZĂ', 'LIMBA ROMÂNĂ'])
        sheet.append([LABEL_ORDER[0], 'first'])
        for number in range(1200):
            sheet.append([LABEL_ORDER[1] if number == 0 else None, f'sense {number}'])
        sheet['A1202'].fill = PatternFill('solid', fgColor='FFFFAA')
        sheet['B1202'].fill = PatternFill('solid', fgColor='CCFFCC')
        sheet.row_dimensions[1202].height = 42
        sheet.append([LABEL_ORDER[0], 'second'])
        book.create_sheet('Untouched')['A1'] = 'keep this'
        book.save(source)
        book.close()
        original = source.read_bytes()
        app = create_app(source, database_path=self.root / 'large.sqlite3', test_config={'DEFAULT_UI_LANGUAGE':'en',
            'TESTING': True, 'EXPORT_DIRECTORY': str(self.root / 'downloads'),
        })
        store = app.extensions['lexicon_store']
        self.addCleanup(store.close)
        store.add_row(1, LABEL_ORDER[1], 'new sense')
        store.add_etymon('third')
        response = app.test_client().get('/export')
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 200)
        exported = load_workbook(BytesIO(response.data), rich_text=True)
        self.addCleanup(exported.close)
        sheet = exported.worksheets[0]
        self.assertEqual(str(sheet['B1202'].value), 'sense 1199')
        self.assertEqual(str(sheet['B1203'].value), 'new sense')
        self.assertEqual(str(sheet['B1204'].value), 'second')
        self.assertEqual(str(sheet['B1205'].value), 'third')
        self.assertEqual(sheet['B1203'].fill.fgColor.rgb, 'FFF7CAAC')
        self.assertEqual(sheet['A1203'].fill.fgColor.rgb, 'FFF7CAAC')
        self.assertEqual(sheet.row_dimensions[1203].height, 42)
        self.assertEqual(exported['Untouched']['A1'].value, 'keep this')
        self.assertEqual(source.read_bytes(), original)

    def test_inserting_after_label_only_row_preserves_following_inherited_label(self):
        book = load_workbook(self.source)
        sheet = book['Lexicon']
        sheet['A5'] = LABEL_ORDER[3]
        sheet['B5'] = None
        sheet['A6'] = None
        book.save(self.source)
        book.close()
        store = LexiconDB(':memory:', self.source)
        self.addCleanup(store.close)
        store.add_row(1, LABEL_ORDER[2], 'inserted extension')
        exported = self.root / 'inherited.xlsx'
        exported.write_bytes(workbook_bytes(store))
        imported = LexiconDB(':memory:', exported)
        self.addCleanup(imported.close)
        self.assertEqual(imported.cell((1, LABEL_ORDER[3], 1, 'LIMBA FRANCEZĂ'))['plaintext_content'], 'special')
        self.assertEqual(imported.cell((1, LABEL_ORDER[2], 1, 'LIMBA FRANCEZĂ'))['plaintext_content'], 'inserted extension')

    def test_row_creation_reuses_existing_label_spelling_and_spacing(self):
        book = load_workbook(self.source)
        book['Lexicon']['A3'] = ' SENSURI DE BAZA  '
        book.save(self.source)
        book.close()
        store = LexiconDB(':memory:', self.source)
        self.addCleanup(store.close)
        label = store.row_labels(1)[0]
        self.assertEqual(label, ' SENSURI DE BAZA  ')
        self.assertEqual(store.add_row(1, label, 'new')['label_number'], 3)
        self.assertEqual(store.cell((1, label, 3, 'LIMBA FRANCEZĂ'))['background_color'], '#F7CAAC')

    def test_new_etymon_uses_type_colors_even_without_donor_rows(self):
        book = load_workbook(self.source)
        book['Lexicon'].delete_rows(3, 6)
        book.save(self.source)
        book.close()
        store = LexiconDB(':memory:', self.source)
        self.addCleanup(store.close)
        created = [store.add_etymon('new headword')]
        created.extend(store.add_row(2, label, 'new content') for label in LABEL_ORDER[1:])
        frame = store.to_dataframe(2)
        book = load_workbook(BytesIO(workbook_bytes(store)))
        self.addCleanup(book.close)
        for row in created:
            color = ROW_BACKGROUND_COLORS[row['label']]
            key = (2, row['label'], 1)
            self.assertEqual(frame.attrs['label_backgrounds'][key], color)
            for column in ('LIMBA FRANCEZĂ', 'LIMBA ROMÂNĂ', 'LIMBA CATALANĂ', 'Notes'):
                self.assertEqual(frame.attrs['empty_cell_backgrounds'][(*key, column)], color)
            position = store.connection.execute('SELECT sheet_row FROM row_metadata WHERE etimon_number=? AND label=?',
                                                key[:2]).fetchone()[0]
            for column in range(1, 5):
                cell = book['Lexicon'].cell(position, column)
                self.assertEqual(cell.fill.patternType, 'solid')
                self.assertEqual(cell.fill.fgColor.rgb, 'FF' + color[1:])

    def test_configured_colors_reach_browser_and_persist_after_edit_and_restart(self):
        self.store.connection.execute('UPDATE row_types SET default_background=? WHERE name=?', ('#AABBCC',LABEL_ORDER[1]))
        app = self.open_app()
        store = app.extensions['lexicon_store']
        client = app.test_client()
        headers = {'X-CSRF-Token': Page(client.get('/')).payload['csrf']}
        authenticate(client)
        client.post('/mode', json={'edit_mode': True}, headers=headers)
        client.post('/etymons', json={'text': 'new headword'}, headers=headers)
        response = client.post('/rows', json={'etimon': 3, 'label': LABEL_ORDER[1], 'text': 'new sense'}, headers=headers)
        self.assertEqual(response.status_code, 201)
        key = (3, LABEL_ORDER[1], 1, 'LIMBA ROMÂNĂ')
        store.save_cell(key, 0, [{'insert': 'Romanian added later\n'}])
        row = Page(client.get('/')).payload['rows'][1]
        self.assertTrue(row['backgrounds'])
        self.assertEqual(set(row['backgrounds'].values()), {'#AABBCC'})
        self.assertEqual(store.cell(key)['background_color'], '#AABBCC')
        self.source.unlink()
        reopened = LexiconDB(self.database)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.to_dataframe(3).attrs['label_backgrounds'][key[:3]], '#AABBCC')
        exported = load_workbook(BytesIO(workbook_bytes(reopened)))
        self.addCleanup(exported.close)
        for column in range(1, 5):
            self.assertEqual(exported['Lexicon'].cell(10, column).fill.fgColor.rgb, 'FFAABBCC')
        # Reopening uses the persisted type definition for future rows too.
        reopened.add_row(3, LABEL_ORDER[1], 'future row')
        frame = reopened.to_dataframe(3)
        self.assertEqual(frame.attrs['label_backgrounds'][key[:3]], '#AABBCC')
        self.assertEqual(frame.attrs['label_backgrounds'][(3, LABEL_ORDER[1], 2)], '#AABBCC')

    def test_invalid_row_colors_fail_before_creating_database(self):
        for invalid in (None, {}, {**ROW_BACKGROUND_COLORS, LABEL_ORDER[1]: 'orange'},
                        {**ROW_BACKGROUND_COLORS, LABEL_ORDER[1]: None}):
            with self.subTest(colors=invalid):
                destination = self.root / 'invalid.sqlite3'
                with self.assertRaisesRegex(ValueError, 'ROW_BACKGROUND_COLORS'):
                    create_app(self.source, database_path=destination,
                               test_config={'DEFAULT_UI_LANGUAGE':'en', 'TESTING': True, 'ROW_BACKGROUND_COLORS': invalid})
                self.assertFalse(destination.exists())

    def test_creation_is_serialized_across_connections_and_survives_restart(self):
        other = LexiconDB(self.database)
        self.addCleanup(other.close)
        other.to_dataframe()  # Warm the background cache before external insertions.
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda store: store.add_row(1, LABEL_ORDER[1], 'concurrent'), [self.store, other]))
        self.assertEqual(sorted(result['label_number'] for result in results), [3, 4])
        self.assertIn((1, LABEL_ORDER[1], 3, 'LIMBA FRANCEZĂ'), other.to_dataframe().attrs['empty_cell_backgrounds'])
        self.source.unlink()
        reopened = LexiconDB(self.database)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.cell((1, LABEL_ORDER[1], 4, 'LIMBA FRANCEZĂ'))['plaintext_content'], 'concurrent')
        self.assertTrue(workbook_bytes(reopened))

    def test_older_database_schema_is_rejected_without_modification(self):
        self.source.unlink()
        for version in (1,2,3):
            with self.subTest(version=version):
                self.store.connection.execute('UPDATE dataset SET schema_version=?',(version,))
                before = self.database.read_bytes()
                with self.assertRaisesRegex(ValueError,'Reimport'):
                    LexiconDB(self.database)
                self.assertEqual(self.database.read_bytes(),before)

    def test_search_mode_blocks_all_content_mutations_and_modes_are_browser_local(self):
        app = self.open_app()
        client, other = app.test_client(), app.test_client()
        authenticate(client)
        page = Page(client.get('/?search=1&q=first'))
        self.assertFalse(page.payload['edit_mode'])
        headers = {'X-CSRF-Token': page.payload['csrf']}
        for path, body in [('/cell', {'token': page.payload['rows'][0]['editors']['content_0']['token'], 'ops': [{'insert': 'x\n'}]}),
                           ('/rows', {'etimon': 1, 'label': LABEL_ORDER[1], 'text': 'new'}), ('/etymons', {'text': 'new'})]:
            self.assertEqual(client.post(path, json=body, headers=headers).status_code, 403)
        self.assertEqual(client.post('/mode', json={'edit_mode': True}).status_code, 403)
        self.assertEqual(client.post('/mode', json={'edit_mode': 'yes'}, headers=headers).status_code, 400)
        self.assertEqual(client.post('/mode', json={'edit_mode': True}, headers=headers).status_code, 200)
        editing = Page(client.get('/'))
        self.assertTrue(editing.payload['edit_mode'])
        self.assertEqual(editing.matches, [1])
        self.assertEqual(editing.payload['criteria']['query'], 'first')
        filtered = Page(client.get('/?search=1&q=second&column=LIMBA+FRANCEZĂ'))
        self.assertEqual(filtered.matches, [2])
        self.assertEqual(filtered.payload['criteria']['column'], ['LIMBA FRANCEZĂ'])
        self.assertFalse(Page(other.get('/')).payload['edit_mode'])
        self.assertEqual(client.post('/mode', json={'edit_mode': False}, headers=headers).status_code, 200)
        self.assertEqual(Page(client.get('/')).matches, [2])

    def test_creation_endpoints_require_text_and_reject_etymon_row_insertion(self):
        client = self.open_app().test_client()
        payload = Page(client.get('/')).payload
        headers = {'X-CSRF-Token': payload['csrf']}
        authenticate(client)
        client.post('/mode', json={'edit_mode': True}, headers=headers)
        for body in ({'etimon': 1, 'label': LABEL_ORDER[0], 'text': 'x'},
                     {'etimon': True, 'label': LABEL_ORDER[1], 'text': 'x'},
                     {'etimon': 1, 'label': LABEL_ORDER[1], 'text': '  '}):
            self.assertEqual(client.post('/rows', json=body, headers=headers).status_code, 400)
        self.assertEqual(client.post('/etymons', json={'text': ''}, headers=headers).status_code, 400)
        created = client.post('/rows', json={'etimon': 1, 'label': LABEL_ORDER[1], 'text': 'new'}, headers=headers)
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json['label_number'], 3)
        new = client.post('/etymons', json={'text': 'third'}, headers=headers)
        self.assertEqual(new.status_code, 201)
        page = Page(client.get('/'))
        self.assertEqual(page.selected, 3)
        self.assertEqual(page.payload['total'], 3)
        self.assertIn('third', page.payload['title'])


if __name__ == '__main__':
    unittest.main()
