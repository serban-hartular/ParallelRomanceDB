# XLDB

A Flask interface for searching, comparing, and editing etymons imported from an Excel workbook.
The page is branded **Parallel Words**; its header shows the loaded workbook's
filename followed by the actual worksheet name (including when the first sheet
is selected automatically).

For the development handoff, agreed behavior, future work, and a prompt to paste
into a new chat, read [HANDOFF.md](HANDOFF.md). Remote deployment instructions
and untested deployment assumptions are in [DEPLOYMENT.md](DEPLOYMENT.md).

Run the server from this directory:

```bash
.venv/bin/python main.py
```

Open **http://127.0.0.1:5000**. On first use, the app imports `db/example.xlsx`
into `db/example.xlsx.sqlite3`. Later starts reopen SQLite and retain edits.
To import a different workbook, optionally choosing a worksheet:

```bash
.venv/bin/python main.py "db/my workbook.xlsx"
.venv/bin/python main.py "db/my workbook.xlsx" --sheet "Sheet 2"
```

Local access is the default. To choose a port or allow other machines to connect:

```bash
.venv/bin/python main.py --local --port 8080
.venv/bin/python main.py "db/my workbook.xlsx" --public --port 8080
```

`--public` listens on all IPv4 interfaces; open `http://SERVER-IP:8080` from
another machine. `--host IP` can bind one specific IPv4/IPv6 interface instead.
The command uses Waitress rather than Flask's development server. For remote
deployment, read [DEPLOYMENT.md](DEPLOYMENT.md), covering HTTPS proxies,
`--trusted-host`, `--trusted-proxy`, `--secure-cookies`, firewall access, service
permissions, and request limits. **There is no login: every reachable user can
read, edit, delete, and export the database content.** This stage assumes one local user;
put private data behind a VPN or authenticated proxy before allowing remote access.

Omitting the file keeps the bundled example. Omitting `--sheet` (or `-s`) selects
the **first worksheet**, not the active worksheet. Sheet names match exactly.
Provided relative file paths are resolved from the directory where you run the
command; the default example path is relative to `main.py`. Use
`.venv/bin/python main.py --help` for usage without loading a workbook.
Once initialized, the database takes precedence over Excel. Restarting does
not reimport a changed workbook. Use a new database path to import a new version
without replacing existing edits. Python callers can use
`create_app('db/other.xlsx', sheet_name='Sheet1', database_path='db/research.sqlite3')`.

**SQLite storage and Excel export**

```bash
# Import only if this database has not yet been initialized; otherwise reopen it.
.venv/bin/python main.py "db/my workbook.xlsx" --database db/research.sqlite3

# The workbook is no longer needed after import, including for export.
.venv/bin/python main.py --database db/research.sqlite3

# Export a full updated workbook and exit, without starting a web server.
.venv/bin/python main.py --database db/research.sqlite3 --export
.venv/bin/python main.py --database db/research.sqlite3 --export --export-dir exports
```

Without `--database`, a sidecar named `<workbook filename>.sqlite3` is used.
An explicit `--sheet` adds a short sheet-name hash so different sheets get
different databases. A database contains one imported worksheet, with the
original eight DataFrame fields in `cells`, plus permanent cell IDs, persisted
revisions, and line spacing. Supporting tables retain row/column positions,
label fills, Trash entries, dataset identity, and the entire imported workbook template.
The website reads and writes SQLite; a temporary DataFrame for the selected
etymon is used only to reconstruct its display table.

**Export Excel** in the page header saves a new workbook and downloads it.
Exports contain **the entire original workbook, with the selected sheet
updated**, regardless of the current search. Close or cancel an open editor
first. Files go to `exports/` beside the database (or `--export-dir`), named
`<workbook>_YYYY-MM-DD_HH-MM-SS_microseconds+offset.xlsx` (or `.xlsm`). The time
zone is Europe/Bucharest. Existing files are never replaced by this operation.
Back up the SQLite file as well; Excel export is a convenient working copy.

