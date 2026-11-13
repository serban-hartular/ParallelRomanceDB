# Parallel Words: manual test checklist

This checklist covers the application as implemented on 2026-11-13. The
admin interface is available at `/admin/` and described separately in
[ADMIN_DESIGN.md](ADMIN_DESIGN.md). Tasks T60–T80 cover its implemented workflows.

## Current testing status — 2026-11-13

**The checklist currently marks T01–T16 and T81–T82 complete. The other 80 of
98 tasks remain pending, including new search-mode checks T94–T98.** Browser/date/environment
details for the checked tasks have not yet been recorded below. Existing checkbox
marks are preserved; automated checks do not change user acceptance status.

| Coverage | Tasks | User testing status |
| --- | --- | --- |
| Browsing, editing, collections, locking, live updates, recovery, Excel, and deployment | T01–T59 | T01–T16 checked; T17–T59 pending |
| Administrator setup/login, passwords, Trash/recovery, history, active editors, and remote access | T60–T72 | Pending |
| Collection creation, Excel upload/import, Collections Trash, and restoration | T73–T80 | Pending |
| Export picker, multiple collection sheets, formatting/formulas, and fallback | T81–T84 | T81–T82 checked; T83–T84 pending |
| Romanian/English interface, remembered choice, messages, editing, and data integrity | T85–T90 | Pending |
| Import name suggestions, renaming restrictions, and prominent collection headings | T91–T93 | Pending |
| Diacritic/regex modes, normalized queries, highlights, errors, and saved/live searches | T94–T98 | Pending |

Automated verification results are recorded in [HANDOFF.md](HANDOFF.md). These
checks do not complete any task in this **user** checklist or confirm behavior
in the user's Excel installation or deployed environment. Earlier informal
reports that editing/export worked are not completion of this acceptance pass.

The interface now defaults to Romanian. Earlier tasks use English control names;
choose **English** in the page header to follow them verbatim, or use their
Romanian equivalents. Workbook text, column headings, and row labels retain their
original language.

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
full checklist. Keep completed tasks checked and continue with the pending ones.

## Browsing and search

- [X] **T01 — Initial view.** Open the imported collection without signing in. Check several source cells, language names, row labels and numbers against Excel. Text, diacritics, label spelling/spacing, rich text, and imported backgrounds should agree. Browser layout need not match Excel's dimensions.
- [X] **T02 — Public browsing.** Double-click a cell in Search mode. No editor should open. Search, navigation, and Excel download should remain available without a password.
- [X] **T03 — Navigation.** Select an etymon from the list, then use previous/next. Title, selected entry, and displayed rows should agree; the first/last result should have no unavailable neighbor link.
- [X] **T04 — Case and accents.** Search a distinctive accented word using its normal spelling, uppercase/lowercase, and an unaccented spelling. The same cells should match, and displayed source text should remain unchanged.
- [X] **T05 — Multiple filters.** Combine two language columns and two row labels. Results should come from a cell satisfying both the selected language and row-label restrictions; selections within one filter are alternatives. Clearing a filter should mean all values in that filter.
- [X] **T06 — Highlighting and display.** Search a word in richly formatted content, then switch between Formatted and Plain text. Matches should be highlighted without saving those highlights or changing the stored text; original formatting should return in Formatted mode.
- [X] **T07 — No matches and Clear.** Search for a unique nonexistent string. The app should show no results without an error. Clear should restore the full collection and clear the filters.
- [X] **T08 — Search while editing is enabled.** Turn on Edit mode after signing in, then search/filter/navigate while no cell editor is open. Search controls should stay visible and usable.

## Layout and collection separation

- [X] **T09 — Scrolling and resizing.** Scroll a large table horizontally and vertically using the visible scrollbars, resize a column and a row, and hide/show a language through Table columns. Frozen row labels should stay legible and scrollbars should follow the content.
- [X] **T10 — Layout persistence.** Navigate away from and back to that etymon, then reload. Saved widths, column visibility, and resized row heights should return. Reset layout should restore defaults.
- [X] **T11 — Etymon list.** Collapse/reopen the list and, with enough results, scroll it. Searching should reveal the results list. Hiding the list should leave the table usable.
- [X] **T12 — Two collections.** Use different searches/layouts in the imported and empty collections, switching through the header and browser Back. The URL, title, filter choices, row menus, and export target should always belong to the displayed collection. Each collection should retain its own preferences/layout.

## Edit login and identity

