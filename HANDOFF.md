# XLDB development handoff

Updated 2026-11-13 after diacritic/regex search; user acceptance testing is incomplete.
Workspace: `/home/hartular/Lingv/XLDB`. User-facing name: **Parallel Words**.
Read `README.md` first, and `DEPLOYMENT.md` before deployment work.

**Current acceptance status**

MANUAL_TESTING.md currently marks **T01–T16 and T81–T82 complete**; preserve
these user checkbox marks. Details (browser/date/environment) have not been
entered in its result table. The other **80 of 98 tasks remain unchecked and
pending**, including all administrator tasks T60–T80, language tasks T85–T90,
collection-name tasks T91–T93, and search-mode tasks T94–T98. Agent-run automated tests and screenshot reviews do not
complete user acceptance tasks.

The current full Python verification passed 270 tests, including 18 new search tests.
A final focused search/highlighting/localization pass passed 34 tests.
Scrollbar and JavaScript syntax checks also passed. Browser verification details
are recorded in the milestones below. Real Excel
desktop checks, the full manual two-user workflows, and the latest remote
HTTPS/proxy/cookie/admin checks remain for the user's acceptance pass. Earlier
informal confirmations of editing/export apply to earlier checks, not this full
checklist. The user's latest deployment and admin-password setup are unconfirmed;
the agent has not deployed remotely or set real credentials.

No new implementation task is pending. On continuation, preserve the working
tree and use the user's next instructions or reported checklist task IDs to
guide work. The checklist includes a short general pass and an admin-focused
first pass, plus a place to record actual outcomes.

**Copy into the next chat**

