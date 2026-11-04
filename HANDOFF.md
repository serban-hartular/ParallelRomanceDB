# XLDB development handoff

Prepared 2026-11-04. Workspace: `/home/hartular/Lingv/XLDB`.

**Copy into the next chat**

> Continue the XLDB project in `/home/hartular/Lingv/XLDB`. Read `README.md`
> and `HANDOFF.md` first. It is a working local Flask app for searching and
> comparing Romance-language etymon subtables imported from Excel. htmx
> updates search results and etymon selection without full-page reloads;
> Tabulator provides the read-only table, column visibility and resizing.
> Preserve original text/formatting and label wording. Search ignores case
> on the website, removes Unicode diacritics, expands œ/æ and ø/ł, and folds
> Catalan l·l. The search field is named `nodiacritics_plaintext`.
> The layout has compact controls, a collapsible etymon side list, and a table filling
> the remaining viewport. Future Quill editing has been discussed; editing and SQLite have not
> been implemented. There is no unfinished implementation request at handoff.

**Run and verification**

```bash
cd /home/hartular/Lingv/XLDB
.venv/bin/python main.py
# Open http://127.0.0.1:5000

.venv/bin/python -m unittest -v
node --check static/app.js
node --check static/scrollbars.js
node tests/test_scrollbars.js
```

- Existing environment: Python 3.13.12, Flask 3.1.3, pandas 3.1.0,
  openpyxl 3.1.5. Direct dependencies are recorded in `requirements.txt`.
- Latest verification: 38 Python tests, five Node scrollbar interaction tests,
  and JavaScript syntax checks passed after adding configurable search highlights.
  The Node tests use simulated DOM geometry; no browser visual testing was run.
- `tests/__init__.py` preserves discovery with `python -m unittest -v` from
  the project root. Workbook fixture paths are relative to that root.
- No automated browser/visual testing was available. The user has repeatedly
  confirmed that the page and interactions look good.
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

Seven DataFrame columns:

```text
etimon_number, column, label, label_number,
content, plaintext_content, nodiacritics_plaintext
```

`content` is escaped HTML with inline CSS for cell and rich-text-run fonts,
colors, bold, italics, size, underline, strike, and sub/superscript. It
preserves whitespace via `white-space: pre-wrap`. It does not reproduce Excel
borders, fills, or worksheet layout. `plaintext_content` trims only the outer
whitespace. Formulas are retained as expressions, not evaluated.

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
  test_config=None)` and a module-level `app = create_app()`. Importing the
  module therefore loads the workbook. Default source is `db/example.xlsx`,
  relative to `main.py`. The imported df is in `app.extensions['lexicon_df']`.
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
  removes them. Generated highlights must not be treated as saved cell content
  when editing is eventually added.
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

**Discussed future direction and remaining limits**

The user wants an app-like research tool and may next refine layout. They
eventually want to edit cell contents and add rows. The discussed direction
was Flask + htmx + a dedicated grid, with one reusable Quill editor in a side
panel/dialog, plus SQLite persistence before editing. Only the viewing/grid
stage is implemented. There are no save/edit endpoints, Quill assets, database,
authentication, or deployment configuration.

Before implementing editing, introduce stable row/cell IDs: current etymon and
label numbers are worksheet-derived ordering values. Preserve imported content
until an edit is saved. Test Quill round-tripping on representative rich text,
fonts, superscripts, and whitespace; its HTML import may normalize formatting.
HTML/plaintext/normalized search text must be updated together, and match caches
and result titles refreshed after edits. Editing would also require revisiting
the current trust boundary: formatted HTML is presently emitted only by the
escaped workbook converter.

The current backend/tests assume the example fixture's layout and some labels.
The user may clean the source workbook themselves; check fixture-related test
failures against the workbook before changing application behavior. Preserve
the user's Excel files and do not silently normalize label spelling/spacing.
