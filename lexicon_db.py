"""SQLite source of truth for one imported worksheet and its export template."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
from secrets import token_urlsafe
import sqlite3
from threading import RLock
from uuid import uuid4
from weakref import finalize

import pandas as pd
from openpyxl import Workbook, load_workbook

from cell_editing import render_delta, validate_line_height
from df_search import COLUMN_ORDER, LABEL_ORDER
from text_normalization import remove_diacritics


FRAME_COLUMNS = (
    'etimon_number', 'column', 'label', 'label_number', 'content',
    'plaintext_content', 'nodiacritics_plaintext', 'background_color',
)
KEY_SQL = 'etimon_number=? AND label=? AND label_number=? AND "column"=?'
_DEFAULT_ROW_COLORS = object()
HISTORY_SCHEMA = '''CREATE TABLE edit_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL, editor_name TEXT NOT NULL,
    editor_session_id TEXT, occurred_at TEXT NOT NULL, etimon_number INTEGER NOT NULL,
    row_id INTEGER REFERENCES row_metadata(id), column_id INTEGER REFERENCES column_definitions(id),
    cell_id INTEGER REFERENCES cells(id), label TEXT, label_number INTEGER, column_name TEXT,
    trash_id INTEGER REFERENCES trash(id), before_json TEXT, after_json TEXT,
    status TEXT NOT NULL DEFAULT 'saved' CHECK(status IN ('active','saved','cancelled','unchanged','expired','revoked')),
    started_at TEXT, last_seen_at TEXT, expires_at TEXT, finished_at TEXT, lease_hash TEXT)'''

ACTIVE_CELL_SQL = '''EXISTS (SELECT 1 FROM row_metadata r
    WHERE r.id=cell_records.row_id AND r.trash_id IS NULL)'''


def default_database_path(excel_path, sheet_name=None):
    suffix = f'.{sha256(sheet_name.encode()).hexdigest()[:10]}' if sheet_name is not None else ''
    path = Path(excel_path)
    return path.with_name(f'{path.name}{suffix}.sqlite3')


class EditConflict(ValueError):
    pass


class EditBusy(EditConflict):
    pass


def edit_now():
    return datetime.now(timezone.utc)


class LexiconDB:
    def __init__(self, database_path, excel_path=None, sheet_name=None, *, loader=None,
                 row_colors=_DEFAULT_ROW_COLORS, collection_id=None, create_empty=False):
        self.path = str(database_path)
        new_path = self.path != ':memory:' and not Path(self.path).exists()
        self._lock = RLock()
        self._empty_backgrounds = None
        self.session_validator = None
        self._empty_background_rows = None
        if self.path != ':memory:':
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        if row_colors is _DEFAULT_ROW_COLORS:
            from config import ROW_BACKGROUND_COLORS
            row_colors = ROW_BACKGROUND_COLORS
        self.connection = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None, timeout=10)
        self.connection.row_factory = sqlite3.Row
        self._finalizer = finalize(self, self.connection.close)
        self.connection.execute('PRAGMA foreign_keys=ON')
        self.connection.create_function('search_fold', 1, lambda text: text.upper(), deterministic=True)
        try:
            exists = self.connection.execute("SELECT 1 FROM sqlite_master WHERE name='dataset'").fetchone()
            if not exists:
                if self.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchone():
                    raise ValueError('The selected database is not a Parallel Words collection.')
                if excel_path is None and not create_empty:
                    raise ValueError('A workbook or create_empty=True is required to initialize a collection.')
                if excel_path is None:
                    workbook = Workbook()
                    workbook.active.title = sheet_name or 'Lexicon'
                    workbook.active.append(['Label', *COLUMN_ORDER])
                    buffer = BytesIO()
                    workbook.save(buffer)
                    workbook.close()
                    template, source_name, source_path = buffer.getvalue(), 'collection.xlsx', ''
                    from extract_sheet import excel_to_dataframe
                    frame = excel_to_dataframe(BytesIO(template), sheet_name)
                else:
                    if loader is None:
                        from extract_sheet import excel_to_dataframe
                        loader = excel_to_dataframe
                    frame = loader(str(excel_path), sheet_name)
                    source = Path(excel_path)
                    template, source_name, source_path = source.read_bytes(), source.name, str(source.resolve())
                self._initialize(frame, template, source_name, source_path, row_colors, collection_id)
            metadata = self.connection.execute(
                'SELECT id, source_path, source_name, sheet_name, schema_version FROM dataset'
            ).fetchone()
            if metadata is None or metadata['schema_version'] not in (4, 5, 6, 7):
                raise ValueError('This collection requires the new schema (version 7). Reimport the workbook into a new database; the old file is unchanged.')
            self.metadata = dict(metadata)
            if collection_id is not None and collection_id != self.metadata['id']:
                raise ValueError('The database identity does not match its catalog entry.')
            if sheet_name is not None and sheet_name != self.metadata['sheet_name']:
                raise ValueError('The selected database contains a different worksheet. Choose another database.')
            if self.metadata['schema_version'] == 4:
                with self.transaction(write=True):
                    self.connection.execute(HISTORY_SCHEMA.replace('CREATE TABLE ', 'CREATE TABLE IF NOT EXISTS ', 1))
                    self.connection.execute('UPDATE dataset SET schema_version=5')
                self.metadata['schema_version'] = 5
            if self.metadata['schema_version'] == 5:
                with self.transaction(write=True):
                    columns = {row['name'] for row in self.connection.execute('PRAGMA table_info(edit_history)')}
                    for name, definition in self._history_columns().items():
                        if name not in columns:
                            self.connection.execute(f'ALTER TABLE edit_history ADD COLUMN {name} {definition}')
                    self.connection.execute("UPDATE edit_history SET finished_at=occurred_at WHERE status='saved' AND finished_at IS NULL")
                    self._history_indexes()
                    self.connection.execute('UPDATE dataset SET schema_version=6')
                self.metadata['schema_version'] = 6
            if self.metadata['schema_version'] == 6:
                with self.transaction(write=True):
                    columns = {row['name'] for row in self.connection.execute('PRAGMA table_info(dataset)')}
                    if 'content_revision' not in columns:
                        self.connection.execute('ALTER TABLE dataset ADD COLUMN content_revision INTEGER NOT NULL DEFAULT 0')
                    # Triggers include local tools/definition changes and roll back
                    # with the content. Editing contacts/history are deliberately excluded.
                    for table in ('cells', 'row_metadata', 'etymons', 'column_definitions', 'row_types'):
                        for operation in ('INSERT', 'UPDATE', 'DELETE'):
                            self.connection.execute(f'''CREATE TRIGGER IF NOT EXISTS content_{table}_{operation.lower()}
                                AFTER {operation} ON {table} BEGIN
                                UPDATE dataset SET content_revision=content_revision+1; END''')
                    self.connection.execute('''CREATE TRIGGER IF NOT EXISTS content_initial_column
                        AFTER UPDATE OF initial_column_id ON dataset BEGIN
                        UPDATE dataset SET content_revision=content_revision+1; END''')
                    self.connection.execute('UPDATE dataset SET schema_version=7')
                self.metadata['schema_version'] = 7
        except BaseException:
            self._finalizer()
            if new_path:
                Path(self.path).unlink(missing_ok=True)
            raise

    @staticmethod
    def _history_columns():
        return {'status':"TEXT NOT NULL DEFAULT 'saved' CHECK(status IN ('active','saved','cancelled','unchanged','expired','revoked'))",
                'started_at':'TEXT','last_seen_at':'TEXT','expires_at':'TEXT','finished_at':'TEXT','lease_hash':'TEXT'}

    def _history_indexes(self):
        self.connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS active_cell_edit ON edit_history(row_id,column_id) WHERE status='active'")
        self.connection.execute('CREATE UNIQUE INDEX IF NOT EXISTS edit_lease ON edit_history(lease_hash) WHERE lease_hash IS NOT NULL')

    def _initialize(self, frame, template, source_name, source_path, row_colors, collection_id):
        if not isinstance(row_colors, dict) or set(row_colors) != set(LABEL_ORDER):
            raise ValueError('ROW_BACKGROUND_COLORS must define all four canonical row labels.')
        colors = {}
        for label, color in row_colors.items():
            if not isinstance(color, str) or not re.fullmatch(r'#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?', color):
                raise ValueError('ROW_BACKGROUND_COLORS values must be #RGB or #RRGGBB hex colors.')
            if len(color) == 4:
                color = '#' + ''.join(value * 2 for value in color[1:])
            colors[self._label_kind(label)] = color.upper()
        schema = '''
            BEGIN IMMEDIATE;
            CREATE TABLE column_definitions (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, display_order INTEGER NOT NULL,
                sheet_column INTEGER UNIQUE, source_name TEXT, title_priority INTEGER,
                CHECK(sheet_column IS NULL OR sheet_column>=2)
            );
            CREATE TABLE row_types (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, display_order INTEGER NOT NULL,
                is_etymon INTEGER NOT NULL CHECK(is_etymon IN (0,1)),
                allow_add INTEGER NOT NULL CHECK(allow_add IN (0,1)),
                default_background TEXT NOT NULL DEFAULT '', CHECK(NOT(is_etymon AND allow_add))
            );
            CREATE UNIQUE INDEX one_etymon_type ON row_types(is_etymon) WHERE is_etymon=1;
            CREATE TABLE dataset (
                id TEXT PRIMARY KEY, schema_version INTEGER NOT NULL,
                source_path TEXT NOT NULL, source_name TEXT NOT NULL, sheet_name TEXT NOT NULL,
                workbook BLOB NOT NULL, initial_column_id INTEGER NOT NULL REFERENCES column_definitions(id)
            );
            CREATE TABLE etymons (id INTEGER PRIMARY KEY, source_row INTEGER UNIQUE);
            CREATE TABLE trash (
                id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
                etimon_number INTEGER NOT NULL REFERENCES etymons(id), label TEXT, label_number INTEGER,
                title TEXT NOT NULL, deleted_at TEXT NOT NULL, restored_at TEXT
            );
            CREATE TABLE row_metadata (
                id INTEGER PRIMARY KEY, etimon_number INTEGER NOT NULL REFERENCES etymons(id),
                row_type_id INTEGER NOT NULL REFERENCES row_types(id),
                label TEXT NOT NULL, label_number INTEGER NOT NULL,
                sheet_row INTEGER NOT NULL UNIQUE, background_color TEXT NOT NULL DEFAULT '',
                source_row INTEGER UNIQUE, style_row INTEGER,
                trash_id INTEGER REFERENCES trash(id), generation INTEGER NOT NULL DEFAULT 0,
                UNIQUE(etimon_number, label, label_number)
            );
            CREATE INDEX row_trash ON row_metadata(trash_id);
            CREATE TABLE cells (
                id INTEGER PRIMARY KEY, row_id INTEGER NOT NULL REFERENCES row_metadata(id),
                column_id INTEGER NOT NULL REFERENCES column_definitions(id),
                content TEXT NOT NULL, plaintext_content TEXT NOT NULL,
                nodiacritics_plaintext TEXT NOT NULL, background_color TEXT NOT NULL DEFAULT '',
                revision INTEGER NOT NULL DEFAULT 0, line_height REAL,
                UNIQUE(row_id,column_id)
            );
            CREATE VIEW cell_records AS SELECT c.*, r.etimon_number, d.name AS "column",
                r.label, r.label_number, r.row_type_id, t.is_etymon
                FROM cells c JOIN row_metadata r ON r.id=c.row_id
                JOIN column_definitions d ON d.id=c.column_id JOIN row_types t ON t.id=r.row_type_id;
        '''
        try:
            self.connection.executescript(schema)
            self.connection.execute(HISTORY_SCHEMA)
            self._history_indexes()
            physical = frame.attrs['column_positions']
            names = list(COLUMN_ORDER) + [name for name in physical if name not in COLUMN_ORDER]
            column_ids = {}
            for order, name in enumerate(names):
                cursor = self.connection.execute('''INSERT INTO column_definitions
                    (name,display_order,sheet_column,source_name,title_priority) VALUES (?,?,?,?,?)''',
                    (name, order, physical.get(name), name if name in physical else None,
                     order if order<6 else None))
                column_ids[name] = cursor.lastrowid
            self.connection.execute('INSERT INTO dataset VALUES (?,6,?,?,?,?,?)', (
                collection_id or str(uuid4()), source_path, source_name, frame.attrs['sheet_name'],
                template, column_ids[COLUMN_ORDER[0]],
            ))
            labels = list(dict.fromkeys(key[1] for key in frame.attrs['row_positions']))
            # Include label-only definitions, preserving exact source spelling.
            labels = list(dict.fromkeys([*frame.attrs.get('row_labels', []), *labels]))
            type_ids = {}
            for order, default in enumerate(LABEL_ORDER):
                kind = self._label_kind(default)
                name = next((label for label in labels if self._label_kind(label)==kind), default)
                cursor = self.connection.execute('''INSERT INTO row_types
                    (name,display_order,is_etymon,allow_add,default_background) VALUES (?,?,?,?,?)''',
                    (name, order, int(order==0), int(order!=0), colors[kind]))
                type_ids[kind] = cursor.lastrowid
            for label in labels:
                kind = self._label_kind(label)
                if kind not in type_ids:
                    cursor = self.connection.execute('''INSERT INTO row_types
                        (name,display_order,is_etymon,allow_add) VALUES (?,?,0,0)''', (label,len(type_ids)))
                    type_ids[kind] = cursor.lastrowid
            etymons = frame.attrs.get('etymon_positions', {})
            if not etymons:
                etymons = {number: None for number, _, _ in frame.attrs['row_positions']}
            self.connection.executemany('INSERT INTO etymons VALUES (?,?)', etymons.items())
            backgrounds = frame.attrs.get('label_backgrounds', {})
            row_ids = {}
            for key, position in frame.attrs['row_positions'].items():
                cursor = self.connection.execute('''INSERT INTO row_metadata
                    (etimon_number,row_type_id,label,label_number,sheet_row,background_color,source_row)
                    VALUES (?,?,?,?,?,?,?)''', (key[0],type_ids[self._label_kind(key[1])],key[1],key[2],
                                              position,backgrounds.get(key,''),position))
                row_ids[key] = cursor.lastrowid
            self.connection.executemany('''INSERT INTO cells
                (row_id,column_id,content,plaintext_content,nodiacritics_plaintext,background_color)
                VALUES (?,?,?,?,?,?)''', (
                (row_ids[(record.etimon_number,record.label,record.label_number)], column_ids[record.column],
                 record.content,record.plaintext_content,record.nodiacritics_plaintext,record.background_color)
                for record in frame.itertuples(index=False)
            ))
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise

    def column_definitions(self):
        return [dict(row) for row in self.connection.execute('SELECT * FROM column_definitions ORDER BY display_order,id')]

    def content_version(self):
        """Persistent committed-content marker, unaffected by locks and heartbeats."""
        with self._lock:
            revision = self.connection.execute('SELECT content_revision FROM dataset').fetchone()[0]
            return f"{self.metadata['id']}:{revision}"

    def row_types(self):
        return [dict(row) for row in self.connection.execute('SELECT * FROM row_types ORDER BY display_order,id')]

    def initial_column(self):
        row = self.connection.execute('''SELECT c.* FROM column_definitions c
            JOIN dataset d ON c.id=d.initial_column_id''').fetchone()
        if row is None:
            raise ValueError('The collection has no initial-entry column.')
        return dict(row)

    def row_type(self, etimon, label, number):
        row = self.connection.execute('''SELECT t.* FROM row_types t JOIN row_metadata r ON r.row_type_id=t.id
            WHERE r.etimon_number=? AND r.label=? AND r.label_number=?''', (etimon,label,number)).fetchone()
        return dict(row) if row else None

    @contextmanager
    def transaction(self, *, write=False):
        with self._lock:
            self.connection.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            try:
                yield self
                self.connection.commit()
            except BaseException:
                self.connection.rollback()
                raise

    def close(self):
        with self._lock:
            self._finalizer()

    def _records(self, etimon=None):
        sql = 'SELECT * FROM cell_records WHERE ' + ACTIVE_CELL_SQL
        values = ()
        if etimon is not None:
            sql += ' AND etimon_number=?'
            values = (etimon,)
        return [dict(row) for row in self.connection.execute(sql + ' ORDER BY id', values)]

    def to_dataframe(self, etimon=None):
        """Return a detached snapshot; mutating it never changes the database."""
        with self._lock:
            records = self._records(etimon)
            frame = pd.DataFrame.from_records(records, columns=FRAME_COLUMNS)
            frame.attrs['sheet_name'] = self.metadata['sheet_name']
            frame.attrs['column_definitions'] = self.column_definitions()
            frame.attrs['row_types'] = self.row_types()
            frame.attrs['label_type_ids'] = dict(self.connection.execute('SELECT label,row_type_id FROM row_metadata'))
            rows = self.connection.execute('SELECT * FROM row_metadata WHERE trash_id IS NULL').fetchall()
            frame.attrs['label_backgrounds'] = {
                (row['etimon_number'], row['label'], row['label_number']): row['background_color']
                for row in rows if row['background_color']
            }
            frame.attrs['cell_line_heights'] = {
                (row['etimon_number'], row['label'], row['label_number'], row['column']): row['line_height']
                for row in records if row['line_height'] is not None
            }
            identities = (tuple((row['id'], row['sheet_row']) for row in rows),
                          tuple((item['id'],item['name'],item['sheet_column']) for item in self.column_definitions()))
            if identities != self._empty_background_rows:
                self._empty_backgrounds = None
            frame.attrs['empty_cell_backgrounds'] = self._original_empty_backgrounds().copy()
            self._empty_background_rows = identities
            return frame

    def _original_empty_backgrounds(self):
        """Keep a formerly empty cell's fill when it gains content.

        Workbook imports omit blank cells. Recover their presentation
        from the saved template once, without changing data or schema. A blank
        fill means the browser's neutral label background should be retained.
        App-created rows use their persisted type color across every column.
        """
        if self._empty_backgrounds is None:
            from extract_sheet import _cell_background, _color_resolver

            template = self.connection.execute('SELECT workbook FROM dataset').fetchone()[0]
            workbook = load_workbook(BytesIO(template))
            try:
                sheet = workbook[self.metadata['sheet_name']]
                resolve = _color_resolver(workbook)
                columns = dict(self.connection.execute('SELECT name,sheet_column FROM column_definitions'))
                backgrounds = {}
                for row in self.connection.execute('SELECT * FROM row_metadata WHERE trash_id IS NULL'):
                    for name, number in columns.items():
                        key = (row['etimon_number'], row['label'], row['label_number'], name)
                        if row['source_row'] is None:
                            backgrounds[key] = row['background_color']
                            continue
                        source = row['source_row'] or row['style_row']
                        cell = sheet.cell(source, number) if number is not None and source else None
                        if cell is None or cell.value is None or not str(cell.value).strip():
                            backgrounds[key] = (_cell_background(cell, resolve) if cell is not None else '') or row['background_color']
                self._empty_backgrounds = backgrounds
            finally:
                workbook.close()
        return self._empty_backgrounds

    @staticmethod
    def _label_kind(label):
        if re.match(r'^\s*ETIMON\s*/', label, re.IGNORECASE):
            label = LABEL_ORDER[0]
        return ' '.join(remove_diacritics(label).upper().split())

    def row_labels(self, etimon=None):
        return [row['name'] for row in self.row_types() if row['allow_add'] and not row['is_etymon']]

    def add_row(self, etimon, label, text, *, actor=None):
        with self.transaction(write=True):
            rows = [dict(row) for row in self.connection.execute(
                'SELECT * FROM row_metadata WHERE etimon_number=? ORDER BY sheet_row', (etimon,))]
            if not any(row['trash_id'] is None for row in rows):
                raise ValueError('This etymon does not exist.')
            row_type = next((item for item in self.row_types() if item['name']==label and item['allow_add'] and not item['is_etymon']), None)
            if row_type is None:
                raise ValueError('Choose an addable non-etymon row type.')
            same = [row for row in rows if row['row_type_id']==row_type['id']]
            number = max((row['label_number'] for row in same), default=0)+1
            if same:
                position = max(row['sheet_row'] for row in same)+1
            else:
                priorities = {item['id']: item['display_order'] for item in self.row_types()}
                following = [row['sheet_row'] for row in rows if priorities[row['row_type_id']]>row_type['display_order']]
                position = min(following) if following else rows[-1]['sheet_row']+1
            result = self._insert_row(etimon,row_type,number,position,text)
            row = self._row_snapshot(etimon,row_type['name'],number)
            initial = row['cells'][0]
            self._record_edit('add_row',actor,etimon,row=row['rows'][0],after=row,
                              column=initial['column_id'],cell=initial['id'],column_name=initial['column'])
            return result

    def add_etymon(self, text, *, actor=None):
        with self.transaction(write=True):
            etimon = self.connection.execute('SELECT coalesce(max(id),0)+1 FROM etymons').fetchone()[0]
            position = self.connection.execute('SELECT coalesce(max(sheet_row),1)+1 FROM row_metadata').fetchone()[0]
            source_marker = self.connection.execute('SELECT max(source_row) FROM etymons').fetchone()[0]
            if source_marker:
                from excel_rows import RowInsertion
                added = [row[0] for row in self.connection.execute('SELECT sheet_row FROM row_metadata WHERE source_row IS NULL')]
                position = max(position, RowInsertion(added,self.metadata['sheet_name']).number(source_marker)+1)
            row_type = next((item for item in self.row_types() if item['is_etymon']), None)
            if row_type is None:
                raise ValueError('The collection has no etymon row type.')
            self.connection.execute('INSERT INTO etymons(id) VALUES (?)', (etimon,))
            result = self._insert_row(etimon,row_type,1,position,text)
            row = self._row_snapshot(etimon,row_type['name'],1)
            initial = row['cells'][0]
            self._record_edit('add_etymon',actor,etimon,row=row['rows'][0],after=row,
                              column=initial['column_id'],cell=initial['id'],column_name=initial['column'])
            return result

    def _map_column(self, column_id):
        definition = self.connection.execute('SELECT * FROM column_definitions WHERE id=?', (column_id,)).fetchone()
        if definition is None:
            raise ValueError('Unknown collection column.')
        if definition['sheet_column'] is None:
            position = self.connection.execute('SELECT coalesce(max(sheet_column),1)+1 FROM column_definitions').fetchone()[0]
            self.connection.execute('UPDATE column_definitions SET sheet_column=? WHERE id=?', (position,column_id))
            self._empty_backgrounds = None

    def _insert_row(self, etimon, row_type, number, position, text):
        if not isinstance(text,str) or not text.strip():
            raise ValueError('Enter text before creating an entry.')
        html, plaintext = render_delta([{'insert':text+'\n'}])
        donor = self.connection.execute('''SELECT * FROM row_metadata WHERE row_type_id=?
            ORDER BY etimon_number=? DESC,sheet_row DESC LIMIT 1''', (row_type['id'],etimon)).fetchone()
        style_row = (donor['source_row'] or donor['style_row']) if donor else None
        color = row_type['default_background']
        if color and not re.fullmatch(r'#[0-9a-fA-F]{6}',color):
            raise ValueError('The row type default background must be a #RRGGBB color.')
        for row in self.connection.execute('SELECT id,sheet_row FROM row_metadata WHERE sheet_row>=? ORDER BY sheet_row DESC',(position,)).fetchall():
            self.connection.execute('UPDATE row_metadata SET sheet_row=? WHERE id=?',(row['sheet_row']+1,row['id']))
        cursor = self.connection.execute('''INSERT INTO row_metadata
            (etimon_number,row_type_id,label,label_number,sheet_row,background_color,style_row)
            VALUES (?,?,?,?,?,?,?)''',(etimon,row_type['id'],row_type['name'],number,position,color,style_row))
        column = self.initial_column()
        self._map_column(column['id'])
        self.connection.execute('''INSERT INTO cells
            (row_id,column_id,content,plaintext_content,nodiacritics_plaintext,background_color,revision)
            VALUES (?,?,?,?,?,?,1)''', (cursor.lastrowid,column['id'],html,plaintext,remove_diacritics(plaintext),color))
        self._empty_backgrounds = None
        return {'etimon':etimon,'label':row_type['name'],'label_number':number}

    def choices(self, field, preferred=()):
        if field=='column':
            return [item['name'] for item in self.column_definitions()]
        if field=='label':
            labels = [item['name'] for item in self.row_types()]
            labels.extend(row[0] for row in self.connection.execute('SELECT DISTINCT label FROM row_metadata WHERE trash_id IS NULL') if row[0] not in labels)
            return labels
        raise ValueError('Unknown filter field.')

    def entries(self):
        result = {}
        for (number,) in self.connection.execute('SELECT DISTINCT etimon_number FROM row_metadata WHERE trash_id IS NULL ORDER BY etimon_number'):
            rows = self.connection.execute('''SELECT "column", plaintext_content, label, is_etymon FROM cell_records
                WHERE etimon_number=? AND ''' + ACTIVE_CELL_SQL + ' ORDER BY label_number, id', (number,)).fetchall()
            markers = [row for row in rows if row['is_etymon']]
            form, language = 'No language form', ''
            for definition in sorted((item for item in self.column_definitions() if item['title_priority'] is not None), key=lambda item:(item['title_priority'],item['id'])):
                candidate = definition['name']
                text = next((row['plaintext_content'].strip() for row in markers
                             if row['column'] == candidate and row['plaintext_content'].strip()), '')
                if text:
                    first_line = next(line.strip() for line in text.splitlines() if line.strip())
                    form = re.split(r',|\s{2,}', first_line, maxsplit=1)[0].strip() or first_line
                    language = candidate
                    break
            result[number] = {'number': number, 'form': form, 'language': language}
        return result

    def matching_numbers(self, query, labels=(), columns=()):
        sql = 'SELECT DISTINCT etimon_number FROM cell_records WHERE ' + ACTIVE_CELL_SQL + ' AND instr(search_fold(nodiacritics_plaintext), ?) > 0'
        values = [remove_diacritics(query).upper()]
        for field, selected in (('label', labels), ('column', columns)):
            if selected:
                sql += f' AND "{field}" IN ({",".join("?" for _ in selected)})'
                values.extend(selected)
        return tuple(row[0] for row in self.connection.execute(sql + ' ORDER BY etimon_number', values))

    def cell(self, key):
        with self._lock:
            row = self.connection.execute(f'SELECT * FROM cell_records WHERE {KEY_SQL} AND {ACTIVE_CELL_SQL}',key).fetchone()
            metadata = self.connection.execute('''SELECT id,generation FROM row_metadata
                WHERE etimon_number=? AND label=? AND label_number=? AND trash_id IS NULL''',key[:3]).fetchone()
            column = self.connection.execute('SELECT id FROM column_definitions WHERE name=?',(key[3],)).fetchone()
            result = dict(row) if row else {'id':None,'revision':0,'line_height':None}
            result.update(generation=metadata['generation'] if metadata else None,
                          row_id=metadata['id'] if metadata else None, column_id=column['id'] if column else None)
            return result

    def cell_key(self, row_id, column_id):
        with self._lock:
            row = self.connection.execute('''SELECT r.etimon_number,r.label,r.label_number,c.name
                FROM row_metadata r CROSS JOIN column_definitions c WHERE r.id=? AND c.id=?''',(row_id,column_id)).fetchone()
            if row is None:
                raise EditConflict('This cell no longer exists. Cancel and reload.')
            return tuple(row)

    def save_cell(self, key, revision, ops, *, line_height_provided=False, line_height=None, generation=None, actor=None, lease=None):
        self.expire_edits()
        with self.transaction(write=True):
            current = self.cell(key)
            if current['generation'] is None or (generation is not None and current['generation']!=generation):
                raise EditConflict('This row was deleted or restored. Cancel and reload before editing.')
            if current['column_id'] is None:
                raise ValueError('Unknown collection column.')
            if current['revision']!=revision:
                raise EditConflict('Someone else changed this cell. Copy your draft, then cancel and reload.')
            editing = None
            if lease is not None:
                editing = self._owned_edit(lease,actor)
                if (editing['row_id'],editing['column_id']) != (current['row_id'],current['column_id']):
                    raise EditConflict('This editing record belongs to another cell. Cancel and reload.')
                initial = json.loads(editing['before_json'])
                if initial['revision'] != revision or initial['generation'] != current['generation']:
                    raise EditConflict('This cell changed. Copy your draft, then cancel and reload.')
            elif actor and actor.get('session_id'):
                raise EditConflict('Open the cell editor before saving.')
            else:
                self._assert_not_editing(current['row_id'],current['column_id'])
            height = validate_line_height(line_height if line_height_provided else current['line_height'])
            html, plaintext = render_delta(ops,line_height=height)
            self._map_column(current['column_id'])
            if current['id'] is None:
                row = self.connection.execute('SELECT source_row,background_color FROM row_metadata WHERE id=?',(current['row_id'],)).fetchone()
                self.connection.execute('''INSERT INTO cells
                    (row_id,column_id,content,plaintext_content,nodiacritics_plaintext,background_color,revision,line_height)
                    VALUES (?,?,?,?,?,?,1,?)''',(current['row_id'],current['column_id'],html,plaintext,remove_diacritics(plaintext),
                                               row['background_color'] if row['source_row'] is None else '',height))
            else:
                self.connection.execute('''UPDATE cells SET content=?,plaintext_content=?,
                    nodiacritics_plaintext=?,line_height=?,revision=revision+1 WHERE id=?''',
                    (html,plaintext,remove_diacritics(plaintext),height,current['id']))
            saved = self.cell(key)
            if editing:
                now = edit_now().isoformat()
                self.connection.execute("""UPDATE edit_history SET status='saved',finished_at=?,occurred_at=?,last_seen_at=?,
                    cell_id=?,after_json=? WHERE id=?""", (now,now,now,saved['id'],json.dumps(saved,ensure_ascii=False),editing['id']))
            else:
                self._record_edit('save_cell',actor,key[0],row={'id':saved['row_id'],'label':key[1],'label_number':key[2]},
                                  column=saved['column_id'],cell=saved['id'],column_name=key[3],before=current,after=saved)

    def _expire_edits(self):
        now = edit_now().isoformat()
        self.connection.execute("""UPDATE edit_history SET status='expired',finished_at=expires_at,occurred_at=expires_at
            WHERE status='active' AND expires_at<=?""",(now,))
        if self.session_validator is not None:
            sessions = [row[0] for row in self.connection.execute("SELECT DISTINCT editor_session_id FROM edit_history WHERE status='active'")]
            for identity in sessions:
                if not self.session_validator(identity):
                    self.connection.execute("""UPDATE edit_history SET status='revoked',finished_at=?,occurred_at=?
                        WHERE status='active' AND editor_session_id=?""",(now,now,identity))

    def expire_edits(self):
        with self.transaction(write=True):
            self._expire_edits()

    def _assert_not_editing(self, row_id, column_id):
        row = self.connection.execute("""SELECT editor_name FROM edit_history
            WHERE status='active' AND row_id=? AND column_id=? AND expires_at>?""",
            (row_id,column_id,edit_now().isoformat())).fetchone()
        if row:
            raise EditBusy(f"{row['editor_name']} is editing this cell. Please try again after they finish.")

    def _edit_warnings(self, editing):
        return [dict(row) for row in self.connection.execute("""SELECT editor_name AS name,label,label_number,
            column_name, row_id=? AS same_row FROM edit_history WHERE status='active'
            AND etimon_number=? AND id<>? AND expires_at>? ORDER BY row_id,id""",
            (editing['row_id'],editing['etimon_number'],editing['id'],edit_now().isoformat()))]

    def begin_cell_edit(self, key, revision, generation, actor, *, lease_seconds=300):
        if not actor or not actor.get('session_id'):
            raise EditConflict('Sign in before opening a cell editor.')
        self.expire_edits()
        with self.transaction(write=True):
            self._expire_edits()
            current = self.cell(key)
            if current['row_id'] is None or current['column_id'] is None or current['generation'] != generation:
                raise EditConflict('This row was deleted or restored. Reload before editing.')
            self._assert_not_editing(current['row_id'],current['column_id'])
            if current['revision'] != revision:
                raise EditConflict('Someone else changed this cell. Reload before editing.')
            now = edit_now()
            lease = token_urlsafe(32)
            identifier = self._record_edit('save_cell',actor,key[0],
                row={'id':current['row_id'],'label':key[1],'label_number':key[2]},
                column=current['column_id'],cell=current['id'],column_name=key[3],before=current)
            self.connection.execute("""UPDATE edit_history SET status='active',occurred_at=?,started_at=?,last_seen_at=?,
                expires_at=?,finished_at=NULL,lease_hash=? WHERE id=?""",
                (now.isoformat(),now.isoformat(),now.isoformat(),(now+timedelta(seconds=lease_seconds)).isoformat(),
                 sha256(lease.encode()).hexdigest(),identifier))
            editing = self.connection.execute('SELECT * FROM edit_history WHERE id=?',(identifier,)).fetchone()
            return {'lease':lease,'edit_id':identifier,'html':current.get('content',''),
                    'line_height':current['line_height'],'expires_at':editing['expires_at'],
                    'warnings':self._edit_warnings(editing)}

    def _owned_edit(self, lease, actor, *, require_active=True):
        if not isinstance(lease,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',lease) or not actor:
            raise EditConflict('This editing session expired. Copy your draft, then cancel and reload.')
        editing = self.connection.execute('SELECT * FROM edit_history WHERE lease_hash=?',
                                         (sha256(lease.encode()).hexdigest(),)).fetchone()
        if editing is None or editing['editor_session_id'] != actor.get('session_id'):
            raise EditConflict('This editing session expired. Copy your draft, then cancel and reload.')
        if require_active and (editing['status']!='active' or editing['expires_at']<=edit_now().isoformat()):
            raise EditConflict('Your editing lock expired or ended. Copy your draft, then cancel and reload.')
        return editing

    def heartbeat_cell_edit(self, lease, actor, *, lease_seconds=300):
        self.expire_edits()
        with self.transaction(write=True):
            editing = self._owned_edit(lease,actor)
            now = edit_now()
            expires = (now+timedelta(seconds=lease_seconds)).isoformat()
            self.connection.execute('UPDATE edit_history SET last_seen_at=?,expires_at=? WHERE id=?',
                                    (now.isoformat(),expires,editing['id']))
            return {'expires_at':expires,'warnings':self._edit_warnings(editing)}

    def finish_cell_edit(self, lease, actor, outcome):
        if outcome not in ('cancelled','unchanged'):
            raise ValueError('Choose Cancel or unchanged Close.')
        self.expire_edits()
        with self.transaction(write=True):
            editing = self._owned_edit(lease,actor,require_active=False)
            if editing['status']=='active':
                now = edit_now().isoformat()
                self.connection.execute("""UPDATE edit_history SET status=?,finished_at=?,occurred_at=?,last_seen_at=?,
                    after_json=? WHERE id=?""",(outcome,now,now,now,
                    editing['before_json'] if outcome=='unchanged' else None,editing['id']))
                return {'status':outcome}
            return {'status':editing['status']}

    def deletion_version(self, etimon, label=None, label_number=None):
        """Fingerprint the active target, so a stale page cannot discard edits."""
        scope, values = 'etimon_number=?', [etimon]
        if label is not None:
            scope += ' AND label=? AND label_number=?'
            values.extend((label, label_number))
        rows = self.connection.execute('SELECT id, generation FROM row_metadata WHERE '
                                       + scope + ' AND trash_id IS NULL ORDER BY id', values).fetchall()
        if not rows:
            raise ValueError('This item no longer exists in the collection.')
        cells = [tuple(cell) for cell in self.connection.execute('SELECT id, revision FROM cell_records WHERE '
                  + scope + ' AND ' + ACTIVE_CELL_SQL + ' ORDER BY id', values)]
        identity = [tuple(row) for row in rows]
        return sha256(json.dumps([identity, cells]).encode()).hexdigest()

    def delete_row(self, etimon, label, label_number, *, expected=None, actor=None):
        row_type = self.row_type(etimon,label,label_number)
        if row_type and row_type['is_etymon']:
            raise ValueError('Use Delete etymon to remove an etymon and its rows.')
        return self._trash(etimon, label, label_number, expected, actor)

    def delete_etymon(self, etimon, *, expected=None, actor=None):
        return self._trash(etimon, None, None, expected, actor)

    def _trash(self, etimon, label, label_number, expected, actor):
        self.expire_edits()
        with self.transaction(write=True):
            version = self.deletion_version(etimon, label, label_number)
            if expected is not None and expected != version:
                raise EditConflict('This item changed since the page loaded. Reload and review it before deleting.')
            sql, values = "SELECT editor_name FROM edit_history WHERE status='active' AND expires_at>? AND etimon_number=?", [edit_now().isoformat(),etimon]
            if label is not None:
                sql += ' AND row_id=(SELECT id FROM row_metadata WHERE etimon_number=? AND label=? AND label_number=?)'
                values.extend((etimon,label,label_number))
            names = sorted({row[0] for row in self.connection.execute(sql,values)})
            if names:
                target = 'etymon' if label is None else 'row'
                verb = 'is' if len(names)==1 else 'are'
                raise EditBusy(f"{', '.join(names)} {verb} editing a cell in this {target}. You cannot delete it until they finish.")
            before = self._row_snapshot(etimon,label,label_number)
            title = self.entries()[etimon]['form']
            cursor = self.connection.execute('''INSERT INTO trash
                (kind, etimon_number, label, label_number, title, deleted_at) VALUES (?, ?, ?, ?, ?, ?)''',
                ('etymon' if label is None else 'row', etimon, label, label_number, title,
                 datetime.now(timezone.utc).isoformat()))
            trash_id = cursor.lastrowid
            sql = 'UPDATE row_metadata SET trash_id=?, generation=generation+1 WHERE etimon_number=? AND trash_id IS NULL'
            values = [trash_id, etimon]
            if label is not None:
                sql += ' AND label=? AND label_number=?'
                values.extend((label, label_number))
            self.connection.execute(sql, values)
            self._record_edit('delete_etymon' if label is None else 'delete_row',actor,etimon,
                              row=before['rows'][0] if label is not None else None,
                              trash_id=trash_id,before=before)
            self._empty_backgrounds = None
            return trash_id

    def list_trash(self):
        """Local administrative recovery; no web restore endpoint is exposed."""
        with self.transaction():
            return [dict(row) for row in self.connection.execute('''SELECT trash.*,
                (SELECT count(*) FROM row_metadata WHERE trash_id=trash.id) AS row_count
                FROM trash WHERE restored_at IS NULL ORDER BY id''')]

    def restore_trash(self, trash_id, *, actor=None):
        with self.transaction(write=True):
            entry = self.connection.execute('SELECT * FROM trash WHERE id=? AND restored_at IS NULL', (trash_id,)).fetchone()
            if entry is None:
                raise ValueError('No unrestored Trash entry has that ID.')
            if entry['kind'] == 'row' and not self.connection.execute('''SELECT 1 FROM row_metadata
                WHERE etimon_number=? AND trash_id IS NULL''', (entry['etimon_number'],)).fetchone():
                raise ValueError('Restore the containing etymon first, then restore this row.')
            self.connection.execute('UPDATE row_metadata SET trash_id=NULL, generation=generation+1 WHERE trash_id=?', (trash_id,))
            self.connection.execute('UPDATE trash SET restored_at=? WHERE id=?',
                                    (datetime.now(timezone.utc).isoformat(), trash_id))
            self._record_edit('restore_trash',actor,entry['etimon_number'],trash_id=trash_id,
                              after=self._row_snapshot(entry['etimon_number'],entry['label'],entry['label_number']))
            self._empty_backgrounds = None
            return dict(entry)

    def _row_snapshot(self, etimon, label=None, label_number=None):
        scope, values = 'etimon_number=? AND trash_id IS NULL', [etimon]
        if label is not None:
            scope += ' AND label=? AND label_number=?'
            values.extend((label,label_number))
        rows = [dict(row) for row in self.connection.execute('SELECT * FROM row_metadata WHERE '+scope+' ORDER BY id',values)]
        ids = {row['id'] for row in rows}
        return {'rows':rows, 'cells':[cell for cell in self._records(etimon) if cell['row_id'] in ids]}

    def _record_edit(self, action, actor, etimon, *, row=None, column=None, cell=None,
                     column_name=None, trash_id=None, before=None, after=None):
        # Local Python/CLI writes are explicitly attributed too. HTTP handlers
        # supply a server-resolved actor, never a name supplied in a save body.
        actor = actor or {'name':'Local administrator', 'session_id':None}
        row = row or {}
        cursor = self.connection.execute('''INSERT INTO edit_history
            (action,editor_name,editor_session_id,occurred_at,etimon_number,row_id,column_id,cell_id,
             label,label_number,column_name,trash_id,before_json,after_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (action,actor['name'],actor.get('session_id'),datetime.now(timezone.utc).isoformat(),etimon,
             row.get('id'),column,cell,row.get('label'),row.get('label_number'),column_name,trash_id,
             json.dumps(before,ensure_ascii=False) if before is not None else None,
             json.dumps(after,ensure_ascii=False) if after is not None else None))
        self.connection.execute('UPDATE edit_history SET finished_at=occurred_at WHERE id=?',(cursor.lastrowid,))
        return cursor.lastrowid

    def edit_history(self, etimon=None, limit=100, *, include_sessions=False):
        if type(limit) is not int or not 1 <= limit <= 10000:
            raise ValueError('History limit must be 1–10000.')
        self.expire_edits()
        with self.transaction():
            scope = ' WHERE 1=1' if include_sessions else " WHERE status='saved'"
            values = []
            if etimon is not None:
                scope += ' AND etimon_number=?'
                values.append(etimon)
            return [dict(row) for row in self.connection.execute(
                'SELECT * FROM edit_history'+scope+' ORDER BY occurred_at DESC,id DESC LIMIT ?', [*values,limit])]

    def export_snapshot(self):
        with self.transaction():
            dataset = dict(self.connection.execute('SELECT * FROM dataset').fetchone())
            return {
                'dataset': dataset,
                'columns': [dict(row) for row in self.connection.execute('SELECT * FROM column_definitions WHERE sheet_column IS NOT NULL ORDER BY sheet_column')],
                'rows': [dict(row) for row in self.connection.execute('SELECT * FROM row_metadata ORDER BY sheet_row')],
                'cells': self._records(),
                'row_types': self.row_types(),
                'etymons': [dict(row) for row in self.connection.execute('SELECT * FROM etymons ORDER BY id')],
                'trashed_etymons': [row[0] for row in self.connection.execute(
                    "SELECT etimon_number FROM trash WHERE kind='etymon' AND restored_at IS NULL")],
            }