> Continue XLDB in `/home/hartular/Lingv/XLDB`. Read README.md and HANDOFF.md
> first; read DEPLOYMENT.md before deployment work. The app is branded Parallel
> Words and uses Flask + htmx + Tabulator + Quill, served by Waitress.
> MANUAL_TESTING.md marks T01–T16 and T81–T82 complete; preserve those user marks.
> The other 80 of 98 tasks, including admin T60–T80, language T85–T90, naming
> T91–T93, and search T94–T98, remain pending. Automated Python checks passed (270 tests), along with browser/scrollbar/JS checks recorded
> below; these are not user manual acceptance results. Do not check off
> tasks or assume the latest build is verified in the user's Excel/remote setup.
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
> Search ignores case, with independent Match diacritics and Regex checkboxes,
> both off by default. Diacritics off selects nodiacritics_plaintext and normalizes
> query literals with the shared normalizer; on selects plaintext_content. The
> submitted effective query appears in the input. SEARCH_SHOW_NOTICES defaults
> to False in config.py, hiding successful-search explanations; True restores
> them after restart. Errors always display. The short translated hint sits
> beside the two checkboxes; preserve the user's translation edits.
> Regex selection and highlights share one matcher. Ligatures are grouped before
> repetition and positive sets can expand to alternations; ambiguous negated
> ligature sets/combining marks/middle-dot contexts show translated inline errors.
> Switches survive navigation, language changes and live updates per collection.
> Background refresh preserves unsent controls; Clear resets both switches.
> regex==2026.11.9 adds Unicode timed matching; install requirements.txt after pull.
> Default cumulative regex budget is one second including highlights, configurable
> by SEARCH_REGEX_TIMEOUT_SECONDS (max five seconds). Invalid or slow patterns
> retain the last valid saved search. See README for supported syntax/limits.
> No database migration or new Nginx settings are needed. Search controls
> stay visible in Edit mode. Double-click opens Quill; Close/Ctrl+Enter saves,
> Cancel/Escape discards. Typography offers font size and whole-cell spacing.
> The editor suppresses language suggestions and preserves table scroll position.
> Add row/Add etymon ask for initial text in the configured column (French by
> default), prefilled with selected [To be added]. New rows scroll into view.
> Delete row/Delete etymon require typing DELETE and move items to Trash.
> Local admins recover with trash.py DATABASE list/restore ID. Full-workbook
> single-collection Excel export updates only the selected sheet, keeping
> other sheets and unrelated workbook parts. Export Excel now opens a picker
> defaulting to the current collection; multiple selections create a new .xlsx
> with one worksheet per collection, named after the collections. The source workbook is untouched.
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
> role/scope fields; separate global editor and administrator access is implemented.
> Collection-specific credentials remain future work. Quill opening acquires an exclusive cell
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
> LIVE_REFRESH_SECONDS controls polling. The agent has not deployed this work
> remotely; the user's latest deployment status is unconfirmed.
> MANUAL_TESTING.md provides 98 user acceptance tasks plus an isolated-test setup.
> /admin/ implements the approved plain-HTML design: local set-admin-password
> bootstrap/reset, independent administrator browser-session login, global password
> management, collection-scoped Trash preview/recovery, filtered history/activity,
> and active editors. It works without JavaScript; POSTs require admin CSRF, and
> restoration confirmations bind the collection/item and current form context.
> Admin → Collections creates empty collections and imports an uploaded .xlsx/.xlsm
> worksheet into a uniquely named collection. The complete workbook is retained.
> Collections Trash hides/restores whole collections without deleting files or IDs;
> names remain reserved, active cell editors block removal, and confirmation tokens
> bind the target/action/revision/login (plus content version for removal).
> Catalog schema 2 adds deletion state and create/delete/restore audit events.
> Uploads default to 25 MiB compressed/100 MiB expanded, with archive/cell/grid
> bounds; pending uploads are private, login-bound, expire after 30 minutes,
> and are cleaned on subsequent import requests. See config.py and DEPLOYMENT.md.
> Nginx needs client_max_body_size 26m for the default; no remote changes were made.
> Access schema 2 adds secret-free password-change audit metadata, preserving
> credentials/grants. Collection schema stays 7. Password changes revoke only
> their own role. The first admin password must be set locally; none was chosen
> or installed by the coding agent. See ADMIN_DESIGN.md and README.md.
> Pages now default to Romanian. Română / English in every page header saves
> a separate one-year browser preference and works without JS. translations.json
> contains editable ro/en display values under stable English message keys;
> preserve keys/placeholders, restart the server, and reload pages after editing.
> i18n.py handles server messages and cookie selection; static/i18n.js handles
> browser labels/validation and request headers. Open pages keep their language
> across another tab's preference change. Language navigation retains the current
> applied search/filters/etymon and blocks while a cell draft is open. Actual
> workbook/collection text and attribution are never translated. New-entry
> placeholder is [De completat] in Romanian, [To be added] in English; DELETE
> remains literal. CLI tools stay English. No schema change or deployment.
> Import names now default to the selected worksheet, with (1), (2), etc. to
> avoid names in active collections or Collections Trash. Optional admin.js follows
> worksheet changes while keeping custom names. The ordinary Suggest name form
> also works without JS. Admin → Collections → Rename collection changes a name
> only while there are no open cell editors in that collection; Edit mode alone
> is allowed. Signed revision-bound forms reject stale submissions. The catalog
> rename holds the collection SQLite write lock through its catalog commit,
> preserving IDs, bookmarks, files, data, history and preferences. Existing
> lifecycle_revision/collection_events support rename without a schema change.
> Public changes responses include collection_name so open tabs refresh renamed
> headings. The main header now shows a larger collection name only, without
> workbook filename/source suffixes; single-database mode uses its sheet name.
> Inspect Git status and preserve
> existing changes; no implementation request is pending until I provide one.

**Diacritic and regex search (2026-11-13)**

Implemented the approved two-switch design. Both switches default off; search
remains case-insensitive. `search_query.py` owns the effective query, normalization,
validation, Unicode regex matching, cumulative timeout, and highlight spans.
`lexicon_db.py` selects the original or normalized stored column. Literal matching
keeps its SQL path; regex rows are filtered by exact column/label choices before
matching. `df_search.py` exposes the same `diacritics`/`regex` options, preserving
its historical case-sensitive default and input-frame immutability.

Regex literals and escaped Unicode characters normalize while syntax, group
names/references, and Unicode properties remain intact. `œ+` becomes `(?:oe)+`;
`[éœx]+` becomes `(?:[ex]|oe)+`. Negated ligature classes and structurally ambiguous
normalization are rejected with editable ro/en catalog messages. Bounded patterns,
group depth, counted repetitions, range expansion, total matching time, and
highlight count prevent runaway work. Matching uses the pinned `regex` package,
Unicode full case folding, and `concurrent=True`; no per-row fresh full timeout.

