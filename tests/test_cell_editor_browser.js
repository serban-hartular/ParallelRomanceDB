/* Optional real-browser regression check. Requires Playwright + Chromium.
 * Starts its own loopback server and temporary workbook; never uses a live site.
 * NODE_PATH=/path/to/node_modules node tests/test_cell_editor_browser.js
 */
"use strict";
const assert = require("node:assert/strict");
const { spawn, execFileSync } = require("node:child_process");
const { once } = require("node:events");
const { mkdtempSync, rmSync } = require("node:fs");
const { tmpdir } = require("node:os");
const path = require("node:path");
const readline = require("node:readline");
const { chromium } = require("playwright");

const root = path.resolve(__dirname, "..");
const directory = mkdtempSync(path.join(tmpdir(), "xldb-editor-"));
const source = `
from pathlib import Path
import sys
from openpyxl import Workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.styles import PatternFill
from waitress import create_server
from main import create_app
path = Path(sys.argv[1]) / 'browser.xlsx'
workbook = Workbook()
sheet = workbook.active
sheet.append([None, 'LIMBA FRANCEZĂ', 'LIMBA ROMÂNĂ', 'LIMBA ITALIANĂ'])
sheet.append(['ETIMON/ CORESPONDENTE ROMANICE', 'café', 'Romanian'])
sheet['B2'] = CellRichText('  café  \\t', TextBlock(InlineFont(b=True, u='double', strike=True, rFont='Times New Roman', sz=13, color='FF123456'), 'rich'), TextBlock(InlineFont(vertAlign='superscript'), '2'), '\\nsecond line  ')
sheet['B2'].fill = PatternFill('solid', fgColor='AAFFAA')
sheet.append(['SENSURI DE BAZĂ', 'notes\\nmore notes'])
sheet['A3'].fill = PatternFill('solid', fgColor='FFFFAA')
sheet['D3'].fill = PatternFill('solid', fgColor='CCDDFF')
sheet.append(['ETIMON/ CORESPONDENTE ROMANICE', 'other'])
sheet.append(['ETIMON/ CORESPONDENTE ROMANICE', 'scroll target'])
for number in range(50):
    sheet.append([f'SCROLL ROW {number:02}', f'content {number}'])
    sheet.cell(sheet.max_row, 1).fill = PatternFill('solid', fgColor='DDFFDD')
for number in range(50):
    sheet.append(['SENSURI DE BAZĂ' if number == 0 else None, f'sense {number}'])
workbook.create_sheet('Other sheet')['A1'] = 'not edited'
workbook.save(path)
workbook.close()
app = create_app(path)
app.extensions['access_control'].set_edit_password('temporary browser password')
app.config['DEFAULT_UI_LANGUAGE']='en'
server = create_server(app, host='127.0.0.1', port=0)
print(server.effective_port, flush=True)
server.run()
`;
const server = spawn(process.env.XLDB_PYTHON || path.join(root, ".venv/bin/python"), ["-u", "-c", source, directory], {
  cwd: root, stdio: ["ignore", "pipe", "inherit"],
});

// Keep polling in Node: waitForFunction's in-page eval can conflict with the
// application's strict CSP after htmx updates. Do not bypass CSP in the test.
async function waitState(page, predicate) {
  const deadline = Date.now() + 45000;
  while (!(await page.evaluate(predicate))) {
    if (Date.now() > deadline) throw new Error(`Timed out waiting for ${predicate}`);
    await new Promise(resolve => setTimeout(resolve, 50));
  }
}

