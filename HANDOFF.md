# XLDB development handoff

Updated 2026-11-07 for automatic updates across browsing/editing sessions.
Workspace: `/home/hartular/Lingv/XLDB`. User-facing name: **Parallel Words**.
Read `README.md` first, and `DEPLOYMENT.md` before deployment work.

**Copy into the next chat**

> Continue XLDB in `/home/hartular/Lingv/XLDB`. Read README.md and HANDOFF.md
> first; read DEPLOYMENT.md before deployment work. The app is branded Parallel
> Words and uses Flask + htmx + Tabulator + Quill, served by Waitress.
> A catalog lists collections; each has a separate SQLite file, workbook
> template, column/row definitions, content, and recoverable Trash. Collection
> URLs and edit/delete tokens carry collection identity. The header selects a
> collection. Local administration uses manage_collections.py create (optionally
> --workbook and --sheet), register, and list. main.py defaults to
> data/catalog.sqlite3; --catalog selects another catalog. --database retains
> single-file operation/export. Schemas 4/5/6 upgrade to schema 7 without reimport;
> versions 1–3 still require reimport into a fresh collection.
> Column names/order, title priority, initial-entry column, row type names/order,
> marker roles, addability, and default colors are stored in each collection DB.
> Imported text, rich formatting, and exact label spelling/spacing must survive.
> Search supports multiple filters and ignores case/diacritics. Search controls
> stay visible in Edit mode. Double-click opens Quill; Close/Ctrl+Enter saves,
> Cancel/Escape discards. Typography offers font size and whole-cell spacing.
> The editor suppresses language suggestions and preserves table scroll position.
> Add row/Add etymon ask for initial text in the configured column (French by
> default), prefilled with selected [To be added]. New rows scroll into view.
> Delete row/Delete etymon require typing DELETE and move items to Trash.
> Local admins recover with trash.py DATABASE list/restore ID. Full-workbook
> timestamped Excel export updates only the collection's selected sheet, keeping
> other sheets and unrelated workbook parts. The source workbook is untouched.
> Browsing and export are public. Edit mode requires a self-declared name and
> shared global edit password in a Who is editing? dialog. manage_access.py
> set-edit-password configures it with hidden prompts; no password means no edits.
> Access data defaults to access.sqlite3 beside the catalog; --auth-database
> overrides it. Global browser-session login covers all collections/tabs, retains
> login in Search mode, and offers Change editor/Sign out. Every content write
> checks authorization. Password resets and Sign out revoke grants; stale drafts
> cannot be credited to a replacement editor. Per-collection edit_history records
> UTC times, names, permanent targets, and before/after snapshots transactionally.
> history.py DATABASE [--etymon N] [--json] reads it locally. Credentials have
> role/scope fields for future administrator and per-collection passwords; only
> global edit access is implemented. Quill opening acquires an exclusive cell
> lease. Other editors/tabs cannot edit that cell or delete its row/etymon;
> denials name the owner. Other cells in the same row/etymon show inline notices.
> Heartbeats every 30 seconds keep the lock even without typing; five minutes
> without contact expires it. Close/Cancel release it. Lost locks preserve a
> selectable draft, disabling typing/save. One edit_history row starts active
> and ends saved/cancelled/unchanged/expired/revoked; actual saves update the
> original record atomically with content. history.py --sessions includes activity.
> Active locks are enforced by a partial unique index and SQLite transactions.
> Visible tabs check committed content versions every five seconds, refreshing
> content/navigation without a reload and preserving layout, scroll, and searches.
> Open editors/dialogs postpone updates with a notice; drafts and locks survive.
> Schema 7 adds dataset.content_revision and transactional content-table triggers.
> LIVE_REFRESH_SECONDS controls polling. This work has not been deployed remotely.
> Inspect Git status and preserve
> existing changes; no implementation request is pending until I provide one.

**Automatic content refresh milestone (2026-11-07)**

User approved five-second lightweight version checks and automatic workspace
refreshes, deferred while editing. `LIVE_REFRESH_SECONDS` is validated as a
positive integer. Public scoped GET /changes returns only a committed version
marker with no-store. Payload includes content_version, refresh_ms, urls.changes.
Unscoped /changes is 404 in catalog mode. All existing authentication/CSRF/lease
rules for writes remain enforced.

