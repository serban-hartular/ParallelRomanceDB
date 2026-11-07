# Parallel Words: manual test checklist

This checklist covers the application as implemented on 2026-11-07. The
admin interface is available at `/admin/` and described separately in
[ADMIN_DESIGN.md](ADMIN_DESIGN.md). Tasks T60–T72 cover its implemented workflows.

## Current testing status — 2026-11-07

**User acceptance testing has not started: all 72 tasks remain pending.** The
user has looked at the application but has not worked through this checklist.
No task has been marked passed, failed, or not applicable by the user yet.

| Coverage | Tasks | User testing status |
| --- | --- | --- |
| Browsing, editing, collections, locking, live updates, recovery, Excel, and deployment | T01–T59 | Pending |
| Administrator setup/login, passwords, Trash/recovery, history, active editors, and remote access | T60–T72 | Pending |

The preceding implementation passed 210 Python tests, 48 automated browser
check groups, six Node scrollbar tests, and JavaScript syntax checks. Agent
review of desktop/mobile screenshots also took place. These checks do not
complete any task in this **user** checklist or confirm behavior in the user's
Excel installation or deployed environment. Earlier informal reports that
editing/export worked are not completion of this acceptance pass.

Tick a task only after its expected result is observed. Record the browser,
collection, etymon, row label/number, language column, and any error when a task
fails. Testing Chrome and the actual Excel desktop application is particularly
useful; automated browser tests already cover Chromium locally.

## Prepare a disposable test installation

Use a fresh test catalog and a **copy** of a representative workbook. This lets
you test deletion, password changes, and recovery without affecting your team's
work. Choose another directory if `data/manual-test` already contains useful data.
Run from the project directory:

```bash
# Replace this path with your workbook copy. Add --sheet "Sheet name" if needed.
.venv/bin/python manage_collections.py --catalog data/manual-test/catalog.sqlite3 create "QA imported" --workbook "/path/to/workbook-copy.xlsx"
.venv/bin/python manage_collections.py --catalog data/manual-test/catalog.sqlite3 create "QA empty"
.venv/bin/python manage_access.py --database data/manual-test/access.sqlite3 set-edit-password
.venv/bin/python main.py --catalog data/manual-test/catalog.sqlite3 --local --port 8091
```

Open `http://127.0.0.1:8091/`. For remote checks, use the test installation's
HTTPS address and the existing deployment procedure in [DEPLOYMENT.md](DEPLOYMENT.md).
The commands above deliberately serve only the local machine.

Use two independent browser sessions: **A**, a regular window signed in as
**Ana**, and **B**, an incognito window signed in as **Bob**, using the test edit
password. All incognito windows of one browser may share a session. A second
regular tab shares Ana's login and collection preferences; it is useful for the
same-login tests but does not represent Bob. A third browser/profile is useful
for checking anonymous browsing.

Prefer a workbook with several etymons, all three non-etymon row types, French
and other language columns, accents, mixed formatting, empty colored cells,
line breaks, and another worksheet. Record an unedited cell/label with unusual
spacing for later comparison. Choose a sufficiently large etymon to scroll in
both directions. If a test feature is absent from the workbook, create suitable
test entries or mark that task not applicable.

The normal timing is: live check every **5 seconds**, editor heartbeat every
**30 seconds**, and lock expiry after **5 minutes without contact**. Allow a
little extra time for a request to complete. Hidden tabs check when shown again.

## A short first pass

If time is limited, first complete T01, T04, T13, T17, T24, T29, T34, T35, T43,
T46, T48, T52, and T55 below. These exercise browsing, search, authentication,
saving, creation, locking, live updates, recovery, Excel, and restart persistence.

For an admin-focused first pass, complete T60, T61, T63, T66, T68, T70, and T71.
Prepare disposable deleted content using T44–T45 if needed. Continue with the
remaining tasks afterward; finishing a short first pass does not complete the
full checklist. All of these checks are still pending.

## Browsing and search

