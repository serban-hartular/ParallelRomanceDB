/* Temporary-server browser checks for automatic updates and protected drafts. */
'use strict';
const assert = require('node:assert/strict');
const {spawn,execFileSync} = require('node:child_process');
const {once} = require('node:events');
const {mkdtempSync,rmSync} = require('node:fs');
const {tmpdir} = require('node:os');
const path = require('node:path');
const readline = require('node:readline');
const {chromium} = require('playwright');
const root = path.resolve(__dirname,'..');
const directory = mkdtempSync(path.join(tmpdir(),'xldb-live-updates-'));
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
store=catalog.store(a['id'])
store.add_etymon('Alpha'); store.add_etymon('Beta')
for n in range(35): store.add_row(1,LABEL_ORDER[1],f'sense {n}')
catalog.store(b['id']).add_etymon('Fashion term')
catalog.close()
app=create_app(catalog_path=root/'catalog.sqlite3',test_config={'LIVE_REFRESH_SECONDS':1,'EDIT_HEARTBEAT_SECONDS':1,'EDIT_LEASE_SECONDS':30})
app.extensions['access_control'].set_edit_password('temporary browser password')
server=create_server(app,host='127.0.0.1',port=0)
print(json.dumps({'port':server.effective_port,'a':a,'b':b}),flush=True)
server.run()
`;
const server=spawn(python,['-u','-c',source,directory],{cwd:root,stdio:['ignore','pipe','inherit']});
async function waitFor(predicate, description='condition') {
 const until=Date.now()+45000;
 while(!(await predicate())) {
  if(Date.now()>until) throw new Error(`Timed out: ${description}`);
  await new Promise(resolve=>setTimeout(resolve,60));
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
  const viewerContext=await browser.newContext({viewport:{width:1200,height:780}});
  const editorContext=await browser.newContext({viewport:{width:1200,height:780}});
  for(const context of [viewerContext,editorContext]) {context.setDefaultTimeout(45000);context.setDefaultNavigationTimeout(60000);}
  const viewer=await viewerContext.newPage(), editor=await editorContext.newPage();
  const errors=[];
  for(const page of [viewer,editor]) page.on('pageerror',error=>errors.push(error.message));
  const payload=page=>page.locator('.workspace-data').evaluate(el=>JSON.parse(el.textContent));
  const ready=async page=>{
   await page.locator('.grid-active').waitFor();
   await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  };
  const cell=(page,row=0,field='content_0')=>page.locator(`.tabulator-row [tabulator-field="${field}"]`).nth(row);
  const login=async(page,name)=>{
   await page.getByRole('button',{name:'Edit mode',exact:true}).click();
   await page.getByRole('textbox',{name:'Name',exact:true}).fill(name);
   await page.getByLabel('Edit password',{exact:true}).fill('temporary browser password');
   await page.getByRole('button',{name:'Sign in',exact:true}).click();
   await page.locator('#editor-login-dialog').waitFor({state:'hidden'});
   await waitFor(async()=> (await payload(page)).edit_mode,'edit mode');
   await ready(page);
  };
  const open=async(page,row=0,field='content_0')=>{
   await cell(page,row,field).dblclick();
   await page.locator('.ql-editor').waitFor();
  };
  const close=async(page,save=false)=>{
   if(save) await page.keyboard.press('Control+Enter');
   else await page.getByRole('button',{name:'Cancel',exact:true}).click();
   await page.locator('.cell-editor').waitFor({state:'detached'});
   if(save) await ready(page);
  };
  const local=(code,entry=a)=>JSON.parse(execFileSync(python,['-c',`