The same effective matcher maps highlights back to original rich text, including
ligatures, decomposed accents, HTML entities, and formatting runs. Anchors use
the stored plaintext while preserving outer spaces in imported HTML. Zero-length
matches select cells but receive no empty marks. Matching errors show an inline
message and no partial results. Highlighting errors clear all marks and retain
complete results with a warning; neither failure replaces saved valid criteria.
The query input shows normalization only after submission. Search state includes
both switches per collection and in language/live URLs. Background refresh keeps
unsent text and checkbox state; draft navigation guards stay in place. Both
languages and ordinary HTML forms are covered. No stored workbook text, schema,
real databases, credentials, or remote installation were changed.

Verification: `tests/test_regex_search.py` adds 18 self-contained tests; its latest
focused run with the six existing highlight tests passed (24 total). Four focused
Chromium search groups passed, including plain HTML, mobile fit, language and
collection persistence, rich-text highlights, inline errors, applied-vs-unsent
live state, and draft protection. All eight existing live-update browser groups
passed. Four i18n helper tests, six scrollbar tests, and JavaScript syntax checks
passed. The full suite passed 270 tests in 153.933 seconds. A final refinement
for escaped non-ASCII literals passed the 34-test search/highlighting/localization
subset. The initial disposable full
run used the wrong historical workbook; its fixture-only failures were resolved
by restoring `e3112e5:db/example.xlsx` into the snapshot, never the live workspace.
The snapshot is `/tmp/xldb-regex-full-254pxq9q`; legacy fixture recovery now uses
Git history because the earlier temporary checkouts were removed.

Deployment: install `.venv/bin/python -m pip install -r requirements.txt` and
restart. No database or Nginx changes for this feature. Pending manual tasks
T94–T98 were added; all existing user checkbox marks were preserved (18 complete,
80 pending out of 98). Automated checks do not complete acceptance tasks.

**Search hint and optional success notices (2026-11-13)**

The user's shortened search hint now appears beside the two checkboxes, wrapping
at narrow widths. `translations.json` was preserved unchanged for this follow-up,
including the user's shorter Romanian checkbox label. `SEARCH_SHOW_NOTICES = False`
in config.py suppresses successful-search explanations in full HTML and htmx/live
payloads; changing it to True and restarting restores them. Normalized queries
still appear in the input; errors always remain visible. Existing request tests
cover the default and enabled configurations, and browser checks cover hidden
success notices and visible errors. Prior full-suite results above predate this
small follow-up. Verification passed 28 focused Python tests, four search browser
groups, and JavaScript syntax checks. Desktop and mobile screenshot review
confirmed the hint placement. No user acceptance checkbox marks were changed.

**Permanent search clear and bulk column visibility (2026-11-13)**

The query input has an always-visible × with translated Clear search text label.
It clears only query input text, emits the usual input event, and refocuses the
input, preserving filters, switches, and applied results until Search. JavaScript
reveals the custom button and suppresses the duplicate native clear; without JS,
the native search control remains available (with explicit visible opacity).
All columns / Toate coloanele is the first display-column checkbox. It shows or
hides every content column, leaving frozen identifiers visible, and tracks
individual visibility through syncColumnChooser, including saved layouts and
live updates. Opening a cell draft blocks bulk layout changes. The existing
All columns translation was reused; only Clear search text was added to the
catalog, preserving all prior edits. Manual checks T94/T98 were expanded without
changing any user checkbox marks. Verification passed 28 focused Python tests,
five Chromium search/layout groups (including bulk visibility persistence and
draft protection), four translation helper tests, six scrollbar tests, and
JavaScript syntax checks. Desktop/mobile screenshots were reviewed.

**Collection naming improvements (2026-11-09)**

The user requested worksheet-based import names, renaming blocked during editing,
and a more prominent collection name without the original workbook filename.
All three are implemented. Active editing means an open cell editor/lease;
merely selecting Edit mode does not block a rename. No unrelated changes were
made to the existing workbook moves/deletions or user checklist marks.

CollectionCatalog.suggested_name uses the trimmed selected worksheet name and
appends (1), (2), etc. until unused, including names in Collections Trash. It
limits suggestions to valid collection-name length and leaves original sheet
names untouched. Import review computes suggestions for each exact worksheet.
static/admin.js follows changes while the name is still automatic, preserving
custom names. The plain HTML action=suggest button refreshes the name without
consuming the upload. A hidden default_name also allows a plain HTML import to
follow a newly selected worksheet at submission, with fresh collision checks;
custom names and failed submissions retain their entered values. JSON is escaped
with tojson and read into a Map, supporting unusual names such as __proto__.

