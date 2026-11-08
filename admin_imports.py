"""Private, expiring workbook uploads for the plain HTML import wizard."""

from i18n import gettext as _

from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path
import re
from secrets import token_hex
import shutil
from threading import RLock
import time
from xml.parsers import expat
from zipfile import ZipFile

from openpyxl import load_workbook


class WorkbookUploads:
    def __init__(self, directory, config):
        self.directory = Path(directory)
        self.config = config
        self.lock = RLock()

    def _cleanup(self):
        if not self.directory.exists():
            return
        for directory in self.directory.iterdir():
            if re.fullmatch(r'[a-f0-9]{64}',directory.name) and directory.is_dir():
                if time.time()-directory.stat().st_mtime > self.config['COLLECTION_UPLOAD_TTL_SECONDS']:
                    shutil.rmtree(directory)

    @staticmethod
    def _owner(context):
        return sha256(context.encode()).hexdigest()

    def stage(self, upload, context):
        with self.lock:
            self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
            self._cleanup()
            if len(list(self.directory.iterdir())) >= self.config['COLLECTION_UPLOAD_MAX_PENDING']:
                raise ValueError(_('Too many pending uploads. Finish or cancel an import, or try again after 30 minutes.'))
            name = (upload.filename or '').replace('\\','/').rsplit('/',1)[-1]
            if (Path(name).suffix.lower() not in ('.xlsx','.xlsm') or len(name)>200 or
                    any(ord(char)<32 or ord(char)==127 for char in name)):
                raise ValueError(_('Choose an .xlsx or .xlsm workbook with a filename of at most 200 characters.'))
            token = token_hex(32)
            directory = self.directory/token
            directory.mkdir(mode=0o700)
            try:
                path = directory/name
                total = 0
                with path.open('xb') as output:
                    while chunk := upload.stream.read(64*1024):
                        total += len(chunk)
                        if total > self.config['COLLECTION_UPLOAD_MAX_BYTES']:
                            raise ValueError(_('The workbook exceeds the configured upload limit.'))
                        output.write(chunk)
                bounds = self._validate_archive(path)
                book = load_workbook(path,read_only=True,keep_links=False)
                try:
                    sheets = [sheet.title for sheet in book.worksheets]
                    if not sheets:
                        raise ValueError(_('The workbook has no worksheets.'))
                    dimensions = {}
                    for sheet in book.worksheets:
                        # Pinned openpyxl's read-only path identifies the ZIP
                        # part. Actual XML bounds also cover missing or false
                        # <dimension> declarations in uploaded worksheets.
                        actual = bounds.get(sheet._worksheet_path.lstrip('/'),(0,0))
                        dimensions[sheet.title] = [max(sheet.max_row or 0,actual[0]),
                                                   max(sheet.max_column or 0,actual[1])]
                finally:
                    book.close()
                record = {'filename':name,'sheets':sheets,'dimensions':dimensions,'owner':self._owner(context)}
                (directory/'upload.json').write_text(json.dumps(record),encoding='utf-8')
                return token
            except BaseException:
                shutil.rmtree(directory)
                raise

    def _validate_archive(self, path):
        with ZipFile(path) as archive:
            members = archive.infolist()
            if (len(members)>self.config['COLLECTION_UPLOAD_MAX_MEMBERS'] or
                    sum(item.file_size for item in members)>self.config['COLLECTION_UPLOAD_MAX_EXPANDED_BYTES']):
                raise ValueError(_('The expanded workbook exceeds the configured import limits.'))
            names = [item.filename for item in members]
            if len(set(names)) != len(names) or any(item.flag_bits & 1 for item in members):
                raise ValueError(_('Encrypted workbooks and duplicate archive members are not supported.'))
            if '[Content_Types].xml' not in names or 'xl/workbook.xml' not in names:
                raise ValueError(_('This file is not an Excel workbook.'))
            # Reject DTD/entity declarations before openpyxl parses any XML,
            # including UTF-16 XML. Expat streams under the expanded-size bound.
            cells = 0
            bounds = {}
            row_bound = column_bound = current_column = 0
            def declaration(*args):
                raise ValueError(_('Workbook XML must not contain DTD or entity declarations.'))
            def element(name, attributes):
                nonlocal cells, row_bound, column_bound, current_column
                local = name.rsplit('}',1)[-1]
                if local=='row':
                    value = attributes.get('r',str(row_bound+1))
                    if not value.isdigit() or not 1<=int(value)<=100000:
                        raise ValueError(_('Browser imports support worksheet rows up to 100000. Use a smaller workbook.'))
                    row_bound = max(row_bound,int(value))
                    current_column = 0
                if local=='c':
                    cells += 1
                    if cells > self.config['COLLECTION_UPLOAD_MAX_CELLS']:
                        raise ValueError(_('The workbook contains too many cells for a browser import.'))
                    if 'r' in attributes:
                        coordinate = re.fullmatch(r'([A-Z]{1,3})([1-9][0-9]{0,5})',attributes['r'])
                        if coordinate is None:
                            raise ValueError(_('The workbook contains an invalid or oversized cell coordinate.'))
                        column = 0
                        for character in coordinate[1]:
                            column = column*26+ord(character)-ord('A')+1
                        if column>256 or int(coordinate[2])>100000:
                            raise ValueError(_('Browser imports support at most 100000 worksheet rows and 256 columns.'))
                        current_column = column
                        row_bound = max(row_bound,int(coordinate[2]))
                    else:
                        current_column += 1
                    column_bound = max(column_bound,current_column)
                    if column_bound>256:
                        raise ValueError(_('Browser imports support at most 256 worksheet columns.'))
            for item in members:
                with archive.open(item) as source:
                    first = source.read(64*1024)
                    # Relationships may point at XML parts with unconventional
                    # extensions. Inspect XML signatures as well as filenames.
                    signature = first.lstrip(b' \t\r\n')
                    if (not item.filename.lower().endswith(('.xml','.rels')) and
                            not signature.startswith((b'<',b'\xef\xbb\xbf',b'\xff\xfe',b'\xfe\xff',b'\x00'))):
                        continue
                    parser = expat.ParserCreate(namespace_separator='}')
                    parser.StartDoctypeDeclHandler = declaration
                    parser.EntityDeclHandler = declaration
                    parser.ExternalEntityRefHandler = declaration
                    parser.StartElementHandler = element
                    row_bound = column_bound = current_column = 0
                    parser.Parse(first,False)
                    while chunk := source.read(64*1024):
                        parser.Parse(chunk,False)
                    parser.Parse(b'',True)
                    bounds[item.filename.lstrip('/')] = (row_bound,column_bound)
            return bounds

    @contextmanager
    def pending(self, token, context):
        # Serialize cleanup/consumption so two tabs cannot import one upload
        # twice or remove it while another request is reading it.
        with self.lock:
            self._cleanup()
            if not re.fullmatch(r'[a-f0-9]{64}',token):
                raise ValueError(_('This upload is unavailable. Upload the workbook again.'))
            directory = self.directory/token
            try:
                record = json.loads((directory/'upload.json').read_text(encoding='utf-8'))
            except (FileNotFoundError,json.JSONDecodeError):
                raise ValueError(_('This upload expired or was already used. Upload the workbook again.')) from None
            if record['owner'] != self._owner(context):
                raise ValueError(_('This upload belongs to another administrator login. Upload the workbook again.'))
            yield record, directory/record['filename']

    def discard(self, token):
        with self.lock:
            if re.fullmatch(r'[a-f0-9]{64}',token):
                shutil.rmtree(self.directory/token,ignore_errors=True)

    def validate_sheet(self, record, sheet):
        if sheet not in record['sheets']:
            raise ValueError(_('Choose a worksheet from this workbook.'))
        rows, columns = record['dimensions'][sheet]
        if rows>100000 or columns>256 or rows*columns>self.config['COLLECTION_UPLOAD_MAX_GRID_CELLS']:
            raise ValueError(_('This worksheet is too large for a browser import (100000 rows, 256 columns, or the configured grid limit).'))
