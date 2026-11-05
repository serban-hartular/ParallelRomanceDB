/* Optional real-browser regression check. Requires Playwright + Chromium.
 * Starts its own loopback server and temporary workbook; never uses a live site.
 * NODE_PATH=/path/to/node_modules node tests/test_cell_editor_browser.js
 */
"use strict";
const assert = require("node:assert/strict");
const { spawn } = require("node:child_process");
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
sheet.append([None, 'LIMBA FRANCEZĂ', 'LIMBA ROMÂNĂ'])
sheet.append(['ETIMON/ CORESPONDENTE ROMANICE', 'café', 'Romanian'])
sheet['B2'] = CellRichText('  café  \\t', TextBlock(InlineFont(b=True, u='double', strike=True, rFont='Times New Roman', sz=13, color='FF123456'), 'rich'), TextBlock(InlineFont(vertAlign='superscript'), '2'), '\\nsecond line  ')
sheet['B2'].fill = PatternFill('solid', fgColor='AAFFAA')
sheet.append(['SENSURI DE BAZĂ', 'notes\\nmore notes'])
sheet['A3'].fill = PatternFill('solid', fgColor='FFFFAA')
sheet.append(['ETIMON/ CORESPONDENTE ROMANICE', 'other'])
workbook.save(path)
workbook.close()
server = create_server(create_app(path), host='127.0.0.1', port=0)
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
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    page.on("console", message => {
      if (message.type() === "error") console.error("Browser:", message.text());
    });
    const payload = () => page.locator(".workspace-data").evaluate(element => JSON.parse(element.textContent));
    const cell = (row = 0, field = "content_0") => page.locator(`.tabulator-row .tabulator-cell[tabulator-field="${field}"]`).nth(row);
    const waitGrid = () => waitState(page, () => document.querySelector(".detail-panel.grid-active") && !document.querySelector('[aria-busy="true"]')).catch(async error => {
      console.error({ errors, status: await page.locator("#request-status").textContent() });
      throw error;
    });
    const quillValue = () => page.locator(".cell-editor .ql-container").evaluate(element => ({
      text: Quill.find(element).getText(), ops: Quill.find(element).getContents().ops,
    }));
    await page.goto(url);
    await waitGrid();
    const before = await payload();
    let posts = 0;
    page.on("request", request => { if (request.method() === "POST") posts++; });

    const cellLineHeight = await cell().evaluate(element => getComputedStyle(element).lineHeight);
    await cell().dblclick();
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
    assert.equal(posts, 0);
    assert.deepEqual((await payload()).rows[0].editors, before.rows[0].editors);
    console.log("ok - imported rich text/whitespace and no-op close preserve original HTML");

    await cell().dblclick();
    await page.locator(".ql-editor").fill("cancelled draft");
    await page.keyboard.press("Escape");
    assert.equal(posts, 0);
    assert.deepEqual((await payload()).rows[0].editors, before.rows[0].editors);
    console.log("ok - Escape cancels without saving");

    await cell(1).dblclick();
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
    await waitState(page, () => JSON.parse(document.querySelector('.workspace-data').textContent).rows[1].editors.content_0.line_height === 2);
    await waitGrid();
    assert.ok((await payload()).rows[1].content_0.includes('font-size: 18pt'));
    assert.equal(await cell(1).evaluate(element => parseFloat(getComputedStyle(element).lineHeight) / parseFloat(getComputedStyle(element).fontSize)), 2);
    await cell(1).dblclick();
    assert.equal((await quillValue()).ops.find(op => op.insert === 'not').attributes.size, '18pt');
    await page.getByRole('button', { name: 'Typography', exact: true }).click();
    assert.equal(await page.getByLabel('Line spacing (whole cell)', { exact: true }).inputValue(), '2');
    await page.getByLabel('Line spacing (whole cell)', { exact: true }).selectOption('3');
    await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    assert.equal((await payload()).rows[1].editors.content_0.line_height, 2);
    assert.equal(posts, 1);
    // Spacing alone must count as an edit, even when the Delta is unchanged.
    await cell(1).dblclick();
    await page.getByRole('button', { name: 'Typography', exact: true }).click();
    await page.getByLabel('Line spacing (whole cell)', { exact: true }).selectOption('1.5');
    await page.getByRole('button', { name: 'Close', exact: true }).click();
    await waitState(page, () => JSON.parse(document.querySelector('.workspace-data').textContent).rows[1].editors.content_0.line_height === 1.5);
    await waitGrid();
    await cell(1).dblclick();
    await page.getByRole('button', { name: 'Typography', exact: true }).click();
    await page.getByRole('button', { name: 'Close', exact: true }).click();
    assert.equal(posts, 2);
    posts = 0;
    console.log('ok - inherited line height, selected font size, whole-cell spacing, reopening and Cancel');

    const otherContext = await browser.newContext();
    const other = await otherContext.newPage();
    await other.goto(url);
    await other.waitForSelector(".detail-panel.grid-active");
    await other.locator('.tabulator-cell[tabulator-field="content_0"]').first().dblclick();
    await other.locator(".ql-editor").fill("stale draft");
    await cell().dblclick();
    await page.locator(".ql-editor").fill("  Prăjitură  \nline two  ");
    await page.getByRole("button", { name: "Search", exact: false }).click();
    assert.equal(await page.locator(".cell-editor").count(), 1);
    await page.keyboard.press("Control+Enter");
    await waitState(page, () => JSON.parse(document.querySelector(".workspace-data").textContent).rows[0].editors.content_0.html.includes('Prăjitură'));
    await waitGrid();
    assert.equal(posts, 1);
    await other.getByRole("button", { name: "Close", exact: true }).click();
    await other.getByText("Someone else changed this cell.", { exact: false }).waitFor();
    assert.equal(await other.locator(".ql-editor").innerText(), "stale draft");
    await other.getByRole("button", { name: "Cancel", exact: true }).click();
    await other.reload();
    await other.waitForSelector(".detail-panel.grid-active");
    assert.ok((await other.locator('.tabulator-cell[tabulator-field="content_0"]').first().innerText()).includes("Prăjitură"));
    console.log("ok - shared save, navigation guard and conflicting draft preservation");

    await page.locator("#query").fill("prajitura");
    await page.getByRole("button", { name: "Search", exact: false }).click();
    await page.locator(".search-highlight").first().waitFor();
    await page.getByRole("link", { name: "Plain text", exact: true }).click();
    await waitState(page, () => JSON.parse(document.querySelector(".workspace-data").textContent).plaintext === true);
    await waitGrid();
    await cell().dblclick();
    assert.equal((await quillValue()).text, "  Prăjitură  \nline two  \n");
    assert.equal(await page.locator(".ql-editor mark").count(), 0);
    await page.getByRole("button", { name: "Cancel", exact: true }).click();
    console.log("ok - search and plain-text mode use saved content without importing highlights");
    assert.equal(await cell(1).evaluate(element => parseFloat(getComputedStyle(element).lineHeight) / parseFloat(getComputedStyle(element).fontSize)), 1.5);

    await cell(1, "content_1").dblclick();
    await page.locator(".ql-editor").fill("new empty-cell text");
    await page.getByRole("button", { name: "Close", exact: true }).click();
    await waitState(page, () => JSON.parse(document.querySelector(".workspace-data").textContent).rows[1].content_1 === 'new empty-cell text');
    await waitGrid();
    await cell(1, "content_1").dblclick();
    await page.locator(".ql-editor").fill("");
    await page.getByRole("button", { name: "Close", exact: true }).click();
    await waitState(page, () => JSON.parse(document.querySelector(".workspace-data").textContent).rows[1].content_1 === '');
    assert.equal((await payload()).rows[1].backgrounds.content_1, "#FFFFAA");
    console.log("ok - empty cells can be filled and cleared, retaining label fills");

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
