"""Set the global edit password locally; passwords are never command arguments."""

import argparse
from getpass import getpass
from pathlib import Path
import sqlite3

from access_control import AccessControl


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=Path('data/access.sqlite3'), help='Access database (default: data/access.sqlite3).')
    parser.add_argument('command', choices=['set-edit-password'])
    args = parser.parse_args(argv)
    try:
        password = getpass('Global edit password: ')
        if password != getpass('Repeat password: '):
            parser.error('The passwords do not match; nothing was changed.')
        access = AccessControl(args.database)
        try:
            access.set_edit_password(password)
        finally:
            access.close()
    except (EOFError, KeyboardInterrupt):
        parser.exit(1, '\nCancelled; password was not changed.\n')
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.error(str(error))
    print('Global edit password set. Existing edit logins have been signed out.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
