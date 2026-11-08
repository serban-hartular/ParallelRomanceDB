"""Bounded, collection-local queries for the HTML administration interface."""

from i18n import gettext as _

import json


ACTIONS = {
    'save_cell':'Cell edit', 'add_row':'Row added', 'add_etymon':'Etymon added',
    'delete_row':'Row deleted', 'delete_etymon':'Etymon deleted', 'restore_trash':'Recovered from Trash',
}
STATUSES = ('active','saved','cancelled','unchanged','expired','revoked')
PAGE_SIZE = 50


def _page(connection, sql, values, page, *, count_sql):
    total = connection.execute(count_sql,values).fetchone()[0]
    items = [dict(row) for row in connection.execute(sql+' LIMIT ? OFFSET ?',
                                                   [*values,PAGE_SIZE,(page-1)*PAGE_SIZE])]
    return {'items':items,'total':total,'page':page,'previous':page-1 if page>1 else None,
            'next':page+1 if page*PAGE_SIZE<total else None}


def overview(store):
    store.expire_edits()
    with store.transaction():
        connection = store.connection
        latest = connection.execute("SELECT id,editor_name,action,occurred_at FROM edit_history WHERE status='saved' ORDER BY occurred_at DESC,id DESC LIMIT 1").fetchone()
        return {
            'etymons':connection.execute('SELECT count(DISTINCT etimon_number) FROM row_metadata WHERE trash_id IS NULL').fetchone()[0],
            'trash':connection.execute('SELECT count(*) FROM trash WHERE restored_at IS NULL').fetchone()[0],
            'editors':connection.execute("SELECT count(*) FROM edit_history WHERE status='active'").fetchone()[0],
            'latest':dict(latest) if latest else None,
        }


def trash_page(store, *, page=1, etymon=None, kind='', recovered=False):
    scope, values = ['t.restored_at IS NOT NULL' if recovered else 't.restored_at IS NULL'], []
    if etymon is not None:
        scope.append('t.etimon_number=?'); values.append(etymon)
    if kind:
        if kind not in ('row','etymon'):
            raise ValueError(_('Choose a valid Trash item type.'))
        scope.append('t.kind=?'); values.append(kind)
    where = ' WHERE '+' AND '.join(scope)
    with store.transaction():
        sql = '''SELECT t.*,
            (SELECT count(*) FROM row_metadata r WHERE r.trash_id=t.id) AS row_count,
            (SELECT count(*) FROM cells c JOIN row_metadata r ON r.id=c.row_id WHERE r.trash_id=t.id) AS cell_count,
            (SELECT editor_name FROM edit_history h WHERE h.trash_id=t.id AND h.action IN ('delete_row','delete_etymon') ORDER BY id LIMIT 1) AS deleted_by
            FROM trash t'''+where+' ORDER BY t.deleted_at DESC,t.id DESC'
        return _page(store.connection,sql,values,page,count_sql='SELECT count(*) FROM trash t'+where)


