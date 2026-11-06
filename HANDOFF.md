# XLDB development handoff

Updated 2026-11-05 for recoverable deletion, Search/Edit modes, adding rows/etymons, and structural
Excel export, following SQLite and cell editing improvements.
Workspace: `/home/hartular/Lingv/XLDB`. User-facing name: **Parallel Words**.

**Copy into the next chat**

> Continue the XLDB project in `/home/hartular/Lingv/XLDB`. Read `README.md`
> and `HANDOFF.md` first; also read `DEPLOYMENT.md` before deployment work.
> The app is branded Parallel Words and uses Flask + htmx + Tabulator, with
> Waitress for local/public serving. It imports one Excel sheet when initializing SQLite,
> supports multiple column/label filters and case/diacritic-insensitive search,
> and displays resizable tables with persistent scrollbars, a collapsible
> ETYMONS list, previous/next navigation, and configurable search highlighting.
> Excel background fills cover content cells, labels, label numbers, and empty
> cells using the documented inheritance rules; highlighting stays above fills.
> Preserve original workbook text, formatting, and label spelling/spacing.
> CLI options select the workbook, sheet, local/public/specific interface, port,
> trusted hosts/proxy, and secure cookies. The user reports remote deployment works.
> The header's Edit mode toggle enables Quill and creation controls; Search
> mode is read-only. Search controls and filters remain available in both modes,
> with the current search retained when switching. Double-clicking a
> content cell in Edit mode opens Quill inline; Close saves to SQLite,
> Cancel/Escape discards. Saved edits survive restart; startup reopens
> the database without reimporting Excel. Export Excel writes/downloads a new
> timestamped full workbook with only the selected sheet updated. The source
> stays untouched. This stage assumes one local user. Authentication, edit
> tracking/locks remain future work. Add row offers the three non-etymon labels;
> Add etymon assigns the next number. Both require initial French text in a
> Create/Cancel dialog, prefilled with `[To be added]` and selected for easy
> replacement. The default may be saved unchanged.
> New entries export inside the proper Excel group and survive reimport.
> New rows use the four type defaults in `config.py` (`ROW_BACKGROUND_COLORS`),
> saved in SQLite and used throughout the browser and Excel export. Imported
> colors and exact label spelling/spacing remain intact.
> Edit mode also offers Delete row (except etymon markers) and Delete etymon,
> with a strong dialog requiring DELETE. Items are soft-deleted into Trash;
> local administrators recover them with `trash.py DATABASE list` or
> `trash.py DATABASE restore ID`. No web recovery/admin login is exposed.
> Future edit access is
> intended to use a shared password and self-declared editor names.
> Inspect the current Git state and preserve existing changes. No implementation
> request is pending; I will provide the next task.

**Current state and continuation**

- Creation-dialog update (2026-11-06): Add row/Add etymon prefill the French
  textarea with `[To be added]` on every opening and select it for replacement.
  Create may save the default unchanged; Cancel still creates nothing.
  Verified in a targeted Chromium check, including replacement, reopening,
  and saving the literal default for both types; JS syntax checks pass.
- The latest existing commit is `7bf0fd5` (`Switch to sqlite, implemented add etymon/row.`).
  Deletion/recovery work is uncommitted. Check `git status` when resuming; this work does not
  commit, push, or deploy anything.
- Latest behavior: Search mode is read-only; Edit mode enables Quill, Add row,
  and Add etymon. Each browser session remembers the mode. Quill opens inside
  a double-clicked content cell in Edit mode. Close or
  Ctrl/Cmd+Enter saves; Cancel or Escape discards. Changes update the running
  SQLite database. No-op closes preserve exact original HTML. Labels/numbers
  remain fixed. Imported backgrounds and all search/layout behavior remain.
- Cell editors disable browser spellchecking, autocomplete, autocorrection,
  automatic capitalization, and writing suggestions on Quill's editable root,
  so English assistance does not interfere with multilingual entries.
- Typography: Quill starts with the cell's line height. A Typography toggle
  reveals a font-size input (pt, Apply size/Enter) and whole-cell line-spacing
  select. Text selection survives menu focus; font size affects the selection
  or subsequent typing. Spacing affects every line, not individual paragraphs.
  Spacing-only changes count as edits; menu-only/no-op closes preserve HTML.
- The user deployed the previous browsing version successfully and verified
  regular/incognito session separation. Editing changes have not been deployed
  remotely by this project work.
- `README.md` describes operation and import contracts; this file records
  development details; `DEPLOYMENT.md` contains remote deployment examples and
  limitations. Maintain all affected documents when behavior changes.
- Preserve source Excel files and label spelling/spacing. The latest task
  replaces in-memory updates with SQLite and timestamped full-workbook exports.
  The explicit `overwrite_sheet` Python helper is tested on temporary files;
  the website never overwrites an existing workbook. Password access,
  attribution/locks/history, uploads, and accounts are absent.

**SQLite and export workflow**

`lexicon_db.py` owns persistence. `cells` keeps the original eight data fields
plus integer `id`, `revision`, and `line_height`. `row_metadata` retains logical
row keys, original sheet row positions, and label backgrounds; `sheet_columns`
retains headings and Excel column positions; `dataset` stores UUID identity,
source labels, schema version 3, and the complete original workbook bytes.
Excel import adds `row_positions` and `column_positions` to DataFrame attrs.

