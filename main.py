"""Flask interface for a persistent SQLite lexicon imported from Excel.

Run with .venv/bin/python main.py [workbook.xlsx] [--sheet NAME], then open
http://127.0.0.1:5000.
"""

import argparse
from functools import wraps
from ipaddress import ip_address
import json
import os
from pathlib import Path
import re
from secrets import compare_digest, token_hex
import sqlite3
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

from flask import Flask, abort, render_template, request, send_file, session
from itsdangerous import BadSignature, URLSafeSerializer
from openpyxl.utils.exceptions import InvalidFileException
from waitress import serve

from df_search import COLUMN_ORDER, LABEL_ORDER, get_etimon
from extract_sheet import excel_to_dataframe
from lexicon_db import EditConflict, LexiconDB, default_database_path
from search_highlighting import highlight_content


DEFAULT_EXCEL_PATH = Path(__file__).parent / 'db' / 'example.xlsx'


def _filter_values(values):
    """Canonicalize selections, including single values from older sessions."""
    if isinstance(values, str):
        values = [values]
    return sorted(set(value for value in values if value))


def create_app(excel_path=DEFAULT_EXCEL_PATH, sheet_name=None, test_config=None, database_path=None):
    """Open a database, importing the selected workbook only on first use."""
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get('FLASK_SECRET_KEY') or token_hex(32),
        EXCEL_PATH=str(excel_path),
        SHEET_NAME=sheet_name,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
    )
    app.config.from_pyfile('config.py')
    if test_config:
        app.config.update(test_config)
    if not re.fullmatch(r'#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?', app.config['SEARCH_HIGHLIGHT_COLOR']):
        raise ValueError('SEARCH_HIGHLIGHT_COLOR must be a #RGB or #RRGGBB hex color.')

    path = database_path or app.config.get('DATABASE_PATH')
    if path is None:
        path = ':memory:' if app.testing else default_database_path(app.config['EXCEL_PATH'], app.config['SHEET_NAME'])
    store = LexiconDB(path, app.config['EXCEL_PATH'], app.config['SHEET_NAME'],
                      loader=excel_to_dataframe, row_colors=app.config['ROW_BACKGROUND_COLORS'])
    app.config['DATABASE_PATH'] = str(path)
    app.config.setdefault('EXPORT_DIRECTORY', str(Path(path).resolve().parent / 'exports') if str(path) != ':memory:' else str(Path(app.root_path) / 'exports'))
    app.extensions['lexicon_store'] = store
    source_label = f"{store.metadata['source_name']} · {store.metadata['sheet_name']}"
    dataset_key = store.metadata['id']
    # A fresh salt also prevents an editor opened before restart saving over
    # a newly loaded workbook, even when FLASK_SECRET_KEY is stable.
    editor_tokens = URLSafeSerializer(app.secret_key, salt=f'cell-editor-{token_hex(16)}')

    def locked(function):
        @wraps(function)
        def wrapper(*args, **kwargs):
            with store.transaction():
                return function(*args, **kwargs)
        return wrapper

    def cell_key(etimon, row, column):
        return (int(etimon), row['label'], int(row['label_number']), column)

    @app.before_request
    def limit_request():
        # Check before parsing arguments or updating the signed preference cookie.
        if len(request.query_string) > app.config['MAX_QUERY_STRING_LENGTH']:
            abort(414, description='Query string is too long.')
        if len(request.args.get('q', '')) > app.config['MAX_SEARCH_LENGTH']:
            abort(400, description='Search text is too long.')

    @app.after_request
    def security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        # Excel formatting and grid sizing require inline styles; scripts are local files.
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        if app.config['SESSION_COOKIE_SECURE'] and request.is_secure:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        return response

    @app.get('/')
    @locked
    def index():
        edit_mode = bool(session.get('edit_mode', False))
        entries = store.entries()
        labels = store.choices('label', LABEL_ORDER)
        columns = store.choices('column', COLUMN_ORDER)
        if 'edit_csrf' not in session:
            session['edit_csrf'] = token_hex(32)
        if 'reset' in request.args:
            session.pop('search', None)
            session.pop('etimon', None)
        elif 'search' in request.args:
            selections = {
                name: _filter_values(request.args.getlist(name))
                for name in ('label', 'column')
            }
            if set(selections['label']) - set(labels) or set(selections['column']) - set(columns):
                abort(400, description='Unknown search filter.')
            session['search'] = {
                'query': request.args.get('q', ''),
                **selections,
            }
            session.pop('etimon', None)

        saved = session.get('search', {})
        criteria = {
            'query': saved.get('query', ''),
            'label': _filter_values(saved.get('label', [])),
            'column': _filter_values(saved.get('column', [])),
        }
        if 'search' in session:
            session['search'] = criteria
        numbers = store.matching_numbers(
            criteria['query'], tuple(criteria['label']), tuple(criteria['column']),
        )
        requested = request.args.get('etimon', type=int)
        selected = requested if requested is not None else session.get('etimon')
        if selected not in numbers:
            selected = numbers[0] if numbers else None
        session['etimon'] = selected

        if 'plaintext' in request.args:
            session['plaintext'] = request.args.get('plaintext') == '1'
        plaintext = session.get('plaintext', False)

        df = store.to_dataframe(selected if selected is not None else -1)
        cell_line_heights = df.attrs['cell_line_heights']
        table = get_etimon(df, selected, plaintext=plaintext) if selected is not None else None
        table_columns = list(table.columns[2:]) if table is not None else []
        table_rows = table.to_dict('records') if table is not None else []
        cell_backgrounds = {
            (record.label, record.label_number, record.column): record.background_color
            for record in df.loc[df['etimon_number'].eq(selected)].itertuples(index=False)
            if record.background_color
        }
        label_backgrounds = df.attrs.get('label_backgrounds', {})
        empty_backgrounds = df.attrs['empty_cell_backgrounds']
        background_rows = []
        for row in table_rows:
            label_color = label_backgrounds.get((selected, row['label'], row['label_number']), '')
            backgrounds = {'label': label_color, 'label_number': label_color} if label_color else {}
            for column in table_columns:
                color = cell_backgrounds.get((row['label'], row['label_number'], column), '')
                key = cell_key(selected, row, column)
                if key in empty_backgrounds:
                    color = empty_backgrounds[key] or ('var(--label-background)' if row[column] else '')
                elif not row[column]:
                    color = label_color
                if color:
                    backgrounds[column] = color
            background_rows.append(backgrounds)
        highlighted_rows = [
            {
                column: highlighted
                for column in table_columns
                if (highlighted := highlight_content(
                    row[column], criteria['query'], plaintext=plaintext,
                )) is not None
            }
            for row in table_rows
        ]
        grid_columns = [
            {'title': title, 'field': f'content_{index}'}
            for index, title in enumerate(table_columns)
        ]
        # Editing always starts with original formatted HTML, even when the
        # current display uses plaintext or presentation-only search marks.
        formatted = get_etimon(df, selected) if plaintext and selected is not None else table
        formatted_rows = formatted.to_dict('records') if formatted is not None else []
        line_height_rows = [
            {
                column: cell_line_heights[key]
                for column in table_columns
                if (key := cell_key(selected, row, column)) in cell_line_heights
            }
            for row in table_rows
        ]
        def editor_info(row, column, original):
            key = cell_key(selected, row, column)
            record = store.cell(key)
            return {
                'id': record['id'], 'html': original[column],
                'line_height': record['line_height'],
                'token': editor_tokens.dumps([*key, record['revision'], record['generation']]),
            }

        def deletion_token(label=None, number=None):
            return editor_tokens.dumps({
                'kind': 'etymon' if label is None else 'row', 'etimon': selected,
                'label': label, 'label_number': number,
                'version': store.deletion_version(selected, label, number),
            })

        grid_rows = [
            {
                'id': json.dumps([row['label'], row['label_number']], ensure_ascii=False),
                'label': row['label'],
                'label_number': row['label_number'],
                'delete_token': deletion_token(row['label'], int(row['label_number']))
                    if edit_mode and store._label_kind(row['label']) != store._label_kind(LABEL_ORDER[0]) else None,
                **{column['field']: row[column['title']] for column in grid_columns},
                'highlights': {
                    column['field']: highlights[column['title']]
                    for column in grid_columns if column['title'] in highlights
                },
                'backgrounds': {
                    **{field: backgrounds[field] for field in ('label', 'label_number') if field in backgrounds},
                    **{
                        column['field']: backgrounds[column['title']]
                        for column in grid_columns if column['title'] in backgrounds
                    },
                },
                'editors': {
                    column['field']: editor_info(row, column['title'], original)
                    for column in grid_columns
                },
            }
            for row, highlights, backgrounds, original in zip(
                table_rows, highlighted_rows, background_rows, formatted_rows,
            )
        ]
        selected_entry = entries.get(selected)
        selected_index = numbers.index(selected) if numbers else 0
        previous_entry = entries[numbers[selected_index - 1]] if selected_index > 0 else None
        next_entry = entries[numbers[selected_index + 1]] if selected_index + 1 < len(numbers) else None
        page_title = f"{selected_entry['form']} · Parallel Words" if selected_entry else 'Parallel Words'
        template = '_workspace.html' if request.headers.get('HX-Request') == 'true' else 'index.html'
        response = app.make_response(render_template(
            template,
            criteria=criteria,
            source_label=source_label,
            page_title=page_title,
            labels=labels,
            columns=columns,
            matches=[entries[number] for number in numbers],
            reveal_results='search' in request.args and 'reset' not in request.args,
            total=len(entries),
            selected=selected_entry,
            previous=previous_entry,
            next=next_entry,
            table_columns=table_columns,
            table_rows=table_rows,
            highlighted_rows=highlighted_rows,
            background_rows=background_rows,
            line_height_rows=line_height_rows,
            highlight_color=app.config['SEARCH_HIGHLIGHT_COLOR'],
            max_search_length=app.config['MAX_SEARCH_LENGTH'],
            grid_columns=grid_columns,
            plaintext=plaintext,
            edit_mode=edit_mode,
            row_labels=store.row_labels(selected),
            grid_payload={
                'dataset': dataset_key,
                'etimon': selected,
                'plaintext': plaintext,
                'columns': grid_columns,
                'rows': grid_rows,
                'criteria': criteria,
                'title': page_title,
                'csrf': session['edit_csrf'],
                'edit_mode': edit_mode,
                'total': len(entries),
                'delete_etymon_token': deletion_token() if edit_mode and selected is not None else None,
                'etymon_name': selected_entry['form'] if selected_entry else '',
            },
        ))
        response.vary.add('HX-Request')
        response.headers['Cache-Control'] = 'no-store'
        return response

    def mutation(function):
        @wraps(function)
        def wrapper(*args, **kwargs):
            csrf = request.headers.get('X-CSRF-Token', '')
            if not csrf or not compare_digest(csrf.encode(), session.get('edit_csrf', '').encode()):
                return {'error': 'Your editing session expired. Reload the page before editing.'}, 403
            if request.path != '/mode' and not session.get('edit_mode', False):
                return {'error': 'Switch to Edit mode before making changes.'}, 403
            response = app.make_response(function(*args, **kwargs))
            response.headers['Cache-Control'] = 'no-store'
            return response
        return wrapper

    @app.post('/mode')
    @mutation
    def set_mode():
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not isinstance(body.get('edit_mode'), bool):
            return {'error': 'Choose Search or Edit mode.'}, 400
        session['edit_mode'] = body['edit_mode']
        return {'edit_mode': body['edit_mode']}

    @app.post('/rows')
    @mutation
    def add_row():
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or type(body.get('etimon')) is not int or not isinstance(body.get('label'), str):
            return {'error': 'Choose an etymon and row type.'}, 400
        try:
            result = store.add_row(body['etimon'], body['label'], body.get('text'))
        except ValueError as error:
            return {'error': str(error)}, 400
        session['etimon'] = result['etimon']
        return result, 201

    @app.post('/etymons')
    @mutation
    def add_etymon():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return {'error': 'Enter French text before creating an entry.'}, 400
        try:
            result = store.add_etymon(body.get('text'))
        except ValueError as error:
            return {'error': str(error)}, 400
        session.pop('search', None)
        session['etimon'] = result['etimon']
        return result, 201

    @app.post('/cell')
    @mutation
    def save_cell():
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not isinstance(body.get('token'), str):
            return {'error': 'Invalid cell edit.'}, 400
        try:
            signed = editor_tokens.loads(body['token'])
            if not isinstance(signed, list) or len(signed) != 6:
                raise BadSignature('Wrong token type.')
        except BadSignature:
            return {'error': 'This cell has expired. Cancel and reload before editing.'}, 409
        key, revision, generation = tuple(signed[:4]), signed[4], signed[5]
        try:
            store.save_cell(key, revision, body.get('ops'),
                            line_height_provided='line_height' in body, line_height=body.get('line_height'), generation=generation)
        except EditConflict as error:
            return {'error': str(error)}, 409
        except ValueError as error:
            return {'error': str(error)}, 400
        response = app.json.response({'saved': True})
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.post('/trash')
    @mutation
    def delete_entry():
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or body.get('confirmation') != 'DELETE' or not isinstance(body.get('token'), str):
            return {'error': 'Type DELETE to confirm moving this item to Trash.'}, 400
        try:
            target = editor_tokens.loads(body['token'])
            if not isinstance(target, dict) or target.get('kind') not in ('row', 'etymon'):
                raise BadSignature('Wrong token type.')
        except BadSignature:
            return {'error': 'This deletion request expired. Reload and review the item again.'}, 409
        try:
            if target['kind'] == 'row':
                trash_id = store.delete_row(target['etimon'], target['label'], target['label_number'], expected=target['version'])
            else:
                trash_id = store.delete_etymon(target['etimon'], expected=target['version'])
        except EditConflict as error:
            return {'error': str(error)}, 409
        except ValueError as error:
            return {'error': str(error)}, 400
        return {'trashed': True, 'trash_id': trash_id}

    @app.get('/export')
    def export_excel():
        from excel_export import export_timestamped
        path = export_timestamped(store, app.config['EXPORT_DIRECTORY']).resolve()
        response = send_file(path, as_attachment=True, download_name=path.name)
        response.headers['Cache-Control'] = 'no-store'
        return response

    return app


