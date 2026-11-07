"""Export SQLite edits into the original workbook, without rewriting untouched parts."""

from copy import copy
from datetime import datetime
from html.parser import HTMLParser
from io import BytesIO
import math
import os
from pathlib import Path
import posixpath
import re
from tempfile import NamedTemporaryFile
from xml.dom import minidom
from xml.etree import ElementTree
from zipfile import ZipFile
from zoneinfo import ZoneInfo

from openpyxl import load_workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.styles import Font
from openpyxl.utils import column_index_from_string, get_column_letter


# Match the grid/editor's unformatted text (12 CSS px = 9 pt). Imported
# formatting is explicit in the HTML; a newly typed bare run must not inherit
# the workbook cell's old font, color, bold, etc.
EDITOR_FONT = Font(name='Segoe UI', sz=9, color='FF253B35')


class _RichText(HTMLParser):
    def __init__(self, html, base_font):
        super().__init__(convert_charrefs=True)
        self.fonts = [InlineFont(
            rFont=base_font.name, sz=base_font.sz, b=base_font.b, i=base_font.i,
            color=copy(base_font.color), u=base_font.u, strike=base_font.strike,
            vertAlign=base_font.vertAlign,
        )]
        self.parts = []
        self.feed(html)
        self.close()

    def handle_starttag(self, tag, attrs):
        if tag == 'br':
            self.handle_data('\n')
            return
        font = copy(self.fonts[-1])
        styles = dict(part.split(':', 1) for part in dict(attrs).get('style', '').split(';') if ':' in part)
        styles = {key.strip(): value.strip() for key, value in styles.items()}
        if 'font-family' in styles:
            font.rFont = styles['font-family'].split(',')[0].strip(' "\'')
        size = styles.get('font-size', '')
        if re.fullmatch(r'\d+(?:\.\d+)?(?:pt|px)', size):
            font.sz = float(size[:-2]) * (0.75 if size.endswith('px') else 1)
        if 'font-weight' in styles:
            font.b = styles['font-weight'] == 'bold'
        if 'font-style' in styles:
            font.i = styles['font-style'] == 'italic'
        if 'text-decoration-line' in styles:
            decorations = styles['text-decoration-line']
            font.u = ('double' if styles.get('text-decoration-style') == 'double' else 'single') if 'underline' in decorations else None
            font.strike = 'line-through' in decorations
        if 'vertical-align' in styles:
            font.vertAlign = {'super': 'superscript', 'sub': 'subscript'}.get(styles['vertical-align'])
        color = styles.get('color', '')
        if color.startswith('#'):
            value = color[1:]
            if len(value) == 3:
                value = ''.join(character * 2 for character in value)
            font.color = 'FF' + value.upper()
        elif color.startswith('rgb('):
            values = re.findall(r'\d+', color)
            font.color = 'FF' + ''.join(f'{int(value):02X}' for value in values)
        self.fonts.append(font)

    def handle_endtag(self, tag):
        if tag != 'br' and len(self.fonts) > 1:
            self.fonts.pop()

    def handle_data(self, text):
        if text:
            self.parts.append(TextBlock(copy(self.fonts[-1]), text))


def html_to_rich_text(html, base_font=None):
    return CellRichText(_RichText(html, base_font or EDITOR_FONT).parts)


def _rich_text_tree(value):
    """Serialize complete run styles and preserve even whitespace-only runs.

    openpyxl omits xml:space on whitespace-only text. Excel can then treat a
    newline-only run as empty and repair its string properties on opening.
    It also omits false bold/italic and no-underline properties, which would
    otherwise inherit the old cell style instead of the editor's defaults.
    """
    tree = value.to_tree()
    for run, block in zip(tree, value):
        properties = run.find('rPr')
        if isinstance(block, TextBlock):
            for name, setting in (
                ('b', '1' if block.font.b else '0'),
                ('i', '1' if block.font.i else '0'),
                ('strike', '1' if block.font.strike else '0'),
                ('u', block.font.u or 'none'),
                ('vertAlign', block.font.vertAlign or 'baseline'),
            ):
                item = properties.find(name)
                if item is None:
                    item = ElementTree.SubElement(properties, name)
                item.set('val', setting)
        run.find('t').set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
    return tree


def _worksheet_part(archive, title):
    workbook = ElementTree.fromstring(archive.read('xl/workbook.xml'))
    ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    relationships = ElementTree.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
    targets = {item.attrib['Id']: item.attrib['Target'] for item in relationships}
    for sheet in workbook.findall('s:sheets/s:sheet', ns):
        if sheet.attrib['name'] == title:
            identifier = sheet.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']
            target = targets[identifier]
            return posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join('xl', target))
    raise ValueError(f'Worksheet {title!r} is absent from the saved template.')


