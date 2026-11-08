"""In-memory editing, browser isolation, concurrency and formatted input boundaries."""

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from openpyxl import Workbook
from openpyxl.styles import PatternFill

from cell_editing import render_delta
from main import create_app
from tests.auth_helpers import authenticate, save_edit
from tests.test_flask_app import Page


class CellEditingTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'source.xlsx'
        workbook = Workbook()
        sheet = workbook.active
        sheet.append([None, 'LIMBA FRANCEZĂ', 'LIMBA ROMÂNĂ'])
        sheet.append(['ETIMON/ CORESPONDENTE ROMANICE', 'café', 'original'])
        sheet.append(['SENSURI DE BAZĂ', 'two  spaces'])
        sheet['A3'].fill = PatternFill('solid', fgColor='FFFFAA')
        sheet['B2'].fill = PatternFill('solid', fgColor='AAFFAA')
        sheet.append(['ETIMON/ CORESPONDENTE ROMANICE', 'other'])
        workbook.save(self.path)
        workbook.close()
        self.original = sha256(self.path.read_bytes()).digest()
        self.app = create_app(self.path, test_config={'DEFAULT_UI_LANGUAGE':'en', 'TESTING': True, 'SECRET_KEY': 'edit-test-key'})
        self.client = self.app.test_client()

    def payload(self, client=None, url='/'):
        target = client or self.client
        return authenticate(target,Page(target.get(url)).payload,url)

    def editor(self, payload, row=0, field='content_0'):
        return payload['rows'][row]['editors'][field]

    def save(self, payload, ops, client=None, row=0, field='content_0', token=None, **formatting):
        target = client or self.client
        target.post('/mode', json={'edit_mode': True}, headers={'X-CSRF-Token': payload['csrf']})
        return save_edit(target,payload,ops,token=token,row=row,field=field,**formatting)

    def test_save_updates_shared_data_search_titles_and_preserves_workbook(self):
        payload = self.payload()
        other = self.app.test_client()
        # Populate the old cached results before editing.
        self.assertEqual(Page(other.get('/?search=1&q=cafe')).matches, [1])
        response = self.save(payload, [{'insert': 'Prăjitură\n', 'attributes': {'bold': True}}])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Page(other.get('/?search=1&q=cafe')).matches, [])
        self.assertEqual(Page(other.get('/?search=1&q=prajitura')).matches, [1])
        displayed = self.payload(other)
        self.assertIn('Prăjitură', displayed['title'])
        self.assertIn('font-weight: bold', self.editor(displayed)['html'])
        frame = self.app.extensions['lexicon_store'].to_dataframe()
        self.assertEqual(frame.iloc[0]['plaintext_content'], 'Prăjitură')
        self.assertEqual(frame.iloc[0]['nodiacritics_plaintext'], 'Prajitura')
        self.assertEqual(frame.iloc[0]['background_color'], '#AAFFAA')
        self.assertEqual(sha256(self.path.read_bytes()).digest(), self.original)
        restarted = create_app(self.path, test_config={'DEFAULT_UI_LANGUAGE':'en', 'TESTING': True, 'SECRET_KEY': 'edit-test-key'})
        self.assertIn('café', restarted.extensions['lexicon_store'].to_dataframe().iloc[0]['plaintext_content'])

    def test_editing_plaintext_or_highlighted_display_loads_original_html(self):
        payload = self.payload(url='/?search=1&q=cafe&plaintext=1')
        self.assertEqual(payload['rows'][0]['content_0'], 'café')
        self.assertIn('<mark', payload['rows'][0]['highlights']['content_0'])
        original = self.editor(payload)['html']
        self.assertIn('<div', original)
        self.assertNotIn('<mark', original)

    def test_empty_cell_can_be_filled_and_cleared_without_changing_row_identity(self):
        payload = self.payload()
        row = next(i for i, item in enumerate(payload['rows']) if item['label'] == 'SENSURI DE BAZĂ')
        field = 'content_1'
        identity = payload['rows'][row]['id']
        self.assertEqual(self.editor(payload, row, field)['html'], '')
        self.assertEqual(self.save(payload, [{'insert': 'new text\n'}], row=row, field=field).status_code, 200)
        updated = self.payload()
        self.assertEqual(updated['rows'][row][field], '<div style="white-space: pre-wrap">new text</div>')
        self.assertEqual(updated['rows'][row]['backgrounds'][field], '#FFFFAA')
        self.assertEqual(self.save(updated, [{'insert': '\n'}], row=row, field=field).status_code, 200)
        cleared = self.payload()
        self.assertEqual(cleared['rows'][row]['id'], identity)
        self.assertEqual(cleared['rows'][row][field], '')
        self.assertEqual(cleared['rows'][row]['backgrounds'][field], '#FFFFAA')

    def test_originally_empty_cell_keeps_its_own_fill_after_edit_and_restart(self):
        from openpyxl import load_workbook

        workbook = load_workbook(self.path)
        workbook.active['C3'].fill = PatternFill('solid', fgColor='ABCDEF')
        workbook.save(self.path)
        workbook.close()
        database = Path(self.directory.name) / 'fills.sqlite3'
        app = create_app(self.path, database_path=database, test_config={'DEFAULT_UI_LANGUAGE':'en', 'TESTING': True})
        self.addCleanup(app.extensions['lexicon_store'].close)
        client = app.test_client()
        payload = self.payload(client)
        self.assertEqual(payload['rows'][1]['backgrounds']['content_1'], '#ABCDEF')
        self.assertEqual(self.save(payload, [{'insert': 'filled\n'}], client=client,
                                   row=1, field='content_1').status_code, 200)
        # Reopening also covers old initialized databases: no reimport or
        # migration is needed to recover the formerly empty cell's fill.
        self.path.unlink()
        restarted = create_app(self.path, database_path=database, test_config={'DEFAULT_UI_LANGUAGE':'en', 'TESTING': True})
        self.addCleanup(restarted.extensions['lexicon_store'].close)
        response = restarted.test_client().get('/?plaintext=1')
        self.assertEqual(Page(response).payload['rows'][1]['backgrounds']['content_1'], '#ABCDEF')
        self.assertIn('background-color: #ABCDEF', response.get_data(as_text=True))

    def test_uncolored_empty_cell_keeps_neutral_background_after_edit(self):
        payload = self.payload()
        self.assertEqual(self.save(payload, [{'insert': 'new\n'}], field='content_2').status_code, 200)
        self.assertEqual(self.payload()['rows'][0]['backgrounds']['content_2'], 'var(--label-background)')

    def test_stale_edits_conflict_and_different_cells_do_not(self):
        first = self.payload()
        other = self.app.test_client()
        second = self.payload(other)
        self.assertEqual(self.save(first, [{'insert': 'first\n'}]).status_code, 200)
        conflict = self.save(second, [{'insert': 'second\n'}], client=other)
        self.assertEqual(conflict.status_code, 409)
        self.assertIn('Someone else', conflict.json['error'])
        self.assertEqual(self.save(second, [{'insert': 'independent\n'}], client=other, field='content_1').status_code, 200)
        self.assertIn('first', self.editor(self.payload())['html'])

    def test_whole_cell_spacing_survives_reload_plaintext_and_later_edits(self):
        payload = self.payload()
        self.assertEqual(self.save(payload, [{'insert': 'café\nline two\n'}], line_height=2).status_code, 200)
        updated = self.payload()
        self.assertEqual(self.editor(updated)['line_height'], 2)
        self.assertIn('line-height: 2', self.editor(updated)['html'])
        self.assertIsNone(self.editor(updated, field='content_1')['line_height'])
        self.assertEqual(self.app.extensions['lexicon_store'].to_dataframe().attrs['cell_line_heights'][
            (1, 'ETIMON/ CORESPONDENTE ROMANICE', 1, 'LIMBA FRANCEZĂ')
        ], 2)
        response = self.client.get('/?plaintext=1')
        plain = Page(response).payload
        self.assertEqual(plain['rows'][0]['content_0'], 'café\nline two')
        self.assertEqual(self.editor(plain)['line_height'], 2)
        self.assertIn('line-height: 2.0;', response.get_data(as_text=True))
        self.assertEqual(self.save(plain, [{'insert': 'another edit\n'}]).status_code, 200)
        self.assertEqual(self.editor(self.payload())['line_height'], 2)
        self.assertEqual(sha256(self.path.read_bytes()).digest(), self.original)

    def test_spacing_on_empty_cells_and_invalid_spacing(self):
        payload = self.payload()
        for height in ('2', '2; position:fixed', True, {}, [], float('nan'), float('inf'), 10**400, 0, 4.1):
            with self.subTest(height=height):
                self.assertEqual(self.save(payload, [{'insert': 'café\n'}], line_height=height).status_code, 400)
        self.assertEqual(self.editor(self.payload()), self.editor(payload))
        self.assertEqual(self.save(payload, [{'insert': '\n'}], row=1, field='content_1', line_height=1.5).status_code, 200)
        empty = self.payload()
        self.assertEqual(empty['rows'][1]['content_1'], '')
        self.assertEqual(self.editor(empty, row=1, field='content_1')['line_height'], 1.5)

    def test_filling_a_missing_standard_language_updates_available_filters(self):
        payload = self.payload()
        self.assertEqual(self.save(payload, [{'insert': 'italiano\n'}], field='content_2').status_code, 200)
        self.client.post('/mode', json={'edit_mode': False}, headers={'X-CSRF-Token': payload['csrf']})
        response = self.client.get('/', query_string={
            'search': '1', 'q': 'italiano', 'column': 'LIMBA ITALIANĂ',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Page(response).matches, [1])

    def test_simultaneous_saves_cannot_overwrite_each_other(self):
        clients = [self.app.test_client(), self.app.test_client()]
        payloads = [self.payload(client) for client in clients]
        def save(index):
            return self.save(payloads[index], [{'insert': f'writer {index}\n'}], client=clients[index]).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(save, [0, 1]))
        self.assertEqual(sorted(statuses), [200, 409])

    def test_csrf_and_signed_cell_identity_are_required(self):
        payload = self.payload()
        body = {'token': self.editor(payload)['token'], 'ops': [{'insert': 'bad\n'}]}
        self.assertEqual(self.client.post('/cell', json=body).status_code, 403)
        self.assertEqual(self.app.test_client().post('/cell', json=body, headers={'X-CSRF-Token': payload['csrf']}).status_code, 403)
        self.assertEqual(self.save(payload, body['ops'], token='forged').status_code, 409)
        self.assertIn('café', self.editor(self.payload())['html'])

    def test_restart_expires_edit_tokens_even_with_stable_secret_key(self):
        old = self.payload()
        restarted = create_app(self.path, test_config={'DEFAULT_UI_LANGUAGE':'en', 'TESTING': True, 'SECRET_KEY': 'edit-test-key'})
        client = restarted.test_client()
        fresh = self.payload(client)
        self.assertEqual(self.save(fresh, [{'insert': 'stale\n'}], client=client,
                                   token=self.editor(old)['token']).status_code, 409)

    def test_invalid_and_oversized_documents_do_not_modify_data(self):
        payload = self.payload()
        for ops in (None, [], [{'insert': {'image': 'bad'}}], [{'insert': 'x\n', 'attributes': {'font': 'x;position:fixed'}}]):
            with self.subTest(ops=ops):
                self.assertEqual(self.save(payload, ops).status_code, 400)
        self.assertEqual(self.save(payload, [{'insert': 'x' * 70000 + '\n'}]).status_code, 413)
        self.assertIn('café', self.editor(self.payload())['html'])


