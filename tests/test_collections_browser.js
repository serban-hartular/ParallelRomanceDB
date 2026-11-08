/* Real-browser collection switching and multi-tab editing. Requires Playwright. */
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
const directory = mkdtempSync(path.join(tmpdir(),'xldb-collections-'));
const python = process.env.XLDB_PYTHON || path.join(root,'.venv/bin/python');
const source = `
from pathlib import Path
import json,sys
from openpyxl import Workbook
from collection_catalog import CollectionCatalog
from df_search import LABEL_ORDER
from main import create_app
from waitress import create_server
root=Path(sys.argv[1])
workbook=Workbook()
sheet=workbook.active
sheet.append(['Label','LIMBA FRANCEZĂ','LIMBA ROMÂNĂ'])
sheet.append([LABEL_ORDER[0],'alpha','Romanian alpha'])
sheet.append([LABEL_ORDER[1],'a sense'])
workbook.save(root/'source.xlsx')
workbook.close()
catalog=CollectionCatalog(root/'catalog.sqlite3')
a=catalog.create('Gastronomy',root/'source.xlsx')
b=catalog.create('Fashion',root/'source.xlsx')
empty=catalog.create('Empty collection')
store=catalog.store(b['id'])
store.connection.execute("UPDATE column_definitions SET name='Headword' WHERE name='LIMBA FRANCEZĂ'")
store.connection.execute("UPDATE row_types SET name='Definition',default_background='#AABBCC' WHERE name=?",(LABEL_ORDER[1],))
store.save_cell((1,LABEL_ORDER[0],1,'Headword'),0,[{'insert':'beta\\n'}])
catalog.close()
app=create_app(catalog_path=root/'catalog.sqlite3')
app.extensions['access_control'].set_edit_password('temporary browser password')
app.config['DEFAULT_UI_LANGUAGE']='en'
server=create_server(app,host='127.0.0.1',port=0)
print(json.dumps({'port':server.effective_port,'a':a['id'],'b':b['id'],'empty':empty['id']}),flush=True)
server.run()
`;
const server = spawn(python,['-u','-c',source,directory],{cwd:root,stdio:['ignore','pipe','inherit']});

