"""Server-rendered administration. All forms work without JavaScript."""

from datetime import date, datetime, time, timedelta, timezone
import json
import re
from secrets import compare_digest, token_hex
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for
from itsdangerous import BadSignature, URLSafeSerializer
from werkzeug.exceptions import HTTPException

from access_control import LoginDenied, LoginThrottled
import admin_data as data


ZONE = ZoneInfo('Europe/Bucharest')


def local_time(value):
    if not value:
        return 'Not recorded'
    try:
        value = datetime.fromisoformat(value)
        value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
        return value.astimezone(ZONE).strftime('%d %b %Y, %H:%M:%S %z')
    except (ValueError,TypeError):
        return 'Not recorded'


def date_bounds(since, through):
    def parse(value):
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):
            raise ValueError('Enter dates as YYYY-MM-DD.')
        return date.fromisoformat(value)
    try:
        start, end = parse(since) if since else None, parse(through) if through else None
        if start and end and start>end:
            raise ValueError('The end date must not precede the start date.')
        lower = datetime.combine(start,time(),ZONE).astimezone(timezone.utc).isoformat() if start else None
        upper = datetime.combine(end+timedelta(days=1),time(),ZONE).astimezone(timezone.utc).isoformat() if end else None
        return lower, upper
    except (ValueError,OverflowError) as error:
        raise ValueError('Enter a valid date range. '+str(error)) from None


def safe_next(value):
    if not isinstance(value,str) or '\\' in value or any(ord(char)<32 or ord(char)==127 for char in value):
        return '/admin/'
    try:
        parts = urlsplit(value)
    except ValueError:
        return '/admin/'
    return value if not parts.scheme and not parts.netloc and parts.path.startswith('/admin/') else '/admin/'