Default database: `<workbook filename>[.<sheet-name hash>].sqlite3` beside the
workbook. `--database PATH` selects an explicit file. Existing initialized
databases win over Excel, even if the source was moved/deleted. Restart never
reimports or overwrites saved edits; choose a new database path for another
import. `create_app(..., database_path=...)` supports Python callers. TESTING
apps use isolated `:memory:` databases unless a path is explicitly provided.

`app.extensions['lexicon_store']` exposes the store; `lexicon_df` is removed.
SQL performs searches, filter choices, title lookup, cell lookup, and writes.
Case-insensitive literal search uses `instr(search_fold(nodiacritics_plaintext),
normalized_query)` with Python uppercase semantics; SQL LIKE wildcards are
not introduced. Only the selected etymon's rows become a detached DataFrame
for the existing `get_etimon` pivot. `to_dataframe()` is an explicit snapshot,
not a writable live database. The old process-local search cache is removed.

`excel_export.py` reads an atomic DB snapshot. `workbook_bytes` starts from
the saved workbook archive and patches only changed cells in the original
worksheet XML. Other ZIP members, macros, drawings, formulas, formatting,
blank label cells, and extra sheets stay intact. No-op export returns the
original workbook bytes exactly. Edited cells use inline rich text, so leading
`=` remains text. New content in a missing standard language gets a heading.
CSS line spacing and per-run background highlights have no exact Excel mapping;
row heights provide room, while SQLite preserves the original app settings.

GET `/export` and the header's Export Excel link create/download a full workbook
in `exports/` beside the DB, with Europe/Bucharest date/time, microseconds, and
offset in the filename. `--export-dir` overrides the directory. CLI `--export`
writes a new workbook and exits without serving. Names never overwrite files;
temporary files and atomic links/replacement avoid partial final output.
`overwrite_sheet(store, path, sheet_name=...)` is a separate opt-in helper for
an existing workbook/sheet. It uses openpyxl-supported features and preserves
other sheets' data; advanced unsupported workbook features may be affected.
The normal export uses archive patching instead. No source workbook was changed.

Current verification: 111 Python tests, six Node scrollbar tests, JS syntax
checks, and sixteen Chromium browser groups after the edit-workflow
corrections. Tests cover restart without the
source, stable IDs/revisions, SQL search, rich-text exports, archive preservation,
timestamp collisions, adding/clearing cells, explicit sheet overwrite, CLI
export without serving, and the browser download. Runtime needs no new dependency;
SQLite is part of Python. No remote SQLite deployment was performed.

**Rich-text export corrections (2026-11-05)**

The user reported new text adopting the original Excel cell's color and Excel
repairing string properties in `sheet1.xml`. Saved HTML explicitly formats the
imported runs, but new unformatted text inherits the web editor's defaults.
The exporter incorrectly used the original Excel font as its default for all
runs. `excel_export.py` now uses the grid/editor default (9 pt Segoe UI,
`#253b35`) and writes explicit normal bold/italic/strike/underline/script states,
so missing styles do not accidentally inherit the original cell's formatting.

openpyxl's run serializer omits `xml:space="preserve"` for whitespace-only text,
including standalone newlines. Export now sets it on every text run, addressing
a possible source of Excel's repair warning without changing stored edits.
The user subsequently confirmed fresh exports work. The exact XML repair was
not compared against an Excel-repaired copy. The normal ZIP
patch still changes only the selected worksheet. No shared-string table rewrite
or wholesale workbook conversion was introduced.

`tests/test_excel_export.py` adds three regressions for mixed colors/defaults,
explicit style resets, whitespace-only runs, and clearing cells without empty
rich-text runs. All 84 Python tests passed in a temporary checkout copy using
the committed `db/example.xlsx` fixture: the user has renamed/deleted that
workspace fixture, which was left untouched. A corrected export from a read-only
snapshot of `db/research.sqlite3` retained the original red text and the new
default-colored text through a local LibreOffice open/save. Only temporary
files under `/tmp/xldb-export-check` were used; source workbooks, saved edits,
and previous exports were not modified. The user subsequently confirmed the
export now works in Excel.

**Empty-cell backgrounds and editor scrolling (2026-11-05)**

An empty cell previously inherited the row label's background in the browser,
then became unfilled after saving text because its SQLite record had no fill.
`LexiconDB._original_empty_backgrounds()` now recovers the original blank-cell
positions/fills from the workbook snapshot already stored in SQLite, once per
store. It includes missing standard columns and falls back to label fills.
Detached DataFrame attrs carry a copy as `empty_cell_backgrounds`; the page
uses these fills for formerly empty cells even after they gain content. Blank
cells' own Excel fills take precedence. Neutral label backgrounds stay neutral
after adding text. Existing databases and edits work without schema migration
or source workbook access. Stored cell text and Excel export remain unchanged.
The editor panel also takes its cell's computed background when opening.

`cell_editor.js` calls `onBeforeClose` before removing the expanded editor.
`app.js` captures both table scroll offsets there, restores them after row
height normalization, and carries them through the saved-edit htmx refresh,
restoring them after data replacement/redraw. Cancel and no-op Close preserve
position too. Refresh snapshots are consumed once and only for the same
etymon; ordinary etymon navigation keeps its existing scroll reset behavior.

New coverage checks formerly empty colored and neutral cells, reopening an
existing database without its source workbook, editor backgrounds, and a
large table scrolled in both directions through Save, Cancel, and no-op Close.
The full Python/browser suites run in a temporary project copy with the
committed example fixture, preserving the user's workspace workbook changes.

**Search/Edit modes and creating entries (2026-11-05)**

