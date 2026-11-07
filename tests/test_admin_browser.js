/* Actual HTML admin workflows with JavaScript disabled, alongside a live editor. */
'use strict';
const assert=require('node:assert/strict');
const {spawn,execFileSync}=require('node:child_process');
const {once}=require('node:events');
const {mkdtempSync,rmSync}=require('node:fs');
const {tmpdir}=require('node:os');
const path=require('node:path');
const readline=require('node:readline');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..');
const directory=mkdtempSync(path.join(tmpdir(),'xldb-admin-browser-'));
const python=process.env.XLDB_PYTHON||path.join(root,'.venv/bin/python');
const ADMIN='temporary browser admin password', EDIT='temporary browser edit password';
const source=`
import json,sys
from pathlib import Path
from collection_catalog import CollectionCatalog
from df_search import LABEL_ORDER
from main import create_app
from waitress import create_server
root=Path(sys.argv[1]);catalog=CollectionCatalog(root/'catalog.sqlite3')
a=catalog.create('Gastronomy');b=catalog.create('Fashion')
for entry,name in [(a,'headword'),(b,'fashion term')]:
 store=catalog.store(entry['id']);store.add_etymon(name)
 store.add_row(1,LABEL_ORDER[1],'recover this sense' if entry==a else 'fashion recovery')
 store.add_row(1,LABEL_ORDER[1],'keep this sense')
 store.delete_row(1,LABEL_ORDER[1],1,actor={'name':'Bob'})
catalog.close()
app=create_app(catalog_path=root/'catalog.sqlite3',test_config={'EDIT_HEARTBEAT_SECONDS':1,'EDIT_LEASE_SECONDS':15,'LIVE_REFRESH_SECONDS':1})
app.extensions['access_control'].set_admin_password(${JSON.stringify(ADMIN)})
app.extensions['access_control'].set_edit_password(${JSON.stringify(EDIT)})
server=create_server(app,host='127.0.0.1',port=0)
print(json.dumps({'port':server.effective_port,'a':a,'b':b}),flush=True)
server.run()
`;
const server=spawn(python,['-u','-c',source,directory],{cwd:root,stdio:['ignore','pipe','inherit']});
async function waitFor(predicate,description){
 const end=Date.now()+45000;
 while(!(await predicate())){
  if(Date.now()>end)throw new Error(`Timed out: ${description}`);
  await new Promise(resolve=>setTimeout(resolve,60));
 }
}
async function main(){
 let browser;
 try{
  const lines=readline.createInterface({input:server.stdout});
  const [line]=await Promise.race([once(lines,'line'),once(server,'exit').then(()=>{throw new Error('Test server exited');})]);
  const {port,a,b}=JSON.parse(line),base=`http://127.0.0.1:${port}`;
  const collection=entry=>`${base}/collections/${entry.id}/`;
  browser=await chromium.launch({headless:true});
  const adminContext=await browser.newContext({javaScriptEnabled:false,viewport:{width:1440,height:1000}});
  const editorContext=await browser.newContext({viewport:{width:1440,height:1000}});
  const otherContext=await browser.newContext({javaScriptEnabled:false});
  for(const context of [adminContext,editorContext,otherContext]){context.setDefaultTimeout(45000);context.setDefaultNavigationTimeout(60000);}
  const admin=await adminContext.newPage(),editor=await editorContext.newPage();
  const errors=[];
  for(const page of [admin,editor])page.on('pageerror',error=>errors.push(error.message));
  const adminLogin=async(page,name='Elena',password=ADMIN)=>{
   await page.getByLabel('Administrator name',{exact:true}).fill(name);
   await page.getByLabel('Administrator password',{exact:true}).fill(password);
   await page.getByRole('button',{name:'Sign in',exact:true}).click();
   await page.waitForURL(url=>!url.pathname.endsWith('/login'));
  };
  const payload=()=>editor.locator('.workspace-data').evaluate(el=>JSON.parse(el.textContent));
  const editorLogin=async(password=EDIT)=>{
   await editor.getByRole('button',{name:'Edit mode',exact:true}).click();
   await editor.getByRole('textbox',{name:'Name',exact:true}).fill('Ana');
   await editor.getByLabel('Edit password',{exact:true}).fill(password);
   await editor.getByRole('button',{name:'Sign in',exact:true}).click();
   await editor.locator('#editor-login-dialog').waitFor({state:'hidden'});
   await waitFor(async()=>(await payload()).edit_mode,'editor login');
  };
  const openCell=async()=>{
   await editor.locator('.tabulator-row [tabulator-field="content_0"]').last().dblclick();
   await editor.locator('.ql-editor').waitFor();
  };
  await editor.goto(collection(a));await editor.locator('.grid-active').waitFor();
  await admin.goto(`${base}/admin/`);
  assert.equal(new URL(admin.url()).pathname,'/admin/login');
  await admin.getByLabel('Administrator name',{exact:true}).fill('Elena');
  await admin.getByLabel('Administrator password',{exact:true}).fill(EDIT);
  await admin.getByRole('button',{name:'Sign in',exact:true}).click();
  await admin.getByRole('alert').filter({hasText:'Incorrect administrator password'}).waitFor();
  assert.equal(await admin.getByLabel('Administrator password',{exact:true}).inputValue(),'');
  await adminLogin(admin);
  await admin.getByRole('heading',{name:'Overview',exact:true}).waitFor();
  assert.equal(await admin.locator('script').count(),0);
  assert.equal((await payload()).auth.authenticated,false);
  await admin.screenshot({path:'/tmp/xldb-admin-working-desktop.png'});
  console.log('ok - Admin requires its own password; ordinary HTML login works without JavaScript and does not grant editing');

  await editorLogin();await openCell();
  await editor.locator('.ql-editor').fill('Ana protected draft');
  await editor.getByRole('link',{name:'Admin',exact:true}).click();
  assert.equal(editor.url(),collection(a));
  assert.equal(await editor.locator('.ql-editor').innerText(),'Ana protected draft');
  await admin.getByRole('link',{name:'Active editors',exact:true}).click();
  await admin.getByRole('cell',{name:'Ana',exact:true}).waitFor();
  assert.ok((await admin.locator('main').innerText()).includes('SENSURI DE BAZĂ #2'));
  assert.equal(await admin.locator('script').count(),0);
  console.log('ok - Active editors use the existing lease records; an open cell draft blocks navigation to administration');

  await admin.getByRole('link',{name:'Trash',exact:true}).click();
  await admin.getByRole('link',{name:'View item →',exact:true}).click();
  await admin.getByText('recover this sense',{exact:true}).waitFor();
  await admin.getByRole('link',{name:'Review restoration →',exact:true}).click();
  await admin.getByRole('link',{name:'Cancel / back to item',exact:true}).click();
  assert.equal((await payload()).rows.length,2);
  await admin.getByRole('link',{name:'Review restoration →',exact:true}).click();
  await admin.getByRole('button',{name:'Restore this row',exact:true}).click();
  await admin.getByRole('status').filter({hasText:'Trash item restored'}).waitFor();
  await editor.locator('#live-update-status').filter({hasText:'close the cell editor'}).waitFor();
  assert.equal(await editor.locator('.ql-editor').innerText(),'Ana protected draft');
  await editor.getByRole('button',{name:'Cancel',exact:true}).click();
  await editor.locator('.cell-editor').waitFor({state:'detached'});
  await waitFor(async()=>(await payload()).rows.length===3,'live restoration');
  assert.ok((await payload()).rows[1].content_0.includes('recover this sense'));
  console.log('ok - Trash preview, Cancel and confirmed recovery work without JavaScript; live viewers receive recovered content safely');

  await admin.getByRole('link',{name:'History',exact:true}).click();
  await admin.getByLabel('Editor name',{exact:true}).fill('Elena');
  await admin.getByLabel('Action',{exact:true}).selectOption('restore_trash');
  await admin.getByRole('button',{name:'Apply filters',exact:true}).click();
  assert.ok((await admin.locator('main').innerText()).includes('1 result'));
  await admin.getByRole('link',{name:'View event →',exact:true}).click();
  assert.ok((await admin.locator('main').innerText()).includes('Elena'));
  assert.ok((await admin.locator('main').innerText()).includes('recover this sense'));
  await admin.getByRole('link',{name:'Back to history',exact:true}).click();
  await admin.getByLabel('Outcome',{exact:true}).selectOption('cancelled');
  await admin.getByRole('button',{name:'Apply filters',exact:true}).click();
  await admin.getByRole('link',{name:'View event →',exact:true}).click();
  await admin.getByText('No change saved.',{exact:false}).waitFor();
  console.log('ok - History filters, administrator attribution, snapshots and cancelled-session details are usable without scripts');

  await openCell();await editor.locator('.ql-editor').fill('Draft retained after edit password reset');
  await admin.getByRole('link',{name:'Passwords',exact:true}).click();
  const editForm=admin.locator('form').filter({has:admin.getByRole('heading',{name:'Global edit password',exact:true})});
  await editForm.getByLabel('Current administrator password',{exact:true}).fill(ADMIN);
  await editForm.getByLabel('New edit password',{exact:true}).fill('changed editor password');
  await editForm.getByLabel('Repeat new edit password',{exact:true}).fill('changed editor password');
  await editForm.getByRole('button',{name:'Change edit password and sign out editors',exact:true}).click();
  await admin.getByRole('status').filter({hasText:'Edit password changed'}).waitFor();
  await editor.locator('.cell-editor [role="status"]').filter({hasText:'Copy your draft'}).waitFor();
  assert.equal(await editor.locator('.ql-editor').innerText(),'Draft retained after edit password reset');
  assert.equal(await editor.getByRole('button',{name:'Close',exact:true}).isDisabled(),true);
  assert.ok((await admin.locator('.identity').innerText()).includes('Elena'));
  await editor.keyboard.press('Escape');await editor.locator('.cell-editor').waitFor({state:'detached'});
  await editor.reload();await editor.locator('.grid-active').waitFor();await editorLogin('changed editor password');
  console.log('ok - Changing the edit password signs editors out, preserves rejected drafts, and keeps the administrator signed in');

  const other=await otherContext.newPage();
  await other.goto(`${base}/admin/`);await adminLogin(other,'Second administrator');
  await openCell();await editor.locator('.ql-editor').fill('Saved while administrator password changes');
  const adminForm=admin.locator('form').filter({has:admin.getByRole('heading',{name:'Global administrator password',exact:true})});
  await adminForm.getByLabel('Current administrator password',{exact:true}).fill(ADMIN);
  await adminForm.getByLabel('New administrator password',{exact:true}).fill('changed administrator password');
  await adminForm.getByLabel('Repeat new administrator password',{exact:true}).fill('changed administrator password');
  await adminForm.getByRole('button',{name:'Change administrator password and sign out',exact:true}).click();
  await admin.waitForURL(url=>url.pathname==='/admin/login');
  await admin.getByRole('status').filter({hasText:'Administrator password changed'}).waitFor();
  await other.goto(`${base}/admin/`);assert.equal(new URL(other.url()).pathname,'/admin/login');
  await editor.keyboard.press('Control+Enter');await editor.locator('.cell-editor').waitFor({state:'detached'});
  await waitFor(async()=>(await payload()).rows.at(-1).content_0.includes('Saved while administrator'),'editor remains authorized');
  await adminLogin(admin,'Elena','changed administrator password');
  console.log('ok - Changing the admin password revokes every administrator while leaving independent editor grants valid');

  await admin.getByLabel('Collection',{exact:true}).selectOption(b.id);
  await admin.getByRole('button',{name:'Open',exact:true}).click();
  await admin.getByRole('heading',{name:'Fashion',exact:true}).waitFor();
  await admin.getByRole('link',{name:'Trash',exact:true}).click();
  await admin.getByRole('link',{name:'View item →',exact:true}).click();
  await admin.getByText('fashion recovery',{exact:true}).waitFor();
  assert.equal(await admin.getByText('recover this sense',{exact:true}).count(),0);
  await admin.getByRole('link',{name:'Overview',exact:true}).click();
  await admin.setViewportSize({width:390,height:844});
  const dimensions=await admin.locator('html').evaluate(el=>({width:el.clientWidth,scroll:el.scrollWidth}));
  assert.ok(dimensions.scroll<=390,JSON.stringify(dimensions));
  await admin.screenshot({path:'/tmp/xldb-admin-working-mobile.png'});
  await admin.getByRole('button',{name:'Sign out',exact:true}).click();
  await admin.waitForURL(url=>url.pathname==='/admin/login');
  assert.equal((await payload()).auth.authenticated,true);
  assert.deepEqual(errors,[]);
  console.log('ok - Collection switching remains explicit, mobile layout fits, and admin sign-out leaves editor access intact');
  console.log('Administration browser checks passed.');
 }finally{
  if(browser)await browser.close();
  if(server.exitCode===null){const stopped=once(server,'exit');server.kill('SIGTERM');await stopped;}
  rmSync(directory,{recursive:true,force:true});
 }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
