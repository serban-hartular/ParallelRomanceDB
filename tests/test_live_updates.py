"""Committed-content markers and stateless, collection-scoped view refreshes."""

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from tempfile import TemporaryDirectory
from threading import Event
import unittest

from collection_catalog import CollectionCatalog
from df_search import LABEL_ORDER
from excel_export import workbook_bytes
from lexicon_db import LexiconDB
from main import create_app
from tests.test_flask_app import Page


class ContentVersionTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name)/'collection.sqlite3'
        self.store = LexiconDB(self.path,create_empty=True)
        self.addCleanup(self.store.close)
        self.store.add_etymon('headword')
        self.store.add_row(1,LABEL_ORDER[1],'sense')
        self.key = (1,LABEL_ORDER[0],1,'LIMBA FRANCEZĂ')
        self.actor = {'name':'Ana','session_id':'test-session'}

    def start(self, key=None):
        key = key or self.key
        cell = self.store.cell(key)
        return self.store.begin_cell_edit(key,cell['revision'],cell['generation'],self.actor)

    def assertChanges(self, operation):
        before = self.store.content_version()
        result = operation()
        self.assertNotEqual(self.store.content_version(),before)
        return result

    def test_counter_survives_reopen_and_is_seen_by_other_connections(self):
        other = LexiconDB(self.path)
        self.addCleanup(other.close)
        before = other.content_version()
        self.assertChanges(lambda:self.store.save_cell(self.key,self.store.cell(self.key)['revision'],[{'insert':'new content\n'}]))
        self.assertNotEqual(other.content_version(),before)
        self.assertEqual(other.content_version(),self.store.content_version())
        reopened = LexiconDB(self.path)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.content_version(),other.content_version())

    def test_target_and_cell_reads_wait_for_another_requests_transaction(self):
        cell = self.store.cell(self.key)
        for reader in (lambda:self.store.cell_key(cell['row_id'],cell['column_id']),
                       lambda:self.store.cell(self.key)):
            started, finished = Event(), Event()
            def read():
                started.set()
                result = reader()
                finished.set()
                return result
            with ThreadPoolExecutor(max_workers=1) as pool:
                with self.store.transaction(write=True):
                    future = pool.submit(read)
                    self.assertTrue(started.wait(2))
                    self.assertFalse(finished.wait(0.05),'A read bypassed another request’s connection lock')
                self.assertIsNotNone(future.result(timeout=2))

    def test_locks_contacts_cancel_unchanged_and_expiry_do_not_change_content_version(self):
        before = self.store.content_version()
        for outcome in ('cancelled','unchanged'):
            opened = self.start()
            self.store.heartbeat_cell_edit(opened['lease'],self.actor)
            self.store.finish_cell_edit(opened['lease'],self.actor,outcome)
        self.start()
        self.store.connection.execute("UPDATE edit_history SET expires_at='2000-01-01' WHERE status='active'")
        self.store.expire_edits()
        self.store.edit_history(include_sessions=True)
        self.assertEqual(self.store.content_version(),before)

    def test_completing_older_open_editor_advances_version_after_a_newer_editor_saved(self):
        other_key = (1,LABEL_ORDER[1],1,'LIMBA FRANCEZĂ')
        first, second = self.start(), self.start(other_key)
        self.store.save_cell(other_key,self.store.cell(other_key)['revision'],[{'insert':'second\n'}],actor=self.actor,lease=second['lease'])
        self.assertChanges(lambda:self.store.save_cell(self.key,self.store.cell(self.key)['revision'],[{'insert':'first\n'}],actor=self.actor,lease=first['lease']))

    def test_additions_deletions_and_local_recovery_advance_counter(self):
        row = self.assertChanges(lambda:self.store.add_row(1,LABEL_ORDER[1],'new row'))
        trash = self.assertChanges(lambda:self.store.delete_row(1,row['label'],row['label_number']))
        self.assertChanges(lambda:self.store.restore_trash(trash))
        etymon = self.assertChanges(lambda:self.store.add_etymon('second'))
        trash = self.assertChanges(lambda:self.store.delete_etymon(etymon['etimon']))
        self.assertChanges(lambda:self.store.restore_trash(trash))

    def test_definition_changes_are_visible_without_application_write_helpers(self):
        self.assertChanges(lambda:self.store.connection.execute("UPDATE column_definitions SET name='French' WHERE id=1"))
        self.assertChanges(lambda:self.store.connection.execute("UPDATE row_types SET default_background='#123456' WHERE is_etymon=1"))
        self.assertChanges(lambda:self.store.connection.execute('UPDATE dataset SET initial_column_id=2'))

    def test_rollback_restores_counter_and_failed_save_does_not_announce_changes(self):
        before = self.store.content_version()
        with self.assertRaisesRegex(ValueError,'rollback'):
            with self.store.transaction(write=True):
                self.store.connection.execute("UPDATE cells SET content='uncommitted'")
                raise ValueError('rollback')
        self.assertEqual(self.store.content_version(),before)
        self.store.connection.execute("""CREATE TRIGGER reject_history BEFORE INSERT ON edit_history
            BEGIN SELECT RAISE(ABORT,'history failure'); END""")
        with self.assertRaisesRegex(Exception,'history failure'):
            self.store.save_cell(self.key,self.store.cell(self.key)['revision'],[{'insert':'rejected\n'}])
        self.assertEqual(self.store.content_version(),before)
        self.assertEqual(self.store.cell(self.key)['plaintext_content'],'headword')

    def test_schema_six_upgrade_retains_content_identity_history_trash_and_export(self):
        trash = self.store.delete_row(1,LABEL_ORDER[1],1)
        before, history = workbook_bytes(self.store), self.store.edit_history()
        identity, cell = self.store.metadata['id'], self.store.cell(self.key)
        triggers = [row[0] for row in self.store.connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'content_%'")]
        for name in triggers:
            self.store.connection.execute(f'DROP TRIGGER {name}')
        self.store.connection.execute('ALTER TABLE dataset DROP COLUMN content_revision')
        self.store.connection.execute('UPDATE dataset SET schema_version=6')
        reopened = LexiconDB(self.path)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.metadata['schema_version'],7)
        self.assertEqual(reopened.metadata['id'],identity)
        self.assertEqual(reopened.cell(self.key),cell)
        self.assertEqual(reopened.list_trash()[0]['id'],trash)
        self.assertEqual(reopened.edit_history(),history)
        self.assertEqual(workbook_bytes(reopened),before)
        marker = reopened.content_version()
        reopened.restore_trash(trash)
        self.assertNotEqual(reopened.content_version(),marker)


class LiveRefreshHTTPTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.catalog_path = Path(directory.name)/'catalog.sqlite3'
        self.catalog = CollectionCatalog(self.catalog_path)
        self.addCleanup(self.catalog.close)
        self.a, self.b = self.catalog.create('Gastronomy'), self.catalog.create('Fashion')
        self.store = self.catalog.store(self.a['id'])
        self.store.add_etymon('first')
        self.store.add_etymon('second')
        self.app = create_app(catalog_path=self.catalog_path,test_config={'DEFAULT_UI_LANGUAGE':'en', 'TESTING':True,'SECRET_KEY':'live-test'})
        self.addCleanup(self.app.extensions['collection_catalog'].close)
        self.client = self.app.test_client()
        self.url = f"/collections/{self.a['id']}/"
        self.page = Page(self.client.get(self.url)).payload

    def test_public_check_is_small_scoped_uncached_and_does_not_write_browser_state(self):
        with self.client.session_transaction() as state:
            before = dict(state)
        preferences = self.catalog.connection.execute('SELECT * FROM browser_preferences').fetchall()
        response = self.client.get(self.page['urls']['changes'])
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json,{'version':self.page['content_version'], 'collection_name':self.page['collection_name']})
        self.assertEqual(response.headers['Cache-Control'],'no-store')
        self.assertNotIn('Set-Cookie',response.headers)
        self.assertEqual(self.page['refresh_ms'],5000)
        with self.client.session_transaction() as state:
            self.assertEqual(dict(state),before)
        self.assertEqual(self.catalog.connection.execute('SELECT * FROM browser_preferences').fetchall(),preferences)
        self.assertEqual(self.client.get('/changes').status_code,404)
        self.assertEqual(self.client.get('/collections/unknown/changes').status_code,404)
        self.assertEqual(self.client.post(self.page['urls']['changes']).status_code,405)

    def test_collection_versions_are_independent(self):
        b_url = f"/collections/{self.b['id']}/changes"
        b_version = self.client.get(b_url).json
        self.store.add_etymon('third')
        self.assertNotEqual(self.client.get(self.page['urls']['changes']).json['version'],self.page['content_version'])
        self.assertEqual(self.client.get(b_url).json,b_version)

    def test_background_view_uses_explicit_tab_state_and_does_not_save_preferences(self):
        # Another same-profile tab selected a different etymon/search.
        self.client.get(self.url,query_string={'search':1,'q':'second','plaintext':1})
        saved = self.catalog.connection.execute('SELECT preferences FROM browser_preferences').fetchall()
        response = self.client.get(self.url,query_string={'live':1,'search':1,'q':'first',
            'etimon':1,'plaintext':0,'editing':1},headers={'HX-Request':'true'})
        view = Page(response).payload
        self.assertEqual(view['etimon'],1)
        self.assertEqual(view['criteria']['query'],'first')
        self.assertFalse(view['plaintext'])
        self.assertFalse(view['edit_mode'])  # A GET cannot grant access.
        self.assertEqual(view['content_version'],self.store.content_version())
        self.assertNotIn('data-reveal-results="true"',response.get_data(as_text=True))
        self.assertEqual(self.catalog.connection.execute('SELECT preferences FROM browser_preferences').fetchall(),saved)
        self.assertEqual(Page(self.client.get(self.url)).payload['etimon'],2)

    def test_deleted_selection_falls_back_and_empty_collection_refreshes(self):
        self.store.delete_etymon(1)
        query = {'live':1,'search':1,'q':'','etimon':1}
        self.assertEqual(Page(self.client.get(self.url,query_string=query)).payload['etimon'],2)
        self.store.delete_etymon(2)
        view = Page(self.client.get(self.url,query_string=query)).payload
        self.assertIsNone(view['etimon'])
        self.assertEqual(view['total'],0)
        self.store.add_etymon('back again')
        view = Page(self.client.get(self.url,query_string=query)).payload
        self.assertEqual(view['etimon'],3)

    def test_refresh_discards_removed_filter_definitions_instead_of_failing(self):
        view = Page(self.client.get(self.url,query_string={'live':1,'search':1,'q':'',
            'column':'Removed column','label':'Removed label'})).payload
        self.assertEqual(view['criteria'],{'query':'','column':[],'label':[], 'diacritics':False, 'regex':False})

    def test_single_collection_changes_route(self):
        app = create_app(database_path=self.a['database_path'],test_config={'DEFAULT_UI_LANGUAGE':'en', 'TESTING':True})
        self.addCleanup(app.extensions['lexicon_store'].close)
        self.addCleanup(app.extensions['access_control'].close)
        client = app.test_client()
        self.assertEqual(client.get('/changes').json['version'],self.store.content_version())

    def test_refresh_interval_requires_a_positive_integer(self):
        for interval in (0,-1,True,0.5,'5'):
            with self.assertRaisesRegex(ValueError,'LIVE_REFRESH_SECONDS'):
                create_app(catalog_path=self.catalog_path,test_config={'DEFAULT_UI_LANGUAGE':'en', 'LIVE_REFRESH_SECONDS':interval})


if __name__ == '__main__':
    unittest.main()