`session['edit_mode']` defaults to false. POST `/mode` accepts a boolean and
requires the existing CSRF header. Search mode disables opening Quill and the
server rejects POST `/cell`, `/rows`, and `/etymons` with 403 unless that session
is in Edit mode. This is a workflow boundary, not access control: anyone can
enable Edit mode. Search criteria are active in both modes; switching mode
retains them. Creating an etymon clears saved search criteria.

The user initially proposed empty French placeholders, then offered to require
initial text. The accepted implementation uses a native dialog with a required
French textarea, Create, and Cancel. No DB row/number is allocated until a valid
submission. The server also rejects whitespace-only text. Initial text is escaped
through the existing Delta renderer; rich formatting is available in Quill afterward.
No hidden workbook metadata, auxiliary worksheet, or importer changes were needed.
Completely clearing a row afterward still leaves it in SQLite, while the importer
retains its prior rule of skipping completely empty Excel rows.

`LexiconDB.add_row` validates one of three non-etymon categories, reuses label
spelling/spacing through accent/whitespace-insensitive category lookup, and
assigns max(label_number)+1 within that exact label/etymon. Missing categories
use the canonical label. `add_etymon` assigns max(etimon_number)+1 and creates
its marker row numbered 1. Both insert the submitted French text, revision 1,
in a BEGIN IMMEDIATE transaction. Row and cell IDs remain stable. New rows
follow their category; new etymons follow the existing collection.

Schema version 2 adds `source_row` and `style_row` to `row_metadata`. Version 1
databases migrate transactionally on startup without reading source files or
changing content/revisions/IDs. `sheet_row` is the current export position;
`source_row` retains the original template coordinate, null for additions.
`style_row` points to a matching original donor row for new entries. Row positions
shift in descending order to satisfy uniqueness. Original blank-cell formatting
uses source coordinates after shifts, and background caches notice rows created
by another connection.

`excel_rows.py` inserts new worksheet rows into the original archive before
`excel_export.py` applies cell edits. It copies donor row/cell styles without
copying values/formulas, writes actual labels, shifts A1 references in formulas
(including other sheets), named ranges, validations, merges, and layout, and
adjusts owned table/drawing/comment coordinates. A matching inherited label is
made explicit only when an inserted category would otherwise relabel following
data. Ordinary cell-only exports keep the existing single-worksheet patch path.
Unrelated ZIP members are retained; affected reference parts may change during
row insertion. No source workbook is overwritten.

The browser refreshes the workspace, updates the header count, selects a new
etymon, reveals the French column when needed, and focuses the new French cell.
The current implementation uses native viewport coordinates to reveal the cell;
pinned Tabulator 6.3.1's `Table.scrollToColumn` leaves its outer Promise pending,
and renderer centering was unreliable for the basic renderer. Opening
creation dialogs/mode changes is blocked during an active cell edit; focus
returns to Quill. Cancel/Escape in the creation dialog leaves SQLite unchanged.

`tests/test_creation.py` covers migration, browser-local modes and server-side
mutation enforcement, required text, atomic numbering/concurrent connections,
restart without the source, label spelling, inserted row positions/styles,
inherited labels, and export/reimport including formulas on other sheets.
Tests still use a temporary project copy and the committed example fixture
because the user's workspace example file was renamed/deleted; those workbook
changes and the production SQLite database were left untouched.
The complete twelve-group Chromium run passed, including read-only Search
mode, mode transitions, required-text/Cancel behavior, both creation commands,
French-cell focus, and all previous editor/scroll/export regressions. A temporary
workbook with inserted rows and a new etymon also passed a local LibreOffice
open/save and reimport check. Actual Microsoft Excel verification of structural
insertion remains for the user's environment.

**Export recursion correction (2026-11-05)**

The user encountered RecursionError exporting after adding rows. This was
reproduced from a read-only snapshot of `db/research.sqlite3`: `deepcopy(row)`
in `excel_rows.py` followed DOM parent/sibling/document links through the
worksheet instead of copying only the row subtree. The prior small fixture
did not expose the failure. Donor rows now use `cloneNode(deep=True)` and only
the actual `style_row` donors are cloned. No recursion-limit changes or DB
changes are needed.

The new regression in `tests/test_creation.py` exports through GET `/export`
after adding a row and an etymon to a 1,200-row worksheet, verifying original
data, inserted data, copied fills/heights, an unrelated sheet, and source-file
preservation. All 95 Python tests pass. A read-only snapshot of the user's DB
also exported successfully: four added rows retained and all ten edited cells
matched their saved text. The corrected temporary copy is
`/tmp/xldb-fixed-row-export.xlsx`; the user's DB, source files, and old exports
were not modified. Restart the running server to load the fix, then export again.
Previous browser/scrollbar checks remain the latest frontend verification;
this correction changes only Python XML cloning.

**Edit workflow, focus, and new-cell borders (2026-11-05)**

Search controls remain visible and functional in Edit mode. `main.py` applies
the same query/label/column criteria in both modes. The mode only gates cell
editing and creation; toggling it keeps the current filters. Add row is now a
native details/summary dropdown with three category buttons. Each button carries
the exact existing label spelling in `data-row-label` and opens the French-text
dialog. The summary has an explicit button role and accessible name; Escape and
outside clicks use the existing details handling.

After creation, `app.js` waits for layout and adjusts only the table viewport
using row/cell bounding rectangles, accounting for frozen columns, then focuses
the French cell without scrolling the page. This replaces the basic renderer's
unreliable center-scroll calculation. The browser fixture includes fifty existing
basic-sense rows and checks that the 51st new row is actually visible with a
nonzero scroll offset, rather than checking focus alone.