- [ ] **T01 — Initial view.** Open the imported collection without signing in. Check several source cells, language names, row labels and numbers against Excel. Text, diacritics, label spelling/spacing, rich text, and imported backgrounds should agree. Browser layout need not match Excel's dimensions.
- [ ] **T02 — Public browsing.** Double-click a cell in Search mode. No editor should open. Search, navigation, and Excel download should remain available without a password.
- [ ] **T03 — Navigation.** Select an etymon from the list, then use previous/next. Title, selected entry, and displayed rows should agree; the first/last result should have no unavailable neighbor link.
- [ ] **T04 — Case and accents.** Search a distinctive accented word using its normal spelling, uppercase/lowercase, and an unaccented spelling. The same cells should match, and displayed source text should remain unchanged.
- [ ] **T05 — Multiple filters.** Combine two language columns and two row labels. Results should come from a cell satisfying both the selected language and row-label restrictions; selections within one filter are alternatives. Clearing a filter should mean all values in that filter.
- [ ] **T06 — Highlighting and display.** Search a word in richly formatted content, then switch between Formatted and Plain text. Matches should be highlighted without saving those highlights or changing the stored text; original formatting should return in Formatted mode.
- [ ] **T07 — No matches and Clear.** Search for a unique nonexistent string. The app should show no results without an error. Clear should restore the full collection and clear the filters.
- [ ] **T08 — Search while editing is enabled.** Turn on Edit mode after signing in, then search/filter/navigate while no cell editor is open. Search controls should stay visible and usable.

## Layout and collection separation

- [ ] **T09 — Scrolling and resizing.** Scroll a large table horizontally and vertically using the visible scrollbars, resize a column and a row, and hide/show a language through Table columns. Frozen row labels should stay legible and scrollbars should follow the content.
- [ ] **T10 — Layout persistence.** Navigate away from and back to that etymon, then reload. Saved widths, column visibility, and resized row heights should return. Reset layout should restore defaults.
- [ ] **T11 — Etymon list.** Collapse/reopen the list and, with enough results, scroll it. Searching should reveal the results list. Hiding the list should leave the table usable.
- [ ] **T12 — Two collections.** Use different searches/layouts in the imported and empty collections, switching through the header and browser Back. The URL, title, filter choices, row menus, and export target should always belong to the displayed collection. Each collection should retain its own preferences/layout.

## Edit login and identity

- [ ] **T13 — Sign in.** Click Edit mode, try a wrong password, then Cancel. Search mode should remain active. Try again with Ana and the correct password: Edit mode should activate and the header should name Ana.
- [ ] **T14 — Shared browser session.** Switch to Search mode and back, then open a second regular tab. Ana should not need to re-enter the password. Bob's incognito session should still require its own login.
- [ ] **T15 — Change editor and sign out.** Change Ana to another test name, make a test edit, then sign out. The new edit should have the new name in history, and further edits should require login. Sign-out should revoke access in other tabs sharing that login; an already displayed tab may retain old controls until refreshed.
- [ ] **T16 — Later visits.** Sign out explicitly, close the window, and revisit. Editing should require login again. Closing every incognito window and reopening also starts a fresh private session. A browser's session-restore feature can restore session cookies, so closing a regular window alone is not a reliable logout test.

## Editing cells

Sign back in as Ana and enable Edit mode in QA imported before this group.

- [ ] **T17 — Type immediately and save.** Double-click a populated cell, type without an extra click, and press Close. The caret should be inside the contents, typing should work immediately, and the saved content should survive reload. Close means save.
- [ ] **T18 — Cancel and shortcuts.** Change a cell and click Cancel; repeat using Escape. Neither draft should be saved. Repeat with Ctrl+Enter: it should save and close.
- [ ] **T19 — Unchanged Close.** Open an imported cell with mixed formatting/whitespace and close it without changing anything. Its source text and formatting should remain intact; history should classify this session as unchanged, not a saved change.
- [ ] **T20 — Rich text.** Add an accented word, repeated spaces, a line break, bold/italic text, underline/strike, sub/superscript, and a differently colored word. Save/reopen. Supported formatting and meaningful whitespace should survive. Keyboard undo/redo should work while editing.
- [ ] **T21 — Typography.** Check that opening Quill retains the cell's line spacing. Select some text and apply a font size through Typography; then change Line spacing. Font size should affect the selection/new typing, and line spacing should affect the whole cell. Save/reopen, then separately verify Cancel discards typography changes.
- [ ] **T22 — Empty colored cell.** Edit an empty cell with a known background, save some text, then clear it and save again. Its original/inherited background should stay correct in the browser and in Excel.
- [ ] **T23 — Editor behavior.** Scroll to a cell far from the top left, edit it, and save; repeat with Cancel. The table should stay at the edited position. English spelling/autocomplete suggestions should be suppressed by the editor; browser extensions or OS suggestions may need separate disabling. Navigation, export, collection switching, and identity changes should request closing/cancelling the open draft first.