def workbook_bytes(store):
    """Return the complete imported workbook with a consistent snapshot of edits.

    Only modified worksheet cells/row heights are patched. Unchanged workbook
    ZIP members (including other sheets, drawings and macros) remain intact.
    """
    snapshot = store.export_snapshot()
    template = snapshot['dataset']['workbook']
    changed = [cell for cell in snapshot['cells'] if cell['revision']]
    deleted = any(row.get('trash_id') is not None for row in snapshot['rows'])
    renamed = any(column['name'] != column.get('source_name', column['name']) for column in snapshot['columns'])
    if not changed and not deleted and not renamed:
        return template
    title = snapshot['dataset']['sheet_name']
    if any(row['source_row'] is None for row in snapshot['rows']):
        from excel_rows import insert_workbook_rows
        with ZipFile(BytesIO(template)) as archive:
            part = _worksheet_part(archive, title)
        template = insert_workbook_rows(template, snapshot, part)
    workbook = load_workbook(BytesIO(template), rich_text=True)
    sheet = workbook[title]
    try:
        with ZipFile(BytesIO(template)) as archive:
            part = _worksheet_part(archive, title)
            document = minidom.parseString(archive.read(part))
            namespace = document.documentElement.namespaceURI
            prefix = document.documentElement.prefix
            def element(name):
                return document.createElementNS(namespace, f'{prefix}:{name}' if prefix else name)
            data = document.getElementsByTagNameNS(namespace, 'sheetData')[0]
            rows = {int(row.getAttribute('r')): row for row in data.childNodes if row.nodeType == row.ELEMENT_NODE and row.localName == 'row'}

            def target_cell(number, column):
                if number not in rows:
                    row = element('row')
                    row.setAttribute('r', str(number))
                    following = next((item for key, item in sorted(rows.items()) if key > number), None)
                    data.insertBefore(row, following)
                    rows[number] = row
                row = rows[number]
                address = f'{get_column_letter(column)}{number}'
                children = [item for item in row.childNodes if item.nodeType == item.ELEMENT_NODE and item.localName == 'c']
                existing = next((item for item in children if item.getAttribute('r') == address), None)
                if existing is not None:
                    return existing
                cell = element('c')
                cell.setAttribute('r', address)
                following = next((item for item in children if column_index_from_string(re.match(r'[A-Z]+', item.getAttribute('r'))[0]) > column), None)
                row.insertBefore(cell, following)
                return cell

            def set_text(cell, value):
                for child in list(cell.childNodes):
                    if child.nodeType == child.ELEMENT_NODE and child.localName in ('v', 'f', 'is'):
                        cell.removeChild(child)
                cell.setAttribute('t', 'inlineStr')
                tree = _rich_text_tree(value) if isinstance(value, CellRichText) else ElementTree.fromstring('<is><t/></is>')
                if not isinstance(value, CellRichText):
                    tree[0].text = value
                    tree[0].set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
                def convert(node):
                    result = element(node.tag.rsplit('}', 1)[-1])
                    for name, text in node.attrib.items():
                        if name == '{http://www.w3.org/XML/1998/namespace}space':
                            result.setAttributeNS('http://www.w3.org/XML/1998/namespace', 'xml:space', text)
                        else:
                            result.setAttribute(name, text)
                    if node.text:
                        result.appendChild(document.createTextNode(node.text))
                    for child in node:
                        result.appendChild(convert(child))
                    return result
                cell.appendChild(convert(tree))

            columns = {column['name']: column['sheet_column'] for column in snapshot['columns']}
            positions = {(row['etimon_number'], row['label'], row['label_number']): row['sheet_row'] for row in snapshot['rows']}
            for name, column in columns.items():
                if sheet.cell(1, column).value != name:
                    set_text(target_cell(1, column), name)
            for record in changed:
                number = positions[(record['etimon_number'], record['label'], record['label_number'])]
                column = columns[record['column']]
                value = html_to_rich_text(record['content'])
                set_text(target_cell(number, column), value if value else '')
                # Excel has no CSS line-height. Give edited multiline content
                # adequate row height; exact line spacing remains in SQLite.
                if record['line_height'] is not None and record['plaintext_content']:
                    font_size = max((block.font.sz or 11 for block in value if isinstance(block, TextBlock)), default=11)
                    width = sheet.column_dimensions[get_column_letter(column)].width or 13
                    lines = sum(max(1, math.ceil(len(line) / max(1, width))) for line in record['plaintext_content'].split('\n'))
                    height = min(409, lines * font_size * record['line_height'] + 4)
                    row = rows[number]
                    row.setAttribute('ht', str(max(float(row.getAttribute('ht') or sheet.sheet_format.defaultRowHeight or 15), height)))
                    row.setAttribute('customHeight', '1')
            # Adding a formerly absent language column can expand the used area.
            dimension = document.getElementsByTagNameNS(namespace, 'dimension')
            if dimension:
                dimension[0].setAttribute('ref', f'A1:{get_column_letter(max(sheet.max_column, max(columns.values(), default=1)))}{max(sheet.max_row, max(rows, default=1))}')
            output = BytesIO()
            with ZipFile(output, 'w') as exported:
                exported.comment = archive.comment
                for member in archive.infolist():
                    exported.writestr(member, document.toxml(encoding='utf-8') if member.filename == part else archive.read(member.filename))
            payload = output.getvalue()
            if deleted:
                from excel_rows import insert_workbook_rows
                payload = insert_workbook_rows(payload, snapshot, part, deleting=True)
            return payload
    finally:
        workbook.close()