The double-click handler prevents native default selection. `cell_editor.js`
clears an outside browser selection, sets a collapsed Quill caret at the end,
and focuses the editor with preventScroll. A following animation frame repairs
any native double-click focus/selection override, guarded against a closed
editor. Toolbar/action text is not selectable. Browser tests type through the
keyboard immediately after double-clicking populated and empty cells, without
using fill() or clicking the editable region to repair focus.

The user's source formatting had borderless cells and cells missing their top
edge. Copying those formats into independent new rows left visible gaps.
`excel_rows.py` now completes new cells' left/right/top/bottom edges, preserving
existing edge styles/colors and borrowing missing edges from compatible source
borders, with thin automatic-color edges as fallback. It appends border/cell-XF
definitions to `xl/styles.xml`, leaving existing style indices and cells intact.
It creates styled blank cells for all known columns in each new row. A read-only
export of the user's current database confirmed every added cell has four edges.

Verification: all 96 Python tests and thirteen Chromium groups pass, including
Edit-mode text/column searches, immediate typing, the dropdown and creation,
visible-row scrolling, complete new borders, unchanged original borders, and
the earlier editor/export regressions. The source workbooks and research DB
remain unchanged; tests use the temporary checkout with the original fixture.

**Default backgrounds for created rows (2026-11-05)**

The last matching donor row sometimes had an atypical fill (yellow for a basic
sense). `config.py` now defines `ROW_BACKGROUND_COLORS` using the workbook's
usual type colors: etymon `#D9E2F3`, basic sense `#F7CAAC`, extension `#FEF2CB`,
and specialized sense `#B7E1CD`. All four canonical labels and valid hex colors
are required at startup; `#RGB` expands to uppercase `#RRGGBB`. The store matches
actual labels by its existing accent/whitespace-insensitive type key, retaining
their original text. Flask passes its config to `LexiconDB`; standalone stores
default to the same setting and accept an optional `row_colors` mapping.

Creation persists the default in `row_metadata.background_color` and the initial
French cell; later edits into blank cells of created rows retain that color.
Browser presentation uses the saved row color across labels, numbers, populated
and empty cells, including Quill. Export appends solid fills and cell-XF styles
for added rows, retaining donor fonts/heights/borders and completing outlines.
Imported rows/cells and source files keep their own fills. Changing configuration
and restarting affects future rows, without rewriting saved row colors. No schema
migration is needed. Existing app-created rows keep their saved row background;
this change does not recolor a previously yellow row orange in the database.

Verification: 99 Python tests, six Node scrollbar checks, JS syntax checks,
and fourteen Chromium groups. Regressions cover missing donor types, all four
defaults, exact imported label spellings, configuration overrides, invalid settings,
editing/restarting/exporting with persisted colors, and a new orange basic-sense
row inside a newly created etymon. Tests use temporary workbooks and databases;
the user's workbooks and research database remain untouched.

**Recoverable deletion (2026-11-05)**

Edit mode shows Delete row beneath non-marker labels and Delete etymon in the
toolbar. A modal names the target, warns that all languages (and all rows for an
etymon) are affected, requires exact `DELETE`, and defaults focus to Cancel.
Escape cancels. Open Quill editors block deletion. After deletion, the workspace
refreshes navigation/counts/results; row deletion retains table scroll offsets.

Schema 3 adds `trash` (kind, etymon, optional row label/number, title, UTC deletion
and recovery timestamps) and `row_metadata.trash_id`/`generation`. Migrations from
versions 1/2 are transactional and preserve cells/template. Soft deletion keeps
all original row/cell records, IDs, rich text, spacing, colors, revisions, and
source/style coordinates. Active queries exclude rows with a Trash link.
Creation counts trashed rows when reserving numbers/positions, so restoration
does not collide or reverse the order of later added rows. No purge is provided.

POST `/trash` requires Edit mode, session CSRF, exact confirmation, and a signed
target/fingerprint token from the current page. Fingerprints cover row identity,
generation, cell IDs/revisions, and (for an etymon) all active rows. Changes after
page load abort deletion instead of discarding unseen edits. Cell edit tokens
now also include the row generation; deletion and recovery increment it without
changing cell revisions, so stale editors cannot resurrect/overwrite restored
data and no-op restored originals still export byte-for-byte.

`LexiconDB.list_trash()`/`restore_trash(id)` support local recovery; `trash.py`
provides `DATABASE list` and `DATABASE restore ID`. No recovery HTTP endpoint or
admin login is introduced. Recovery can run alongside Waitress under SQLite's
write lock; refresh the browser afterward. Independently trashed rows retain
separate entries when their etymon is later deleted; recover the etymon first.
The presentation cache tracks active row identities/positions, including changes
committed by another connection.

Export first reconstructs the full row layout, patches active edits, then
physically removes trashed rows/etymon sections (including label-only/blank rows
in deleted etymons) from XML. `RowRemoval` shrinks ranges, produces `#REF!` for
deleted direct references, and adjusts formulas/layout/owned parts using the
existing structural exporter. Newly exposed inherited labels become explicit
with their saved fills. Unrelated workbook parts remain intact. App numbers
remain stable; Excel reimport numbers sequentially as usual.

Tests use temporary copies/workbooks/databases; the user's source workbooks and
research database have not been changed. Coverage includes exact recovery after
restart, v1/v2 migrations, separate row/etymon restoration, complete-collection
deletion, reserved numbering/order, stale editors/confirmations, CLI recovery,
original/added row removal, label inheritance/fills, references/merges/validations,
and confirmation/cancellation/recovery/Excel download in Chromium.

