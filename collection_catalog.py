"""Registered collection identities, separate SQLite stores, and browser preferences."""

from i18n import gettext as _

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from threading import RLock
from uuid import uuid4
from weakref import finalize

from lexicon_db import LexiconDB


class CollectionCatalog:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._stores = {}
        self.connection = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None, timeout=10)
        self.connection.row_factory = sqlite3.Row
        self._finalizer = finalize(self, self.connection.close)
        self.connection.execute('PRAGMA foreign_keys=ON')
        with self.transaction():
            tables = {row[0] for row in self.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables and 'catalog_metadata' not in tables:
                raise ValueError(_('This file is not a Parallel Words collection catalog.'))
            self.connection.execute('CREATE TABLE IF NOT EXISTS catalog_metadata (version INTEGER NOT NULL)')
            if not self.connection.execute('SELECT 1 FROM catalog_metadata').fetchone():
                self.connection.execute('INSERT INTO catalog_metadata VALUES (1)')
            if self.connection.execute('SELECT version FROM catalog_metadata').fetchone()[0] not in (1, 2):
                raise ValueError(_('Unsupported collection catalog schema.'))
            self.connection.execute('''CREATE TABLE IF NOT EXISTS collections (
                id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE,
                database_path TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL)''')
            self.connection.execute('''CREATE TABLE IF NOT EXISTS browser_preferences (
                browser_id TEXT NOT NULL, collection_id TEXT NOT NULL REFERENCES collections(id),
                preferences TEXT NOT NULL, PRIMARY KEY(browser_id,collection_id))''')
            columns = {row['name'] for row in self.connection.execute('PRAGMA table_info(collections)')}
            for name, definition in [('deleted_at','TEXT'), ('deleted_by','TEXT'),
                                     ('lifecycle_revision','INTEGER NOT NULL DEFAULT 0')]:
                if name not in columns:
                    self.connection.execute(f'ALTER TABLE collections ADD COLUMN {name} {definition}')
            self.connection.execute('''CREATE TABLE IF NOT EXISTS collection_events (
                id INTEGER PRIMARY KEY, collection_id TEXT NOT NULL REFERENCES collections(id),
                action TEXT NOT NULL, actor_name TEXT NOT NULL, occurred_at TEXT NOT NULL)''')
            self.connection.execute('UPDATE catalog_metadata SET version=2')

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
            for store in self._stores.values():
                store.close()
            self._stores.clear()
            self._finalizer()

    def collections(self, *, deleted=False):
        with self._lock:
            condition = 'IS NOT NULL' if deleted else 'IS NULL'
            return [dict(row) for row in self.connection.execute(
                f'SELECT * FROM collections WHERE deleted_at {condition} ORDER BY created_at,id')]

    def get(self, collection_id, *, include_deleted=False):
        with self._lock:
            row = self.connection.execute('SELECT * FROM collections WHERE id=?', (collection_id,)).fetchone()
            if row is None or (row['deleted_at'] and not include_deleted):
                raise KeyError(collection_id)
            return dict(row)

    def store(self, collection_id):
        with self._lock:
            entry = self.get(collection_id)
            if collection_id not in self._stores:
                if not Path(entry['database_path']).is_file():
                    raise ValueError(_('The database for {value1} is missing.', value1=entry['name']))
                self._stores[collection_id] = LexiconDB(entry['database_path'], collection_id=collection_id)
            return self._stores[collection_id]

    @staticmethod
    def _name(name):
        if (not isinstance(name, str) or not name.strip() or len(name)>120 or
                any(ord(char)<32 or ord(char)==127 for char in name)):
            raise ValueError(_('Use a collection name of 1–120 characters.'))
        return name.strip()

    def _event(self, collection_id, action, actor):
        self.connection.execute('''INSERT INTO collection_events
            (collection_id,action,actor_name,occurred_at) VALUES (?,?,?,?)''',
            (collection_id,action,(actor or {}).get('name','Local administrator'),
             datetime.now(timezone.utc).isoformat()))

    def suggested_name(self, sheet_name):
        """Suggest a valid name without reserving it or changing the worksheet."""
        base = ''.join(char for char in sheet_name if ord(char)>=32 and ord(char)!=127).strip()
        base = (base or _('Collection'))[:120]
        with self._lock:
            names = {row[0] for row in self.connection.execute('SELECT name FROM collections')}
        candidate, suffix = base, 0
        while candidate in names:
            suffix += 1
            ending = f' ({suffix})'
            candidate = base[:120-len(ending)] + ending
        return candidate

    def rename(self, collection_id, name, revision, *, actor=None):
        """Rename an active collection while excluding concurrent cell leases."""
        name = self._name(name)
        with self._lock:
            store = self.store(collection_id)
            # Keep the collection write lock until the catalog update commits.
            # A lease acquired through another SQLite connection cannot race it.
            store.expire_edits()
            with store.transaction(write=True):
                if store.connection.execute("SELECT 1 FROM edit_history WHERE status='active' LIMIT 1").fetchone():
                    raise ValueError(_('This collection is being edited. Ask editors to close their cell editors before renaming it.'))
                try:
                    with self.transaction():
                        entry = self.get(collection_id)
                        if entry['lifecycle_revision'] != revision:
                            raise ValueError(_('This collection changed. Reload the rename form and try again.'))
                        if name != entry['name']:
                            self.connection.execute('''UPDATE collections SET name=?,
                                lifecycle_revision=lifecycle_revision+1 WHERE id=?''',(name,collection_id))
                            self._event(collection_id,'rename',actor)
                        return self.get(collection_id)
                except sqlite3.IntegrityError:
                    raise ValueError(_('That collection name is already in use, including Collections Trash.')) from None

    def register(self, name, database_path, *, actor=None):
        name = self._name(name)
        path = Path(database_path).resolve()
        if not path.is_file():
            raise ValueError(_('The collection database does not exist.'))
        store = LexiconDB(path)
        try:
            with self.transaction():
                self.connection.execute('INSERT INTO collections (id,name,database_path,created_at) VALUES (?,?,?,?)',
                    (store.metadata['id'],name,str(path),datetime.now(timezone.utc).isoformat()))
                self._event(store.metadata['id'],'create',actor)
                entry = self.get(store.metadata['id'])
            return entry
        except sqlite3.IntegrityError as error:
            raise ValueError(_('That collection name, identity, or database is already registered.')) from error
        finally:
            store.close()

    def create(self, name, workbook=None, sheet_name=None, *, actor=None):
        name = self._name(name)
        collection_id = str(uuid4())
        directory = self.path.parent/'collections'
        directory.mkdir(parents=True, exist_ok=True)
        path = directory/f'{collection_id}.sqlite3'
        # Reserve a new path; failed imports cannot replace an existing database.
        with path.open('xb'):
            pass
        try:
            store = LexiconDB(path,workbook,sheet_name,create_empty=workbook is None,collection_id=collection_id)
            store.close()
            return self.register(name,path,actor=actor)
        except BaseException:
            path.unlink(missing_ok=True)
            for suffix in ('-journal','-wal','-shm'):
                Path(str(path)+suffix).unlink(missing_ok=True)
            raise

    def move_to_trash(self, collection_id, revision, *, actor=None, expected_version=None):
        # Match the request guard's catalog -> collection lock ordering. The
        # collection write transaction also excludes another SQLite connection
        # while checking leases. Files and cached stores stay intact.
        with self._lock:
            entry = self.get(collection_id)
            store = self.store(collection_id)
            store.expire_edits()
            with store.transaction(write=True):
                if expected_version is not None and store.content_version()!=expected_version:
                    raise ValueError(_('The collection content changed. Review its removal again.'))
                if store.connection.execute("SELECT 1 FROM edit_history WHERE status='active' LIMIT 1").fetchone():
                    raise ValueError(_('This collection has active cell editors. Ask them to close their drafts first.'))
                with self.transaction():
                    entry = self.get(collection_id)
                    if entry['lifecycle_revision'] != revision:
                        raise ValueError(_('This collection changed. Review its removal again.'))
                    self.connection.execute('''UPDATE collections SET deleted_at=?,deleted_by=?,
                        lifecycle_revision=lifecycle_revision+1 WHERE id=?''',
                        (datetime.now(timezone.utc).isoformat(),(actor or {}).get('name','Local administrator'),collection_id))
                    self._event(collection_id,'delete',actor)

    def restore_collection(self, collection_id, revision, *, actor=None):
        with self.transaction():
            entry = self.get(collection_id,include_deleted=True)
            if not entry['deleted_at'] or entry['lifecycle_revision'] != revision:
                raise ValueError(_('This collection changed or has already been restored. Reload Collections Trash.'))
            if not Path(entry['database_path']).is_file():
                raise ValueError(_('The collection database is missing. Restore the database file from backup first.'))
            self.connection.execute('''UPDATE collections SET deleted_at=NULL,deleted_by=NULL,
                lifecycle_revision=lifecycle_revision+1 WHERE id=?''',(collection_id,))
            self._event(collection_id,'restore',actor)

    def preferences(self, browser_id, collection_id):
        with self._lock:
            row = self.connection.execute('''SELECT preferences FROM browser_preferences
                WHERE browser_id=? AND collection_id=?''', (browser_id,collection_id)).fetchone()
            return json.loads(row[0]) if row else {}

    def save_preferences(self, browser_id, collection_id, preferences):
        with self.transaction():
            self.connection.execute('''INSERT INTO browser_preferences VALUES (?,?,?)
                ON CONFLICT(browser_id,collection_id) DO UPDATE SET preferences=excluded.preferences''',
                (browser_id,collection_id,json.dumps(preferences,ensure_ascii=False)))
