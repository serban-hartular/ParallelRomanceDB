"""Application settings. Restart the app after changing this file."""

# Search-match background color, as #RGB or #RRGGBB. Standard highlight yellow.
SEARCH_HIGHLIGHT_COLOR = '#ffff00'

# Set to the public hostname(s), e.g. ['words.example.org'], to reject other
# Host headers. CLI --trusted-host overrides this list. None accepts any host.
TRUSTED_HOSTS = None

# Enable only behind HTTPS; CLI --secure-cookies also enables this setting.
SESSION_COOKIE_SECURE = False

# This read-only application has no upload endpoints. Waitress also limits
# incoming bodies to 64 KiB and headers to 16 KiB in main.py.
MAX_CONTENT_LENGTH = 64 * 1024
MAX_QUERY_STRING_LENGTH = 8 * 1024
MAX_SEARCH_LENGTH = 500
