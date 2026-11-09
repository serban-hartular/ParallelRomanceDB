# XLDB

A Flask interface for searching, comparing, and editing linguistic collections,
branded **Parallel Words**. Each collection has its own SQLite database,
workbook template, content, column and row type definitions, and Trash.
A small catalog database lists the collections and stores browser preferences.

Read [HANDOFF.md](HANDOFF.md) for development continuity and
[DEPLOYMENT.md](DEPLOYMENT.md) before deployment work.
Use [MANUAL_TESTING.md](MANUAL_TESTING.md) for the user acceptance checklist.
The checklist currently marks T01–T16 and T81–T82 complete; the remaining 75 of
93 tasks, including new collection-name checks T91–T93, are pending. Automated test results are
recorded separately in HANDOFF.md and do not change user acceptance status.
Administration is available at `/admin/` (also linked from the page header).
See [ADMIN_DESIGN.md](ADMIN_DESIGN.md) for its interface and access rules; the
[original static preview](design/admin/index.html) remains available as a design reference.

**Interface language and editing translations**

Romanian is the default. Use **Română / English** in any page header to switch
between the two languages. The choice is saved in a separate browser cookie for
one year and also applies to administration and export pages. The switch works
without JavaScript. A cell editor must be closed or cancelled before switching;
the current applied search/filters and selected etymon are retained.

All interface messages are in [translations.json](translations.json), encoded in
UTF-8. Each stable English message key has editable `ro` and `en` display values:

```json
"Search": {
  "en": "Search",
  "ro": "Caută"
}
```

Edit the values, keeping the keys and named placeholders such as `{count}`,
`{name}`, or `{value1}` intact. Values are plain text, not HTML. Restart the server
and reload open pages after editing the file. No translation service or network
request is used. `DEFAULT_UI_LANGUAGE` in `config.py` controls the default for
browsers without a saved choice; its normal value is `ro`.

Collection names, worksheet names, imported column/row labels, saved content,
formatting, snapshots, and editor names retain their original text in either
interface language. A new entry's suggested initial text is localized as
`[De completat]` / `[To be added]`. DELETE remains the exact confirmation token.
Command-line tools continue to use English. Romanian administrator timestamps
use `dd.mm.yyyy`, with the existing Europe/Bucharest UTC offset.

**Create collections and start the server**

Run these commands from the project directory after installing `requirements.txt`:

```bash
# Import one sheet; omit --sheet to select the first worksheet.
.venv/bin/python manage_collections.py create "Gastronomy" --workbook "db/my workbook.xlsx" --sheet "Sheet 1"

# An empty collection starts with the standard language columns and four row types.
.venv/bin/python manage_collections.py create "Fashion"
.venv/bin/python manage_collections.py list

# Set the shared edit password (hidden prompts); browsing works without it.
.venv/bin/python manage_access.py set-edit-password

# Defaults to data/catalog.sqlite3 and http://127.0.0.1:5000.
.venv/bin/python main.py
```

Choose a collection in the page header. Bookmarks and all search/edit/export
requests use `/collections/<collection-id>/...`. Different tabs can work in
different collections safely. Search, selection, display mode, and Edit mode
are remembered separately for each browser profile and collection; tabs showing
the same collection still share these preferences. Table layouts are stored
locally in the browser, keyed by collection identity.

No collections are imported automatically. An empty catalog shows an empty
landing page until an administrator creates a collection. **Admin → Collections**
creates empty collections, imports Excel worksheets, and manages recoverable
Collections Trash. Import names default to the selected worksheet, with (1), (2),
and so on added for names already used by active or trashed collections. Automatic
suggestions follow worksheet changes; a name you type is retained. **Suggest name
for worksheet** refreshes the suggestion and also works without JavaScript.

**Admin → Collections → Rename collection** changes an active collection's name.
It requires a unique name and is blocked while any cell editor is open in that
collection. Edit mode without an open cell is allowed; editors in other
collections do not block it. Closing/Cancel releases the restriction. Renaming
preserves the collection's ID/bookmarks, workbook, content, history, Trash, and
preferences. An already-open collection page picks up its new name on the next
live refresh. The main header prominently shows only the collection name; in
single-database mode it uses the worksheet name. Local create/import/register commands remain available;
registering an existing database still requires the local command.

