/* Romanian defaults, remembered languages, htmx, and draft safety. Disposable data. */
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
const directory = mkdtempSync(path.join(tmpdir(), 'xldb-language-browser-'));
const python = process.env.XLDB_PYTHON || path.join(root, '.venv/bin/python');
const source = `
import json,sys
from pathlib import Path
from collection_catalog import CollectionCatalog
from df_search import LABEL_ORDER
from main import create_app
from waitress import create_server
root=Path(sys.argv[1]);catalog=CollectionCatalog(root/'catalog.sqlite3')
a=catalog.create('Search');store=catalog.store(a['id'])
store.add_etymon('Cancel');store.add_row(1,LABEL_ORDER[1],'  original text  ')
store.add_etymon('second word')
catalog.close()
app=create_app(catalog_path=root/'catalog.sqlite3',test_config={'LIVE_REFRESH_SECONDS':1})
app.extensions['access_control'].set_admin_password('temporary admin password')
app.extensions['access_control'].set_edit_password('temporary editor password')
server=create_server(app,host='127.0.0.1',port=0)
print(json.dumps({'port':server.effective_port,'id':a['id']}),flush=True)
server.run()
`;
const server = spawn(python, ['-u', '-c', source, directory], {cwd:root, stdio:['ignore','pipe','inherit']});
async function main() {
  let browser;
  try {
    const lines = readline.createInterface({input:server.stdout});
    const [line] = await Promise.race([once(lines,'line'), once(server,'exit').then(() => {throw new Error('Test server exited');})]);
    const {port,id} = JSON.parse(line), base = `http://127.0.0.1:${port}`, collection = `${base}/collections/${id}/`;
    browser = await chromium.launch({headless:true});
    const htmlContext = await browser.newContext({javaScriptEnabled:false, locale:'en-US'});
    htmlContext.setDefaultTimeout(60000);
    const html = await htmlContext.newPage();
    await html.goto(collection + 'export?choose=1');
    assert.equal(await html.locator('html').getAttribute('lang'), 'ro');
    assert.equal(await html.getByRole('button',{name:'Descarcă Excel',exact:true}).count(), 1);
    assert.equal(await html.getByLabel('Search',{exact:true}).isChecked(), true);
    await html.getByRole('link',{name:'English',exact:true}).click();
    assert.equal(await html.getByRole('button',{name:'Download Excel',exact:true}).count(),1);
    await html.goto(base + '/admin/login');
    assert.equal(await html.getByRole('heading',{name:'Administrator sign in',exact:true}).count(),1);
    await html.getByRole('link',{name:'Română',exact:true}).click();
    await html.getByLabel('Numele administratorului',{exact:true}).fill('Search');
    await html.getByLabel('Parolă de administrator',{exact:true}).fill('wrong');
    await html.getByRole('button',{name:'Autentificare',exact:true}).click();
    assert.match(await html.locator('.error').textContent(), /Parolă de administrator incorectă/);
    await html.getByLabel('Numele administratorului',{exact:true}).fill('Search');
    await html.getByLabel('Parolă de administrator',{exact:true}).fill('temporary admin password');
    await html.getByRole('button',{name:'Autentificare',exact:true}).click();
    await html.getByRole('heading',{name:'Prezentare generală',exact:true}).waitFor();
    await html.getByRole('link',{name:'Parole',exact:true}).click();
    assert.equal(await html.getByRole('heading',{name:'Parolă globală de editare',exact:true}).count(),1);
    await html.getByRole('link',{name:'English',exact:true}).click();
    assert.equal(await html.getByRole('heading',{name:'Global edit password',exact:true}).count(),1);
    await htmlContext.close();
    console.log('ok - Romanian defaults and remembered language work on export and authenticated administration without JavaScript');

    const context = await browser.newContext({locale:'en-US',viewport:{width:1450,height:1000}});
    context.setDefaultTimeout(60000);
    const page = await context.newPage(), errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(collection);
    await page.locator('.grid-active').waitFor();
    const patternMessage = await page.evaluate(() => {
      const input = document.createElement('input');
      input.pattern = 'DELETE'; input.value = 'wrong'; document.body.append(input);
      input.checkValidity(); const message = input.validationMessage; input.remove(); return message;
    });
    assert.equal(patternMessage,'Folosiți formatul indicat în instrucțiuni.');
    assert.equal(await page.getByRole('columnheader',{name:'Etichetă',exact:true}).count(),1);
    await page.getByRole('button',{name:'Mod editare',exact:true}).click();
    const login = page.locator('#editor-login-dialog');
    await login.waitFor({state:'visible'});
    await login.getByRole('button',{name:'Autentificare',exact:true}).click();
    assert.equal(await login.locator('#editor-name').evaluate(node => node.validationMessage),'Completați acest câmp.');
    await login.getByLabel('Nume',{exact:true}).fill('Name');
    await login.getByLabel('Parolă de editare',{exact:true}).fill('wrong');
    await login.getByRole('button',{name:'Autentificare',exact:true}).click();
    await login.getByText('Parolă de editare incorectă.',{exact:true}).waitFor();
    await page.route('**/auth/login', route => route.abort());
    await login.getByLabel('Parolă de editare',{exact:true}).fill('retry while offline');
    await login.getByRole('button',{name:'Autentificare',exact:true}).click();
    await login.getByText('Serverul nu a putut fi contactat.',{exact:true}).waitFor();
    await page.unroute('**/auth/login');
    await login.getByLabel('Parolă de editare',{exact:true}).fill('temporary editor password');
    await login.getByRole('button',{name:'Autentificare',exact:true}).click();
    await login.waitFor({state:'hidden'});
    await page.locator('[data-toggle-edit][aria-pressed="true"]').waitFor();
    const cell = page.locator('.tabulator-row .tabulator-cell[tabulator-field="content_0"]').first();
    await cell.dblclick();
    const editor = page.getByRole('group',{name:'Editează celula',exact:true});
    await editor.waitFor();
    await editor.getByRole('button',{name:'Aldin',exact:true}).waitFor();
    await editor.getByRole('button',{name:'Tipografie',exact:true}).click();
    const size = editor.getByLabel('Mărime font (pt)',{exact:true});
    await size.fill('0');
    await editor.getByRole('button',{name:'Aplică mărimea',exact:true}).click();
    assert.match(await size.evaluate(node => node.validationMessage),/Introduceți un număr valid/);
    const draft = editor.getByRole('textbox',{name:'Conținutul celulei',exact:true});
    await draft.fill('unsaved literal Cancel');
    await page.getByRole('link',{name:'English',exact:true}).click();
    assert.equal(await page.locator('html').getAttribute('lang'),'ro');
    assert.equal(await draft.textContent(),'unsaved literal Cancel');
    await page.getByText('Închideți sau anulați editarea celulei și așteptați încheierea operației curente înainte de a schimba limba.',{exact:true}).waitFor();
    await editor.getByRole('button',{name:'Anulează',exact:true}).click();
    await editor.waitFor({state:'hidden'});
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:'/tmp/xldb-language-ro-mobile.png',fullPage:true});
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
    await page.getByRole('link',{name:'English',exact:true}).click();
    await page.locator('.grid-active').waitFor();
    assert.equal(await page.locator('html').getAttribute('lang'),'en');
    assert.equal(await page.getByRole('columnheader',{name:'Label',exact:true}).count(),1);
    assert.equal(await page.locator('.tabulator-row .tabulator-cell[tabulator-field="content_0"]').first().textContent(),'Cancel');
    console.log('ok - Romanian login, validation, grid, Quill controls, and draft-preserving language navigation work in an English browser');

    const second = await context.newPage();
    await second.goto(base + '/language/ro?next=' + encodeURIComponent(`/collections/${id}/`));
    await second.locator('.grid-active').waitFor();
    assert.equal(await second.locator('html').getAttribute('lang'),'ro');
    await page.locator('#query').fill('second');
    const updated = page.waitForResponse(response => response.url().includes('q=second') && response.request().headers()['hx-request'] === 'true');
    await page.getByRole('button',{name:'Search',exact:true}).click();
    assert.equal((await updated).headers()['content-language'],'en');
    await page.locator('#detail-heading').filter({hasText:'second word'}).waitFor();
    assert.equal(await page.getByRole('columnheader',{name:'Label',exact:true}).count(),1);
    assert.equal(await page.getByRole('columnheader',{name:'Etichetă',exact:true}).count(),0);
    const next = new URL(await page.getByRole('link',{name:'Română',exact:true}).getAttribute('href'));
    assert.equal(new URL(next.searchParams.get('next'),base).searchParams.get('q'),'second');
    await page.getByRole('link',{name:'Română',exact:true}).click();
    await page.locator('#detail-heading').filter({hasText:'second word'}).waitFor();
    assert.equal(await page.locator('html').getAttribute('lang'),'ro');
    assert.equal(await page.locator('#query').inputValue(),'second');
    assert.deepEqual(errors,[]);
    await context.close();
    console.log('ok - htmx retains each open page’s language across tab preference changes; switching preserves the current search');
  } finally {
    if (browser) await browser.close();
    if (server.exitCode === null) {const stopped=once(server,'exit');server.kill();await stopped;}
    rmSync(directory,{recursive:true,force:true});
  }
}
main().catch(error => {console.error(error);process.exitCode=1;});