- [X] **T13 — Sign in.** Click Edit mode, try a wrong password, then Cancel. Search mode should remain active. Try again with Ana and the correct password: Edit mode should activate and the header should name Ana.
- [X] **T14 — Shared browser session.** Switch to Search mode and back, then open a second regular tab. Ana should not need to re-enter the password. Bob's incognito session should still require its own login.
- [X] **T15 — Change editor and sign out.** Change Ana to another test name, make a test edit, then sign out. The new edit should have the new name in history, and further edits should require login. Sign-out should revoke access in other tabs sharing that login; an already displayed tab may retain old controls until refreshed.
- [X] **T16 — Later visits.** Sign out explicitly, close the window, and revisit. Editing should require login again. Closing every incognito window and reopening also starts a fresh private session. A browser's session-restore feature can restore session cookies, so closing a regular window alone is not a reliable logout test.

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

## Collection management (administrator, disposable catalog only)

Use Admin → Collections with the disposable catalog/access file. Prepare a copy
of a workbook containing at least two worksheets. Include exact label spacing,
rich formatting, and known content in the worksheet to import. None of these
tasks have been performed or accepted by the user yet.

- [ ] **T73 — Create an empty collection.** Choose Create collection, enter a unique name, and submit. Its overview should show no etymons; opening it publicly should work, and Edit mode should allow adding its first etymon. Standard language columns and row types should be present. Blank/duplicate names should fail without leaving extra collections. Cancel should leave the catalog unchanged.
- [ ] **T74 — Import the chosen worksheet.** Choose Import Excel workbook, upload the workbook copy, then choose the exact worksheet and a new unique name. The correct worksheet's etymons, language headings, labels, numbers, spacing, formatting, and fills should appear. Other worksheet contents must not become this collection's data. The uploaded filename should appear as the source label. The original workbook copy must remain unchanged.
- [ ] **T75 — Imported full-workbook export.** Before editing the imported collection, export it and compare with the uploaded workbook: all worksheets, original content, rich formatting, names, and spacing should be retained. Open the export in actual Excel. Edit a disposable cell, export again, and check that only the selected worksheet has the intended change. Existing collections must remain unchanged throughout import/export.
- [ ] **T76 — Invalid uploads, retry, cancellation, and expiry.** Try a renamed non-Excel file, unsupported .xls, a worksheet with invalid layout, an existing collection name, and a workbook exceeding the configured upload limit. Each should show a clear error and leave no new collection. Correct a failed name and retry without reuploading. Cancel a staged upload: it should create no collection, and revisiting its URL should fail. A different administrator login should not open the first login's pending upload. An abandoned upload should expire after 30 minutes; mark only the expiry part unrun if not observed.
- [ ] **T77 — Move a collection to Collections Trash.** Review removal of a disposable collection, check its name/counts, then Cancel. It should remain intact. Review again and confirm by typing DELETE exactly. It should leave active/admin/public collection lists; reloading old collection/search/export URLs should report it unavailable. Another collection should still work. An already-open page's chooser updates on reload. Its name should remain reserved. Collections Trash should show the removing administrator and time; it must be separate from the row/etymon Trash.
- [ ] **T78 — Active editors and stale confirmations.** With Ana's cell draft open, try removing that collection. Removal should be blocked and Ana's draft should remain editable/saveable. Close the draft, reopen the removal confirmation, and save a change from another browser before confirming: the old confirmation should be rejected. Also try using a removal form opened before admin sign-out/sign-in; it must not remove the collection under the new login.
- [ ] **T79 — Restore a collection and restart.** Remove a disposable collection containing edits, row/etymon Trash, and history, then review restoration in Collections Trash. Cancel must leave it removed. Confirm restoration and verify the same collection URL/identity, original data/formatting, saved search/layout preferences, row Trash, and history. Its exported workbook must retain all original worksheets. Reusing old removal/restoration forms must not perform another operation. Restart the test server and verify removal/restoration persists. Removing the last active disposable collection should leave an empty landing page with usable Admin access and restoration.
- [ ] **T80 — HTML/mobile and remote uploads.** Repeat empty creation, worksheet import, removal, and restoration with JavaScript disabled and at a narrow/mobile width. Repeat an upload larger than 64 KiB on the HTTPS test deployment after applying the documented Nginx upload limit; a valid workbook within the configured limit should pass. Anonymous/editor-only browsers must be redirected to admin login when opening collection management URLs. A server in single-database mode should explain that collection management requires --catalog.

## Exporting multiple collections

Use disposable collections; keep all original workbook copies unchanged. Earlier
single-collection export tasks now use Export Excel → Download Excel.