Schema 7 upgrades normalized 4/5/6 files additively. dataset.content_revision
starts at zero on upgrade; triggers on cells, row_metadata, etymons,
column_definitions, row_types, and dataset.initial_column_id advance it within
the content transaction. Activity/history/heartbeat changes are excluded. This
also handles CLI recovery and direct definition administration while serving.
Versions combine collection UUID and counter, persist across reopen, and are
read from the same transaction as rendered content. Do not replace this with
MAX(edit_history.id): an earlier opened editor can complete after a newer one.

Visible browsers poll the version, fetching an htmx workspace only on change.
Hidden tabs skip checks; visibility/online events check immediately. Requests
are bounded by ten-second timeouts and retry automatically. `live=1` workspace
GETs use explicit applied criteria/selection/plaintext/edit-mode from this tab,
with detached preferences, preventing background requests from overwriting a
same-profile tab's preferences. Missing/deleted selected etymons fall back to the
first remaining search match or no results. Filter definitions removed since the
last view are dropped from the background search rather than returning 400.

Frontend checks editorOpening/editing, pending mutations/navigation/renders,
and all open dialogs before swapping. A generation and workspace reference
also discard stale GET responses after navigation, including an editor opened
while the response was in flight. htmx.swap preserves the grid; rendering restores
current column widths/visibility explicitly (Tabulator redraw can reset widths),
saved row heights, both grid offsets, sidebar scroll and window position. Applied
search/display and selection survive; search draft inputs/open filter menus are
left alone. A separate live-update notice reports deferred changes/offline retries
without overwriting editor/network conflict messages. Closing a draft/dialog
schedules a pending check; saving already fetches fresh workspace data. Empty
collections continue polling and notice later creation/recovery.

Concurrent target/cell reads now use the store connection lock as well; polling
exposed an unsynchronized cell_key lookup that could return SQLite API errors
under concurrent heartbeat/save/check requests. A cross-thread regression test
ensures these reads wait for another request’s transaction.

No deployment, commit, or push was performed; user workbooks and databases were
not changed by development work. Tests use temporary files/servers.

**Cell editing lifecycle milestone (2026-11-07)**

The user approved named same-cell exclusion, row/etymon deletion protection,
non-blocking same-row/etymon notices, and reuse of the locking record for saved
history. A contact is a background heartbeat, not typing/mouse activity.
Defaults are EDIT_HEARTBEAT_SECONDS=30 and EDIT_LEASE_SECONDS=300. These require
positive integers with heartbeat shorter than lease. An editor can stay open
indefinitely while contacts succeed; offline/sleep/crash leads to expiry.

Schema 6 extends edit_history with status, started_at, last_seen_at, expires_at,
finished_at, and lease_hash. Existing schema 4/5 records upgrade without
reimport, retaining their IDs/content/history and backfilling finished_at from
occurred_at for historical completed events. Unknown historical start times
remain NULL. Old schemas 1–3 are still rejected unchanged.

`begin_cell_edit` starts one active save_cell record with original content and
an opaque per-editor lease. A partial unique index on row_id,column_id WHERE
status='active' enforces one holder across connections. Save checks the original
revision/generation and owner/lease, writes the cell, and updates that exact
history ID to saved with new content/finish time. It never inserts a duplicate
save history event. Cancel/unchanged Close complete the record without changing
cell content, formatting, fill, revision, or spacing. Expired/revoked records
remain activity, not changes. Local Python writes still make instantaneous
completed events and cannot overwrite a currently leased cell.

Expired/revoked leases are reaped before acquisitions/writes/deletions/history
reads. AccessControl.session_active checks stored identity hashes so a revoked
login cannot block another valid user. Acquisition and deletion run under
BEGIN IMMEDIATE and recheck current state, so racing requests cannot both win.
Even the same logged-in browser needs a separate lease per tab/editor; names
are never ownership keys. A stale lease cannot save, renew, or release a newer
holder. Deletion checks stable row IDs (history labels remain exact snapshots).