Export uses the original worksheet layout, preserving label spelling,
spacing, headings, and untouched workbook parts. Added rows are inserted in
their etymon/category, copying formatting from a matching row when available,
with the configured default background for their row type.
New cells receive a complete border outline even when the source row has
missing edges; existing cells and their borders remain unchanged.
References to shifted rows in formulas, named ranges, validations, and worksheet
layout are adjusted; other sheets change only where their references require it.
An inherited label is made explicit when necessary to preserve its meaning
after inserting another category. Edited
text is written as Excel rich text, including fonts, sizes, colors, bold,
italics, underline, strike, and sub/superscript. Unformatted edited text uses
the editor's default color and 9 pt sans-serif font (Segoe UI in Excel), rather
than inheriting the original Excel cell's font/color. Rich-text runs retain
spaces, tabs, and blank lines, including runs consisting entirely of whitespace.
Existing formulas stay formulas;
formula-like text entered in Quill stays text. Excel has no direct equivalent
of CSS line spacing or per-run text background highlights: export provides
room through edited row heights, and retains these settings fully in SQLite.
Original cell and label fills stay intact.

Python export helpers in `excel_export.py`:

```python
from lexicon_db import LexiconDB
from excel_export import export_timestamped, overwrite_sheet

store = LexiconDB('db/research.sqlite3')  # Open an initialized database.
try:
    new_file = export_timestamped(store, 'exports')
    # Explicit opt-in: overwrite an existing sheet; never invoked by the website.
    overwrite_sheet(store, 'a-copy-of-my-workbook.xlsx', sheet_name='Sheet1')
finally:
    store.close()
```

The overwrite helper copies the database's selected sheet into the named
existing sheet and preserves the other sheets' data. It uses openpyxl's
supported worksheet features; advanced drawings and unsupported Excel features
can be affected. Normal timestamped export preserves the original archive's
unrelated parts instead. There are no accounts, shared-password access,
editing locks, or cell edit history in this first database stage.

**Deleting and recovering rows/etymons**

In Edit mode, **Delete row** appears beneath each non-etymon row's label;
**Delete etymon** in the table toolbar removes the whole etymon, in every
language. An etymon marker cannot be deleted as an individual row. Close or
cancel an open cell editor first. The dialog identifies the item, asks
“Are you really, really sure?”, and requires typing `DELETE` before **Move to
Trash** becomes available. Cancel or Escape leaves everything intact. If another
edit changed the item since the page loaded, reload and review it before deleting.

Deleted items disappear from searches, navigation, counts, and Excel exports.
SQLite retains every cell's exact text, formatting, ID, revision, and spacing,
plus its row metadata. The `trash` table records the item, UTC deletion time,
etymon, and (for a single row) its label/number; `row_metadata.trash_id` links
the retained rows to that entry. There is no automatic purge. Numbers remain
reserved and surviving app entries are not renumbered. Excel exports physically
remove deleted rows and adjust references; references to deleted cells become
`#REF!`, and ranges shrink. Reimporting Excel numbers rows/etymons sequentially,
as with any workbook import.

Recovery is a **local administrator command**, requiring access to the database
file on the server; there is no browser recovery endpoint or administrator login:

```bash
.venv/bin/python trash.py db/research.sqlite3 list
.venv/bin/python trash.py db/research.sqlite3 restore 12  # Use the listed Trash ID.
```

Recovery restores the entire Trash entry with its existing IDs and saved
formatting. It works while the server is running; refresh the browser afterward.
If a row was deleted separately before deleting its etymon, restore the etymon
first, then the row's separate entry. Restored entries are marked with a UTC
recovery time and omitted from the pending Trash list. Editors opened before
deletion/recovery must reload before saving. On startup, older databases migrate
automatically to schema 3 without reimporting or rewriting their content.
Python callers can use `store.list_trash()` and `store.restore_trash(trash_id)`.