- [X] **T81 — Current collection by default.** Open Export Excel in each of two different collection tabs. Exactly the current collection should be checked. Cancel/Escape must leave the page, selection, search, layout, and scroll unchanged. Download without changing the selection: the full original workbook should be retained, including unrelated sheets. Reopen after a multi-selection: it should again default only to the current collection. Unchecking every collection should disable Download Excel; a plain HTML submission with no selection should show an error.
- [X] **T82 — Several collections in one workbook.** Select at least two collections and download. Open the .xlsx in actual Excel: it should have exactly one worksheet per selected collection, in catalog order, with no repair warning. Every collection's complete saved entries should appear even under a narrow search. Check saved edits, additions, deleted/recovered rows, empty collections, and distinct language/row definitions. A single different collection selected on its own should export that collection's complete original workbook.
- [ ] **T83 — Formats, names, and references.** Check unusual text/label spacing, blank lines, rich fonts/colors, fills, borders, widths/heights, merged cells, and comments against each source. Check tables/charts where present. Long/invalid/colliding collection names should become valid unique tab names without changing collection names or cell labels. Self-references should use the new tab name; references to another selected sheet from the same original workbook should follow its new name. References to omitted sheets should become #REF!. Combined output is .xlsx; use individual exports to retain macros or external-workbook links.
- [ ] **T84 — HTML/mobile and unavailable collections.** Use the picker on a narrow screen and download multiple collections with JavaScript disabled. Try Export Excel with an open or opening cell editor: the draft should remain intact and export should be blocked. In a disposable second administrator session, remove a collection after opening the picker; submitting that stale selection should report it unavailable, without silently omitting it or downloading a partial selection. A refreshed picker should exclude Collections Trash. Verify that exports also work when the app serves a single database.

## Romanian and English interface

Use disposable collections and credentials. These new checks are pending user
acceptance; agent-run browser checks do not complete them.

- [ ] **T85 — Romanian default and language switch.** In a fresh browser/profile with no saved language preference, open a collection, Export Excel, and `/admin/`. The interface should be Romanian even if the browser prefers English. The header should offer Română / English with the current choice indicated. Switch to English and back from each page; verify page titles, labels, instructions, accessibility labels, and empty states. Try a narrow/mobile screen.
- [ ] **T86 — Remembered choice and plain HTML.** Choose English, reload, navigate between collections/admin/export, close and reopen the browser, and verify the choice persists. Change back to Romanian. Repeat the export and administrator flows with JavaScript disabled; the language links, login, collection forms, history filters, and recovery pages should still work.
- [ ] **T87 — Messages and administration.** In both languages, try incorrect login credentials, missing required input, duplicate collection names, an invalid Excel upload, an invalid history filter, and an empty export selection. Check success notices after a disposable collection creation/restoration. History actions/outcomes should be translated; event text, editor names, and stored snapshots should stay original. Romanian dates should use numeric day.month.year with the Europe/Bucharest UTC offset.
- [ ] **T88 — Editing controls and draft safety.** In Romanian, sign in, open a disposable cell, and check formatting tooltips, color controls, Typography, font size/spacing, Close/Cancel, Add row/Add etymon, and deletion instructions. Try changing language while a cell draft is open: navigation should be blocked with a translated message and the draft should remain intact. Cancel or save, then change language successfully. DELETE remains the literal confirmation word in both languages.
- [ ] **T89 — Original collection data.** Switch languages while viewing imported content with unusual spaces, line breaks, rich formatting, English words such as Cancel/Search, and custom column/row names. Only interface text should change. Export in each language and compare the actual worksheet contents/labels/formatting with the original. Existing data must not be translated; the initial text for a newly created entry is localized ([De completat] / [To be added]).
- [ ] **T90 — Search and separate tabs.** Search and select another etymon, then change language: the applied search, filters, display mode, and selected etymon should be retained. Leave an English page open, change the preference to Romanian in another tab, and use search/live updates in the original page: its labels/messages should stay English until navigation or an explicit language change. New full pages should use the saved Romanian preference.

## Collection names

Use disposable collections and workbook copies. These new checks are pending.