To put the catalog elsewhere, pass the same path to both commands:

```bash
.venv/bin/python manage_collections.py --catalog /path/to/catalog.sqlite3 create "Gastronomy" --workbook /path/to/source.xlsx
.venv/bin/python main.py --catalog /path/to/catalog.sqlite3 --local --port 8080
```

Collection files are created under `collections/` beside the catalog, with
UUID filenames. The catalog records their absolute paths. Keep the catalog and
its collection files together when backing up; moving them to another directory
requires updating the catalog paths or registering the files in a new catalog.
Register an existing **new-format** collection with
`manage_collections.py register "Collection name" /path/to/collection.sqlite3`.
The same identity or name cannot be registered twice in one catalog.

**Fresh database format**

The collection redesign starts from scratch, as agreed. Schema versions 1–3 are rejected
with a reimport message and left unchanged. Reimport the desired Excel workbook
into a new collection; export older saved edits using the previous application
version first if they need to be carried forward. No migration is attempted.
Existing source workbooks and database files are not replaced by collection creation.
Normalized schema-4/5/6 collections upgrade automatically to schema 7 by adding
edit history, its editing lifecycle fields, and a committed-content version
counter. Their content, IDs, formatting, and Trash are retained. No reimport is needed for that update. Earlier edits have no retroactive attribution.

Within each collection, `column_definitions` stores exact names, display order,
original Excel column positions, and result-title priority. `row_types` stores
the default labels, display order, etymon-marker role, whether rows can be added,
and default background colors. `dataset.initial_column_id` selects the column
used for initial text when creating entries (French by default).
`row_metadata` links each row to its type while retaining its exact original
label spelling/spacing and number. `cells` links permanent row and column IDs
to saved HTML, searchable text, fill, revision, and line spacing.
`cell_records` is a joined view exposing the familiar DataFrame fields.
Etymons, columns, row types, rows, and cells have stable IDs; each collection
has a UUID. Original label variants remain intact even if a type's default
label is changed for future rows.

Runtime display order, title selection, row creation, and marker protection use
these database definitions. Constants in `df_search.py` and `config.py` only
seed the default definitions on import/empty creation. Definition management
currently requires local database administration; there is no metadata-editing
UI. The Excel importer still expects the source layout documented below.
A temporary DataFrame reconstructs the selected etymon's display; SQLite is
the source of truth.

**Serving and single-database tools**

Local access is the default. Use `--public --port 8080` to bind all IPv4
interfaces, or `--host IP` for a specific interface. These flags are mutually
exclusive. Waitress serves the app. Read [DEPLOYMENT.md](DEPLOYMENT.md) for
HTTPS proxy settings, trusted hosts, secure cookies, and service permissions.
Browsing, search, and Excel download are public. Editing requires the shared
global edit password and a self-declared editor name, as described below.

**Administration**

Set a separate global administrator password locally before using `/admin/`:

```bash
.venv/bin/python manage_access.py set-admin-password
# If the server uses a custom access file:
.venv/bin/python manage_access.py --database /path/to/access.sqlite3 set-admin-password
```

Use the same access file as the running server (normally `data/access.sqlite3`).
The command prompts twice with hidden input; no default admin password is created.
Use a different password from the shared edit password. Until it is configured,
the admin login page explains that local setup is required. The same command
resets a forgotten administrator password and revokes existing administrator logins.

Open **Admin** in the header, or visit `/admin/`, and enter an administrator name
and password. This browser-session login is independent of editing: the edit
password grants no administration access, and an admin login does not silently
activate editing. Admin sign-out leaves an independent editor login intact.
The interface uses plain HTML forms and works with JavaScript disabled.

The overview and collection selector lead to:

- **Collections:** create a uniquely named empty collection, or upload an `.xlsx`
  or `.xlsm` workbook and choose the exact worksheet and new collection name.
  Standard columns/row types seed empty collections. Imports use the existing
  workbook layout validation and retain the complete original workbook for export.
  A failed import leaves no partial collection. Cancel removes the staged upload.
  Pending uploads belong to the current admin login, expire after 30 minutes,
  and are cleaned up on the next upload/import request.
