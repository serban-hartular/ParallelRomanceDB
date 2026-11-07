"""Local administration of independent Parallel Words collections."""

import argparse
from pathlib import Path
import sqlite3
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

from openpyxl.utils.exceptions import InvalidFileException

from collection_catalog import CollectionCatalog


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, default=Path('data/catalog.sqlite3'))
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('list', help='List collection IDs, names, and database paths.')
    create = commands.add_parser('create', help='Create an empty collection or import one Excel sheet.')
    create.add_argument('name')
    create.add_argument('--workbook', type=Path)
    create.add_argument('--sheet')
    register = commands.add_parser('register', help='Register an existing collection using the new schema.')
    register.add_argument('name')
    register.add_argument('database', type=Path)
    args = parser.parse_args(argv)
    try:
        catalog = CollectionCatalog(args.catalog)
        try:
            if args.command=='list':
                for entry in catalog.collections():
                    print(f"{entry['id']} · {entry['name']} · {entry['database_path']}")
            else:
                entry = (catalog.create(args.name,args.workbook,args.sheet) if args.command=='create'
                         else catalog.register(args.name,args.database))
                print(f"{entry['id']} · {entry['name']} · {entry['database_path']}")
        finally:
            catalog.close()
    except (OSError,ValueError,sqlite3.Error,BadZipFile,InvalidFileException,ParseError,KeyError) as error:
        parser.error(str(error))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
