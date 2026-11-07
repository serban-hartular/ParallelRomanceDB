"""Shared credentials and revocable browser-session grants.

Credentials have a role and scope so administrator/collection grants can be
added later. Only global editor grants are issued or accepted at this stage.
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
                if self.connection.execute('SELECT version FROM access_metadata').fetchone()[0] != 1:
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

    def _credential(self):
        return self.connection.execute("SELECT * FROM credentials WHERE role='editor' AND scope_type='global' AND scope_id=''").fetchone()

    def configured(self):
        with self._lock:
            return self._credential() is not None

    @staticmethod
    def _password(password):
        if not isinstance(password, str) or not password or len(password) > 1024:
            raise ValueError('Enter a password of 1–1024 characters.')
        return password

    def set_edit_password(self, password):
        password_hash = generate_password_hash(self._password(password))
        with self.transaction():
            self.connection.execute('''INSERT INTO credentials
                (role,scope_type,scope_id,password_hash,updated_at) VALUES ('editor','global','',?,?)
                ON CONFLICT(role,scope_type,scope_id) DO UPDATE SET
                password_hash=excluded.password_hash,revision=revision+1,updated_at=excluded.updated_at''',
                (password_hash, datetime.now(timezone.utc).isoformat()))
            credential = self._credential()
            self.connection.execute('DELETE FROM editor_sessions WHERE credential_id=?', (credential['id'],))
            self._failures.clear()

    def login(self, name, password, peer):
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120 or any(unicodedata.category(char).startswith('C') for char in name):
            raise LoginDenied('Enter your name (1–120 characters).')
        try:
            self._password(password)
        except ValueError as error:
            raise LoginDenied(str(error)) from error
        with self._lock:
            now = monotonic()
            failures, started = self._failures.get(peer, (0, now))
            if now-started >= 300:
                failures, started = 0, now
            if failures >= 10:
                raise LoginThrottled('Too many unsuccessful attempts. Please wait five minutes and try again.')
            credential = self._credential()
            if credential is None:
                raise LoginDenied('Editing is not available yet. Ask the administrator to set the edit password.')
            if not check_password_hash(credential['password_hash'], password):
                self._failures[peer] = (failures+1, started)
                self._failures.move_to_end(peer)
                while len(self._failures) > 1000:
                    self._failures.popitem(last=False)
                raise LoginDenied('Incorrect edit password.')
            self._failures.pop(peer, None)
            token = token_urlsafe(32)
            with self.transaction():
                current = self._credential()
                if current is None or current['revision'] != credential['revision']:
                    raise LoginDenied('The edit password changed. Please try again.')
                self.connection.execute('INSERT INTO editor_sessions VALUES (?,?,?,?,?)',
                    (sha256(token.encode()).hexdigest(), credential['id'], credential['revision'],
                     name.strip(), datetime.now(timezone.utc).isoformat()))
            return token

    def editor(self, token):
        if not isinstance(token, str) or len(token) > 128:
            return None
        with self._lock:
            row = self.connection.execute('''SELECT s.id AS session_id,s.editor_name AS name,
                c.role,c.scope_type,c.scope_id FROM editor_sessions s JOIN credentials c ON c.id=s.credential_id
                WHERE s.id=? AND s.credential_revision=c.revision
                AND c.role='editor' AND c.scope_type='global' AND c.scope_id='' ''',
                (sha256(token.encode()).hexdigest(),)).fetchone()
            return dict(row) if row else None

    @staticmethod
    def can_edit(editor, collection_id):
        # Deliberately accepts only the implemented grant. Future collection
        # policy and administrator permissions belong here, not in route handlers.
        return bool(editor and editor['role']=='editor' and editor['scope_type']=='global' and editor['scope_id']=='')

    def session_active(self, identity):
        """Check a stored session hash without exposing its bearer token."""
        with self._lock:
            return self.connection.execute("""SELECT 1 FROM editor_sessions s JOIN credentials c ON c.id=s.credential_id
                WHERE s.id=? AND s.credential_revision=c.revision AND c.role='editor'
                AND c.scope_type='global' AND c.scope_id=''""", (identity,)).fetchone() is not None

    def logout(self, token):
        if isinstance(token, str):
            with self.transaction():
                self.connection.execute('DELETE FROM editor_sessions WHERE id=?', (sha256(token.encode()).hexdigest(),))