- **Collections Trash:** review removal, type `DELETE`, and confirm. Active cell
  editors block removal. Removed collections disappear from public routes and
  both collection selectors; existing bookmarks return 404 until restoration.
  Reload an already-open page to update its collection chooser. Restore from
  Collections Trash with the original IDs, database, workbook, content, history,
  preferences, and row/etymon Trash. Names remain reserved; there is no permanent
  deletion. Collections Trash is separate from the selected collection's row Trash.
- **Passwords:** change either global password after re-entering the current
  administrator password. Changing the edit password revokes editor logins while
  retaining admin access. Changing the admin password signs out all administrators,
  including the current one, without revoking independent editor logins.
- **Trash:** filter pending/recovered rows or etymons, inspect retained text, then
  review and confirm recovery. Restore a containing etymon before a separately
  deleted row. Original IDs, numbers, content, and formatting return, recovery is
  attributed to the admin name, and open collection views update automatically.
  Large previews show at most 200 cells; recovery restores the complete entry.
- **History:** filter by etymon, editor, action, outcome, and local date range;
  browse 50 events per page; inspect before/after text and escaped formatting
  snapshots. Saved changes are the default; activity shows cancelled, unchanged,
  active, expired, and revoked editors. Unsaved typing is never recorded.
- **Active editors:** see current cell locks and contact/expiry times, with a
  manual Refresh link. This does not provide forced lock takeover.

Times display Europe/Bucharest with UTC offsets; storage remains UTC. Every
admin POST checks the admin grant and CSRF. Recovery confirmations also bind the
collection, item, and login's form context. Admin pages are uncached. There is no
permanent purge, revision revert, or browser definition editing.
Local tools remain available. Use HTTPS for remote admin access, as for editing.

The access database upgrades additively from schema 1 to 2, retaining existing
credentials and grants and adding `admin_events`. Password changes and their
audit metadata commit together, without passwords/hashes in audit records.
Recoveries use the collection's existing transactional history. Collection schema
7 and workbook data are unchanged by the access upgrade. No reimport is needed.
The catalog upgrades additively from schema 1 to 2, retaining collection entries
and browser preferences and adding removal state and attributed collection events.
Collection management requires catalog mode (`--catalog`), not single-file mode.

Workbook uploads default to 25 MiB, with a 100 MiB expanded archive limit,
2,000 archive members, 500,000 populated cells across the workbook, and a
2,000,000-cell selected-sheet grid. Browser imports support up to 100,000 rows
and 256 columns. DTD/entity XML, encrypted archives, and duplicate ZIP members
are rejected. `COLLECTION_UPLOAD_*` settings in `config.py` control the configurable
bounds. Only workbook uploads get the larger body allowance; other requests
retain the 64 KiB limit. See DEPLOYMENT.md for the proxy upload setting.

**Edit access and attribution**

Before enabling edits, set the global password locally:

```bash
.venv/bin/python manage_access.py set-edit-password
```

The command prompts twice with hidden input. It stores a salted password hash,
never the password, in `data/access.sqlite3`. Do not put passwords in source,
command arguments, or environment variables. Setting/changing the password
revokes all existing edit logins immediately, without restarting the server.
If no password is configured, browsing/export work and editing stays disabled.

With a custom catalog, the access database defaults to `access.sqlite3` beside
that catalog; single-file mode uses the collection database's directory. To
select an explicit shared location, use matching paths:

```bash
.venv/bin/python manage_access.py --database /path/to/access.sqlite3 set-edit-password
.venv/bin/python main.py --catalog /path/to/catalog.sqlite3 --auth-database /path/to/access.sqlite3
```

`AUTH_DATABASE_PATH` in `config.py` is another option. New access files are
created with owner-only permissions. Keep the access database in backups too;
losing it requires setting a new edit password and signing in again.

