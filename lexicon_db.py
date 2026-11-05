"""SQLite source of truth for one imported worksheet and its export template."""

from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
import sqlite3
from threading import RLock
from uuid import uuid4
from weakref import finalize

import pandas as pd
from openpyxl import load_workbook

from cell_editing import render_delta, validate_line_height
from df_search import COLUMN_ORDER, LABEL_ORDER
from text_normalization import remove_diacritics


FRAME_COLUMNS = (
    'etimon_number', 'column', 'label', 'label_number', 'content',
    'plaintext_content', 'nodiacritics_plaintext', 'background_color',
)
KEY_SQL = 'etimon_number=? AND label=? AND label_number=? AND "column"=?'
_DEFAULT_ROW_COLORS = object()
ACTIVE_CELL_SQL = '''EXISTS (SELECT 1 FROM row_metadata r
    WHERE r.etimon_number=cells.etimon_number AND r.label=cells.label
    AND r.label_number=cells.label_number AND r.trash_id IS NULL)'''


def default_database_path(excel_path, sheet_name=None):
    suffix = f'.{sha256(sheet_name.encode()).hexdigest()[:10]}' if sheet_name is not None else ''
    path = Path(excel_path)
    return path.with_name(f'{path.name}{suffix}.sqlite3')


class EditConflict(ValueError):
    pass


