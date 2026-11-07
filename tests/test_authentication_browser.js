/* Optional real-browser login/session/identity regression. Temporary files only.
 * Requires Playwright + Chromium, as with test_cell_editor_browser.js.
 */
"use strict";
const assert = require('node:assert/strict');
const {spawn, execFileSync} = require('node:child_process');
const {once} = require('node:events');
const {mkdtempSync, rmSync} = require('node:fs');
const {tmpdir} = require('node:os');
const path = require('node:path');
const readline = require('node:readline');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const directory = mkdtempSync(path.join(tmpdir(), 'xldb-auth-browser-'));
const python = process.env.XLDB_PYTHON || path.join(root, '.venv/bin/python');
const password = 'temporary browser password';
const source = `
from pathlib import Path
import json,sys
from collection_catalog import CollectionCatalog
from main import create_app
from waitress import create_server
root=Path(sys.argv[1])
catalog=CollectionCatalog(root/'catalog.sqlite3')
a=catalog.create('Gastronomy')
b=catalog.create('Fashion')
catalog.store(a['id']).add_etymon('alpha')
catalog.store(b['id']).add_etymon('beta')
catalog.close()
app=create_app(catalog_path=root/'catalog.sqlite3')
app.extensions['access_control'].set_edit_password('temporary browser password')
server=create_server(app,host='127.0.0.1',port=0)
print(json.dumps({'port':server.effective_port,'a':a,'b':b}),flush=True)
server.run()
`;
const server = spawn(python, ['-u','-c',source,directory], {cwd:root,stdio:['ignore','pipe','inherit']});
async function waitState(page, predicate) {
  const deadline = Date.now()+45000;
  while (!(await page.evaluate(predicate))) {
    if (Date.now()>deadline) throw new Error(`Timed out: ${predicate}`);
    await new Promise(resolve => setTimeout(resolve,50));
  }
}
async function main() {
  let browser;
  try {
    const lines = readline.createInterface({input:server.stdout});
    const [line] = await Promise.race([once(lines,'line'),once(server,'exit').then(() => {throw new Error('Server exited');})]);
    const {port,a,b} = JSON.parse(line);
    const url = entry => `http://127.0.0.1:${port}/collections/${entry.id}/`;
    browser = await chromium.launch({headless:true});
    const context = await browser.newContext({viewport:{width:1600,height:1000}});
    context.setDefaultNavigationTimeout(60000);
    context.setDefaultTimeout(60000);
    const first = await context.newPage();
    const errors = [];
    const watch = page => page.on('pageerror',error => errors.push(error.message));
    watch(first);
    const payload = page => page.locator('.workspace-data').evaluate(el => JSON.parse(el.textContent));
    const ready = async page => {
      await page.locator('.detail-panel.grid-active').waitFor();
      await waitState(page,() => !document.querySelector('[aria-busy="true"]'));
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    };
    const cell = page => page.locator('.tabulator-row [tabulator-field="content_0"]').first();
    const login = async (page,name,secret=password) => {
      await page.getByRole('textbox',{name:'Name',exact:true}).fill(name);
      await page.getByLabel('Edit password',{exact:true}).fill(secret);
      await page.getByRole('button',{name:'Sign in',exact:true}).click();
    };
    const loginFinished = async page => {
      await page.locator('#editor-login-dialog').waitFor({state:'hidden'});
      await waitState(page,() => JSON.parse(document.querySelector('.workspace-data').textContent).auth.authenticated);
      await ready(page);
    };
    const history = entry => JSON.parse(execFileSync(python,['-c',`
import json,sqlite3,sys
connection=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True)
connection.row_factory=sqlite3.Row
print(json.dumps([dict(row) for row in connection.execute("SELECT * FROM edit_history WHERE action='save_cell' AND status='saved' ORDER BY id")]))
connection.close()
`,entry.database_path],{encoding:'utf8'}));

    await first.goto(url(a));
    await ready(first);
    assert.equal((await payload(first)).auth.authenticated,false);
    await cell(first).dblclick();
    assert.equal(await first.locator('.cell-editor').count(),0);
    const downloadEvent = first.waitForEvent('download');
    await first.getByRole('link',{name:'Export Excel',exact:true}).click();
    await downloadEvent;
    console.log('ok - Anonymous visitors can browse and download while cells remain read-only');

    await first.getByRole('button',{name:'Edit mode',exact:true}).click();
    await first.getByRole('heading',{name:'Who is editing?',exact:true}).waitFor();
    await login(first,'Ana','wrong');
    await first.locator('.login-error').filter({hasText:'Incorrect edit password'}).waitFor();
    assert.equal(await first.getByLabel('Edit password',{exact:true}).inputValue(),'');
    assert.equal((await payload(first)).edit_mode,false);
    await first.getByRole('button',{name:'Cancel',exact:true}).click();
    await first.getByRole('button',{name:'Edit mode',exact:true}).click();
    assert.equal(await first.getByRole('textbox',{name:'Name',exact:true}).inputValue(),'');
    await login(first,'Ana Șerban');
    await loginFinished(first);
    assert.equal((await payload(first)).edit_mode,true);
    assert.equal(await first.locator('[data-editor-name]').textContent(),'Ana Șerban');
    const sessionCookie = (await context.cookies()).find(cookie => cookie.name==='session');
    assert.equal(sessionCookie.expires,-1);
    assert.equal(sessionCookie.httpOnly,true);
    await first.getByRole('button',{name:'Edit mode',exact:true}).click();
    await waitState(first,() => !JSON.parse(document.querySelector('.workspace-data').textContent).edit_mode);
    await ready(first);
    assert.equal((await payload(first)).auth.authenticated,true);
    await first.getByRole('button',{name:'Edit mode',exact:true}).click();
    await waitState(first,() => JSON.parse(document.querySelector('.workspace-data').textContent).edit_mode);
    await ready(first);
    assert.equal(await first.locator('#editor-login-dialog').isVisible(),false);
    console.log('ok - Wrong passwords and Cancel preserve Search mode; login uses a session cookie and survives mode changes');

    await cell(first).dblclick();
    await first.locator('.ql-editor').fill('alpha saved by Ana');
    await first.keyboard.press('Control+Enter');
    await first.locator('.cell-editor').waitFor({state:'detached'});
    await ready(first);
    const second = await context.newPage();
    watch(second);
    await second.goto(url(b));
    await ready(second);
    assert.equal((await payload(second)).auth.name,'Ana Șerban');
    assert.equal((await payload(second)).edit_mode,false);
    await second.getByRole('button',{name:'Edit mode',exact:true}).click();
    await waitState(second,() => JSON.parse(document.querySelector('.workspace-data').textContent).edit_mode);
    await ready(second);
    await cell(second).dblclick();
    await second.locator('.ql-editor').fill('beta saved by Ana');
    await second.keyboard.press('Control+Enter');
    await second.locator('.cell-editor').waitFor({state:'detached'});
    await ready(second);
    assert.equal(history(a)[0].editor_name,'Ana Șerban');
    assert.equal(history(b)[0].editor_name,'Ana Șerban');
    console.log('ok - One login covers collections and tabs; saved edits retain the correct editor in each database');

    await cell(first).dblclick();
    await first.locator('.cell-editor').waitFor();
    await first.getByRole('button',{name:'Change editor',exact:true}).click();
    assert.equal(await first.locator('#editor-login-dialog').isVisible(),false);
    await first.getByRole('button',{name:'Sign out',exact:true}).click();
    assert.equal((await payload(first)).auth.authenticated,true);
    await first.keyboard.press('Escape');
    await first.locator('.cell-editor').waitFor({state:'detached'});
    await first.getByRole('button',{name:'Change editor',exact:true}).click();
    await first.getByRole('button',{name:'Cancel',exact:true}).click();
    assert.equal(await first.locator('[data-editor-name]').textContent(),'Ana Șerban');
    await second.getByRole('button',{name:'Add row',exact:true}).click();
    await second.getByRole('button',{name:'SENSURI DE BAZĂ',exact:true}).click();
    await second.getByLabel('Text for LIMBA FRANCEZĂ',{exact:true}).fill('old Ana row draft');
    await first.getByRole('button',{name:'Change editor',exact:true}).click();
    await login(first,'Mihai');
    await loginFinished(first);
    assert.equal((await payload(first)).auth.name,'Mihai');
    await second.getByRole('button',{name:'Create',exact:true}).click();
    await second.locator('.creation-error').filter({hasText:'editor changed'}).waitFor();
    assert.equal(await second.getByLabel('Text for LIMBA FRANCEZĂ',{exact:true}).inputValue(),'old Ana row draft');
    await second.getByRole('button',{name:'Cancel',exact:true}).click();
    // This other tab still holds a token created under Ana's revoked login.
    await cell(second).dblclick();
    await second.locator('#request-status').filter({hasText:'expired'}).waitFor();
    assert.equal(await second.locator('.cell-editor').count(),0);
    assert.equal(history(b).length,1);
    await second.reload();
    await ready(second);
    assert.equal((await payload(second)).auth.name,'Mihai');
    await cell(second).dblclick();
    await second.locator('.ql-editor').fill('beta saved by Mihai');
    await second.keyboard.press('Control+Enter');
    await second.locator('.cell-editor').waitFor({state:'detached'});
    await ready(second);
    assert.equal(history(b)[1].editor_name,'Mihai');
    console.log('ok - Identity changes require closed drafts; old tokens cannot be saved as the replacement editor');

    await first.getByRole('button',{name:'Sign out',exact:true}).click();
    await waitState(first,() => !JSON.parse(document.querySelector('.workspace-data').textContent).auth.authenticated);
    await ready(first);
    await second.reload();
    await ready(second);
    assert.equal((await payload(second)).edit_mode,false);
    assert.equal((await payload(second)).auth.authenticated,false);
    await first.getByRole('button',{name:'Edit mode',exact:true}).click();
    await login(first,'Ana');
    await loginFinished(first);
    const fresh = await browser.newContext();
    fresh.setDefaultNavigationTimeout(60000);
    fresh.setDefaultTimeout(60000);
    const laterVisit = await fresh.newPage();
    watch(laterVisit);
    await laterVisit.goto(url(a));
    await ready(laterVisit);
    assert.equal((await payload(laterVisit)).auth.authenticated,false);
    await laterVisit.getByRole('button',{name:'Edit mode',exact:true}).click();
    await laterVisit.getByRole('heading',{name:'Who is editing?',exact:true}).waitFor();
    await fresh.close();
    console.log('ok - Sign out revokes access across tabs, and a fresh browser session requires another login');

    await cell(first).dblclick();
    await first.locator('.ql-editor').fill('draft before password change');
    execFileSync(python,['-c',`
from access_control import AccessControl
import sys
access=AccessControl(sys.argv[1]);access.set_edit_password('replacement password');access.close()
`,path.join(directory,'access.sqlite3')],{cwd:root});
    await first.keyboard.press('Control+Enter');
    await first.locator('.cell-editor [role="status"]').filter({hasText:'Sign in to edit'}).waitFor();
    assert.equal(await first.locator('.ql-editor').innerText(),'draft before password change');
    await first.keyboard.press('Escape');
    await first.locator('.cell-editor').waitFor({state:'detached'});
    await first.reload();
    await ready(first);
    assert.equal((await payload(first)).edit_mode,false);
    await first.getByRole('button',{name:'Edit mode',exact:true}).click();
    await login(first,'Ana',password);
    await first.locator('.login-error').filter({hasText:'Incorrect edit password'}).waitFor();
    await login(first,'Ana','replacement password');
    await loginFinished(first);
    assert.equal(history(a).length,1);
    assert.deepEqual(errors,[]);
    console.log('ok - Password changes revoke open sessions immediately and preserve rejected drafts without recording edits');
    console.log('Authentication browser checks passed.');
  } finally {
    if (browser) await browser.close();
    if (server.exitCode===null) {
      const stopped = once(server,'exit');
      server.kill('SIGTERM');
      await stopped;
    }
    rmSync(directory,{recursive:true,force:true});
  }
}
main().catch(error => {console.error(error);process.exitCode=1;});