- [ ] **T91 — Worksheet-based import names.** Upload a workbook whose filename differs from its worksheet names. The initial collection name should match the first selected worksheet. Change worksheets: the automatic suggestion should follow the selection. If the name already exists, including in Collections Trash, the suggestion should append (1), then (2), and so on until unused. Type a custom name and change worksheets: the custom name should stay. Suggest name for worksheet should restore a fresh suggestion. Repeat without JavaScript using that button, then import and confirm the exact selected worksheet and complete original workbook are retained.
- [ ] **T92 — Rename a collection safely.** In Admin → Collections, choose Rename collection. Cancel first; nothing should change. Try a blank name, a duplicate active name, and a name reserved in Collections Trash: each must fail. With Ana's cell editor open in that collection, the rename form should explain the restriction and disable its button. A form loaded before Ana opened the editor must also be rejected on submission. Close/Cancel the cell editor, refresh the rename form, and rename successfully. A cell editor in another collection should not block renaming. Old forms from before another rename or administrator sign-in must not overwrite the current name. Existing collection URLs, contents, formatting, history, Trash, and preferences should remain intact.
- [ ] **T93 — Prominent collection heading.** The main header should prominently show the collection name, with no original workbook filename or extra worksheet/source label. Check desktop and narrow/mobile widths, switching collections, search/navigation, and both interface languages. A rename should appear in an already-open collection tab after its next live refresh, preserving the current view. Long names should fit with a full-name tooltip. In single-database mode, the worksheet name should be used without the workbook filename. Exports should retain the original data and full-workbook behavior; combined export tabs should use the current collection names.

## Diacritic and regex search

Use disposable data containing `café`, `cafe`, `cœur`, `coeur`, `œœ`, and
`col·laboració`, with some words split across bold/italic runs. These checks
remain pending user acceptance.

- [ ] **T94 — Independent search modes.** In a fresh browser, both Match diacritics and Regex should be off. Check all four combinations. With diacritics off, `café` and `cafe` should find both spellings; with it on, each should find its own spelling, ignoring case. With Regex off, `cafe|vin` and `[aeiou]+` should be literal text; with it on, they should act as patterns. Check column/label filters and an empty query. The permanent × in the search box should remain visible without hovering or focusing the box, clear only its text, and return focus without submitting or changing filters/switches. Clear/Resetează should reset the query, filters, and both switches.
- [ ] **T95 — Effective normalized expression.** With Regex on and Match diacritics off, submit `café|cœur`: the input should show `cafe|coeur`. Successful-search explanations should be hidden by default. Set `SEARCH_SHOW_NOTICES = True` in `config.py` and restart to show the normalization notice; errors should remain visible with either setting. The shortened search hint should sit beside the two checkboxes and wrap on narrow screens. Try `œ+` (becomes `(?:oe)+`), `[éœx]+` (becomes `(?:[ex]|oe)+`), `\bcafé\b` (becomes `\bcafe\b`), and `col·laboració` (becomes `collaboracio`). Resubmitting an effective expression should preserve it. With Match diacritics on, the accented expression should remain unchanged. Switching a checkbox should not rewrite an unsubmitted query.
- [ ] **T96 — Original text and highlights.** Search accented words and ligatures in rich-text and plaintext views, including matches across formatting runs. Highlights should cover the original characters while keeping accents, formatting, labels, spacing, and line breaks. Check anchors on imported cells with outer spaces: matching should use stored plaintext while the formatted view retains those spaces. Try whole-word patterns, ranges, groups, and zero-length matches such as `^` (no empty marks). Export after searching and verify the workbook has its original text and formatting without search marks.
- [ ] **T97 — Invalid, ambiguous, and slow patterns.** Submit `[` and `(` with Regex on. With diacritics off, try `[^œ]` and `[·]`: each should show an explanatory inline error, allowing correction. Enabling Match diacritics should allow those valid classes. Try a repetition above the limit, such as `a{1001}`. On disposable long text only, try a costly pattern such as `(a|aa)+$`: a search that exceeds its budget should stop with an error and no partial result list. The last valid saved search should return on reload. Check errors in Romanian and English; no raw server/library error should appear.
- [ ] **T98 — Persistence, live updates, mobile, and plain HTML.** Apply a regex/diacritic search, select another match, change formatted/plaintext view and language, and switch away from and back to the collection: the applied query and switches should be retained separately per collection. Change the query and switches without submitting, then have another browser edit a matching cell: the results should update using the applied search while the unsent controls remain intact. Try Search/Clear with an open cell draft: existing navigation guards should preserve it. In Table columns / Coloanele tabelului, Toate coloanele should be first: selecting it shows every content column, hiding one column unchecks it, and showing the last hidden column checks it again. Check saved visibility after reload and that an open cell draft blocks bulk column changes. Check narrow/mobile widths. Repeat the searches, normalized input, and errors with JavaScript disabled.

## Report a failure

Leave failed or unrun tasks unchecked and record their outcome below. If a task
contains an inapplicable part, name that part explicitly; do not count an unrun
task as passed. Update the status above as actual results become available.

| Task | Outcome (pass/fail/not applicable) | Date / browser / environment | Notes or issue |
| --- | --- | --- | --- |
| T01–T16, T81–T82 | Checked complete in the checklist | Not recorded | Existing user marks preserved; details pending |
| Remaining tasks | Pending | — | Includes language T85–T90, collection names T91–T93, and search T94–T98 |

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
