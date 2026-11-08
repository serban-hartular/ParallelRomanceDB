/* Export selection/downloads with and without JavaScript. Disposable data only. */
'use strict';
const assert=require('node:assert/strict');
const {spawn,execFileSync}=require('node:child_process');
const {once}=require('node:events');
const {mkdtempSync,rmSync}=require('node:fs');
const {tmpdir}=require('node:os');
const path=require('node:path');
const readline=require('node:readline');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),directory=mkdtempSync(path.join(tmpdir(),'xldb-export-browser-'));
const python=process.env.XLDB_PYTHON||path.join(root,'.venv/bin/python');
const source=`
import json,sys
from pathlib import Path
from collection_catalog import CollectionCatalog
from main import create_app
from waitress import create_server
directory=Path(sys.argv[1]);catalog=CollectionCatalog(directory/'catalog.sqlite3')
a=catalog.create('First collection');b=catalog.create('Second collection')
catalog.store(a['id']).add_etymon('  premier  ')
catalog.store(b['id']).add_etymon('deuxième')
catalog.close()
app=create_app(catalog_path=directory/'catalog.sqlite3')
app.config['DEFAULT_UI_LANGUAGE']='en'
server=create_server(app,host='127.0.0.1',port=0)
print(json.dumps({'port':server.effective_port,'a':a['id'],'b':b['id']}),flush=True)
server.run()
`;
const server=spawn(python,['-u','-c',source,directory],{cwd:root,stdio:['ignore','pipe','inherit']});
async function main(){
 let browser;
 try{
  const lines=readline.createInterface({input:server.stdout});
  const [line]=await Promise.race([once(lines,'line'),once(server,'exit').then(()=>{throw new Error('Test server exited');})]);
  const {port,a,b}=JSON.parse(line),base=`http://127.0.0.1:${port}`;
  browser=await chromium.launch({headless:true});
  const htmlContext=await browser.newContext({javaScriptEnabled:false});
  htmlContext.setDefaultTimeout(60000);htmlContext.setDefaultNavigationTimeout(60000);
  const html=await htmlContext.newPage();
  await html.goto(`${base}/collections/${a}/export?choose=1`);
  await html.screenshot({path:'/tmp/xldb-export-html.png'});
  assert.equal(await html.getByLabel('First collection',{exact:true}).isChecked(),true);
  assert.equal(await html.getByLabel('Second collection',{exact:true}).isChecked(),false);
  await html.getByLabel('Second collection',{exact:true}).check();
  const receiving=html.waitForEvent('download');
  await html.getByRole('button',{name:'Download Excel',exact:true}).click();
  const download=await receiving;
  execFileSync(python,['-c',`
from pathlib import Path
from io import BytesIO
from openpyxl import load_workbook
import sys
book=load_workbook(BytesIO(Path(sys.argv[1]).read_bytes()),rich_text=True)
assert book.sheetnames==['First collection','Second collection']
assert str(book['First collection']['B2'].value)=='  premier  '
assert str(book['Second collection']['B2'].value)=='deuxième'
book.close()
`,await download.path()]);
  await htmlContext.close();
  console.log('ok - Plain HTML defaults to the current collection and downloads selected collections as independent worksheets');

  const context=await browser.newContext({viewport:{width:1000,height:900}});
  context.setDefaultTimeout(60000);context.setDefaultNavigationTimeout(60000);
  const page=await context.newPage();
  await page.goto(`${base}/collections/${b}/`);
  await page.locator('.grid-active').waitFor();
  await page.getByRole('link',{name:'Export Excel',exact:true}).click();
  const dialog=page.getByRole('dialog',{name:'Export Excel',exact:true});
  await dialog.waitFor();
  assert.equal(await dialog.getByLabel('First collection',{exact:true}).isChecked(),false);
  assert.equal(await dialog.getByLabel('Second collection',{exact:true}).isChecked(),true);
  await dialog.getByLabel('Second collection',{exact:true}).uncheck();
  assert.equal(await dialog.getByRole('button',{name:'Download Excel',exact:true}).isDisabled(),true);
  await dialog.getByLabel('First collection',{exact:true}).check();
  await dialog.getByLabel('Second collection',{exact:true}).check();
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:'/tmp/xldb-export-picker-mobile.png'});
  const combinedEvent=page.waitForEvent('download');
  await dialog.getByRole('button',{name:'Download Excel',exact:true}).click();
  assert.match((await combinedEvent).suggestedFilename(),/^Parallel_Words_.*\.xlsx$/);
  await dialog.waitFor({state:'hidden'});
  await page.getByRole('link',{name:'Export Excel',exact:true}).click();
  assert.equal(await dialog.getByLabel('First collection',{exact:true}).isChecked(),false);
  assert.equal(await dialog.getByLabel('Second collection',{exact:true}).isChecked(),true);
  await page.keyboard.press('Escape');
  await dialog.waitFor({state:'hidden'});
  assert.equal(new URL(page.url()).pathname,`/collections/${b}/`);
  console.log('ok - The picker resets to the current collection, validates empty selection, downloads multiple sheets, fits mobile, and cancels without navigation');
 }finally{
  if(browser)await browser.close();
  if(server.exitCode===null){const stopped=once(server,'exit');server.kill();await stopped;}
  rmSync(directory,{recursive:true,force:true});
 }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