async function main() {
  let browser;
  try {
    const lines = readline.createInterface({ input: server.stdout });
    const port = await Promise.race([
      once(lines, "line").then(([line]) => Number(line)),
      once(server, "exit").then(([code]) => { throw new Error(`Test server exited: ${code}`); }),
    ]);
    assert.ok(port > 0);
    const url = `http://127.0.0.1:${port}/`;
    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({ viewport: { width: 1440, height: 950 } });
    context.setDefaultNavigationTimeout(60000);
    context.setDefaultTimeout(60000);
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    page.on("console", message => {
      if (message.type() === "error") console.error("Browser:", message.text());
    });
    const payload = () => page.locator(".workspace-data").evaluate(element => JSON.parse(element.textContent));
    const cell = (row = 0, field = "content_0") => page.locator(`.tabulator-row .tabulator-cell[tabulator-field="${field}"]`).nth(row);
    const waitGrid = () => waitState(page, () => document.querySelector(".detail-panel.grid-active") && !document.querySelector('[aria-busy="true"]')).then(() =>
      page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    ).catch(async error => {
      console.error({ errors, status: await page.locator("#request-status").textContent() });
      throw error;
    });
    const quillValue = () => page.locator(".cell-editor .ql-container").evaluate(element => ({
      text: Quill.find(element).getText(), ops: Quill.find(element).getContents().ops,
    }));
    await page.goto(url);
    await waitGrid();
    assert.equal((await payload()).edit_mode, false);
    await cell().dblclick();
    if ((await payload()).edit_mode) await page.locator('.cell-editor').waitFor();
    assert.equal(await page.locator('.cell-editor').count(), 0);
    await page.getByRole('button', { name: 'Edit mode', exact: true }).click();
    await page.getByRole('textbox', {name:'Name', exact:true}).fill('Browser editor');
    await page.getByLabel('Edit password', {exact:true}).fill('temporary browser password');
    await page.getByRole('button', {name:'Sign in', exact:true}).click();
    await waitState(page, () => JSON.parse(document.querySelector('.workspace-data').textContent).edit_mode);
    await waitGrid();
    assert.equal(await page.locator('.search-panel').isVisible(), true);
    console.log('ok - Search mode is read-only; Edit mode enables editing and retains search controls');
    const before = await payload();
    let posts = 0;
    page.on("request", request => { if (request.method() === "POST" && new URL(request.url()).pathname.endsWith("/cell")) posts++; });

    const cellLineHeight = await cell().evaluate(element => getComputedStyle(element).lineHeight);
    await cell().dblclick();
    if ((await payload()).edit_mode) await page.locator('.cell-editor').waitFor();
    assert.equal(await page.locator('.ql-editor').evaluate(element => getComputedStyle(element).lineHeight), cellLineHeight);
    const imported = await quillValue();
    assert.equal(imported.text, "  café  \trich2\nsecond line  \n");
    const rich = imported.ops.find(op => op.insert === "rich");
    assert.equal(rich.attributes.bold, true);
    assert.equal(rich.attributes.underline, true);
    assert.equal(rich.attributes.strike, true);
    assert.equal(rich.attributes.font, "Times New Roman");
    assert.equal(rich.attributes.size, "13pt");
    assert.equal(imported.ops.find(op => op.insert === "2").attributes.script, "super");
    const geometry = await page.locator(".cell-editor").evaluate(panel => ({
      panel: panel.getBoundingClientRect().height,
      row: panel.closest(".tabulator-row").getBoundingClientRect().height,
    }));
    assert.ok(geometry.row >= geometry.panel, JSON.stringify(geometry));
    await page.getByRole("button", { name: "Close", exact: true }).click();
    await page.locator('.cell-editor').waitFor({state:'detached'});
    assert.equal(posts, 0);
    assert.deepEqual((await payload()).rows[0].editors, before.rows[0].editors);
    console.log("ok - imported rich text/whitespace and no-op close preserve original HTML");

    for (const target of [cell(), cell(1, 'content_1')]) {
      await target.dblclick();
      await page.locator('.cell-editor').waitFor();
      await page.keyboard.type('instant typing');
      assert.ok((await quillValue()).text.includes('instant typing'));
      const selection = await page.locator('.ql-editor').evaluate(element => ({
        focused: document.activeElement === element,
        inside: element.contains(window.getSelection().anchorNode),
        collapsed: window.getSelection().isCollapsed,
      }));
      assert.deepEqual(selection, { focused: true, inside: true, collapsed: true });
      await page.keyboard.press('Escape');
    await page.locator('.cell-editor').waitFor({state:'detached'});
    }
    assert.equal(posts, 0);
    console.log('ok - double-click focuses cell contents immediately in populated and empty cells');

    await cell().dblclick();
    if ((await payload()).edit_mode) await page.locator('.cell-editor').waitFor();
    await page.locator(".ql-editor").fill("cancelled draft");
    await page.keyboard.press("Escape");
    await page.locator('.cell-editor').waitFor({state:'detached'});
    assert.equal(posts, 0);
    assert.deepEqual((await payload()).rows[0].editors, before.rows[0].editors);
    console.log("ok - Escape cancels without saving");

    await cell(1).dblclick();
    if ((await payload()).edit_mode) await page.locator('.cell-editor').waitFor();
    const editorText = page.locator('.ql-editor');
    await page.locator('.cell-editor .ql-container').evaluate(element => Quill.find(element).setSelection(0, 3, 'user'));
    await page.getByRole('button', { name: 'Typography', exact: true }).click();
    const sizeInput = page.getByLabel('Font size (pt)', { exact: true });
    await sizeInput.fill('18');
    await page.getByRole('button', { name: 'Apply size', exact: true }).click();
    const sized = (await quillValue()).ops;
    assert.equal(sized.find(op => op.insert === 'not')?.attributes?.size, '18pt', JSON.stringify(sized));
    assert.ok(sized.some(op => op.insert.includes('es') && op.attributes?.size !== '18pt'));
    await page.getByLabel('Line spacing (whole cell)', { exact: true }).selectOption('2');
    const lineRatios = await editorText.locator('p').evaluateAll(lines => lines.map(line => {
      const style = getComputedStyle(line);
      return parseFloat(style.lineHeight) / parseFloat(style.fontSize);
    }));
    assert.ok(lineRatios.length >= 2);
    assert.ok(lineRatios.every(ratio => Math.abs(ratio - 2) < 0.01));
    await page.getByRole('button', { name: 'Close', exact: true }).click();
    await page.locator('.cell-editor').waitFor({state:'detached'});
    await waitState(page, () => JSON.parse(document.querySelector('.workspace-data').textContent).rows[1].editors.content_0.line_height === 2);
    await waitGrid();
    assert.ok((await payload()).rows[1].content_0.includes('font-size: 18pt'));
    assert.equal(await cell(1).evaluate(element => parseFloat(getComputedStyle(element).lineHeight) / parseFloat(getComputedStyle(element).fontSize)), 2);
    await cell(1).dblclick();
    if ((await payload()).edit_mode) await page.locator('.cell-editor').waitFor();
    assert.equal((await quillValue()).ops.find(op => op.insert === 'not').attributes.size, '18pt');
    await page.getByRole('button', { name: 'Typography', exact: true }).click();
    assert.equal(await page.getByLabel('Line spacing (whole cell)', { exact: true }).inputValue(), '2');
    await page.getByLabel('Line spacing (whole cell)', { exact: true }).selectOption('3');
    await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    await page.locator('.cell-editor').waitFor({state:'detached'});
    assert.equal((await payload()).rows[1].editors.content_0.line_height, 2);
    assert.equal(posts, 1);
    // Spacing alone must count as an edit, even when the Delta is unchanged.
    await cell(1).dblclick();
    if ((await payload()).edit_mode) await page.locator('.cell-editor').waitFor();
    await page.getByRole('button', { name: 'Typography', exact: true }).click();
    await page.getByLabel('Line spacing (whole cell)', { exact: true }).selectOption('1.5');
    await page.getByRole('button', { name: 'Close', exact: true }).click();
    await page.locator('.cell-editor').waitFor({state:'detached'});
    await waitState(page, () => JSON.parse(document.querySelector('.workspace-data').textContent).rows[1].editors.content_0.line_height === 1.5);
    await waitGrid();
    await cell(1).dblclick();
    if ((await payload()).edit_mode) await page.locator('.cell-editor').waitFor();
    await page.getByRole('button', { name: 'Typography', exact: true }).click();
    await page.getByRole('button', { name: 'Close', exact: true }).click();
    await page.locator('.cell-editor').waitFor({state:'detached'});
    assert.equal(posts, 2);
    posts = 0;
    console.log('ok - inherited line height, selected font size, whole-cell spacing, reopening and Cancel');

    const otherContext = await browser.newContext();
    otherContext.setDefaultNavigationTimeout(60000);
    otherContext.setDefaultTimeout(60000);
    const other = await otherContext.newPage();
    await other.goto(url);
    await other.waitForSelector(".detail-panel.grid-active");
    await other.getByRole('button', { name: 'Edit mode', exact: true }).click();
    await other.getByRole('textbox', {name:'Name', exact:true}).fill('Other editor');
    await other.getByLabel('Edit password', {exact:true}).fill('temporary browser password');
    await other.getByRole('button', {name:'Sign in', exact:true}).click();
    await waitState(other, () => JSON.parse(document.querySelector('.workspace-data').textContent).edit_mode);
    await waitState(other, () => document.querySelector('.detail-panel.grid-active'));
    await other.locator('.tabulator-cell[tabulator-field="content_0"]').first().dblclick();
    await other.locator(".ql-editor").fill("stale draft");
    await cell().dblclick();
    await page.locator('#request-status').filter({hasText:'Other editor is editing this cell'}).waitFor();
    assert.equal(await page.locator('.cell-editor').count(),0);
    await other.getByRole('button',{name:'Cancel',exact:true}).click();
    await other.locator('.cell-editor').waitFor({state:'detached'});
    await cell().dblclick();
    if ((await payload()).edit_mode) await page.locator('.cell-editor').waitFor();
    await page.locator(".ql-editor").fill("  Prăjitură  \nline two  ");
    await page.getByRole('link', { name: 'Export Excel', exact: true }).click();
    assert.equal(await page.locator('#export-dialog').isVisible(),false);
    assert.equal(await page.locator('.cell-editor').count(), 1);
    await page.getByRole('button', { name: 'Edit mode', exact: true }).click();
    assert.equal(await page.locator(".cell-editor").count(), 1);
    await page.keyboard.press("Control+Enter");
    await waitState(page, () => JSON.parse(document.querySelector(".workspace-data").textContent).rows[0].editors.content_0.html.includes('Prăjitură'));
    await waitGrid();
    assert.equal(posts, 1);
    await other.reload();
    await other.waitForSelector(".detail-panel.grid-active");
    assert.ok((await other.locator('.tabulator-cell[tabulator-field="content_0"]').first().innerText()).includes("Prăjitură"));
    console.log("ok - shared save, navigation guard and exclusive cell editing");

    await page.getByRole('button', { name: 'Edit mode', exact: true }).click();
    await waitState(page, () => !JSON.parse(document.querySelector('.workspace-data').textContent).edit_mode);
    await waitGrid();
    await page.locator("#query").fill("prajitura");
    await page.getByRole("button", { name: "Search", exact: false }).click();
    await page.locator(".search-highlight").first().waitFor();
    await page.getByRole("link", { name: "Plain text", exact: true }).click();
    await waitState(page, () => JSON.parse(document.querySelector(".workspace-data").textContent).plaintext === true);
    await waitGrid();
    await cell().dblclick();
    if ((await payload()).edit_mode) await page.locator('.cell-editor').waitFor();
    assert.equal(await page.locator('.cell-editor').count(), 0);
    await page.getByRole('button', { name: 'Edit mode', exact: true }).click();
    await waitState(page, () => JSON.parse(document.querySelector('.workspace-data').textContent).edit_mode);
    await waitGrid();
    await cell().dblclick();
    if ((await payload()).edit_mode) await page.locator('.cell-editor').waitFor();
    assert.equal((await quillValue()).text, "  Prăjitură  \nline two  \n");
    assert.equal(await page.locator(".ql-editor mark").count(), 0);
    await page.getByRole("button", { name: "Cancel", exact: true }).click();
    await page.locator('.cell-editor').waitFor({state:'detached'});
    console.log("ok - Search mode highlights saved content; switching to Edit mode keeps plaintext and loads formatted originals");
    assert.equal(await cell(1).evaluate(element => parseFloat(getComputedStyle(element).lineHeight) / parseFloat(getComputedStyle(element).fontSize)), 1.5);

    await cell(1, "content_1").dblclick();
    if ((await payload()).edit_mode) await page.locator('.cell-editor').waitFor();
    assert.equal(await cell(1, 'content_1').evaluate(element => getComputedStyle(element.querySelector('.cell-editor')).backgroundColor), 'rgb(255, 255, 170)');
    await page.locator(".ql-editor").fill("new empty-cell text");
    await page.getByRole("button", { name: "Close", exact: true }).click();
    await page.locator('.cell-editor').waitFor({state:'detached'});
    await waitState(page, () => JSON.parse(document.querySelector(".workspace-data").textContent).rows[1].content_1 === 'new empty-cell text');
    await waitGrid();
    assert.equal((await payload()).rows[1].backgrounds.content_1, '#FFFFAA');
    assert.equal(await cell(1, 'content_1').evaluate(element => getComputedStyle(element).backgroundColor), 'rgb(255, 255, 170)');
    await cell(1, "content_1").dblclick();
    if ((await payload()).edit_mode) await page.locator('.cell-editor').waitFor();
    await page.locator(".ql-editor").fill("");
    await page.getByRole("button", { name: "Close", exact: true }).click();
    await page.locator('.cell-editor').waitFor({state:'detached'});
    await waitState(page, () => JSON.parse(document.querySelector(".workspace-data").textContent).rows[1].content_1 === '');
    assert.equal((await payload()).rows[1].backgrounds.content_1, "#FFFFAA");
    console.log("ok - empty cells can be filled and cleared, retaining label fills");

    const ownFill = cell(1, 'content_2');
    assert.equal(await ownFill.evaluate(element => getComputedStyle(element).backgroundColor), 'rgb(204, 221, 255)');
    await ownFill.dblclick();
    await page.locator('.cell-editor').waitFor();
    assert.equal(await ownFill.evaluate(element => getComputedStyle(element.querySelector('.cell-editor')).backgroundColor), 'rgb(204, 221, 255)');
    await page.locator('.ql-editor').fill('originally blank with its own fill');
    await page.keyboard.press('Control+Enter');
    await waitState(page, () => JSON.parse(document.querySelector('.workspace-data').textContent).rows[1].content_2 === 'originally blank with its own fill');
    await waitGrid();
    assert.equal(await ownFill.evaluate(element => getComputedStyle(element).backgroundColor), 'rgb(204, 221, 255)');
    console.log('ok - an originally empty cell retains its own workbook fill during and after editing');

    const downloading = page.waitForEvent('download');
    await page.getByRole('link', { name: 'Export Excel', exact: true }).click();
    await page.getByRole('button',{name:'Download Excel',exact:true}).click();
    const download = await downloading;
    assert.match(download.suggestedFilename(), /^browser_\d{4}-\d{2}-\d{2}_.*\.xlsx$/);
    execFileSync(process.env.XLDB_PYTHON || path.join(root, '.venv/bin/python'), ['-c', `
import sys
from io import BytesIO
from pathlib import Path
from openpyxl import load_workbook
workbook = load_workbook(BytesIO(Path(sys.argv[1]).read_bytes()), rich_text=True)
assert str(workbook.worksheets[0]['B2'].value) == '  Prăjitură  \\nline two  '
assert str(workbook.worksheets[0]['B4'].value) == 'other'
assert workbook['Other sheet']['A1'].value == 'not edited'
workbook.close()
`, await download.path()]);
    console.log('ok - timestamped full-workbook download includes saved edits and untouched sheets');

    await page.goto(`${url}?reset=1&etimon=3`);
    await waitGrid();
    const target = page.locator('.tabulator-row').filter({ has: page.locator('.grid-label', { hasText: 'SCROLL ROW 25' }) }).locator('[tabulator-field="content_5"]');
    const position = () => page.locator('.tabulator-tableholder').evaluate(element => ({ left: element.scrollLeft, top: element.scrollTop }));
    for (const action of ['save', 'cancel', 'no-op']) {
      await target.dblclick();
      await page.locator('.cell-editor').waitFor();
      if (action !== 'no-op') await page.locator('.ql-editor').fill(action === 'save' ? 'saved while scrolled' : 'discard this');
      const beforeClose = await position();
      assert.ok(beforeClose.left > 100 && beforeClose.top > 100, JSON.stringify(beforeClose));
      await page.keyboard.press(action === 'cancel' ? 'Escape' : 'Control+Enter');
      await page.locator('.cell-editor').waitFor({ state: 'detached' });
      if (action === 'save') {
        await waitState(page, () => JSON.parse(document.querySelector('.workspace-data').textContent).rows.some(row => row.content_5 === 'saved while scrolled'));
        await waitGrid();
      }
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      const afterClose = await position();
      assert.ok(Math.abs(afterClose.left - beforeClose.left) <= 2 && Math.abs(afterClose.top - beforeClose.top) <= 2,
        JSON.stringify({ action, beforeClose, afterClose }));
    }
    console.log('ok - Save, Cancel and no-op Close retain horizontal and vertical table scroll');

    const countBefore = (await payload()).total;
    await page.getByRole('button', { name: 'Add row', exact: true }).click();
    assert.equal(await page.locator('.add-row-options').isVisible(), true);
    assert.equal(await page.locator('[data-add-row]').count(), 3);
    await page.getByRole('button', { name: 'SENSURI DE BAZĂ', exact: true }).click();
    assert.equal(await page.locator('#create-entry-dialog').isVisible(), true);
    assert.equal(await page.getByLabel('Text for LIMBA FRANCEZĂ', { exact: true }).inputValue(), '[To be added]');
    await page.getByLabel('Text for LIMBA FRANCEZĂ', { exact: true }).fill('   ');
    await page.getByRole('button', { name: 'Create', exact: true }).click();
    await page.locator('.creation-error').getByText('Enter text', { exact: false }).waitFor();
    await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    await page.locator('.cell-editor').waitFor({state:'detached'});
    assert.equal((await payload()).total, countBefore);
    await page.getByRole('button', { name: 'Add row', exact: true }).click();
    await page.getByRole('button', { name: 'SENSURI DE BAZĂ', exact: true }).click();
    await page.getByLabel('Text for LIMBA FRANCEZĂ', { exact: true }).fill('nouveau sens <>&');
    await page.getByRole('button', { name: 'Create', exact: true }).click();
    await waitState(page, () => JSON.parse(document.querySelector('.workspace-data').textContent).rows.some(row => row.label === 'SENSURI DE BAZĂ' && row.content_0.includes('nouveau sens')));
    await waitGrid();
    await waitState(page, () => document.activeElement?.getAttribute('tabulator-field') === 'content_0');
    const added = (await payload()).rows.find(row => row.content_0.includes('nouveau sens'));
    assert.equal(added.label_number, 51);
    assert.deepEqual([...new Set(Object.values(added.backgrounds))], ['#F7CAAC']);
    assert.equal(await page.locator('.tabulator-cell[tabulator-field="content_0"]').filter({ hasText: 'nouveau sens' })
      .evaluate(element => getComputedStyle(element).backgroundColor), 'rgb(247, 202, 172)');
    assert.equal((await payload()).etimon, 3);
    const visibility = await page.locator('.tabulator-cell[tabulator-field="content_0"]').filter({ hasText: 'nouveau sens' }).evaluate(element => {
      const viewport = element.closest('.tabulator-tableholder');
      const cell = element.getBoundingClientRect(), bounds = viewport.getBoundingClientRect();
      return { top: viewport.scrollTop, visible: cell.top >= bounds.top && cell.bottom <= bounds.bottom && cell.right <= bounds.right };
    });
    assert.ok(visibility.visible && visibility.top > 200, JSON.stringify(visibility));
    console.log('ok - Add row dropdown requires text, Cancel changes nothing, and the new row is focused and scrolled into view');

    await page.getByRole('button', { name: 'Add etymon', exact: true }).click();
    assert.equal(await page.getByLabel('Text for LIMBA FRANCEZĂ', { exact: true }).inputValue(), '[To be added]');
    await page.getByLabel('Text for LIMBA FRANCEZĂ', { exact: true }).fill('quatrième mot');
    await page.getByRole('button', { name: 'Create', exact: true }).click();
    await waitState(page, () => JSON.parse(document.querySelector('.workspace-data').textContent).etimon === 4);
    await waitGrid();
    const createdEtymon = await payload();
    assert.equal(createdEtymon.total, 4);
    assert.equal(createdEtymon.rows.length, 1);
    assert.equal(createdEtymon.rows[0].label_number, 1);
    assert.ok(createdEtymon.rows[0].label.startsWith('ETIMON/'));
    assert.deepEqual([...new Set(Object.values(createdEtymon.rows[0].backgrounds))], ['#D9E2F3']);
    assert.ok(createdEtymon.title.includes('quatrième mot'));
    assert.ok((await page.locator('.collection-count').textContent()).startsWith('4 '));
    await cell().dblclick();
    if ((await payload()).edit_mode) await page.locator('.cell-editor').waitFor();
    assert.equal((await quillValue()).text, 'quatrième mot\n');
    await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    await page.locator('.cell-editor').waitFor({state:'detached'});
    await page.locator('#query').fill('quatrième');
    await page.locator('[data-search-filter="column"] > summary').click();
    await page.locator('.search-form input[name="column"][value="LIMBA FRANCEZĂ"]').check();
    await page.getByRole('button', { name: 'Search', exact: false }).click();
    await waitState(page, () => JSON.parse(document.querySelector('.workspace-data').textContent).criteria.query === 'quatrième');
    await waitGrid();
    assert.equal((await payload()).edit_mode, true);
    assert.deepEqual((await payload()).criteria.column, ['LIMBA FRANCEZĂ']);
    assert.equal(await page.locator('.etimon-link').count(), 1);
    await cell().dblclick();
    if ((await payload()).edit_mode) await page.locator('.cell-editor').waitFor();
    assert.equal(await page.locator('.ql-editor mark').count(), 0);
    await page.keyboard.type(' direct');
    assert.ok((await quillValue()).text.includes('direct'));
    await page.keyboard.press('Escape');
    await page.locator('.cell-editor').waitFor({state:'detached'});
    console.log('ok - Add etymon assigns the next number, refreshes navigation/count/title, and opens normally in Quill');

    await page.getByRole('button', { name: 'Add row', exact: true }).click();
    await page.getByRole('button', { name: 'SENSURI DE BAZĂ', exact: true }).click();
    await page.getByLabel('Text for LIMBA FRANCEZĂ', { exact: true }).fill('sens du nouveau mot');
    await page.getByRole('button', { name: 'Create', exact: true }).click();
    await waitState(page, () => JSON.parse(document.querySelector('.workspace-data').textContent).rows.length === 2);
    await waitGrid();
    const newSense = page.locator('.tabulator-cell[tabulator-field="content_0"]').filter({ hasText: 'sens du nouveau mot' });
    assert.equal(await newSense.evaluate(element => getComputedStyle(element).backgroundColor), 'rgb(247, 202, 172)');
    await newSense.dblclick();
    assert.equal(await page.locator('.cell-editor').evaluate(element => getComputedStyle(element).backgroundColor), 'rgb(247, 202, 172)');
    await page.keyboard.press('Escape');
    await page.locator('.cell-editor').waitFor({state:'detached'});
    console.log('ok - New basic-sense rows are orange in new etymons and retain that color in Quill');

    await newSense.dblclick();
    await page.locator('.ql-editor').waitFor();
    await page.getByRole('button', { name: 'Delete etymon', exact: true }).click();
    assert.equal(await page.locator('#delete-entry-dialog').isVisible(), false);
    await page.keyboard.press('Escape');
    await page.locator('.cell-editor').waitFor({state:'detached'});
    await page.locator('.tabulator-row .delete-row').click();
    assert.ok((await page.locator('#delete-entry-description').textContent()).includes('SENSURI DE BAZĂ #1'));
    const confirmDelete = page.getByRole('button', { name: 'Move to Trash', exact: true });
    assert.equal(await confirmDelete.isDisabled(), true);
    await page.getByLabel('Type DELETE to confirm', { exact: true }).fill('yes');
    assert.equal(await confirmDelete.isDisabled(), true);
    await page.keyboard.press('Escape');
    await page.locator('.cell-editor').waitFor({state:'detached'});
    assert.equal((await payload()).rows.length, 2);
    await page.locator('.tabulator-row .delete-row').click();
    await page.getByLabel('Type DELETE to confirm', { exact: true }).fill('DELETE');
    await confirmDelete.click();
    await waitState(page, () => JSON.parse(document.querySelector('.workspace-data').textContent).rows.length === 1);
    await waitGrid();
    assert.equal((await payload()).etimon, 4);
    const db = path.join(directory, 'browser.xlsx.sqlite3');
    const admin = (...args) => execFileSync(process.env.XLDB_PYTHON || path.join(root, '.venv/bin/python'),
      [path.join(root, 'trash.py'), db, ...args], { encoding: 'utf8' });
    const rowTrash = admin('list').match(/^(\d+) ·/)[1];
    admin('restore', rowTrash);
    await page.goto(`${url}?etimon=4`);
    await waitGrid();
    assert.equal((await payload()).rows.length, 2);
    assert.equal(await page.locator('.tabulator-cell[tabulator-field="content_0"]').filter({ hasText: 'sens du nouveau mot' })
      .evaluate(element => getComputedStyle(element).backgroundColor), 'rgb(247, 202, 172)');
    console.log('ok - Row deletion requires typed confirmation, Escape cancels, open editing blocks deletion, and local recovery restores the row');

    await page.getByRole('button', { name: 'Delete etymon', exact: true }).click();
    assert.ok((await page.locator('#delete-entry-description').textContent()).includes('ALL its rows'));
    await page.locator('[data-cancel-delete]').click();
    assert.equal((await payload()).total, 4);
    await page.getByRole('button', { name: 'Delete etymon', exact: true }).click();
    await page.getByLabel('Type DELETE to confirm', { exact: true }).fill('DELETE');
    await confirmDelete.click();
    await waitState(page, () => JSON.parse(document.querySelector('.workspace-data').textContent).total === 3);
    assert.equal((await payload()).etimon, null);
    assert.ok((await page.locator('.collection-count').textContent()).startsWith('3 '));
    const trashedDownloadEvent = page.waitForEvent('download');
    await page.getByRole('link', { name: 'Export Excel', exact: true }).click();
    await page.getByRole('button',{name:'Download Excel',exact:true}).click();
    const trashedDownload = await trashedDownloadEvent;
    execFileSync(process.env.XLDB_PYTHON || path.join(root, '.venv/bin/python'), ['-c', `
import sys
from io import BytesIO
from pathlib import Path
from openpyxl import load_workbook
book = load_workbook(BytesIO(Path(sys.argv[1]).read_bytes()), rich_text=True)
sheet = book.worksheets[0]
assert sum(str(row[0] or '').startswith('ETIMON/') for row in sheet.iter_rows(values_only=True)) == 3
assert not any('quatrième' in str(cell.value) or 'sens du nouveau mot' in str(cell.value) for row in sheet for cell in row)
book.close()
`, await trashedDownload.path()]);
    const etymonTrash = admin('list').match(/^(\d+) ·/)[1];
    admin('restore', etymonTrash);
    await page.goto(`${url}?reset=1&etimon=4`);
    await waitGrid();
    assert.equal((await payload()).total, 4);
    assert.equal((await payload()).rows.length, 2);
    await page.getByRole('button', { name: 'Edit mode', exact: true }).click();
    await waitState(page, () => !JSON.parse(document.querySelector('.workspace-data').textContent).edit_mode);
    await waitGrid();
    assert.equal(await page.locator('[data-delete-row], [data-delete-etymon]').count(), 0);
    console.log('ok - Etymon deletion updates filtered navigation/counts and Excel, recovery restores all rows, and Search mode hides deletion');

    assert.deepEqual(errors, []);
    console.log("Browser editor checks passed.");
  } finally {
    if (browser) await browser.close();
    if (server.exitCode === null) {
      const exited = once(server, "exit");
      server.kill();
      await exited;
    }
    rmSync(directory, { recursive: true, force: true });
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
