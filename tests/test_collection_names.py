"""Collection naming, import suggestions, and safe renames on disposable data."""

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import re
from threading import Event
import unittest
from unittest.mock import patch

from openpyxl import Workbook

from collection_catalog import CollectionCatalog
from excel_export import workbook_bytes
from lexicon_db import LexiconDB
from main import create_app
import tests.test_admin as helpers
from tests.test_admin import Inputs
from tests.test_flask_app import Page


class CollectionNameTests(unittest.TestCase):
    login, csrf, post, editor = helpers.AdminTests.login, helpers.AdminTests.csrf, helpers.AdminTests.post, helpers.AdminTests.editor

    def setUp(self):
        helpers.AdminTests.setUp(self)
        self.catalog = self.app.extensions['collection_catalog']
        self.store = self.catalog.store(self.a['id'])
        self.login()
        self.path = f"/admin/collections/{self.a['id']}/rename"

    def form(self, path=None):
        response = self.client.get(path or self.path)
        self.assertEqual(response.status_code,200)
        return Inputs(response).values['target']

    def rename(self, name, *, target=None, path=None):
        return self.post(path or self.path,{'name':name,'target':target or self.form(path)})

    def open_editor(self):
        payload = self.editor()
        headers = {'X-CSRF-Token':payload['csrf']}
        opened = self.client.post(payload['urls']['edit_start'],json={
            'token':payload['rows'][0]['editors']['content_0']['token']},headers=headers)
        self.assertEqual(opened.status_code,201)
        return payload, opened.json['lease'], headers

    def upload(self):
        book = Workbook(); book.active.title = 'Gastronomy'
        for sheet in (book.active, book.create_sheet(' Terms '), book.create_sheet('__proto__')):
            sheet.append(['Label','LIMBA FRANCEZĂ'])
            sheet.append([' ETIMON/ CORESPONDENTE ROMANICE ','  café  '])
        output=BytesIO();book.save(output);book.close()
        response=self.post('/admin/collections/import',{'workbook':(BytesIO(output.getvalue()),'different filename.xlsx')})
        self.assertEqual(response.status_code,303)
        return response.location, output.getvalue()

    def test_import_names_follow_selected_sheet_and_reserve_trash_names(self):
        self.catalog.create('Gastronomy (1)')
        self.catalog.move_to_trash(self.b['id'],0)
        self.assertEqual(self.catalog.suggested_name('Fashion'),'Fashion (1)')
        path,original = self.upload()
        initial = self.client.get(path)
        self.assertEqual(Inputs(initial).values['name'],'Gastronomy (2)')
        # The plain HTML suggestion button changes no collection and consumes no upload.
        count=len(self.catalog.collections())
        preview = self.post(path,{'action':'suggest','sheet':' Terms ','name':''})
        self.assertEqual(preview.status_code,200)
        self.assertEqual(Inputs(preview).values['name'],'Terms')
        self.assertEqual(len(self.catalog.collections()),count)
        imported = self.post(path,{'sheet':' Terms ','name':'Gastronomy (2)','default_name':'Gastronomy (2)','action':'import'})
        self.assertEqual(imported.status_code,303)
        entry = next(entry for entry in self.catalog.collections() if entry['name']=='Terms')
        self.assertEqual(workbook_bytes(self.catalog.store(entry['id'])),original)
        self.assertEqual(self.catalog.store(entry['id']).metadata['sheet_name'],' Terms ')

    def test_import_custom_name_survives_errors_and_suggestions_handle_collisions(self):
        path,_ = self.upload()
        failed = self.post(path,{'sheet':' Terms ','name':'Gastronomy'})
        self.assertEqual(failed.status_code,400)
        self.assertEqual(Inputs(failed).values['name'],'Gastronomy')
        self.assertEqual(Inputs(self.post(path,{'action':'suggest','sheet':'__proto__'})).values['name'],'__proto__')
        self.assertEqual(self.post(path,{'action':'suggest','sheet':'Missing'}).status_code,400)
        self.assertEqual(self.catalog.suggested_name('  Terms  '),'Terms')
        long='a'*120;self.catalog.create(long)
        self.assertEqual(self.catalog.suggested_name(long),'a'*116+' (1)')
        self.assertTrue(self.catalog.suggested_name('  ').strip())

    def test_rename_preserves_identity_contents_template_preferences_and_history(self):
        original=workbook_bytes(self.store); rows=self.store.to_dataframe().to_dict('records')
        history=self.store.edit_history();meta=dict(self.store.metadata)
        self.catalog.save_preferences('test-browser',self.a['id'],{'search':{'query':'café'}})
        result=self.rename('New name')
        self.assertEqual(result.status_code,303,result.text)
        entry=self.catalog.get(self.a['id'])
        self.assertEqual(entry['name'],'New name');self.assertEqual(entry['database_path'],self.a['database_path'])
        self.assertEqual(entry['lifecycle_revision'],1)
        self.assertEqual(workbook_bytes(self.store),original)
        self.assertEqual(rows,self.store.to_dataframe().to_dict('records'))
        self.assertEqual(self.store.edit_history(),history);self.assertEqual(dict(self.store.metadata),meta)
        self.assertEqual(self.catalog.preferences('test-browser',self.a['id']),{'search':{'query':'café'}})
        event=self.catalog.connection.execute("SELECT * FROM collection_events WHERE action='rename'").fetchone()
        self.assertEqual(event['actor_name'],'Elena')
        fresh=CollectionCatalog(self.catalog.path);self.addCleanup(fresh.close)
        self.assertEqual(fresh.get(self.a['id'])['name'],'New name')
        url=f"/collections/{self.a['id']}/"
        page=Page(self.client.get(url)).payload
        self.assertEqual(page['collection_name'],'New name')
        self.assertIn('New name',page['title'])
        self.assertEqual(self.client.get(page['urls']['changes']).json['collection_name'],'New name')
        # Existing bookmarks remain valid, and catalog-only changes notify open tabs.
        self.assertEqual(page['content_version'],self.store.content_version())
        unchanged=self.rename('New name')
        self.assertEqual(unchanged.status_code,303)
        self.assertEqual(self.catalog.get(self.a['id'])['lifecycle_revision'],1)

    def test_names_are_valid_unique_and_trash_names_remain_reserved(self):
        self.catalog.move_to_trash(self.b['id'],0)
        for name in ('Fashion','', ' ', 'bad\nname','x'*121):
            result=self.rename(name)
            self.assertEqual(result.status_code,409,result.text)
            self.assertEqual(self.catalog.get(self.a['id'])['name'],'Gastronomy')
        result=self.rename('  New collection  ')
        self.assertEqual(result.status_code,303)
        self.assertEqual(self.catalog.get(self.a['id'])['name'],'New collection')
        self.assertEqual(self.client.get(f"/admin/collections/{self.b['id']}/rename").status_code,404)

    def test_open_editor_blocks_even_an_earlier_form_until_it_is_closed(self):
        target=self.form()
        payload,lease,headers=self.open_editor()
        preview=self.client.get(self.path)
        self.assertIn('disabled',preview.text)
        denied=self.rename('Blocked',target=target)
        self.assertEqual(denied.status_code,409)
        self.assertIn('being edited',denied.text)
        self.assertEqual(self.catalog.get(self.a['id'])['name'],'Gastronomy')
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM edit_history WHERE status='active'").fetchone()[0],1)
        # An editor in another collection does not block this collection's rename.
        other=f"/admin/collections/{self.b['id']}/rename"
        self.assertEqual(self.rename('Other renamed',path=other).status_code,303)
        self.assertEqual(self.client.post(payload['urls']['edit_finish'],json={'lease':lease,'outcome':'cancelled'},headers=headers).status_code,200)
        # Edit mode alone is allowed: there is no longer an open cell editor.
        self.assertEqual(self.rename('Allowed',target=target).status_code,303)

    def test_expired_leases_do_not_block_rename_and_stale_forms_cannot_overwrite(self):
        target=self.form()
        self.open_editor()
        self.store.connection.execute("UPDATE edit_history SET expires_at='2000-01-01T00:00:00+00:00' WHERE status='active'")
        self.assertEqual(self.rename('After expiry',target=target).status_code,303)
        self.assertEqual(self.rename('Stale name',target=target).status_code,409)
        self.assertEqual(self.catalog.get(self.a['id'])['name'],'After expiry')
        other=CollectionCatalog(self.catalog.path);self.addCleanup(other.close)
        other.rename(self.a['id'],'Other administrator',1)
        with self.assertRaisesRegex(ValueError,'changed'):
            self.catalog.rename(self.a['id'],'Stale administrator',1)

    def test_rename_requires_admin_csrf_and_current_collection_target(self):
        target=self.form()
        anonymous=self.app.test_client()
        self.assertEqual(anonymous.get(self.path).status_code,302)
        self.assertEqual(anonymous.post(self.path,data={'name':'Denied','target':target}).status_code,303)
        self.assertEqual(self.client.post(self.path,data={'name':'Denied','target':target}).status_code,403)
        wrong=f"/admin/collections/{self.b['id']}/rename"
        self.assertEqual(self.rename('Wrong collection',target=target,path=wrong).status_code,409)
        with self.client.session_transaction() as state:state['admin_csrf']='replacement-form-context'
        self.assertEqual(self.rename('Wrong login',target=target).status_code,409)
        self.assertEqual(self.catalog.get(self.a['id'])['name'],'Gastronomy')

    def test_rename_write_transaction_excludes_a_concurrent_cell_lease(self):
        payload=self.editor()
        actor={'name':'Ana','session_id':payload['auth']['identity']}
        key=(1,'ETIMON/ CORESPONDENTE ROMANICE',1,'LIMBA FRANCEZĂ')
        other=LexiconDB(self.a['database_path']);self.addCleanup(other.close)
        cell=other.cell(key)
        entered,release=Event(),Event()
        record=self.catalog._event
        def paused(*args):
            record(*args);entered.set()
            if not release.wait(5):raise RuntimeError('Test rename release timed out')
        with ThreadPoolExecutor(max_workers=2) as pool,patch.object(self.catalog,'_event',side_effect=paused):
            renamed=pool.submit(self.catalog.rename,self.a['id'],'Serialized',0)
            self.assertTrue(entered.wait(5))
            attempt=Event()
            def open_cell():
                attempt.set()
                return other.begin_cell_edit(key,cell['revision'],cell['generation'],actor)
            opening=pool.submit(open_cell)
            self.assertTrue(attempt.wait(5))
            self.assertFalse(opening.done())
            release.set()
            self.assertEqual(renamed.result(timeout=5)['name'],'Serialized')
            self.assertIn('lease',opening.result(timeout=5))

    def test_header_shows_only_prominent_collection_name_in_catalog_and_single_mode(self):
        response=self.client.get(f"/collections/{self.a['id']}/")
        header=re.search(r'<a class="brand".*?</a>',response.text,re.S)[0]
        self.assertIn('>Gastronomy</span>',header)
        self.assertNotIn('.xlsx',header)
        single=create_app(database_path=self.a['database_path'],test_config={'TESTING':True,'DEFAULT_UI_LANGUAGE':'en',
            'AUTH_DATABASE_PATH':str(self.root/'access.sqlite3')})
        self.addCleanup(single.extensions['lexicon_store'].close);self.addCleanup(single.extensions['access_control'].close)
        response=single.test_client().get('/')
        header=re.search(r'<a class="brand".*?</a>',response.text,re.S)[0]
        self.assertIn(self.store.metadata['sheet_name'],header)
        self.assertNotIn('.xlsx',header)
        self.assertEqual(single.test_client().get('/export?choose=1').status_code,200)
        self.assertEqual(self.client.get(self.path,headers={'X-Interface-Language':'ro'}).status_code,200)
