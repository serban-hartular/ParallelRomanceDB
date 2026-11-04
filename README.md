# XLDB

A local Flask interface for searching and comparing the etymons in an Excel workbook.
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
starts. Restart the server after editing the workbook. To load another file or
sheet, change the `app = create_app()` call in `main.py`, for example:

```python
app = create_app('db/other.xlsx', sheet_name='Sheet1')
```

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

Set the highlight background in `config.py`, then restart the server:

```python
SEARCH_HIGHLIGHT_COLOR = '#ffff00'  # Standard highlight yellow; #RGB or #RRGGBB.
```

Search controls sit in a compact bar. A side list headed **ETYMONS** shows the
results. Use **«** to hide it and give the table more width, or **»** to show it
again. The choice survives etymon selection and display-mode changes; a new
search reveals the results. On narrow screens, the list opens over the left
side of the table. The table fills the remaining viewport height.
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

The app uses Flask, pandas, and openpyxl >= 3.1 from the virtual environment.
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
not require Node or npm. The most recent verification passed all 38 Python
tests, five scrollbar interaction tests, and JavaScript syntax checks.
Scrollbar tests use simulated DOM geometry, not a browser. Automated browser interaction/visual
tests have not been run; the user has confirmed that the page looks good.

**Project files**

| File | Purpose |
| --- | --- |
| `main.py` | Flask app factory, startup import, search sessions, cached matches, grid payloads |
| `config.py` | Display configuration, including the search highlight color |
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
| `content` | HTML preserving text formatting and original whitespace |
| `plaintext_content` | Plain text with outer whitespace trimmed |
| `nodiacritics_plaintext` | Derived search text with accents removed and letter variants expanded |

The grid remains read-only. Quill editing, row insertion, and database
persistence have been discussed but are not implemented.