**Workbook layout and import errors**

The importer expects column headings in **row 1**, row labels in **column A**,
and etymon sections starting with a label beginning `ETIMON/`. Blank label cells
inherit the preceding label. It does not detect alternate spreadsheet layouts
or repair them automatically.

| Input | Behavior |
| --- | --- |
| Missing/unreadable file, unsupported Excel format, corrupt archive, or nonexistent sheet | Startup stops with an error; the command exits with status 2. Use `.xlsx` or `.xlsm`, not legacy `.xls`. |
| Data before the first `ETIMON/` marker | Startup stops with the offending row number. |
| Populated data cell without a heading in row 1 | Startup stops with the cell coordinate. |
| Duplicate column headings | Startup stops with the heading and both header-cell coordinates. Names are compared exactly. |
| Empty sheet, or headings/labels without data cells | The app starts with an empty collection. |
| Different labels, additional columns, or missing standard language columns | Accepted. Original names are retained; missing standard columns display empty. Result titles may say “No language form” if no standard language entry is available. |

These are structural checks, not validation of linguistic content. Importing
never saves changes to the source workbook. Direct Python calls to
`excel_to_dataframe`/`create_app` raise exceptions for import errors; the
command-line entry point formats common errors as readable startup messages.

The initial page lists all etymons and displays the first. Search is literal and
case-insensitive and ignores diacritics: `prajitura` matches `Prăjitură`.
`excel_to_dataframe` adds `nodiacritics_plaintext` for searching while retaining
the original HTML and plaintext for display. Column and label checkbox menus
allow multiple selections; no selections means all. A cell must match any
selected column and any selected label, using exact values for both filters.
Search normalization also expands `œ/Œ` to `oe/OE`, `æ/Æ` to `ae/AE`,
`ø/Ø` to `o/O`, `ł/Ł` to `l/L`, and Catalan `l·l` to `ll` (including
uppercase forms and the older `ŀl` spelling).
Selecting an etymon displays its complete table, including cells that did not
match the search. Each browser remembers its search, selected etymon, and
formatted/plaintext preference. Clear returns to the full collection.

Search terms are highlighted throughout the displayed cell content in both
formatted and plain-text views, including the HTML fallback table. Highlighting
uses the same case/diacritic normalization as search and preserves original text,
rich-text formatting, and whitespace. Clear removes the highlights.
Solid Excel background fills are also imported for content cells and cover the
whole displayed cell in both formatted and plain-text views. Search highlighting
is drawn over the fill and keeps its configured color. RGB, indexed, and
theme/tinted fills are supported. Patterned fills, gradients, and conditional
formatting are not rendered. Cells without text remain omitted by the importer.
Label-cell fills also color the displayed label, its number, and empty cells
across that row (including empty language/notes columns). Populated content
cells keep their own fills. An empty cell with its own Excel fill uses that
color; otherwise it uses the label background. Adding text to an empty cell
retains that background during editing and after saving, including on reload.
Blank label cells inherit the preceding explicit
label's fill unless they have a fill of their own; a new uncolored label resets
that inheritance. With no imported label fill, labels, numbers, and empty cells
share the table's neutral label background. Entirely empty rows remain omitted.

New rows use `ROW_BACKGROUND_COLORS` in `config.py`: etymons blue (`#D9E2F3`),
basic senses orange (`#F7CAAC`), semantic extensions yellow (`#FEF2CB`), and
specialized senses green (`#B7E1CD`), sampled from the existing workbook.
The type's color covers the label, number, and every content/empty cell in the
browser and Excel export. The mapping uses the four canonical labels; imported
label spelling and spacing are retained when selecting a type's color.
Values accept `#RGB` or `#RRGGBB`. Restart after changing configuration;
changes apply to future rows. Created rows retain their saved colors in SQLite,
and imported rows keep their original fills.

Set the highlight background in `config.py`, then restart the server:

