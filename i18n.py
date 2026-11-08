"""Interface translations. Collection/workbook content never passes through this catalog."""

import json
from pathlib import Path
from urllib.parse import urlsplit

from flask import current_app, g, has_request_context, redirect, render_template, request, url_for
from werkzeug.exceptions import HTTPException, SecurityError

LANGUAGES = ('ro', 'en')
COOKIE = 'ui_language'


def language():
    if not has_request_context():
        return 'en'  # Command-line tools and stored data are independent of the UI.
    return getattr(g, 'ui_language', current_app.config.get('DEFAULT_UI_LANGUAGE', 'ro'))


class InterfaceText(str):
    """Mark application messages so import failures can omit library diagnostics."""


def gettext(message, **values):
    if has_request_context():
        catalog = current_app.extensions['translations']
        message = catalog.get(message, {}).get(language(), message)
    return InterfaceText(message.format_map(values) if values else message)


def safe_return(value):
    if not isinstance(value, str) or '\\' in value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        return '/'
    try:
        parts = urlsplit(value)
    except ValueError:
        return '/'
    return value if not parts.scheme and not parts.netloc and parts.path.startswith('/') and not parts.path.startswith('//') else '/'


def init_app(app):
    app.config.setdefault('DEFAULT_UI_LANGUAGE', 'ro')
    if app.config['DEFAULT_UI_LANGUAGE'] not in LANGUAGES:
        raise ValueError('DEFAULT_UI_LANGUAGE must be ro or en.')
    with (Path(app.root_path) / 'translations.json').open(encoding='utf-8') as source:
        app.extensions['translations'] = json.load(source)

    @app.before_request
    def select_language():
        # Requests from an already open page keep its language when another tab switches.
        candidate = request.headers.get('X-Interface-Language')
        if candidate not in LANGUAGES:
            candidate = request.cookies.get(COOKIE)
        g.ui_language = candidate if candidate in LANGUAGES else app.config['DEFAULT_UI_LANGUAGE']

    @app.context_processor
    def translation_context():
        destination = request.full_path.rstrip('?')
        return {'_': gettext, 'ui_language': language(),
                'language_url': lambda code: url_for('set_language', code=code, next=destination),
                'interface_messages': {key: value[language()] for key, value in app.extensions['translations'].items()}}

    @app.get('/language/<code>')
    def set_language(code):
        if code not in LANGUAGES:
            from flask import abort
            abort(404)
        g.ui_language = code
        response = redirect(safe_return(request.args.get('next')), code=303)
        response.set_cookie(COOKIE, code, max_age=365 * 24 * 60 * 60, httponly=True,
                            samesite='Lax', secure=app.config.get('SESSION_COOKIE_SECURE', False))
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.after_request
    def language_headers(response):
        response.headers['Content-Language'] = language()
        response.vary.add('Cookie')
        response.vary.add('X-Interface-Language')
        return response

    @app.errorhandler(HTTPException)
    def localized_http_error(error):
        # Explicit application descriptions are translated at their source. Werkzeug's
        # defaults get a concise catalog message, without exposing technical details.
        description = error.description
        if isinstance(error, SecurityError) or description == type(error).description:
            description = gettext('The request could not be completed. Please return to the page and try again.')
        if request.is_json:
            return {'error': description}, error.code
        return render_template('error.html', status=error.code, description=description,
                               navigation=not isinstance(error, SecurityError)), error.code
