"""Application settings. Restart the app after changing this file."""

# Search-match background color, as #RGB or #RRGGBB. Standard highlight yellow.
SEARCH_HIGHLIGHT_COLOR = '#ffff00'

# Seed backgrounds for a new collection, sampled from the original workbook.
# Each collection stores its own row type defaults in SQLite after creation.
# Changing this mapping affects newly initialized collections only.
# Use the canonical row labels here; workbook spelling/spacing is preserved.
ROW_BACKGROUND_COLORS = {
    'ETIMON/ CORESPONDENTE ROMANICE': '#D9E2F3',  # Blue
    'SENSURI DE BAZĂ': '#F7CAAC',  # Orange
    'EXTENSII SEMANTICE (METAFORIZĂRI,  METONIMII)': '#FEF2CB',  # Yellow
    'SENSURI SPECIALIZATE': '#B7E1CD',  # Green
}

# Set to the public hostname(s), e.g. ['words.example.org'], to reject other
# Host headers. CLI --trusted-host overrides this list. None accepts any host.
TRUSTED_HOSTS = None

# Enable only behind HTTPS; CLI --secure-cookies also enables this setting.
SESSION_COOKIE_SECURE = False

# Global credential/session store. None uses access.sqlite3 beside the catalog
# (or the single collection database); CLI --auth-database overrides it.
# Set the password with manage_access.py, never in this file.
AUTH_DATABASE_PATH = None

# Open editors renew their lock independently of typing or mouse activity.
EDIT_HEARTBEAT_SECONDS = 30
EDIT_LEASE_SECONDS = 300

# Browsing tabs check for committed content changes, including local recovery.
LIVE_REFRESH_SECONDS = 5

# Edits are stored in SQLite; there are no upload endpoints. Waitress limits
# incoming bodies to 64 KiB and headers to 16 KiB in main.py.
MAX_CONTENT_LENGTH = 64 * 1024
MAX_QUERY_STRING_LENGTH = 8 * 1024
MAX_SEARCH_LENGTH = 500
