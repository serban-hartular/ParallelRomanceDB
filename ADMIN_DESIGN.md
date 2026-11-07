# Parallel Words: administration interface

Status: **implemented**, 2026-11-07. The running application now serves the
protected interface at `/admin/`. Set its first password locally with
`manage_access.py set-admin-password`, using the server's access file; see
[README.md](README.md#administration).

The [original HTML preview](design/admin/index.html) remains a static design
reference with invented sample records and inactive forms. The implementation
uses real collection data, ordinary HTML pages, and working POST forms.

## Address and navigation

Use `https://www.wsite.name/admin/` on the same site as Parallel Words.
`/admin` redirects to `/admin/`. The application handles authentication and
routing; no second server or port is needed. A reverse proxy must forward this
prefix to the same Flask application. If that domain already serves another
application, preserve its routes when adding the proxy location.

Use ordinary server-rendered HTML, a small stylesheet, and standard forms.
There is no need for Quill, Tabulator, htmx, live polling, or JavaScript in the
admin interface. Forms submit with POST and redirect to a confirmation/list
page, so reloading a result page does not repeat an operation.

Navigation:

```text
Parallel Words · Administration                 Signed in as Elena · Sign out
Overview | Passwords | Trash | History | Active editors | Back to collections

Collection: [Gastronomy v]   [Open]
```

Passwords are global and do not depend on the collection selector. Trash,
history, and active editing always show an explicit collection name. Carry its
UUID in their URLs and form targets; never infer the target from a different
browser tab's preferences. In single-database mode, use the same screens with a
fixed collection identity and omit the selector.

## Access: a separate global administrator password

The existing edit password must not grant access to administration. Add one
global administrator credential using the existing `role='admin'`, global scope
fields in `access.sqlite3`. Keep the shared-password/self-declared-name model;
there is no need for personal accounts at this stage.

Initial setup and forgotten-password recovery remain local commands:

```bash
# Local administrator bootstrap or reset:
.venv/bin/python manage_access.py set-admin-password

# Custom installations must point at the server's actual access file:
.venv/bin/python manage_access.py --database /path/to/access.sqlite3 set-admin-password
```

These prompt twice with hidden input. Until an admin password is configured,
admin access is disabled; a visitor cannot claim the first admin password
through the website. The login page can explain that local setup is required.
No default admin password is created.

The login form asks **Administrator name** and **Administrator password**. A
successful login lasts for the browser session. It uses a separately revocable
grant, stored as `admin_session` in the signed session alongside the existing
`editor_session`. Resolve and authorize each role explicitly. An editor login
must never satisfy an admin check, and an admin login need not sign into editing
or activate Edit mode automatically. Admin sign-out ends the admin grant without
changing an independent editor login in that browser.

An unauthenticated request to any admin page goes to admin login. Requests
with only edit access receive the same requirement. Every admin action verifies
the admin grant, collection identity, and CSRF token on the server; hiding a
button is not authorization. Only allow local `/admin/...` return destinations
when redirecting after login.

Use existing password hashing, bounded inputs, session-cookie settings, and
login throttling, extended with separate role-aware failure limits. Serve the
remote interface over HTTPS. No passwords, hashes, or raw session tokens appear
in page source, URLs, history snapshots, audit details, or logs. Set admin
responses to `Cache-Control: no-store` and retain the application's security
headers. Forms and navigation must work with JavaScript disabled.

## Overview

The landing page shows the administrator's name, links to each tool, and a
collection chooser. For the selected collection display:

| Item | Purpose |
| --- | --- |
| Collection name | Make the target unmistakable. |
| Etymon count | Basic content summary; link to its public collection view. |
| Items in Trash | Count pending recovery entries; link to Trash. |
| Active cell editors | Count current, unexpired locks; link to Active editors. |
| Latest saved change | Time, action, and editor; link to that history event. |

Do not display filesystem paths, password hashes, or internal session IDs in
the normal UI. Refreshing the page updates these figures; a Refresh link is
enough initially.

## Passwords

Two separate forms on a global **Passwords** page:

| Form | Fields | Result |
| --- | --- | --- |
| Change global edit password | Current admin password, new edit password, repeat new edit password | Revoke all editor grants for that credential, retain admin login, and require editors to sign in again. |
| Change global admin password | Current admin password, new admin password, repeat new admin password | Revoke all admin grants, including the current one, then redirect to admin login. Editor grants are unaffected. |

Show whether each credential is configured and when it was last changed. Never
show its current value. Password inputs use appropriate password autocomplete
attributes and are never echoed back on validation failure. Check confirmation
before changing anything. Verify the current admin password again for either
change; a wrong value is a throttled authentication failure, not a successful
change. Use the credential revision check during the write to reject a form if
the admin password changed concurrently.

The edit-password form explains, before submission: **All editors will be signed
out. Open drafts cannot be saved under the old login; their text remains
available to copy.** Revoked locks become available as existing lease checks
process them. Changing passwords does not itself erase a draft or saved content.
Use a clear submit label such as **Change edit password and sign out editors**.

Changing the administrator password explains that all administrators, including
the current one, will need to sign in again. A success message on the login page
confirms the change. Keep local reset available if the new password is forgotten.

The form's password change and its audit event commit in the same access-database
transaction. Record actor name/session hash, time, role/scope and credential
revision, without storing either old/new passwords or password hashes in the
audit event.

Future per-collection passwords belong in this authorization layer using the
existing scope fields. Do not show working per-collection password controls or
invent inheritance rules in the first admin release.

## Trash: inspect and recover

Default to **Awaiting recovery**, newest deletion first, with 50 entries per page.
Allow filtering by etymon and kind (row/etymon), and optionally show recovered
entries as a separate read-only listing.

| Column | Contents |
| --- | --- |
| Deleted | Local date/time with timezone. |
| Item | Row or entire etymon. |
| Etymon | Number and title recorded at deletion. |
| Row | Exact label and number, or “All rows in this deletion”. |
| Deleted by | Name from the matching deletion-history event, or “Not recorded” for older data. |
| Size | Number of rows/cells in this Trash entry. |
| Action | View details; from there, Review restoration. |

A details page previews retained row labels and cell text, identifies the
collection and Trash entry, and summarizes what will return. Read deleted rows
through their `trash_id`; normal active-cell queries deliberately exclude them.
Display text safely escaped. This screen does not need a rich-text editor.

**Review restoration** leads to a confirmation page showing the exact collection,
etymon, rows and affected cell count. A POST restores that one entry using
`store.restore_trash(..., actor=admin_identity)`. It preserves IDs, reserved
numbers, content, formatting, and backgrounds; history records the administrator's
name in the same collection transaction. The content version advances, so open
browsers notice the recovery through existing live updates. Redirect back to
Trash with a success message and a link to the recovered etymon.

If a row's containing etymon is still deleted, explain **Restore the etymon
first** and link to the relevant parent Trash entry. Restoring an etymon must
not silently restore rows that were separately deleted earlier. Already-restored,
missing, or cross-collection entries produce a clear result and no duplicate
recovery. Recheck the current state on POST, not just on the preview page.

There is no permanent-delete/Empty Trash button in this first release. Recovery
does not renumber surviving entries. This keeps the existing recoverable-delete
behavior.

## History: changes and editing activity

Default to **Saved changes**, newest completion first, with 50 events per page.
Filters: collection, etymon number, editor name, action, and date range. An
**Include editing activity** option also exposes active, cancelled, unchanged,
expired, and revoked sessions, with an optional status filter. Apply filters in
SQL before pagination; do not load or truncate the entire history first.

| Column | Contents |
| --- | --- |
| Completed / started | Completion time for completed events; clearly marked start time for active editors. |
| Editor | Recorded name, including Local administrator for local tools. |
| Action / outcome | For example, Cell edit · Saved, or Cell edit · Cancelled. |
| Etymon | Recorded number. |
| Row | Exact historical label and label number. |
| Language | Recorded column name, if applicable. |
| Details | Link to the event and before/after text. |

Details display the target identity, start/finish times where known, and **Before**
and **After** panels. For a saved cell, show readable escaped text side by side;
show font/spacing metadata when relevant, so formatting-only saves are understandable.
A collapsed technical section may show escaped JSON snapshots for diagnosis,
omitting raw lease tokens/hashes and session identifiers from the page. Cell
content is not interpreted as new admin-page HTML.

Cancelled/unchanged/expired/revoked events explicitly say **No change saved**;
active events say **Editing in progress**. Do not present original content as an
unsaved draft: live keystrokes are not sent to the server. Earlier historical
records may have unknown start times or missing attribution; show that honestly.
For additions/deletions/recovery, summarize row/cell snapshots rather than
pretending every action is a single-cell edit.

Provide ordinary Previous/Next pages, preserving filters in links. All timestamps
show Europe/Bucharest with an explicit UTC offset; storage remains UTC. Interpret
date filters in that displayed timezone, including daylight-saving transitions.
Viewing history does not roll content back. A revision-revert feature needs its
own conflict/deletion design and is outside the first admin release.

## Active editors

This is a convenient filtered view of existing active editing records, not a
second lock table. Show collection, editor, etymon, exact row/column, start time,
last contact, and expiry, after applying the existing expired/revoked-lock cleanup.
A note explains the 30-second heartbeat and five-minute no-contact expiry.
A Refresh link is sufficient; no typing/mouse activity is tracked.

Do not expose bearer tokens or let an admin silently take over a cell. A forced
lock-release operation is not part of the first release; ordinary Save/Cancel,
sign-out/password revocation, and expiry retain their established behavior.

## Implemented routes

The running server uses these routes; the original static preview uses section anchors.
`GET /admin/choose` also handles the collection selector without saving browser preferences.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/admin/` | Protected overview. |
| GET / POST | `/admin/login` | Login form / authenticate. |
| POST | `/admin/logout` | Revoke only the admin login. |
| GET | `/admin/passwords` | Credential status and change forms. |
| POST | `/admin/passwords/edit` | Change global edit password. |
| POST | `/admin/passwords/admin` | Change global admin password. |
| GET | `/admin/collections/<id>/trash` | Collection's Trash list/filters. |
| GET | `/admin/collections/<id>/trash/<trash_id>` | Retained-content details. |
| GET | `/admin/collections/<id>/trash/<trash_id>/restore` | Restoration confirmation. |
| POST | `/admin/collections/<id>/trash/<trash_id>/restore` | Confirm restoration. |
| GET | `/admin/collections/<id>/history` | Changes/activity list with filters. |
| GET | `/admin/collections/<id>/history/<event_id>` | Before/after and event details. |
| GET | `/admin/collections/<id>/editors` | Current unexpired editors. |

An admin blueprint resolves collections directly by their explicit catalog UUID;
the current public-route collection selector must not fall back to a different
collection for an admin request. In single-database mode, accept only that
store's actual UUID. Unknown collections/events/Trash IDs give 404 rather than
leaking another collection's record. GET navigation never performs password
changes or restores content. POST failures keep content unchanged.

## Implementation structure

1. Extend AccessControl's credential/session methods to accept an explicit role,
   retaining fail-closed global editor behavior and existing login/lease APIs.
   Reuse the credential-linked session table with role-aware resolution; its
   current `editor_sessions` name need not force a table rename. Store separate
   editor/admin bearer references in Flask's session. Add the local admin command.
2. Add a small access-database admin-audit table for successful password changes,
   without secrets. Collection recoveries continue to use that collection's
   `edit_history`; avoid a second, non-atomic restoration log in another file.
3. Add an `admin.py` blueprint and `templates/admin/` pages. Reuse the current
   store/catalog services and security headers; admin handlers have their own
   admin-grant/CSRF checks and do not require the browser's Edit mode preference.
4. Add bounded Trash preview and SQL history filtering/pagination helpers. Reuse
   existing transactional restoration, lease cleanup, snapshots, and content
   versioning rather than adding another set of content writes or lock state.
5. Test role separation, bootstrap/reset, revoked grants, CSRF, credential-change
   races, safe rendering, collection isolation, double restoration, parent-first
   recovery, timezone filters/pagination, and JavaScript-disabled navigation.
   Run the existing editor/auth/lock/live-update/export regressions too.

The first version covers passwords, Trash/recovery, history, and active editors.
A later iteration can move collection creation/import into administration, using
a separate upload flow and appropriate workbook-size limits; the current public
request body limit is only 64 KiB. Collection-specific passwords, row/column
schema editors, permanent deletion, history revert, personal accounts, and
browser backup/restore are separate future tasks.

## Acceptance examples

- An anonymous visitor or someone with only the edit password cannot view admin
  history/Trash or submit an admin POST, even by typing its URL directly.
- The local admin command enables login without changing any existing edit
  credential, content, history, or Trash entry.
- Changing the edit password revokes editor grants and old draft saves, retains
  the administrator login, and records no secret in any audit/snapshot.
- Changing the admin password revokes every admin grant but leaves independent
  editor grants valid; only the new admin password works afterward.
- A restoration preserves the original content/formatting/IDs, is attributed to
  the admin name, and appears automatically in already-open collection views.
- A row whose etymon is deleted receives a parent-first explanation; repeated
  restoration does not duplicate rows. Another collection cannot be targeted by
  substituting an event/Trash ID or by changing tabs.
- Cancelled/expired sessions are distinguishable from saved edits. History
  filters and page links do not skip filtering just because a dataset is large.
- Text resembling HTML in a cell/name is displayed as text rather than executing
  as admin-page markup. Password/session/lease secrets remain absent from pages.
- All screens and confirmation workflows work with JavaScript disabled. Closing
  a browser session or signing out ends admin access according to the existing
  session-cookie behavior; explicit sign-out also defeats session restoration.

## Verification

`tests/test_admin.py` covers role separation, local bootstrap, credential migration,
password/grant revocation, CSRF, stale forms, password-change races, atomic audit
rollback, collection scoping, safe rendering, parent-first/double recovery,
activity versus saved changes, SQL pagination, and daylight-saving date filters.
`tests/test_admin_browser.js` exercises the HTML interface with JavaScript disabled
alongside a real editor: recovery triggers live updates, password resets preserve
rejected drafts, and administrator password changes do not revoke editors.
Desktop/mobile screenshots of working pages were visually reviewed.

Access schema 2 adds only the admin password-event audit table; existing credential
role/scope fields and the session table are reused. Collection schema remains 7.
Trash previews are limited to 200 cells, with full counts and complete restoration.
The static preview is kept unchanged as a reference.