**Run and verification**

```bash
cd /home/hartular/Lingv/XLDB
.venv/bin/python main.py
.venv/bin/python main.py "db/my workbook.xlsx" --sheet "Sheet 2"
# Open http://127.0.0.1:5000
# Optional: choose a different local port, or expose all IPv4 interfaces.
.venv/bin/python main.py --local --port 8080
.venv/bin/python main.py "db/my workbook.xlsx" --public --port 8080

.venv/bin/python -m unittest -v
node --check static/app.js
node --check static/cell_editor.js
node --check static/scrollbars.js
node tests/test_scrollbars.js
```

- Existing environment: Python 3.13.12, Flask 3.1.3, pandas 3.1.0,
  openpyxl 3.1.5, Waitress 3.0.2. Direct dependencies are recorded in `requirements.txt`.
- Latest verification: 111 Python tests, six Node scrollbar interaction tests,
  and JavaScript syntax checks. Sixteen real Chromium check groups exercise inline
  editing under the app's CSP, rich text/whitespace, no-op/Cancel, shared saves,
  conflicts, search/plaintext, empty-cell fill/clear, selected font size,
  inherited line height, whole-cell spacing/save/reopen/Cancel, creation/default
  colors, scroll retention, confirmed deletion, local recovery, and full-workbook
  Excel downloads. Scrollbar tests use
  simulated geometry. No remote editing deployment has been tested here.
- Manual Waitress smoke checks bound only `127.0.0.1` on an ephemeral port:
  full page and htmx search returned 200; an unapproved Host returned 400;
  `/db/example.xlsx` returned 404; oversized headers/body returned 431/413.
  A forged forwarding header did not enable HTTPS behavior. This was an ad hoc
  check, not a committed socket-based test.
- `tests/__init__.py` preserves discovery with `python -m unittest -v` from
  the project root. Workbook fixture paths are relative to that root.
- The user removed/renamed `db/example.xlsx` in their working tree. The latest
  tests ran in `/tmp/xldb-creation-tests-u62wko89`, with the original committed
  example restored only in that temporary checkout. Do not restore/replace the
  user's workbooks or run the import-based `main` tests against a live database.
- Optional `tests/test_cell_editor_browser.js` uses Playwright + Chromium and
  creates an isolated temporary workbook and ephemeral loopback Waitress server.
  Node 18 testing used Playwright 1.51.1 installed only under `/tmp/xldb-browser`,
  with browsers under `/tmp/xldb-browser/browsers`; no runtime npm dependency
  was added. Run with `NODE_PATH=/tmp/xldb-browser/node_modules
  PLAYWRIGHT_BROWSERS_PATH=/tmp/xldb-browser/browsers node tests/test_cell_editor_browser.js`
  while that temporary installation exists. The test retains the real CSP.
- No Node build or CDN is required at runtime. Vendor versions and licenses
  live in `static/vendor/README.md` and adjacent files.

**Domain and import contract**

The workbook contains a header row, label cells in column A, and several
etymon subtables. A label beginning with `ETIMON/` starts a new subtable; the
rest of that label is not used for detection, so the user's occasional
`CCORESPONDENTE` spelling still works. Blank label cells inherit the preceding
label. The import preserves original label and column wording, including
whitespace. The user explicitly wants to handle label cleanup themselves.

`excel_to_dataframe(excel_path, sheet_name=None)` defaults to the first
worksheet. It emits one record per nonempty data cell, including etymon rows,
observations, and conclusions. Whitespace-only cells are skipped. Entirely
empty data rows do not increment numbering. Labels without any data can
establish the category for following rows. Numbering is shared across
languages on a worksheet row, rather than counted independently per column.
Duplicate nonempty column headings are rejected with both header-cell
coordinates, comparing the original names exactly. Missing headings for data
and data before an etymon marker are also rejected. Empty/header-only sheets
are accepted as empty collections; unfamiliar labels/columns are accepted.
There is no general layout detection or linguistic-content validation.

Eight DataFrame columns (background_color is appended to the original seven):

```text
etimon_number, column, label, label_number,
content, plaintext_content, nodiacritics_plaintext, background_color
```

`content` is escaped HTML with inline CSS for cell and rich-text-run fonts,
colors, bold, italics, size, underline, strike, and sub/superscript. It
preserves whitespace via `white-space: pre-wrap`. Static solid fills are included
as inline `background-color` and in `background_color` as CSS hex strings (`''`
when no supported fill is present). RGB, indexed, and theme/tint colors reuse
the font color resolver. Patterned/gradient fills, conditional formatting,
borders, and worksheet layout are not rendered. Formatting-only blank cells
remain omitted. `plaintext_content` trims only the outer
whitespace. Formulas are retained as expressions, not evaluated.
`df.attrs['label_backgrounds']` maps `(etimon_number, label, label_number)` to
effective label fills for observed data rows. Blank label cells inherit the
last explicit label's fill unless their own cell has a supported fill. A new
explicit label resets the inherited color, including when uncolored. Label-only
rows can establish the inherited fill without consuming a label number.

The current `db/example.xlsx` has 221 records and four etymons. Its labels
have been cleaned since the original conversation. Cell C8 is the reference
example: etymon 2, `LIMBA ROMÂNĂ`, `SENSURI DE BAZĂ`, label number 2,
`Prăjitură cu cremă, cu înghețată și cu frișcă (DEX, DCR3)`.