class LexiconDB:
    def __init__(self, database_path, excel_path=None, sheet_name=None, *, loader=None, row_colors=_DEFAULT_ROW_COLORS):
        if row_colors is _DEFAULT_ROW_COLORS:
            from config import ROW_BACKGROUND_COLORS
            row_colors = ROW_BACKGROUND_COLORS
        if not isinstance(row_colors, dict) or set(row_colors) != set(LABEL_ORDER):
            raise ValueError('ROW_BACKGROUND_COLORS must define all four canonical row labels.')
        self.row_colors = {}
        for label, color in row_colors.items():
            if not isinstance(color, str) or not re.fullmatch(r'#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?', color):
                raise ValueError('ROW_BACKGROUND_COLORS values must be #RGB or #RRGGBB hex colors.')
            if len(color) == 4:
                color = '#' + ''.join(character * 2 for character in color[1:])
            self.row_colors[self._label_kind(label)] = color.upper()
        self.path = str(database_path)
        if self.path != ':memory:':
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._empty_backgrounds = None
        self._empty_background_rows = None
        self.connection = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None, timeout=10)
        self.connection.row_factory = sqlite3.Row
        self._finalizer = finalize(self, self.connection.close)
        self.connection.execute('PRAGMA foreign_keys=ON')
        self.connection.create_function('search_fold', 1, lambda text: text.upper(), deterministic=True)
        try:
            exists = self.connection.execute("SELECT 1 FROM sqlite_master WHERE name='dataset'").fetchone()
            if not exists:
                if self.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchone():
                    raise ValueError('The selected database is not a Parallel Words database.')
                if excel_path is None:
                    raise ValueError('A workbook is required to initialize a new database.')
                if loader is None:
                    from extract_sheet import excel_to_dataframe
                    loader = excel_to_dataframe
                frame = loader(str(excel_path), sheet_name)
                self._initialize(frame, Path(excel_path))
            metadata = self.connection.execute(
                'SELECT id, source_path, source_name, sheet_name, schema_version FROM dataset'
            ).fetchone()
            if metadata is None:
                raise ValueError('The selected database has no imported dataset.')
            self.metadata = dict(metadata)
            if self.metadata['schema_version'] == 1:
                with self.transaction(write=True):
                    # Recheck under the write lock in case another opener migrated.
                    if self.connection.execute('SELECT schema_version FROM dataset').fetchone()[0] == 1:
                        self.connection.execute('ALTER TABLE row_metadata ADD COLUMN source_row INTEGER')
                        self.connection.execute('ALTER TABLE row_metadata ADD COLUMN style_row INTEGER')
                        self.connection.execute('UPDATE row_metadata SET source_row=sheet_row')
                        self.connection.execute('UPDATE dataset SET schema_version=2')
                self.metadata['schema_version'] = 2
            if self.metadata['schema_version'] == 2:
                with self.transaction(write=True):
                    if self.connection.execute('SELECT schema_version FROM dataset').fetchone()[0] == 2:
                        self.connection.execute('''CREATE TABLE trash (
                            id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
                            etimon_number INTEGER NOT NULL, label TEXT, label_number INTEGER,
                            title TEXT NOT NULL, deleted_at TEXT NOT NULL, restored_at TEXT)''')
                        self.connection.execute('ALTER TABLE row_metadata ADD COLUMN trash_id INTEGER REFERENCES trash(id)')
                        self.connection.execute('ALTER TABLE row_metadata ADD COLUMN generation INTEGER NOT NULL DEFAULT 0')
                        self.connection.execute('UPDATE dataset SET schema_version=3')
                self.metadata['schema_version'] = 3
            if self.metadata['schema_version'] != 3:
                raise ValueError('Unsupported Parallel Words database schema version.')
            if sheet_name is not None and sheet_name != self.metadata['sheet_name']:
                raise ValueError('The selected database contains a different worksheet. Choose another database.')
        except BaseException:
            self.connection.close()
            raise

    def _initialize(self, frame, source):
        template = source.read_bytes()
        schema = '''
            BEGIN IMMEDIATE;
            CREATE TABLE dataset (
                id TEXT PRIMARY KEY, schema_version INTEGER NOT NULL,
                source_path TEXT NOT NULL, source_name TEXT NOT NULL,
                sheet_name TEXT NOT NULL, workbook BLOB NOT NULL
            );
            CREATE TABLE sheet_columns (name TEXT PRIMARY KEY, sheet_column INTEGER NOT NULL UNIQUE);
            CREATE TABLE row_metadata (
                id INTEGER PRIMARY KEY, etimon_number INTEGER NOT NULL,
                label TEXT NOT NULL, label_number INTEGER NOT NULL,
                sheet_row INTEGER NOT NULL UNIQUE, background_color TEXT NOT NULL DEFAULT '',
                source_row INTEGER, style_row INTEGER,
                UNIQUE(etimon_number, label, label_number)
            );
            CREATE TABLE cells (
                id INTEGER PRIMARY KEY,
                etimon_number INTEGER NOT NULL, "column" TEXT NOT NULL,
                label TEXT NOT NULL, label_number INTEGER NOT NULL,
                content TEXT NOT NULL, plaintext_content TEXT NOT NULL,
                nodiacritics_plaintext TEXT NOT NULL, background_color TEXT NOT NULL DEFAULT '',
                revision INTEGER NOT NULL DEFAULT 0, line_height REAL,
                UNIQUE(etimon_number, label, label_number, "column"),
                FOREIGN KEY(etimon_number, label, label_number)
                    REFERENCES row_metadata(etimon_number, label, label_number),
                FOREIGN KEY("column") REFERENCES sheet_columns(name)
            );
            CREATE INDEX cells_etymon ON cells(etimon_number);
        '''
        try:
            self.connection.executescript(schema)
            self.connection.execute('INSERT INTO dataset VALUES (?, 2, ?, ?, ?, ?)', (
                str(uuid4()), str(source.resolve()), source.name, frame.attrs['sheet_name'], template,
            ))
            self.connection.executemany('INSERT INTO sheet_columns VALUES (?, ?)',
                                        frame.attrs['column_positions'].items())
            backgrounds = frame.attrs.get('label_backgrounds', {})
            self.connection.executemany('''INSERT INTO row_metadata
                (etimon_number, label, label_number, sheet_row, background_color, source_row) VALUES (?, ?, ?, ?, ?, ?)''', (
                (*key, position, backgrounds.get(key, ''), position)
                for key, position in frame.attrs['row_positions'].items()
            ))
            self.connection.executemany('''INSERT INTO cells
                (etimon_number, "column", label, label_number, content, plaintext_content,
                 nodiacritics_plaintext, background_color) VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                frame.loc[:, list(FRAME_COLUMNS)].itertuples(index=False, name=None))
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise

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
        sql = 'SELECT * FROM cells WHERE ' + ACTIVE_CELL_SQL
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
            rows = self.connection.execute('SELECT * FROM row_metadata WHERE trash_id IS NULL').fetchall()
            frame.attrs['label_backgrounds'] = {
                (row['etimon_number'], row['label'], row['label_number']): row['background_color']
                for row in rows if row['background_color']
            }
            frame.attrs['cell_line_heights'] = {
                (row['etimon_number'], row['label'], row['label_number'], row['column']): row['line_height']
                for row in records if row['line_height'] is not None
            }
            identities = tuple((row['id'], row['sheet_row']) for row in rows)
            if identities != self._empty_background_rows:
                self._empty_backgrounds = None
            frame.attrs['empty_cell_backgrounds'] = self._original_empty_backgrounds().copy()
            self._empty_background_rows = identities
            return frame

    def _original_empty_backgrounds(self):
        """Keep a formerly empty cell's fill when it gains content.

        Old databases omit blank cells entirely. Recover their presentation
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
                columns = dict(self.connection.execute('SELECT name, sheet_column FROM sheet_columns'))
                for name in COLUMN_ORDER:
                    columns.setdefault(name, None)
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
        """Three allowed types, retaining existing spelling and spacing."""
        rows = self.connection.execute('''SELECT label FROM row_metadata
            ORDER BY trash_id IS NULL DESC, etimon_number=? DESC, sheet_row''', (etimon,)).fetchall()
        return [next((row['label'] for row in rows if self._label_kind(row['label']) == self._label_kind(label)), label)
                for label in LABEL_ORDER[1:]]

    def add_row(self, etimon, label, text):
        with self.transaction(write=True):
            rows = [dict(row) for row in self.connection.execute(
                'SELECT * FROM row_metadata WHERE etimon_number=? ORDER BY sheet_row', (etimon,))]
            if not any(row['trash_id'] is None for row in rows):
                raise ValueError('This etymon does not exist.')
            if label not in self.row_labels(etimon):
                raise ValueError('Choose one of the three non-etymon row types.')
            same = [row for row in rows if row['label'] == label]
            number = max((row['label_number'] for row in same), default=0) + 1
            if same:
                position = max(row['sheet_row'] for row in same) + 1
            else:
                priority = {self._label_kind(value): index for index, value in enumerate(LABEL_ORDER)}
                following = [row['sheet_row'] for row in rows
                             if priority.get(self._label_kind(row['label']), len(priority)) > priority[self._label_kind(label)]]
                position = min(following) if following else rows[-1]['sheet_row'] + 1
            return self._insert_row(etimon, label, number, position, text)

    def add_etymon(self, text):
        with self.transaction(write=True):
            etimon = self.connection.execute('SELECT coalesce(max(etimon_number),0)+1 FROM row_metadata').fetchone()[0]
            position = self.connection.execute('SELECT coalesce(max(sheet_row),1)+1 FROM row_metadata').fetchone()[0]
            label = next((row[0] for row in self.connection.execute('SELECT label FROM row_metadata ORDER BY sheet_row')
                          if re.match(r'^\s*ETIMON\s*/', row[0], re.IGNORECASE)), LABEL_ORDER[0])
            return self._insert_row(etimon, label, 1, position, text)

    def _insert_row(self, etimon, label, number, position, text):
        if not isinstance(text, str) or not text.strip():
            raise ValueError('Enter French text before creating an entry.')
        html, plaintext = render_delta([{'insert': text + '\n'}])
        donor = self.connection.execute('''SELECT * FROM row_metadata WHERE label=?
            ORDER BY etimon_number=? DESC, sheet_row DESC LIMIT 1''', (label, etimon)).fetchone()
        style_row = (donor['source_row'] or donor['style_row']) if donor else None
        color = self.row_colors[self._label_kind(label)]
        # Descending updates avoid transient collisions with the UNIQUE index.
        for row in self.connection.execute('SELECT id, sheet_row FROM row_metadata WHERE sheet_row>=? ORDER BY sheet_row DESC', (position,)).fetchall():
            self.connection.execute('UPDATE row_metadata SET sheet_row=? WHERE id=?', (row['sheet_row'] + 1, row['id']))
        self.connection.execute('''INSERT INTO row_metadata
            (etimon_number, label, label_number, sheet_row, background_color, style_row)
            VALUES (?, ?, ?, ?, ?, ?)''', (etimon, label, number, position, color, style_row))
        french = COLUMN_ORDER[0]
        if not self.connection.execute('SELECT 1 FROM sheet_columns WHERE name=?', (french,)).fetchone():
            column = self.connection.execute('SELECT coalesce(max(sheet_column),1)+1 FROM sheet_columns').fetchone()[0]
            self.connection.execute('INSERT INTO sheet_columns VALUES (?, ?)', (french, column))
        self.connection.execute('''INSERT INTO cells
            (etimon_number, label, label_number, "column", content, plaintext_content, nodiacritics_plaintext, background_color, revision)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)''', (etimon, label, number, french, html, plaintext, remove_diacritics(plaintext), color))
        self._empty_backgrounds = None
        return {'etimon': etimon, 'label': label, 'label_number': number}

    def choices(self, field, preferred):
        if field not in ('column', 'label'):
            raise ValueError('Unknown filter field.')
        values = {row[0] for row in self.connection.execute(f'SELECT DISTINCT "{field}" FROM cells WHERE {ACTIVE_CELL_SQL}')}
        return [value for value in preferred if value in values] + sorted(values - set(preferred))

    def entries(self):
        result = {}
        for (number,) in self.connection.execute('SELECT DISTINCT etimon_number FROM row_metadata WHERE trash_id IS NULL ORDER BY etimon_number'):
            rows = self.connection.execute('''SELECT "column", plaintext_content, label FROM cells
                WHERE etimon_number=? AND ''' + ACTIVE_CELL_SQL + ' ORDER BY label_number, id', (number,)).fetchall()
            markers = [row for row in rows if re.match(r'^\s*ETIMON\s*/', row['label'], re.IGNORECASE)]
            form, language = 'No language form', ''
            for candidate in COLUMN_ORDER[:6]:
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
        sql = 'SELECT DISTINCT etimon_number FROM cells WHERE ' + ACTIVE_CELL_SQL + ' AND instr(search_fold(nodiacritics_plaintext), ?) > 0'
        values = [remove_diacritics(query).upper()]
        for field, selected in (('label', labels), ('column', columns)):
            if selected:
                sql += f' AND "{field}" IN ({",".join("?" for _ in selected)})'
                values.extend(selected)
        return tuple(row[0] for row in self.connection.execute(sql + ' ORDER BY etimon_number', values))

    def cell(self, key):
        row = self.connection.execute(f'SELECT * FROM cells WHERE {KEY_SQL} AND {ACTIVE_CELL_SQL}', key).fetchone()
        metadata = self.connection.execute('''SELECT generation FROM row_metadata
            WHERE etimon_number=? AND label=? AND label_number=? AND trash_id IS NULL''', key[:3]).fetchone()
        result = dict(row) if row else {'id': None, 'revision': 0, 'line_height': None}
        result['generation'] = metadata[0] if metadata else None
        return result

    def save_cell(self, key, revision, ops, *, line_height_provided=False, line_height=None, generation=None):
        with self.transaction(write=True):
            current = self.cell(key)
            if current['generation'] is None or (generation is not None and current['generation'] != generation):
                raise EditConflict('This row was deleted or restored. Cancel and reload before editing.')
            if current['revision'] != revision:
                raise EditConflict('Someone else changed this cell. Copy your draft, then cancel and reload.')
            row = self.connection.execute('''SELECT source_row, background_color FROM row_metadata
                WHERE etimon_number=? AND label=? AND label_number=?''', key[:3]).fetchone()
            if row is None:
                raise ValueError('This worksheet row does not exist.')
            height = validate_line_height(line_height if line_height_provided else current['line_height'])
            html, plaintext = render_delta(ops, line_height=height)
            if not self.connection.execute('SELECT 1 FROM sheet_columns WHERE name=?', (key[3],)).fetchone():
                if key[3] not in COLUMN_ORDER:
                    raise ValueError('Unknown worksheet column.')
                position = self.connection.execute('SELECT coalesce(max(sheet_column),1)+1 FROM sheet_columns').fetchone()[0]
                self.connection.execute('INSERT INTO sheet_columns VALUES (?, ?)', (key[3], position))
            if current['id'] is None:
                self.connection.execute('''INSERT INTO cells
                    (etimon_number, label, label_number, "column", content, plaintext_content,
                     nodiacritics_plaintext, background_color, revision, line_height) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)''',
                    (*key, html, plaintext, remove_diacritics(plaintext),
                     row['background_color'] if row['source_row'] is None else '', height))
            else:
                self.connection.execute('''UPDATE cells SET content=?, plaintext_content=?,
                    nodiacritics_plaintext=?, line_height=?, revision=revision+1 WHERE id=?''',
                    (html, plaintext, remove_diacritics(plaintext), height, current['id']))

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
        cells = [tuple(cell) for cell in self.connection.execute('SELECT id, revision FROM cells WHERE '
                  + scope + ' AND ' + ACTIVE_CELL_SQL + ' ORDER BY id', values)]
        identity = [tuple(row) for row in rows]
        return sha256(json.dumps([identity, cells]).encode()).hexdigest()

    def delete_row(self, etimon, label, label_number, *, expected=None):
        if self._label_kind(label) == self._label_kind(LABEL_ORDER[0]):
            raise ValueError('Use Delete etymon to remove an etymon and its rows.')
        return self._trash(etimon, label, label_number, expected)

    def delete_etymon(self, etimon, *, expected=None):
        return self._trash(etimon, None, None, expected)

    def _trash(self, etimon, label, label_number, expected):
        with self.transaction(write=True):
            version = self.deletion_version(etimon, label, label_number)
            if expected is not None and expected != version:
                raise EditConflict('This item changed since the page loaded. Reload and review it before deleting.')
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
            self._empty_backgrounds = None
            return trash_id

    def list_trash(self):
        """Local administrative recovery; no web restore endpoint is exposed."""
        with self.transaction():
            return [dict(row) for row in self.connection.execute('''SELECT trash.*,
                (SELECT count(*) FROM row_metadata WHERE trash_id=trash.id) AS row_count
                FROM trash WHERE restored_at IS NULL ORDER BY id''')]

    def restore_trash(self, trash_id):
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
            self._empty_backgrounds = None
            return dict(entry)

    def export_snapshot(self):
        with self.transaction():
            dataset = dict(self.connection.execute('SELECT * FROM dataset').fetchone())
            return {
                'dataset': dataset,
                'columns': [dict(row) for row in self.connection.execute('SELECT * FROM sheet_columns ORDER BY sheet_column')],
                'rows': [dict(row) for row in self.connection.execute('SELECT * FROM row_metadata ORDER BY sheet_row')],
                'cells': self._records(),
                'trashed_etymons': [row[0] for row in self.connection.execute(
                    "SELECT etimon_number FROM trash WHERE kind='etymon' AND restored_at IS NULL")],
            }
