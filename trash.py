"""Local administrator commands for listing and restoring deleted entries."""

import argparse
from pathlib import Path
import sqlite3

from lexicon_db import LexiconDB


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path, help='An existing Parallel Words SQLite database.')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('list', help='List items awaiting recovery.')
    restore = commands.add_parser('restore', help='Restore all rows/cells in one Trash entry.')
    restore.add_argument('id', type=int, help='Trash ID shown by list.')
    args = parser.parse_args(argv)
    if not args.database.is_file():
        parser.error('The database file does not exist.')
    try:
        store = LexiconDB(args.database)
        try:
            if args.command == 'list':
                entries = store.list_trash()
                if not entries:
                    print('Trash is empty.')
                for entry in entries:
                    row = f" · {entry['label']} #{entry['label_number']}" if entry['kind'] == 'row' else ''
                    print(f"{entry['id']} · {entry['deleted_at']} · etymon {entry['etimon_number']}: "
                          f"{entry['title']}{row} · {entry['row_count']} row(s)")
            else:
                entry = store.restore_trash(args.id)
                print(f"Restored Trash entry {args.id} ({entry['kind']}, etymon {entry['etimon_number']}). "
                      'Refresh the browser to see it.')
        finally:
            store.close()
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.error(str(error))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