Click **Edit mode** to open **Who is editing?** and enter your name and the shared
password. Cancel or an incorrect password leaves the collection unchanged.
The header shows the signed-in name and offers **Change editor** and **Sign out**.
This login covers all collections and tabs in the same browser session. Switching
to Search mode retains the login. A later browser session must sign in again;
there is no “remember me” option and no login data in localStorage.
Browser session restoration can restore session cookies; **Sign out** explicitly
revokes access even if a browser restores an old cookie.

Close/cancel a cell draft before changing identity or signing out. A draft/token
opened under one login cannot be saved under another person's name. Creation
dialogs also carry the opening login identity, so an old tab's Add action is
rejected after changing editor elsewhere. Sign-out
and password changes revoke access on the server across tabs; a stale tab may
still show old controls until refresh, but cannot save. Rejected saves retain
the draft so the user can copy it before cancelling/reloading. Password attempts
are limited to ten failures per client IP in five minutes per application process.

Each successful cell save completes its open `edit_history` record. A row/etymon
addition, deletion, or local Trash recovery adds a completed record to that collection's database. It includes
UTC time, action, editor name/session identity, permanent target IDs, exact row
label/number and column name, and before/after content snapshots. The content
write and history completion commit together. A rejected save leaves its
editing-session record active until closed or expired, with no saved change.
Local Python/CLI modifications without a browser identity are attributed to
**Local administrator**. No-op Close records an unchanged editing session without writing cell content. Existing imported content has no invented editor identity.

Administrators can inspect history locally:

```bash
.venv/bin/python history.py data/collections/COLLECTION-ID.sqlite3
.venv/bin/python history.py data/collections/COLLECTION-ID.sqlite3 --etymon 1 --limit 50
.venv/bin/python history.py data/collections/COLLECTION-ID.sqlite3 --json
```

`--json` includes exact before/after snapshots. History is available through the protected admin interface or local CLI;
it is not public or exported into Excel. There is no revision-revert UI.
Cell editors now acquire an exclusive lock before Quill opens. Another editor
cannot open that cell or delete its containing row/etymon, including from another
tab under the same login. The server names the person holding the lock. Editing
a different cell in the same row or etymon remains allowed; an inline notice
lists the other editors and their row/column. It requires no extra confirmation.
Notices update with background contacts. Collections remain independent.

An open editor sends a heartbeat every **30 seconds**, independently of typing
or mouse activity. It can remain open indefinitely while connected. Without
contact for **five minutes**, its lock expires. Save, Cancel, and unchanged Close
release it immediately when connected. Page departure attempts a best-effort
release; a crash, sleep, or network interruption can leave the lock until expiry.
These intervals are `EDIT_HEARTBEAT_SECONDS` and `EDIT_LEASE_SECONDS` in config.py.

If a lease expires, is revoked, or cannot be renewed before its deadline, the
draft stays visible and selectable for copying, with saving/typing disabled.
Copy it, Cancel, reload, and open the cell again. A late heartbeat/save cannot
reclaim a lock now held by someone else, and closing an old editor cannot
release the replacement editor's lock. Existing revision/generation checks
remain in force. Password changes/sign-out make old locks available to another
valid login on their next lock/deletion request. A server restart invalidates
open editor tokens; Cancel can release the old lock, otherwise it expires.

The **same `edit_history` row** controls an open editor and records its outcome.
It starts as `active` with the person, permanent row/column IDs, exact
label/number/column, original content, start time, last-contact time, expiry,
and a hash of an opaque per-editor lease token. Save updates that row to
`saved`, adding the new content, cell ID if newly populated, and finish time,
in the same transaction as the content write. Close without changes becomes
`unchanged`; Cancel becomes `cancelled`; abandonment becomes `expired`; a
revoked login becomes `revoked`. These states never masquerade as saved changes.
Creation, deletion, and local writes remain completed history events.

The normal history command lists actual changes, newest completion first.
Include editing activity, cancellations, and expiry with:

```bash
.venv/bin/python history.py data/collections/COLLECTION-ID.sqlite3 --sessions
.venv/bin/python history.py data/collections/COLLECTION-ID.sqlite3 --sessions --json
```

`store.edit_history(include_sessions=True)` exposes the same lifecycle records.
Expiration is applied when needed by a lock, write, deletion, or history request;
no separate cleanup daemon is required.

**Updates from other users**