async function waitState(page,predicate) {
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
    const [line] = await Promise.race([once(lines,'line'),once(server,'exit').then(() => {throw new Error('Server exited.');})]);
    const {port,a,b,empty} = JSON.parse(line);
    const origin = `http://127.0.0.1:${port}`;
    const url = id => `${origin}/collections/${id}/`;
    browser = await chromium.launch({headless:true});
    const context = await browser.newContext({viewport:{width:1600,height:1000}});
    context.setDefaultNavigationTimeout(60000);
    context.setDefaultTimeout(60000);
    const first = await context.newPage();
    const second = await context.newPage();
    const errors = [];
    for (const page of [first,second]) page.on('pageerror',error => errors.push(error.message));
    const payload = page => page.locator('.workspace-data').evaluate(el => JSON.parse(el.textContent));
    const ready = async page => {
      await page.locator('.detail-panel.grid-active').waitFor();
      await waitState(page,() => !document.querySelector('[aria-busy="true"]'));
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    };
    const editMode = async page => {
      const needsLogin = !(await payload(page)).auth.authenticated;
      await page.getByRole('button',{name:'Edit mode',exact:true}).click();
      if (needsLogin) {
        await page.getByRole('textbox',{name:'Name',exact:true}).fill('Collection editor');
        await page.getByLabel('Edit password',{exact:true}).fill('temporary browser password');
        await page.getByRole('button',{name:'Sign in',exact:true}).click();
      }
      await waitState(page,() => JSON.parse(document.querySelector('.workspace-data').textContent).edit_mode);
      if ((await payload(page)).total) await ready(page);
      else await waitState(page,() => !document.querySelector('[aria-busy="true"]'));
    };
    const cell = page => page.locator('.tabulator-row [tabulator-field="content_0"]').first();
    await first.goto(url(a));
    await ready(first);
    await editMode(first);
    await second.goto(url(b));
    await ready(second);
    assert.equal((await payload(second)).edit_mode,false);
    assert.equal(await second.locator('.search-form').getAttribute('action'),`/collections/${b}/`);
    await editMode(second);
    await cell(first).dblclick();
    await first.locator('.ql-editor').fill('alpha edited in its own tab');
    await cell(second).dblclick();
    await second.locator('.ql-editor').fill('beta edited in its own tab');
    await Promise.all([first.keyboard.press('Control+Enter'),second.keyboard.press('Control+Enter')]);
    for (const page of [first,second]) {
      await page.locator('.cell-editor').waitFor({state:'detached'});
      await ready(page);
    }
    await waitState(first,() => JSON.parse(document.querySelector('.workspace-data').textContent).title.includes('alpha edited'));
    await waitState(second,() => JSON.parse(document.querySelector('.workspace-data').textContent).title.includes('beta edited'));
    console.log('ok - Separate tabs save simultaneous edits to the correct collections');

    await first.locator('#query').fill('a sense');
    await first.getByRole('button',{name:'Search',exact:false}).click();
    await waitState(first,() => JSON.parse(document.querySelector('.workspace-data').textContent).criteria.query==='a sense');
    await ready(first);
    await first.locator('#collection-select').selectOption(`/collections/${b}/`);
    await first.waitForURL(url(b));
    await ready(first);
    assert.equal((await payload(first)).criteria.query,'');
    assert.equal((await payload(first)).columns[0].title,'Headword');
    assert.ok((await first.locator('.brand span').textContent()).includes('Fashion'));
    assert.equal(await first.getByRole('link',{name:'Export Excel',exact:true}).getAttribute('href'),`/collections/${b}/export?choose=1`);
    await first.getByRole('button',{name:'Add row',exact:true}).click();
    await first.getByRole('button',{name:'Definition',exact:true}).click();
    assert.equal(await first.getByLabel('Text for Headword',{exact:true}).inputValue(),'[To be added]');
    await first.getByLabel('Text for Headword',{exact:true}).fill('fashion definition');
    await first.getByRole('button',{name:'Create',exact:true}).click();
    await waitState(first,() => JSON.parse(document.querySelector('.workspace-data').textContent).rows.some(row => row.label==='Definition'));
    await ready(first);
    const definition = first.locator('.tabulator-row').filter({has:first.locator('.grid-label',{hasText:'Definition'})});
    assert.equal(await definition.locator('[tabulator-field="content_0"]').evaluate(el => getComputedStyle(el).backgroundColor),'rgb(170, 187, 204)');
    console.log('ok - Switching updates the URL, headings, row menus, initial-entry column, colors and export target');

    await cell(first).dblclick();
    await first.locator('.cell-editor').waitFor();
    await first.locator('#collection-select').selectOption(`/collections/${a}/`);
    assert.equal(first.url(),url(b));
    assert.equal(await first.locator('#collection-select').inputValue(),`/collections/${b}/`);
    await first.keyboard.press('Escape');
    await first.locator('.cell-editor').waitFor({state:'detached'});
    await first.locator('#collection-select').selectOption(`/collections/${a}/`);
    await first.waitForURL(url(a));
    await ready(first);
    assert.equal((await payload(first)).criteria.query,'a sense');
    assert.ok(!(await payload(first)).rows.some(row => row.label==='Definition'));
    await first.goBack();
    await ready(first);
    assert.equal(first.url(),url(b));
    console.log('ok - Open editors block switching; search preferences and browser Back retain collection identity');

    const downloadEvent = first.waitForEvent('download');
    await first.getByRole('link',{name:'Export Excel',exact:true}).click();
    await first.getByRole('button',{name:'Download Excel',exact:true}).click();
    const download = await downloadEvent;
    execFileSync(python,['-c',`
from io import BytesIO
from pathlib import Path
from openpyxl import load_workbook
import sys
book=load_workbook(BytesIO(Path(sys.argv[1]).read_bytes()),rich_text=True)
assert book.active['B1'].value=='Headword'
assert 'beta edited' in str(book.active['B2'].value)
assert any(str(cell.value)=='fashion definition' for row in book.active for cell in row)
book.close()
`,await download.path()]);
    await first.getByRole('button',{name:'Delete etymon',exact:true}).click();
    await first.getByLabel('Type DELETE to confirm',{exact:true}).fill('DELETE');
    await first.getByRole('button',{name:'Move to Trash',exact:true}).click();
    await waitState(first,() => JSON.parse(document.querySelector('.workspace-data').textContent).total===0);
    await second.goto(url(a));
    await ready(second);
    assert.equal((await payload(second)).total,1);
    console.log('ok - Downloaded Excel and Trash actions affect only the selected collection');

    await first.locator('#collection-select').selectOption(`/collections/${empty}/`);
    await first.waitForURL(url(empty));
    assert.equal((await payload(first)).total,0);
    await editMode(first);
    await first.getByRole('button',{name:'Add etymon',exact:true}).click();
    await first.getByRole('button',{name:'Create',exact:true}).click();
    await waitState(first,() => JSON.parse(document.querySelector('.workspace-data').textContent).total===1);
    await ready(first);
    assert.equal((await payload(first)).etimon,1);
    assert.ok((await payload(first)).title.includes('[To be added]'));
    assert.deepEqual(errors,[]);
    console.log('ok - Empty collections can create their first etymon and initialize the table');
    console.log('Collection browser checks passed.');
  } finally {
    if (browser) await browser.close();
    if (server.exitCode===null) {
      const stopped=once(server,'exit');
      server.kill('SIGTERM');
      await stopped;
    }
    rmSync(directory,{recursive:true,force:true});
  }
}
main().catch(error => {console.error(error);process.exitCode=1;});
