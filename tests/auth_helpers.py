"""Authenticate regression clients through the real login endpoint."""

from tests.test_flask_app import Page

PASSWORD = 'temporary regression password'


def authenticate(client, payload=None, url='/'):
    access = client.application.extensions['access_control']
    if not access.configured():
        access.set_edit_password(PASSWORD)
    payload = payload or Page(client.get(url)).payload
    if not payload['auth']['authenticated']:
        response = client.post('/auth/login',json={'name':'Test editor','password':PASSWORD},
                               headers={'X-CSRF-Token':payload['csrf']})
        assert response.status_code == 200, response.json
        payload = Page(client.get(url)).payload
    client.environ_base['HTTP_X_EDITOR_SESSION'] = payload['auth']['identity']
    return payload


def save_edit(client, payload, ops, *, token=None, row=0, field='content_0', **formatting):
    """Open and complete one editor; failed saves discard this test draft."""
    token = token or payload['rows'][row]['editors'][field]['token']
    headers = {'X-CSRF-Token':payload['csrf']}
    opened = client.post(payload['urls']['edit_start'],json={'token':token},headers=headers)
    if opened.status_code != 201:
        return opened
    lease = opened.json['lease']
    response = client.post(payload['urls']['cell'],json={
        'token':token,'lease':lease,'ops':ops,**formatting,
    },headers=headers)
    if response.status_code != 200:
        client.post(payload['urls']['edit_finish'],json={'lease':lease,'outcome':'cancelled'},headers=headers)
    return response
