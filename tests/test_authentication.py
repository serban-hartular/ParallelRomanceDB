"""Shared edit authentication, identity binding, atomic history, and local tools."""

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from io import StringIO
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from openpyxl import Workbook

from access_control import AccessControl, LoginDenied
from collection_catalog import CollectionCatalog
from df_search import LABEL_ORDER
from excel_export import workbook_bytes
from history import main as history_command
from lexicon_db import LexiconDB
from main import create_app
from manage_access import main as access_command
from tests.auth_helpers import save_edit
from tests.test_flask_app import Page


PASSWORD = 'shared test password with accents é'


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.catalog = CollectionCatalog(self.root/'catalog.sqlite3')
        self.addCleanup(self.catalog.close)
        self.a = self.catalog.create('Gastronomy')
        self.b = self.catalog.create('Fashion')
        self.app = create_app(catalog_path=self.root/'catalog.sqlite3',test_config={'DEFAULT_UI_LANGUAGE':'en',
            'TESTING':True,'SECRET_KEY':'auth tests','AUTH_DATABASE_PATH':str(self.root/'access.sqlite3'),
        })
        self.access = self.app.extensions['access_control']
        self.addCleanup(self.access.close)
        self.addCleanup(self.app.extensions['collection_catalog'].close)
        self.client = self.app.test_client()
        self.url = f"/collections/{self.a['id']}/"
        self.store = self.catalog.store(self.a['id'])
        self.store.add_etymon('headword')
        self.access.set_edit_password(PASSWORD)

    def page(self, client=None, url=None):
        response = (client or self.client).get(url or self.url)
        self.assertEqual(response.status_code,200)
        return Page(response).payload

    def login(self, name='Ana', client=None, password=PASSWORD):
        client = client or self.client
        payload = self.page(client)
        response = client.post('/auth/login',json={'name':name,'password':password},headers={'X-CSRF-Token':payload['csrf']})
        self.assertEqual(response.status_code,200,response.json)
        return response

    def edit(self, name='Ana', client=None):
        client = client or self.client
        self.login(name,client)
        payload = self.page(client)
        self.assertEqual(client.post(payload['urls']['mode'],json={'edit_mode':True},headers={'X-CSRF-Token':payload['csrf']}).status_code,200)
        return self.page(client)

    def save(self, payload, text='saved', client=None, **extra):
        return save_edit(client or self.client,payload,[{'insert':text+'\n'}],**extra)

    def test_reading_and_export_remain_public_and_all_writes_fail_closed(self):
        payload = self.page()
        self.assertFalse(payload['auth']['authenticated'])
        response = self.client.get(payload['urls']['export'])
        self.addCleanup(response.close)
        self.assertEqual(response.status_code,200)
        headers = {'X-CSRF-Token':payload['csrf']}
        bodies = {'mode':{'edit_mode':True},'cell':{},'rows':{},'etymons':{},'trash':{}}
        for endpoint,body in bodies.items():
            with self.subTest(endpoint=endpoint):
                self.assertEqual(self.client.post(payload['urls'][endpoint],json=body,headers=headers).status_code,401)
        with self.client.session_transaction() as cookie:
            cookie['edit_mode'] = True
            cookie['editor_session'] = 'forged'
        self.assertEqual(self.save(payload).status_code,401)
        self.assertFalse(self.page()['edit_mode'])
        self.assertEqual(self.store.cell((1,LABEL_ORDER[0],1,'LIMBA FRANCEZĂ'))['plaintext_content'],'headword')

    def test_unconfigured_password_never_allows_edits(self):
        self.access.connection.execute('DELETE FROM credentials')
        payload = self.page()
        self.assertFalse(payload['auth']['configured'])
        response = self.client.post('/auth/login',json={'name':'Ana','password':PASSWORD},headers={'X-CSRF-Token':payload['csrf']})
        self.assertEqual(response.status_code,401)
        self.assertIn('administrator',response.json['error'])

    def test_login_validation_csrf_and_failed_password_do_not_authenticate(self):
        payload = self.page()
        self.assertEqual(self.client.post('/auth/login',json={'name':'Ana','password':PASSWORD}).status_code,403)
        for body in ({'name':'Ana','password':'wrong'}, {'name':'  ','password':PASSWORD},
                     {'name':'a\nb','password':PASSWORD}, {'name':'x'*121,'password':PASSWORD},
                     {'name':'Ana','password':'x'*1025}, {'name':'Ana','password':None}):
            response = self.client.post('/auth/login',json=body,headers={'X-CSRF-Token':payload['csrf']})
            self.assertEqual(response.status_code,401)
            self.assertFalse(self.page()['auth']['authenticated'])

    def test_browser_session_cookie_and_global_grant_across_collections(self):
        response = self.login('  Ana Șerban  ')
        cookie = response.headers['Set-Cookie']
        self.assertNotIn('Expires=',cookie)
        self.assertNotIn('Max-Age=',cookie)
        self.assertIn('HttpOnly',cookie)
        self.assertEqual(self.page()['auth']['name'],'Ana Șerban')
        other = self.page(url=f"/collections/{self.b['id']}/")
        self.assertTrue(other['auth']['authenticated'])
        self.assertFalse(self.page(self.app.test_client())['auth']['authenticated'])
        credential = dict(self.access.connection.execute('SELECT * FROM credentials').fetchone())
        self.assertEqual((self.root/'access.sqlite3').stat().st_mode & 0o077,0)
        self.assertNotEqual(credential['password_hash'],PASSWORD)
        self.assertTrue(credential['password_hash'].startswith('scrypt:'))
        with self.client.session_transaction() as session:
            self.assertNotIn('password',session)
            self.assertFalse(session.permanent)
        stored = dict(self.access.connection.execute('SELECT * FROM editor_sessions').fetchone())
        with self.client.session_transaction() as session:
            self.assertNotEqual(stored['id'],session['editor_session'])
        self.assertEqual((credential['role'],credential['scope_type'],credential['scope_id']),('editor','global',''))
        self.assertFalse(AccessControl.can_edit({'role':'admin','scope_type':'global','scope_id':''},self.a['id']))
        self.assertFalse(AccessControl.can_edit({'role':'editor','scope_type':'collection','scope_id':self.a['id']},self.a['id']))

    def test_search_mode_retains_login_but_logout_revokes_old_cookie(self):
        payload = self.edit()
        headers = {'X-CSRF-Token':payload['csrf']}
        self.assertEqual(self.client.post(payload['urls']['mode'],json={'edit_mode':False},headers=headers).status_code,200)
        self.assertTrue(self.page()['auth']['authenticated'])
        copied = self.app.test_client()
        copied.set_cookie('session',self.client.get_cookie('session').value)
        self.assertEqual(self.client.post('/auth/logout').status_code,403)
        self.assertEqual(self.client.post('/auth/logout',headers=headers).status_code,200)
        self.assertFalse(self.page(copied)['auth']['authenticated'])
        self.assertEqual(self.save(payload,client=copied).status_code,401)
        self.assertFalse(self.page()['edit_mode'])

    def test_changing_editor_invalidates_open_cell_and_delete_tokens(self):
        old = self.edit('Ana')
        self.login('Mihai')
        self.assertEqual(self.save(old).status_code,409)
        response = self.client.post(old['urls']['trash'],json={'token':old['delete_etymon_token'],'confirmation':'DELETE'},headers={'X-CSRF-Token':old['csrf']})
        self.assertEqual(response.status_code,409)
        fresh = self.page()
        self.assertEqual(self.save(fresh).status_code,200)
        self.assertEqual(self.store.edit_history()[0]['editor_name'],'Mihai')

    def test_readonly_tokens_cannot_be_used_after_login(self):
        old = self.page()
        self.edit()
        self.assertEqual(self.save(old).status_code,409)

    def test_password_rotation_revokes_every_session_without_server_restart(self):
        payload = self.edit()
        other = self.app.test_client()
        self.edit('Mihai',other)
        manager = AccessControl(self.root/'access.sqlite3')
        self.addCleanup(manager.close)
        manager.set_edit_password('replacement')
        self.assertEqual(self.save(payload).status_code,401)
        self.assertFalse(self.page(other)['auth']['authenticated'])
        self.assertFalse(self.page()['edit_mode'])
        failed = self.client.post('/auth/login',json={'name':'Ana','password':PASSWORD},headers={'X-CSRF-Token':payload['csrf']})
        self.assertEqual(failed.status_code,401)
        self.login(password='replacement')

    def test_restart_with_stable_secret_retains_browser_login_but_expires_open_drafts(self):
        old = self.edit()
        restarted = create_app(catalog_path=self.root/'catalog.sqlite3',test_config={'DEFAULT_UI_LANGUAGE':'en',
            'TESTING':True,'SECRET_KEY':'auth tests','AUTH_DATABASE_PATH':str(self.root/'access.sqlite3'),
        })
        self.addCleanup(restarted.extensions['access_control'].close)
        self.addCleanup(restarted.extensions['collection_catalog'].close)
        client = restarted.test_client()
        client.set_cookie('session',self.client.get_cookie('session').value)
        fresh = self.page(client)
        self.assertTrue(fresh['auth']['authenticated'])
        self.assertEqual(fresh['auth']['name'],'Ana')
        self.assertTrue(fresh['edit_mode'])
        self.assertEqual(self.save(old,client=client).status_code,409)
        self.assertEqual(self.save(fresh,client=client).status_code,200)

    def test_password_rotation_during_verification_cannot_issue_a_stale_grant(self):
        manager = AccessControl(self.root/'access.sqlite3')
        self.addCleanup(manager.close)
        def changed(*args):
            manager.set_edit_password('replacement')
            return True
        with patch('access_control.check_password_hash',side_effect=changed),self.assertRaises(LoginDenied):
            self.access.login('Ana',PASSWORD,'peer')
        self.assertEqual(self.access.connection.execute('SELECT count(*) FROM editor_sessions').fetchone()[0],0)

    def test_name_and_exact_before_after_content_are_recorded_from_server_identity(self):
        payload = self.edit('Ana Șerban')
        before = self.store.cell((1,LABEL_ORDER[0],1,'LIMBA FRANCEZĂ'))
        self.assertEqual(self.save(payload,'edited é',name='Impostor',editor='Impostor',actor={'name':'Impostor'}).status_code,200)
        event = self.store.edit_history()[0]
        self.assertEqual(event['editor_name'],'Ana Șerban')
        self.assertEqual(event['action'],'save_cell')
        self.assertEqual((event['etimon_number'],event['row_id'],event['column_id'],event['cell_id']),
                         (1,before['row_id'],before['column_id'],before['id']))
        self.assertEqual(event['label'],LABEL_ORDER[0])
        self.assertEqual(event['label_number'],1)
        self.assertEqual(event['column_name'],'LIMBA FRANCEZĂ')
        self.assertEqual(json.loads(event['before_json'])['content'],before['content'])
        self.assertEqual(json.loads(event['after_json'])['plaintext_content'],'edited é')
        self.assertIsNotNone(datetime.fromisoformat(event['occurred_at']).utcoffset())
        self.assertNotIn(PASSWORD,str(event))

    def test_failed_conflicting_and_denied_saves_create_no_history(self):
        payload = self.edit()
        count = len(self.store.edit_history())
        invalid = save_edit(self.client,payload,[{'insert':{'image':'bad'}}])
        self.assertEqual(invalid.status_code,400)
        self.assertEqual(len(self.store.edit_history()),count)
        self.assertEqual(self.save(payload).status_code,200)
        self.assertEqual(self.save(payload).status_code,409)
        self.assertEqual(len(self.store.edit_history()),count+1)

    def test_additions_deletions_recovery_and_history_are_collection_specific(self):
        payload = self.edit()
        headers = {'X-CSRF-Token':payload['csrf'],'X-Editor-Session':payload['auth']['identity']}
        response = self.client.post(payload['urls']['rows'],json={'etimon':1,'label':LABEL_ORDER[1],'text':'sense'},headers=headers)
        self.assertEqual(response.status_code,201)
        created = self.page()
        row = created['rows'][1]
        self.assertEqual(self.client.post(payload['urls']['trash'],json={'token':row['delete_token'],'confirmation':'DELETE'},headers=headers).status_code,200)
        self.assertEqual(self.client.post(payload['urls']['etymons'],json={'text':'second'},headers=headers).status_code,201)
        second = self.page()
        self.assertEqual(self.client.post(payload['urls']['trash'],json={'token':second['delete_etymon_token'],'confirmation':'DELETE'},headers=headers).status_code,200)
        events = list(reversed(self.store.edit_history()))[1:]
        self.assertEqual([item['action'] for item in events],['add_row','delete_row','add_etymon','delete_etymon'])
        self.assertEqual({item['editor_name'] for item in events},{'Ana'})
        self.assertEqual(json.loads(events[0]['after_json'])['cells'][0]['plaintext_content'],'sense')
        self.assertIsNotNone(events[0]['cell_id'])
        self.assertEqual(events[0]['column_name'],'LIMBA FRANCEZĂ')
        self.assertEqual(json.loads(events[1]['before_json'])['cells'][0]['plaintext_content'],'sense')
        self.assertEqual(self.catalog.store(self.b['id']).edit_history(),[])
        self.store.restore_trash(events[-1]['trash_id'])
        self.assertEqual(self.store.edit_history()[0]['editor_name'],'Local administrator')
        self.assertEqual(self.store.edit_history()[0]['action'],'restore_trash')
        output = StringIO()
        with redirect_stdout(output):
            history_command([self.a['database_path'],'--etymon','1','--json'])
        self.assertTrue(all(item['etimon_number']==1 for item in json.loads(output.getvalue())))

    def test_creation_dialogs_cannot_be_credited_to_a_replacement_editor(self):
        old = self.edit('Ana')
        self.login('Mihai')
        stale = {'X-CSRF-Token':old['csrf'],'X-Editor-Session':old['auth']['identity']}
        bodies = {'rows':{'etimon':1,'label':LABEL_ORDER[1],'text':'old row draft'},
                  'etymons':{'text':'old etymon draft'}}
        count = len(self.store.edit_history())
        for endpoint,body in bodies.items():
            self.assertEqual(self.client.post(old['urls'][endpoint],json=body,headers=stale).status_code,409)
        self.assertEqual(len(self.store.edit_history()),count)
        fresh = self.page()
        headers = {'X-CSRF-Token':fresh['csrf'],'X-Editor-Session':fresh['auth']['identity']}
        self.assertEqual(self.client.post(fresh['urls']['rows'],json=bodies['rows'],headers=headers).status_code,201)
        self.assertEqual(self.store.edit_history()[0]['editor_name'],'Mihai')

    def test_history_failure_rolls_back_content_creation_and_deletion(self):
        key = (1,LABEL_ORDER[0],1,'LIMBA FRANCEZĂ')
        before = self.store.cell(key)
        self.store.connection.execute("CREATE TRIGGER audit_failure BEFORE INSERT ON edit_history BEGIN SELECT RAISE(ABORT,'test history failure'); END")
        for change in (lambda:self.store.save_cell(key,before['revision'],[{'insert':'new\n'}]),
                       lambda:self.store.add_etymon('new'),
                       lambda:self.store.delete_etymon(1)):
            with self.assertRaises(sqlite3.IntegrityError):
                change()
            self.assertEqual(self.store.cell(key),before)
            self.assertEqual(list(self.store.entries()),[1])
            self.assertEqual(self.store.list_trash(),[])

    def test_failed_logins_are_throttled_without_logging_passwords(self):
        payload = self.page()
        headers = {'X-CSRF-Token':payload['csrf']}
        with patch('access_control.monotonic',return_value=100):
            for _ in range(10):
                response = self.client.post('/auth/login',json={'name':'Ana','password':'wrong'},headers=headers)
                self.assertEqual(response.status_code,401)
            limited = self.client.post('/auth/login',json={'name':'Ana','password':PASSWORD},headers=headers)
            self.assertEqual(limited.status_code,429)
            self.assertEqual(limited.headers['Retry-After'],'300')
            self.assertNotIn(PASSWORD,limited.get_data(as_text=True))
        with patch('access_control.monotonic',return_value=401):
            self.login()

    def test_cli_sets_hash_and_mismatch_preserves_credentials_and_sessions(self):
        self.login()
        original = self.access.connection.execute('SELECT password_hash FROM credentials').fetchone()[0]
        with patch('manage_access.getpass',side_effect=['new','different']),redirect_stderr(StringIO()),self.assertRaises(SystemExit):
            access_command(['--database',str(self.root/'access.sqlite3'),'set-edit-password'])
        self.assertEqual(self.access.connection.execute('SELECT password_hash FROM credentials').fetchone()[0],original)
        with patch('manage_access.getpass',side_effect=['new','new']),redirect_stdout(StringIO()):
            access_command(['--database',str(self.root/'access.sqlite3'),'set-edit-password'])
        self.assertFalse(self.page()['auth']['authenticated'])
        self.login(password='new')

    def test_access_store_refuses_a_collection_file_without_changing_it(self):
        before = Path(self.a['database_path']).read_bytes()
        with self.assertRaisesRegex(ValueError,'access database'):
            AccessControl(self.a['database_path'])
        self.assertEqual(Path(self.a['database_path']).read_bytes(),before)

    def test_schema_four_migration_retains_ids_edits_trash_and_workbook(self):
        source = self.root/'source.xlsx'
        book = Workbook()
        book.active.append(['Label','LIMBA FRANCEZĂ'])
        book.active.append([LABEL_ORDER[0],'original'])
        book.active.append([LABEL_ORDER[1],'sense'])
        book.save(source)
        book.close()
        path = self.root/'old-four.sqlite3'
        old = LexiconDB(path,source)
        key = (1,LABEL_ORDER[0],1,'LIMBA FRANCEZĂ')
        old.save_cell(key,0,[{'insert':'saved edit\n'}])
        trash = old.delete_row(1,LABEL_ORDER[1],1)
        before = old.cell(key)
        workbook = workbook_bytes(old)
        identity = old.metadata['id']
        old.connection.execute('DROP TABLE edit_history')
        old.connection.execute('UPDATE dataset SET schema_version=4')
        old.close()
        source.unlink()
        new = LexiconDB(path)
        self.addCleanup(new.close)
        self.assertEqual(new.metadata['schema_version'],7)
        self.assertEqual(new.metadata['id'],identity)
        self.assertEqual(new.cell(key),before)
        self.assertEqual(new.list_trash()[0]['id'],trash)
        self.assertEqual(new.edit_history(),[])
        self.assertEqual(workbook_bytes(new),workbook)


if __name__ == '__main__':
    unittest.main()