def _write_atomic(path, payload, *, overwrite=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(dir=path.parent, prefix='.parallel-words-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.chmod(temporary, path.stat().st_mode & 0o777)
            os.replace(temporary, path)
        else:
            os.link(temporary, path)  # Atomic creation; an existing file is never replaced.
        return path
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def export_timestamped(store, directory, *, now=None):
    """Create a new full workbook, with local date/time and offset in its name."""
    source = Path(store.metadata['source_name'])
    stamp = (now or datetime.now(ZoneInfo('Europe/Bucharest'))).strftime('%Y-%m-%d_%H-%M-%S_%f%z')
    payload = workbook_bytes(store)
    for sequence in range(1000):
        suffix = f'_{sequence}' if sequence else ''
        path = Path(directory) / f'{source.stem}_{stamp}{suffix}{source.suffix}'
        try:
            return _write_atomic(path, payload)
        except FileExistsError:
            continue
    raise FileExistsError('Could not allocate a new timestamped export filename.')


def overwrite_sheet(store, workbook_path, *, sheet_name=None):
    """Explicitly replace one existing worksheet, retaining other sheets.

    This opt-in helper uses openpyxl's supported worksheet features. The normal
    timestamped export instead patches the original archive without rewriting
    unrelated parts. This function is never called by the website.
    """
    path = Path(workbook_path)
    title = sheet_name or store.metadata['sheet_name']
    source = load_workbook(BytesIO(workbook_bytes(store)), rich_text=True)
    target = None
    try:
        target = load_workbook(path, rich_text=True, keep_vba=path.suffix.lower() == '.xlsm')
        if title not in target.sheetnames:
            raise ValueError(f'Worksheet {title!r} does not exist in {path.name}.')
        original = source[store.metadata['sheet_name']]
        sheet = target[title]
        for merged in list(sheet.merged_cells.ranges):
            sheet.unmerge_cells(str(merged))
        sheet.delete_rows(1, sheet.max_row)
        sheet.row_dimensions.clear()
        sheet.column_dimensions.clear()
        for row in original:
            for cell in row:
                destination = sheet.cell(cell.row, cell.column, copy(cell.value))
                destination.data_type = cell.data_type
                destination.font = copy(cell.font)
                destination.fill = copy(cell.fill)
                destination.border = copy(cell.border)
                destination.alignment = copy(cell.alignment)
                destination.number_format = cell.number_format
                destination.protection = copy(cell.protection)
                destination.comment = copy(cell.comment)
                if cell.hyperlink:
                    destination.hyperlink = copy(cell.hyperlink)
        for name in ('row_dimensions', 'column_dimensions'):
            for key, value in getattr(original, name).items():
                dimension = type(value)(sheet, index=key)
                for attribute in ('hidden', 'outlineLevel', 'collapsed', 'height', 'thickTop', 'thickBot', 'width', 'min', 'max', 'bestFit'):
                    if hasattr(value, attribute):
                        setattr(dimension, attribute, getattr(value, attribute))
                for attribute in ('font', 'fill', 'border', 'alignment', 'number_format', 'protection'):
                    setattr(dimension, attribute, copy(getattr(value, attribute)))
                getattr(sheet, name)[key] = dimension
        for merged in original.merged_cells.ranges:
            sheet.merge_cells(str(merged))
        sheet.freeze_panes = original.freeze_panes
        sheet.print_title_rows = original.print_title_rows
        sheet.print_title_cols = original.print_title_cols
        for name in ('sheet_format', 'sheet_properties', 'print_options', 'page_margins', 'page_setup', 'protection', 'auto_filter', 'data_validations', 'conditional_formatting'):
            setattr(sheet, name, copy(getattr(original, name)))
        output = BytesIO()
        target.save(output)
        return _write_atomic(path, output.getvalue(), overwrite=True)
    finally:
        source.close()
        if target is not None:
            target.close()
