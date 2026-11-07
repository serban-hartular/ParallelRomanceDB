"""Registered collection identities, separate SQLite stores, and browser preferences."""

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
                raise ValueError('This file is not a Parallel Words collection catalog.')
            self.connection.execute('CREATE TABLE IF NOT EXISTS catalog_metadata (version INTEGER NOT NULL)')
            if not self.connection.execute('SELECT 1 FROM catalog_metadata').fetchone():
                self.connection.execute('INSERT INTO catalog_metadata VALUES (1)')
            if self.connection.execute('SELECT version FROM catalog_metadata').fetchone()[0] != 1:
                raise ValueError('Unsupported collection catalog schema.')
            self.connection.execute('''CREATE TABLE IF NOT EXISTS collections (
                id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE,
                database_path TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL)''')
            self.connection.execute('''CREATE TABLE IF NOT EXISTS browser_preferences (
                browser_id TEXT NOT NULL, collection_id TEXT NOT NULL REFERENCES collections(id),
                preferences TEXT NOT NULL, PRIMARY KEY(browser_id,collection_id))''')

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

    def collections(self):
        with self._lock:
            return [dict(row) for row in self.connection.execute('SELECT * FROM collections ORDER BY created_at,id')]

    def get(self, collection_id):
        with self._lock:
            row = self.connection.execute('SELECT * FROM collections WHERE id=?', (collection_id,)).fetchone()
            if row is None:
                raise KeyError(collection_id)
            return dict(row)

    def store(self, collection_id):
        with self._lock:
            entry = self.get(collection_id)
            if collection_id not in self._stores:
                if not Path(entry['database_path']).is_file():
                    raise ValueError(f"The database for {entry['name']} is missing.")
                self._stores[collection_id] = LexiconDB(entry['database_path'], collection_id=collection_id)
            return self._stores[collection_id]

    @staticmethod
    def _name(name):
        if not isinstance(name, str) or not name.strip() or len(name)>120:
            raise ValueError('Use a collection name of 1–120 characters.')
        return name.strip()

    def register(self, name, database_path):
        name = self._name(name)
        path = Path(database_path).resolve()
        if not path.is_file():
            raise ValueError('The collection database does not exist.')
        store = LexiconDB(path)
        try:
            with self.transaction():
                self.connection.execute('INSERT INTO collections VALUES (?,?,?,?)',
                    (store.metadata['id'],name,str(path),datetime.now(timezone.utc).isoformat()))
            return self.get(store.metadata['id'])
        except sqlite3.IntegrityError as error:
            raise ValueError('That collection name, identity, or database is already registered.') from error
        finally:
            store.close()

    def create(self, name, workbook=None, sheet_name=None):
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
            return self.register(name,path)
        except BaseException:
            path.unlink(missing_ok=True)
            for suffix in ('-journal','-wal','-shm'):
                Path(str(path)+suffix).unlink(missing_ok=True)
            raise

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