def _port(value):
    try:
        port = int(value)
        if 1 <= port <= 65535:
            return port
    except ValueError:
        pass
    raise argparse.ArgumentTypeError('Port must be an integer from 1 to 65535.')


def _ip(value):
    try:
        return str(ip_address(value))
    except ValueError:
        raise argparse.ArgumentTypeError('Expected a single IPv4 or IPv6 address.') from None


def main(argv=None):
    """Load the requested workbook and serve it with Waitress, without debug mode."""
    parser = argparse.ArgumentParser(description='Browse an Excel etymon workbook with Parallel Words.')
    parser.add_argument(
        'excel_file', nargs='?', type=Path, default=DEFAULT_EXCEL_PATH,
        help='Workbook to load (default: db/example.xlsx beside main.py).',
    )
    parser.add_argument(
        '--sheet', '-s', metavar='NAME',
        help='Exact worksheet name (default: the first worksheet).',
    )
    parser.add_argument('--database', type=Path, help='SQLite file; an existing database is reopened without importing Excel.')
    parser.add_argument('--export', action='store_true', help='Write a timestamped updated workbook and exit.')
    parser.add_argument('--export-dir', type=Path, help='Export directory (default: exports beside the database).')
    binding = parser.add_mutually_exclusive_group()
    binding.add_argument('--local', dest='host', action='store_const', const='127.0.0.1',
                         help='Listen on localhost only (default).')
    binding.add_argument('--public', dest='host', action='store_const', const='0.0.0.0',
                         help='Listen on all IPv4 interfaces; all reachable users can read the data.')
    binding.add_argument('--host', type=_ip, metavar='IP',
                         help='Listen on a specific IPv4 or IPv6 interface instead.')
    parser.set_defaults(host='127.0.0.1')
    parser.add_argument('--port', type=_port, default=5000, help='Listening port (default: 5000).')
    parser.add_argument('--trusted-host', action='append', metavar='HOSTNAME',
                        help='Allowed Host header name, without scheme/port; repeat for more names.')
    parser.add_argument('--trusted-proxy', type=_ip, metavar='IP',
                        help='Trust one proxy at this exact IP for client address and HTTP/HTTPS scheme.')
    parser.add_argument('--secure-cookies', action='store_true',
                        help='Send session cookies only over HTTPS; requires an HTTPS reverse proxy.')
    args = parser.parse_args(argv)
    settings = {'DEBUG': False, 'TESTING': False}
    if args.trusted_host:
        settings['TRUSTED_HOSTS'] = args.trusted_host
    if args.secure_cookies:
        settings['SESSION_COOKIE_SECURE'] = True
    if args.export_dir:
        settings['EXPORT_DIRECTORY'] = str(args.export_dir.resolve())
    try:
        server = create_app(args.excel_file, sheet_name=args.sheet, test_config=settings, database_path=args.database)
        if args.export:
            from excel_export import export_timestamped
            print(export_timestamped(server.extensions['lexicon_store'], server.config['EXPORT_DIRECTORY']))
            server.extensions['lexicon_store'].close()
            return 0
    except (OSError, ValueError, sqlite3.Error, BadZipFile, InvalidFileException, ParseError, KeyError) as error:
        parser.error(f'Could not load {args.excel_file}: {error}')
    proxy_settings = {}
    if args.trusted_proxy:
        proxy_settings = {
            'trusted_proxy': args.trusted_proxy,
            'trusted_proxy_count': 1,
            'trusted_proxy_headers': {'x-forwarded-for', 'x-forwarded-proto'},
        }
    try:
        serve(
            server, host=args.host, port=args.port,
            clear_untrusted_proxy_headers=True, expose_tracebacks=False,
            max_request_header_size=16 * 1024, max_request_body_size=64 * 1024,
            channel_timeout=30, connection_limit=100, threads=4,
            **proxy_settings,
        )
    except OSError as error:
        parser.error(f'Could not listen on {args.host}:{args.port}: {error}')


if __name__ == '__main__':
    main()
else:
    # Preserve Flask's import-based entry point without loading the default
    # workbook before command-line arguments (including --help) are parsed.
    app = create_app()