Admin → Collections links to GET/POST /admin/collections/<id>/rename. The form
binds collection, rename action, lifecycle revision, and administrator CSRF
context. Renaming rejects duplicates (including Trash), invalid names, stale
forms, and open cell editors. GET explains and disables the action while editing;
POST checks again. Catalog.rename expires old leases and holds the collection
write transaction through the catalog name/revision/event commit, excluding a
concurrent lease from another SQLite connection. Unchanged names are a no-op.
It preserves IDs, database paths, content, workbook metadata/template, history,
Trash and preferences. There is no new schema version or CLI command.

The main header shows the collection name at 24px on desktop / 20px on narrow
screens, with a full-name tooltip and truncation. The workbook/source label is
kept as metadata in the payload, but removed from the displayed name and its
accessibility label. Single-database mode uses the worksheet name for public,
admin, and export display. Browser titles include the collection name. The
lightweight changes response adds collection_name; the browser refreshes when
that changes even if the content revision is unchanged, following existing draft/
dialog/scroll protections. Combined export tab names follow current catalog names;
original full-workbook exports and source files remain intact.

Verification: all 252 Python tests passed in the disposable snapshot
/tmp/xldb-collection-names-check-9_mmfc0f, using only the legacy test fixture copied
there. The nine focused tests also passed directly in the workspace, covering
suggestions, plain HTML import defaults, duplicates, snapshots/preferences/audit,
identity persistence, active/expired leases, stale forms, roles/CSRF, and concurrent
SQLite lease exclusion. Three browser groups passed for plain HTML imports and
rename/live headings; JS suggestions/custom names/unusual titles; active editor
restrictions, cancellation, Romanian labels, and mobile layout. A screenshot is
/tmp/xldb-collection-name-mobile.png. Four translation helper tests, six scrollbar
tests, JS syntax checks and git diff --check passed. Broader historical browser
suites were not rerun. No deployment or real data/credential changes. New manual
T91–T93 remain unchecked; existing T01–T16 and T81–T82 checks were preserved.

**Romanian / English interface (2026-11-08)**

Romanian is the default regardless of Accept-Language. All main, export, empty,
error, and administrator pages offer an ordinary Română / English link pair.
The choice persists for one year in the HttpOnly/SameSite=Lax ui_language cookie,
with Secure following SESSION_COOKIE_SECURE. DEFAULT_UI_LANGUAGE is ro in
config.py. The validated /language/<code>?next=... endpoint permits local return
paths only; rejected hosts also receive a localized error without building URLs
through their unavailable routing adapter.

translations.json stores both display values for each stable English msgid.
Named placeholders must be retained; plain text only, escaped by templates or
assigned through textContent. Restart/reload to apply catalog edits. i18n.py
translates explicit UI messages at their source, with English outside requests
for command-line tools. Imported content, labels/headings, names, snapshot data,
and stored attribution are never run through a general replacement pass.
An entries(empty_form=...) argument localizes only the generated missing-form
caption; DB/history callers retain the English fallback. The suggested text for
a new entry follows the interface language. DELETE remains the required token.

static/i18n.js provides browser translation lookup and localized native validity
messages, clearing custom validity on input/form reset. A marked InterfaceError
keeps application messages while native network/JSON failures use a translated
fallback. app.js/cell_editor.js translate dynamic counts, notices, confirmations,
login/create/delete dialogs, Tabulator identifying headers, and Quill toolbar,
typography and generated color picker controls. Shared JSON translations are
escaped with tojson, and the executable helper stays external under the CSP.
Admin forms retain their JavaScript-independent operation. Language navigation
blocks active/opening cell editors and mutations. Main-page language links track
the current applied query/filters/display/etymon. X-Interface-Language on htmx
and fetch requests pins responses to the open page's language if another tab
changes the cookie. Cache variation includes Cookie and that header.

Romanian administrator timestamps use dd.mm.yyyy with Europe/Bucharest UTC
offsets. Actions and outcomes are translated only for display; machine values
remain unchanged in forms/queries/history. Friendly localized import errors
retain application validation messages but omit raw third-party diagnostics.
Longer controls wrap on narrow screens. Existing English regression fixtures
explicitly select en; new tests prove the real Romanian default with TESTING on.

