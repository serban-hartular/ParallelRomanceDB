# Running Parallel Words on another machine

Status (2026-11-05): the user reports a successful remote deployment of the
previous browsing version. The latest local-only stage stores edits in SQLite
and exports full updated workbooks. Saved edits survive restarts. Keep one
application process while editor-token signing remains process-specific. Remote
deployment of these persistence changes has not been verified here. Read [HANDOFF.md](HANDOFF.md) for the development state and
continuation prompt, and [README.md](README.md) for workbook usage.

Install `requirements.txt` into a virtual environment on the destination machine.
The `main.py` command uses **Waitress**, a production WSGI server, for both local
and public access. Do not use `flask run`, `app.run()`, or Flask's debugger for a
remote deployment. See [Flask's deployment guidance](https://flask.palletsprojects.com/en/stable/deploying/).

## Addresses and ports

```bash
# Local access only; these two commands are equivalent.
.venv/bin/python main.py
.venv/bin/python main.py --local --port 5000

# Direct access from other machines, using a selected workbook/sheet.
.venv/bin/python main.py /srv/lexicon.xlsx --sheet Sheet1 --public --port 8080

# Restrict binding to one network interface instead of all interfaces.
.venv/bin/python main.py /srv/lexicon.xlsx --host 192.0.2.10 --port 8080
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

**There is no login or authorization. Every reachable user can browse/search
the entire loaded worksheet.** Hiding columns, search filters, and `HX-Request`
headers do not restrict access. For private data, use a VPN or authenticate all
requests at a reverse proxy. **Every reachable visitor can also edit the shared
database content and export full workbooks; there are no separate editing permissions.** Direct HTTP leaves traffic and cookies
unencrypted; use HTTPS for Internet access.

## HTTPS and proxy headers

Waitress does not terminate TLS. Run an HTTPS reverse proxy such as Nginx in
front of it, keeping the app bound to localhost. This command assumes exactly
one proxy connecting from `127.0.0.1`:

```bash
.venv/bin/python main.py /srv/lexicon.xlsx --local --port 8080 \
  --database /var/lib/parallel-words/research.sqlite3 \
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
    client_max_body_size 64k;

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
that directory with ownership for the service account first. Set `--database`
and `--export-dir` explicitly rather than using a sidecar beside a read-only
source workbook. Keep code/configuration and source workbooks owned by an administrator;
do not use `chmod 777`. A typical arrangement is `/opt/parallel-words` for code
and `/srv/parallel-words` for workbooks, with group-readable files and directories
traversable by the service account. Avoid serving the project directory as a
web root: only Flask's `static/` is intended for direct file access.

Set a stable, random `FLASK_SECRET_KEY` in the service environment. Generate a
value with `python3 -c 'import secrets; print(secrets.token_hex(32))'` and store
it outside Git in a protected service environment file. Without it, a fresh
random key is generated each startup and existing browser preferences reset.
Signed cookies contain preferences/search terms, not workbook contents; they
are signed, not encrypted. Search terms also appear in GET URLs and may be
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
ExecStart=/opt/parallel-words/.venv/bin/python /opt/parallel-words/main.py /srv/parallel-words/lexicon.xlsx --database /var/lib/parallel-words/research.sqlite3 --export-dir /var/lib/parallel-words/exports --local --port 8080 --trusted-host words.example.org --trusted-proxy 127.0.0.1 --secure-cookies
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

Adapt paths and the sheet option, and create the venv on the destination rather
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
- The CLI caps headers at 16 KiB, request bodies at 64 KiB, idle connections at
  30 seconds, and concurrent connections at 100, using four worker threads.
  See [Waitress's settings](https://docs.pylonsproject.org/projects/waitress/en/latest/arguments.html).
  Application limits in `config.py` cap query strings at 8 KiB and search terms
  at 500 characters; unknown column/label filter values are rejected. These are
  bounds, not a rate limiter. Apply proxy rate limits/network restrictions for
  public traffic.
- Excel is imported only when initializing a database. Restarts reopen SQLite,
  preserving edits even if the original workbook is absent. Source changes
  are not automatically reimported. Normal export uses the saved workbook
  template and creates a new timestamped full workbook. Back up the database
  using SQLite backup tools, or stop the app before copying it. Large workbooks
  and exports still need memory/CPU; there is no pagination or job queue.
- The app exposes browsing/static routes, GET `/export`, POST `/mode`, POST `/cell`,
  POST `/rows`, and POST `/etymons`. It starts in Search mode; Edit mode enables
  cell saves and entry creation. Modes are session preferences, not authorization.
  Edits require a session-bound CSRF token and a signed cell/revision token.
  Creation and mode changes require the CSRF token; new entries require French text.
  The server accepts validated text/format operations rather than HTML,
  rejects stale saves, and uses transactions to keep SQLite consistent.
  These checks do not authenticate visitors. Keep one application process
  for the current editor-token implementation. Source workbooks and the
  project directory still need no write permissions; the state directory does.
- Existing SQLite databases upgrade to schema version 2 on startup without
  reimporting the workbook. Back up the database before updating the service.

Before opening access, verify from a second machine that HTTPS, any required
authentication, searches, selection, highlighting, and scrolling work. Check
that port 8080 cannot bypass the proxy, unapproved `Host` headers are rejected,
and `/db/lexicon.xlsx`, `/.git/config`, and `/config.py` are not served. Review
service/proxy logs for errors without exposing secrets. The automated suite
tests the request boundaries, and a loopback HTTP smoke check exercises Waitress;
the user reports the previous remote deployment works. The editing changes
have been tested with local Waitress and Chromium, not against that deployment.
