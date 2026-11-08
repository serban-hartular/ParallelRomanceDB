"""Atomic cell leases, shared activity/history records, and deletion protection."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest
from unittest.mock import patch

from df_search import LABEL_ORDER
from excel_export import workbook_bytes
from lexicon_db import EditBusy, EditConflict, LexiconDB
from main import create_app
from tests.auth_helpers import authenticate
from tests.test_flask_app import Page


ANA = {'name':'Ana','session_id':'ana-session'}
BOB = {'name':'Bob','session_id':'bob-session'}


class CellLeaseTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.path = self.root/'collection.sqlite3'
        self.store = LexiconDB(self.path,create_empty=True)
        self.addCleanup(self.store.close)
        self.store.add_etymon('headword')
        self.store.add_row(1,LABEL_ORDER[1],'sense')
        self.store.add_row(1,LABEL_ORDER[1],'second sense')
        self.store.add_etymon('other')
        self.key = (1,LABEL_ORDER[0],1,'LIMBA FRANCEZĂ')
        self.origin = datetime(2026,11,7,12,0,tzinfo=timezone.utc)

    def start(self, key=None, actor=ANA, store=None):
        store = store or self.store
        key = key or self.key
        cell = store.cell(key)
        return store.begin_cell_edit(key,cell['revision'],cell['generation'],actor)

    def save(self, opened, text='saved', key=None, actor=ANA):
        key = key or self.key
        cell = self.store.cell(key)
        return self.store.save_cell(key,cell['revision'],[{'insert':text+'\n'}],
                                   generation=cell['generation'],actor=actor,lease=opened['lease'])

    def events(self):
        return sorted(self.store.edit_history(include_sessions=True),key=lambda event:event['id'],reverse=True)

    def test_change_history_is_ordered_by_completion_not_editor_opening_order(self):
        other_key = (1,LABEL_ORDER[1],1,'LIMBA FRANCEZĂ')
        with patch('lexicon_db.edit_now',return_value=self.origin):
            first = self.start()
        with patch('lexicon_db.edit_now',return_value=self.origin+timedelta(seconds=1)):
            second = self.start(other_key,BOB)
        with patch('lexicon_db.edit_now',return_value=self.origin+timedelta(seconds=2)):
            self.save(second,key=other_key,actor=BOB)
        with patch('lexicon_db.edit_now',return_value=self.origin+timedelta(seconds=3)):
            self.save(first)
        saves = [event for event in self.store.edit_history() if event['action']=='save_cell']
        self.assertEqual([event['id'] for event in saves],[first['edit_id'],second['edit_id']])

    def test_cell_is_exclusive_even_for_another_tab_with_the_same_login(self):
        opened = self.start()
        for actor in (ANA,BOB,dict(BOB,name='Ana')):
            with self.assertRaisesRegex(EditBusy,'Ana is editing this cell'):
                self.start(actor=actor)
        self.assertNotIn(opened['lease'],json.dumps(self.events()))
        with self.assertRaises(sqlite3.IntegrityError):
            original = self.store.connection.execute("SELECT * FROM edit_history WHERE status='active'").fetchone()
            self.store.connection.execute("""INSERT INTO edit_history
                (action,editor_name,occurred_at,etimon_number,row_id,column_id,status)
                VALUES ('save_cell','Bypass','now',1,?,?,'active')""",(original['row_id'],original['column_id']))

    def test_notices_distinguish_same_row_and_other_rows_and_exclude_other_etymons(self):
        first = self.start()
        same_row = self.start((*self.key[:3],'LIMBA ROMÂNĂ'),BOB)
        self.assertEqual(same_row['warnings'][0]['name'],'Ana')
        self.assertTrue(same_row['warnings'][0]['same_row'])
        self.assertNotIn('lease',same_row['warnings'][0])
        other_row = self.start((1,LABEL_ORDER[1],1,'LIMBA FRANCEZĂ'),BOB)
        self.assertEqual({x['name'] for x in other_row['warnings']},{'Ana','Bob'})
        self.assertFalse(any(x['same_row'] for x in other_row['warnings']))
        other_etymon = self.start((2,LABEL_ORDER[0],1,'LIMBA FRANCEZĂ'),BOB)
        self.assertEqual(other_etymon['warnings'],[])
        renewed = self.store.heartbeat_cell_edit(first['lease'],ANA)
        self.assertEqual(len(renewed['warnings']),2)

    def test_row_and_etymon_deletion_are_blocked_for_every_editor(self):
        key = (1,LABEL_ORDER[1],1,'LIMBA FRANCEZĂ')
        opened = self.start(key)
        for actor in (None,ANA,BOB):
            with self.assertRaisesRegex(EditBusy,'Ana.*row'):
                self.store.delete_row(*key[:3],actor=actor)
            with self.assertRaisesRegex(EditBusy,'Ana.*etymon'):
                self.store.delete_etymon(1,actor=actor)
        self.store.delete_row(1,LABEL_ORDER[1],2)
        self.store.delete_etymon(2)
        self.store.finish_cell_edit(opened['lease'],ANA,'cancelled')
        self.store.delete_row(*key[:3])
        self.assertEqual(next(event for event in self.events() if event['id']==opened['edit_id'])['status'],'cancelled')

    def test_successful_save_completes_the_original_activity_record(self):
        initial = self.store.cell(self.key)
        before_count = len(self.events())
        opened = self.start()
        active = self.events()[0]
        self.assertEqual(active['status'],'active')
        self.assertEqual(active['id'],opened['edit_id'])
        self.assertIsNone(active['finished_at'])
        self.save(opened,'changed é')
        finished = self.events()[0]
        self.assertEqual(len(self.events()),before_count+1)
        self.assertEqual(finished['id'],opened['edit_id'])
        self.assertEqual(finished['status'],'saved')
        self.assertEqual(json.loads(finished['before_json'])['content'],initial['content'])
        self.assertEqual(json.loads(finished['after_json'])['plaintext_content'],'changed é')
        self.assertIsNotNone(finished['started_at'])
        self.assertIsNotNone(finished['finished_at'])
        self.assertEqual(self.store.finish_cell_edit(opened['lease'],ANA,'cancelled')['status'],'saved')
        self.start(actor=BOB)

    def test_empty_cells_are_locked_before_they_have_a_cell_record(self):
        key = (*self.key[:3],'LIMBA ITALIANĂ')
        self.assertIsNone(self.store.cell(key)['id'])
        opened = self.start(key)
        with self.assertRaises(EditBusy):
            self.start(key,BOB)
        self.save(opened,'italiano',key)
        event = self.events()[0]
        self.assertEqual(event['cell_id'],self.store.cell(key)['id'])
        self.assertEqual(event['column_name'],'LIMBA ITALIANĂ')

    def test_cancel_and_unchanged_close_preserve_content_formatting_and_revision(self):
        before = self.store.cell(self.key)
        workbook = workbook_bytes(self.store)
        saved_count = len(self.store.edit_history())
        for outcome in ('cancelled','unchanged'):
            opened = self.start()
            self.assertEqual(self.store.finish_cell_edit(opened['lease'],ANA,outcome)['status'],outcome)
            self.assertEqual(self.store.cell(self.key),before)
            self.assertEqual(workbook_bytes(self.store),workbook)
            self.assertEqual(len(self.store.edit_history()),saved_count)
            self.assertEqual(self.events()[0]['status'],outcome)
            self.assertIsNotNone(self.events()[0]['finished_at'])

    def test_heartbeat_renews_without_a_content_change_or_extra_history(self):
        with patch('lexicon_db.edit_now',return_value=self.origin):
            opened = self.start()
        for seconds in (200,400,600):
            with patch('lexicon_db.edit_now',return_value=self.origin+timedelta(seconds=seconds)):
                renewed = self.store.heartbeat_cell_edit(opened['lease'],ANA)
                self.assertEqual(datetime.fromisoformat(renewed['expires_at']),self.origin+timedelta(seconds=seconds+300))
                with self.assertRaises(EditBusy):
                    self.start(actor=BOB)
        with patch('lexicon_db.edit_now',return_value=self.origin+timedelta(seconds=601)):
            self.assertEqual(self.events()[0]['status'],'active')
            self.assertEqual(self.store.cell(self.key)['plaintext_content'],'headword')

    def test_expiry_frees_the_cell_and_rejects_old_saves_renewals_and_releases(self):
        with patch('lexicon_db.edit_now',return_value=self.origin):
            old = self.start()
        with patch('lexicon_db.edit_now',return_value=self.origin+timedelta(seconds=301)):
            new = self.start(actor=BOB)
            with self.assertRaises(EditConflict):
                self.save(old)
            with self.assertRaises(EditConflict):
                self.store.heartbeat_cell_edit(old['lease'],ANA)
            self.assertEqual(self.store.finish_cell_edit(old['lease'],ANA,'cancelled')['status'],'expired')
            self.assertEqual(self.events()[0]['id'],new['edit_id'])
            self.assertEqual(self.events()[0]['status'],'active')
            expired = self.events()[1]
            self.assertEqual(datetime.fromisoformat(expired['finished_at']),self.origin+timedelta(seconds=300))
            with self.assertRaisesRegex(EditBusy,'Bob'):
                self.store.delete_etymon(1)

    def test_stale_revision_and_deleted_or_restored_rows_cannot_acquire_a_lock(self):
        old = self.store.cell(self.key)
        self.store.save_cell(self.key,old['revision'],[{'insert':'new\n'}])
        with self.assertRaises(EditConflict):
            self.store.begin_cell_edit(self.key,old['revision'],old['generation'],ANA)
        key = (1,LABEL_ORDER[1],1,'LIMBA FRANCEZĂ')
        old = self.store.cell(key)
        trash = self.store.delete_row(*key[:3])
        self.store.restore_trash(trash)
        with self.assertRaises(EditConflict):
            self.store.begin_cell_edit(key,old['revision'],old['generation'],ANA)

    def test_lease_cannot_be_used_for_another_actor_cell_or_collection(self):
        opened = self.start()
        for invalid in (None,{},'bad','\ud800','x'*1000):
            with self.assertRaises(EditConflict):
                self.store.heartbeat_cell_edit(invalid,ANA)
        for operation in (lambda:self.store.heartbeat_cell_edit(opened['lease'],BOB),
                          lambda:self.store.finish_cell_edit(opened['lease'],BOB,'cancelled'),
                          lambda:self.save(opened,actor=BOB),
                          lambda:self.save(opened,key=(2,LABEL_ORDER[0],1,'LIMBA FRANCEZĂ'))):
            with self.assertRaises(EditConflict): operation()
        other = LexiconDB(self.root/'other.sqlite3',create_empty=True)
        self.addCleanup(other.close)
        other.add_etymon('other collection')
        with self.assertRaises(EditConflict):
            other.heartbeat_cell_edit(opened['lease'],ANA)
        with self.assertRaises(ValueError):
            self.store.finish_cell_edit(opened['lease'],ANA,'saved')

    def test_revoked_login_immediately_frees_its_active_locks(self):
        active = {ANA['session_id'],BOB['session_id']}
        self.store.session_validator = lambda identity:identity in active
        self.start()
        active.remove(ANA['session_id'])
        self.start(actor=BOB)
        self.assertEqual(self.events()[1]['status'],'revoked')

    def test_local_writes_cannot_bypass_a_live_editor(self):
        self.start()
        cell = self.store.cell(self.key)
        with self.assertRaisesRegex(EditBusy,'Ana'):
            self.store.save_cell(self.key,cell['revision'],[{'insert':'local overwrite\n'}])
        with self.assertRaises(EditConflict):
            self.store.save_cell((2,LABEL_ORDER[0],1,'LIMBA FRANCEZĂ'),1,[{'insert':'HTTP bypass\n'}],actor=ANA)

    def test_a_failed_save_does_not_complete_the_record_or_release_the_lock(self):
        opened = self.start()
        original = self.store.cell(self.key)
        self.store.connection.execute("""CREATE TRIGGER history_failure BEFORE UPDATE OF status ON edit_history
            WHEN NEW.status='saved' BEGIN SELECT RAISE(ABORT,'history failed'); END""")
        with self.assertRaises(sqlite3.IntegrityError):self.save(opened)
        self.assertEqual(self.store.cell(self.key),original)
        self.assertEqual(self.events()[0]['status'],'active')
        with self.assertRaises(EditBusy):self.start(actor=BOB)
        self.store.connection.execute('DROP TRIGGER history_failure')
        self.save(opened)
        self.assertEqual(self.events()[0]['id'],opened['edit_id'])

    def test_concurrent_connections_can_only_acquire_one_lock(self):
        other = LexiconDB(self.path)
        self.addCleanup(other.close)
        barrier = Barrier(2)
        def acquire(pair):
            store,actor = pair
            barrier.wait()
            try:return self.start(actor=actor,store=store)
            except EditBusy:return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(acquire,[(self.store,ANA),(other,BOB)]))
        self.assertEqual(sum(result is not None for result in results),1)
        self.assertEqual(len([event for event in self.events() if event['status']=='active']),1)

    def test_acquisition_and_deletion_are_atomic_against_each_other(self):
        other = LexiconDB(self.path)
        self.addCleanup(other.close)
        barrier = Barrier(2)
        def acquire():
            barrier.wait()
            try:self.start();return 'opened'
            except EditConflict:return 'deleted'
        def delete():
            barrier.wait()
            try:other.delete_etymon(1);return 'deleted'
            except EditBusy:return 'locked'
        with ThreadPoolExecutor(max_workers=2) as pool:
            first,second = pool.submit(acquire),pool.submit(delete)
            results = (first.result(),second.result())
        self.assertIn(results,[('opened','locked'),('deleted','deleted')])

    def test_schema_five_upgrade_retains_saved_history_and_content(self):
        records = self.store.edit_history()
        original = self.store.cell(self.key)
        self.store.connection.execute('DROP TABLE edit_history')
        self.store.connection.execute('''CREATE TABLE edit_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL,editor_name TEXT NOT NULL,
            editor_session_id TEXT,occurred_at TEXT NOT NULL,etimon_number INTEGER NOT NULL,
            row_id INTEGER REFERENCES row_metadata(id),column_id INTEGER REFERENCES column_definitions(id),
            cell_id INTEGER REFERENCES cells(id),label TEXT,label_number INTEGER,column_name TEXT,
            trash_id INTEGER REFERENCES trash(id),before_json TEXT,after_json TEXT)''')
        for event in reversed(records):
            columns = list(event)[:15]
            self.store.connection.execute('INSERT INTO edit_history ('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+')',[event[key] for key in columns])
        self.store.connection.execute('UPDATE dataset SET schema_version=5')
        reopened = LexiconDB(self.path)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.metadata['schema_version'],7)
        self.assertEqual(reopened.cell(self.key),original)
        migrated = reopened.edit_history()
        self.assertEqual(len(migrated),len(records))
        self.assertTrue(all(event['status']=='saved' and event['finished_at']==event['occurred_at'] for event in migrated))
        self.start(store=reopened)


class CellLeaseHTTPTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name)/'collection.sqlite3'
        store = LexiconDB(path,create_empty=True)
        store.add_etymon('headword')
        store.add_row(1,LABEL_ORDER[1],'sense')
        store.close()
        self.app = create_app(database_path=path,test_config={'DEFAULT_UI_LANGUAGE':'en', 'TESTING':True})
        self.addCleanup(self.app.extensions['access_control'].close)
        self.store = self.app.extensions['lexicon_store']
        self.addCleanup(self.store.close)
        self.client = self.app.test_client()
        self.payload = authenticate(self.client)
        self.headers = {'X-CSRF-Token':self.payload['csrf']}
        self.client.post('/mode',json={'edit_mode':True},headers=self.headers)
        self.payload = Page(self.client.get('/')).payload

    def start(self):
        return self.client.post('/cell/start',json={'token':self.payload['rows'][1]['editors']['content_0']['token']},headers=self.headers)

    def test_start_requires_csrf_authentication_and_edit_mode(self):
        self.assertEqual(self.client.post('/cell/start',json={}).status_code,403)
        other = self.app.test_client()
        page = Page(other.get('/')).payload
        self.assertEqual(other.post('/cell/start',json={},headers={'X-CSRF-Token':page['csrf']}).status_code,401)
        self.client.post('/mode',json={'edit_mode':False},headers=self.headers)
        self.assertEqual(self.start().status_code,403)

    def test_named_busy_responses_protect_cells_rows_and_etymons(self):
        self.assertEqual(self.start().status_code,201)
        blocked = self.start()
        self.assertEqual(blocked.status_code,409)
        self.assertIn('Test editor',blocked.json['error'])
        for token in (self.payload['delete_etymon_token'],self.payload['rows'][1]['delete_token']):
            response = self.client.post('/trash',json={'token':token,'confirmation':'DELETE'},headers=self.headers)
            self.assertEqual(response.status_code,409)
            self.assertIn('Test editor',response.json['error'])

    def test_save_requires_its_lease_and_updates_the_opened_record(self):
        body = {'token':self.payload['rows'][1]['editors']['content_0']['token'],'ops':[{'insert':'saved\n'}]}
        self.assertEqual(self.client.post('/cell',json=body,headers=self.headers).status_code,409)
        opened = self.start().json
        self.assertEqual(opened['heartbeat_ms'],30000)
        self.assertEqual(opened['lease_ms'],300000)
        body['lease'] = opened['lease']
        self.assertEqual(self.client.post('/cell',json=body,headers=self.headers).status_code,200)
        self.assertEqual(self.store.edit_history()[0]['id'],opened['edit_id'])

    def test_heartbeat_and_cancel_work_after_switching_to_search_mode(self):
        opened = self.start().json
        token = self.payload['rows'][1]['editors']['content_0']['token']
        self.client.post('/mode',json={'edit_mode':False},headers=self.headers)
        self.assertEqual(self.client.post('/cell/heartbeat',json={'token':token,'lease':opened['lease']},headers=self.headers).status_code,200)
        response = self.client.post('/cell/finish',json={'lease':opened['lease'],'outcome':'cancelled'},headers=self.headers)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['status'],'cancelled')

    def test_signout_revokes_locks_before_another_person_acquires(self):
        old = self.start().json
        self.client.post('/auth/logout',headers=self.headers)
        payload = authenticate(self.client)
        self.client.post('/mode',json={'edit_mode':True},headers={'X-CSRF-Token':payload['csrf']})
        self.payload = Page(self.client.get('/')).payload
        new = self.start()
        self.assertEqual(new.status_code,201)
        self.assertNotEqual(new.json['edit_id'],old['edit_id'])
        old_event = next(event for event in self.store.edit_history(include_sessions=True) if event['id']==old['edit_id'])
        self.assertEqual(old_event['status'],'revoked')


if __name__ == '__main__':
    unittest.main()
