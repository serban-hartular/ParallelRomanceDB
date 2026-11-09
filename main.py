"""Flask interface for independent SQLite lexicon collections.

Run .venv/bin/python main.py [--catalog PATH], then open http://127.0.0.1:5000.
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

from flask import Flask, abort, render_template, request, send_file, session, g, redirect, url_for
from itsdangerous import BadSignature, URLSafeSerializer
from openpyxl.utils.exceptions import InvalidFileException
from waitress import serve
from werkzeug.local import LocalProxy

from access_control import AccessControl, LoginDenied, LoginThrottled
from i18n import gettext as _, init_app as init_i18n
from collection_catalog import CollectionCatalog

from df_search import get_etimon
from extract_sheet import excel_to_dataframe
from lexicon_db import EditConflict, LexiconDB, default_database_path
from search_highlighting import highlight_content


DEFAULT_EXCEL_PATH = Path(__file__).parent / 'db' / 'example.xlsx'
DEFAULT_CATALOG_PATH = Path('data/catalog.sqlite3')


def _filter_values(values):
    """Canonicalize selections, including single values from older sessions."""
    if isinstance(values, str):
        values = [values]
    return sorted(set(value for value in values if value))


def create_app(excel_path=DEFAULT_EXCEL_PATH, sheet_name=None, test_config=None, database_path=None, catalog_path=None):
    """Open a catalog, or one database with an optional first-use workbook import."""
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
    init_i18n(app)
    if not re.fullmatch(r'#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?', app.config['SEARCH_HIGHLIGHT_COLOR']):
        raise ValueError(_('SEARCH_HIGHLIGHT_COLOR must be a #RGB or #RRGGBB hex color.'))

    if not (type(app.config['EDIT_HEARTBEAT_SECONDS']) is int and type(app.config['EDIT_LEASE_SECONDS']) is int
            and 0 < app.config['EDIT_HEARTBEAT_SECONDS'] < app.config['EDIT_LEASE_SECONDS']):
        raise ValueError(_('EDIT_HEARTBEAT_SECONDS must be positive and less than EDIT_LEASE_SECONDS.'))

    if type(app.config['LIVE_REFRESH_SECONDS']) is not int or app.config['LIVE_REFRESH_SECONDS'] <= 0:
        raise ValueError(_('LIVE_REFRESH_SECONDS must be a positive integer.'))

    catalog_path = catalog_path or app.config.get('CATALOG_PATH')
    catalog = CollectionCatalog(catalog_path) if catalog_path is not None else None
    if catalog is not None:
        app.extensions['collection_catalog'] = catalog
        app.config['CATALOG_PATH'] = str(catalog.path)
        single_store = None
    else:
        path = database_path or app.config.get('DATABASE_PATH')
        if path is None:
            path = ':memory:' if app.testing else default_database_path(app.config['EXCEL_PATH'],app.config['SHEET_NAME'])
        single_store = LexiconDB(path,app.config['EXCEL_PATH'],app.config['SHEET_NAME'],
                                loader=excel_to_dataframe,row_colors=app.config['ROW_BACKGROUND_COLORS'])
        app.config['DATABASE_PATH'] = str(path)
        app.config.setdefault('EXPORT_DIRECTORY',str(Path(path).resolve().parent/'exports') if str(path)!=':memory:' else str(Path(app.root_path)/'exports'))
        app.extensions['lexicon_store'] = single_store
    access_path = app.config.get('AUTH_DATABASE_PATH')
    if access_path is None:
        access_path = ':memory:' if app.testing else (
            catalog.path.parent/'access.sqlite3' if catalog else Path(path).resolve().parent/'access.sqlite3')
    access = AccessControl(access_path)
    app.config['AUTH_DATABASE_PATH'] = str(access_path)
    app.extensions['access_control'] = access
    if single_store is not None:
        single_store.session_validator = access.session_active

    @app.before_request
    def identify_editor():
        if session.permanent:
            session.permanent = False
        g.editor = access.editor(session.get('editor_session'))
        if g.editor is None:
            session.pop('editor_session', None)

    def authorized():
        return access.can_edit(g.editor, g.lexicon_store.metadata['id'] if g.lexicon_store else None)

    store = LocalProxy(lambda: g.lexicon_store)
    preferences = LocalProxy(lambda: g.collection_preferences)
    scoped_endpoints = {'index','set_mode','add_row','add_etymon','save_cell','delete_entry','export_excel','begin_cell_edit','heartbeat_cell_edit','finish_cell_edit','content_changes'}

    @app.url_defaults
    def collection_urls(endpoint, values):
        if endpoint in scoped_endpoints and getattr(g,'collection_id',None):
            values.setdefault('collection_id',g.collection_id)

    @app.before_request
    def guard_collection_lifecycle():
        # Hold the catalog lock through response construction and preference
        # writes, so removal cannot race a request using a selected store.
        if catalog is not None and ((request.view_args or {}).get('collection_id') or
                request.endpoint in {'admin.overview','admin.choose','admin.passwords','admin.change_password'}):
            catalog._lock.acquire()
            g.catalog_guard = True

    @app.teardown_request
    def release_collection_lifecycle(error):
        if g.pop('catalog_guard',False):
            catalog._lock.release()

    @app.before_request
    def select_collection():
        collection_id = (request.view_args or {}).get('collection_id')
        g.lexicon_store = single_store
        g.collection_id = None
        g.collection_preferences = session
        if catalog is None:
            if collection_id is not None and collection_id!=single_store.metadata['id']:
                abort(404)
            return
        if request.endpoint not in scoped_endpoints:
            return
        if collection_id is None:
            if request.endpoint!='index':
                abort(404)
            return
        try:
            entry = catalog.get(collection_id)
            g.lexicon_store = catalog.store(collection_id)
        except KeyError:
            abort(404,description=_('Unknown collection.'))
        except ValueError as error:
            abort(503,description=str(error))
        g.lexicon_store.session_validator = access.session_active
        g.collection_id = collection_id
        g.collection_name = entry['name']
        if 'browser_id' not in session:
            session['browser_id'] = token_hex(24)
        g.collection_preferences = catalog.preferences(session['browser_id'],collection_id)
        g.original_preferences = json.dumps(g.collection_preferences,sort_keys=True)

    # A fresh salt also prevents an editor opened before restart saving over
    # a newly loaded workbook, even when FLASK_SECRET_KEY is stable.
    editor_tokens = URLSafeSerializer(app.secret_key, salt=f'cell-editor-{token_hex(16)}')

    def locked(function):
        @wraps(function)
        def wrapper(*args, **kwargs):
            if g.lexicon_store is None:
                return function(*args, **kwargs)
            with store.transaction():
                return function(*args, **kwargs)
        return wrapper

    def cell_key(etimon, row, column):
        return (int(etimon), row['label'], int(row['label_number']), column)

    @app.before_request
    def limit_request():
        if request.endpoint == 'admin.import_upload':
            request.max_content_length = app.config['COLLECTION_UPLOAD_MAX_BYTES'] + 64 * 1024
        # Check before parsing arguments or updating the signed preference cookie.
        if len(request.query_string) > app.config['MAX_QUERY_STRING_LENGTH']:
            abort(414, description=_('Query string is too long.'))
        if len(request.args.get('q', '')) > app.config['MAX_SEARCH_LENGTH']:
            abort(400, description=_('Search text is too long.'))

    @app.after_request
    def security_headers(response):
        if catalog is not None and getattr(g,'collection_id',None) and response.status_code<400:
            if json.dumps(g.collection_preferences,sort_keys=True)!=g.original_preferences:
                catalog.save_preferences(session['browser_id'],g.collection_id,g.collection_preferences)
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
    @app.get('/collections/<collection_id>/')
    @locked
    def index(collection_id=None):
        if g.lexicon_store is None:
            entries = catalog.collections()
            if entries:
                return redirect(url_for('index',collection_id=entries[0]['id']))
            return render_template('collections_empty.html')
        live = request.args.get('live') == '1'
        # A background refresh describes this tab's view and never saves preferences.
        view_preferences = {'edit_mode':request.args.get('editing') == '1'} if live else preferences
        source_label = f"{store.metadata['source_name']} · {store.metadata['sheet_name']}"
        collection_name = getattr(g,'collection_name',store.metadata['sheet_name'])
        dataset_key = store.metadata['id']
        edit_mode = bool(view_preferences.get('edit_mode', False) and authorized())
        entries = store.entries(empty_form=_('No language form'))
        labels = store.choices('label')
        columns = store.choices('column')
        if 'edit_csrf' not in session:
            session['edit_csrf'] = token_hex(32)
        if 'reset' in request.args:
            view_preferences.pop('search', None)
            view_preferences.pop('etimon', None)
        elif 'search' in request.args:
            selections = {
                name: _filter_values(request.args.getlist(name))
                for name in ('label', 'column')
            }
            if live:
                selections['label'] = [value for value in selections['label'] if value in labels]
                selections['column'] = [value for value in selections['column'] if value in columns]
            if set(selections['label']) - set(labels) or set(selections['column']) - set(columns):
                abort(400, description=_('Unknown search filter.'))
            view_preferences['search'] = {
                'query': request.args.get('q', ''),
                **selections,
            }
            view_preferences.pop('etimon', None)

        saved = view_preferences.get('search', {})
        criteria = {
            'query': saved.get('query', ''),
            'label': _filter_values(saved.get('label', [])),
            'column': _filter_values(saved.get('column', [])),
        }
        if 'search' in view_preferences:
            view_preferences['search'] = criteria
        numbers = store.matching_numbers(
            criteria['query'], tuple(criteria['label']), tuple(criteria['column']),
        )
        requested = request.args.get('etimon', type=int)
        selected = requested if requested is not None else view_preferences.get('etimon')
        if selected not in numbers:
            selected = numbers[0] if numbers else None
        view_preferences['etimon'] = selected

        if 'plaintext' in request.args:
            view_preferences['plaintext'] = request.args.get('plaintext') == '1'
        plaintext = view_preferences.get('plaintext', False)

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
                'token': editor_tokens.dumps([dataset_key,record['row_id'],record['column_id'],record['revision'],record['generation'],g.editor['session_id'] if g.editor else None]),
            }

        def deletion_token(label=None, number=None):
            return editor_tokens.dumps({
                'editor_session':g.editor['session_id'] if g.editor else None, 'dataset':dataset_key, 'kind': 'etymon' if label is None else 'row', 'etimon': selected,
                'label': label, 'label_number': number,
                'version': store.deletion_version(selected, label, number),
            })

        grid_rows = [
            {
                'id': json.dumps([row['label'], row['label_number']], ensure_ascii=False),
                'label': row['label'],
                'label_number': row['label_number'],
                'delete_token': deletion_token(row['label'], int(row['label_number']))
                    if edit_mode and not store.row_type(selected,row['label'],int(row['label_number']))['is_etymon'] else None,
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
        page_title = f"{collection_name} · {selected_entry['form']} · Parallel Words" if selected_entry else f'{collection_name} · Parallel Words'
        template = '_workspace.html' if request.headers.get('HX-Request') == 'true' else 'index.html'
        response = app.make_response(render_template(
            template,
            criteria=criteria,
            source_label=source_label,
            collection_name=collection_name,
            collection_options=[{'id':entry['id'],'name':entry['name'],'url':url_for('index',collection_id=entry['id'])} for entry in catalog.collections()] if catalog else [],
            initial_column_name=store.initial_column()['name'],
            page_title=page_title,
            labels=labels,
            columns=columns,
            matches=[entries[number] for number in numbers],
            reveal_results=not live and 'search' in request.args and 'reset' not in request.args,
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
            editor_name=g.editor['name'] if authorized() else None,
            row_labels=store.row_labels(selected),
            grid_payload={
                'auth': {'authenticated':authorized(), 'name':g.editor['name'] if authorized() else None,
                         'identity':g.editor['session_id'] if authorized() else None,
                         'configured':access.configured(), 'login_url':url_for('login_editor'),
                         'logout_url':url_for('logout_editor')},
                'dataset': dataset_key,
                'content_version':store.content_version(),
                'refresh_ms':app.config['LIVE_REFRESH_SECONDS'] * 1000,
                'collection_name':collection_name,
                'collection_options':[{'id':entry['id'],'name':entry['name'],'url':url_for('index',collection_id=entry['id'])} for entry in catalog.collections()] if catalog else [],
                'source_label':source_label,
                'initial_column':store.initial_column()['name'],
                'filters':{'label':labels,'column':columns},
                'urls':{'index':url_for('index'),'cell':url_for('save_cell'),'mode':url_for('set_mode'),
                        'rows':url_for('add_row'),'etymons':url_for('add_etymon'),'trash':url_for('delete_entry'),
                        'export':url_for('export_excel'), 'changes':url_for('content_changes'), 'edit_start':url_for('begin_cell_edit'),
                        'edit_heartbeat':url_for('heartbeat_cell_edit'), 'edit_finish':url_for('finish_cell_edit')},
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

    @app.get('/changes')
    @app.get('/collections/<collection_id>/changes')
    @locked
    def content_changes(collection_id=None):
        response = app.json.response({'version':store.content_version(),
            'collection_name':getattr(g,'collection_name',store.metadata['sheet_name'])})
        response.headers['Cache-Control'] = 'no-store'
        return response

    def mutation(function):
        @wraps(function)
        def wrapper(*args, **kwargs):
            csrf = request.headers.get('X-CSRF-Token', '')
            if not csrf or not compare_digest(csrf.encode(), session.get('edit_csrf', '').encode()):
                return {'error': _('Your editing session expired. Reload the page before editing.')}, 403
            if request.endpoint!='set_mode' and not authorized():
                return {'error':_('Sign in to edit. Your edit login may have expired.'), 'authentication_required':True}, 401
            if request.endpoint not in {'set_mode','heartbeat_cell_edit','finish_cell_edit'} and not preferences.get('edit_mode', False):
                return {'error': _('Switch to Edit mode before making changes.')}, 403
            if request.endpoint in {'add_row','add_etymon'} and request.headers.get('X-Editor-Session') != g.editor['session_id']:
                return {'error':_('The editor changed. Close this dialog and reload before adding entries.')}, 409
            response = app.make_response(function(*args, **kwargs))
            response.headers['Cache-Control'] = 'no-store'
            return response
        return wrapper

    def authentication_post(function):
        @wraps(function)
        def wrapper(*args, **kwargs):
            csrf = request.headers.get('X-CSRF-Token', '')
            if not csrf or not compare_digest(csrf.encode(),session.get('edit_csrf','').encode()):
                return {'error':_('Your session expired. Reload the page before signing in.')}, 403
            response = app.make_response(function(*args, **kwargs))
            response.headers['Cache-Control'] = 'no-store'
            return response
        return wrapper

    @app.post('/auth/login')
    @authentication_post
    def login_editor():
        body = request.get_json(silent=True)
        if not isinstance(body,dict):
            return {'error':_('Enter your name and the edit password.')}, 400
        try:
            token = access.login(body.get('name'),body.get('password'),request.remote_addr or 'unknown')
        except LoginThrottled as error:
            response = app.json.response({'error':str(error)})
            response.status_code = 429
            response.headers['Retry-After'] = '300'
            return response
        except LoginDenied as error:
            return {'error':str(error)}, 401
        editor = access.editor(token)
        if editor is None:
            return {'error':_('The edit password changed. Please try again.')}, 401
        access.logout(session.get('editor_session'))
        session['editor_session'] = token
        session.permanent = False
        return {'authenticated':True,'name':editor['name']}

    @app.post('/auth/logout')
    @authentication_post
    def logout_editor():
        access.logout(session.pop('editor_session',None))
        return {'authenticated':False}

    @app.post('/mode')
    @app.post('/collections/<collection_id>/mode')
    @mutation
    def set_mode(collection_id=None):
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not isinstance(body.get('edit_mode'), bool):
            return {'error': _('Choose Search or Edit mode.')}, 400
        if body['edit_mode'] and not authorized():
            return {'error':_('Enter your name and the edit password.'), 'authentication_required':True}, 401
        preferences['edit_mode'] = body['edit_mode']
        return {'edit_mode': body['edit_mode']}

    @app.post('/rows')
    @app.post('/collections/<collection_id>/rows')
    @mutation
    def add_row(collection_id=None):
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or type(body.get('etimon')) is not int or not isinstance(body.get('label'), str):
            return {'error': _('Choose an etymon and row type.')}, 400
        try:
            result = store.add_row(body['etimon'], body['label'], body.get('text'),actor=g.editor)
        except ValueError as error:
            return {'error': str(error)}, 400
        preferences['etimon'] = result['etimon']
        return result, 201

    @app.post('/etymons')
    @app.post('/collections/<collection_id>/etymons')
    @mutation
    def add_etymon(collection_id=None):
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return {'error': _('Enter text before creating an entry.')}, 400
        try:
            result = store.add_etymon(body.get('text'),actor=g.editor)
        except ValueError as error:
            return {'error': str(error)}, 400
        preferences.pop('search', None)
        preferences['etimon'] = result['etimon']
        return result, 201

    def editing_target(body):
        if not isinstance(body,dict) or not isinstance(body.get('token'),str):
            raise EditConflict(_('Invalid cell editor request.'))
        try:
            if not re.fullmatch(r'[A-Za-z0-9_.-]+',body['token']):
                raise BadSignature('Invalid token encoding.')
            signed = editor_tokens.loads(body['token'])
            if not isinstance(signed,list) or len(signed)!=6 or signed[0]!=store.metadata['id'] or signed[5]!=g.editor['session_id']:
                raise BadSignature('Wrong token type.')
        except BadSignature:
            raise EditConflict(_('This cell has expired. Cancel and reload before editing.')) from None
        return store.cell_key(signed[1],signed[2]),signed[3],signed[4]

    @app.post('/cell/start')
    @app.post('/collections/<collection_id>/cell/start')
    @mutation
    def begin_cell_edit(collection_id=None):
        body = request.get_json(silent=True)
        try:
            key,revision,generation = editing_target(body)
            result = store.begin_cell_edit(key,revision,generation,g.editor,lease_seconds=app.config['EDIT_LEASE_SECONDS'])
        except EditConflict as error:
            return {'error':str(error)}, 409
        result['heartbeat_ms'] = app.config['EDIT_HEARTBEAT_SECONDS']*1000
        result['lease_ms'] = app.config['EDIT_LEASE_SECONDS']*1000
        return result,201

    @app.post('/cell/heartbeat')
    @app.post('/collections/<collection_id>/cell/heartbeat')
    @mutation
    def heartbeat_cell_edit(collection_id=None):
        body = request.get_json(silent=True)
        try:
            editing_target(body)  # Retains the existing restart/identity guards.
            result = store.heartbeat_cell_edit(body.get('lease'),g.editor,lease_seconds=app.config['EDIT_LEASE_SECONDS'])
        except EditConflict as error:
            return {'error':str(error),'lock_lost':True}, 409
        result['lease_ms'] = app.config['EDIT_LEASE_SECONDS']*1000
        return result

    @app.post('/cell/finish')
    @app.post('/collections/<collection_id>/cell/finish')
    @mutation
    def finish_cell_edit(collection_id=None):
        body = request.get_json(silent=True)
        if not isinstance(body,dict):
            return {'error':_('Invalid editor close request.')},400
        try:
            return store.finish_cell_edit(body.get('lease'),g.editor,body.get('outcome'))
        except EditConflict as error:
            return {'error':str(error)},409
        except ValueError as error:
            return {'error':str(error)},400

    @app.post('/cell')
    @app.post('/collections/<collection_id>/cell')
    @mutation
    def save_cell(collection_id=None):
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not isinstance(body.get('token'), str):
            return {'error': _('Invalid cell edit.')}, 400
        try:
            if not re.fullmatch(r'[A-Za-z0-9_.-]+',body['token']):
                raise BadSignature('Invalid token encoding.')
            signed = editor_tokens.loads(body['token'])
            if not isinstance(signed, list) or len(signed)!=6 or signed[0]!=store.metadata['id'] or signed[5]!=g.editor['session_id']:
                raise BadSignature('Wrong token type.')
        except BadSignature:
            return {'error': _('This cell has expired. Cancel and reload before editing.')}, 409
        revision,generation = signed[3],signed[4]
        try:
            key = store.cell_key(signed[1],signed[2])
            store.save_cell(key, revision, body.get('ops'),
                            line_height_provided='line_height' in body, line_height=body.get('line_height'), generation=generation,actor=g.editor,lease=body.get('lease'))
        except EditConflict as error:
            return {'error': str(error)}, 409
        except ValueError as error:
            return {'error': str(error)}, 400
        response = app.json.response({'saved': True})
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.post('/trash')
    @app.post('/collections/<collection_id>/trash')
    @mutation
    def delete_entry(collection_id=None):
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or body.get('confirmation') != 'DELETE' or not isinstance(body.get('token'), str):
            return {'error': _('Type DELETE to confirm moving this item to Trash.')}, 400
        try:
            if not re.fullmatch(r'[A-Za-z0-9_.-]+',body['token']):
                raise BadSignature('Invalid token encoding.')
            target = editor_tokens.loads(body['token'])
            if not isinstance(target, dict) or target.get('kind') not in ('row','etymon') or target.get('dataset')!=store.metadata['id'] or target.get('editor_session')!=g.editor['session_id']:
                raise BadSignature('Wrong token type.')
        except BadSignature:
            return {'error': _('This deletion request expired. Reload and review the item again.')}, 409
        try:
            if target['kind'] == 'row':
                trash_id = store.delete_row(target['etimon'], target['label'], target['label_number'], expected=target['version'],actor=g.editor)
            else:
                trash_id = store.delete_etymon(target['etimon'], expected=target['version'],actor=g.editor)
        except EditConflict as error:
            return {'error': str(error)}, 409
        except ValueError as error:
            return {'error': str(error)}, 400
        return {'trashed': True, 'trash_id': trash_id}

    @app.get('/export')
    @app.get('/collections/<collection_id>/export')
    def export_excel(collection_id=None):
        from excel_export import export_timestamped, export_collections_timestamped
        choices = catalog.collections() if catalog else [{'id':store.metadata['id'],'name':store.metadata['sheet_name']}]
        selected = request.args.getlist('collection') if 'selection' in request.args else [store.metadata['id']]
        selected = list(dict.fromkeys(selected))
        error = _('Choose at least one collection.') if not selected else None
        if any(identifier not in {item['id'] for item in choices} for identifier in selected):
            abort(404,description=_('A selected collection is unavailable. Reload the export options.'))
        if request.args.get('choose')=='1' or error:
            response = app.make_response((render_template('export.html',collections=choices,
                selected=selected,error=error,back_url=url_for('index')),400 if error else 200))
            response.headers['Cache-Control'] = 'no-store'
            return response
        directory = app.config.get('EXPORT_DIRECTORY')
        if len(selected)>1:
            entries = [entry for entry in choices if entry['id'] in selected]
            directory = (Path(directory) if directory else catalog.path.parent/'exports')/'combined'
            try:
                path = export_collections_timestamped([(entry['name'],catalog.store(entry['id'])) for entry in entries],directory).resolve()
            except ValueError as exception:
                response = app.make_response((render_template('export.html',collections=choices,selected=selected,
                    error=str(exception),back_url=url_for('index')),400))
                response.headers['Cache-Control'] = 'no-store'
                return response
        else:
            target = catalog.store(selected[0]) if catalog else store
            if catalog:
                directory = (Path(directory) if directory else catalog.path.parent/'exports')/target.metadata['id']
            path = export_timestamped(target,directory).resolve()
        response = send_file(path, as_attachment=True, download_name=path.name)
        response.headers['Cache-Control'] = 'no-store'
        return response

    from admin import create_admin_blueprint
    app.register_blueprint(create_admin_blueprint(app,access,catalog,single_store))
    return app


def _port(value):
    try:
        port = int(value)
        if 1 <= port <= 65535:
            return port
    except ValueError:
        pass
    raise argparse.ArgumentTypeError(_('Port must be an integer from 1 to 65535.'))


def _ip(value):
    try:
        return str(ip_address(value))
    except ValueError:
        raise argparse.ArgumentTypeError(_('Expected a single IPv4 or IPv6 address.')) from None


def main(argv=None):
    """Serve a collection catalog or one database with Waitress."""
    parser = argparse.ArgumentParser(description='Browse and edit Parallel Words collections (default: data/catalog.sqlite3).')
    parser.add_argument(
        'excel_file', nargs='?', type=Path,
        help='Import a workbook into a single database instead of serving a catalog.',
    )
    parser.add_argument(
        '--sheet', '-s', metavar='NAME',
        help='Exact worksheet name (default: the first worksheet).',
    )
    parser.add_argument('--catalog',type=Path,help='Collection catalog to serve; manage collections with manage_collections.py.')
    parser.add_argument('--database', type=Path, help='SQLite file; an existing database is reopened without importing Excel.')
    parser.add_argument('--auth-database',type=Path,help='Global access database (default: access.sqlite3 beside the catalog/database).')
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
    if args.catalog is None and args.database is None and args.excel_file is None and not args.sheet:
        args.catalog = DEFAULT_CATALOG_PATH
    if args.catalog and (args.database or args.excel_file is not None or args.sheet or args.export):
        parser.error('--catalog selects collection mode; use manage_collections.py to import or export a specific database with --database.')
    args.excel_file = args.excel_file or DEFAULT_EXCEL_PATH
    settings = {'DEBUG': False, 'TESTING': False}
    if args.trusted_host:
        settings['TRUSTED_HOSTS'] = args.trusted_host
    if args.secure_cookies:
        settings['SESSION_COOKIE_SECURE'] = True
    if args.auth_database:
        settings['AUTH_DATABASE_PATH'] = str(args.auth_database.resolve())
    if args.export_dir:
        settings['EXPORT_DIRECTORY'] = str(args.export_dir.resolve())
    try:
        server = create_app(args.excel_file, sheet_name=args.sheet, test_config=settings, database_path=args.database,catalog_path=args.catalog)
        if args.export:
            from excel_export import export_timestamped
            print(export_timestamped(server.extensions['lexicon_store'], server.config['EXPORT_DIRECTORY']))
            server.extensions['lexicon_store'].close()
            return 0
    except (OSError, ValueError, sqlite3.Error, BadZipFile, InvalidFileException, ParseError, KeyError) as error:
        parser.error(f'Could not open {args.catalog or args.database or args.excel_file}: {error}')
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
            max_request_header_size=16 * 1024,
            max_request_body_size=server.config['COLLECTION_UPLOAD_MAX_BYTES'] + 64 * 1024,
            channel_timeout=30, connection_limit=100, threads=4,
            **proxy_settings,
        )
    except OSError as error:
        parser.error(f'Could not listen on {args.host}:{args.port}: {error}')


if __name__ == '__main__':
    main()
