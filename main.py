"""Read-only Flask interface for browsing the Romance-language workbook.

Run with .venv/bin/python main.py [workbook.xlsx] [--sheet NAME], then open
http://127.0.0.1:5000.
"""

import argparse
from functools import lru_cache
from hashlib import sha256
from ipaddress import ip_address
import json
import os
from pathlib import Path
import re
from secrets import token_hex
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

from flask import Flask, abort, render_template, request, session
from openpyxl.utils.exceptions import InvalidFileException
from waitress import serve

from df_search import COLUMN_ORDER, LABEL_ORDER, get_etimon, search_dataframe
from extract_sheet import excel_to_dataframe
from search_highlighting import highlight_content


DEFAULT_EXCEL_PATH = Path(__file__).parent / 'db' / 'example.xlsx'


def _ordered_values(values, preferred):
    present = set(values.dropna())
    return [value for value in preferred if value in present] + sorted(present - set(preferred))


def _filter_values(values):
    """Canonicalize selections, including single values from older sessions."""
    if isinstance(values, str):
        values = [values]
    return sorted(set(value for value in values if value))


def _etimon_entries(df):
    """Build result titles from the first available language's etymon entry."""
    etimon_rows = df.loc[df['label'].str.contains(r'^\s*ETIMON\s*/', case=False, na=False)]
    entries = {}
    for number in sorted(df['etimon_number'].unique().tolist()):
        rows = etimon_rows.loc[etimon_rows['etimon_number'].eq(number)].sort_values('label_number')
        form = 'No language form'
        language = ''
        for candidate in COLUMN_ORDER[:6]:
            texts = rows.loc[rows['column'].eq(candidate), 'plaintext_content'].dropna()
            text = next((value.strip() for value in texts if value.strip()), '')
            if text:
                # The workbook places the headword before grammatical notes.
                first_line = next(line.strip() for line in text.splitlines() if line.strip())
                form = re.split(r',|\s{2,}', first_line, maxsplit=1)[0].strip() or first_line
                language = candidate
                break
        entries[number] = {'number': number, 'form': form, 'language': language}
    return entries


def create_app(excel_path=DEFAULT_EXCEL_PATH, sheet_name=None, test_config=None):
    """Load one worksheet at startup and create the browsing application.

    Search results are cached in server memory. Each browser's signed
    session remembers its search criteria, selection, and display mode.
    Only small preferences are stored in the cookie, not workbook content
    or the potentially long list of matches. Restart to reload the file.
    """
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

    df = excel_to_dataframe(app.config['EXCEL_PATH'], app.config['SHEET_NAME'])
    source_label = f"{Path(app.config['EXCEL_PATH']).name} · {df.attrs['sheet_name']}"
    app.extensions['lexicon_df'] = df
    entries = _etimon_entries(df)
    labels = _ordered_values(df['label'], LABEL_ORDER)
    columns = _ordered_values(df['column'], COLUMN_ORDER)
    dataset_key = sha256(
        f"{Path(app.config['EXCEL_PATH']).resolve()}:{app.config['SHEET_NAME']}".encode()
    ).hexdigest()[:16]

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

    @lru_cache(maxsize=128)
    def matching_numbers(query, label, column):
        if not query and not label and not column:
            return tuple(entries)
        return tuple(search_dataframe(
            df, query, label=label or None, column=column or None, case_sensitive=False,
        ))

    @app.get('/')
    def index():
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
        numbers = matching_numbers(
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

        table = get_etimon(df, selected, plaintext=plaintext) if selected is not None else None
        table_columns = list(table.columns[2:]) if table is not None else []
        table_rows = table.to_dict('records') if table is not None else []
        cell_backgrounds = {
            (record.label, record.label_number, record.column): record.background_color
            for record in df.loc[df['etimon_number'].eq(selected)].itertuples(index=False)
            if record.background_color
        }
        label_backgrounds = df.attrs.get('label_backgrounds', {})
        background_rows = []
        for row in table_rows:
            label_color = label_backgrounds.get((selected, row['label'], row['label_number']), '')
            backgrounds = {'label': label_color, 'label_number': label_color} if label_color else {}
            for column in table_columns:
                color = cell_backgrounds.get((row['label'], row['label_number'], column), '')
                if not row[column]:
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
        grid_rows = [
            {
                'id': json.dumps([row['label'], row['label_number']], ensure_ascii=False),
                'label': row['label'],
                'label_number': row['label_number'],
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
            }
            for row, highlights, backgrounds in zip(table_rows, highlighted_rows, background_rows)
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
            highlight_color=app.config['SEARCH_HIGHLIGHT_COLOR'],
            max_search_length=app.config['MAX_SEARCH_LENGTH'],
            grid_columns=grid_columns,
            plaintext=plaintext,
            grid_payload={
                'dataset': dataset_key,
                'etimon': selected,
                'plaintext': plaintext,
                'columns': grid_columns,
                'rows': grid_rows,
                'criteria': criteria,
                'title': page_title,
            },
        ))
        response.vary.add('HX-Request')
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
    try:
        server = create_app(args.excel_file, sheet_name=args.sheet, test_config=settings)
    except (OSError, ValueError, BadZipFile, InvalidFileException, ParseError, KeyError) as error:
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