```python
SEARCH_HIGHLIGHT_COLOR = '#ffff00'  # Standard highlight yellow; #RGB or #RRGGBB.
```

Search controls sit in a compact bar. A side list headed **ETYMONS** shows the
results. Use **«** to hide it and give the table more width, or **»** to show it
again. The choice survives etymon selection and display-mode changes; a new
search reveals the results. On narrow screens, the list opens over the left
side of the table. The table fills the remaining viewport height.
The results list has a persistent, draggable scrollbar on its right whenever
the entries exceed the available height, synchronized with wheel and keyboard
scrolling even after hiding/showing the sidebar.
The current etymon and its smaller previous/next links form a compact group
alongside the table controls. These links follow the current result list and
disappear at either end. Controls wrap on narrow screens.

Searches, etymon selection, Clear, and the formatted/plaintext switch update
the workspace through htmx without reloading the page. Tabulator provides the
interactive table. Use **Table columns** to choose visible columns, drag
column-header edges to resize widths, and drag row borders to resize heights.
Labels and label numbers remain visible while scrolling horizontally.
Persistent, draggable scrollbars sit **above the table** for left/right scrolling
and at its **right edge** for up/down scrolling. They stay visible whenever
content overflows, regardless of the system's overlay-scrollbar setting. Click
a track or drag its thumb; wheel, touch, and keyboard scrolling stay synchronized.
Focused scrollbars also support arrow keys, Page Up/Down, Home, and End.

The browser remembers column widths and visibility for each workbook, and row
heights for each etymon. **Reset layout** clears those display preferences for
the current workbook. These layout controls do not change cell contents.

**Inline cell editing**

The app starts in **Search mode**, where cells are read-only. Click **Edit mode**
in the header to enable editing. Search controls and filters remain available
in both modes, and switching mode retains the current search and selection.
The choice is stored with the browser's session preferences.
Close or cancel an open editor before changing mode. This is a workflow toggle;
every reachable visitor can enable it.

In Edit mode, double-click a language or notes cell, including an empty cell, to open Quill
inside it. Labels, label numbers, and headings remain fixed. The editor always
loads the original formatted content, including in plain-text view, without
search highlights. **Close** (or Ctrl/Cmd+Enter) saves and closes; **Cancel**
(or Escape) discards the draft. Closing without changes preserves the exact
original HTML. Close or cancel before navigating, searching, or changing the
table layout. Refreshing/closing the browser tab discards an unsaved draft.
The editor places the caret at the end of the cell contents, ready for immediate
typing after double-clicking; toolbar/button text is excluded from selection.
Saving, cancelling, and closing without changes retain the table's horizontal
and vertical scroll position.

Saved edits commit to **SQLite**: they survive server restarts, and search,
highlighting, and titles use the committed content on the next request. The
source workbook is never overwritten by the website. Run one application
process for now; the signed editor-token handling is scoped to that process.

The toolbar supports bold, italics, underline, strikethrough, sub/superscript,
text colors, and text highlights. Imported font families/sizes are retained
where supported by Quill; saving an edited cell converts that cell's formatting
to Quill's supported formats (for example, double underline becomes underline).
Workbook cell and label background fills remain separate and unchanged.
There are no images, links, or embedded HTML in edited content. The server
validates text/format operations and creates escaped HTML itself.
The cell editor disables browser spellchecking, autocomplete, autocorrection,
automatic capitalization, and writing suggestions for multilingual entries.

Quill uses the cell's line height when it opens. **Typography** reveals a
font-size input (points) and a line-spacing menu. Select text, enter a size,
then click **Apply size** (or press Enter in the size input); with only a cursor,
the size applies to subsequent typing. Line spacing applies to the **entire
cell**, independently of the text selection, and previews immediately. **Close**
saves both text and typography; **Cancel** discards both. Merely opening the
Typography menu does not change the cell. Saved line spacing carries through
formatted/plain-text views, the HTML fallback, and reopening the editor.