Verification: full Python suite passed 243 tests in the disposable snapshot
/tmp/xldb-localization-check-n8jz81kq using the legacy fixture copied there only.
The ten focused localization tests also passed directly in the workspace.
Four dependency-free translation helper tests, six scrollbar tests, and
JavaScript syntax checks passed. The localization
browser suite passed all three groups: JS-disabled export/admin and remembered
choice; Romanian login/validation/network failure/grid/Quill/draft safety/mobile; htmx and
cross-tab language consistency with retained searches. One intermediate browser
run hit a navigation timeout; an earlier run exposed header overflow, which was
fixed before the passing run. A mobile screenshot is /tmp/xldb-language-ro-mobile.png.
The broader historical browser suites were not rerun for localization.
Real credentials/databases/workbooks were untouched. No remote deployment.
T85–T90 were added unchecked; T81/T82 user checkbox marks were preserved.

**Multi-collection Excel export (2026-11-08)**

The user requested multiple selected collections as worksheets in one Excel file,
with only the current collection selected by default. Export Excel now opens a
native dialog, repopulated from the current workspace each time; Download Excel
submits a normal public GET, closes the dialog, and preserves the current view.
Cancel/Escape does nothing to content. Opening/active editors and pending writes
block export; the open dialog defers automatic refreshes. Without JavaScript,
the link opens the same collection-selection form as a plain HTML page.

The existing scoped /export URL still downloads the current full workbook by
default. `?choose=1` opens options; `selection=1&collection=ID&collection=ID`
downloads explicit selections. Empty selection fails with a form error; unknown
or removed selections fail without silently omitting a collection. Catalog order
controls sheet order, and duplicate IDs cannot duplicate worksheets. One selected
collection (including another collection selected on its own) retains the
existing full-workbook/no-op byte-for-byte export, filename, and directory.

Multiple collections produce a fresh .xlsx in exports/combined/ beneath the
catalog or --export-dir, with a unique Parallel_Words_<local timestamp>.xlsx name.
Only each selected collection's own sheet is included. Tabs use collection names,
made valid/unique within Excel's 31-character limit, without renaming collections
or touching cell text/labels. excel_merge.py combines source worksheet packages
and relationship closures, merges/remaps styles and custom formats, inlines shared
strings with exact whitespace, and resolves source theme/indexed colors. Related
comments, drawings, charts, tables, row/column dimensions, and formatting survive.
Date serials using the 1904 system are normalized to the output's 1900 system.

Static formulas, chart references, hyperlinks, and sheet-local defined names
follow the new tab names. References between selected sheets from the same
original template follow their target's new name. Omitted sheet references become
#REF!, described in the picker. Table names are made workbook-unique. The output
does not merge VBA macros. External workbook links, workbook-global cell metadata,
or formulas that cannot be safely renamed require separate single exports and
produce a form error. Sources/databases are never modified by export.

Verification: 233 Python tests passed in the disposable source snapshot
`/tmp/xldb-multi-export-check-wvfh2dts`; the nine focused export tests passed
again after final style/date/reference refinements. Six scrollbar tests and
JavaScript syntax checks passed. The focused export browser suite passed both
JavaScript-disabled download and JavaScript dialog/mobile/default/reset/cancel
checks. Desktop/HTML and mobile screenshots were reviewed. The broader
collection navigation browser suite encountered browser navigation/evaluation
timeouts. The editor suite passed its first seven groups (including the new
export-dialog guard), then hit an expired/noneditable draft during later
empty-cell checks. These incomplete broader runs are not counted as passes.

Focused tests cover source fidelity, rich text/blank lines, comments, styles and
custom number formats, conditional formatting, themes, charts/tables, date systems,
shared strings/prefixed XML, formula remapping, saved edits/additions/Trash,
selection/defaults/public routes, and non-overwriting filenames. Identical styles
and number formats are reused across collections. Manual T81–T84 were added and
remain pending. Existing user files/credentials and all previous uncommitted work
were preserved; no remote deployment, commit, or push occurred.

**Collection management milestone (2026-11-07)**

The user requested empty creation, worksheet upload/import, and collection removal
in administration, and explicitly chose recoverable Collections Trash. The new
Collections navigation item covers all three. Ordinary HTML forms work with
JavaScript disabled and retain the existing admin login/CSRF protections.

