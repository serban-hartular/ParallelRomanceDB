"""Language selection and translated interfaces, using disposable collections only."""

from html import unescape
import json
from io import BytesIO
from pathlib import Path
import re
from string import Formatter
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from jinja2 import Environment, nodes
from openpyxl import Workbook

from admin import local_time
from cell_editing import validate_line_height
from collection_catalog import CollectionCatalog
from excel_export import workbook_bytes
from i18n import gettext, safe_return
from main import create_app
from tests.test_admin import Inputs
from tests.test_flask_app import Page


def body(response):
    """Ignore embedded translation catalogs when checking actual rendered text."""
    return re.sub(r'<script\b[^>]*>.*?</script>', '', response.text, flags=re.S)


class LocalizationTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory(); self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        book = Workbook(); book.active.title = 'Overview'
        book.active.append(['Label','LIMBA FRANCEZĂ','Search'])
        book.active.append(['ETIMON/ CORESPONDENTE ROMANICE','Cancel','  Name\n\n Text  '])
        book.active.append(['Save','No language form','Search'])
        source = self.root/'History.xlsx'; book.save(source); book.close()
        self.original = source.read_bytes()
        catalog = CollectionCatalog(self.root/'catalog.sqlite3')
        self.entry = catalog.create('Search',source,'Overview')
        self.empty = catalog.create('Cancel')
        catalog.close()
        self.app = create_app(catalog_path=self.root/'catalog.sqlite3', test_config={
            'TESTING':True, 'SECRET_KEY':'disposable-localization-test'})
        self.catalog = self.app.extensions['collection_catalog']; self.addCleanup(self.catalog.close)
        self.access = self.app.extensions['access_control']; self.addCleanup(self.access.close)
        self.access.set_admin_password('temporary administrator password')
        self.access.set_edit_password('temporary editor password')
        self.client = self.app.test_client()
        self.url = f"/collections/{self.entry['id']}/"
        self.store = self.catalog.store(self.entry['id'])

    def admin_login(self):
        csrf = Inputs(self.client.get('/admin/login')).values['csrf_token']
        result = self.client.post('/admin/login',data={'csrf_token':csrf,'name':'Cancel',
            'password':'temporary administrator password'})
        self.assertEqual(result.status_code,303)
        return csrf

    def test_romanian_is_default_and_data_is_not_translated(self):
        before = self.store.to_dataframe().to_dict('records')
        response = self.client.get(self.url,headers={'Accept-Language':'en-US,en;q=0.9'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.headers['Content-Language'],'ro')
        self.assertIn('<html lang="ro">',body(response))
        self.assertIn('Căutați un cuvânt sau o expresie…',body(response))
        self.assertIn('Mod editare',body(response))
        self.assertIn('Descarcă Excel',body(response))
        self.assertIn('Etichetă',body(response))
        self.assertIn('>Cancel</strong>',body(response))
        self.assertIn('  Name\n\n Text  ',unescape(body(response)))
        payload = Page(response).payload
        self.assertEqual(payload['collection_name'],'Search')
        self.assertEqual(payload['source_label'],'History.xlsx · Overview')
        self.assertIn('Search',payload['filters']['column'])
        self.assertIn('Save',payload['filters']['label'])
        self.assertEqual(before,self.store.to_dataframe().to_dict('records'))
        self.assertEqual(workbook_bytes(self.store),self.original)

    def test_switch_persists_across_public_and_admin_pages(self):
        target = self.url+'?search=1&q=Cancel&etimon=1'
        response = self.client.get('/language/en',query_string={'next':target})
        self.assertEqual(response.status_code,303)
        self.assertEqual(response.location,target)
        cookie = response.headers['Set-Cookie']
        for flag in ('ui_language=en','Max-Age=31536000','HttpOnly','SameSite=Lax'):
            self.assertIn(flag,cookie)
        for path in (target,self.url+'export?choose=1','/admin/login'):
            page = self.client.get(path)
            self.assertEqual(page.headers['Content-Language'],'en')
            self.assertIn('<html lang="en">',body(page))
        self.client.get('/language/ro',query_string={'next':self.url})
        self.assertIn('Cine editează?',body(self.client.get(self.url)))
        self.assertEqual(self.app.test_client().get(self.url).headers['Content-Language'],'ro')

    def test_request_language_keeps_existing_tabs_consistent(self):
        self.client.get('/language/en')
        page = self.client.get(self.url,headers={'HX-Request':'true','X-Interface-Language':'ro'})
        self.assertIn('ETIMOANE',body(page))
        self.assertIn('Etichetă',body(page))
        self.assertEqual(page.headers['Content-Language'],'ro')
        self.assertIn('Cookie',page.headers['Vary'])
        self.assertIn('X-Interface-Language',page.headers['Vary'])
        self.assertEqual(self.client.get(self.url).headers['Content-Language'],'en')
        self.assertEqual(self.client.get(self.url,headers={'X-Interface-Language':'xx'}).headers['Content-Language'],'en')
        payload = Page(self.client.get(self.url)).payload
        for locale, text in [('ro','Parolă de editare incorectă.'),('en','Incorrect edit password.')]:
            result = self.client.post('/auth/login',json={'name':'Search','password':'wrong'},
                headers={'X-CSRF-Token':payload['csrf'],'X-Interface-Language':locale})
            self.assertEqual(result.status_code,401)
            self.assertEqual(result.json['error'],text)

    def test_language_redirects_reject_external_and_malformed_targets(self):
        for target in ('https://example.org/','//example.org/','/\\example.org/','/\n//example.org/',
                       'javascript:alert(1)','http://[broken',None):
            self.assertEqual(safe_return(target),'/')
            response = self.client.get('/language/en',query_string={} if target is None else {'next':target})
            self.assertEqual(response.location,'/')
        self.assertEqual(safe_return('/admin/history?editor=Search'),'/admin/history?editor=Search')
        self.assertEqual(self.client.get('/language/xx').status_code,404)
        self.assertIsNone(self.client.get('/language/xx').headers.get('Set-Cookie'))
        self.app.config['SESSION_COOKIE_SECURE'] = True
        self.assertIn('Secure',self.client.get('/language/ro').headers['Set-Cookie'])

    def test_admin_pages_localize_without_changing_form_values(self):
        self.admin_login()
        identifier = self.entry['id']
        paths = {
            '/admin/':'Prezentare generală', '/admin/collections':'Colecții active',
            '/admin/collections/new':'Numele colecției','/admin/collections/import':'Încarcă și alege foaia de calcul',
            '/admin/passwords':'Parolă globală de administrator',
            f'/admin/collections/{identifier}/history':'Include activitatea de editare',
            f'/admin/collections/{identifier}/trash':'În așteptarea recuperării',
            f'/admin/collections/{identifier}/editors':'Nicio celulă',
            f'/admin/collections/{identifier}/delete':'Tastați DELETE pentru a confirma',
        }
        for path,text in paths.items():
            with self.subTest(path=path):
                response=self.client.get(path)
                self.assertEqual(response.status_code,200)
                self.assertIn(text,body(response))
                self.assertIn('<html lang="ro">',body(response))
                self.assertIn('lang="en"',body(response))
                self.assertIn('Cancel',body(response))  # Administrator identity stays literal.
        history = self.client.get(f'/admin/collections/{identifier}/history').text
        self.assertIn('value="saved"',history)
        self.assertIn('>Salvat</option>',history)
        self.assertIn('value="save_cell"',history)
        self.assertIn('>Editare celulă</option>',history)

    def test_admin_errors_upload_sheet_names_and_flash_messages(self):
        csrf = self.admin_login()
        with self.client.session_transaction() as state:csrf=state['admin_csrf']
        result = self.client.post('/admin/collections/new',data={'csrf_token':csrf,'name':'Search'})
        self.assertIn('este deja înregistrată',body(result))
        result = self.client.post('/admin/collections/new',data={'csrf_token':csrf,'name':'New collection'})
        self.assertEqual(result.status_code,303)
        self.assertIn('Colecția a fost creată.',body(self.client.get(result.location)))
        result = self.client.post('/admin/collections/import',data={'csrf_token':csrf,
            'workbook':(BytesIO(self.original),'Cancel.xlsx')})
        review = self.client.get(result.location)
        self.assertIn('value="Overview"',body(review))
        self.assertIn('>Overview</option>',body(review))
        self.assertNotIn('value="Prezentare generală"',body(review))
        result = self.client.post('/admin/collections/import',data={'csrf_token':csrf,
            'workbook':(BytesIO(b'broken zip'),'broken.xlsx')})
        self.assertIn('Acest registru de calcul nu a putut fi citit.',body(result))
        self.assertNotIn('File is not a zip file',body(result))
        invalid = self.client.get(f"/admin/collections/{self.entry['id']}/history?page=-1")
        self.assertIn('numărul paginii',body(invalid))

    def test_domain_validation_and_time_display_follow_request_language(self):
        for locale,message,date in [('ro','Spațierea între rânduri','08.11.2026'),('en','Line spacing','08 Nov 2026')]:
            with self.app.test_request_context(headers={'X-Interface-Language':locale}):
                self.app.preprocess_request()
                with self.assertRaisesRegex(ValueError,message):validate_line_height('bad')
                self.assertIn(date,local_time('2026-11-08T12:00:00+00:00'))
        # Command-line validation remains English and never changes stored attribution.
        with self.assertRaisesRegex(ValueError,'Line spacing'):validate_line_height('bad')
        self.assertEqual(gettext('Cancel'),'Cancel')

    def test_http_and_export_selection_errors_are_localized(self):
        for locale,text in [('ro','Cererea nu a putut fi finalizată'),('en','Request could not complete')]:
            response = self.client.get('/missing-page',headers={'X-Interface-Language':locale})
            self.assertEqual(response.status_code,404)
            self.assertIn(text,body(response))
        response = self.client.get(self.url+'export?selection=1')
        self.assertEqual(response.status_code,400)
        self.assertIn('Alegeți cel puțin o colecție.',body(response))
        self.assertIn('checked',body(self.client.get(self.url+'export?choose=1')))
        invalid = self.client.get(self.url+'?q='+'x'*501)
        self.assertEqual(invalid.status_code,400)
        self.assertIn('Textul de căutat este prea lung.',body(invalid))

    def test_empty_catalog_and_ui_catalog_changes(self):
        empty_app = create_app(catalog_path=self.root/'empty.sqlite3',test_config={'TESTING':True})
        self.addCleanup(empty_app.extensions['collection_catalog'].close)
        self.addCleanup(empty_app.extensions['access_control'].close)
        self.assertIn('Nu există încă nicio colecție',body(empty_app.test_client().get('/')))
        with patch.dict(self.app.extensions['translations']['Search'],{'ro':'Căutare personalizată','en':'Custom search'}):
            response = self.client.get(self.url)
            self.assertIn('Căutare personalizată',body(response))
            self.assertEqual(Page(response).payload['collection_name'],'Search')
            self.assertIn('>Search</option>',body(response))
            self.assertIn('>Cancel</strong>',body(response))


class TranslationCatalogTests(unittest.TestCase):
    def test_catalog_is_complete_and_preserves_substitutions(self):
        root=Path(__file__).resolve().parents[1]
        catalog=json.loads((root/'translations.json').read_text())
        for key,versions in catalog.items():
            with self.subTest(message=key):
                self.assertEqual(set(versions),{'ro','en'})
                fields=lambda text:{name for _,name,_,_ in Formatter().parse(text) if name is not None}
                for text in versions.values():
                    self.assertTrue(text.strip())
                    self.assertEqual(fields(key),fields(text))
        # Every literal template msgid must be in the editable file.
        for path in (root/'templates').rglob('*.html'):
            for call in Environment().parse(path.read_text()).find_all(nodes.Call):
                if isinstance(call.node,nodes.Name) and call.node.name=='_' and isinstance(call.args[0],nodes.Const):
                    self.assertIn(call.args[0].value,catalog,str(path))
