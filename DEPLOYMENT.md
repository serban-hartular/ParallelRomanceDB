# Running Parallel Words on another machine

Status (2026-11-07): the user reports remote editing and export work. The new
collection catalog, schema-7 live updates/leases/history, global edit authentication,
and `/admin/` interface have been tested locally only; these changes have not
been deployed remotely by the coding agent. Read [HANDOFF.md](HANDOFF.md) for
current contracts and [README.md](README.md) for import and collection commands.
Use one application process while editor-token signing remains process-specific.

Schema-4/5/6 collections upgrade automatically to schema 7, adding history/lifecycle
fields and content versioning without changing existing content/IDs/Trash. The
access database upgrades from schema 1 to 2 for administrator password-change
audit events. The catalog upgrades additively from schema 1 to 2 for recoverable
collection removal and collection-event attribution. Back up before updating.
Schema versions 1–3 still require a fresh collection import; export saved edits
with the previous version first if needed. Never replace the old files during
reimport. Earlier edits cannot gain retroactive author names.

Install `requirements.txt` into a virtual environment on the destination machine.
After pulling this search update, install the new pinned `regex` dependency and
restart the application:

```bash
.venv/bin/python -m pip install -r requirements.txt
```

Regex search requires no database migration or additional Nginx configuration.
Its request time budget is `SEARCH_REGEX_TIMEOUT_SECONDS` in `config.py`.