**Search and table contracts**

`search_dataframe(df, text, column=None, label=None, *, case_sensitive=True)`
returns unique etymon numbers sorted ascending. Search is a literal substring
search. Each of `column` and `label` accepts a single string or an iterable of
strings. `None` or an empty iterable means all values. Filters match any exact
value within each selection, with both filters applied to the same cell.
Both query and searchable content undergo the shared normalization.

- The website explicitly uses `case_sensitive=False`; the standalone function
  defaults to case-sensitive matching.
- `nodiacritics_plaintext` is computed at import. Older DataFrames without it
  are supported by deriving normalized values on demand without mutating df.
- Normalization uses Unicode NFD, removes nonspacing combining marks, then
  recomposes with NFC. It handles composed/decomposed accents and Romanian
  comma-below/cedilla variants.
- Explicit expansions: `œ/Œ → oe/OE`, `æ/Æ → ae/AE`, `ø/Ø → o/O`,
  `ł/Ł → l/L`, Catalan `l·l → ll` with case retained, and older `ŀl/ĿL`.
  Middle dots elsewhere remain. This is not a general transliteration of
  every writing system.
- Normalized text is for search; displayed HTML/plaintext retain the originals.
  The actual column name is `nodiacritics_plaintext`, although the user once
  referred to it informally as `nodiacritics_content`.

`get_etimon(df, etimon_number, plaintext=False)` reconstructs a wide
DataFrame. Its first columns are `label` and `label_number`; remaining
columns follow this order:

```text
LIMBA FRANCEZĂ
LIMBA ROMÂNĂ
LIMBA ITALIANĂ
LIMBA SPANIOLĂ
LIMBA PORTUGHEZĂ
LIMBA CATALANĂ
OBSERVAȚII
CONCLUZII
```

All standard columns appear even if empty. Additional columns for that
etymon follow alphabetically. Label priority is exactly:

```text
ETIMON/ CORESPONDENTE ROMANICE
SENSURI DE BAZĂ
EXTENSII SEMANTICE (METAFORIZĂRI,  METONIMII)
SENSURI SPECIALIZATE
```

The extensions label has **two spaces** after the comma. Other labels follow
alphabetically; within each label, rows sort by ascending `label_number`.
Only observed label/number combinations appear. Missing cells are `""`.
Duplicate label/number/column combinations raise ValueError. No etymon gives
an empty table with the standard columns. Default values are HTML; the
`plaintext=True` flag selects original plaintext, never normalized search text.

**Application and frontend architecture**

- `main.py` has `create_app(excel_path=DEFAULT_EXCEL_PATH, sheet_name=None,
  test_config=None, database_path=None)`. Importing exposes `app = create_app()`
  and opens/initializes the default SQLite database. Default first-import source
  is `db/example.xlsx`, relative to `main.py`. The store is exposed as
  `app.extensions['lexicon_store']`.
- Direct script execution calls `main(argv=None)`: an optional positional file
  and `--sheet/-s NAME` are parsed before creating the app. Only the selected
  workbook is loaded; `--help` loads none. Omitted arguments retain the example
  and the first worksheet. Explicit relative paths resolve from the shell's
  current directory. Common file/format/sheet/layout errors print an argparse
  startup error and exit 2 without starting Flask; factory calls still raise.
- The workbook is read only for initial DB creation. All saved edits persist;
  SQL searches read current data without a process-local match cache.
  Signed Flask sessions hold each browser's criteria, selection, and plaintext
  mode, not the full match list.
  `FLASK_SECRET_KEY` is optional; otherwise a fresh key is generated on startup.
- GET `/` accepts `search=1&q=...&column=...&label=...`, with repeated `column`
  and `label` parameters for multiple selections, `etimon=N`,
  `plaintext=0|1`, or `reset=1`. New searches select the first match. A selection
  outside current matches falls back to the first match. Empty results are
  handled without showing a stale etymon. Clear retains the display mode.
- Search filters use checkbox dropdowns; no checked values means all. An
  **All columns/labels** button clears that filter's checkboxes. Criteria store
  sorted, deduplicated lists in the session and grid payload; older sessions
  containing single strings are migrated on read. SQL filters use bound values.
  The frontend restores checkboxes and selection counts after htmx updates.
- Result titles use the first nonempty etymon entry in French, then Romanian,
  Italian, Spanish, Portuguese, Catalan. The first line is shortened before
  a comma or multiple spaces to omit grammatical notes. This is a heuristic.
- Normal requests render `templates/index.html`. `HX-Request: true` returns
  `templates/_workspace.html`. Responses set `Vary: HX-Request` and `no-store`.
- htmx swaps `#workspace`; the search form remains outside it. Inherited
  request synchronization replaces obsolete requests. Selection and display
  controls also use htmx. There is no custom browser-history integration.
- The page is a viewport-height flex layout with a compact header/search bar.
  Its header brand is **Parallel Words**, followed by `<filename> · <sheet name>`.
  The importer records the actual selected title in `df.attrs['sheet_name']`,
  including the default first sheet; displaying it does not reread the workbook.
  The workspace toolbar contains the selected title, display mode,
  **Table columns**, and Reset layout. A sidebar headed **ETYMONS** (bold) shows
  results as a list. Its **«/»** control collapses it into a narrow side strip or
  expands it. JavaScript keeps the choice through htmx navigation in memory;
  new searches reveal the list via `data-reveal-results`. On narrow screens the
  expanded sidebar overlays the left part of the table. Without JavaScript,
  the list remains visible beside the fallback table. Controls wrap on small screens;
  filter menus stay within the search panel's width. Outside clicks and Escape
  close dropdowns. No decorative title area or footer takes up table space.
  The selected etymon and smaller previous/next links form a compact group,
  centered in the space to the left of the table controls and shifted slightly
  right. Neighbors come from the current match tuple,
  with no wraparound, and preserve search and display mode through the session.
  Navigation and display controls share one row, wrapping on narrow screens.
