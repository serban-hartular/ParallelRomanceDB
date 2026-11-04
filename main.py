"""Local Flask interface for browsing the Romance-language workbook.

Run with .venv/bin/python main.py, then open http://127.0.0.1:5000.
"""

from functools import lru_cache
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from secrets import token_hex

from flask import Flask, render_template, request, session

from df_search import COLUMN_ORDER, LABEL_ORDER, get_etimon, search_dataframe
from extract_sheet import excel_to_dataframe


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
    if test_config:
        app.config.update(test_config)

    df = excel_to_dataframe(app.config['EXCEL_PATH'], app.config['SHEET_NAME'])
    source_label = f"{Path(app.config['EXCEL_PATH']).name} · {df.attrs['sheet_name']}"
    app.extensions['lexicon_df'] = df
    entries = _etimon_entries(df)
    labels = _ordered_values(df['label'], LABEL_ORDER)
    columns = _ordered_values(df['column'], COLUMN_ORDER)
    dataset_key = sha256(
        f"{Path(app.config['EXCEL_PATH']).resolve()}:{app.config['SHEET_NAME']}".encode()
    ).hexdigest()[:16]

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
            session['search'] = {
                'query': request.args.get('q', ''),
                'label': request.args.getlist('label'),
                'column': request.args.getlist('column'),
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
            }
            for row in table_rows
        ]
        selected_entry = entries.get(selected)
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
            results_open='search' in request.args and 'reset' not in request.args,
            total=len(entries),
            selected=selected_entry,
            table_columns=table_columns,
            table_rows=table_rows,
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


app = create_app()


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000)