The `main.py` command uses **Waitress**, a production WSGI server, for both local
and public access. Do not use `flask run`, `app.run()`, or Flask's debugger for a
remote deployment. See [Flask's deployment guidance](https://flask.palletsprojects.com/en/stable/deploying/).

## Addresses and ports

```bash
# Local access only; these two commands are equivalent.
.venv/bin/python main.py
.venv/bin/python main.py --local --port 5000

# Import collections locally before serving; use actual paths and sheet names.
.venv/bin/python manage_collections.py --catalog /var/lib/parallel-words/catalog.sqlite3 create "Gastronomy" --workbook /srv/lexicon.xlsx --sheet Sheet1
.venv/bin/python manage_collections.py --catalog /var/lib/parallel-words/catalog.sqlite3 create "Fashion"

# Set the shared edit password locally (hidden prompts), using the service account.
.venv/bin/python manage_access.py --database /var/lib/parallel-words/access.sqlite3 set-edit-password

# Direct access from other machines, serving the registered collections.
.venv/bin/python main.py --catalog /var/lib/parallel-words/catalog.sqlite3 --public --port 8080

# Restrict binding to one network interface instead of all interfaces.
.venv/bin/python main.py --catalog /var/lib/parallel-words/catalog.sqlite3 --host 192.0.2.10 --port 8080
```

`--local` binds `127.0.0.1`; `--public` binds `0.0.0.0` (all IPv4 interfaces).
`--host` accepts a specific IPv4 or IPv6 address. These three flags are mutually
exclusive. Ports must be 1–65535 and default to 5000. Other machines open
`http://SERVER-IP:8080`, not `http://0.0.0.0:8080`. Public binding alone does not
open a firewall, cloud security group, router/NAT, or container port mapping.
Permit only the intended networks/ports. IPv6 exposure must be configured separately.

For public use, add `--trusted-host words.example.org`, replacing the example
with the hostname people will use. Repeat the option for additional names or
IP addresses. Do not include a scheme, path, or port. This validates the HTTP
`Host` header; it does **not** restrict who may connect. `TRUSTED_HOSTS` in
`config.py` provides the same setting; the CLI list overrides it. By default,
hostnames are unrestricted so local/IP access works without configuration.

Browsing, search, and full Excel download remain public for every registered
collection. Editing requires the global edit password and a self-declared name;
the server checks the authenticated grant on every save, creation, and deletion.
Search filters and hidden columns do not restrict reading. For private workbook
content, use a VPN or require authentication for all routes at the proxy.
Use HTTPS for Internet access, including the login form and downloads.

The access database defaults to `access.sqlite3` beside the catalog; configure
another location with `--auth-database PATH` (or `AUTH_DATABASE_PATH` in config.py).
Point `manage_access.py --database PATH set-edit-password` at that same file.
Password changes revoke all edit logins immediately, without a restart. An
unconfigured password disables editing. The command prompts twice with hidden
input; do not pass passwords as shell arguments, environment values, or source.

The header provides **Who is editing?**, the signed-in name, **Change editor**,
and **Sign out**. Authentication uses a browser-session cookie with no persistent
expiry/remember-me setting. Session restoration in some browsers can restore
cookies; Sign out revokes the server-side grant even for restored cookies.
Keep `FLASK_SECRET_KEY` stable to retain open browser logins over server restart;
open cell draft tokens still expire when the process restarts; Cancel can release
their old locks, otherwise those locks expire after five minutes without contact. Per-collection passwords
remain future work. A separate global administrator role is enabled at `/admin/`.

## Administrator setup

After installing this version, initialize the separate administrator password
locally, using the service account and the same access file as the application:

```bash
.venv/bin/python manage_access.py --database /var/lib/parallel-words/access.sqlite3 set-admin-password
```

Do not pass a password on the command line; this prompts with hidden input.
No administrator password is installed automatically, and there is no public
first-admin registration form. Use the command again for forgotten-password
recovery. It revokes only administrator grants; edit grants remain independent.

Restart the app to load the new code, then open `https://YOUR-HOST/admin/`, or
use **Admin** in the header. An existing proxy forwarding `/` to this Flask app
already covers the admin routes. Do not add a public static mapping to database
files or the source directory. Use the existing HTTPS/secure-cookie/trusted-proxy
configuration for the login and all admin pages. The same application port is used.

Admin pages use ordinary HTML and do not need JavaScript. They cover global
password management, collection-specific Trash/recovery, history, and active
editors. All are protected by the separate admin grant; POSTs also require CSRF.
Changing the edit password signs out editors; changing the admin password signs
out administrators, including the current browser, while independent edit logins
remain valid. Responses are no-store. Admin → Collections now creates empty
collections and imports uploaded Excel worksheets. Collections Trash hides and
restores whole collections while retaining their database files and original
identities. Active editors block removal. Names in Collections Trash remain
reserved. There is no permanent purge or history-revert action.

The access schema-1-to-2 upgrade is additive, retains credentials/grants, and
records successful password-change metadata without secrets in `admin_events`.
Admin recoveries use the existing collection history and live updates. Back up
the access file together with the catalog and collection files as before.

## HTTPS and proxy headers

Waitress does not terminate TLS. Run an HTTPS reverse proxy such as Nginx in
front of it, keeping the app bound to localhost. This command assumes exactly
one proxy connecting from `127.0.0.1`:

```bash
.venv/bin/python main.py --catalog /var/lib/parallel-words/catalog.sqlite3 --local --port 8080 \
  --export-dir /var/lib/parallel-words/exports \
  --trusted-host words.example.org --trusted-proxy 127.0.0.1 --secure-cookies
```

`--secure-cookies` requires HTTPS at the browser; it does not enable TLS on
Waitress. It enables the cookie's `Secure` flag and a one-year HSTS response
header on HTTPS requests. Cookies already use `HttpOnly` and `SameSite=Lax`.
Once HSTS is received, browsers expect HTTPS for that hostname. Keep this
option off for ordinary local HTTP testing.

The CLI clears untrusted forwarding headers. With `--trusted-proxy IP`, only
that exact socket peer can supply `X-Forwarded-For` and `X-Forwarded-Proto`,
with one trusted hop. Forwarded host/port and RFC `Forwarded` headers are not
trusted. Pass the original hostname using `Host`. Never trust arbitrary client
addresses or a wildcard proxy, and do not add `ProxyFix` on top of this setup.
For a different proxy machine, bind to a private interface, trust that machine's
IP, and firewall the backend so clients cannot bypass the proxy. Multi-proxy
chains and hosting under a URL subpath require separate configuration; these
examples serve at `/`. See [Waitress's proxy documentation](https://docs.pylonsproject.org/projects/waitress/en/stable/reverse-proxy.html).

Example Nginx configuration for a hostname with an existing, valid certificate;
replace the hostname and certificate paths. Add this to Nginx's HTTP
configuration using the layout provided by your operating system:

```nginx
server {
    listen 80;
    server_name words.example.org;
    return 301 https://words.example.org$request_uri;
}

server {
    listen 443 ssl;
    server_name words.example.org;
    ssl_certificate /etc/letsencrypt/live/words.example.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/words.example.org/privkey.pem;
    client_max_body_size 26m;  # 25 MiB workbook plus multipart overhead; Flask limits other routes to 64 KiB.

    location / {
        # For private data, configure authentication here (for every route),
        # or make this hostname accessible only through your VPN.
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header Connection "";
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Forwarded "";
        proxy_set_header X-Forwarded-Host "";
        proxy_set_header X-Forwarded-Port "";
        proxy_connect_timeout 5s;
        proxy_read_timeout 60s;
        proxy_cache off;
    }
}
```

The proxy overwrites client-supplied scheme/address headers rather than passing
them through. Preserve `HX-Request`, cookies, `Vary`, and `Cache-Control` headers.
Do not cache the workspace: it depends on each browser's signed session, and
htmx requests receive fragments instead of complete pages. All assets are
bundled locally; no CORS allowance is needed. Proxy header configuration follows
the [Nginx proxy module documentation](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_set_header).
Validate with `nginx -t` before reloading on the destination machine. These
instructions do not provision a certificate, configure authentication, or open
any firewall ports automatically.

## Process, secrets, and filesystem permissions

Run as a dedicated **unprivileged** account. Use a port above 1023 and let the
proxy listen on 80/443. The account needs read access to the selected workbook,
code, configuration, templates, and static files, execute access to Python,
and traversal permission on their parent directories. The web app does not
need to write the source workbook or project directory. It now needs a separate
writable directory for SQLite (including its journal) and timestamped exports,
for example `/var/lib/parallel-words`. When launching outside systemd, create
that directory with ownership for the service account first. Set `--catalog` and `--export-dir` explicitly. Collection files live in
`collections/` beside the catalog; single exports use a per-collection subdirectory,
and multi-collection exports use `exports/combined/` (also beneath --export-dir).
The account needs write access to the catalog, its directory, collection files
and directory, and export directories, including SQLite journal files. Browser imports also create a private `imports/`
directory beside the catalog for temporary uploads. The access database and
its directory must also be writable; newly created access files are owner-only. Keep code/configuration and source workbooks owned by an administrator;
do not use `chmod 777`. A typical arrangement is `/opt/parallel-words` for code
and `/srv/parallel-words` for workbooks, with group-readable files and directories
traversable by the service account. Avoid serving the project directory as a
web root: only Flask's `static/` is intended for direct file access.

Set a stable, random `FLASK_SECRET_KEY` in the service environment. Generate a
value with `python3 -c 'import secrets; print(secrets.token_hex(32))'` and store
it outside Git in a protected service environment file. Without it, a fresh
random key is generated each startup and existing browser preferences reset.
In catalog mode, signed cookies contain opaque browser/login identifiers and a CSRF token;
search/mode/selection preferences live in the catalog, separately per browser
and collection. Single-file mode still stores preferences in the signed cookie.
Cookies are signed, not encrypted. Search terms also appear in GET URLs and may be
recorded by proxy access logs/browser history. Restrict log access and retention
if queries are sensitive.

For example, after creating an `xldb` account, installing the app/venv under
`/opt/parallel-words`, and preparing a root-readable `/etc/parallel-words.env`
containing `FLASK_SECRET_KEY=YOUR_GENERATED_VALUE`, a systemd service can use:

```ini
[Unit]
Description=Parallel Words
After=network.target

[Service]
User=xldb
Group=xldb
WorkingDirectory=/opt/parallel-words
EnvironmentFile=/etc/parallel-words.env
Environment=PYTHONDONTWRITEBYTECODE=1
StateDirectory=parallel-words
ReadWritePaths=/var/lib/parallel-words
ExecStart=/opt/parallel-words/.venv/bin/python /opt/parallel-words/main.py --catalog /var/lib/parallel-words/catalog.sqlite3 --export-dir /var/lib/parallel-words/exports --local --port 8080 --trusted-host words.example.org --trusted-proxy 127.0.0.1 --secure-cookies
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
UMask=0077

[Install]
WantedBy=multi-user.target
```

Create/register collections locally or create/import them through administration after starting the service. Adapt paths and
create the venv on the destination rather
than copying the development venv. `ProtectHome=true` intentionally prevents
loading files from `/home`; place the deployment outside it. The read-only
filesystem protection permits temporary buffers in the service's private `/tmp`
and persistent SQLite/export writes in the dedicated state directory.
See [systemd's execution settings](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html).

## Limits and verification

- The CLI disables debug/testing mode and traceback exposure. Browser headers
  restrict scripts/connections to the same origin, prevent framing and MIME
  sniffing, and limit referrer sharing. Inline CSS remains allowed for imported
  Excel formatting and table sizing. htmx evaluation and history caching are
  disabled. Workbook text is escaped by the importer.
- The CLI caps headers at 16 KiB. Waitress permits
  `COLLECTION_UPLOAD_MAX_BYTES + 64 KiB` request bodies (25 MiB plus form overhead
  by default). Flask allows that size only at `/admin/collections/import`; other
  routes retain their 64 KiB cap. Set Nginx `client_max_body_size` to at least
  the configured upload size plus overhead (26m for the default). After changing
  the Python configuration, restart the app; validate/reload Nginx separately.
  No remote proxy configuration is changed by updating the source.
  The CLI caps idle connections at
  30 seconds, and concurrent connections at 100, using four worker threads.
  See [Waitress's settings](https://docs.pylonsproject.org/projects/waitress/en/latest/arguments.html).
  Application limits in `config.py` cap query strings at 8 KiB and search terms
  at 500 characters; unknown column/label filter values are rejected. These are
  bounds, not a rate limiter. Apply proxy rate limits/network restrictions for
  public traffic.
- Excel is imported only when initializing a database. Restarts reopen SQLite,
  preserving edits even if the original workbook is absent. Source changes
  are not automatically reimported. Normal export uses the saved workbook
  template and creates a new timestamped full workbook. Back up the catalog,
  access database, and every collection database using SQLite backup tools,
  or stop the app before copying them. The catalog contains absolute collection
  paths; after restoring to a different directory, update these paths or register
  the restored files in a new catalog. Large workbooks
  and exports still need memory/CPU; there is no pagination or job queue.
- Catalog routes use `/collections/<UUID>/` and the same prefix for GET
  `/export` and POST `/mode`, `/cell`, `/rows`, `/etymons`, `/trash`. Collection
  identity is explicit on every request and edit/delete token; unscoped writes
  are rejected. Modes/preferences are separate per collection, but these are
  isolation checks. Every reachable visitor can read/export every registered
  collection; a global edit login grants writes to all collections.
- Edit mode enables saves, creation, and recoverable deletion. Changes require
  browser-session CSRF and signed revision/identity tokens where applicable.
  The server validates Quill operations instead of accepting supplied HTML;
  stale saves/deletes are rejected. A global edit login is required for content
  writes. Exclusive cell leases block same-cell edits and row/etymon deletion,
  naming the owner; inline notices warn about other cells in the same row/etymon. Creation
  requires initial text in the collection's configured column (French by default).
- Collection creation/import are available in administrator-only HTML forms
  in catalog mode. Uploads accept `.xlsx`/`.xlsm`, keep the whole workbook, and
  import one selected worksheet into a new uniquely named collection. Expanded
  archives default to 100 MiB/2,000 members/500,000 populated cells; selected
  sheet grids are capped at 2,000,000 cells, with at most 100,000 rows and 256
  columns. DTD/entity XML and encrypted/duplicate-member archives are rejected.
  At most ten uploads may be pending globally. They expire after 30 minutes and
  are removed on the next upload/import request; successful import and Cancel
  remove them immediately. Uploads are private and bound to the admin login.
  Collections Trash retains database files, preferences, and history. Include
  removed collections in backups; do not delete their files from `collections/`.
  Local creation/import commands remain available. Row/etymon Trash recovery is
  available in the protected admin interface and through the local CLI. Run
  `manage_collections.py --catalog PATH create NAME [--workbook FILE --sheet NAME]`
  with the service account's file permissions. Run `trash.py COLLECTION_DB list`
  or `restore ID` against the appropriate collection file. Never expose these
  scripts or databases through Nginx's document root.
- Collection schema 7 records active editing and saved attribution together,
  including start/contact/expiry/finish times, target IDs, and before/after snapshots.
  Schemas 4/5/6 upgrade
  automatically; versions 1–3 require a fresh workbook import. History stays in
  its collection DB, separate from credentials/sessions in the access DB.
  Inspect locally with `history.py COLLECTION_DB [--etymon N] [--sessions] [--json]`.
  Default history lists actual changes; --sessions includes other editing outcomes.
- Login failures are limited to ten per client IP in five minutes per process.
  This is an in-process limit; keep the documented single-process deployment.
  Credential changes and Sign out revoke server-side grants, and editor tokens
  are bound to the login identity that opened them. Stale tabs may show controls
  until refreshed, but unauthenticated or misattributed saves are rejected.

## Existing HTTPS site on the same machine

The user's reported host, `capibara.hopto.org`, already serves another site on
443 via Nginx, with a valid certificate. Its previous port 8080 listener was
plain Waitress HTTP. Changing the URL to `https://capibara.hopto.org:8080/` does
not enable TLS and cannot work with that listener. Chrome's insecure-download
warning is addressed by serving both the app and exports over HTTPS.

Keep the existing site intact. Either use another HTTPS hostname with its own
Nginx server block, or configure a separate Nginx TLS listener on a selected
external port, proxying to a different loopback-only Waitress port. For example,
if using external 8080 for HTTPS, first move Waitress to `127.0.0.1:8081`; the
Nginx server then listens on `8080 ssl`, uses the existing certificate paths,
and proxies to `http://127.0.0.1:8081`. Use the proxy headers from the example
above and the corresponding trusted-host/proxy/secure-cookie CLI options.
Check the actual complete Nginx configuration and port availability before
changing listeners; test the configuration before reload. These are deployment
instructions, not changes applied to the remote machine by this milestone.

## Active cell leases

Open editors contact the server every 30 seconds, independent of typing. A lease
expires after five minutes without contact; this also handles closed tabs,
sleep, crashes, or interrupted connections. Close/Cancel attempt release at once.
Keep /collections/<UUID>/cell/start, /cell/heartbeat, and /cell/finish reachable
through the same HTTPS proxy with cookies/CSRF headers intact. Do not cache these
responses or introduce proxy timeouts that interrupt short heartbeat requests.

Lease ownership and saved history share one collection-local database record.
SQLite write transactions plus an active-cell unique index enforce exclusion;
no separate locking service/daemon is required. Collections remain independent.
Schema upgrades retain existing content and saved history. Back up the collection
databases as before. Password resets/sign-out revoke active ownership on the next
lock/history operation. Server restarts preserve records, while old signed editor
tokens fail; users copy their draft and cancel/reload. Lost locks never overwrite
another person's work, and the browser retains a selectable draft with Save disabled.
