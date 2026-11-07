"""Recoverable deletion, stale requests, and structural Excel export."""

from contextlib import redirect_stdout
from io import BytesIO, StringIO
import unittest

from openpyxl import load_workbook

from df_search import LABEL_ORDER
from excel_export import workbook_bytes
from lexicon_db import EditConflict, LexiconDB
from tests import test_creation
from tests.auth_helpers import authenticate
from tests.test_flask_app import Page
from trash import main as trash_command


class TrashTests(unittest.TestCase):
    def setUp(self):
        test_creation.CreationTests.setUp(self)

    def open_app(self):
        return test_creation.CreationTests.open_app(self)

    def test_row_retains_every_cell_and_format_and_recovers_after_restart(self):
        key = (1, LABEL_ORDER[1], 2, 'LIMBA FRANCEZĂ')
        self.store.save_cell(key, 0, [{'insert': 'edited sense', 'attributes': {'color': '#123456', 'bold': True}},
                                     {'insert': '\n'}], line_height_provided=True, line_height=2)
        before = dict(self.store.connection.execute('SELECT * FROM cells WHERE id=?', (self.store.cell(key)['id'],)).fetchone())
        self.store.to_dataframe()  # Warm the cache before another connection changes Trash.
        trash_id = self.store.delete_row(*key[:3])
        self.assertIsNone(self.store.cell(key)['id'])
        self.assertEqual(self.store.matching_numbers('edited sense'), ())
        self.assertEqual(self.store.entries()[1]['form'], 'first')
        saved = dict(self.store.connection.execute('SELECT * FROM cells WHERE id=?', (before['id'],)).fetchone())
        self.assertEqual(saved, before)
        entry = self.store.list_trash()[0]
        self.assertEqual((entry['id'], entry['kind'], entry['row_count']), (trash_id, 'row', 1))
        self.assertTrue(entry['deleted_at'].endswith('+00:00'))
        self.source.unlink()
        reopened = LexiconDB(self.database)
        self.addCleanup(reopened.close)
        self.assertEqual(len(reopened.list_trash()), 1)
        reopened.restore_trash(trash_id)
        restored = self.store.cell(key)
        self.assertEqual({name: restored[name] for name in before}, before)
        self.assertEqual(restored['generation'], 2)
        self.assertEqual(self.store.list_trash(), [])
        self.assertEqual(self.store.to_dataframe().attrs['empty_cell_backgrounds'][(*key[:3], 'LIMBA ROMÂNĂ')], '#FFFFAA')

    def test_etymon_removes_all_languages_and_reserves_numbers_for_recovery(self):
        old = self.store.export_snapshot()['cells']
        trash_id = self.store.delete_etymon(1)
        self.assertEqual(list(self.store.entries()), [2])
        self.assertNotIn(1, self.store.matching_numbers(''))
        self.assertFalse(self.store.to_dataframe()['etimon_number'].eq(1).any())
        self.assertEqual(self.store.list_trash()[0]['row_count'], 5)
        self.assertEqual(self.store.add_etymon('third')['etimon'], 3)
        self.store.restore_trash(trash_id)
        self.assertEqual(list(self.store.entries()), [1, 2, 3])
        restored = self.store.export_snapshot()['cells']
        self.assertEqual([cell for cell in restored if cell['etimon_number'] < 3], old)

    def test_separate_row_trash_requires_containing_etymon_and_numbers_are_not_reused(self):
        row_id = self.store.delete_row(1, LABEL_ORDER[1], 2)
        created = self.store.add_row(1, LABEL_ORDER[1], 'after deletion')
        self.assertEqual(created['label_number'], 3)
        etymon_id = self.store.delete_etymon(1)
        with self.assertRaisesRegex(ValueError, 'etymon first'):
            self.store.restore_trash(row_id)
        self.store.restore_trash(etymon_id)
        self.assertIsNone(self.store.cell((1, LABEL_ORDER[1], 2, 'LIMBA FRANCEZĂ'))['id'])
        self.store.restore_trash(row_id)
        self.assertEqual(self.store.cell((1, LABEL_ORDER[1], 2, 'LIMBA FRANCEZĂ'))['plaintext_content'], 'sense two')
        book = load_workbook(BytesIO(workbook_bytes(self.store)), rich_text=True)
        self.addCleanup(book.close)
        self.assertEqual([str(book['Lexicon'].cell(number, 2).value) for number in (3, 4, 5)],
                         ['sense one', 'sense two', 'after deletion'])
        with self.assertRaises(ValueError):
            self.store.restore_trash(row_id)
        with self.assertRaisesRegex(ValueError, 'Delete etymon'):
            self.store.delete_row(1, LABEL_ORDER[0], 1)

    def test_deletion_confirmation_csrf_mode_and_stale_editor_guards(self):
        client = self.open_app().test_client()
        initial = Page(client.get('/')).payload
        headers = {'X-CSRF-Token': initial['csrf']}
        self.assertEqual(client.post('/trash', json={}).status_code, 403)
        self.assertEqual(client.post('/trash', json={}, headers=headers).status_code, 401)
        authenticate(client)
        client.post('/mode', json={'edit_mode': True}, headers=headers)
        payload = Page(client.get('/')).payload
        row = next(row for row in payload['rows'] if row['label'] == LABEL_ORDER[1] and row['label_number'] == 1)
        self.assertIsNone(payload['rows'][0]['delete_token'])
        token = row['delete_token']
        self.assertEqual(client.post('/trash', json={'token': token}, headers=headers).status_code, 400)
        self.assertEqual(client.post('/trash', json={'token': 'forged', 'confirmation': 'DELETE'}, headers=headers).status_code, 409)
        self.assertEqual(client.post('/trash', json={'token': row['editors']['content_0']['token'], 'confirmation': 'DELETE'}, headers=headers).status_code, 409)
        self.assertEqual(client.post('/cell', json={'token': token, 'ops': []}, headers=headers).status_code, 409)
        response = client.post('/trash', json={'token': token, 'confirmation': 'DELETE'}, headers=headers)
        self.assertEqual(response.status_code, 200)
        stale_edit = {'token': row['editors']['content_0']['token'], 'ops': [{'insert': 'stale\n'}]}
        self.assertEqual(client.post('/cell', json=stale_edit, headers=headers).status_code, 409)
        self.store.restore_trash(response.json['trash_id'])
        self.assertEqual(client.post('/cell', json=stale_edit, headers=headers).status_code, 409)
        stale_empty = {'token': row['editors']['content_1']['token'], 'ops': [{'insert': 'stale empty\n'}]}
        self.assertEqual(client.post('/cell', json=stale_empty, headers=headers).status_code, 409)
        self.assertEqual(self.store.cell((1, LABEL_ORDER[1], 1, 'LIMBA FRANCEZĂ'))['plaintext_content'], 'sense one')

    def test_concurrent_edits_and_new_rows_invalidate_deletion_confirmation(self):
        version = self.store.deletion_version(1, LABEL_ORDER[1], 1)
        self.store.save_cell((1, LABEL_ORDER[1], 1, 'LIMBA FRANCEZĂ'), 0, [{'insert': 'newer content\n'}])
        with self.assertRaises(EditConflict):
            self.store.delete_row(1, LABEL_ORDER[1], 1, expected=version)
        etymon_version = self.store.deletion_version(1)
        self.store.add_row(1, LABEL_ORDER[3], 'newer row')
        with self.assertRaises(EditConflict):
            self.store.delete_etymon(1, expected=etymon_version)
        self.assertEqual(self.store.list_trash(), [])

    def test_export_removes_original_row_and_preserves_inherited_label_and_references(self):
        self.store.delete_row(1, LABEL_ORDER[1], 1)
        payload = workbook_bytes(self.store)
        book = load_workbook(BytesIO(payload), rich_text=True)
        self.addCleanup(book.close)
        sheet = book['Lexicon']
        self.assertEqual(str(sheet['B3'].value), 'sense two')
        self.assertEqual(sheet['A3'].value, LABEL_ORDER[1])
        self.assertEqual(sheet['A3'].fill.fgColor.rgb, 'FFFFFFAA')
        self.assertEqual(sheet['B3'].fill.fgColor.rgb, '00CCFFCC')
        self.assertEqual(sheet['D5'].value, '=B6')
        self.assertEqual(book['Other']['B1'].value, '=Lexicon!$B$6')
        self.assertEqual(str(sheet.data_validations.dataValidation[0].sqref), 'B3:B7')
        self.assertEqual(str(sheet.merged_cells), '')
        self.assertEqual(sheet.max_row, 7)
        self.assertEqual(self.source.read_bytes(), self.original)
        path = self.root / 'deleted.xlsx'
        path.write_bytes(payload)
        reimported = LexiconDB(':memory:', path)
        self.addCleanup(reimported.close)
        self.assertEqual(reimported.cell((1, LABEL_ORDER[1], 1, 'LIMBA FRANCEZĂ'))['plaintext_content'], 'sense two')

    def test_export_etymon_deletion_with_no_cell_edits_and_restore_is_exact(self):
        entry = self.store.delete_etymon(2)
        book = load_workbook(BytesIO(workbook_bytes(self.store)))
        self.addCleanup(book.close)
        self.assertEqual(book['Lexicon'].max_row, 6)
        self.assertEqual(book['Lexicon']['D6'].value, '=#REF!')
        self.assertEqual(book['Other']['B1'].value, '=Lexicon!#REF!')
        self.assertEqual(book['Other']['A1'].value, 'keep this')
        self.store.restore_trash(entry)
        self.assertEqual(workbook_bytes(self.store), self.original)

    def test_mixed_added_and_original_deletions_export_only_active_records(self):
        row = self.store.add_row(1, LABEL_ORDER[1], 'added then trashed')
        self.store.delete_row(1, row['label'], row['label_number'])
        etymon = self.store.add_etymon('added etymon then trashed')
        self.store.add_row(etymon['etimon'], LABEL_ORDER[2], 'added extension then trashed')
        self.store.delete_etymon(etymon['etimon'])
        self.store.delete_etymon(1)
        self.store.add_etymon('survivor')
        book = load_workbook(BytesIO(workbook_bytes(self.store)), rich_text=True)
        self.addCleanup(book.close)
        values = [str(row[0]) for row in book['Lexicon'].iter_rows(min_col=2, max_col=2, min_row=2, values_only=True)]
        self.assertEqual(values, ['second', 'another sense', 'survivor'])

    def test_local_administrator_command_lists_and_restores(self):
        entry = self.store.delete_etymon(2)
        listing = StringIO()
        with redirect_stdout(listing):
            self.assertEqual(trash_command([str(self.database), 'list']), 0)
        self.assertIn(f'{entry} ·', listing.getvalue())
        self.assertIn('etymon 2', listing.getvalue())
        with redirect_stdout(StringIO()):
            self.assertEqual(trash_command([str(self.database), 'restore', str(entry)]), 0)
        self.assertIn(2, self.store.entries())

    def test_etymon_export_removes_label_only_rows_in_the_deleted_section(self):
        book = load_workbook(self.source)
        sheet = book['Lexicon']
        sheet.insert_rows(2)
        sheet['A2'] = LABEL_ORDER[0]
        sheet['A3'] = None  # Marker label with no data; next row inherits it.
        book.save(self.source)
        book.close()
        store = LexiconDB(':memory:', self.source)
        self.addCleanup(store.close)
        store.delete_etymon(1)
        exported = load_workbook(BytesIO(workbook_bytes(store)))
        self.addCleanup(exported.close)
        self.assertEqual(exported['Lexicon']['A2'].value, LABEL_ORDER[0])
        self.assertEqual(exported['Lexicon']['B2'].value, 'second')
        self.assertEqual(exported['Lexicon']['B3'].value, 'another sense')

    def test_deleting_every_etymon_still_exports_and_can_create_and_restore(self):
        first = self.store.delete_etymon(1)
        second = self.store.delete_etymon(2)
        self.assertEqual(self.store.entries(), {})
        self.assertEqual(self.store.matching_numbers(''), ())
        self.assertTrue(self.store.to_dataframe().empty)
        book = load_workbook(BytesIO(workbook_bytes(self.store)))
        self.addCleanup(book.close)
        self.assertEqual(book['Lexicon'].max_row, 1)
        self.assertEqual(book['Lexicon']['B1'].value, 'LIMBA FRANCEZĂ')
        self.assertEqual(self.store.add_etymon('after clearing')['etimon'], 3)
        self.store.restore_trash(first)
        self.store.restore_trash(second)
        self.assertEqual(list(self.store.entries()), [1, 2, 3])



if __name__ == '__main__':
    unittest.main()
