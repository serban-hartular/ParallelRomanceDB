"""Admin role separation, password revocation, recovery, safe history and HTML flows."""

from contextlib import redirect_stdout
from datetime import datetime, timedelta
from html.parser import HTMLParser
from io import StringIO
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from access_control import AccessControl, LoginDenied
from admin import date_bounds, safe_next
import admin_data
from collection_catalog import CollectionCatalog
from df_search import LABEL_ORDER
from main import create_app
from manage_access import main as manage_access
from tests.auth_helpers import PASSWORD
from tests.test_flask_app import Page


ADMIN_PASSWORD = 'temporary administrator password'


class Inputs(HTMLParser):
    def __init__(self, response):
        super().__init__()
        self.values = {}
        self.feed(response.get_data(as_text=True))

    def handle_starttag(self,tag,attrs):
        attrs = dict(attrs)
        if tag=='input' and attrs.get('name'):
            self.values[attrs['name']] = attrs.get('value','')


class AdminTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.catalog = CollectionCatalog(self.root/'catalog.sqlite3')
        self.addCleanup(self.catalog.close)
        self.a, self.b = self.catalog.create('Gastronomy'), self.catalog.create('Fashion')
        for entry in (self.a,self.b):
            store = self.catalog.store(entry['id'])
            store.add_etymon('headword')
            store.add_row(1,LABEL_ORDER[1],'sense')
        self.store = self.catalog.store(self.a['id'])
        self.app = create_app(catalog_path=self.root/'catalog.sqlite3',test_config={'DEFAULT_UI_LANGUAGE':'en',
            'TESTING':True,'SECRET_KEY':'admin-regression','AUTH_DATABASE_PATH':str(self.root/'access.sqlite3')})
        self.addCleanup(self.app.extensions['collection_catalog'].close)
        self.access = self.app.extensions['access_control']
        self.addCleanup(self.access.close)
        self.access.set_edit_password(PASSWORD)
        self.access.set_admin_password(ADMIN_PASSWORD)
        self.client = self.app.test_client()

    def path(self, suffix='',entry=None):
        return f"/admin/collections/{(entry or self.a)['id']}/{suffix}"

    def login(self,client=None,name='Elena',password=ADMIN_PASSWORD):
        client = client or self.client
        response = client.get('/admin/login')
        csrf = Inputs(response).values['csrf_token']
        result = client.post('/admin/login',data={'csrf_token':csrf,'name':name,'password':password})
        self.assertEqual(result.status_code,303,result.get_data(as_text=True))
        return result

    def csrf(self,client=None):
        with (client or self.client).session_transaction() as state:
            return state['admin_csrf']

    def post(self,path,body=None,client=None):
        client = client or self.client
        return client.post(path,data={'csrf_token':self.csrf(client),**(body or {})})

    def editor(self,client=None,name='Ana'):
        client = client or self.client
        url = f"/collections/{self.a['id']}/"
        initial = Page(client.get(url)).payload
        result = client.post('/auth/login',json={'name':name,'password':PASSWORD},headers={'X-CSRF-Token':initial['csrf']})
        self.assertEqual(result.status_code,200)
        client.post(initial['urls']['mode'],json={'edit_mode':True},headers={'X-CSRF-Token':initial['csrf']})
        return Page(client.get(url)).payload

    def trash_row(self):
        return self.store.delete_row(1,LABEL_ORDER[1],1,actor={'name':'Bob'})

    def password_change(self,role='edit',password='replacement',current=ADMIN_PASSWORD):
        return self.post(f'/admin/passwords/{role}',{'current_password':current,
            'password':password,'repeat_password':password})

    def test_anonymous_and_editor_only_sessions_cannot_access_any_admin_tool(self):
        trash = self.trash_row()
        event = self.store.edit_history()[0]['id']
        for authenticated_editor in (False,True):
            if authenticated_editor:
                self.editor()
            for path in ('/admin/', '/admin/passwords',self.path('trash'),self.path(f'trash/{trash}'),
                         self.path(f'trash/{trash}/restore'),self.path('history'),self.path(f'history/{event}'),self.path('editors')):
                response = self.client.get(path)
                self.assertEqual(response.status_code,302,path)
                self.assertTrue(response.location.startswith('/admin/login'))
                self.assertNotIn('headword',response.get_data(as_text=True))
            self.assertEqual(self.post(self.path(f'trash/{trash}/restore')).status_code,303)
            self.assertEqual(len(self.store.list_trash()),1)

    def test_admin_bootstrap_is_local_only_and_no_default_credential_is_created(self):
        with self.access.transaction():
            self.access.connection.execute("DELETE FROM editor_sessions WHERE credential_id IN (SELECT id FROM credentials WHERE role='admin')")
            self.access.connection.execute("DELETE FROM credentials WHERE role='admin'")
        response = self.client.get('/admin/login')
        self.assertEqual(response.status_code,503)
        self.assertIn('set-admin-password',response.get_data(as_text=True))
        self.assertNotIn('name="password"',response.get_data(as_text=True))
        csrf = self.csrf()
        result = self.post('/admin/login',{'name':'New admin','password':'invented'})
        self.assertEqual(result.status_code,503)
        self.assertFalse(self.access.configured('admin'))
        self.assertEqual(self.csrf(),csrf)

    def test_admin_login_does_not_grant_editing_and_edit_password_cannot_grant_admin(self):
        initial = self.client.get('/admin/login')
        denied = self.post('/admin/login',{'name':'Ana','password':PASSWORD})
        self.assertEqual(denied.status_code,401)
        self.login()
        payload = Page(self.client.get(f"/collections/{self.a['id']}/")).payload
        self.assertFalse(payload['auth']['authenticated'])
        response = self.client.post(payload['urls']['rows'],json={'etimon':1,'label':LABEL_ORDER[1],'text':'bad'},
                                    headers={'X-CSRF-Token':payload['csrf']})
        self.assertEqual(response.status_code,401)
        self.assertNotIn(ADMIN_PASSWORD,initial.get_data(as_text=True))

    def test_login_rotates_csrf_and_uses_a_browser_session_cookie(self):
        self.client.get('/admin/login')
        before = self.csrf()
        response = self.login()
        self.assertNotEqual(self.csrf(),before)
        cookie = response.headers.get('Set-Cookie','')
        self.assertIn('HttpOnly',cookie)
        self.assertIn('SameSite=Lax',cookie)
        self.assertNotIn('Expires=',cookie)
        self.assertNotIn('Max-Age=',cookie)
        with self.client.session_transaction() as state:
            self.assertFalse(state.permanent)
        self.assertEqual(self.client.get('/admin').status_code,308)

    def test_admin_posts_require_csrf_and_logout_is_post_only(self):
        self.login()
        for path in ('/admin/logout','/admin/passwords/edit','/admin/passwords/admin'):
            self.assertEqual(self.client.post(path,data={}).status_code,403)
            self.assertEqual(self.client.post(path,data={'csrf_token':'bad'}).status_code,403)
        self.assertEqual(self.client.get('/admin/logout').status_code,405)
        self.assertEqual(self.client.get('/admin/passwords/edit').status_code,405)
        self.assertEqual(self.client.get('/admin/').status_code,200)

    def test_wrong_passwords_are_throttled_separately_from_editor_login(self):
        self.client.get('/admin/login')
        with patch('access_control.monotonic',return_value=100):
            for _ in range(10):
                self.assertEqual(self.post('/admin/login',{'name':'Elena','password':'bad'}).status_code,401)
            response = self.post('/admin/login',{'name':'Elena','password':ADMIN_PASSWORD})
            self.assertEqual(response.status_code,429)
            self.assertEqual(response.headers['Retry-After'],'300')
            self.editor()  # The administrator limit cannot lock out editing.
        with patch('access_control.monotonic',return_value=401):
            self.login()

    def test_login_redirects_cannot_leave_admin_or_the_current_site(self):
        for value in ('https://evil.test/','//evil.test/','/admin/\\evil','/collections/x/','//[bad','/admin/\nLocation: bad'):
            self.assertEqual(safe_next(value),'/admin/')
        self.client.get('/admin/login')
        response = self.post('/admin/login',{'name':'Elena','password':ADMIN_PASSWORD,'next':'https://evil.test/'})
        self.assertEqual(response.location,'/admin/')
        self.assertEqual(safe_next(self.path('history')+'?etymon=1'),self.path('history')+'?etymon=1')

    def test_independent_admin_and_editor_logout_and_password_resets(self):
        self.editor()
        self.login()
        with self.client.session_transaction() as state:
            editor = state['editor_session']; admin = state['admin_session']
        self.assertEqual(self.post('/admin/logout').status_code,303)
        self.assertIsNotNone(self.access.editor(editor))
        self.assertIsNone(self.access.administrator(admin))
        self.login()
        with self.client.session_transaction() as state:
            admin = state['admin_session']
        self.access.set_edit_password('local replacement')
        self.assertIsNotNone(self.access.administrator(admin))
        self.assertIsNone(self.access.editor(editor))
        self.assertEqual(self.client.get('/admin/').status_code,200)

    def test_password_confirmation_current_password_and_actor_are_checked(self):
        self.login()
        before = self.access.connection.execute("SELECT password_hash FROM credentials WHERE role='editor'").fetchone()[0]
        response = self.post('/admin/passwords/edit',{'current_password':ADMIN_PASSWORD,'password':'new','repeat_password':'different'})
        self.assertEqual(response.status_code,400)
        self.assertNotIn('value="new"',response.get_data(as_text=True))
        self.assertEqual(self.password_change(current='wrong').status_code,401)
        self.assertEqual(self.access.connection.execute("SELECT password_hash FROM credentials WHERE role='editor'").fetchone()[0],before)

    def test_edit_password_change_revokes_editors_not_admin_and_audits_no_secrets(self):
        self.editor()
        self.login()
        with self.client.session_transaction() as state:
            editor, administrator = state['editor_session'],state['admin_session']
        before = self.access.connection.execute('SELECT count(*) FROM admin_events').fetchone()[0]
        self.assertEqual(self.password_change(password='new edit secret').status_code,303)
        self.assertIsNone(self.access.editor(editor))
        self.assertIsNotNone(self.access.administrator(administrator))
        self.assertEqual(self.access.connection.execute('SELECT count(*) FROM admin_events').fetchone()[0],before+1)
        event = dict(self.access.connection.execute('SELECT * FROM admin_events ORDER BY id DESC LIMIT 1').fetchone())
        self.assertEqual(event['actor_name'],'Elena')
        self.assertEqual(event['role'],'editor')
        self.assertNotIn('new edit secret',json.dumps(event))
        self.assertNotIn('scrypt:',json.dumps(event))
        with self.assertRaises(LoginDenied):
            self.access.login('Ana',PASSWORD,'new-peer')
        self.access.login('Ana','new edit secret','new-peer')

    def test_admin_password_change_revokes_all_admins_not_independent_editor(self):
        self.editor()
        self.login()
        other = self.app.test_client();self.login(other,name='Other admin')
        with self.client.session_transaction() as state:
            editor = state['editor_session']
        self.assertEqual(self.password_change(role='admin',password='new admin secret').status_code,303)
        self.assertEqual(other.get('/admin/').status_code,302)
        self.assertEqual(self.client.get('/admin/').status_code,302)
        self.assertIsNotNone(self.access.editor(editor))
        self.login(password='new admin secret')

    def test_password_change_race_does_not_override_a_concurrent_local_reset(self):
        self.login()
        with self.client.session_transaction() as state:
            actor = self.access.administrator(state['admin_session'])
        manager = AccessControl(self.root/'access.sqlite3');self.addCleanup(manager.close)
        def reset(*args):
            manager.set_admin_password('replacement administrator password')
            return True
        with patch('access_control.check_password_hash',side_effect=reset),self.assertRaises(LoginDenied):
            self.access.change_password('editor','unauthorized replacement',current_password=ADMIN_PASSWORD,actor=actor,peer='race')
        self.access.login('Ana',PASSWORD,'unaffected')

    def test_audit_failure_rolls_back_password_and_session_revocation(self):
        self.login()
        with self.client.session_transaction() as state:
            token = state['admin_session'];actor = self.access.administrator(token)
        self.access.connection.execute("""CREATE TRIGGER reject_admin_event BEFORE INSERT ON admin_events
            BEGIN SELECT RAISE(ABORT,'audit failed'); END""")
        with self.assertRaisesRegex(sqlite3.IntegrityError,'audit failed'):
            self.access.change_password('admin','not committed',current_password=ADMIN_PASSWORD,actor=actor,peer='audit')
        self.assertIsNotNone(self.access.administrator(token))
        self.access.login('Elena',ADMIN_PASSWORD,'still old',role='admin')

    def test_cli_admin_bootstrap_uses_hidden_prompts_and_keeps_editor_login(self):
        self.editor()
        with self.client.session_transaction() as state:
            editor = state['editor_session']
        with patch('manage_access.getpass',side_effect=['local admin password','local admin password']),redirect_stdout(StringIO()):
            self.assertEqual(manage_access(['--database',str(self.root/'access.sqlite3'),'set-admin-password']),0)
        self.assertIsNotNone(self.access.editor(editor))
        self.login(password='local admin password')

    def test_access_schema_one_upgrades_without_losing_credentials_or_grants(self):
        self.editor()
        self.login()
        with self.client.session_transaction() as state:
            editor, admin = state['editor_session'],state['admin_session']
        self.access.connection.execute('DROP TABLE admin_events')
        self.access.connection.execute('UPDATE access_metadata SET version=1')
        reopened = AccessControl(self.root/'access.sqlite3');self.addCleanup(reopened.close)
        self.assertEqual(reopened.connection.execute('SELECT version FROM access_metadata').fetchone()[0],2)
        self.assertIsNotNone(reopened.editor(editor))
        self.assertIsNotNone(reopened.administrator(admin))
        self.assertEqual(reopened.connection.execute('SELECT count(*) FROM admin_events').fetchone()[0],0)

    def test_trash_confirmation_restores_once_with_admin_attribution_and_live_version(self):
        before = self.store.to_dataframe().copy()
        identifier = self.trash_row()
        version = self.store.content_version()
        self.login()
        url = self.path(f'trash/{identifier}/restore')
        confirmation = self.client.get(url)
        self.assertEqual(confirmation.status_code,200)
        self.assertEqual(len(self.store.list_trash()),1)  # GET is just a review.
        target = Inputs(confirmation).values['target']
        self.assertEqual(self.post(url,{'target':target}).status_code,303)
        self.assertEqual(self.store.list_trash(),[])
        self.assertNotEqual(self.store.content_version(),version)
        event = self.store.edit_history()[0]
        self.assertEqual((event['action'],event['editor_name']),('restore_trash','Elena'))
        self.assertEqual(self.post(url,{'target':target}).status_code,409)
        self.assertEqual(self.store.to_dataframe().to_dict('records'),before.to_dict('records'))
        self.assertIn('Recovered',self.client.get(self.path(f'trash/{identifier}')).get_data(as_text=True))

    def test_recovery_requires_csrf_signed_target_and_fails_across_collections(self):
        identifier = self.trash_row()
        other_id = self.catalog.store(self.b['id']).delete_row(1,LABEL_ORDER[1],1)
        self.login()
        url = self.path(f'trash/{identifier}/restore')
        target = Inputs(self.client.get(url)).values['target']
        self.assertEqual(self.client.post(url,data={'target':target}).status_code,403)
        self.assertEqual(self.post(url,{'target':'tampered'}).status_code,409)
        other_url = self.path(f'trash/{other_id}/restore',self.b)
        self.assertEqual(self.post(other_url,{'target':target}).status_code,409)
        self.assertEqual(len(self.store.list_trash()),1)
        self.assertEqual(len(self.catalog.store(self.b['id']).list_trash()),1)

    def test_recovery_parent_first_and_cancel_leave_other_deleted_rows_separate(self):
        child = self.trash_row()
        parent = self.store.delete_etymon(1)
        self.login()
        child_url = self.path(f'trash/{child}/restore')
        response = self.client.get(child_url)
        self.assertIn('containing etymon first',response.get_data(as_text=True))
        self.assertNotIn('type="submit">Restore',response.get_data(as_text=True))
        parent_url = self.path(f'trash/{parent}/restore')
        target = Inputs(self.client.get(parent_url)).values['target']
        self.assertEqual(self.post(parent_url,{'target':target}).status_code,303)
        self.assertEqual([item['id'] for item in self.store.list_trash()],[child])
        target = Inputs(self.client.get(child_url)).values['target']
        self.assertEqual(self.post(child_url,{'target':target}).status_code,303)
        self.assertEqual(self.store.list_trash(),[])

    def test_stale_form_cannot_be_credited_to_a_different_admin_login(self):
        identifier = self.trash_row()
        self.login()
        url = self.path(f'trash/{identifier}/restore')
        values = Inputs(self.client.get(url)).values
        self.post('/admin/logout')
        self.login(name='Replacement administrator')
        self.assertEqual(self.client.post(url,data=values).status_code,403)
        self.assertEqual(len(self.store.list_trash()),1)
        self.assertEqual(self.post(url,{'target':values['target']}).status_code,409)

    def test_history_and_trash_render_untrusted_text_as_text_without_secrets(self):
        malicious = '<img src=x onerror=alert(1)>'
        self.store.save_cell((1,LABEL_ORDER[1],1,'LIMBA FRANCEZĂ'),1,[{'insert':malicious+'\n'}],actor={'name':malicious})
        saved_id = self.store.edit_history()[0]['id']
        trash_id = self.store.delete_row(1,LABEL_ORDER[1],1,actor={'name':malicious})
        self.login()
        with self.client.session_transaction() as state:
            token = state['admin_session']; identity = self.access.administrator(token)['session_id']
        for path in (self.path('history'),self.path(f'history/{saved_id}'),self.path('trash'),self.path(f'trash/{trash_id}')):
            response = self.client.get(path)
            self.assertEqual(response.status_code,200,path)
            body = response.get_data(as_text=True)
            self.assertNotIn('<img src=x',body)
            self.assertIn('&lt;img',body)
            for secret in (token,identity,ADMIN_PASSWORD,'lease_hash','editor_session_id','password_hash'):
                self.assertNotIn(secret,body)
            self.assertEqual(response.headers['Cache-Control'],'no-store')
            self.assertIn("frame-ancestors 'none'",response.headers['Content-Security-Policy'])

    def test_history_distinguishes_activity_and_saved_changes_and_hides_unsaved_drafts(self):
        key = (1,LABEL_ORDER[1],1,'LIMBA FRANCEZĂ')
        cell = self.store.cell(key)
        opened = self.store.begin_cell_edit(key,cell['revision'],cell['generation'],{'name':'Ana','session_id':'local-test'})
        self.store.finish_cell_edit(opened['lease'],{'name':'Ana','session_id':'local-test'},'cancelled')
        self.login()
        event = self.client.get(self.path(f"history/{opened['edit_id']}"))
        self.assertIn('No change saved',event.get_data(as_text=True))
        listing = self.client.get(self.path('history'),query_string={'action':'save_cell'})
        self.assertNotIn(f"history/{opened['edit_id']}\"",listing.get_data(as_text=True))
        listing = self.client.get(self.path('history'),query_string={'activities':'1','status':'cancelled'})
        self.assertIn(f"history/{opened['edit_id']}\"",listing.get_data(as_text=True))

    def test_active_editors_use_existing_records_and_reap_revoked_owners(self):
        payload = self.editor()
        response = self.client.post(payload['urls']['edit_start'],json={'token':payload['rows'][0]['editors']['content_0']['token']},headers={'X-CSRF-Token':payload['csrf']})
        self.assertEqual(response.status_code,201)
        self.login()
        body = self.client.get(self.path('editors')).get_data(as_text=True)
        self.assertIn('Ana',body)
        self.assertNotIn(response.json['lease'],body)
        self.access.set_edit_password('revocation')
        body = self.client.get(self.path('editors')).get_data(as_text=True)
        self.assertIn('No cells are currently being edited',body)

    def test_missing_collections_and_items_do_not_fall_back_or_touch_preferences(self):
        self.login()
        before = self.catalog.connection.execute('SELECT * FROM browser_preferences').fetchall()
        for path in ('/admin/collections/missing/trash',self.path('trash/999'),self.path('history/999')):
            self.assertEqual(self.client.get(path).status_code,404)
        self.assertEqual(self.catalog.connection.execute('SELECT * FROM browser_preferences').fetchall(),before)
        self.assertEqual(self.client.get('/admin/choose',query_string={'collection_id':self.b['id'],'section':'history'}).location,self.path('history',self.b))

    def test_bad_filters_dates_and_pages_return_user_errors(self):
        self.login()
        for path,query in [(self.path('history'),{'page':'0'}),(self.path('history'),{'page':'huge'}),
                           (self.path('history'),{'etymon':'-1'}),(self.path('history'),{'status':'unknown'}),
                           (self.path('history'),{'action':'drop table'}),(self.path('history'),{'since':'2026-02-30'}),
                           (self.path('history'),{'since':'2026-11-07','through':'2026-01-01'}),
                           (self.path('trash'),{'kind':'anything'}),(self.path('trash'),{'state':'bad'})]:
            self.assertEqual(self.client.get(path,query_string=query).status_code,400,(path,query))

    def test_history_filters_are_applied_before_pagination_and_preserved_in_links(self):
        with self.store.transaction(write=True):
            for index in range(120):
                self.store._record_edit('save_cell',{'name':'Wanted' if index%2 else 'Other'},1)
        self.login()
        response = self.client.get(self.path('history'),query_string={'editor':'wanted','collection_id':self.b['id']})
        self.assertEqual(response.status_code,200)
        self.assertIn('Results: 60',response.get_data(as_text=True))
        self.assertIn('editor=wanted',response.get_data(as_text=True))
        self.assertIn(self.path('history'),response.get_data(as_text=True))
        second = admin_data.history_page(self.store,editor='wanted',page=2)
        self.assertEqual(len(second['items']),10)
        self.assertTrue(all(event['editor_name']=='Wanted' for event in second['items']))

    def test_timezone_date_filters_include_the_whole_local_day_across_dst(self):
        lower,upper = date_bounds('2026-03-29','2026-03-29')
        self.assertEqual(datetime.fromisoformat(upper)-datetime.fromisoformat(lower),timedelta(hours=23))
        lower,upper = date_bounds('2026-10-25','2026-10-25')
        self.assertEqual(datetime.fromisoformat(upper)-datetime.fromisoformat(lower),timedelta(hours=25))
        with self.store.transaction(write=True):
            identifier = self.store._record_edit('save_cell',{'name':'Midnight'},1)
            self.store.connection.execute("UPDATE edit_history SET occurred_at='2026-11-06T22:30:00+00:00' WHERE id=?",(identifier,))
        lower,upper = date_bounds('2026-11-07','2026-11-07')
        listing = admin_data.history_page(self.store,editor='Midnight',since=lower,until=upper)
        self.assertEqual(listing['total'],1)

    def test_single_database_mode_and_empty_catalog_have_working_admin_pages(self):
        app = create_app(database_path=self.a['database_path'],test_config={'DEFAULT_UI_LANGUAGE':'en', 'TESTING':True,'AUTH_DATABASE_PATH':str(self.root/'access.sqlite3')})
        self.addCleanup(app.extensions['lexicon_store'].close);self.addCleanup(app.extensions['access_control'].close)
        client = app.test_client()
        client.get('/admin/login')
        token = Inputs(client.get('/admin/login')).values['csrf_token']
        self.assertEqual(client.post('/admin/login',data={'csrf_token':token,'name':'Solo','password':ADMIN_PASSWORD}).status_code,303)
        self.assertEqual(client.get('/admin/').status_code,200)
        self.assertEqual(client.get(self.path('history')).status_code,200)
        self.assertEqual(client.get(self.path('history',self.b)).status_code,404)
        empty = create_app(catalog_path=self.root/'empty-catalog.sqlite3',test_config={'DEFAULT_UI_LANGUAGE':'en', 'TESTING':True,'AUTH_DATABASE_PATH':str(self.root/'access.sqlite3')})
        self.addCleanup(empty.extensions['collection_catalog'].close);self.addCleanup(empty.extensions['access_control'].close)
        client = empty.test_client();csrf = Inputs(client.get('/admin/login')).values['csrf_token']
        client.post('/admin/login',data={'csrf_token':csrf,'name':'Empty','password':ADMIN_PASSWORD})
        self.assertIn('No collections are available',client.get('/admin/').get_data(as_text=True))
        self.assertEqual(client.get('/admin/passwords').status_code,200)


if __name__ == '__main__':
    unittest.main()
