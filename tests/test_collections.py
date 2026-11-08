"""Collection isolation, persisted definitions, initialization, and local administration."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from openpyxl import Workbook, load_workbook
from openpyxl.styles import PatternFill

from collection_catalog import CollectionCatalog
from df_search import LABEL_ORDER, get_etimon
from excel_export import workbook_bytes
from lexicon_db import LexiconDB
from main import create_app
from manage_collections import main as manage
from tests.auth_helpers import authenticate
from tests.test_flask_app import Page


class CollectionTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.source = self.root/'source.xlsx'
        book = Workbook()
        sheet = book.active
        sheet.title = 'Terms'
        sheet.append(['Label','LIMBA FRANCEZĂ','LIMBA ROMÂNĂ',' Notes '])
        sheet.append([' ETIMON/ CORESPONDENTE ROMANICE ','headword','romanian headword'])
        sheet.append([' SENSURI DE BAZA  ','sense',None,'note'])
        sheet['C3'].fill = PatternFill('solid',fgColor='123456')
        book.create_sheet('Other')['A1'] = 'untouched'
        book.save(self.source)
        book.close()
        self.original = self.source.read_bytes()
        self.catalog_path = self.root/'catalog.sqlite3'
        self.catalog = CollectionCatalog(self.catalog_path)
        self.addCleanup(self.catalog.close)
        self.a = self.catalog.create('Gastronomy',self.source,'Terms')
        self.b = self.catalog.create('Fashion',self.source,'Terms')
        self.store_a = self.catalog.store(self.a['id'])
        self.store_b = self.catalog.store(self.b['id'])
        self.app = create_app(catalog_path=self.catalog_path,test_config={'DEFAULT_UI_LANGUAGE':'en',
            'TESTING':True,'SECRET_KEY':'collections','EXPORT_DIRECTORY':str(self.root/'exports'),
        })
        self.addCleanup(self.app.extensions['collection_catalog'].close)
        self.client = self.app.test_client()

    def url(self, entry):
        return f"/collections/{entry['id']}/"

    def page(self, entry, client=None, **query):
        response = (client or self.client).get(self.url(entry),query_string=query)
        self.assertEqual(response.status_code,200)
        return Page(response).payload

    def editing(self, entry):
        payload = authenticate(self.client,self.page(entry),self.url(entry))
        headers = {'X-CSRF-Token':payload['csrf']}
        self.assertEqual(self.client.post(payload['urls']['mode'],json={'edit_mode':True},headers=headers).status_code,200)
        return self.page(entry),headers

    def test_catalog_uses_permanent_identities_and_separate_files(self):
        self.assertNotEqual(self.a['id'],self.b['id'])
        self.assertNotEqual(self.a['database_path'],self.b['database_path'])
        self.assertEqual(self.store_a.metadata['id'],self.a['id'])
        self.assertEqual(self.store_b.metadata['id'],self.b['id'])
        self.assertEqual(self.store_a.cell((1,' ETIMON/ CORESPONDENTE ROMANICE ',1,'LIMBA FRANCEZĂ'))['id'],
                         self.store_b.cell((1,' ETIMON/ CORESPONDENTE ROMANICE ',1,'LIMBA FRANCEZĂ'))['id'])
        self.assertEqual(self.source.read_bytes(),self.original)
        self.assertEqual(self.client.get('/').location,self.url(self.a))
        self.assertEqual(self.page(self.b)['collection_name'],'Fashion')

    def test_requests_and_tokens_cannot_cross_collection_boundaries(self):
        a,headers = self.editing(self.a)
        b,_ = self.editing(self.b)
        token = a['rows'][0]['editors']['content_0']['token']
        opened = self.client.post(a['urls']['edit_start'],json={'token':token},headers=headers)
        self.assertEqual(opened.status_code,201)
        body = {'token':token,'lease':opened.json['lease'],'ops':[{'insert':'changed\n'}]}
        self.assertEqual(self.client.post(b['urls']['cell'],json=body,headers=headers).status_code,409)
        deletion = {'token':a['delete_etymon_token'],'confirmation':'DELETE'}
        self.assertEqual(self.client.post(b['urls']['trash'],json=deletion,headers=headers).status_code,409)
        self.assertEqual(self.client.post('/cell',json=body,headers=headers).status_code,404)
        self.assertEqual(self.client.post(a['urls']['cell'],json=body,headers=headers).status_code,200)
        self.assertEqual(self.store_a.entries()[1]['form'],'changed')
        self.assertEqual(self.store_b.entries()[1]['form'],'headword')
        self.assertEqual(self.store_b.list_trash(),[])

    def test_collection_urls_are_explicit_for_every_action(self):
        for entry in (self.a,self.b):
            payload = self.page(entry)
            self.assertEqual(set(payload['urls']),{'index','cell','mode','rows','etymons','trash','export','edit_start','edit_heartbeat','edit_finish','changes'})
            self.assertTrue(all(value.startswith(self.url(entry)) for value in payload['urls'].values()))
        self.assertEqual(self.client.get('/collections/not-registered/').status_code,404)
        for path in ('/mode','/rows','/etymons','/trash','/export'):
            response = self.client.get(path) if path=='/export' else self.client.post(path,json={})
            self.assertEqual(response.status_code,404)

    def test_search_mode_selection_and_plaintext_are_collection_and_browser_specific(self):
        self.editing(self.a)
        self.page(self.a,search=1,q='sense',column='LIMBA FRANCEZĂ')
        b = self.page(self.b)
        self.assertFalse(b['edit_mode'])
        self.assertEqual(b['criteria']['query'],'')
        self.page(self.b,plaintext=1,search=1,q='headword')
        a = self.page(self.a)
        self.assertTrue(a['edit_mode'])
        self.assertFalse(a['plaintext'])
        self.assertEqual(a['criteria'],{'query':'sense','label':[],'column':['LIMBA FRANCEZĂ']})
        other = self.page(self.a,client=self.app.test_client())
        self.assertFalse(other['edit_mode'])
        self.assertEqual(other['criteria']['query'],'')
        with self.client.session_transaction() as cookie:
            self.assertIn('browser_id',cookie)
            self.assertNotIn('search',cookie)
        # A fresh app with the same secret retains the server-side preferences.
        second = create_app(catalog_path=self.catalog_path,test_config={'DEFAULT_UI_LANGUAGE':'en', 'TESTING':True,'SECRET_KEY':'collections'})
        self.addCleanup(second.extensions['collection_catalog'].close)
        client = second.test_client()
        client.set_cookie('session',self.client.get_cookie('session').value)
        self.assertEqual(Page(client.get(self.url(self.a))).payload['criteria']['query'],'sense')

    def test_definitions_drive_columns_title_order_and_initial_entry(self):
        c = self.store_a.connection
        c.execute("UPDATE column_definitions SET name='Headword' WHERE name='LIMBA FRANCEZĂ'")
        romanian = c.execute("SELECT id FROM column_definitions WHERE name='LIMBA ROMÂNĂ'").fetchone()[0]
        c.execute('UPDATE column_definitions SET display_order=-1,title_priority=-1 WHERE id=?',(romanian,))
        c.execute('UPDATE dataset SET initial_column_id=?',(romanian,))
        self.assertEqual(self.store_a.entries()[1]['form'],'romanian headword')
        self.assertEqual(self.store_a.cell((1,' ETIMON/ CORESPONDENTE ROMANICE ',1,'Headword'))['plaintext_content'],'headword')
        c.execute("INSERT INTO column_definitions(name,display_order) VALUES ('Future language',99)")
        payload = self.page(self.a)
        self.assertEqual(payload['columns'][0]['title'],'LIMBA ROMÂNĂ')
        self.assertIn('Future language',payload['filters']['column'])
        self.assertIn('Future language',[item['title'] for item in payload['columns']])
        new = self.store_a.add_etymon('new in configured column')
        self.assertEqual(self.store_a.cell((new['etimon'],new['label'],1,'LIMBA ROMÂNĂ'))['plaintext_content'],'new in configured column')
        self.assertIsNone(self.store_a.cell((new['etimon'],new['label'],1,'Headword'))['id'])
        self.assertEqual(self.store_b.initial_column()['name'],'LIMBA FRANCEZĂ')
        self.assertEqual(self.store_b.entries()[1]['form'],'headword')

    def test_column_definition_rename_updates_export_without_changing_cell_ids(self):
        key = (1,' ETIMON/ CORESPONDENTE ROMANICE ',1,'LIMBA FRANCEZĂ')
        previous = self.store_a.cell(key)['id']
        self.store_a.connection.execute("UPDATE column_definitions SET name=' Headword ' WHERE name=?",(key[3],))
        self.assertEqual(self.store_a.cell((*key[:3],' Headword '))['id'],previous)
        book = load_workbook(BytesIO(workbook_bytes(self.store_a)))
        self.addCleanup(book.close)
        self.assertEqual(book['Terms']['B1'].value,' Headword ')
        self.assertEqual(book['Terms']['B2'].value,'headword')
        self.assertEqual(book['Other']['A1'].value,'untouched')
        self.assertEqual(self.source.read_bytes(),self.original)

    def test_row_definitions_drive_creation_colors_order_and_structural_roles(self):
        c = self.store_a.connection
        marker = c.execute('SELECT id FROM row_types WHERE is_etymon=1').fetchone()[0]
        c.execute("UPDATE row_types SET name='ENTRY' WHERE id=?",(marker,))
        c.execute("INSERT INTO row_types(name,display_order,is_etymon,allow_add,default_background) VALUES ('Gloss',-5,0,1,'#112233')")
        c.execute("UPDATE row_types SET allow_add=0 WHERE name=?",(LABEL_ORDER[3],))
        self.assertIn('Gloss',self.store_a.row_labels())
        self.assertNotIn(LABEL_ORDER[3],self.store_a.row_labels())
        created = self.store_a.add_row(1,'Gloss','new gloss')
        frame = get_etimon(self.store_a.to_dataframe(1),1)
        self.assertEqual(frame.iloc[0]['label'],'Gloss')
        self.assertEqual(self.store_a.cell((1,'Gloss',created['label_number'],'LIMBA FRANCEZĂ'))['background_color'],'#112233')
        entry = self.store_a.add_etymon('custom marker')
        self.assertEqual(entry['label'],'ENTRY')
        self.assertEqual(self.store_a.entries()[entry['etimon']]['form'],'custom marker')
        with self.assertRaisesRegex(ValueError,'Delete etymon'):
            self.store_a.delete_row(entry['etimon'],'ENTRY',1)
        self.store_a.delete_etymon(entry['etimon'])
        book = load_workbook(BytesIO(workbook_bytes(self.store_a)))
        self.addCleanup(book.close)
        self.assertFalse(any('custom marker'==str(cell.value) for row in book['Terms'] for cell in row))
        self.assertNotIn('Gloss',self.store_b.row_labels())

    def test_definition_names_and_original_label_variants_survive_reopen(self):
        self.assertEqual(self.store_a.row_labels()[0],' SENSURI DE BAZA  ')
        self.assertEqual(workbook_bytes(self.store_a),self.original)
        c = self.store_a.connection
        c.execute("UPDATE row_types SET name='Basic sense' WHERE name=' SENSURI DE BAZA  '")
        new = self.store_a.add_row(1,'Basic sense','later')
        self.assertEqual(new['label_number'],2)
        frame = get_etimon(self.store_a.to_dataframe(1),1)
        self.assertEqual(list(frame['label']),[' ETIMON/ CORESPONDENTE ROMANICE ',' SENSURI DE BAZA  ','Basic sense'])
        reopened = LexiconDB(self.a['database_path'])
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.row_labels()[0],'Basic sense')
        self.assertEqual(reopened.cell((1,' SENSURI DE BAZA  ',1,'LIMBA FRANCEZĂ'))['plaintext_content'],'sense')

    def test_blank_collection_has_definitions_and_a_working_excel_template(self):
        entry = self.catalog.create('Empty')
        store = self.catalog.store(entry['id'])
        self.assertEqual(store.entries(),{})
        self.assertEqual(len(store.column_definitions()),8)
        self.assertEqual(len(store.row_types()),4)
        book = load_workbook(BytesIO(workbook_bytes(store)))
        self.addCleanup(book.close)
        self.assertEqual(book.active['B1'].value,'LIMBA FRANCEZĂ')
        self.assertEqual(book.active.max_row,1)
        created = store.add_etymon('[To be added]')
        store.add_row(created['etimon'],store.row_labels()[0],'[To be added]')
        self.assertEqual(len(store.to_dataframe()),2)
        self.assertEqual(self.page(entry)['total'],1)
        path = self.root/'blank-export.xlsx'
        path.write_bytes(workbook_bytes(store))
        reimport = LexiconDB(':memory:',path)
        self.addCleanup(reimport.close)
        self.assertEqual(reimport.entries()[1]['form'],'[To be added]')

    def test_trash_recovery_and_export_directories_are_isolated(self):
        a,headers = self.editing(self.a)
        response = self.client.post(a['urls']['trash'],json={'token':a['delete_etymon_token'],'confirmation':'DELETE'},headers=headers)
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.store_a.entries(),{})
        self.assertEqual(len(self.store_b.entries()),1)
        self.assertEqual(self.store_b.list_trash(),[])
        self.assertEqual(self.page(self.a)['total'],0)
        self.assertEqual(self.page(self.b)['total'],1)
        self.store_a.restore_trash(response.json['trash_id'])
        for entry in (self.a,self.b):
            payload = self.page(entry)
            download = self.client.get(payload['urls']['export'])
            self.addCleanup(download.close)
            self.assertEqual(download.status_code,200)
            self.assertEqual(len(list((self.root/'exports'/entry['id']).glob('*.xlsx'))),1)

    def test_simultaneous_writes_to_distinct_collections(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(lambda pair:pair[0].add_etymon(pair[1]),
                                   [(self.store_a,'gastronomy new'),(self.store_b,'fashion new')]))
        self.assertEqual([entry['etimon'] for entry in result],[2,2])
        self.assertEqual(self.store_a.entries()[2]['form'],'gastronomy new')
        self.assertEqual(self.store_b.entries()[2]['form'],'fashion new')

    def test_failed_imports_and_duplicate_registration_leave_no_orphan_files(self):
        before = set((self.root/'collections').iterdir())
        with self.assertRaises(ValueError):
            self.catalog.create('Gastronomy',self.source)
        with self.assertRaises(ValueError):
            self.catalog.create('Bad sheet',self.source,'Missing')
        with self.assertRaises(ValueError):
            self.catalog.register('Copy',self.a['database_path'])
        self.assertEqual(set((self.root/'collections').iterdir()),before)
        self.assertEqual(len(self.catalog.collections()),2)
        self.assertEqual(self.source.read_bytes(),self.original)

    def test_empty_catalog_and_unknown_collection_do_not_open_a_fallback_store(self):
        app = create_app(catalog_path=self.root/'empty/catalog.sqlite3',test_config={'DEFAULT_UI_LANGUAGE':'en', 'TESTING':True})
        self.addCleanup(app.extensions['collection_catalog'].close)
        client = app.test_client()
        self.assertIn('No collections are available',client.get('/').text)
        self.assertEqual(client.get(self.url(self.a)).status_code,404)
        self.assertEqual(client.post('/cell',json={}).status_code,404)
        self.assertEqual(list((self.root/'empty').glob('collections/*.sqlite3')),[])

    def test_local_management_commands_create_import_register_and_list(self):
        path = self.root/'admin/catalog.sqlite3'
        with redirect_stdout(StringIO()):
            self.assertEqual(manage(['--catalog',str(path),'create','Blank']),0)
            self.assertEqual(manage(['--catalog',str(path),'create','Imported','--workbook',str(self.source),'--sheet','Terms']),0)
            self.assertEqual(manage(['--catalog',str(path),'register','Existing',self.a['database_path']]),0)
        listing = StringIO()
        with redirect_stdout(listing):
            self.assertEqual(manage(['--catalog',str(path),'list']),0)
        for name in ('Blank','Imported','Existing'):
            self.assertIn(name,listing.getvalue())
        with redirect_stderr(StringIO()),self.assertRaises(SystemExit):
            manage(['--catalog',str(path),'create','Bad','--workbook',str(self.root/'missing.xlsx')])


if __name__=='__main__':
    unittest.main()