Scoped POST /cell/start, /cell/heartbeat, /cell/finish routes require CSRF/login.
Start/save require Edit mode; heartbeat/cancel may finish an existing editor
if another tab switches the shared preference to Search. Save requires both the
original signed target token and acquired lease. Heartbeat retains the signed
identity/restart guard; finish can release after a process restart. No public
history or lock-override endpoint is exposed. Payload URLs are edit_start,
edit_heartbeat, edit_finish in addition to the prior scoped actions.

Frontend acquisition precedes Quill creation and blocks navigation while pending.
Warnings name peers editing other cells in the row/etymon and refresh on contacts.
Timers use monotonic elapsed time plus a conservative server lease duration,
avoiding client/server clock skew. Visibility resume contacts the server; an
expired/revoked lease freezes the draft but keeps it visible/selectable. Save
is disabled, Cancel stays available. Network failure retains the draft and
retries contacts until the deadline; it never silently reacquires a lost lock.
Pagehide requests a best-effort cancellation, with expiry as fallback.
Escape cancels even when disabling Quill has moved focus to the document body. Close/
Cancel wait for release (up to five seconds if offline), then restore scrolling.

`history.py` and `store.edit_history()` show saved changes by completion time.
`--sessions` / include_sessions=True includes active/cancelled/unchanged/expired/
revoked records, with full times/snapshots in JSON. No-op Close now records an
unchanged session, not a changed cell. Older tests/helpers acquire a lease before
HTTP saves; they do not bypass locking. Tests use temporary databases/workbooks;
no existing user data was opened or deployed by this work.

**Authentication milestone (2026-11-07)**

The user approved authentication and attribution first, with live editing
coordination deferred. A login lasts for the browser session, across collections,
with no remember-me option. Names are self-declared; no personal accounts or
uniqueness rules are intended. Switching to Search mode retains authentication.

Set the password locally with `.venv/bin/python manage_access.py set-edit-password`.
For custom paths use `--database PATH` on that command and `--auth-database PATH`
on main.py. The defaults align at access.sqlite3 beside the catalog (or single
collection DB). Until configured, all content writes are denied. Passwords are
hidden prompts and stored as Werkzeug scrypt hashes; never ask the user to send
a password in chat, put it in source, or pass it as a shell argument. New access
files are mode 0600. Existing user files were not opened/migrated by development
checks; tests use temporary files. No remote deployment, commit, or push occurred.

**Collection milestone (2026-11-06)**

The user chose one SQLite file per collection instead of multiple sets of tables
inside one file, and asked to put column and row names in the database before
adding access control. They explicitly allowed workbook reimport and a fresh
normalized schema. Versions 1–3 still require workbook reimport; the subsequent
authentication milestone adds an additive schema-4-to-5 history migration. No source workbook or existing user database was modified by this
implementation. No commit, push, or remote deployment was performed.

Default commands (from the project directory):

```bash
.venv/bin/python manage_collections.py create "Gastronomy" --workbook db/exemple.xlsx --sheet "Sheet1"
.venv/bin/python manage_collections.py create "Fashion"
.venv/bin/python manage_collections.py list
.venv/bin/python manage_access.py set-edit-password
.venv/bin/python main.py
```

Use the actual worksheet name or omit `--sheet` for the first worksheet. Both
commands accept `--catalog PATH`. Catalogs store absolute collection paths.
Moving backups to a different directory requires updating these paths or
registering the collection files in a new catalog. Browser administration,
uploads, collection deletion/renaming, and definition-editing UI are not part
of this step.

**Storage and identity**

`collection_catalog.py` owns a schema-1 catalog:

- `collections`: collection UUID, display name, absolute DB path, UTC creation time.
- `browser_preferences`: browser ID + collection ID -> JSON search, selected
  etymon, plaintext, and edit-mode preferences.
- `catalog_metadata`: catalog schema version.

New collection files live under `collections/<UUID>.sqlite3` beside the catalog.
They can start empty or import one sheet, retaining the entire source workbook.
An empty collection has a real header-only Excel template and can immediately
add/export its first etymon. Empty catalogs show an explanatory landing page.
Registration accepts normalized schema-4/5/6/7 collections (upgrading 4/5/6) and rejects duplicate
names/IDs/paths. Unknown collection URLs return 404; missing collection files
return an error and never create a fallback database.