Catalog schema 1 upgrades additively to 2: collections gain deleted_at/deleted_by
and a lifecycle revision; collection_events records create/delete/restore with
admin name and UTC time, atomically with the catalog change. Names/UUIDs/paths
remain reserved while removed. Collection/access schema versions remain 7/2.
No files are moved/deleted for collection removal. Original workbook bytes,
content/formatting, row Trash, edit history, IDs, and browser preferences survive
restoration. All public/content-admin routes reject removed collections. Removing
the last one leaves the public empty state and administration functional.

Removal confirmation requires DELETE and a signed collection/action/lifecycle/
admin-context/content-version token; restoration binds the same fields except
content version. Active (nonexpired/nonrevoked) leases block removal. Catalog
lifecycle guards cover selected collection requests through response construction
and preference writes, so removal waits for in-flight requests. Use the documented
single process. CLI create/import/register still work, with attributed catalog
events; CLI listing excludes removed collections.

admin_imports.py stages files privately in imports/<random-token>/ beside the
catalog. Uploads are bound to the current admin form context, and a shared lock
prevents concurrent consumption/cleanup. Success/Cancel remove the upload; stale
uploads expire after 30 minutes and are cleaned on a later upload/import request.
There are at most ten pending globally. The worksheet chooser uses exact titles;
failed validation/name collisions leave the wizard retryable without partial
collection databases. Uploaded names become source labels; no source file is
rewritten. The complete original archive is retained, including other sheets.

Upload-specific body limit: 25 MiB plus 64 KiB multipart overhead; ordinary
requests remain 64 KiB. Waitress allows the larger body; Nginx documentation now
uses 26m. Defaults also bound expanded ZIP data to 100 MiB, members to 2,000,
populated cells to 500,000, and selected sheet grids to 2,000,000 cells. Browser
imports support at most 100,000 rows and 256 columns. Streaming Expat rejects
DTD/entity declarations before openpyxl, including UTF-16/nonstandard XML part
extensions. Actual worksheet bounds are checked even when dimension metadata is
missing or incorrect. Encrypted/duplicate ZIP entries and invalid coordinates
are rejected.
Single-database mode explains that management needs --catalog.

Verification: 224 Python tests passed in a disposable source snapshot, followed
by a 14-test focused pass after the final sparse-sheet bounds check. All 52
browser groups across six suites passed, including eleven administration groups
with JavaScript disabled, plus six scrollbar tests and JavaScript syntax checks.
Desktop/mobile screenshots of Collections and restoration were reviewed.
An initial parallel browser run closed Chromium during the editor suite and
expired a six-second test lease during the departure check. The editor, lease,
and live-update suites subsequently passed when run sequentially.

README/DEPLOYMENT/ADMIN_DESIGN describe these flows and limits. MANUAL_TESTING
adds T73–T80, all pending. Existing user credentials, databases, and workbooks
were untouched. No remote deployment, commit, or push was performed.

**Working administration milestone (2026-11-07)**

The user approved implementing the preview. `admin.py` registers a blueprint at
/admin; /admin redirects to /admin/. `templates/admin/` and static/admin.css use
ordinary HTML forms with POST/303 redirects, no client scripts or Quill/htmx.
The main header/empty landing page link to administration; an open or opening
editor/pending operation blocks the header link to prevent draft loss.

`manage_access.py set-admin-password` bootstraps or resets the global admin
credential locally, with hidden prompts. Use --database to match a custom access
file. No password was generated or installed in the user's access database.
Before bootstrap, admin login returns a local-setup explanation without a public
registration form. Admin login requires a name and separate password and has its
own role-aware throttling. A separately revocable admin_session cookie reference
coexists with editor_session. Roles and global scope are checked explicitly;
admin login does not grant editing, editor login does not grant administration,
and admin sign-out does not revoke an independent editor grant.

Access schema 2 adds admin_events, preserving all existing credentials/grants.
The old session table name remains editor_sessions, with role-aware resolvers.
Password changes require current admin password and repeated new password, check
credential revision/grant again inside the write transaction, revoke only that
role's grants, and insert secret-free audit metadata atomically. Changing admin
password signs out the initiating administrator too. A failure of audit insertion
rolls back the credential/grant change. Raw passwords/hashes never enter audits.
The editor API and lease validator still accept only global editor grants.