import json,sys
from lexicon_db import LexiconDB
from df_search import LABEL_ORDER
store=LexiconDB(sys.argv[1])
${code}
store.close()
`,entry.database_path],{cwd:root,encoding:'utf8'}));
  const change=(text,entry=a)=>local(`key=(1,LABEL_ORDER[0],1,'LIMBA FRANCEZĂ')\nstore.save_cell(key,store.cell(key)['revision'],[{'insert':${JSON.stringify(text+'\n')}}])\nprint(json.dumps(store.content_version()))`,entry);
  let checks=0, refreshes=0;
  viewer.on('response',response=>{
   if(new URL(response.url()).pathname.endsWith('/changes')) checks++;
   if(new URL(response.url()).searchParams.get('live')==='1') refreshes++;
  });
  await viewer.goto(url(a)); await ready(viewer);
  await editor.goto(url(a)); await ready(editor); await login(editor,'Ana');
  const initialChecks=checks, initialRefreshes=refreshes;
  await waitFor(()=>checks>=initialChecks+2,'idle checks');
  assert.equal(refreshes,initialRefreshes);
  console.log('ok - Public readers check lightweight versions without repeatedly fetching the workspace');

  // Browser-only state must survive a remote save, including unsubmitted search.
  await viewer.evaluate(()=>{
   window.liveTestSentinel='same document';
   const table=Tabulator.findTable('#etimon-grid')[0];
   table.getColumn('content_0').setWidth(420);
   table.getColumn('content_2').hide();
   const viewport=document.querySelector('.tabulator-tableholder');
   viewport.scrollTop=420;viewport.scrollLeft=260;
  });
  await viewer.locator('#query').fill('unsubmitted search');
  await viewer.locator('#query').evaluate(el=>el.setSelectionRange(4,4));
  const position=()=>viewer.locator('.tabulator-tableholder').evaluate(el=>({left:el.scrollLeft,top:el.scrollTop}));
  const before=await position();
  assert.ok(before.left>0 && before.top>0);
  await open(editor); await editor.locator('.ql-editor').fill('Alpha updated by Ana'); await close(editor,true);
  await waitFor(async()=> (await payload(viewer)).rows[0].content_0.includes('Alpha updated by Ana'),'remote save');
  await ready(viewer);
  const after=await position();
  assert.ok(Math.abs(before.left-after.left)<=2,JSON.stringify({before,after}));
  assert.ok(Math.abs(before.top-after.top)<=2,JSON.stringify({before,after}));
  assert.equal(await viewer.locator('#query').inputValue(),'unsubmitted search');
  assert.equal(await viewer.evaluate(()=>document.activeElement.id),'query');
  assert.equal(await viewer.evaluate(()=>document.activeElement.selectionStart),4);
  assert.equal(await viewer.evaluate(()=>window.liveTestSentinel),'same document');
  assert.equal(await viewer.evaluate(()=>Tabulator.findTable('#etimon-grid')[0].getColumn('content_0').getWidth()),420);
  assert.equal(await viewer.evaluate(()=>Tabulator.findTable('#etimon-grid')[0].getColumn('content_2').isVisible()),false);
  assert.ok((await viewer.locator('#detail-heading').innerText()).includes('Alpha updated by Ana'));
  console.log('ok - Another user’s save updates table and title without reload, losing focus, layout, search draft or scroll');

  await login(viewer,'Bob');
  await open(viewer,1); await viewer.locator('.ql-editor').fill('Bob unsaved draft');
  const version=(await payload(viewer)).content_version;
  change('Alpha while Bob edits');
  await viewer.locator('#live-update-status').filter({hasText:'close the cell editor'}).waitFor();
  assert.equal((await payload(viewer)).content_version,version);
  assert.equal(await viewer.locator('.ql-editor').innerText(),'Bob unsaved draft');
  assert.equal(await viewer.locator('.ql-editor').getAttribute('contenteditable'),'true');
  await close(viewer);
  await waitFor(async()=> (await payload(viewer)).rows[0].content_0.includes('Alpha while Bob edits'),'refresh after cancel');
  await viewer.locator('#live-update-status').waitFor({state:'hidden'});
  console.log('ok - Open editors retain their draft and lock, show an update notice, and refresh after Cancel');

  await viewer.getByRole('button',{name:'Add etymon',exact:true}).click();
  await viewer.locator('#create-entry-text').fill('my unfinished entry');
  const added=local("result=store.add_row(1,LABEL_ORDER[1],'remotely added sense')\nprint(json.dumps(result))");
  await viewer.locator('#live-update-status').filter({hasText:'current operation finishes'}).waitFor();
  assert.equal(await viewer.locator('#create-entry-text').inputValue(),'my unfinished entry');
  assert.equal((await payload(viewer)).rows.length,36);
  await viewer.getByRole('button',{name:'Cancel',exact:true}).click();
  await waitFor(async()=> (await payload(viewer)).rows.length===37,'remote addition');
  local(`print(json.dumps(store.delete_row(1,LABEL_ORDER[1],${added.label_number})))`);
  await waitFor(async()=> (await payload(viewer)).rows.length===36,'remote row deletion');
  console.log('ok - Creation dialogs are protected; remote row additions and deletions update automatically');

  // Hold the refresh response until an editor has opened: it must be discarded.
  let held, release;
  const waiting=new Promise(resolve=>{held=resolve;});
  await viewer.route('**/*',async route=>{
   const requestUrl=new URL(route.request().url());
   if(requestUrl.searchParams.get('live')!=='1' || release) return route.continue();
   const response=await route.fetch();
   await new Promise(resolve=>{release=()=>{resolve();};held();});
   await route.fulfill({response});
  });
  change('Alpha delayed response');
  await waiting;
  await open(viewer,1);await viewer.locator('.ql-editor').fill('draft during delayed refresh');
  release();
  await viewer.locator('#live-update-status').filter({hasText:'close the cell editor'}).waitFor();
  assert.equal(await viewer.locator('.ql-editor').innerText(),'draft during delayed refresh');
  await viewer.unroute('**/*');
  await close(viewer,true);
  await waitFor(async()=> (await payload(viewer)).rows[0].content_0.includes('Alpha delayed response') && (await payload(viewer)).rows[1].content_0.includes('draft during delayed refresh'),'refresh after save');
  console.log('ok - A refresh arriving after an editor opens cannot replace its draft; Save fetches both users’ changes');

  // Failed checks retry automatically when connectivity returns.
  await viewerContext.setOffline(true);
  await viewer.locator('#live-update-status').filter({hasText:'Retrying automatically'}).waitFor();
  change('Alpha after reconnection');
  await viewerContext.setOffline(false);
  await waitFor(async()=> (await payload(viewer)).rows[0].content_0.includes('Alpha after reconnection'),'reconnect');
  console.log('ok - Temporary connection failures recover without a reload');

  const other=await viewerContext.newPage();
  other.on('pageerror',error=>errors.push(error.message));
  await other.goto(url(b));await ready(other);
  const aVersion=(await payload(viewer)).content_version;
  change('New fashion term',b);
  await waitFor(async()=> (await payload(other)).rows[0].content_0.includes('New fashion term'),'other collection refresh');
  await viewer.bringToFront();
  const count=checks;
  await waitFor(()=>checks>=count+2,'independent collection checks');
  assert.equal((await payload(viewer)).content_version,aVersion);
  assert.equal((await payload(viewer)).etimon,1);
  await other.close();
  console.log('ok - Different collection tabs refresh independently');

  const trash=local('print(json.dumps(store.delete_etymon(1)))');
  await waitFor(async()=> (await payload(viewer)).etimon===2,'deleted selected etymon');
  assert.ok((await viewer.locator('#detail-heading').innerText()).includes('Beta'));
  local('print(json.dumps(store.delete_etymon(2)))');
  await waitFor(async()=> (await payload(viewer)).etimon===null,'empty collection');
  await viewer.locator('.empty-state').waitFor();
  local(`store.restore_trash(${trash})\nprint(json.dumps(True))`);
  await waitFor(async()=> (await payload(viewer)).etimon===1,'local recovery');
  await ready(viewer);
  assert.equal((await payload(viewer)).rows.length,36);
  console.log('ok - Selected etymon deletion, an empty collection, and local Trash recovery all refresh navigation and content');
  assert.deepEqual(errors,[]);
  console.log('Live update browser checks passed.');
 } finally {
  if(browser) await browser.close();
  if(server.exitCode===null) {const stopped=once(server,'exit');server.kill('SIGTERM');await stopped;}
  rmSync(directory,{recursive:true,force:true});
 }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