- Tabulator uses `height: '100%'` inside the flexing detail panel. Both it and
  the HTML fallback scroll within the remaining viewport height. Cell padding
  and column-header padding are reduced without changing stored text formats.
- `static/scrollbars.js` supplies persistent top horizontal and right vertical
  scrollbars in a CSS grid `.table-frame`. Native scroll positions still drive
  the table and frozen headers. The controller hides native bars only while
  custom controls are attached, with rails shown only for overflowing axes.
  Pointer capture supports dragging; track clicks and keyboard navigation are
  supported. Scroll events and ResizeObserver keep thumbs and ARIA values in
  sync with content, window size, and column/row resizing. `app.js` rebinds the
  controller to the preserved grid after swaps, destroys observers/listeners
  when its frame is removed, and supports the HTML fallback when Tabulator is
  unavailable. With scripts unavailable, the fallback keeps native scrolling.
  The controller supports frames with only one rail. The results list uses
  a separate vertical instance in `.results-scroll-frame`, controlling
  `#results-viewport`. `app.js` binds it independently of Tabulator during
  workspace initialization, refreshes it after sidebar hide/show, and destroys
  it before its frame is removed by htmx. The sidebar keeps native scrolling
  when the script is unavailable; no rail is rendered for empty results.
- Workspace HTML includes a safely JSON-encoded payload. JavaScript updates
  the page title and search controls from it. Internal grid fields such as
  `content_0` avoid interpreting punctuation in column names as property paths.
- `config.py` is loaded once per app creation. `SEARCH_HIGHLIGHT_COLOR` defaults
  to `#ffff00` (yellow) and accepts #RGB/#RRGGBB. Restart after changing it. The
  workspace sets `--search-highlight-color`, shared by the grid and fallback.
- `search_highlighting.py` creates presentation-only `<mark>` elements for all
  query occurrences in displayed content, regardless of column/label filters.
  It maps normalized uppercase search matches back to original characters,
  including ligatures, combining accents, and Catalan middle dots. HTML parsing
  matches decoded text across rich-text runs, never attributes, and wraps text
  within each existing run to retain formatting. Plaintext is escaped before
  marking; empty or normalization-empty queries produce no marks.
- The original DataFrame, `get_etimon` output, and raw grid field values retain
  their contents. Each grid row additionally has `highlights`, mapping internal
  content field names to highlighted HTML only for matching cells. The frontend
  renders those generated strings when present; the fallback uses the same
  server-generated HTML. Search/display changes replace highlights and Clear
  removes them. The editor loads original HTML from separate metadata, never
  the generated highlights.
- Each grid row also has `backgrounds`, mapping internal content fields and
  `label`/`label_number` to effective fill colors. The label fill colors both
  identifier cells and empty content cells without their own Excel fill.
  Originally empty cells retain that background when filled by editing.
  Originally populated cells keep their own fill; unfilled populated cells
  retain the standard content surface.
  `formatRow` applies colors to all actual Tabulator cells (including frozen
  cells, padding, and resized area), clearing old inline colors when absent.
  Empty cells also get `is-empty`, sharing `--label-background` with identifier
  cells when no Excel fill is set. The fallback sets the same colors/classes
  on its `<th>` and `<td>` elements.
  Fills remain visible in plain-text mode. Search `<mark>` backgrounds use
  their own configured color and stay above cell fills. `get_etimon` keeps its
  existing wide-column contract; the extra import field is display metadata.
- `#etimon-grid` uses `hx-preserve`. `static/app.js` keeps its Tabulator instance
  alive between fragments, updates rows, reconfigures changed columns, and
  destroys it when the grid is actually removed. A native HTML fallback table
  is hidden only after the interactive grid is ready.
- Grid header sorting is disabled to preserve domain ordering. Label and
  number columns are frozen and always visible. Language/notes columns can
  be hidden. Both column widths and row heights can be resized.
- localStorage stores column widths/visibility per workbook and row heights
  per etymon and label/number pair, using `xldb.layout.v1.<dataset hash>`.
  Dataset identity is the database's persisted UUID, so moving it preserves
  layout keys. Reset layout clears preferences for that dataset. In-memory
  preferences still work when localStorage is unavailable.
- **Upgrade-sensitive detail:** restoring individual row heights uses
  `row._getSelf().setHeight(height)`, an isolated private-API adapter for
  pinned Tabulator 6.3.1. Recheck it when upgrading Tabulator.

**Earlier workbook utilities**

- `extract_sheet(original_path, sheet_name, new_path)` retains the chosen
  worksheet, makes it visible, and saves a new workbook. It protects against
  overwriting the source; references to removed sheets are not rewritten.
- `find_replace_excel(excel_path, replace_dict, sheet_name=None,
  output_file=None, cell_range=None)` applies every literal, case-sensitive
  pair in dictionary insertion order, including within formula text, and
  saves once. Replacement text may be affected by later pairs.
- Default output is `<stem>_replaced<extension>` beside the source.
  `output_file=False` explicitly overwrites the original. Range is a bounded
  cell/rectangle, e.g. `A1:D20`; all column A is `A1:A1048576`, not `A:A`.