Every admin POST requires an active admin grant and admin_csrf. CSRF rotates on
admin login/logout/admin-password reset, rejecting previous-login forms. Recovery
confirmation tokens bind collection UUID, Trash ID, and current admin form nonce;
cross-item/collection/context submissions fail. Admin responses are no-store and
inherit the existing CSP/frame/cookie protections. Return URLs are restricted to
local /admin/ paths. Names, cell text, HTML formatting and JSON snapshots are
escaped; bearer tokens, identity/lease hashes are not passed to view templates.

`admin_data.py` reads collection-local Trash/history using bounded SQL filters
before pagination (50 events/items per page). Trash previews show at most 200
cells with full counts; restored entries use deletion snapshots. Restore reuses
store.restore_trash(actor=admin), preserves IDs/formatting, handles parent-first
recovery and duplicate/stale submissions, and emits existing history/version
updates in the same transaction. There is no purge/forced-lock/revert action.
History supports editor, etymon, action, outcome, and local date ranges, with
DST-correct UTC bounds. Activity is distinguished from saved content. Active
editors reuse existing lease records/cleanup, with configurable heartbeat/expiry
settings displayed and a manual Refresh link. Collection selection never saves
public browser preferences; single-file and empty-catalog modes are supported.

Verification: all 210 Python tests, six Node scrollbar tests, JavaScript syntax
checks, and 48 browser groups across six suites passed. The seven new admin
groups run with JavaScript disabled alongside a real editor. Working desktop/
mobile screenshots were reviewed. An existing editor-browser test now explicitly
waits for Quill after its asynchronous double-click before trying to cancel;
without that wait it could test an editor that had not yet opened.

README/DEPLOYMENT/ADMIN_DESIGN describe setup and use; MANUAL_TESTING now has
72 tasks, including the admin flows. The original static design preview is kept
unchanged. Tests use disposable databases/workbooks/servers. No deployment,
commit/push, or modifications to real credentials/workbooks/collections occurred.

**Manual acceptance checklist and admin design (2026-11-07)**

The user requested a list of manual testing tasks for implemented functionality
and a design for administration at /admin. MANUAL_TESTING.md includes a separate
test catalog/access-file setup, independent Ana/Bob browser sessions, 59 tasks
with expected results, a short first pass, and CLI recovery/history/password
commands for the existing app. It includes Excel desktop and remote HTTPS checks
which local automated tests cannot substitute for.

ADMIN_DESIGN.md specifies ordinary HTML forms/pages for a protected overview,
global editor/admin password management, collection-scoped Trash preview/recovery,
saved history and editing activity, and active editors. A separate global admin
credential/grant, local bootstrap/reset, role checks, CSRF, attribution, bounded
SQL filtering/pagination, and parent-first Trash recovery are part of the proposed
implementation. Password-change effects on admin versus editor grants are explicit.
The first release excludes permanent purge, forced lock takeover, history revert,
personal accounts, and workbook upload/collection administration.

design/admin/index.html plus style.css is a local static preview: all navigation
uses section anchors, examples are invented, forms are inactive, no scripts or
network/database connections are included. This is a design deliverable, not
a running /admin route. README links both documents and the preview. No runtime
code, credentials, databases, or user workbooks were changed by this task.
The preview was checked in Chromium at desktop/mobile sizes with JavaScript
disabled: anchor navigation, native restoration disclosure, inactive forms,
and page width passed; screenshots were visually reviewed. All 59 task IDs and
document links were checked, and git diff --check passed. Runtime test results
below are from the preceding implementation; no runtime changes required reruns.

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

`collection_catalog.py` owns a schema-2 catalog (additive upgrade from schema 1):

- `collections`: collection UUID, display name, absolute DB path, UTC creation time,
  deletion time/name, and lifecycle revision.
- `collection_events`: create/delete/restore actions, collection UUID, actor, UTC time.
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

`access_control.py` owns a separate schema-2 access database with:

- `credentials`: password hash, revision, role (`editor`/`admin`), scope type
  (`global`/`collection`), scope ID, and UTC update time. Only the global editor
  and global administrator credentials are accepted by separate policies;
  collection scopes fail closed.
- `editor_sessions`: SHA-256 of a random bearer token, credential ID/revision,
  self-declared name, UTC creation time. The raw token stays in Flask's signed
  HttpOnly/SameSite cookie, never in history, HTML payloads, or localStorage.
- `admin_events`: password-change actor/time/role/scope/revision, without secrets.
- `access_metadata`: storage version; schema 1 upgrades additively to 2.