class DeltaRenderingTests(unittest.TestCase):
    def test_cell_spacing_wraps_all_lines_without_changing_text_or_inline_sizes(self):
        html, text = render_delta([
            {'insert': 'large', 'attributes': {'size': '18pt'}},
            {'insert': '\nsmall', 'attributes': {'size': '11pt'}},
            {'insert': '\n'},
        ], line_height=1.5)
        self.assertTrue(html.startswith('<div style="white-space: pre-wrap; line-height: 1.5">'))
        self.assertEqual(html.count('line-height:'), 1)
        self.assertIn('font-size: 18pt', html)
        self.assertIn('font-size: 11pt', html)
        self.assertEqual(text, 'large\nsmall')

    def test_whitespace_html_escaping_and_inline_formats(self):
        html, text = render_delta([
            {'insert': '  <script> &\t\n', 'attributes': {
                'font': 'Times New Roman', 'size': '11pt', 'color': 'rgb(1, 2, 3)',
                'background': '#ffff00', 'underline': True, 'strike': True,
            }},
            {'insert': 'x', 'attributes': {'script': 'super'}},
            {'insert': ' \n\n'},
        ])
        self.assertEqual(text, '  <script> &\t\nx \n')
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt; &amp;', html)
        for expected in ('Times New Roman', '11pt', 'rgb(1, 2, 3)', 'underline line-through', 'vertical-align: super'):
            self.assertIn(expected, html)

    def test_embeds_markup_and_css_injections_are_rejected(self):
        for op in (
            {'insert': {'image': 'javascript:alert(1)'}},
            {'insert': 'x\n', 'attributes': {'link': 'javascript:alert(1)'}},
            {'insert': 'x\n', 'attributes': {'color': 'red;position:fixed'}},
            {'insert': 'x\n', 'attributes': {'background': 'url(https://example.org)'}},
            {'insert': 'x\n', 'attributes': {'color': 'rgb(999,0,0)'}},
            {'insert': 'x\n', 'attributes': {'size': '10000px'}},
            {'insert': 'x\n', 'attributes': {'bold': 'true'}},
            {'retain': 1}, {'insert': 'no final newline'}, {'insert': '\ud800\n'},
        ):
            with self.subTest(op=op), self.assertRaises(ValueError):
                render_delta([op])


if __name__ == '__main__':
    unittest.main()