Visible collection pages check for saved changes every **five seconds**, including
pages used only for browsing. A lightweight version check fetches a new workspace
only when content changes. Cell saves, row/etymon additions and deletions, local
Trash recovery, and definition changes are included. Opening/closing an editor,
heartbeats, and other activity without a content change do not trigger refreshes.

Updates preserve the selected etymon (while it still matches), applied search,
formatted/plain display, table widths/visibility, saved row heights, scroll
positions, and unsubmitted search text/filter choices. Result counts, titles,
and previous/next links update too. If the selected etymon disappears or no
longer matches, the view selects the first remaining match or shows no results.

An open cell editor or creation/deletion/login dialog postpones refreshes. A
notice explains that changes are waiting; drafts remain intact and locks keep
renewing. Closing the editor/dialog allows the pending update. A refresh already
in flight is discarded if an editor opens or navigation changes the view before
it arrives. Browsers retry after temporary network failures and check when a
hidden tab becomes visible again. Hidden tabs pause periodic checks.

`LIVE_REFRESH_SECONDS` in config.py controls the interval (a positive integer;
restart after changing it). Change checks and background workspace GETs are
collection-scoped, public, uncached, and do not save browser preferences. Schema 7
stores `dataset.content_revision`; SQLite triggers advance it in the same
transaction as content changes, including local tools. Failed/rolled-back writes
never announce a change. No WebSocket service or separate background worker is
needed.

