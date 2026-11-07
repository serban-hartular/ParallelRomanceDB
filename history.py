"""Read a collection's edit attribution and saved changes locally."""

import argparse
import json
from pathlib import Path
import sqlite3

from lexicon_db import LexiconDB


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path)
    parser.add_argument('--etymon', type=int)
    parser.add_argument('--limit', type=int, default=100)
    parser.add_argument('--sessions',action='store_true',help='Include active, cancelled, unchanged, expired, and revoked editing sessions.')
    parser.add_argument('--json', action='store_true', help='Include before/after content snapshots.')
    args = parser.parse_args(argv)
    if not args.database.is_file():
        parser.error('The collection database does not exist.')
    try:
        store = LexiconDB(args.database)
        try:
            entries = store.edit_history(args.etymon,args.limit,include_sessions=args.sessions)
        finally:
            store.close()
        if args.json:
            print(json.dumps(entries,ensure_ascii=False,indent=2))
        else:
            if not entries:
                print('No edit history yet.')
            for entry in entries:
                row = f" · {entry['label']} #{entry['label_number']}" if entry['label'] else ''
                column = f" · {entry['column_name']}" if entry['column_name'] else ''
                print(f"{entry['id']} · {entry['occurred_at']} · {entry['editor_name']} · {entry['action']} ({entry['status']})"
                      f" · etymon {entry['etimon_number']}{row}{column}")
    except (OSError,ValueError,sqlite3.Error) as error:
        parser.error(str(error))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