`lexicon_db.py` owns a schema-7 collection:

- `dataset`: UUID, schema version, source labels/path, sheet name, full workbook
  bytes, `initial_column_id` (French by default), and `content_revision`.
- `column_definitions`: stable integer ID, exact name, display order, nullable
  physical Excel column, original heading (`source_name`), nullable title priority.
- `row_types`: stable ID, default label, display order, etymon-marker flag,
  addability, default background. Exactly one marker is seeded. Unknown source
  labels get their own non-addable types. Spelling variants of standard types
  share a type, while each actual row retains its exact original label.
- `etymons`: stable number and nullable original marker row, including marker-only
  sections without content. Numbers remain reserved after deletion.
- `row_metadata`: stable ID, etymon/type IDs, exact label/number, sheet/source/style
  positions, saved fill, Trash reference, and edit generation.
- `cells`: stable ID, row/column IDs, HTML, plaintext, normalized search text,
  fill, revision, and whole-cell line height.
- `cell_records`: joined read view exposing the familiar DataFrame field names.
- `trash`: deletion kind, etymon, exact label/number, title, UTC deletion/recovery times.
- `edit_history`: action, UTC timestamp, server-resolved editor name and hashed
  session ID, etymon/row/column/cell IDs, exact label/number/column name, Trash ID,
  and before/after JSON content snapshots. Saves, additions, deletions, and local
  recovery insert their history in the same write transaction. Failed writes
  produce no saved change; failed history completion rolls back the content write.
  Cell editors reuse one row from active through completion, with lifecycle
  status, start/last-contact/expiry/finish timestamps, and a hashed lease token.

Foreign keys are enabled. Runtime behavior reads the definitions, including
ordering, entry-title priority, initial-text column, row defaults, and protection
of marker rows. Renaming a column definition updates its Excel heading without
changing cell IDs. Changing a row type's default label affects future rows;
original row labels remain exact. Initial physical Excel layout is preserved;
changing display order changes the site order only. Missing standard columns
remain visible as empty definitions until content needs an Excel column.

`ROW_BACKGROUND_COLORS` in config.py seeds new collections only. Existing
collections use their persisted row type defaults; existing rows keep saved
fills. Defaults sampled from the original workbook: marker #D9E2F3, basic
#F7CAAC, extensions #FEF2CB, specialized #B7E1CD.

SQL searches use literal `instr` and Python Unicode uppercase normalization;
there is no SQL wildcard interpretation. Only the selected etymon becomes a
detached DataFrame for `get_etimon`. `to_dataframe()` is a snapshot, not writable
live storage. Its attrs carry definitions, type mappings, row/column positions,
label fills, empty-cell backgrounds, and saved line spacing. Raw DataFrame helper
calls still have default constant ordering for compatibility.

**Requests, browser state, and editing**

Catalog requests use `/collections/<UUID>/` plus `/mode`, `/cell`, `/rows`,
`/etymons`, `/trash`, `/export` beneath that prefix. Unscoped mutation/export
routes return 404 in catalog mode. Root redirects to the first collection.
`g.lexicon_store` selects storage from the explicit URL on every request.
Cell tokens carry collection UUID, row ID, column ID, revision, generation,
and the identity of the login that opened the draft;
delete tokens also carry collection identity. Cross-collection tokens are
rejected even when integer IDs happen to coincide. CSRF is browser-session-bound.

The catalog holds browser preferences separately per collection. The signed
cookie holds opaque browser/login identifiers and a CSRF token, not an ever-growing map of
collection preferences. A stable `FLASK_SECRET_KEY` preserves these identities
across restart. Different tabs can work in different collections; tabs in the
same browser profile showing the same collection still share saved preferences.
Layout preferences live in localStorage and use collection UUID keys.

The collection selector performs full navigation so bookmarks, refresh, and
browser Back retain the correct collection URL. Within a collection, htmx keeps
its existing fragment updates. The frontend receives scoped URLs, filter choices,
and initial column from the server. An open editor or pending write blocks
switching. Header links, forms, filters, labels, menus, and export targets stay
consistent with the current payload.

