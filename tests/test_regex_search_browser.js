/* Search mode controls and live/browser behavior, using disposable data only. */
'use strict';
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const {mkdtempSync, rmSync} = require('node:fs');
const {tmpdir} = require('node:os');
const path = require('node:path');
const readline = require('node:readline');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const directory = mkdtempSync(path.join(tmpdir(), 'xldb-regex-browser-'));
const python = process.env.XLDB_PYTHON || path.join(root, '.venv/bin/python');
const source = `
import json,sys
from pathlib import Path
from openpyxl import Workbook
from openpyxl.cell.rich_text import CellRichText,TextBlock
from openpyxl.cell.text import InlineFont
from collection_catalog import CollectionCatalog
from main import create_app
from waitress import create_server
root=Path(sys.argv[1]);book=Workbook();sheet=book.active
sheet.append(['Label','LIMBA FRANCEZĂ','LIMBA ROMÂNĂ'])
sheet.append(['ETIMON/','FIRST','unu'])
sheet.append(['SENSURI DE BAZĂ',CellRichText(['  ',TextBlock(InlineFont(b=True),'ca'),TextBlock(InlineFont(i=True),'fé'), ' cœur  ']),'ceai'])
sheet.append(['ETIMON/','SECOND','doi'])
sheet.append(['SENSURI DE BAZĂ','cafe vin','apă'])
sheet.append(['ETIMON/','THIRD','trei'])
sheet.append(['SENSURI DE BAZĂ','vin','café'])
workbook=root/'fixture.xlsx';book.save(workbook);book.close()
catalog=CollectionCatalog(root/'catalog.sqlite3')
a=catalog.create('Search samples',workbook);b=catalog.create('Other collection',workbook);catalog.close()
app=create_app(catalog_path=root/'catalog.sqlite3',test_config={'LIVE_REFRESH_SECONDS':1})
app.extensions['access_control'].set_edit_password('temporary editor password')
server=create_server(app,host='127.0.0.1',port=0)
print(json.dumps({'port':server.effective_port,'a':a['id'],'b':b['id']}),flush=True)
server.run()
`;
const server = spawn(python, ['-u', '-c', source, directory], {cwd:root, stdio:['ignore','pipe','inherit']});
async function data(page) {
  return page.locator('.workspace-data').evaluate(node => JSON.parse(node.textContent));
}
async function submit(page, query, {regex=false, diacritics=false}={}) {
  await page.locator('#query').fill(query);
  await page.locator('input[name=regex]').setChecked(regex);
  await page.locator('input[name=diacritics]').setChecked(diacritics);
  const response = page.waitForResponse(response => response.request().method()==='GET' && response.url().includes('search=1') && !response.url().includes('live=1'));
  await page.locator('.search-button').click();
  assert.equal((await response).status(), 200);
  await page.waitForFunction(() => !document.querySelector('#request-status').classList.contains('htmx-request'));
  await page.waitForFunction(({regex,diacritics}) => {
    const data=JSON.parse(document.querySelector('.workspace-data').textContent);
    return data.criteria.regex===regex && data.criteria.diacritics===diacritics;
  }, {regex,diacritics});
}
async function main() {
  let browser;
  try {
    const lines=readline.createInterface({input:server.stdout});
    const [line]=await Promise.race([once(lines,'line'),once(server,'exit').then(()=>{throw new Error('Test server exited');})]);
    const {port,a,b}=JSON.parse(line), base=`http://127.0.0.1:${port}`, url=`${base}/collections/${a}/`;
    browser=await chromium.launch({headless:true});
    const context=await browser.newContext({viewport:{width:1360,height:900}});
    context.setDefaultTimeout(30000);
    const page=await context.newPage(), errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    await page.goto(url);await page.locator('.grid-active').waitFor();
    assert.equal(await page.locator('html').getAttribute('lang'),'ro');
    assert.equal(await page.locator('input[name=diacritics]').isChecked(),false);
    assert.equal(await page.locator('input[name=regex]').isChecked(),false);
    const clearQuery=page.getByRole('button',{name:'Șterge textul căutării',exact:true});
    await page.locator('#query').fill('unsubmitted text');
    await page.locator('input[name=diacritics]').check();
    await page.locator('input[name=regex]').check();
    await page.locator('.brand').focus();await page.mouse.move(1350,880);
    assert.equal(await clearQuery.isVisible(),true);
    assert.equal(await clearQuery.evaluate(node=>getComputedStyle(node).opacity),'1');
    await clearQuery.click();
    assert.equal(await page.locator('#query').inputValue(),'');
    assert.equal(await page.locator('#query').evaluate(node=>node===document.activeElement),true);
    assert.equal(await page.locator('input[name=diacritics]').isChecked(),true);
    assert.equal(await page.locator('input[name=regex]').isChecked(),true);
    assert.equal((await data(page)).criteria.regex,false);
    await page.locator('input[name=diacritics]').uncheck();
    await page.locator('input[name=regex]').uncheck();
    await page.locator('.column-chooser summary').click();
    const allColumns=page.locator('[data-grid-all]'), firstColumn=page.locator('[data-grid-field]').first();
    assert.equal(await page.locator('.column-chooser label').first().textContent().then(text=>text.trim()),'Toate coloanele');
    assert.equal(await allColumns.isChecked(),true);
    await firstColumn.uncheck();
    assert.equal(await allColumns.isChecked(),false);
    await allColumns.check();
    assert.ok(await page.evaluate(()=>Tabulator.findTable('#etimon-grid')[0].getColumns().every(column=>column.isVisible())));
    await allColumns.uncheck();
    assert.equal(await page.locator('[data-grid-field]:checked').count(),0);
    assert.ok(await page.evaluate(()=>Tabulator.findTable('#etimon-grid')[0].getColumns().filter(column=>column.getDefinition().frozen).every(column=>column.isVisible())));
    await allColumns.check();await firstColumn.uncheck();
    await page.reload();await page.locator('.grid-active').waitFor();
    await page.locator('.column-chooser summary').click();
    assert.equal(await allColumns.isChecked(),false);
    assert.equal(await firstColumn.isChecked(),false);
    await allColumns.check();
    await page.screenshot({path:'/tmp/xldb-clear-and-all-columns.png',fullPage:true});
    await page.locator('.column-chooser summary').click();
    console.log('ok - Permanent clear button preserves search modes; All columns selects, hides, and tracks saved individual visibility');
    await page.screenshot({path:'/tmp/xldb-search-options-desktop.png',fullPage:true});
    await page.getByRole('link',{name:'English',exact:true}).click();
    await page.locator('.grid-active').waitFor();
    await submit(page,'café|cœur',{regex:true});
    await page.waitForFunction(()=>document.querySelector('#query').value==='cafe|coeur');
    assert.equal(await page.locator('#search-feedback').isVisible(),false);
    assert.equal(await page.locator('.etimon-link').count(),3);
    assert.ok((await page.locator('.tabulator-cell mark').allTextContents()).join('').includes('café'));
    assert.ok((await page.locator('.tabulator-cell mark').allTextContents()).join('').includes('cœur'));
    assert.ok(await page.locator('.tabulator-cell b mark, .tabulator-cell span[style*="bold"] mark').count());
    console.log('ok - Romanian defaults, independent switches, normalized input, and original rich-text highlights');

    await submit(page,String.raw`\bcafé\b`,{regex:true,diacritics:true});
    assert.equal(await page.locator('.etimon-link').count(),2);
    await page.locator('.etimon-link[data-etimon-id="3"]').click();
    await page.waitForFunction(()=>JSON.parse(document.querySelector('.workspace-data').textContent).etimon===3);
    assert.equal(await page.locator('input[name=diacritics]').isChecked(),true);
    await page.getByRole('link',{name:'Română',exact:true}).click();
    await page.locator('.grid-active').waitFor();
    assert.equal(await page.locator('input[name=regex]').isChecked(),true);
    assert.equal((await data(page)).etimon,3);
    assert.equal(await page.locator('#query').inputValue(),String.raw`\bcafé\b`);
    await page.getByRole('link',{name:'English',exact:true}).click();
    await page.locator('.grid-active').waitFor();
    await submit(page,'[',{regex:true});
    await page.locator('#search-feedback.is-error').waitFor();
    assert.ok((await page.locator('#search-feedback').textContent()).includes('Invalid regex'));
    assert.equal(await page.locator('.etimon-link').count(),0);
    await submit(page,'œ+',{regex:true});
    await page.waitForFunction(()=>document.querySelector('#query').value==='(?:oe)+');
    assert.equal(await page.locator('.etimon-link').count(),1);
    await page.selectOption('#collection-select',`/collections/${b}/`);
    await page.locator('.grid-active').waitFor();
    assert.equal(await page.locator('input[name=regex]').isChecked(),false);
    await page.selectOption('#collection-select',`/collections/${a}/`);
    await page.locator('.grid-active').waitFor();
    assert.equal(await page.locator('#query').inputValue(),'(?:oe)+');
    assert.equal(await page.locator('input[name=regex]').isChecked(),true);
    console.log('ok - Mode retention through navigation, language changes and collections; inline errors recover');

    await page.locator('.clear-link').click();
    await page.waitForFunction(()=>document.querySelector('#query').value==='');
    await submit(page,'^café',{regex:true,diacritics:true});
    assert.ok((await page.locator('.tabulator-cell mark').allTextContents()).join('').includes('café'));
    const applied=await data(page);
    await page.locator('#query').fill('unsubmitted café');
    await page.locator('input[name=diacritics]').uncheck();
    await page.locator('input[name=regex]').uncheck();
    // Another browser edits a matching cell; the first browser must keep its
    // applied modes for the refreshed results and its unsent form untouched.
    const editorContext=await browser.newContext();const editor=await editorContext.newPage();
    editorContext.setDefaultTimeout(30000);
    await editor.goto(url);await editor.locator('.grid-active').waitFor();
    await editor.getByRole('link',{name:'English',exact:true}).click();
    await editor.locator('.grid-active').waitFor();
    await editor.getByRole('button',{name:'Edit mode',exact:true}).click();
    const login=editor.locator('#editor-login-dialog');await login.waitFor();
    await login.getByLabel('Name',{exact:true}).fill('Ana');
    await login.getByLabel('Edit password',{exact:true}).fill('temporary editor password');
    await login.getByRole('button',{name:'Sign in',exact:true}).click();
    await editor.waitForFunction(()=>JSON.parse(document.querySelector('.workspace-data').textContent).edit_mode);
    const editPayload=await data(editor), token=editPayload.rows[1].editors.content_0.token;
    await editor.evaluate(async ({payload,token})=>{
      const headers={'Content-Type':'application/json','X-CSRF-Token':payload.csrf};
      const opened=await fetch(payload.urls.edit_start,{method:'POST',headers,body:JSON.stringify({token})});
      if(opened.status!==201)throw new Error('Unable to open disposable cell');
      const lease=(await opened.json()).lease;
      const result=await fetch(payload.urls.cell,{method:'POST',headers,body:JSON.stringify({token,lease,ops:[{insert:'café cœur updated\n'}]})});
      if(!result.ok)throw new Error('Unable to save disposable cell');
    },{payload:editPayload,token});
    await page.waitForFunction(version=>JSON.parse(document.querySelector('.workspace-data').textContent).content_version>version,applied.content_version);
    assert.equal((await data(page)).criteria.regex,true);assert.equal((await data(page)).criteria.diacritics,true);
    assert.equal(await page.locator('#query').inputValue(),'unsubmitted café');
    assert.equal(await page.locator('input[name=regex]').isChecked(),false);
    assert.equal(await page.locator('input[name=diacritics]').isChecked(),false);
    assert.ok((await page.locator('.tabulator-cell').allTextContents()).some(text=>text.includes('updated')));
    await editor.reload();await editor.locator('.grid-active').waitFor();
    await editor.locator('.tabulator-row [tabulator-field="content_0"]').first().dblclick();
    await editor.locator('.ql-editor').fill('Keep this unsaved draft');
    await editor.locator('.column-chooser summary').click();
    await editor.locator('[data-grid-all]').click();
    assert.equal(await editor.locator('[data-grid-all]').isChecked(),true);
    assert.equal(await editor.locator('.ql-editor').innerText(),'Keep this unsaved draft');
    await editor.locator('#query').fill('café|vin');
    await editor.locator('input[name=regex]').check();
    await editor.locator('input[name=diacritics]').check();
    await editor.locator('.search-button').click();
    await editor.locator('#request-status').filter({hasText:'Close or cancel the cell editor'}).waitFor();
    assert.equal(await editor.locator('.ql-editor').innerText(),'Keep this unsaved draft');
    assert.equal((await data(editor)).criteria.regex,false);
    await editor.getByRole('button',{name:'Cancel',exact:true}).click();
    await editor.locator('.cell-editor').waitFor({state:'detached'});
    await editorContext.close();
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:'/tmp/xldb-regex-mobile.png',fullPage:true});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
    assert.ok(await page.locator('.search-switches').isVisible());
    console.log('ok - Live updates retain applied modes and unsent controls, cell drafts block searching, and mobile controls fit');

    const htmlContext=await browser.newContext({javaScriptEnabled:false});
    const html=await htmlContext.newPage();htmlContext.setDefaultTimeout(30000);
    await html.goto(url+'?search=1&q=caf%C3%A9&regex=1');
    assert.equal(await html.locator('#query').inputValue(),'cafe');
    assert.equal(await html.locator('input[name=regex]').isChecked(),true);
    assert.ok((await html.locator('mark').allTextContents()).join('').includes('café'));
    await html.locator('#query').fill('[');
    await html.getByRole('button',{name:'Caută',exact:false}).click();
    assert.ok((await html.locator('#search-feedback').textContent()).includes('Expresie regulată nevalidă'));
    await html.locator('#query').fill('café');
    await html.locator('input[name=diacritics]').check();
    await html.getByRole('button',{name:'Caută',exact:false}).click();
    assert.equal(await html.locator('#query').inputValue(),'café');
    assert.equal(await html.locator('.etimon-link').count(),2);
    await htmlContext.close();await context.close();
    assert.deepEqual(errors,[]);
    console.log('ok - Plain HTML search, normalization, accent switches and Romanian errors work without JavaScript');
  } finally {
    if(browser)await browser.close();
    if(server.exitCode===null){const stopped=once(server,'exit');server.kill();await stopped;}
    rmSync(directory,{recursive:true,force:true});
  }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
