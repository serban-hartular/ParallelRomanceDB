"""Collection lifecycle and untrusted workbook imports, using disposable files."""

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
import re
import sqlite3
from threading import Event
import time
import unittest
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

from openpyxl import Workbook
from openpyxl.styles import Font

from collection_catalog import CollectionCatalog
from excel_export import workbook_bytes
from main import create_app
import tests.test_admin as helpers


class AdminCollectionTests(unittest.TestCase):
    login = helpers.AdminTests.login
    csrf = helpers.AdminTests.csrf
    post = helpers.AdminTests.post
    editor = helpers.AdminTests.editor

    def setUp(self):
        helpers.AdminTests.setUp(self)
        self.catalog = self.app.extensions['collection_catalog']
        self.store = self.catalog.store(self.a['id'])
        self.login()

    def upload(self, content=None, filename='original workbook.xlsx', client=None):
        if content is None:
            book = Workbook()
            book.active.title = 'Unrelated'
            book.active['A1'] = 'keep the other worksheet'
            sheet = book.create_sheet(' Terms ')
            sheet.append(['Label','LIMBA FRANCEZĂ',' Notes '])
            sheet.append([' ETIMON/ CORESPONDENTE ROMANICE ','  café  ','note'])
            sheet['B2'].font = Font(bold=True,color='123456')
            stream = BytesIO()
            book.save(stream)
            book.close()
            content = stream.getvalue()
        response = self.post('/admin/collections/import',{'workbook':(BytesIO(content),filename)},client=client)
        return response, content

    def confirm(self, entry=None, action='delete'):
        entry = entry or self.a
        path = f"/admin/collections/{entry['id']}/{action}"
        response = self.client.get(path)
        self.assertEqual(response.status_code,200,response.text)
        return path, helpers.Inputs(response).values['target']

    def remove(self, entry=None):
        path, token = self.confirm(entry)
        response = self.post(path,{'target':token,'confirmation':'DELETE'})
        self.assertEqual(response.status_code,303,response.text)
        return path, token

    def test_empty_creation_duplicates_and_no_javascript_forms(self):
        response = self.post('/admin/collections/new',{'name':'New empty'})
        self.assertEqual(response.status_code,303)
        entry = self.catalog.collections()[-1]
        store = self.catalog.store(entry['id'])
        self.assertEqual(store.entries(),{})
        self.assertEqual(len(store.row_types()),4)
        self.assertEqual(len(store.column_definitions()),8)
        self.assertEqual(self.client.get(f"/collections/{entry['id']}/").status_code,200)
        before = set((self.root/'collections').iterdir())
        for name in ('New empty',' ','invalid\nname'):
            self.assertEqual(self.post('/admin/collections/new',{'name':name}).status_code,400)
        self.assertEqual(set((self.root/'collections').iterdir()),before)
        for path in ('/admin/collections','/admin/collections/new','/admin/collections/import'):
            response = self.client.get(path)
            if path != '/admin/collections':
                self.assertIn('method="post"',response.text)
            self.assertNotIn('onclick=',response.text)
            self.assertEqual(response.headers['Cache-Control'],'no-store')

    def test_import_selects_exact_sheet_and_retains_original_full_workbook(self):
        response, original = self.upload()
        self.assertEqual(response.status_code,303,response.text)
        review = response.location
        self.assertIn(' Terms ',self.client.get(review).text)
        imported = self.post(review,{'name':'Imported','sheet':' Terms '})
        self.assertEqual(imported.status_code,303,imported.text)
        entry = next(item for item in self.catalog.collections() if item['name']=='Imported')
        store = self.catalog.store(entry['id'])
        self.assertEqual(store.metadata['source_name'],'original workbook.xlsx')
        self.assertEqual(store.metadata['sheet_name'],' Terms ')
        self.assertEqual(workbook_bytes(store),original)
        self.assertIn('  café  ',store.to_dataframe().iloc[0]['content'])
        self.assertEqual(list((self.root/'imports').iterdir()),[])
        self.assertEqual(self.post(review,{'name':'Replay','sheet':' Terms '}).status_code,409)
        self.assertEqual(self.client.get('/imports/'+review.rsplit('/',1)[-1]).status_code,404)

    def test_failed_import_is_retryable_without_orphan_databases(self):
        response,_ = self.upload()
        before = set((self.root/'collections').iterdir())
        for name, sheet in [('Gastronomy',' Terms '),('Import','Missing')]:
            result = self.post(response.location,{'name':name,'sheet':sheet})
            self.assertEqual(result.status_code,400,result.text)
        self.assertEqual(set((self.root/'collections').iterdir()),before)
        self.assertEqual(self.post(response.location,{'name':'Retry','sheet':' Terms '}).status_code,303)
        book = Workbook()
        book.active.append(['Label','French'])
        book.active.append(['SENSURI DE BAZĂ','before marker'])
        stream = BytesIO(); book.save(stream); book.close()
        uploaded,_ = self.upload(stream.getvalue())
        before = set((self.root/'collections').iterdir())
        failed = self.post(uploaded.location,{'name':'Invalid structure','sheet':'Sheet'})
        self.assertEqual(failed.status_code,400)
        self.assertIn('no collection was created',failed.text)
        self.assertEqual(set((self.root/'collections').iterdir()),before)

    def test_imports_bound_to_login_cancel_and_expiry(self):
        response,_ = self.upload()
        token = response.location.rsplit('/',1)[-1]
        other = self.app.test_client(); self.login(other,name='Other administrator')
        self.assertEqual(other.get(response.location).status_code,409)
        self.assertEqual(self.post(response.location+'/cancel',client=other).status_code,409)
        self.assertEqual(self.post(response.location+'/cancel').status_code,303)
        self.assertFalse((self.root/'imports'/token).exists())
        response,_ = self.upload()
        with patch('admin_imports.time.time',return_value=time.time()+1900):
            self.assertEqual(self.client.get(response.location).status_code,409)
        self.assertEqual(list((self.root/'imports').iterdir()),[])

    def test_upload_validation_limits_and_xml_entities(self):
        _, valid = self.upload()
        for content, filename in [(b'bad','file.xls'),(b'bad','file.xlsx')]:
            response,_ = self.upload(content,filename)
            self.assertEqual(response.status_code,400,response.text)
        modified = BytesIO()
        with ZipFile(BytesIO(valid)) as original, ZipFile(modified,'w',ZIP_DEFLATED) as output:
            for item in original.infolist():
                content = original.read(item.filename)
                if item.filename=='xl/workbook.xml':
                    content = b'<!DOCTYPE workbook [<!ENTITY test "bad">]>'+content
                output.writestr(item,content)
        response,_ = self.upload(modified.getvalue())
        self.assertEqual(response.status_code,400)
        self.assertIn('DTD',response.text)
        # The XML declaration guard also covers UTF-16 and XML parts whose
        # extension is not .xml/.rels, before any openpyxl parser runs.
        disguised = BytesIO()
        with ZipFile(BytesIO(valid)) as original, ZipFile(disguised,'w') as output:
            for item in original.infolist():
                output.writestr(item,original.read(item.filename))
            output.writestr('xl/extra.dat','<!DOCTYPE x [<!ENTITY x "bad">]><x/>'.encode('utf-16'))
        self.assertEqual(self.upload(disguised.getvalue())[0].status_code,400)
        oversized = BytesIO()
        with ZipFile(BytesIO(valid)) as original, ZipFile(oversized,'w') as output:
            for item in original.infolist():
                value = original.read(item.filename)
                if item.filename=='xl/worksheets/sheet2.xml':
                    value = value.replace(b'<row r="2"',b'<row r="100001"')
                output.writestr(item,value)
        self.assertEqual(self.upload(oversized.getvalue())[0].status_code,400)
        for setting, limit in [('COLLECTION_UPLOAD_MAX_EXPANDED_BYTES',100),
                               ('COLLECTION_UPLOAD_MAX_MEMBERS',1),('COLLECTION_UPLOAD_MAX_CELLS',1)]:
            with patch.dict(self.app.config,{setting:limit}):
                response,_ = self.upload(valid)
                self.assertEqual(response.status_code,400,response.text)
        with patch.dict(self.app.config,{'COLLECTION_UPLOAD_MAX_BYTES':100}):
            self.assertEqual(self.upload(valid)[0].status_code,400)
        with patch.dict(self.app.config,{'COLLECTION_UPLOAD_MAX_BYTES':100}):
            self.assertEqual(self.upload(b'x'*70000)[0].status_code,413)
        with patch.dict(self.app.config,{'COLLECTION_UPLOAD_MAX_PENDING':1}):
            self.assertEqual(self.upload(valid)[0].status_code,400)
        response,_ = self.upload(valid,filename='macro workbook.xlsm')
        self.assertEqual(response.status_code,303)
        with patch.dict(self.app.config,{'COLLECTION_UPLOAD_MAX_GRID_CELLS':1}):
            self.assertEqual(self.post(response.location,{'name':'Grid limit','sheet':' Terms '}).status_code,400)
        sparse = BytesIO()
        with ZipFile(BytesIO(valid)) as original, ZipFile(sparse,'w') as output:
            for item in original.infolist():
                value = original.read(item.filename)
                if item.filename=='xl/worksheets/sheet2.xml':
                    value = re.sub(rb'<dimension[^>]*/>',b'',value)
                    value = value.replace(b'<row r="2"',b'<row r="10000"').replace(b'r="B2"',b'r="IV10000"')
                output.writestr(item,value)
        uploaded,_ = self.upload(sparse.getvalue())
        self.assertEqual(uploaded.status_code,303,uploaded.text)
        self.assertEqual(self.post(uploaded.location,{'name':'Sparse limit','sheet':' Terms '}).status_code,400)
        # The ordinary small request limit still applies outside uploads.
        self.assertEqual(self.post('/admin/collections/new',{'name':'x'*70000}).status_code,413)

    def test_concurrent_import_submissions_consume_upload_once(self):
        response,_ = self.upload()
        cookie = self.client.get_cookie('session').value
        csrf = self.csrf()
        def submit(name):
            client = self.app.test_client()
            client.set_cookie('session',cookie)
            return client.post(response.location,data={'csrf_token':csrf,'name':name,'sheet':' Terms '}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(submit,['First concurrent import','Second concurrent import']))
        self.assertEqual(sorted(statuses),[303,409])
        self.assertEqual(len(self.catalog.collections()),3)

    def test_single_database_mode_explains_catalog_requirement(self):
        app = create_app(database_path=self.a['database_path'],test_config={'DEFAULT_UI_LANGUAGE':'en',
            'TESTING':True,'SECRET_KEY':'single-admin-collections',
            'AUTH_DATABASE_PATH':str(self.root/'single-access.sqlite3')})
        self.addCleanup(app.extensions['lexicon_store'].close)
        access = app.extensions['access_control']; self.addCleanup(access.close)
        access.set_admin_password(helpers.ADMIN_PASSWORD)
        client = app.test_client(); self.login(client)
        response = client.get('/admin/collections')
        self.assertEqual(response.status_code,200)
        self.assertIn('Collection management requires catalog mode',response.text)
        for path in ('/admin/collections/new','/admin/collections/import',f"/admin/collections/{self.a['id']}/delete"):
            self.assertEqual(client.get(path).status_code,400)
            self.assertEqual(self.post(path,client=client).status_code,400)

    def test_trash_hides_every_route_and_restore_preserves_all_data(self):
        self.store.delete_row(1,self.store.row_labels()[0],1)
        snapshots = {table:[tuple(row) for row in self.store.connection.execute('SELECT * FROM '+table)]
                     for table in ('cells','row_metadata','trash','edit_history','dataset')}
        self.catalog.save_preferences('browser',self.a['id'],{'selection':1})
        path, token = self.remove()
        self.assertTrue(Path(self.a['database_path']).is_file())
        self.assertEqual([entry['id'] for entry in self.catalog.collections()],[self.b['id']])
        self.assertEqual(self.client.get('/').location,f"/collections/{self.b['id']}/")
        for suffix in ('','changes','export'):
            self.assertEqual(self.client.get(f"/collections/{self.a['id']}/{suffix}").status_code,404)
        for suffix in ('cell','cell/start','rows','etymons','trash'):
            self.assertEqual(self.client.post(f"/collections/{self.a['id']}/{suffix}",json={}).status_code,404)
        self.assertEqual(self.client.get(f"/admin/collections/{self.a['id']}/history").status_code,404)
        self.assertEqual(self.post(path,{'target':token,'confirmation':'DELETE'}).status_code,404)
        self.assertIn('Elena',self.client.get('/admin/collections?state=deleted').text)
        self.assertEqual(self.post('/admin/collections/new',{'name':'Gastronomy'}).status_code,400)
        restore, target = self.confirm(action='restore')
        self.assertEqual(self.post(restore,{'target':target}).status_code,303)
        self.assertEqual(self.client.get(f"/collections/{self.a['id']}/").status_code,200)
        for table, rows in snapshots.items():
            self.assertEqual([tuple(row) for row in self.store.connection.execute('SELECT * FROM '+table)],rows)
        self.assertEqual(self.catalog.preferences('browser',self.a['id']),{'selection':1})
        self.assertEqual(self.post(restore,{'target':target}).status_code,409)
        # A confirmation from before removal/restoration cannot remove it again.
        self.assertEqual(self.post(path,{'target':token,'confirmation':'DELETE'}).status_code,409)

    def test_confirmations_require_exact_target_csrf_login_and_fresh_content(self):
        path, token = self.confirm()
        self.assertEqual(self.post(path,{'target':token,'confirmation':'delete'}).status_code,400)
        other_path,_ = self.confirm(self.b)
        self.assertEqual(self.post(other_path,{'target':token,'confirmation':'DELETE'}).status_code,409)
        self.assertEqual(self.client.post(path,data={'target':token,'confirmation':'DELETE'}).status_code,403)
        self.store.add_etymon('new content')
        self.assertEqual(self.post(path,{'target':token,'confirmation':'DELETE'}).status_code,409)
        path, token = self.confirm()
        self.login(name='New identity')
        self.assertEqual(self.post(path,{'target':token,'confirmation':'DELETE'}).status_code,409)

    def test_active_editors_prevent_removal_and_expired_leases_do_not(self):
        payload = self.editor()
        headers = {'X-CSRF-Token':payload['csrf']}
        opened = self.client.post(payload['urls']['edit_start'],json={
            'token':payload['rows'][0]['editors']['content_0']['token']},headers=headers)
        self.assertEqual(opened.status_code,201)
        path, token = self.confirm()
        response = self.post(path,{'target':token,'confirmation':'DELETE'})
        self.assertEqual(response.status_code,409)
        self.assertIn('active cell editors',response.text)
        self.store.connection.execute("UPDATE edit_history SET expires_at='2000-01-01T00:00:00+00:00' WHERE status='active'")
        self.assertEqual(self.post(path,{'target':token,'confirmation':'DELETE'}).status_code,303)

    def test_anonymous_editor_and_revoked_admin_cannot_manage_collections(self):
        client = self.app.test_client()
        self.editor(client)
        for path in ('/admin/collections/new','/admin/collections/import',f"/admin/collections/{self.a['id']}/delete"):
            self.assertEqual(client.get(path).status_code,302)
            self.assertEqual(client.post(path,data={}).status_code,303)
        self.access.set_admin_password('temporary replacement admin password')
        self.assertEqual(self.post('/admin/collections/new',{'name':'Denied'}).status_code,303)
        self.assertEqual(len(self.catalog.collections()),2)

    def test_catalog_migration_persistence_and_atomic_audit(self):
        legacy = self.root/'legacy.sqlite3'
        connection = sqlite3.connect(legacy)
        connection.executescript('''CREATE TABLE catalog_metadata(version INTEGER NOT NULL);
            INSERT INTO catalog_metadata VALUES(1);
            CREATE TABLE collections(id TEXT PRIMARY KEY,name TEXT NOT NULL UNIQUE,
                database_path TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL);
            CREATE TABLE browser_preferences(browser_id TEXT NOT NULL,collection_id TEXT NOT NULL REFERENCES collections(id),
                preferences TEXT NOT NULL,PRIMARY KEY(browser_id,collection_id));''')
        connection.execute('INSERT INTO collections VALUES (?,?,?,?)',tuple(self.a[key] for key in ('id','name','database_path','created_at')))
        connection.execute('INSERT INTO browser_preferences VALUES (?,?,?)',('browser',self.a['id'],'{"selection":1}'))
        connection.commit(); connection.close()
        catalog = CollectionCatalog(legacy); self.addCleanup(catalog.close)
        self.assertEqual(catalog.connection.execute('SELECT version FROM catalog_metadata').fetchone()[0],2)
        self.assertEqual(catalog.preferences('browser',self.a['id']),{'selection':1})
        with patch.object(catalog,'_event',side_effect=sqlite3.OperationalError('audit failure')):
            with self.assertRaises(sqlite3.OperationalError):
                catalog.move_to_trash(self.a['id'],0)
        self.assertIsNone(catalog.get(self.a['id'])['deleted_at'])
        catalog.move_to_trash(self.a['id'],0)
        catalog.close()
        reopened = CollectionCatalog(legacy); self.addCleanup(reopened.close)
        self.assertEqual(reopened.collections(),[])
        self.assertEqual(reopened.collections(deleted=True)[0]['id'],self.a['id'])
        reopened.restore_collection(self.a['id'],1)
        events = reopened.connection.execute('SELECT action,actor_name FROM collection_events ORDER BY id').fetchall()
        self.assertEqual([tuple(row) for row in events],[('delete','Local administrator'),('restore','Local administrator')])

    def test_collection_request_finishes_before_removal(self):
        selected, release, deleting = Event(), Event(), Event()
        path, target = self.confirm()
        # Pause the public request after store selection, while it owns the
        # request lifecycle guard. Removal must wait until it has finished.
        original = self.store.entries
        def delayed_entries(*args,**kwargs):
            selected.set()
            self.assertTrue(release.wait(5))
            return original(*args,**kwargs)
        def public_request():
            return self.app.test_client().get(f"/collections/{self.a['id']}/").status_code
        def delete_request():
            deleting.set()
            return self.post(path,{'target':target,'confirmation':'DELETE'}).status_code
        with patch.object(self.store,'entries',side_effect=delayed_entries),ThreadPoolExecutor(max_workers=2) as pool:
            active = pool.submit(public_request)
            self.assertTrue(selected.wait(5))
            removed = pool.submit(delete_request)
            self.assertTrue(deleting.wait(5))
            self.assertFalse(removed.done())
            release.set()
            self.assertEqual(active.result(timeout=10),200)
            self.assertEqual(removed.result(timeout=10),303)
        self.assertEqual(public_request(),404)

    def test_remove_last_collection_and_missing_database_restore(self):
        self.remove(self.a); self.remove(self.b)
        self.assertIn('No collections are available',self.client.get('/').text)
        self.assertEqual(self.client.get('/admin/').status_code,200)
        path, token = self.confirm(action='restore')
        with patch('collection_catalog.Path.is_file',return_value=False):
            self.assertEqual(self.post(path,{'target':token}).status_code,409)
        self.assertEqual(self.post(path,{'target':token}).status_code,303)


if __name__=='__main__':
    unittest.main()