**Adding rows and etymons**

In Edit mode, click **Add row** to open its dropdown and choose a row type for
the selected etymon. Only the three non-etymon categories are offered: basic senses, semantic
extensions, and specialized senses. Existing label spelling/spacing is reused.
The new label number is one greater than the largest number for that label in
that etymon. Existing entries keep their numbers.

**Add etymon** in the header creates the next etymon number across the whole
collection, with an etymon row numbered 1. Both commands open a dialog requiring
initial **French text**. **Create** commits the new entry to SQLite; **Cancel**
or Escape discards the dialog without creating anything. Initial text can have
multiple lines; use Quill afterward to add rich formatting. The display updates
and scrolls to the new row, bringing the French cell into view and focusing it.
A new etymon becomes selected, with
its title, count, and navigation updated; creating it clears prior search filters.

Initial text is required so new entries survive Excel export/reimport without
hidden placeholders or auxiliary sheets. If all content is subsequently cleared
from a row, SQLite retains it, but the Excel importer still skips empty rows.
Existing databases upgrade automatically to schema version 3 on startup,
retaining data, IDs, and revisions; no workbook reimport is needed.

Simultaneous edits to different cells are accepted. A stale save to a cell
already changed by someone else is rejected and keeps the draft open; copy
the draft before cancelling and reloading. Editor tokens also expire when
the server restarts. There are no user accounts: every reachable visitor can
edit; CSRF protection and conflict checks do not restrict who has access.

The pinned htmx and Tabulator files are bundled under `static/vendor`, including
their licenses, so no CDN connection or frontend build step is required. A
standard HTML table remains available if the interactive grid cannot load.

Result titles use the first line of the etymon entry, before grammatical notes,
preferring French, then Romanian, Italian, Spanish, Portuguese, and Catalan.
The table retains the HTML text formatting produced by `excel_to_dataframe`.

The app uses Flask, Waitress, pandas, and openpyxl >= 3.1 from the virtual environment.
The working environment uses Python 3.13.12. To set up a new environment,
install the direct dependency versions recorded in `requirements.txt`:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Run the checks with:

```bash
.venv/bin/python -m unittest -v
node --check static/app.js
node --check static/cell_editor.js
node --check static/scrollbars.js
node tests/test_scrollbars.js
```

Node is optional for the JavaScript checks; the application itself does
not require Node or npm. Latest verification (2026-11-05): 96 Python tests,
six scrollbar interaction tests, JavaScript syntax checks, and thirteen Chromium
browser-check groups covering inline editing, typography, formatting/whitespace, Cancel,
shared saves/conflicts, search/plaintext, empty-cell fills, scroll preservation,
mode transitions, creating rows/etymons, and Excel downloads. The scrollbar tests
use simulated geometry. Earlier manual loopback checks also verified Waitress
responses, host validation, and header/body limits. The user reports successful
remote deployment of the previous browsing version; these editing changes
have only been tested locally.
The export regression suite also exercises adding rows/etymons to a 1,200-row
worksheet, checking the HTTP download, inherited formatting, and shifted data.

An optional browser regression script starts its own temporary workbook and
loopback server. With Playwright and its Chromium browser installed, run
`node tests/test_cell_editor_browser.js` (set `NODE_PATH` if Playwright is
installed outside this project). It never connects to a deployed server.

**Project files**