Quill saves validated Delta operations through server-generated HTML, never
arbitrary supplied HTML. No-op Close preserves original HTML. Rich formatting,
whitespace, font sizes, whole-cell line spacing, and imported fills persist.
The editor starts with the cell's computed line height, immediately focuses the
contents, and suppresses spellcheck/autocomplete/autocorrection/capitalization/
writing suggestions. Empty cells retain their imported/inherited fill after
saving. Close/Cancel preserve both scroll offsets; added rows scroll into view.
Search controls remain visible in both Search and Edit modes.

Adding rows uses the DB type's addability/default fill and next reserved number
within the etymon/type. Initial text is required and defaults to `[To be added]`.
Adding an etymon uses the DB marker type and next reserved global number.
Deletion asks “Are you really, really sure?” and requires DELETE. Content,
formatting, revisions, IDs, and positions remain stored for local recovery.
Local commands: `trash.py DATABASE list` and `trash.py DATABASE restore ID`.
Restore the containing etymon before a separately trashed row. Browsers notice
local recovery through their next background change check.

Optimistic conflicts prevent stale saves/deletes. Every content mutation now
requires a global editor grant as well as Edit mode and CSRF. There are no
personal accounts or per-collection policies yet. Use one application process: editor-token signing
includes a process-specific random salt. Restart invalidates open editor tokens
independently of the stable cookie secret.

**Access storage and UI**

`access_control.py` owns a separate schema-1 access database with:

- `credentials`: password hash, revision, role (`editor`/`admin`), scope type
  (`global`/`collection`), scope ID, and UTC update time. Only the global editor
  credential is accepted by the current policy; future roles/scopes fail closed.
- `editor_sessions`: SHA-256 of a random bearer token, credential ID/revision,
  self-declared name, UTC creation time. The raw token stays in Flask's signed
  HttpOnly/SameSite cookie, never in history, HTML payloads, or localStorage.
- `access_metadata`: storage version.

Credential setup/reset deletes existing grants. Every request resolves its grant
against the current DB/revision; explicit Sign out revokes the grant on the server.
Cookie lifetime is a browser session (`session.permanent=False`), with no Expires/
Max-Age. Browser session restoration can restore cookies; Sign out explicitly
ends access even if an old cookie is restored. Stable FLASK_SECRET_KEY + access
DB retain a live browser login over server restart, while editor tokens expire.
Abandoned auth records are not editing leases and do not block anyone.

`POST /auth/login` and `/auth/logout` require the browser CSRF token. Login uses
validated names (1–120 chars, no control characters) and bounded passwords;
failed attempts are limited to ten per client IP/five minutes/process. Do not
trust forwarded addresses beyond the existing explicit Waitress proxy settings.
`AccessControl.can_edit` is the central policy hook for future admin/collection
permissions. Test apps use in-memory access storage unless explicitly configured;
there is no authentication bypass in testing mode. Regression clients sign in
through the real endpoint using `tests/auth_helpers.py`.

The frontend reads an `auth` payload alongside scoped collection URLs. Edit mode
opens the login dialog when needed; it is enabled only after successful login.
Change editor replaces the grant only on successful submission; Cancel retains
the existing identity. Sign out/Change editor require closing any open draft.
Other tabs can retain stale controls but cannot save under a revoked/replacement
grant. Rejected drafts stay open for copying. The header uses textContent for
names. Draft/delete tokens bind the grant's hash so changing identity cannot
misattribute a draft opened earlier. Add row/etymon requests also require the
opening grant hash in X-Editor-Session; stale creation dialogs cannot be credited
to the new editor.

History is private local administration: `history.py DATABASE [--etymon N]
[--limit N] [--json]` or `store.edit_history()`. Local Python/CLI writes without
an HTTP actor are named Local administrator. Imports/earlier edits are not
backfilled with invented authors. There is no public history/revert endpoint;
Excel remains content-only. Password hashes and login records are never exported.

**Excel contracts**