Credential setup/reset deletes existing grants for that role only. Every request resolves its grant
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
`AccessControl.can_edit` and `can_admin` are the role policy hooks;
collection-specific permissions remain future work. Test apps use in-memory access storage unless explicitly configured;
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

User manual acceptance: **T01–T16 and T81–T82 checked; 80 of 98 tasks pending**,
including all administrator, localization, collection-name, and new search-mode tasks. The checks below are agent-run and do
not change user acceptance status.

Latest full Python verification: 270 tests passed in the disposable snapshot
`/tmp/xldb-regex-full-254pxq9q`, using the project's Python at
`/home/hartular/Lingv/XLDB/.venv/bin/python`. After the final escaped-Unicode
literal refinement, the focused search/highlighting/localization subset passed
34 tests. The legacy `db/example.xlsx` fixture was recovered read-only from
`e3112e5:db/example.xlsx` in Git history into the snapshot. It is absent from
current HEAD/live workspace; do not restore it over the user's workbook or touch
real databases. Earlier temporary checkouts have been removed. Copy current
source/tests into a disposable snapshot before further checks. Self-contained
collection/admin/search suites run directly in the workspace.
The regex change passed four focused Chromium search groups, all eight existing
live-update browser groups, four translation helper tests, six scrollbar tests,
JavaScript syntax checks, and pip dependency validation. See its milestone for
behavior, limits, deployment, and acceptance details.
Four translation helper tests, six scrollbar tests, JavaScript syntax checks,
and three focused collection-name browser groups passed for the naming change.
The previous localization change passed three focused browser groups. The previous export change passed its
two focused export browser groups. The preceding
collection-management milestone passed sixteen editor, five collection, six
authentication, six lease, eight live-update, and eleven JavaScript-disabled
admin browser groups. These broader suites were not all rerun for multi-export;
see the multi-export milestone above for current browser results/limitations.
Browser checks include
simultaneous edits from two tabs in different collections, scoped search/forms/
export/Trash, renamed headings and row types, initial-column metadata, empty
collection creation, editor navigation guards, and browser Back. Optional suites
are `tests/test_cell_editor_browser.js`, `tests/test_collections_browser.js`,
`tests/test_authentication_browser.js`, `tests/test_edit_sessions_browser.js`,
`tests/test_live_updates_browser.js` (eight automatic-refresh groups), and
`tests/test_admin_browser.js` (eleven administration groups including collection management).
`tests/test_exports_browser.js` adds focused HTML/dialog multi-export checks.
`tests/test_localization_browser.js` covers Romanian/English with and without JS.
`tests/test_collection_names_browser.js` covers imports, rename restrictions, and headings.
`tests/test_regex_search_browser.js` covers search modes, normalization, live state, and plain HTML.
Playwright is outside the project at `/tmp/xldb-browser/node_modules`; its
browser installation is `/tmp/xldb-browser/browsers`. Use NODE_PATH and
PLAYWRIGHT_BROWSERS_PATH accordingly. Browser servers/databases are temporary.

The user reports remote editing works and previously diagnosed HTTP download
warnings in Chrome. The remote machine uses Ubuntu 24.04 ARM64 and Nginx;
capibara.hopto.org already has a Let's Encrypt certificate on 443. Port 8080 was
plain Waitress HTTP, so https://...:8080 cannot work without a TLS listener.
Do not replace an existing site's configuration without checking it. This
milestone's catalog/schema/authentication/admin changes were tested locally by
the agent; installation and verification of the latest build on that machine
have not been confirmed by the user. Existing schema-4/5/6 collections upgrade
without reimport; schemas 1–3 still require a fresh collection import. Deploy the
access DB/password setup as documented, with its directory writable by the service.

**Next work, when requested**

The immediate user-facing follow-up is the still-pending MANUAL_TESTING.md
acceptance pass, including T60–T80 for administration, T83–T84 for export, T85–T90 for language, T91–T93 for collection names, and T94–T98 for search modes. Help with setup or fix
specific reported failures when asked; do not infer that the checklist has
already been completed or begin unrelated features during handoff.

Authentication, attribution, live cell coordination, automatic content refresh,
and HTML administration (global passwords, Trash/recovery, history, active editors)
are implemented, including collection creation/import and recoverable Collections
Trash. Collection-specific passwords, permanent purge, personal accounts, and
history revert remain future work.
Do not add these without a new request.
The team prefers shared passwords and self-declared names over personal accounts.
