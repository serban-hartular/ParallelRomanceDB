"""Shared credentials and revocable browser-session grants.

Global editor and administrator credentials issue separate revocable grants.
Collection-scoped grants remain reserved and fail closed.
"""

from collections import OrderedDict
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import os
from pathlib import Path
from secrets import token_urlsafe
import sqlite3
from threading import RLock
from time import monotonic
import unicodedata
from weakref import finalize

from werkzeug.security import check_password_hash, generate_password_hash


class LoginDenied(ValueError):
    pass


class LoginThrottled(LoginDenied):
    pass


class AccessControl:
    def __init__(self, path):
        self.path = str(path)
        if self.path != ':memory:':
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            try:
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(descriptor)
        self._lock = RLock()
        self._failures = OrderedDict()
        self.connection = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None, timeout=10)
        self.connection.row_factory = sqlite3.Row
        self._finalizer = finalize(self, self.connection.close)
        self.connection.execute('PRAGMA foreign_keys=ON')
        try:
            with self.transaction():
                tables = {row[0] for row in self.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if tables and 'access_metadata' not in tables:
                    raise ValueError('This file is not a Parallel Words access database.')
                self.connection.execute('CREATE TABLE IF NOT EXISTS access_metadata (version INTEGER NOT NULL)')
                if not self.connection.execute('SELECT 1 FROM access_metadata').fetchone():
                    self.connection.execute('INSERT INTO access_metadata VALUES (1)')
                if self.connection.execute('SELECT version FROM access_metadata').fetchone()[0] not in (1,2):
                    raise ValueError('Unsupported access database schema.')
                self.connection.execute('''CREATE TABLE IF NOT EXISTS credentials (
                    id INTEGER PRIMARY KEY, role TEXT NOT NULL CHECK(role IN ('editor','admin')),
                    scope_type TEXT NOT NULL CHECK(scope_type IN ('global','collection')),
                    scope_id TEXT NOT NULL, password_hash TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL, UNIQUE(role,scope_type,scope_id),
                    CHECK((scope_type='global' AND scope_id='') OR (scope_type='collection' AND scope_id<>'')))''')
                self.connection.execute('''CREATE TABLE IF NOT EXISTS editor_sessions (
                    id TEXT PRIMARY KEY, credential_id INTEGER NOT NULL REFERENCES credentials(id),
                    credential_revision INTEGER NOT NULL, editor_name TEXT NOT NULL, created_at TEXT NOT NULL)''')
                self.connection.execute('''CREATE TABLE IF NOT EXISTS admin_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, occurred_at TEXT NOT NULL,
                    actor_name TEXT NOT NULL, actor_session_id TEXT, action TEXT NOT NULL,
                    role TEXT NOT NULL, scope_type TEXT NOT NULL, scope_id TEXT NOT NULL,
                    credential_revision INTEGER NOT NULL)''')
                self.connection.execute('UPDATE access_metadata SET version=2')
        except BaseException:
            self.close()
            raise

    @contextmanager
    def transaction(self):
        with self._lock:
            self.connection.execute('BEGIN IMMEDIATE')
            try:
                yield
                self.connection.commit()
            except BaseException:
                self.connection.rollback()
                raise

    def close(self):
        with self._lock:
            self._finalizer()

    @staticmethod
    def _role(role):
        if role not in ('editor','admin'):
            raise ValueError('Unsupported access role.')
        return role

    def _credential(self, role='editor'):
        self._role(role)
        return self.connection.execute("SELECT * FROM credentials WHERE role=? AND scope_type='global' AND scope_id=''",(role,)).fetchone()

    def configured(self, role='editor'):
        with self._lock:
            return self._credential(role) is not None

    def credential_status(self):
        with self._lock:
            return {role: ({'configured':True,'updated_at':row['updated_at']} if
                           (row:=self._credential(role)) else {'configured':False,'updated_at':None})
                    for role in ('editor','admin')}

    @staticmethod
    def _password(password):
        if not isinstance(password, str) or not password or len(password) > 1024:
            raise ValueError('Enter a password of 1–1024 characters.')
        try:
            password.encode('utf-8')
        except UnicodeEncodeError:
            raise ValueError('Enter a valid Unicode password.') from None
        return password

    def _write_password(self, role, password_hash, actor=None):
        # Caller holds a write transaction. Secrets never enter the audit table.
        self.connection.execute('''INSERT INTO credentials
            (role,scope_type,scope_id,password_hash,updated_at) VALUES (?,'global','',?,?)
            ON CONFLICT(role,scope_type,scope_id) DO UPDATE SET
            password_hash=excluded.password_hash,revision=revision+1,updated_at=excluded.updated_at''',
            (role,password_hash,datetime.now(timezone.utc).isoformat()))
        credential = self._credential(role)
        self.connection.execute('DELETE FROM editor_sessions WHERE credential_id=?',(credential['id'],))
        actor = actor or {'name':'Local administrator','session_id':None}
        self.connection.execute('''INSERT INTO admin_events
            (occurred_at,actor_name,actor_session_id,action,role,scope_type,scope_id,credential_revision)
            VALUES (?,?,?,'set_password',?,'global','',?)''',
            (datetime.now(timezone.utc).isoformat(),actor['name'],actor.get('session_id'),role,credential['revision']))
        for key in list(self._failures):
            if key[0] == role:
                del self._failures[key]

    def set_edit_password(self, password):
        self._set_password('editor',password)

    def set_admin_password(self, password):
        self._set_password('admin',password)

    def _set_password(self, role, password):
        password_hash = generate_password_hash(self._password(password))
        with self.transaction():
            self._write_password(self._role(role),password_hash)

    def _verify_password(self, password, peer, role):
        self._role(role)
        try:
            self._password(password)
        except ValueError as error:
            raise LoginDenied(str(error)) from error
        key, now = (role,peer), monotonic()
        failures, started = self._failures.get(key,(0,now))
        if now-started >= 300:
            failures, started = 0, now
        if failures >= 10:
            raise LoginThrottled('Too many unsuccessful attempts. Please wait five minutes and try again.')
        credential = self._credential(role)
        if credential is None:
            if role=='admin':
                raise LoginDenied('Administration is not enabled yet. Set the administrator password locally.')
            raise LoginDenied('Editing is not available yet. Ask the administrator to set the edit password.')
        if not check_password_hash(credential['password_hash'],password):
            self._failures[key] = (failures+1,started)
            self._failures.move_to_end(key)
            while len(self._failures)>1000:
                self._failures.popitem(last=False)
            raise LoginDenied('Incorrect administrator password.' if role=='admin' else 'Incorrect edit password.')
        self._failures.pop(key,None)
        return credential

    def login(self, name, password, peer, *, role='editor'):
        if not isinstance(name,str) or not 1<=len(name.strip())<=120 or any(unicodedata.category(char).startswith('C') for char in name):
            raise LoginDenied('Enter your name (1–120 characters).')
        with self._lock:
            credential = self._verify_password(password,peer,role)
            token = token_urlsafe(32)
            with self.transaction():
                current = self._credential(role)
                if current is None or current['revision']!=credential['revision']:
                    raise LoginDenied('The password changed. Please try again.')
                self.connection.execute('INSERT INTO editor_sessions VALUES (?,?,?,?,?)',
                    (sha256(token.encode()).hexdigest(),credential['id'],credential['revision'],
                     name.strip(),datetime.now(timezone.utc).isoformat()))
            return token

    def _session_identity(self, identity, role):
        row = self.connection.execute('''SELECT s.id AS session_id,s.editor_name AS name,
            c.role,c.scope_type,c.scope_id FROM editor_sessions s JOIN credentials c ON c.id=s.credential_id
            WHERE s.id=? AND s.credential_revision=c.revision
            AND c.role=? AND c.scope_type='global' AND c.scope_id='' ''',(identity,self._role(role))).fetchone()
        return dict(row) if row else None

    def _session(self, token, role):
        if not isinstance(token,str) or len(token)>128:
            return None
        try:
            identity = sha256(token.encode()).hexdigest()
        except UnicodeEncodeError:
            return None
        with self._lock:
            return self._session_identity(identity,role)

    def editor(self, token):
        return self._session(token,'editor')

    def administrator(self, token):
        return self._session(token,'admin')

    def change_password(self, role, password, *, current_password, actor, peer):
        self._role(role)
        password_hash = generate_password_hash(self._password(password))
        with self._lock:
            verified = self._verify_password(current_password,peer,'admin')
            with self.transaction():
                current = self._credential('admin')
                administrator = self._session_identity(actor.get('session_id'),'admin')
                if current is None or current['revision']!=verified['revision'] or administrator is None:
                    raise LoginDenied('The administrator login or password changed. Sign in again.')
                self._write_password(role,password_hash,administrator)

    @staticmethod
    def can_edit(editor, collection_id):
        return bool(editor and editor['role']=='editor' and editor['scope_type']=='global' and editor['scope_id']=='')

    @staticmethod
    def can_admin(administrator):
        return bool(administrator and administrator['role']=='admin' and administrator['scope_type']=='global' and administrator['scope_id']=='')

    def session_active(self, identity):
        """Check an editor's stored session hash without exposing its bearer token."""
        with self._lock:
            return self._session_identity(identity,'editor') is not None

    def logout(self, token):
        if isinstance(token,str):
            try:
                identity = sha256(token.encode()).hexdigest()
            except UnicodeEncodeError:
                return
            with self.transaction():
                self.connection.execute('DELETE FROM editor_sessions WHERE id=?',(identity,))
