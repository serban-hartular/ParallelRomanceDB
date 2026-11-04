# XLDB

A read-only Flask interface for searching and comparing the etymons in an Excel workbook.
The page is branded **Parallel Words**; its header shows the loaded workbook's
filename followed by the actual worksheet name (including when the first sheet
is selected automatically).

For the development handoff, agreed behavior, and future work, read
[HANDOFF.md](HANDOFF.md).

Run the server from this directory:

```bash
.venv/bin/python main.py
```

Open **http://127.0.0.1:5000**. The app loads `db/example.xlsx` once when it
starts. To load a different workbook, optionally choosing a worksheet:

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
read the loaded worksheet.** Put private data behind a VPN or authenticated proxy.

Omitting the file keeps the bundled example. Omitting `--sheet` (or `-s`) selects
the **first worksheet**, not the active worksheet. Sheet names match exactly.
Provided relative file paths are resolved from the directory where you run the
command; the default example path is relative to `main.py`. Use
`.venv/bin/python main.py --help` for usage without loading a workbook.
Restart the server after editing the workbook. Python callers can still use
`create_app('db/other.xlsx', sheet_name='Sheet1')`.

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
cells keep their own fills. Blank label cells inherit the preceding explicit
label's fill unless they have a fill of their own; a new uncolored label resets
that inheritance. With no imported label fill, labels, numbers, and empty cells
share the table's neutral label background. Entirely empty rows remain omitted.

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
interactive, read-only table. Use **Table columns** to choose visible columns, drag
column-header edges to resize widths, and drag row borders to resize heights.
Labels and label numbers remain visible while scrolling horizontally.
Persistent, draggable scrollbars sit **above the table** for left/right scrolling
and at its **right edge** for up/down scrolling. They stay visible whenever
content overflows, regardless of the system's overlay-scrollbar setting. Click
a track or drag its thumb; wheel, touch, and keyboard scrolling stay synchronized.
Focused scrollbars also support arrow keys, Page Up/Down, Home, and End.

The browser remembers column widths and visibility for each workbook, and row
heights for each etymon. **Reset layout** clears those display preferences for
the current workbook. These controls do not change the Excel data.

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
node --check static/scrollbars.js
node tests/test_scrollbars.js
```

Node is optional for the JavaScript checks; the application itself does
not require Node or npm. The most recent verification passed all 56 Python
tests, six scrollbar interaction tests, and JavaScript syntax checks.
Scrollbar tests use simulated DOM geometry, not a browser. Automated browser interaction/visual
tests have not been run; the user has confirmed that the page looks good.

**Project files**

| File | Purpose |
| --- | --- |
| `main.py` | Flask app factory, startup import, search sessions, cached matches, grid payloads |
| `config.py` | Highlight color, allowed hosts, secure cookies, and request limits |
| `DEPLOYMENT.md` | Local/public startup, HTTPS proxy, permissions, and deployment limits |
| `search_highlighting.py` | Normalized match ranges and formatting-preserving highlights |
| `extract_sheet.py` | Worksheet extraction, dictionary find/replace, Excel-to-DataFrame conversion |
| `df_search.py` | DataFrame search, etymon table reconstruction, label/column ordering |
| `text_normalization.py` | Shared accent removal and Latin-letter expansion |
| `templates/index.html` | Full page and search form |
| `templates/_workspace.html` | htmx fragment, results list, grid data and fallback table |
| `static/app.js` | Tabulator lifecycle, display preferences, htmx integration |
| `static/scrollbars.js` | Persistent top/right scroll controls and native-scroll synchronization |
| `static/style.css` | Page, fallback table, and grid styling |
| `static/vendor/` | htmx 2.0.8 and Tabulator 6.3.1, licenses and source references |
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

The grid remains read-only. Quill editing, row insertion, and database
persistence have been discussed but are not implemented.