- `to_replace.py` contains the user's cleanup labels/dictionary; it is not
  automatically executed by the app.
- Unlike the DataFrame importer, these earlier save utilities do not enable
  `rich_text=True` when loading. Within-cell rich-text formatting can therefore
  be flattened by a save. This has not been repaired as part of later work.

**Deployment behavior**

- `main.py` uses Waitress in both modes: `--local` (default, 127.0.0.1),
  `--public` (0.0.0.0), or `--host IP`, plus `--port` (default 5000, 1–65535).
  The CLI forces debug/testing off and disables traceback exposure.
- `--trusted-host HOSTNAME` repeats to override Flask `TRUSTED_HOSTS`;
  `config.py` defaults to None (all hosts). This checks Host, not user access.
- `--trusted-proxy IP` trusts exactly one peer/hop for X-Forwarded-For/Proto
  only. Waitress clears other forwarding headers; no ProxyFix is installed.
  `--secure-cookies` enables Secure cookies and HSTS on HTTPS responses, requiring
  an HTTPS reverse proxy. No built-in TLS or login is provided.
- Stable keys come from `FLASK_SECRET_KEY`; otherwise browser preferences reset
  on restart. HttpOnly/SameSite=Lax stay enabled. Source workbook access remains read-only;
  SQLite accepts edits through POST `/cell` and exports through GET `/export`.
- All Flask responses get CSP, nosniff, frame denial, and same-origin referrer
  policy. CSP allows inline styles for Excel/Tabulator, but scripts only from
  self. htmx allowEval=false, selfRequestsOnly=true, historyCacheSize=0; keep JSON
  workspace script tags intact. There are no inline executable scripts.
- CLI limits: 16 KiB headers, 64 KiB bodies, 30s idle timeout, 100 connections,
  four worker threads. App config: 8 KiB query strings, 500-character searches,
  64 KiB bodies. Unknown filter values are rejected; repeated filters deduplicate
  before cookie storage. Limits run before preference mutations.
- `tests/test_deployment.py` covers headers, Host/proxy trust, HTTPS cookies,
  request bounds, private paths/methods, and an unchanged read-only workbook.
  CLI tests mock Waitress rather than Flask.run. A live loopback HTTP smoke check
  exercises Waitress; local Chromium also checks editing under CSP. No remote
  Nginx/systemd or real HTTPS editing deployment was performed here.
- `DEPLOYMENT.md` includes HTTPS Nginx and unprivileged/read-only systemd examples,
  secret/log handling, firewall guidance, and remaining availability limits.
  Anyone who can reach the app can read and edit all data; use proxy authentication/VPN
  for private workbooks and keep the backend inaccessible around that proxy.

**Discussed future direction and remaining limits**

The first Quill implementation used an in-memory DataFrame. SQLite, Excel
export, mode switching, and entry creation now support a single local user. The team
prefers Excel and does not want individual passwords; future access should
start with one shared editing password and remembered self-declared names.
Do not require per-user accounts or prioritize impersonation prevention over
that preference. Attribution, cell locks with expiry, row/etymon warnings,
and history remain separate future tasks.

`static/cell_editor.js` owns a single active editor. It loads original HTML
from `row.editors[field]`, including in plaintext view; it never imports search
marks. Style-based font/size attributors, whitespace matchers, and a script
matcher retain supported workbook formatting. Changed cells are converted to
Quill's supported formats (double underline becomes underline); unchanged
cells keep their exact original HTML. Navigation and layout changes are blocked
until Close/Cancel. A failed save retains the draft; page reload/close loses it.

POST `/cell` accepts a signed cell/revision token and Quill insert operations.
It requires a session-bound CSRF header. `cell_editing.py` validates only text
and allowlisted inline styles, then escapes and renders HTML; it never accepts
client HTML, images, links, or arbitrary CSS. HTML, plaintext, and normalized
search text update atomically in SQLite; later queries rebuild titles. Cell
fills stay separate. Empty content cells can be populated; clearing a cell
retains its record/row identity. Existing label/number editing is absent;
new rows receive their type and number through the creation controls.

A store RLock serializes use of its SQLite connection. Read transactions keep
each page consistent; BEGIN IMMEDIATE transactions validate revision and commit
edits atomically. Cell IDs/revisions persist in SQLite, including for newly
populated empty cells. Tokens still carry the logical location and revision;
a process-specific signing salt expires them at restart. Keep one application
process while that token mechanism remains. Other browsers see changes on
their next request; there is no push synchronization or authentication.

Whole-cell spacing is a validated unitless number in [0.5, 4]. POST `/cell`
accepts `line_height` separately from Quill's inline Delta. It is stored in
the SQLite cell's `line_height` field and on the rendered HTML's outer div.
Detached DataFrame snapshots expose it through `attrs['cell_line_heights']`.
Grid editor metadata includes `line_height`;
Tabulator cells and fallback `<td>` elements apply it in both display modes.
The existing eight DataFrame columns are unchanged. Omitting spacing on a
save retains a prior setting. Empty cells can retain spacing as metadata.
The editor reads the existing cell line height (normally 1.6), uses that as
its initial whole-cell setting, and compares it alongside the initial Delta
to detect changes. No per-paragraph Quill format or spacing attributes are added.

The current backend/tests assume the example fixture's layout and some labels.
The user may clean the source workbook themselves; check fixture-related test
failures against the workbook before changing application behavior. Preserve
the user's Excel files and do not silently normalize label spelling/spacing.