| File | Purpose |
| --- | --- |
| `main.py` | Flask app factory, database startup, search sessions, grid payloads, Excel download |
| `lexicon_db.py` | SQLite schema, first import, SQL searches, atomic edits, export snapshots |
| `excel_export.py` | Full timestamped workbook export and explicit existing-sheet overwrite |
| `excel_rows.py` | Excel row insertion, inherited labels, and reference adjustments |
| `cell_editing.py` | Validates Quill text operations and renders safe formatted HTML |
| `config.py` | Highlight color, allowed hosts, secure cookies, and request limits |
| `HANDOFF.md` | Continuation prompt, current state, contracts, verification, and future work |
| `DEPLOYMENT.md` | Local/public startup, HTTPS proxy, permissions, and deployment limits |
| `search_highlighting.py` | Normalized match ranges and formatting-preserving highlights |
| `extract_sheet.py` | Worksheet extraction, dictionary find/replace, Excel-to-DataFrame conversion |
| `df_search.py` | DataFrame search, etymon table reconstruction, label/column ordering |
| `text_normalization.py` | Shared accent removal and Latin-letter expansion |
| `templates/index.html` | Full page and search form |
| `templates/_workspace.html` | htmx fragment, results list, grid data and fallback table |
| `static/app.js` | Tabulator lifecycle, display preferences, htmx integration |
| `static/cell_editor.js` | Inline Quill lifecycle, Close/Cancel, and draft handling |
| `static/scrollbars.js` | Persistent top/right scroll controls and native-scroll synchronization |
| `static/style.css` | Page, fallback table, and grid styling |
| `static/vendor/` | htmx 2.0.8, Tabulator 6.3.1, Quill 2.0.3, licenses and source references |
| `to_replace.py` | User-maintained label-cleanup dictionary; not applied automatically |
| `tests/` | Python unittest coverage and dependency-free Node scrollbar tests |

**Python usage**

```python
from extract_sheet import excel_to_dataframe, extract_sheet, find_replace_excel
from df_search import search_dataframe, get_etimon

df = excel_to_dataframe('db/example.xlsx', sheet_name='Sheet1')
numbers = search_dataframe(
    df, 'prajitura', column=['LIMBA ROMÂNĂ', 'LIMBA FRANCEZĂ'],
    label=['SENSURI DE BAZĂ', 'SENSURI SPECIALIZATE'], case_sensitive=False,
)
table_html = get_etimon(df, 2)
table_plain = get_etimon(df, 2, plaintext=True)

# Optional preprocessing utilities; these save workbooks.
extract_sheet('db/orig.xlsx', 'Sheet1', 'db/sheet.xlsx')
find_replace_excel(
    'db/sheet.xlsx', {'old text': 'new text'},
    cell_range='A1:A1048576', output_file='db/replaced.xlsx',
)
```

`search_dataframe` ignores diacritics and letter variants, but defaults to
**case-sensitive** matching. The website explicitly passes
`case_sensitive=False`. Its `column` and `label` arguments each accept a single
string or an iterable of strings; `None` or an empty iterable means all values.
`get_etimon` returns a wide DataFrame with label and
label number first, one column per language/notes field, and empty strings for
missing cells. It defaults to HTML values.

`excel_to_dataframe` returns these columns, in order:

| Column | Meaning |
| --- | --- |
| `etimon_number` | 1-based subtable number in the worksheet |
| `column` | Original language or notes column heading |
| `label` | Original row label, inherited when the label cell is blank |
| `label_number` | 1-based data-row number within that exact label and etymon |
| `content` | HTML preserving text formatting, solid background fill, and original whitespace |
| `plaintext_content` | Plain text with outer whitespace trimmed |
| `nodiacritics_plaintext` | Derived search text with accents removed and letter variants expanded |
| `background_color` | Solid cell fill as a CSS hex color; empty string for absent or unsupported fills |

Row-label fills are metadata in `df.attrs['label_backgrounds']`, keyed by
`(etimon_number, label, label_number)`. They do not add data records or change
searchable text or row numbering.

Detached database snapshots from `store.to_dataframe()` expose saved spacing
in `df.attrs['cell_line_heights']`, keyed by
`(etimon_number, label, label_number, column)`. SQLite stores it on the cell
record, and formatted HTML includes it too. Snapshot mutations do not save edits.

Quill and new rows/etymons save to SQLite. Editing attribution/locks and shared
password access remain future work.