## Adding rows and etymons

- [ ] **T24 — Add a row.** Open Add row. Its choices should drop down from the button and contain the three addable row types, without the etymon-marker type. Choose one: the dialog should contain selected `[To be added]` text. Replace it and create the row. The row should have the next reserved number for that type in the etymon, the text in French (or the collection's configured initial column), and be scrolled into view.
- [ ] **T25 — Other row types and Cancel.** Add each remaining type, checking its label/number and placement. Open a creation dialog and cancel; then try an empty or whitespace-only value. Cancel must add nothing, and blank text must be rejected.
- [ ] **T26 — New etymon.** Add an etymon using the default text or a new name. It should receive the next reserved etymon number and an initial etymon row; the list, count, title, and previous/next links should update. Open its initial cell and edit it normally.
- [ ] **T27 — Default colors.** In a new etymon, add all three types. With the standard defaults, the marker is blue, basic senses orange, semantic extensions yellow, and specialized senses green. Existing collections use their database-stored defaults, which may intentionally differ from newly changed config values.
- [ ] **T28 — Empty collection.** Switch to QA empty, create its first etymon and a basic-sense row, then edit and export it. The empty-state screen should become a normal working table.

## Two-user editing and locks

Return A and B to the same etymon in QA imported, both in Edit mode and signed
in as Ana and Bob respectively.

- [ ] **T29 — Same cell.** Ana opens a cell and leaves Quill open. Bob double-clicks that cell. Bob should be told Ana is editing it and should get no editor.
- [ ] **T30 — Same login, another tab.** While Ana's editor is open, try its cell in another regular tab sharing Ana's login. It must also be blocked; sharing a name/login must not take over the lock.
- [ ] **T31 — Same row warning.** Bob opens a different language cell in Ana's row. His editor should open with a notice naming Ana and identifying the row/column. Both users should be able to edit their separate cells.
- [ ] **T32 — Same etymon warning and isolation.** Bob opens a cell in another row of that etymon: the notice should say another row in the same etymon. Opening a cell in a different etymon, or in another collection, should show no warning about Ana's unrelated cell.
- [ ] **T33 — Deletion protection.** While Ana is editing, Bob tries deleting its row and its etymon, including the typed confirmation. Both should be refused with Ana's name. Ana should also be unable to delete the containing item while her draft is open. An unrelated, unlocked row should remain deletable.
- [ ] **T34 — Release and idle renewal.** Ana saves, cancels, or closes unchanged; Bob should then be able to open the cell. Also leave Ana's editor idle but connected for more than five minutes: Bob should still be blocked, because heartbeats do not require typing. Close both users' editors afterward.

## Automatic updates

Use a visible browsing window B to observe A's changes. Allow about five seconds
plus request time; switching away from B and back should also prompt a check.

- [ ] **T35 — Read-only viewer.** Leave B in Search mode, on the same etymon. Ana saves a cell. B should display the new content without a page reload or an edit login. If the etymon heading changed, the list/title/navigation should update too.
- [ ] **T36 — Preserve the view.** In B, scroll down/right, resize/hide columns, resize a row, and type an unsubmitted search or change an unsubmitted filter. Ana saves another cell. B should keep its selected etymon, layout, scroll, focus, and unsubmitted search choices while showing the update.
- [ ] **T37 — Draft protection.** Bob opens a different cell and types an unsaved draft. Ana saves her cell. Bob should see an update notice, keep his own editable draft and renewed lock, and see the refreshed table after saving or cancelling. Saving should retain both users' separate changes.
- [ ] **T38 — Dialog protection.** Leave Add row/Add etymon or a deletion dialog open in B with partially entered text. Ana changes content. The dialog and its text should remain intact; closing it should allow the pending update. If its target changed, submitting an old deletion confirmation should be rejected rather than delete a newly changed target.
- [ ] **T39 — Structural changes.** Ana adds/deletes a row, adds an etymon, and deletes the etymon B is viewing. B should update rows/counts/navigation. A deleted or no-longer-matching selected etymon should fall back to a remaining match, or to no results. Restoring it locally should also become visible automatically.
- [ ] **T40 — Other collections and hidden tabs.** Keep B in another collection while Ana edits. B should retain its own content and selection. Hide B's tab, make a change relevant to it, and show it again: it should check for the update.

## Connection failures and revocation

These tests deliberately interrupt **test sessions**. Use browser developer tools'
network Offline setting for just one browser session, or disconnect only that
test device. Browser throttling of a hidden/offline tab can delay its messages.
Return B to the collection/etymon Ana is editing; enable Bob's Edit mode for T42.

- [ ] **T41 — Viewer reconnects.** Make B offline while browsing, then let Ana save. B should report that updates will retry. Reconnect B: the saved change should appear without reloading the page.
- [ ] **T42 — Editor loses its lock.** Bob opens a cell, types a distinctive draft, then goes offline for more than five minutes. His draft should remain visible/copyable and eventually become read-only with Save disabled. Ana should be able to open the expired cell. Reconnect Bob: he must not overwrite Ana's work or release her newer lock. Copy the draft if needed, cancel, and reload to retry.
- [ ] **T43 — Password reset.** With a test draft open, run the password command below using a different test password. Existing edit logins should be revoked; the old draft should become unsaveable without disappearing, and a new login should require the new password. Browsing/export should continue. A valid new login should be able to acquire the old cell when the server processes the revoked lock. Restore the desired test password afterward if needed.

```bash
.venv/bin/python manage_access.py --database data/manual-test/access.sqlite3 set-edit-password
```

## Deletion, Trash, and history

These tasks exercise the CLI tools, which remain useful alongside Admin → Trash
and Admin → History. Browser administration is tested in T60–T72. Find the UUID
and database path for **QA imported**:

```bash
.venv/bin/python manage_collections.py --catalog data/manual-test/catalog.sqlite3 list
```

In the following commands replace `COLLECTION-ID` with that UUID, and `TRASH-ID`
with the numeric ID printed by `trash.py list`.
Sign back into Edit mode using the current test password before the browser
deletion tasks. Use the actual test etymon number instead of `1` in history
commands when checking work on a different etymon.

- [ ] **T44 — Strong confirmation.** Start deleting a disposable non-etymon row. Cancel/Escape should leave it intact. The confirmation button should remain disabled until `DELETE` is entered exactly. The marker row must not offer individual-row deletion.
- [ ] **T45 — Row deletion.** Confirm deletion. The row should disappear from every language, search, and export. Existing surviving row numbers should not change; a later new row should not reuse the deleted number.
- [ ] **T46 — Recover a row.** List Trash, restore the row's entry, and watch the browser update. Its original row/cell IDs, number, text, formatting, and backgrounds should return. It should disappear from the pending Trash list.

```bash
.venv/bin/python trash.py data/manual-test/collections/COLLECTION-ID.sqlite3 list
.venv/bin/python trash.py data/manual-test/collections/COLLECTION-ID.sqlite3 restore TRASH-ID
```

- [ ] **T47 — Recover an etymon.** Delete a test row, then its containing etymon. Restoring the separately deleted row first should explain that the etymon must be restored first. Restore the etymon, then that row. All retained content/formatting should return, with no renumbering. Other collections must remain unchanged.
- [ ] **T48 — Saved history and names.** Inspect history after Ana and Bob save, add, delete, and recover test content. Check the correct collection, name, action, etymon, exact row label/number, language, and time. CLI times are UTC. Each cell save should complete one editing record, not create a duplicate save event. CLI recovery should be attributed to Local administrator.

```bash
.venv/bin/python history.py data/manual-test/collections/COLLECTION-ID.sqlite3 --limit 50
.venv/bin/python history.py data/manual-test/collections/COLLECTION-ID.sqlite3 --etymon 1 --json
.venv/bin/python history.py data/manual-test/collections/COLLECTION-ID.sqlite3 --sessions --json
```

- [ ] **T49 — Activity versus changes.** With `--sessions`, find an active editor, a cancelled draft, unchanged Close, and the expired/revoked sessions from earlier tests. Cancelled/unchanged/expired/revoked activity must not appear as saved changes in the normal history listing. Exact before/after snapshots should reflect actual saves; unsaved draft text is not transmitted by typing.

## Excel and persistence

- [ ] **T50 — Full workbook.** Apply a narrow search/column filter and export. The download should still contain the whole original workbook, with the complete selected sheet updated and other sheets retained. Its filename should have a timestamp; two exports should create different files. The source workbook copy must remain unchanged.
- [ ] **T51 — Source fidelity.** Compare untouched labels/cells with the source workbook: spelling, repeated spaces, diacritics, line breaks, original fonts/colors/fills, and existing formulas should remain intact. A no-edit export from a freshly imported collection is useful for this comparison.
- [ ] **T52 — Edited Excel formatting.** Open the export in your actual Excel installation. It should open without repair/compatibility warnings. The differently colored word, mixed font sizes and supported rich formatting from T20–T21 should be present, rather than taking the whole cell's font color. Empty colored cells should retain their fills. CSS line spacing and text background highlighting have no exact Excel equivalent; their browser settings remain in SQLite.
- [ ] **T53 — Added/deleted rows in Excel.** Check the newly added rows/etymons: correct placement, label/number, background, complete border outlines, and no missing/duplicate text. Deleted rows must be absent; recovered rows must be present. Where the workbook has formulas referring to shifted/deleted cells, check that the resulting references are sensible.
- [ ] **T54 — Spreadsheet-looking text.** Enter a literal test value beginning `=` in a disposable cell and export it. It should remain text, not execute as a newly introduced formula. Existing source formulas should still be formulas.
- [ ] **T55 — Restart persistence.** Save representative edits, additions, and deletions; stop and restart the server using the same catalog/access database. Reload the browsers once. Content, collection identities, formatting, Trash, history, and the configured password should persist. Earlier source workbook contents must not be reimported over the database. Browser login survival depends on keeping the same configured secret; restart invalidates already-open editor tokens, so close drafts first.
- [ ] **T56 — Collection-specific export.** Give QA empty distinctive content and export it, then export QA imported. Each file should contain the appropriate collection's content/template, including when different tabs are open on different collections.

## Remote checks (on a test deployment)

- [ ] **T57 — HTTPS.** Open the normal HTTPS domain from another device. Browsing, edit login, and export should work through the proxy, with no insecure-download warning in Chrome. Use the HTTPS site address, not HTTPS on a plain HTTP Waitress port.
- [ ] **T58 — Two real devices.** Repeat T29, T31, T35, and T37 with two people/devices. They should observe the same names, lock denials/warnings, and live updates as the local two-session test.
- [ ] **T59 — Cookie/proxy settings.** If secure cookies and trusted hosts/proxy are configured, check the session cookie's Secure, HttpOnly, and SameSite settings in browser developer tools, and verify the expected domain works. Do not enable secure cookies on the local HTTP test instance. Deployment configuration details are in DEPLOYMENT.md.

## Administration (HTML interface)

Use the disposable test access file, not the team's password store. Keep a
regular editor session as Ana and a separate administrator browser/profile;
also try a browser context with JavaScript disabled. Closing a regular browser
window alone can preserve cookies through browser session restoration; use
explicit Sign out when checking revocation.

- [ ] **T60 — Local bootstrap.** On a fresh test installation before an admin password has been set, visit `/admin/`. It should explain local setup and offer no public first-password registration. Set the test administrator password with the command below. The login form should become available, while the existing edit password/login still works. If already configured, test the command as a reset instead.

```bash
.venv/bin/python manage_access.py --database data/manual-test/access.sqlite3 set-admin-password
```

- [ ] **T61 — Separate access.** Try the edit password at administrator login: it should fail. Sign in with an administrator name and the admin password. Opening `/admin/collections/COLLECTION-ID/history` or `/admin/collections/COLLECTION-ID/trash` from an anonymous/editor-only browser should require admin login; an admin-only login must not silently enable editing in the main app.
- [ ] **T62 — Overview and navigation.** Check the selected collection's etymon count, pending Trash count, active-editor count, and latest saved change against known test activity. Switch collections; the name, URL, counts, Trash, history, and Back to collections link should follow the selected collection. An editing tab's search preferences should stay unchanged.
- [ ] **T63 — Change edit password.** First submit mismatched new passwords or an incorrect current admin password: nothing should change, and password fields should return blank. With Ana editing, submit a valid new edit password. The admin should stay signed in; editor logins should be revoked and the old draft should remain copyable but unsaveable. A new edit login should require the new edit password.
- [ ] **T64 — Change admin password.** Have two administrator sessions and an independent editor session. Change the admin password with correct confirmation. Both administrators, including the initiating one, should have to sign in again using the new password. The editor should remain able to save. The local command should also work for forgotten-password recovery.
- [ ] **T65 — View Trash and cancel.** In Admin → Trash, filter by item type, etymon, and pending/recovered status. View a pending row's retained text, deletion actor/time, and row/cell counts. Review restoration, then Cancel: no row should be restored and no content/history change should occur merely from visiting the preview. If an entry contains more than 200 cells, its preview should be limited to 200 while showing the full counts; mark just this large-entry check not applicable if no suitable example exists.
- [ ] **T66 — Recover through the browser.** Confirm a row restoration. Original IDs/numbers, content, formatting, and backgrounds should return. Its history event should name the administrator; pending Trash should no longer list it, and a recovered listing should show its deletion snapshot. An already-open collection view should update automatically, deferring safely if a draft is open. Reusing an old recovery form should not duplicate rows. If testing a preview-limited entry, verify that recovery restores the entire entry, not only the 200 previewed cells.
- [ ] **T67 — Parent-first and collection isolation.** Delete a row, then its containing etymon. Admin should link the row's blocked recovery to the parent Trash item. Restore the etymon, then the row. In another collection, its separate Trash items and content must remain untouched. This should also work when both collections happen to have Trash item #1.
- [ ] **T68 — Saved history and snapshots.** Filter History by editor, etymon, action, and a local date range. Inspect a saved cell's Before/After text and escaped formatting/spacing details, and inspect a structural add/delete/recovery event. Names, targets, and timestamps should match the actual operations; displayed times include a Europe/Bucharest UTC offset.
- [ ] **T69 — Activity and pages.** Include editing activity or choose a cancelled/unchanged/expired outcome. Such details should say No change saved; active records should say Editing in progress, without displaying unsent typing. With more than 50 matching events, Next/Previous should retain filters and collection identity. If fewer exist, mark only the pagination part not applicable.
- [ ] **T70 — Active editors.** Leave Ana editing and open Admin → Active editors. Verify the exact row/language, start time, last contact, and expiry. Refresh after a heartbeat and after Cancel; the times should advance and the closed editor should disappear. Revoked/expired sessions should be excluded. No forced takeover control should be present.
- [ ] **T71 — Plain HTML, mobile, and sign-out.** Use all admin forms with JavaScript disabled and review at a narrow/mobile width. Forms, filters, collection switching, confirmation pages, and table scrolling should work. Admin Sign out should require admin login on revisit without ending a separate editor login. A stale form from a previous admin login must not perform an operation under a replacement name.
- [ ] **T72 — Remote administrator access.** On the HTTPS test deployment, repeat administrator login, a password change, and a recovery. The same site should serve `/admin/` without a new port. Direct tool URLs should require admin access; browser Back after sign-out must not authorize further operations, even if the browser displays an old page from its own history.

## Report a failure

Leave failed or unrun tasks unchecked and record their outcome below. If a task
contains an inapplicable part, name that part explicitly; do not count an unrun
task as passed. Update the status above as actual results become available.

| Task | Outcome (pass/fail/not applicable) | Date / browser / environment | Notes or issue |
| --- | --- | --- | --- |
| — | No user results recorded yet | — | All tasks pending |

Record a short reproduction such as:

```text
Task: T36
Date/time and timezone:
Browser/version and local/remote address:
Collection / etymon / row label + number / language:
Ana's steps:
Bob's steps:
Expected:
Observed:
Screenshot or terminal error, if available:
```

Do not include passwords, session cookies, or authentication tokens in a report.
Keep the disposable test installation until any failed task has been investigated.
