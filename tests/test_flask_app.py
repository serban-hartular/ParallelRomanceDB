"""Request-level checks for the local lexicon browser."""

from html.parser import HTMLParser
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from openpyxl import Workbook
import pandas as pd

from main import create_app
from extract_sheet import excel_to_dataframe


class Page(HTMLParser):
    def __init__(self, response):
        super().__init__()
        self.matches = []
        self.selected = None
        self.query = None
        self.payload = None
        self.filters = {'column': [], 'label': []}
        self.in_payload = False
        self.feed(response.get_data(as_text=True))

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'script' and attrs.get('class') == 'workspace-data':
            self.in_payload = True
        if tag == 'a' and 'etimon-link' in attrs.get('class', '').split():
            self.matches.append(int(attrs['data-etimon-id']))
        if attrs.get('id') == 'etimon-detail' and 'data-etimon-id' in attrs:
            self.selected = int(attrs['data-etimon-id'])
        if attrs.get('id') == 'query':
            self.query = attrs.get('value')
        if tag == 'input' and attrs.get('type') == 'checkbox' and attrs.get('name') in self.filters and 'checked' in attrs:
            self.filters[attrs['name']].append(attrs['value'])

    def handle_data(self, data):
        if self.in_payload:
            self.payload = json.loads(data)

    def handle_endtag(self, tag):
        if tag == 'script':
            self.in_payload = False


class FlaskAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app(test_config={'TESTING': True, 'SECRET_KEY': 'test-session-key'})

    def setUp(self):
        self.client = self.app.test_client()

    def test_initial_list_selection_and_static_asset(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        page = Page(response)
        self.assertEqual(page.matches, [1, 2, 3, 4])
        self.assertEqual(page.selected, 1)
        self.assertEqual(page.filters, {'column': [], 'label': []})
        self.assertEqual(page.payload['criteria'], {'query': '', 'column': [], 'label': []})
        self.assertIn('ASPIC', response.get_data(as_text=True))
        self.assertIn('PROFITEROLE', response.get_data(as_text=True))
        self.assertIn('LIMBA CATALANĂ', response.get_data(as_text=True))
        self.assertIn('<span style=', response.get_data(as_text=True))
        stylesheet = self.client.get('/static/style.css')
        try:
            self.assertEqual(stylesheet.status_code, 200)
        finally:
            stylesheet.close()

        clicked = Page(self.client.get('/?etimon=2'))
        self.assertEqual(clicked.matches, [1, 2, 3, 4])
        self.assertEqual(clicked.selected, 2)
        self.assertEqual(Page(self.client.get('/')).selected, 2)

    def test_search_filters_retained_when_selecting_another_match(self):
        self.client.get('/?etimon=2')
        response = self.client.get('/', query_string={
            'search': '1', 'q': 'sens nepreluat',
            'column': 'LIMBA ROMÂNĂ',
            'label': 'EXTENSII SEMANTICE (METAFORIZĂRI,  METONIMII)',
        })
        page = Page(response)
        self.assertEqual(page.matches, [1, 4])
        self.assertEqual(page.selected, 1)
        clicked = Page(self.client.get('/?etimon=4'))
        self.assertEqual(clicked.matches, [1, 4])
        self.assertEqual(clicked.selected, 4)
        self.assertEqual(clicked.query, 'sens nepreluat')
        with self.client.session_transaction() as state:
            self.assertEqual(state['search']['column'], ['LIMBA ROMÂNĂ'])
            self.assertEqual(state['search']['label'], ['EXTENSII SEMANTICE (METAFORIZĂRI,  METONIMII)'])
        # A selection outside the matches cannot escape the current search.
        outside = Page(self.client.get('/?etimon=2'))
        self.assertEqual(outside.matches, [1, 4])
        self.assertEqual(outside.selected, 1)

    def test_phrase_search_and_browser_isolation(self):
        response = self.client.get('/', query_string={
            'search': '1', 'q': 'PRĂJITURĂ CU CREMĂ',
            'column': 'LIMBA ROMÂNĂ', 'label': 'SENSURI DE BAZĂ',
        })
        self.assertEqual(Page(response).matches, [2])
        self.assertEqual(Page(response).selected, 2)
        other_browser = self.app.test_client()
        self.assertEqual(Page(other_browser.get('/')).matches, [1, 2, 3, 4])
        self.assertEqual(Page(self.client.get('/')).matches, [2])

    def test_unaccented_search_retains_accents_in_display(self):
        response = self.client.get('/', headers={'HX-Request': 'true'}, query_string={
            'search': '1', 'q': 'PRAJITURA CU CREMA',
            'column': 'LIMBA ROMÂNĂ', 'label': 'SENSURI DE BAZĂ',
        })
        page = Page(response)
        self.assertEqual(page.matches, [2])
        self.assertEqual(page.selected, 2)
        self.assertEqual(page.payload['criteria']['query'], 'PRAJITURA CU CREMA')
        plaintext = Page(self.client.get('/?plaintext=1', headers={'HX-Request': 'true'})).payload
        self.assertTrue(any(
            'Prăjitură cu cremă' in str(value)
            for row in plaintext['rows'] for value in row.values()
        ))

    def test_no_matches_and_clear(self):
        response = self.client.get('/', query_string={'search': '1', 'q': '__no_such_word__'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Page(response).matches, [])
        self.assertIsNone(Page(response).selected)
        self.assertIn('No etimons match this search.', response.get_data(as_text=True))
        self.assertIsNone(Page(self.client.get('/?etimon=2')).selected)
        reset = Page(self.client.get('/?reset=1'))
        self.assertEqual(reset.matches, [1, 2, 3, 4])
        self.assertEqual(reset.selected, 1)
        self.assertEqual(reset.query, '')

    def test_search_highlights_formatted_plaintext_and_clear_without_mutation(self):
        original = self.app.extensions['lexicon_df'].copy(deep=True)
        for headers in ({}, {'HX-Request': 'true'}):
            with self.subTest(headers=headers):
                client = self.app.test_client()
                response = client.get('/', headers=headers, query_string={
                    'search': '1', 'q': 'PRAJITURA CU CREMA',
                    'column': 'LIMBA ROMÂNĂ', 'label': 'SENSURI DE BAZĂ',
                })
                for response in (response, client.get('/?plaintext=1', headers=headers)):
                    payload = Page(response).payload
                    field = next(column['field'] for column in payload['columns'] if column['title'] == 'LIMBA ROMÂNĂ')
                    row = next(row for row in payload['rows'] if row['label'] == 'SENSURI DE BAZĂ' and row['label_number'] == 2)
                    mark = '<mark class="search-highlight">Prăjitură cu cremă</mark>'
                    self.assertIn(mark, row['highlights'][field])
                    self.assertNotIn('<mark', row[field])
                    self.assertIn(mark, response.get_data(as_text=True))
                reset = client.get('/?reset=1', headers=headers)
                self.assertTrue(all(not row['highlights'] for row in Page(reset).payload['rows']))
                self.assertNotIn('<mark', reset.get_data(as_text=True))
        pd.testing.assert_frame_equal(self.app.extensions['lexicon_df'], original)

    def test_search_highlight_color_configuration(self):
        self.assertIn('--search-highlight-color: #ffff00;', self.client.get('/').get_data(as_text=True))
        app = create_app(test_config={
            'TESTING': True, 'SECRET_KEY': 'test', 'SEARCH_HIGHLIGHT_COLOR': '#ff88cc',
        })
        for headers in ({}, {'HX-Request': 'true'}):
            html = app.test_client().get('/?search=1&q=crema', headers=headers).get_data(as_text=True)
            self.assertIn('--search-highlight-color: #ff88cc;', html)
        with self.assertRaisesRegex(ValueError, 'SEARCH_HIGHLIGHT_COLOR'):
            create_app(test_config={'SEARCH_HIGHLIGHT_COLOR': '#fff; color: red'})

    def test_plaintext_mode_preserves_search_and_selection(self):
        self.client.get('/', query_string={
            'search': '1', 'q': 'Prăjitură cu cremă', 'column': 'LIMBA ROMÂNĂ',
        })
        response = self.client.get('/?etimon=2&plaintext=1')
        self.assertEqual(Page(response).matches, [2])
        self.assertEqual(Page(response).selected, 2)
        html = response.get_data(as_text=True)
        self.assertIn('class="plain-content"', html)
        self.assertNotIn('<span style=', html)
        self.assertIn('Prăjitură cu cremă', html)
        self.assertNotIn('<span style=', self.client.get('/').get_data(as_text=True))
        formatted = self.client.get('/?plaintext=0')
        self.assertIn('<span style=', formatted.get_data(as_text=True))
        self.assertEqual(Page(formatted).selected, 2)

    def test_workbook_loaded_once_per_app(self):
        with patch('main.excel_to_dataframe', wraps=excel_to_dataframe) as loader:
            app = create_app(test_config={'TESTING': True, 'SECRET_KEY': 'test'})
            client = app.test_client()
            client.get('/')
            client.get('/?etimon=2')
            client.get('/?search=1&q=cremă')
            client.get('/?plaintext=1')
            loader.assert_called_once()

    def test_htmx_search_and_selection_return_only_the_workspace(self):
        headers = {'HX-Request': 'true'}
        response = self.client.get('/', headers=headers, query_string={
            'search': '1', 'q': 'sens nepreluat', 'column': 'LIMBA ROMÂNĂ',
            'label': 'EXTENSII SEMANTICE (METAFORIZĂRI,  METONIMII)',
        })
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('<!doctype', html)
        self.assertNotIn('class="site-header"', html)
        self.assertNotIn('class="search-form"', html)
        self.assertIn('id="workspace"', html)
        self.assertIn('HX-Request', response.headers['Vary'])
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(Page(response).matches, [1, 4])
        self.assertEqual(Page(response).selected, 1)

        clicked = self.client.get('/?etimon=4', headers=headers)
        page = Page(clicked)
        self.assertEqual(page.matches, [1, 4])
        self.assertEqual(page.selected, 4)
        self.assertEqual(page.payload['etimon'], 4)
        self.assertEqual(page.payload['criteria']['query'], 'sens nepreluat')
        self.assertEqual(page.payload['criteria']['column'], ['LIMBA ROMÂNĂ'])
        self.assertIn('BISCUIT', page.payload['title'])
        self.assertIn('hx-preserve="true"', clicked.get_data(as_text=True))
        # The workbook's private filesystem path is not a browser preference key.
        self.assertEqual(len(page.payload['dataset']), 16)

    def test_grid_payload_matches_formatted_and_plaintext_cells(self):
        formatted = Page(self.client.get('/?etimon=2', headers={'HX-Request': 'true'})).payload
        plain = Page(self.client.get('/?etimon=2&plaintext=1', headers={'HX-Request': 'true'})).payload
        self.assertEqual(formatted['dataset'], plain['dataset'])
        self.assertFalse(formatted['plaintext'])
        self.assertTrue(plain['plaintext'])
        self.assertEqual(formatted['columns'], plain['columns'])
        self.assertEqual(len({row['id'] for row in plain['rows']}), len(plain['rows']))
        romanian = next(column['field'] for column in plain['columns'] if column['title'] == 'LIMBA ROMÂNĂ')
        example = next(row for row in plain['rows'] if row['label'] == 'SENSURI DE BAZĂ' and row['label_number'] == 2)
        self.assertEqual(example[romanian], 'Prăjitură cu cremă, cu înghețată și cu frișcă (DEX, DCR3)')
        rich_example = next(row for row in formatted['rows'] if row['id'] == example['id'])
        self.assertIn('<div style=', rich_example[romanian])
        # Missing entries stay empty, rather than becoming the text "NaN".
        self.assertTrue(any(value == '' for row in plain['rows'] for value in row.values()))

    def test_htmx_empty_results_reset_and_local_assets(self):
        headers = {'HX-Request': 'true'}
        empty = Page(self.client.get('/?search=1&q=__missing__', headers=headers))
        self.assertEqual(empty.matches, [])
        self.assertIsNone(empty.selected)
        self.assertIsNone(empty.payload['etimon'])
        self.assertEqual(empty.payload['rows'], [])
        reset = Page(self.client.get('/?reset=1', headers=headers))
        self.assertEqual(reset.matches, [1, 2, 3, 4])
        self.assertEqual(reset.payload['criteria'], {'query': '', 'column': [], 'label': []})
        for name in ('app.js', 'scrollbars.js', 'vendor/htmx.min.js', 'vendor/tabulator.min.js', 'vendor/tabulator.min.css'):
            asset = self.client.get(f'/static/{name}')
            try:
                self.assertEqual(asset.status_code, 200)
                self.assertGreater(len(asset.get_data()), 100)
            finally:
                asset.close()

    def test_language_fallback_and_escaped_workbook_text(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / 'fallback.xlsx'
            workbook = Workbook()
            sheet = workbook.active
            sheet.append([None, 'LIMBA FRANCEZĂ', 'LIMBA ROMÂNĂ', 'LIMBA ITALIANĂ'])
            sheet.append(['ETIMON/ CORESPONDENTE ROMANICE', None, 'CUVÂNT, subst. neutru', 'PAROLA'])
            sheet.append(['SENSURI DE BAZĂ', None, '<script>alert("text")</script>'])
            sheet.append(['ETIMON/ CORESPONDENTE ROMANICE', None, None, 'PAROLA, sostantivo'])
            workbook.save(source)
            workbook.close()
            app = create_app(source, test_config={'TESTING': True, 'SECRET_KEY': 'test'})
            client = app.test_client()
            html = client.get('/').get_data(as_text=True)
            self.assertIn('<strong>CUVÂNT</strong>', html)
            self.assertIn('<strong>PAROLA</strong>', html)
            self.assertNotIn('<script>', html)
            self.assertIn('&lt;script&gt;', html)
            plain = client.get('/?plaintext=1').get_data(as_text=True)
            self.assertNotIn('<script>', plain)
            self.assertIn('&lt;script&gt;', plain)
            query = client.get('/', query_string={'search': '1', 'q': '"><script>alert(1)</script>'})
            self.assertNotIn('<script>', query.get_data(as_text=True))

    def test_multiple_filters_survive_navigation_reload_and_clear(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / 'filters.xlsx'
            workbook = Workbook()
            sheet = workbook.active
            sheet.append([None, 'French', 'Romanian', 'Italian'])
            for number, label, cells in [
                (1, 'Basic', ['café', None, None]),
                (2, 'Special', [None, 'CAFÉ', None]),
                (3, 'Basic', [None, None, 'café']),
                (4, 'Other', ['café', None, None]),
                (5, 'Special', ['café', None, None]),
            ]:
                sheet.append(['ETIMON/ CORESPONDENTE ROMANICE', f'entry {number}'])
                sheet.append([label, *cells])
                if number == 3:
                    sheet.append(['Special', 'different text'])
                if number == 4:
                    sheet.append(['Basic', 'different text'])
            workbook.save(source)
            workbook.close()
            client = create_app(source, test_config={
                'TESTING': True, 'SECRET_KEY': 'test',
            }).test_client()
            response = client.get('/', headers={'HX-Request': 'true'}, query_string=[
                ('search', '1'), ('q', 'CAFE'),
                ('column', 'Romanian'), ('column', 'French'), ('column', 'French'),
                ('label', 'Special'), ('label', 'Basic'),
            ])
            criteria = {'query': 'CAFE', 'column': ['French', 'Romanian'], 'label': ['Basic', 'Special']}
            page = Page(response)
            self.assertEqual(page.matches, [1, 2, 5])
            self.assertEqual(page.payload['criteria'], criteria)
            for url in ('/?etimon=5', '/?plaintext=1', '/'):
                page = Page(client.get(url))
                self.assertEqual(page.matches, [1, 2, 5])
                self.assertEqual(page.selected, 5)
                self.assertEqual(page.payload['criteria'], criteria)
                self.assertEqual(page.filters, {'column': ['French', 'Romanian'], 'label': ['Basic', 'Special']})
            for url in ('/?reset=1', '/?search=1&q=&column=&label='):
                page = Page(client.get(url))
                self.assertEqual(page.matches, [1, 2, 3, 4, 5])
                self.assertEqual(page.filters, {'column': [], 'label': []})
                self.assertEqual(page.payload['criteria'], {'query': '', 'column': [], 'label': []})

    def test_older_single_value_search_sessions_are_restored(self):
        with self.client.session_transaction() as state:
            state['search'] = {'query': 'prajitura cu crema', 'column': 'LIMBA ROMÂNĂ', 'label': 'SENSURI DE BAZĂ'}
        page = Page(self.client.get('/'))
        self.assertEqual(page.matches, [2])
        self.assertEqual(page.filters, {'column': ['LIMBA ROMÂNĂ'], 'label': ['SENSURI DE BAZĂ']})
        with self.client.session_transaction() as state:
            self.assertEqual(state['search']['column'], ['LIMBA ROMÂNĂ'])

    def test_empty_workbook(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / 'empty.xlsx'
            workbook = Workbook()
            workbook.save(source)
            workbook.close()
            app = create_app(source, test_config={'TESTING': True, 'SECRET_KEY': 'test'})
            response = app.test_client().get('/')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(Page(response).matches, [])
            self.assertIsNone(Page(response).selected)


if __name__ == '__main__':
    unittest.main()