`access_control.py` separates credentials, browser sessions, and authorization.
Credentials have role (`editor`/`admin`) and scope (`global`/`collection`) fields;
the **global editor** and **global administrator** grants are implemented.
Collection-specific policies remain future work in the authorization layer. There are no
personal accounts or name-uniqueness rules; names are self-declared.
Hashing uses [Werkzeug's password helpers](https://werkzeug.palletsprojects.com/en/stable/utils/#werkzeug.security.generate_password_hash),
and cookie lifetime follows [Flask's browser-session settings](https://flask.palletsprojects.com/en/stable/web-security/#set-cookie-options).

Single-database mode remains available for local tools and explicit exports:

```bash
# Import into a fresh file, or reopen it if already initialized.
.venv/bin/python main.py "db/my workbook.xlsx" --database db/new-research.sqlite3

# The workbook is no longer needed after import, including for export.
.venv/bin/python main.py --database data/collections/COLLECTION-ID.sqlite3
.venv/bin/python main.py --database data/collections/COLLECTION-ID.sqlite3 --export
.venv/bin/python main.py --database data/collections/COLLECTION-ID.sqlite3 --export --export-dir exports
```

Explicit workbook mode without `--database` uses a sidecar named
`<workbook filename>[.<sheet-name hash>].sqlite3`. Existing initialized databases
win over Excel: restart never reimports a changed workbook. Use a new path to
import another version. Relative CLI paths resolve from the working directory.
Use `.venv/bin/python main.py --help` for all options without opening a database.
Python callers can use `create_app(catalog_path='data/catalog.sqlite3')` or
`create_app(workbook, sheet_name='Sheet1', database_path='db/new-research.sqlite3')`.

**Export Excel** in the page header opens a collection picker. Only the current
collection is checked by default, each time it opens. Select collections and
choose **Download Excel**; Cancel/Escape leaves the page unchanged. Close or
cancel an open editor first. Browsing and downloads remain public, and a plain
HTML selection page works without JavaScript.

With **one collection**, exports contain **the entire original workbook, with
that collection's sheet updated**, regardless of the current search. An unedited
single-collection export retains the exact original workbook bytes.

With **multiple collections**, export creates one `.xlsx` containing exactly one
worksheet per selected collection, in catalog order. Worksheet tabs use collection
names, replacing Excel's forbidden characters and shortening/deduplicating names
where needed; cell text and labels stay exact. Each sheet includes all saved
content, formatting, additions, and recoverable deletions as reflected by normal
export. Row/column dimensions, rich text/whitespace, fills, comments, charts,
tables, and worksheet relationships are retained. Source theme/indexed colors
are resolved so separate collections keep their colors. Source workbooks are
never modified.

Self-references follow the new tab names. References to another selected sheet
from the same original workbook follow its new name too; references to omitted
sheets become `#REF!`. Defined names are scoped to their collection sheet.
Combined export does not merge workbook macros. Workbooks with external-workbook
links or workbook-level cell metadata require separate single-collection exports;
the picker shows an error rather than producing a broken combined workbook.

Combined files go to `exports/combined/` beside the catalog (or under
`--export-dir`), named `Parallel_Words_YYYY-MM-DD_HH-MM-SS_microseconds+offset.xlsx`.
Single-collection files keep the paths and names below. In catalog mode, files go to `exports/<collection-id>/` beside the catalog;
`--export-dir` changes that root while retaining the collection subdirectory.
Single-database mode uses `exports/` beside the database (or `--export-dir`). Files are named
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

store = LexiconDB('data/collections/COLLECTION-ID.sqlite3')  # Open an initialized database.
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
unrelated parts instead. Personal accounts and revision revert remain future work.

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

Recovery is available in **Admin → Trash**. Local administrator commands remain
available for access to the database file on the server:

```bash
.venv/bin/python trash.py data/collections/COLLECTION-ID.sqlite3 list
.venv/bin/python trash.py data/collections/COLLECTION-ID.sqlite3 restore 12  # Use the listed Trash ID.
```

Recovery restores the entire Trash entry with its existing IDs and saved
formatting. It works while the server is running; open browsers update automatically.
If a row was deleted separately before deleting its etymon, restore the etymon
first, then the row's separate entry. Restored entries are marked with a UTC
recovery time and omitted from the pending Trash list. Editors opened before
deletion/recovery must reload before saving. Older database formats require a
fresh workbook import; they are never upgraded in place.
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
formatted/plaintext preference separately per collection. Clear returns to the full collection.

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

New collections seed their row type defaults from `ROW_BACKGROUND_COLORS` in
`config.py`: etymons blue (`#D9E2F3`),
basic senses orange (`#F7CAAC`), semantic extensions yellow (`#FEF2CB`), and
specialized senses green (`#B7E1CD`), sampled from the existing workbook.
The type's color covers the label, number, and every content/empty cell in the
browser and Excel export. The mapping uses the four canonical labels; imported
label spelling and spacing are retained when selecting a type's color.
Seed values accept `#RGB` or `#RRGGBB`. Changes to `config.py` affect newly
initialized collections. Existing collections use their stored
`row_types.default_background` values for future rows. Created rows retain
their saved colors, and imported rows keep their original fills.

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

The browser remembers column widths and visibility for each collection, and row
heights for each etymon. **Reset layout** clears those display preferences for
the current collection. These layout controls do not change cell contents.

**Inline cell editing**

The app starts in **Search mode**, where cells are read-only. Click **Edit mode**
in the header to enable editing. Search controls and filters remain available
in both modes, and switching mode retains the current search and selection.
The choice is remembered for the current browser and collection.
Close or cancel an open editor before changing mode. Entering Edit mode requires
the global edit login; the server checks authentication on every content write.

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
the selected etymon. The database's addable row types are offered, initially the three non-etymon categories: basic senses, semantic
extensions, and specialized senses. Existing label spelling/spacing is reused.
The new label number is one greater than the largest number for that row type in
that etymon. Existing entries keep their numbers.

**Add etymon** in the header creates the next etymon number across the whole
collection, with an etymon row numbered 1. Both commands open a dialog requiring
initial text in the collection's configured column (**French** by default), prefilled with `[To be added]` and selected for easy
replacement. Keep it or enter your own text. **Create** commits the new entry to SQLite; **Cancel**
or Escape discards the dialog without creating anything. Initial text can have
multiple lines; use Quill afterward to add rich formatting. The display updates
and scrolls to the new row, bringing that initial-text cell into view and focusing it.
A new etymon becomes selected, with
its title, count, and navigation updated; creating it clears prior search filters.

Initial text is required so new entries survive Excel export/reimport without
hidden placeholders or auxiliary sheets. If all content is subsequently cleared
from a row, SQLite retains it, but the Excel importer still skips empty rows.
Older schema versions require a new collection and workbook reimport.

Simultaneous edits to different cells are accepted. A stale save to a cell
already changed by someone else is rejected and keeps the draft open; copy
the draft before cancelling and reloading. Editor tokens also expire when
the server restarts. There are no personal user accounts; the shared global edit password grants
write access and the self-declared name supplies attribution. CSRF and revision
checks remain additional protections.

The pinned htmx and Tabulator files are bundled under `static/vendor`, including
their licenses, so no CDN connection or frontend build step is required. A
standard HTML table remains available if the interactive grid cannot load.

Result titles use the first line of the etymon entry, before grammatical notes,
following the database's `title_priority` order: initially French, then Romanian,
Italian, Spanish, Portuguese, and Catalan.
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
node --check static/i18n.js
node --check static/admin.js
node --check static/app.js
node --check static/cell_editor.js
node --check static/scrollbars.js
node tests/test_scrollbars.js
node tests/test_i18n.js
```

Node is optional for JavaScript checks; serving the application needs no Node
or npm. Latest verification results are recorded in HANDOFF.md. The checks include
Python tests, six Node scrollbar tests, JavaScript syntax checks, and Chromium
editor, collection, authentication, lock, live-update, and admin browser suites. Tests cover independent collections, explicit
request/token scope, per-collection browser preferences, definition-driven
behavior, imports, editing conflicts, rich text, Trash, and full Excel export.
An export regression exercises a 1,200-row worksheet.

Some legacy tests use the committed `db/example.xlsx` fixture. If your working
copy omits that file, run the suite in a temporary checkout with the fixture
restored there; do not replace your working workbook or database.

Optional browser regressions use temporary databases and loopback servers.
With Playwright and Chromium installed, run:

```bash
node tests/test_cell_editor_browser.js
node tests/test_collections_browser.js
node tests/test_authentication_browser.js
node tests/test_edit_sessions_browser.js
node tests/test_localization_browser.js
node tests/test_collection_names_browser.js
```

Set `NODE_PATH` and `PLAYWRIGHT_BROWSERS_PATH` if installed outside the project.
These scripts never connect to a deployed server. This milestone has not been
deployed remotely by this work.

**Project files**

| File | Purpose |
| --- | --- |
| `main.py` | Flask factory, collection routes, browser preferences, grid payloads, Excel download |
| `collection_catalog.py` | Collection registry, separate databases, scoped browser preferences |
| `manage_collections.py` | Local create/import/register/list commands |
| `access_control.py` | Scoped credentials, revocable browser logins, authorization policy |
| `manage_access.py` | Local hidden-prompt setup/reset of global editor/admin passwords |
| `admin.py` | Protected HTML administration routes and independent administrator login |
| `admin_data.py` | Collection-scoped Trash/history previews, SQL filters/pagination, active editors |
| `admin_imports.py` | Private expiring uploads, bounded archive/XML validation, worksheet selection |
| `templates/admin/`, `static/admin.css` | Plain HTML administration pages and styling |
| `MANUAL_TESTING.md` | 84 user acceptance tasks and isolated test setup |
| `ADMIN_DESIGN.md` | Administration access rules, pages, routes, and implementation notes |
| `history.py` | Local attribution/history inspection, including before/after JSON |
| `lexicon_db.py` | SQLite schema, first import, SQL searches, atomic edits, export snapshots |
| `excel_export.py` | Single/combined timestamped workbook exports and explicit existing-sheet overwrite |
| `excel_merge.py` | Combines selected worksheet packages, styles, related parts, and references |
| `excel_rows.py` | Excel row insertion/removal, inherited labels, and reference adjustments |
| `cell_editing.py` | Validates Quill text operations and renders safe formatted HTML |
| `config.py` | Highlight color, language default, allowed hosts, secure cookies, and request limits |
| `translations.json` | Editable Romanian and English interface text; preserve message keys/placeholders |
| `i18n.py` | Server translation lookup, browser language preference, localized HTTP errors |
| `static/i18n.js` | Browser translation lookup, localized validation, request language headers |
| `static/admin.js` | Optional worksheet-based import name suggestions |
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

Quill and new rows/etymons save to SQLite with edit attribution. Collection-specific access policies and revision revert remain future work.