def create_admin_blueprint(app, access, catalog, single_store):
    blueprint = Blueprint('admin',__name__,url_prefix='/admin')
    targets = URLSafeSerializer(app.secret_key,salt='admin-restoration')

    def collections():
        if catalog is not None:
            return [{'id':entry['id'],'name':entry['name']} for entry in catalog.collections()]
        return [{'id':single_store.metadata['id'],
                 'name':f"{single_store.metadata['source_name']} · {single_store.metadata['sheet_name']}"}]

    def select(identifier=None):
        choices = collections()
        identifier = identifier or request.args.get('collection_id') or (choices[0]['id'] if choices else None)
        if identifier is None:
            g.admin_collection = None
            return None
        selected = next((item for item in choices if item['id']==identifier),None)
        if selected is None:
            abort(404,description='Unknown collection.')
        try:
            store = catalog.store(identifier) if catalog is not None else single_store
        except (KeyError,ValueError):
            abort(503,description='The selected collection is unavailable.')
        store.session_validator = access.session_active
        g.admin_collection = selected
        return store

    @blueprint.before_request
    def authorize():
        g.admin = access.administrator(session.get('admin_session'))
        if g.admin is None:
            session.pop('admin_session',None)
        if 'admin_csrf' not in session:
            session['admin_csrf'] = token_hex(32)
        if request.endpoint!='admin.login' and not access.can_admin(g.admin):
            return redirect(url_for('admin.login',next=safe_next(request.full_path.rstrip('?'))),code=303 if request.method=='POST' else 302)
        if request.method=='POST':
            submitted = request.form.get('csrf_token','')
            if not submitted or not compare_digest(submitted.encode('utf-8','replace'),session['admin_csrf'].encode()):
                abort(403,description='This administration form expired. Reload the page and try again.')

    @blueprint.after_request
    def no_cache(response):
        response.headers['Cache-Control'] = 'no-store'
        return response

    @blueprint.context_processor
    def context():
        selected = getattr(g,'admin_collection',None)
        identifier = selected['id'] if selected else None
        def page_link(page):
            return url_for(request.endpoint,**{**request.args.to_dict(),**(request.view_args or {}),'page':page})
        return {'administrator':getattr(g,'admin',None),'collection':selected,'collections':collections(),
                'csrf_token':session.get('admin_csrf'),'actions':data.ACTIONS,'statuses':data.STATUSES,
                'page_link':page_link,'local_time':local_time,'snapshot_cells':data.snapshot_cells,
                'snapshot_json':lambda snapshot:json.dumps(snapshot,ensure_ascii=False,indent=2),
                'back_url':url_for('index',collection_id=identifier) if identifier else url_for('index')}

    @blueprint.errorhandler(HTTPException)
    def error_page(error):
        return render_template('admin/error.html',admin_error=error),error.code

    @blueprint.route('/login',methods=['GET','POST'])
    def login():
        error, status = None, 200
        destination = safe_next(request.form.get('next') if request.method=='POST' else request.args.get('next'))
        if request.method=='POST':
            try:
                token = access.login(request.form.get('name'),request.form.get('password'),request.remote_addr or 'unknown',role='admin')
                if access.administrator(token) is None:
                    raise LoginDenied('The administrator password changed. Please try again.')
                access.logout(session.get('admin_session'))
                session['admin_session'] = token
                session['admin_csrf'] = token_hex(32)
                session.permanent = False
                return redirect(destination,code=303)
            except LoginThrottled as exception:
                error, status = str(exception),429
            except LoginDenied as exception:
                error, status = str(exception),401
        configured = access.configured('admin')
        response = app.make_response((render_template('admin/login.html',error=error,configured=configured,
                                                     destination=destination),status if configured else 503))
        if status==429:
            response.headers['Retry-After'] = '300'
        return response

    @blueprint.post('/logout')
    def logout():
        access.logout(session.pop('admin_session',None))
        session['admin_csrf'] = token_hex(32)
        flash('Administrator signed out.','success')
        return redirect(url_for('admin.login'),code=303)

    @blueprint.get('/')
    def overview():
        store = select()
        return render_template('admin/overview.html',section='overview',summary=data.overview(store) if store else None)

    @blueprint.get('/choose')
    def choose():
        store = select(request.args.get('collection_id'))
        section = request.args.get('section','overview')
        if section not in ('overview','trash','history','editors'):
            abort(400,description='Choose a valid administration page.')
        if store is None:
            return redirect(url_for('admin.overview'))
        return redirect(url_for('admin.'+section,collection_id=g.admin_collection['id']))

    @blueprint.get('/passwords')
    def passwords():
        select()
        return render_template('admin/passwords.html',section='passwords',credentials=access.credential_status())

    @blueprint.post('/passwords/<role>')
    def change_password(role):
        if role not in ('edit','admin'):
            abort(404)
        select()
        error, status = None, 400
        try:
            password = request.form.get('password')
            if password!=request.form.get('repeat_password'):
                raise ValueError('The new passwords do not match; nothing was changed.')
            access.change_password('editor' if role=='edit' else 'admin',password,
                current_password=request.form.get('current_password'),actor=g.admin,peer=request.remote_addr or 'unknown')
        except LoginThrottled as exception:
            error, status = str(exception),429
        except LoginDenied as exception:
            error, status = str(exception),401
        except ValueError as exception:
            error = str(exception)
        if error:
            response = app.make_response((render_template('admin/passwords.html',section='passwords',
                credentials=access.credential_status(),error=error),status))
            if status==429:
                response.headers['Retry-After'] = '300'
            return response
        if role=='admin':
            session.pop('admin_session',None)
            session['admin_csrf'] = token_hex(32)
            flash('Administrator password changed. All administrators have been signed out. Sign in with the new password.','success')
            return redirect(url_for('admin.login'),code=303)
        flash('Edit password changed. All editor logins have been signed out.','success')
        return redirect(url_for('admin.passwords',collection_id=g.admin_collection['id'] if g.admin_collection else None),code=303)

    def positive(name, default=None):
        value = request.args.get(name,'')
        if not value:
            return default
        if not re.fullmatch(r'[0-9]{1,9}',value) or not 1<=int(value)<=1000000:
            abort(400,description=f'Enter a positive {name} (at most 1000000).')
        return int(value)

    def item(store, identifier):
        try:
            return data.trash_detail(store,identifier)
        except KeyError:
            abort(404,description='No Trash item with that ID exists in this collection.')

    @blueprint.get('/collections/<collection_id>/trash')
    def trash(collection_id):
        store = select(collection_id)
        kind = request.args.get('kind','')
        state = request.args.get('state','pending')
        if state not in ('pending','recovered'):
            abort(400,description='Choose a valid Trash status.')
        try:
            listing = data.trash_page(store,page=positive('page',1),etymon=positive('etymon'),kind=kind,recovered=state=='recovered')
        except ValueError as error:
            abort(400,description=str(error))
        return render_template('admin/trash.html',section='trash',listing=listing)

    @blueprint.get('/collections/<collection_id>/trash/<int:trash_id>')
    def trash_item(collection_id,trash_id):
        store = select(collection_id)
        return render_template('admin/trash_item.html',section='trash',item=item(store,trash_id))

    @blueprint.route('/collections/<collection_id>/trash/<int:trash_id>/restore',methods=['GET','POST'])
    def restore(collection_id,trash_id):
        store = select(collection_id)
        target = item(store,trash_id)
        if request.method=='POST':
            try:
                signed = targets.loads(request.form.get('target',''))
                if signed!=[collection_id,trash_id,session['admin_csrf']]:
                    raise BadSignature('Wrong restoration target.')
            except BadSignature:
                abort(409,description='This recovery form expired or belongs to another item. Review the item again.')
            try:
                store.restore_trash(trash_id,actor=g.admin)
            except ValueError as error:
                abort(409,description=str(error))
            flash('Trash item restored. Open collection views will update automatically.','success')
            return redirect(url_for('admin.trash_item',collection_id=collection_id,trash_id=trash_id),code=303)
        return render_template('admin/restore.html',section='trash',item=target,
                               target=targets.dumps([collection_id,trash_id,session['admin_csrf']]))

    @blueprint.get('/collections/<collection_id>/history')
    def history(collection_id):
        store = select(collection_id)
        editor = request.args.get('editor','')
        if len(editor)>120:
            abort(400,description='Use an editor filter of at most 120 characters.')
        try:
            since, until = date_bounds(request.args.get('since',''),request.args.get('through',''))
            listing = data.history_page(store,page=positive('page',1),etymon=positive('etymon'),editor=editor,
                action=request.args.get('action',''),status=request.args.get('status',''),
                activities=request.args.get('activities')=='1',since=since,until=until)
        except ValueError as error:
            abort(400,description=str(error))
        return render_template('admin/history.html',section='history',listing=listing)

    @blueprint.get('/collections/<collection_id>/history/<int:event_id>')
    def event(collection_id,event_id):
        store = select(collection_id)
        try:
            record = data.history_detail(store,event_id)
        except KeyError:
            abort(404,description='No history event with that ID exists in this collection.')
        return render_template('admin/event.html',section='history',event=record)

    @blueprint.get('/collections/<collection_id>/editors')
    def editors(collection_id):
        store = select(collection_id)
        return render_template('admin/editors.html',section='editors',editors=data.active_editors(store),
            heartbeat=app.config['EDIT_HEARTBEAT_SECONDS'],lease=app.config['EDIT_LEASE_SECONDS'])

    return blueprint
