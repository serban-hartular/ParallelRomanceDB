# XLDB development handoff

Updated 2026-11-05 for inline Quill editing in the shared in-memory DataFrame.
Workspace: `/home/hartular/Lingv/XLDB`. User-facing name: **Parallel Words**.

**Copy into the next chat**

> Continue the XLDB project in `/home/hartular/Lingv/XLDB`. Read `README.md`
> and `HANDOFF.md` first; also read `DEPLOYMENT.md` before deployment work.
> The app is branded Parallel Words and uses Flask + htmx + Tabulator, with
> Waitress for local/public serving. It imports one Excel file/sheet at startup,
> supports multiple column/label filters and case/diacritic-insensitive search,
> and displays resizable tables with persistent scrollbars, a collapsible
> ETYMONS list, previous/next navigation, and configurable search highlighting.
> Excel background fills cover content cells, labels, label numbers, and empty
> cells using the documented inheritance rules; highlighting stays above fills.
> Preserve original workbook text, formatting, and label spelling/spacing.
> CLI options select the workbook, sheet, local/public/specific interface, port,
> trusted hosts/proxy, and secure cookies. The user reports remote deployment works.
> Double-clicking a content cell opens Quill inline; Close saves to the shared
> DataFrame only, Cancel/Escape discards. All edits vanish on server restart;
> the workbook stays untouched. There is no authentication: reachable visitors
> can read and edit. Run one application process. SQLite persistence, row
> insertion, and accounts remain future plans.
> Inspect the current Git state and preserve existing changes. No implementation
> request is pending; I will provide the next task.

**Current state and continuation**

- Application code is committed at `5f57829` (`Cell backgrounds. Made server
  work for outside world (not checked yet).`). Existing README/HANDOFF/DEPLOYMENT
  changes were preserved when adding inline editing. Check `git status` when
  resuming; this work does not commit, push, or deploy anything.
- Latest behavior: Quill opens inside a double-clicked content cell. Close or
  Ctrl/Cmd+Enter saves; Cancel or Escape discards. Changes update the running
  DataFrame only. No-op closes preserve exact original HTML. Labels/numbers
  remain fixed. Imported backgrounds and all search/layout behavior remain.
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
- Preserve source Excel files and label spelling/spacing. The user explicitly
  chose in-memory DataFrame updates, rather than SQLite or workbook saves.
  SQLite, uploads, accounts, and row insertion are not implemented.

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
- Latest verification: 70 Python tests, six Node scrollbar interaction tests,
  and JavaScript syntax checks. Six real Chromium check groups exercise inline
  editing under the app's CSP, rich text/whitespace, no-op/Cancel, shared saves,
  conflicts, search/plaintext, empty-cell fill/clear, selected font size,
  inherited line height, and whole-cell spacing/save/reopen/Cancel. Scrollbar tests use
  simulated geometry. No remote editing deployment has been tested here.
- Manual Waitress smoke checks bound only `127.0.0.1` on an ephemeral port:
  full page and htmx search returned 200; an unapproved Host returned 400;
  `/db/example.xlsx` returned 404; oversized headers/body returned 431/413.
  A forged forwarding header did not enable HTTPS behavior. This was an ad hoc
  check, not a committed socket-based test.
- `tests/__init__.py` preserves discovery with `python -m unittest -v` from
  the project root. Workbook fixture paths are relative to that root.
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
  test_config=None)`. Importing the module exposes `app = create_app()` for
  Flask and loads the default workbook. Default source is `db/example.xlsx`,
  relative to `main.py`. The imported df is in `app.extensions['lexicon_df']`.
- Direct script execution calls `main(argv=None)`: an optional positional file
  and `--sheet/-s NAME` are parsed before creating the app. Only the selected
  workbook is loaded; `--help` loads none. Omitted arguments retain the example
  and the first worksheet. Explicit relative paths resolve from the shell's
  current directory. Common file/format/sheet/layout errors print an argparse
  startup error and exit 2 without starting Flask; factory calls still raise.
- The workbook is read once per app creation. Restart after changes. Match
  tuples are held in a bounded LRU cache. Signed Flask sessions hold each
  browser's criteria, selection, and plaintext mode, not the full match list.
  `FLASK_SECRET_KEY` is optional; otherwise a fresh key is generated on startup.
- GET `/` accepts `search=1&q=...&column=...&label=...`, with repeated `column`
  and `label` parameters for multiple selections, `etimon=N`,
  `plaintext=0|1`, or `reset=1`. New searches select the first match. A selection
  outside current matches falls back to the first match. Empty results are
  handled without showing a stale etymon. Clear retains the display mode.
- Search filters use checkbox dropdowns; no checked values means all. An
  **All columns/labels** button clears that filter's checkboxes. Criteria store
  sorted, deduplicated lists in the session and grid payload; older sessions
  containing single strings are migrated on read. The match cache uses tuples.
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
  identifier cells and every empty content cell. Populated content cells keep
  their own fill; unfilled populated cells retain the standard content surface.
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
  Dataset identity comes from the workbook path and requested sheet, not file
  contents. Reset layout clears preferences for that dataset. In-memory
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
  the shared DataFrame accepts edits through POST `/cell`.
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

The original plan considered SQLite before editing and a side-panel Quill editor.
The user subsequently requested Quill inside the double-clicked cell and chose
the existing in-memory DataFrame as the save destination. That behavior is now
implemented. Database persistence, adding rows, accounts, and export remain future work.

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
search text update together, cached matches clear, and titles rebuild. Cell
fills stay separate. Empty content cells can be populated; clearing a cell
retains its record/row identity. Label/number editing and row insertion are absent.

An RLock protects all DataFrame reads/writes during requests. Per-cell revisions
reject stale saves, including conflicting empty-cell edits. A process-specific
signing salt expires editor tokens at restart even with a stable session key.
Cell identity uses the current immutable (etymon, label, number, column) tuple;
introduce persistent stable IDs before adding row insertion/reordering or a
database. One process is required: DataFrames/revisions are not shared between
processes. Waitress's four threads share the one app. Other browsers see changes
on their next request; there is no push synchronization or authentication.

Whole-cell spacing is a validated unitless number in [0.5, 4]. POST `/cell`
accepts `line_height` separately from Quill's inline Delta. It is stored in
`df.attrs['cell_line_heights']`, keyed by the same cell identity tuple, and on
the rendered HTML's outer div. Grid editor metadata includes `line_height`;
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
