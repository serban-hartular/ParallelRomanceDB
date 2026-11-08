/* Real-browser exclusivity, warnings, idle heartbeats, expiry, and history.
 * Uses temporary files and short test-only lease settings, never a live server.
 */
"use strict";
const assert = require('node:assert/strict');
const {spawn,execFileSync} = require('node:child_process');
const {once} = require('node:events');
const {mkdtempSync,rmSync} = require('node:fs');
const {tmpdir} = require('node:os');
const path = require('node:path');
const readline = require('node:readline');
const {chromium} = require('playwright');
const root = path.resolve(__dirname,'..');
const directory = mkdtempSync(path.join(tmpdir(),'xldb-cell-leases-'));
const python = process.env.XLDB_PYTHON || path.join(root,'.venv/bin/python');
const source = `
import json,sys
from pathlib import Path
from collection_catalog import CollectionCatalog
from df_search import LABEL_ORDER
from main import create_app
from waitress import create_server
root=Path(sys.argv[1]); catalog=CollectionCatalog(root/'catalog.sqlite3')
a=catalog.create('Gastronomy'); b=catalog.create('Fashion')
for entry in (a,b):
    store=catalog.store(entry['id'])
    store.add_etymon('headword')
    store.add_row(1,LABEL_ORDER[1],'sense one')
    store.add_row(1,LABEL_ORDER[1],'sense two')
catalog.close()
app=create_app(catalog_path=root/'catalog.sqlite3',test_config={'EDIT_HEARTBEAT_SECONDS':1,'EDIT_LEASE_SECONDS':6})
app.extensions['access_control'].set_edit_password('temporary browser password')
app.config['DEFAULT_UI_LANGUAGE']='en'
server=create_server(app,host='127.0.0.1',port=0)
print(json.dumps({'port':server.effective_port,'a':a,'b':b}),flush=True)
server.run()
`;
const server=spawn(python,['-u','-c',source,directory],{cwd:root,stdio:['ignore','pipe','inherit']});
async function waitState(page,predicate) {
 const deadline=Date.now()+45000;
 while (!(await page.evaluate(predicate))) {
  if(Date.now()>deadline) throw new Error(`Timed out: ${predicate}`);
  await new Promise(resolve=>setTimeout(resolve,50));
 }
}
async function main() {
 let browser;
 try {
  const lines=readline.createInterface({input:server.stdout});
  const [line]=await Promise.race([once(lines,'line'),once(server,'exit').then(()=>{throw new Error('Server exited');})]);
  const {port,a,b}=JSON.parse(line);
  const url=entry=>`http://127.0.0.1:${port}/collections/${entry.id}/`;
  browser=await chromium.launch({headless:true});
  const anaContext=await browser.newContext({viewport:{width:1600,height:1000}});
  const bobContext=await browser.newContext({viewport:{width:1600,height:1000}});
  for (const context of [anaContext,bobContext]) {
   context.setDefaultNavigationTimeout(60000);
   context.setDefaultTimeout(60000);
  }
  const ana=await anaContext.newPage(); const bob=await bobContext.newPage();
  const errors=[];
  for(const page of [ana,bob]) page.on('pageerror',error=>errors.push(error.message));
  const payload=page=>page.locator('.workspace-data').evaluate(el=>JSON.parse(el.textContent));
  const ready=async page=>{
   await page.locator('.detail-panel.grid-active').waitFor();
   await waitState(page,()=>!document.querySelector('[aria-busy="true"]'));
   await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  };
  const cell=(page,row=1,field='content_0')=>page.locator(`.tabulator-row [tabulator-field="${field}"]`).nth(row);
  const open=async(page,row=1,field='content_0')=>{
   const response=page.waitForResponse(response=>new URL(response.url()).pathname.endsWith('/cell/start'));
   await cell(page,row,field).dblclick();
   const result=await response;
   assert.equal(result.status(),201,await result.text());
   await page.locator('.ql-editor').waitFor();
   return result.json();
  };
  const cancel=async page=>{
   await page.getByRole('button',{name:'Cancel',exact:true}).click();
   await page.locator('.cell-editor').waitFor({state:'detached'});
  };
  const save=async page=>{
   await page.keyboard.press('Control+Enter');
   await page.locator('.cell-editor').waitFor({state:'detached'});
   await ready(page);
  };
  const history=()=>JSON.parse(execFileSync(python,['-c',`
import json,sqlite3,sys
connection=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True); connection.row_factory=sqlite3.Row
print(json.dumps([dict(row) for row in connection.execute("SELECT * FROM edit_history WHERE action='save_cell' ORDER BY id")]))
connection.close()
`,a.database_path],{encoding:'utf8'}));
  for(const [page,name] of [[ana,'Ana'],[bob,'Bob']]) {
   await page.goto(url(a)); await ready(page);
   await page.getByRole('button',{name:'Edit mode',exact:true}).click();
   await page.getByRole('textbox',{name:'Name',exact:true}).fill(name);
   await page.getByLabel('Edit password',{exact:true}).fill('temporary browser password');
   await page.getByRole('button',{name:'Sign in',exact:true}).click();
   await page.locator('#editor-login-dialog').waitFor({state:'hidden'});
   await waitState(page,()=>JSON.parse(document.querySelector('.workspace-data').textContent).edit_mode);
   await ready(page);
  }
  const anaOpened=await open(ana);
  await ana.locator('.ql-editor').fill('Ana original draft');
  await cell(bob).dblclick();
  await bob.locator('#request-status').filter({hasText:'Ana is editing this cell'}).waitFor();
  assert.equal(await bob.locator('.cell-editor').count(),0);
  for(const target of ['row','etymon']) {
   if(target==='row') await bob.getByRole('button',{name:/^Delete row:/}).first().click();
   else await bob.getByRole('button',{name:'Delete etymon',exact:true}).click();
   await bob.getByLabel('Type DELETE to confirm',{exact:true}).fill('DELETE');
   await bob.getByRole('button',{name:'Move to Trash',exact:true}).click();
   await bob.locator('.deletion-error').filter({hasText:'Ana'}).waitFor();
   await bob.getByRole('button',{name:'Cancel',exact:true}).click();
  }
  assert.equal((await payload(bob)).rows.length,3);
  console.log('ok - Named cell denial and row/etymon deletion protection are enforced on the server');

  await open(bob,1,'content_1');
  assert.equal(await bob.locator('#request-status').evaluate(el=>el.classList.contains('is-error')),false);
  await bob.locator('.cell-editor-notice').filter({hasText:'Ana is editing another cell in this row'}).waitFor();
  await cancel(bob);
  const bobOther=await open(bob,2);
  await bob.locator('.cell-editor-notice').filter({hasText:'Ana is editing another row in this etymon'}).waitFor();
  await bob.locator('.ql-editor').fill('Bob other sense');
  await save(bob);
  const saved=history().find(event=>event.id===bobOther.edit_id);
  assert.equal(saved.status,'saved'); assert.equal(saved.editor_name,'Bob');
  assert.equal(JSON.parse(saved.after_json).plaintext_content,'Bob other sense');
  assert.ok(saved.started_at && saved.finished_at);
  assert.equal(history().filter(event=>event.id===bobOther.edit_id).length,1);
  console.log('ok - Same-row and same-etymon inline notices allow other-cell edits; saving completes the original record');

  // Wait beyond the initial lease without touching Ana's editor. Contacts,
  // including while another browser is active, must keep it protected.
  const lastSeen=history().find(event=>event.id===anaOpened.edit_id).last_seen_at;
  await new Promise(resolve=>setTimeout(resolve,7000));
  const active=history().find(event=>event.id===anaOpened.edit_id);
  assert.equal(active.status,'active'); assert.ok(active.last_seen_at>lastSeen);
  const sameLoginTab=await anaContext.newPage();
  sameLoginTab.on('pageerror',error=>errors.push(error.message));
  await sameLoginTab.goto(url(a)); await ready(sameLoginTab);
  await cell(sameLoginTab).dblclick();
  await sameLoginTab.locator('#request-status').filter({hasText:'Ana is editing this cell'}).waitFor();
  assert.equal(await sameLoginTab.locator('.cell-editor').count(),0);
  console.log('ok - Idle heartbeats retain locks and another tab with the same login cannot take over');
  await bob.locator('#collection-select').selectOption(`/collections/${b.id}/`);
  await bob.waitForURL(url(b)); await ready(bob);
  await bob.getByRole('button',{name:'Edit mode',exact:true}).click();
  await waitState(bob,()=>JSON.parse(document.querySelector('.workspace-data').textContent).edit_mode);
  await ready(bob); await open(bob);
  assert.equal(await bob.locator('.cell-editor-notice').isVisible(),false);
  await cancel(bob);
  await bob.locator('#collection-select').selectOption(`/collections/${a.id}/`);
  await bob.waitForURL(url(a)); await ready(bob);
  console.log('ok - Editing notices and locks remain isolated to their collection');

  await cancel(ana);
  assert.equal(history().find(event=>event.id===anaOpened.edit_id).status,'cancelled');
  const bobOpened=await open(bob);
  const stalePayload=await payload(bob);
  await bob.locator('.ql-editor').fill('Bob disconnected draft');
  await bobContext.setOffline(true);
  await bob.locator('.cell-editor [role="status"]').filter({hasText:'expired'}).waitFor({timeout:20000});
  assert.equal(await bob.locator('.ql-editor').innerText(),'Bob disconnected draft');
  assert.equal(await bob.getByRole('button',{name:'Close',exact:true}).isDisabled(),true);
  await new Promise(resolve=>setTimeout(resolve,1000));
  const winner=await open(ana);
  await ana.locator('.ql-editor').fill('Ana after expiry');
  assert.equal(history().find(event=>event.id===bobOpened.edit_id).status,'expired');
  await bobContext.setOffline(false);
  const stale=await bob.request.post(`${url(a)}cell`,{headers:{'X-CSRF-Token':stalePayload.csrf},data:{
   token:stalePayload.rows[1].editors.content_0.token,lease:bobOpened.lease,ops:[{insert:'stale overwrite\n'}],
  }});
  assert.equal(stale.status(),409);
  await bob.keyboard.press('Escape');
  await bob.locator('.cell-editor').waitFor({state:'detached'});
  await cell(sameLoginTab).dblclick();
  await sameLoginTab.locator('#request-status').filter({hasText:'Ana is editing this cell'}).waitFor();
  await save(ana);
  assert.equal(history().find(event=>event.id===winner.edit_id).status,'saved');
  assert.equal(history().filter(event=>event.status==='saved').length,2);
  console.log('ok - Disconnection expires the lock, preserves a copyable draft, and rejects stale saves/releases after another editor takes over');

  const unchanged=await open(ana,0);
  await ana.getByRole('button',{name:'Close',exact:true}).click();
  await ana.locator('.cell-editor').waitFor({state:'detached'});
  assert.equal(history().find(event=>event.id===unchanged.edit_id).status,'unchanged');
  assert.equal(history().filter(event=>event.status==='saved').length,2);
  const abandoned=await open(ana,0);
  await ana.reload(); await ready(ana);
  const reopened=await open(ana,0);
  assert.notEqual(reopened.edit_id,abandoned.edit_id);
  await cancel(ana);
  assert.equal(history().find(event=>event.id===abandoned.edit_id).status,'cancelled');
  console.log('ok - Unchanged Close and page departure release locks and remain distinct from saved changes');
  assert.deepEqual(errors,[]);
  console.log('Cell lease browser checks passed.');
 } finally {
  if(browser) await browser.close();
  if(server.exitCode===null) {const stopped=once(server,'exit');server.kill('SIGTERM');await stopped;}
  rmSync(directory,{recursive:true,force:true});
 }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
