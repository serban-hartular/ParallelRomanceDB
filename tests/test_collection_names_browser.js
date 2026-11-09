/* Import defaults, safe collection renames, and name-only headers. Disposable data. */
'use strict';
const assert=require('node:assert/strict');
const {spawn}=require('node:child_process');
const {once}=require('node:events');
const {mkdtempSync,rmSync}=require('node:fs');
const {tmpdir}=require('node:os');
const path=require('node:path');
const readline=require('node:readline');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..'), directory=mkdtempSync(path.join(tmpdir(),'xldb-names-browser-'));
const python=process.env.XLDB_PYTHON||path.join(root,'.venv/bin/python');
const source=`
import json,sys
from pathlib import Path
from openpyxl import Workbook
from collection_catalog import CollectionCatalog
from main import create_app
from waitress import create_server
root=Path(sys.argv[1]);catalog=CollectionCatalog(root/'catalog.sqlite3')
a=catalog.create('Food');catalog.store(a['id']).add_etymon('first word')
b=catalog.create('Terms');c=catalog.create('Terms (1)');catalog.move_to_trash(c['id'],0)
catalog.close()
book=Workbook();book.active.title='Terms'
for sheet in [book.active,book.create_sheet('Fashion'),book.create_sheet('__proto__')]:
 sheet.append(['Label','LIMBA FRANCEZĂ'])
 sheet.append([' ETIMON/ CORESPONDENTE ROMANICE ','  café  '])
workbook=root/'original source.xlsx';book.save(workbook);book.close()
app=create_app(catalog_path=root/'catalog.sqlite3',test_config={'DEFAULT_UI_LANGUAGE':'en','LIVE_REFRESH_SECONDS':1})
app.extensions['access_control'].set_admin_password('temporary admin password')
app.extensions['access_control'].set_edit_password('temporary editor password')
server=create_server(app,host='127.0.0.1',port=0)
print(json.dumps({'port':server.effective_port,'id':a['id'],'workbook':str(workbook)}),flush=True)
server.run()
`;
const server=spawn(python,['-u','-c',source,directory],{cwd:root,stdio:['ignore','pipe','inherit']});
async function login(page,base){
  await page.goto(base+'/admin/login');
  await page.getByLabel('Administrator name',{exact:true}).fill('Elena');
  await page.getByLabel('Administrator password',{exact:true}).fill('temporary admin password');
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await page.getByRole('heading',{name:'Overview',exact:true}).waitFor();
}
async function upload(page,base,workbook){
  await page.goto(base+'/admin/collections/import');
  await page.getByLabel('Excel workbook',{exact:true}).setInputFiles(workbook);
  await page.getByRole('button',{name:'Upload and choose worksheet',exact:true}).click();
  await page.getByRole('heading',{name:'Choose worksheet',exact:true}).waitFor();
}
async function main(){
  let browser;
  try{
    const lines=readline.createInterface({input:server.stdout});
    const [line]=await Promise.race([once(lines,'line'),once(server,'exit').then(()=>{throw new Error('Test server exited');})]);
    const {port,id,workbook}=JSON.parse(line),base=`http://127.0.0.1:${port}`,collection=`${base}/collections/${id}/`;
    browser=await chromium.launch({headless:true});
    const viewerContext=await browser.newContext({viewport:{width:1350,height:900}});
    viewerContext.setDefaultTimeout(60000);viewerContext.setDefaultNavigationTimeout(60000);
    const viewer=await viewerContext.newPage(),errors=[];
    viewer.on('pageerror',error=>errors.push(error.message));
    await viewer.goto(collection);await viewer.locator('.grid-active').waitFor();
    const htmlContext=await browser.newContext({javaScriptEnabled:false});
    htmlContext.setDefaultTimeout(60000);htmlContext.setDefaultNavigationTimeout(60000);
    const html=await htmlContext.newPage();
    await login(html,base);await upload(html,base,workbook);
    assert.equal(await html.getByLabel('Collection name',{exact:true}).inputValue(),'Terms (2)');
    await html.getByLabel('Worksheet',{exact:true}).selectOption('Fashion');
    await html.getByRole('button',{name:'Suggest name for worksheet',exact:true}).click();
    assert.equal(await html.getByLabel('Collection name',{exact:true}).inputValue(),'Fashion');
    await html.getByRole('button',{name:'Import worksheet',exact:true}).click();
    await html.getByRole('heading',{name:'Fashion',exact:true}).waitFor();
    await html.goto(`${base}/admin/collections/${id}/rename`);
    await html.getByLabel('Collection name',{exact:true}).fill('Food renamed');
    await html.getByRole('button',{name:'Rename collection',exact:true}).click();
    await html.getByRole('row').filter({has:html.getByText('Food renamed',{exact:true})}).waitFor();
    await viewer.locator('.brand span').filter({hasText:'Food renamed'}).waitFor();
    assert.equal(await viewer.locator('.brand span').textContent(),'Food renamed');
    assert.equal(await viewer.locator('.brand span').getAttribute('title'),'Food renamed');
    assert.ok(!((await viewer.locator('.brand').textContent()).includes('.xlsx')));
    assert.ok(await viewer.locator('.brand').evaluate(node=>parseFloat(getComputedStyle(node.querySelector('span')).fontSize)>parseFloat(getComputedStyle(node).fontSize)));
    console.log('ok - Plain HTML imports suggest sheet names with reserved-name suffixes; renaming preserves bookmarks and updates prominent name-only headers');

    const adminContext=await browser.newContext();
    adminContext.setDefaultTimeout(60000);adminContext.setDefaultNavigationTimeout(60000);
    const admin=await adminContext.newPage();admin.on('pageerror',error=>errors.push(error.message));
    await login(admin,base);await upload(admin,base,workbook);
    assert.equal(await admin.getByLabel('Collection name',{exact:true}).inputValue(),'Terms (2)');
    await admin.getByLabel('Worksheet',{exact:true}).selectOption('Fashion');
    assert.equal(await admin.getByLabel('Collection name',{exact:true}).inputValue(),'Fashion (1)');
    await admin.getByLabel('Collection name',{exact:true}).fill('My custom name');
    await admin.getByLabel('Worksheet',{exact:true}).selectOption('__proto__');
    assert.equal(await admin.getByLabel('Collection name',{exact:true}).inputValue(),'My custom name');
    await admin.getByRole('button',{name:'Suggest name for worksheet',exact:true}).click();
    assert.equal(await admin.getByLabel('Collection name',{exact:true}).inputValue(),'__proto__');
    await admin.getByLabel('Worksheet',{exact:true}).selectOption('Terms');
    assert.equal(await admin.getByLabel('Collection name',{exact:true}).inputValue(),'Terms (2)');
    await admin.getByRole('button',{name:'Cancel import and remove upload',exact:true}).click();
    await adminContext.close();
    console.log('ok - Selecting worksheets updates automatic suggestions, preserves custom names, and safely handles unusual sheet titles');

    await viewer.getByRole('button',{name:'Edit mode',exact:true}).click();
    const loginDialog=viewer.locator('#editor-login-dialog');await loginDialog.waitFor();
    await loginDialog.getByLabel('Name',{exact:true}).fill('Ana');
    await loginDialog.getByLabel('Edit password',{exact:true}).fill('temporary editor password');
    await loginDialog.getByRole('button',{name:'Sign in',exact:true}).click();
    await loginDialog.waitFor({state:'hidden'});
    await viewer.locator('[data-toggle-edit][aria-pressed="true"]').waitFor();
    await viewer.locator('.tabulator-row .tabulator-cell[tabulator-field="content_0"]').first().dblclick();
    const editor=viewer.locator('.cell-editor');await editor.waitFor();
    await html.goto(`${base}/admin/collections/${id}/rename`);
    assert.equal(await html.getByRole('button',{name:'Rename collection',exact:true}).isDisabled(),true);
    await html.getByText('This collection is being edited. Ask editors to close their cell editors before renaming it.',{exact:true}).waitFor();
    await editor.getByRole('button',{name:'Cancel',exact:true}).click();await editor.waitFor({state:'hidden'});
    await html.reload();
    await html.getByLabel('Collection name',{exact:true}).fill('Food final');
    await html.getByRole('button',{name:'Rename collection',exact:true}).click();
    await viewer.locator('.brand span').filter({hasText:'Food final'}).waitFor();
    await viewer.setViewportSize({width:390,height:844});
    assert.ok(await viewer.locator('.brand').evaluate(node=>parseFloat(getComputedStyle(node.querySelector('span')).fontSize)>parseFloat(getComputedStyle(node).fontSize)));
    await viewer.screenshot({path:'/tmp/xldb-collection-name-mobile.png',fullPage:true});
    assert.ok(await viewer.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
    await html.getByRole('link',{name:'Română',exact:true}).click();
    await html.goto(`${base}/admin/collections/${id}/rename`);
    await html.getByRole('heading',{name:'Redenumește colecția',exact:true}).waitFor();
    assert.deepEqual(errors,[]);
    await viewerContext.close();await htmlContext.close();
    console.log('ok - Open cell editors block renaming; cancelling permits it, live headers update, mobile fits, and Romanian rename controls are translated');
  }finally{
    if(browser)await browser.close();
    if(server.exitCode===null){const stopped=once(server,'exit');server.kill();await stopped;}
    rmSync(directory,{recursive:true,force:true});
  }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