def trash_detail(store, identifier):
    with store.transaction():
        connection = store.connection
        row = connection.execute('''SELECT t.*,
            (SELECT editor_name FROM edit_history h WHERE h.trash_id=t.id AND h.action IN ('delete_row','delete_etymon') ORDER BY id LIMIT 1) AS deleted_by
            FROM trash t WHERE t.id=?''',(identifier,)).fetchone()
        if row is None:
            raise KeyError(identifier)
        result = dict(row)
        row_count = connection.execute('SELECT count(*) FROM row_metadata WHERE trash_id=?',(identifier,)).fetchone()[0]
        cell_count = connection.execute('SELECT count(*) FROM cells c JOIN row_metadata r ON r.id=c.row_id WHERE r.trash_id=?',(identifier,)).fetchone()[0]
        rows = [dict(row) for row in connection.execute('SELECT * FROM row_metadata WHERE trash_id=? ORDER BY sheet_row LIMIT 200',(identifier,))]
        cells = [dict(row) for row in connection.execute('''SELECT c.*,r.label,r.label_number,d.name AS "column"
            FROM cells c JOIN row_metadata r ON r.id=c.row_id JOIN column_definitions d ON d.id=c.column_id
            WHERE r.trash_id=? ORDER BY r.sheet_row,d.display_order,d.id LIMIT 200''',(identifier,))]
        if result['restored_at']:
            old = connection.execute("SELECT before_json FROM edit_history WHERE trash_id=? AND action IN ('delete_row','delete_etymon') ORDER BY id LIMIT 1",(identifier,)).fetchone()
            snapshot = json.loads(old[0]) if old and old[0] else {}
            rows, cells = snapshot.get('rows',[]), snapshot.get('cells',[])
            row_count, cell_count = len(rows), len(cells)
        result.update(rows=rows[:200],cells=cells[:200],row_count=row_count,cell_count=cell_count,truncated=cell_count>200)
        parent_deleted = result['kind']=='row' and not connection.execute(
            'SELECT 1 FROM row_metadata WHERE etimon_number=? AND trash_id IS NULL',(result['etimon_number'],)).fetchone()
        parent = connection.execute("SELECT id FROM trash WHERE kind='etymon' AND restored_at IS NULL AND etimon_number=? ORDER BY id DESC LIMIT 1",(result['etimon_number'],)).fetchone() if parent_deleted else None
        result.update(parent_deleted=bool(parent_deleted),parent_id=parent[0] if parent else None)
        return result


def history_page(store, *, page=1, etymon=None, editor='', action='', status='', activities=False, since=None, until=None):
    scope, values = [], []
    if status and status not in STATUSES:
        raise ValueError(_('Choose a valid editing outcome.'))
    if action and action not in ACTIONS:
        raise ValueError(_('Choose a valid history action.'))
    if status:
        scope.append('status=?'); values.append(status)
    elif not activities:
        scope.append("status='saved'")
    for expression,value in [('etimon_number=?',etymon),('instr(search_fold(editor_name),?)>0',editor.upper() if editor else None),
                              ('action=?',action or None),('occurred_at>=?',since),('occurred_at<?',until)]:
        if value is not None:
            scope.append(expression); values.append(value)
    where = (' WHERE '+' AND '.join(scope)) if scope else ''
    store.expire_edits()
    with store.transaction():
        sql = '''SELECT id,editor_name,action,status,occurred_at,started_at,finished_at,
            etimon_number,label,label_number,column_name FROM edit_history'''+where+' ORDER BY occurred_at DESC,id DESC'
        return _page(store.connection,sql,values,page,count_sql='SELECT count(*) FROM edit_history'+where)


def history_detail(store, identifier):
    store.expire_edits()
    with store.transaction():
        row = store.connection.execute('SELECT * FROM edit_history WHERE id=?',(identifier,)).fetchone()
        if row is None:
            raise KeyError(identifier)
        # No identity or lease hashes are passed to the templates.
        result = {key:row[key] for key in ('id','editor_name','action','status','occurred_at','started_at',
                  'last_seen_at','expires_at','finished_at','etimon_number','label','label_number','column_name','trash_id')}
        for field in ('before','after'):
            result[field] = json.loads(row[field+'_json']) if row[field+'_json'] else None
        return result


def active_editors(store):
    store.expire_edits()
    with store.transaction():
        return [dict(row) for row in store.connection.execute('''SELECT id,editor_name,etimon_number,
            label,label_number,column_name,started_at,last_seen_at,expires_at
            FROM edit_history WHERE status='active' ORDER BY started_at DESC,id DESC''')]


def snapshot_cells(snapshot):
    if not isinstance(snapshot,dict):
        return []
    if 'cells' in snapshot:
        return snapshot['cells']
    return [snapshot] if 'content' in snapshot else []