Source imports still require row 1 headings, column A labels, and section labels
beginning `ETIMON/`; blanks inherit the preceding label. Alternate workbook
layout/marker mapping is future work, even though runtime marker roles are now
stored in the DB. Preserve exact imported text, label names, spacing, formatting,
and source files. `to_replace.py` is never applied automatically.

`excel_export.py` snapshots SQLite atomically, then patches the original archive.
No-op export returns original workbook bytes exactly. Normal exports retain the
whole workbook, including unrelated ZIP parts, extra sheets, and macros. Inserted
and deleted rows adjust formulas/ranges/layout references; original label-only
marker positions determine section boundaries. Newly created cells receive full
border outlines even when a donor row has missing borders. Removed references
become #REF!, ranges shrink, and rows are physically omitted from export.

Edited text is inline Excel rich text: explicit fonts/sizes/colors/bold/italic/
underline/strike/script, whitespace preserved on all runs, including newline-only
runs. Unformatted edited text uses the editor default, 9 pt Segoe UI and #253b35,
rather than inheriting the original Excel font. Leading '=' entered in Quill
remains text; original formulas remain formulas. CSS line spacing and per-run
background highlights have no exact Excel equivalent; row height makes room and
SQLite retains the app settings. Prior Excel repair warnings were fixed and the
user confirmed exports work. Avoid whole-workbook reserialization in normal
export and avoid deepcopy of XML trees with parent links (past RecursionError).

Catalog exports go to `exports/<UUID>/` beside the catalog or beneath
`--export-dir`. Single-file mode uses `exports/` beside its DB. Filenames use
Europe/Bucharest timestamps with microseconds and UTC offset; collisions never
overwrite existing exports. `main.py --database DATABASE --export` exports
without serving. `overwrite_sheet(store,path,sheet_name=...)` is explicit Python
functionality, never used by the website; unsupported advanced workbook features
may be affected by that helper's openpyxl conversion.

**Verification and environment**

Latest Python verification: 183 tests passed in a temporary checkout containing the
committed `db/example.xlsx` fixture. The user removed/renamed that fixture in
the live workspace; leave it and `db/research.sqlite3` untouched. The temporary
checkout used for this milestone is `/tmp/xldb-creation-tests-u62wko89`, with a
symlink to the project's `.venv`. Copy current source/tests there before checks.
Self-contained `tests/test_collections.py` runs directly in the workspace.
Six Node scrollbar tests, JavaScript syntax checks, sixteen Chromium editor
groups, five Chromium collection groups, six Chromium authentication groups,
six Chromium lease groups, and eight Chromium live-update groups passed.
Browser checks include
simultaneous edits from two tabs in different collections, scoped search/forms/
export/Trash, renamed headings and row types, initial-column metadata, empty
collection creation, editor navigation guards, and browser Back. Optional suites
are `tests/test_cell_editor_browser.js`, `tests/test_collections_browser.js`,
`tests/test_authentication_browser.js`, `tests/test_edit_sessions_browser.js`,
and `tests/test_live_updates_browser.js` (eight automatic-refresh groups).
Playwright is outside the project at `/tmp/xldb-browser/node_modules`; its
browser installation is `/tmp/xldb-browser/browsers`. Use NODE_PATH and
PLAYWRIGHT_BROWSERS_PATH accordingly. Browser servers/databases are temporary.

The user reports remote editing works and previously diagnosed HTTP download
warnings in Chrome. The remote machine uses Ubuntu 24.04 ARM64 and Nginx;
capibara.hopto.org already has a Let's Encrypt certificate on 443. Port 8080 was
plain Waitress HTTP, so https://...:8080 cannot work without a TLS listener.
Do not replace an existing site's configuration without checking it. This
milestone's catalog/schema/authentication changes have only been tested locally
and have not been installed on that machine. Existing schema-4/5/6 collections upgrade
without reimport; schemas 1–3 still require a fresh collection import. Deploy the
access DB/password setup as documented, with its directory writable by the service.

**Next work, when requested**

Authentication, attribution, live cell coordination, and automatic content
refresh across browsers are implemented. Global
administrator passwords, collection-specific passwords, and browser administration/
history/revert UI remain future work. Do not add these without a new request.
The team prefers shared passwords and self-declared names over personal accounts.
