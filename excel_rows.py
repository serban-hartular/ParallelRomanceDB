"""Insert/remove database rows in workbook XML, retaining unrelated ZIP parts."""

from bisect import bisect_right
from io import BytesIO
import posixpath
import re
from xml.dom import minidom
from xml.etree import ElementTree
from zipfile import ZipFile

from openpyxl.formula.tokenizer import Tokenizer
from openpyxl.utils import column_index_from_string, get_column_letter


class RowInsertion:
    def __init__(self, positions, title):
        self.positions = sorted(positions)
        self.title = title

    def number(self, number):
        for position in self.positions:
            if number >= position:
                number += 1
        if number > 1048576:
            raise ValueError('Adding rows would exceed the Excel worksheet row limit.')
        return number

    def reference(self, reference):
        """Shift A1 references, ranges and whole-row ranges, retaining $ signs."""
        def address(value):
            match = re.fullmatch(r'(\$?[A-Z]{1,3})?(\$?)([1-9]\d*)', value, re.IGNORECASE)
            if not match:
                return value
            return f'{match[1] or ""}{match[2]}{self.number(int(match[3]))}'
        return ' '.join(':'.join(address(value) for value in area.split(':')) for area in reference.split(' '))

    def formula(self, expression, current_sheet=None):
        if not expression:
            return expression
        equals = expression.startswith('=')
        tokens = Tokenizer(expression if equals else '=' + expression).items
        result = []
        changed = False
        for token in tokens:
            value = token.value
            if token.type == 'OPERAND' and token.subtype == 'RANGE':
                prefix, separator, reference = value.rpartition('!')
                sheet = prefix.strip("'").replace("''", "'") if separator else current_sheet
                # Names and structured/external/3-D references stay untouched.
                if sheet is not None and sheet.casefold() == self.title.casefold():
                    shifted = self.reference(reference if separator else value)
                    replacement = prefix + separator + shifted if separator else shifted
                    changed = changed or replacement != value
                    value = replacement
            result.append(value)
        return ('=' if equals else '') + ''.join(result) if changed else expression


class RowRemoval(RowInsertion):
    def __init__(self, positions, title):
        super().__init__(positions, title)
        self.removed = set(self.positions)

    def number(self, number):
        return max(1, number - bisect_right(self.positions, number))

    def reference(self, reference):
        """Shrink ranges; a direct reference to a removed cell becomes #REF!."""
        removed = self.removed
        def area(value):
            addresses = value.split(':')
            matches = [re.fullmatch(r'(\$?[A-Z]{1,3})?(\$?)([1-9]\d*)', item, re.IGNORECASE) for item in addresses]
            if not all(matches) or len(matches) > 2:
                return value
            numbers = [int(match[3]) for match in matches]
            if len(numbers) == 1:
                if numbers[0] in removed:
                    return '#REF!'
            else:
                start, end = sorted(numbers)
                while start in removed and start <= end:
                    start += 1
                while end in removed and end >= start:
                    end -= 1
                if start > end:
                    return '#REF!'
                numbers = [start, end] if numbers[0] <= numbers[1] else [end, start]
            return ':'.join(f'{match[1] or ""}{match[2]}{self.number(number)}' for match, number in zip(matches, numbers))
        areas = [area(value) for value in reference.split(' ')]
        return ' '.join(value for value in areas if value != '#REF!') or '#REF!'


def insert_workbook_rows(template, snapshot, part, *, deleting=False):
    added = [] if deleting else [row for row in snapshot['rows'] if row['source_row'] is None]
    removed = {row['sheet_row'] for row in snapshot['rows'] if row.get('trash_id') is not None} if deleting else set()
    if not added and not removed:
        return template
    shift = (RowRemoval(removed, snapshot['dataset']['sheet_name']) if deleting else
             RowInsertion([row['sheet_row'] for row in added], snapshot['dataset']['sheet_name']))
    with ZipFile(BytesIO(template)) as archive:
        documents = {}

        def document(name):
            if name not in documents:
                documents[name] = minidom.parseString(archive.read(name))
            return documents[name]

        sheet = document(part)
        namespace = sheet.documentElement.namespaceURI
        prefix = sheet.documentElement.prefix

        def element(name):
            return sheet.createElementNS(namespace, f'{prefix}:{name}' if prefix else name)

        def write_label(row, label):
            number = row.getAttribute('r')
            cell = next((item for item in row.childNodes if item.nodeType == item.ELEMENT_NODE
                         and item.localName == 'c' and item.getAttribute('r') == f'A{number}'), None)
            if cell is None:
                cell = element('c')
                cell.setAttribute('r', f'A{number}')
                row.insertBefore(cell, row.firstChild)
            for child in list(cell.childNodes):
                cell.removeChild(child)
            cell.setAttribute('t', 'inlineStr')
            inline, text = element('is'), element('t')
            text.setAttributeNS('http://www.w3.org/XML/1998/namespace', 'xml:space', 'preserve')
            text.appendChild(sheet.createTextNode(label))
            inline.appendChild(text)
            cell.appendChild(inline)

        data = sheet.getElementsByTagNameNS(namespace, 'sheetData')[0]
        shared = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            for item in ElementTree.fromstring(archive.read('xl/sharedStrings.xml')):
                shared.append(''.join(item.itertext()))

        if deleting:
            # Label-only/blank rows are not DB records, but belong to the
            # etymon section too. Remove these along with a trashed etymon.
            current, start = None, None
            trashed_etymons = set(snapshot.get('trashed_etymons', ()))
            insertion = RowInsertion([row['sheet_row'] for row in snapshot['rows'] if row['source_row'] is None], shift.title)
            marker_types = {item['id'] for item in snapshot['row_types'] if item['is_etymon']}
            markers = {}
            for etymon in snapshot['etymons']:
                position = insertion.number(etymon['source_row']) if etymon['source_row'] is not None else next(
                    row['sheet_row'] for row in snapshot['rows']
                    if row['etimon_number']==etymon['id'] and row['row_type_id'] in marker_types)
                markers[position] = etymon['id']
            last = 1
            for row in data.childNodes:
                if row.nodeType != row.ELEMENT_NODE or row.localName != 'row':
                    continue
                number = int(row.getAttribute('r'))
                last = max(last, number)
                if number in markers:
                    if current in trashed_etymons:
                        removed.update(range(start, number))
                    current = markers[number]
                    start = number
            if current in trashed_etymons:
                removed.update(range(start, last + 1))
            shift = RowRemoval(removed, snapshot['dataset']['sheet_name'])
            for row in list(data.childNodes):
                if row.nodeType == row.ELEMENT_NODE and row.localName == 'row' and int(row.getAttribute('r')) in removed:
                    data.removeChild(row)
        style_cache = {}

        def bordered_style(style_id):
            """Complete new cells' outlines without changing existing styles."""
            if style_id in style_cache:
                return style_cache[style_id]
            styles = document('xl/styles.xml')
            root = styles.documentElement
            style_namespace = root.namespaceURI
            style_prefix = root.prefix
            def style_element(name):
                return styles.createElementNS(style_namespace, f'{style_prefix}:{name}' if style_prefix else name)
            borders = root.getElementsByTagNameNS(style_namespace, 'borders')[0]
            formats = root.getElementsByTagNameNS(style_namespace, 'cellXfs')[0]
            border_list = [item for item in borders.childNodes if item.nodeType == item.ELEMENT_NODE]
            format_list = [item for item in formats.childNodes if item.nodeType == item.ELEMENT_NODE]
            base = format_list[style_id]
            border = border_list[int(base.getAttribute('borderId') or 0)]
            edges = {item.localName: item for item in border.childNodes if item.nodeType == item.ELEMENT_NODE}
            sides = ('left', 'right', 'top', 'bottom')
            if all(edges.get(side) is not None and edges[side].getAttribute('style') for side in sides) and base.getAttribute('applyBorder') != '0':
                style_cache[style_id] = style_id
                return style_id
            completed = border.cloneNode(deep=True)
            order = ('start', 'end', *sides, 'diagonal', 'vertical', 'horizontal')
            for side in sides:
                old = next((item for item in completed.childNodes if item.nodeType == item.ELEMENT_NODE and item.localName == side), None)
                if old is not None and old.getAttribute('style'):
                    continue
                opposite = {'left': 'right', 'right': 'left', 'top': 'bottom', 'bottom': 'top'}[side]
                candidates = [edges[name] for name in (opposite, *sides) if name in edges and edges[name].getAttribute('style')]
                if not candidates:
                    candidates = [edge for item in border_list for edge in item.childNodes
                                  if edge.nodeType == edge.ELEMENT_NODE and edge.localName == side and edge.getAttribute('style')]
                edge = style_element(side)
                if candidates:
                    donor = candidates[0]
                    for key, value in donor.attributes.items():
                        edge.setAttribute(key, value)
                    for child in donor.childNodes:
                        edge.appendChild(child.cloneNode(deep=True))
                else:
                    edge.setAttribute('style', 'thin')
                    color = style_element('color')
                    color.setAttribute('auto', '1')
                    edge.appendChild(color)
                if old is not None:
                    completed.replaceChild(edge, old)
                else:
                    following = next((item for item in completed.childNodes if item.nodeType == item.ELEMENT_NODE
                                      and item.localName in order and order.index(item.localName) > order.index(side)), None)
                    completed.insertBefore(edge, following)
            borders.appendChild(completed)
            borders.setAttribute('count', str(len(border_list) + 1))
            updated = base.cloneNode(deep=True)
            updated.setAttribute('borderId', str(len(border_list)))
            updated.setAttribute('applyBorder', '1')
            formats.appendChild(updated)
            formats.setAttribute('count', str(len(format_list) + 1))
            style_cache[style_id] = len(format_list)
            return len(format_list)

        fill_style_cache = {}
        fill_cache = {}

        def filled_style(style_id, color):
            """Use the saved row color, retaining all other style properties."""
            if not color:
                return style_id
            key = (style_id, color)
            if key in fill_style_cache:
                return fill_style_cache[key]
            styles = document('xl/styles.xml')
            root = styles.documentElement
            ns, prefix = root.namespaceURI, root.prefix
            def style_element(name):
                return styles.createElementNS(ns, f'{prefix}:{name}' if prefix else name)
            fills = root.getElementsByTagNameNS(ns, 'fills')[0]
            if color not in fill_cache:
                fill_cache[color] = len([item for item in fills.childNodes if item.nodeType == item.ELEMENT_NODE])
                fill, pattern = style_element('fill'), style_element('patternFill')
                pattern.setAttribute('patternType', 'solid')
                foreground = style_element('fgColor')
                foreground.setAttribute('rgb', 'FF' + color.lstrip('#'))
                pattern.appendChild(foreground)
                fill.appendChild(pattern)
                fills.appendChild(fill)
                fills.setAttribute('count', str(fill_cache[color] + 1))
            formats = root.getElementsByTagNameNS(ns, 'cellXfs')[0]
            format_list = [item for item in formats.childNodes if item.nodeType == item.ELEMENT_NODE]
            updated = format_list[style_id].cloneNode(deep=True)
            updated.setAttribute('fillId', str(fill_cache[color]))
            updated.setAttribute('applyFill', '1')
            formats.appendChild(updated)
            formats.setAttribute('count', str(len(format_list) + 1))
            fill_style_cache[key] = len(format_list)
            return len(format_list)

        donor_rows = {row['style_row'] for row in added if row['style_row'] is not None}
        # deepcopy follows DOM parent/sibling/document links and can recurse
        # through the entire worksheet. Clone only the donor subtrees instead.
        originals = {int(row.getAttribute('r')): row.cloneNode(deep=True) for row in data.childNodes
                     if row.nodeType == row.ELEMENT_NODE and row.localName == 'row'
                     and int(row.getAttribute('r')) in donor_rows}

        # Discover coordinate-bearing parts owned by the selected worksheet.
        owned = {part}
        rels = posixpath.join(posixpath.dirname(part), '_rels', posixpath.basename(part) + '.rels')
        if rels in archive.namelist():
            for relation in ElementTree.fromstring(archive.read(rels)):
                if relation.get('TargetMode') != 'External':
                    target = relation.get('Target', '')
                    target = posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join(posixpath.dirname(part), target))
                    if target in archive.namelist():
                        owned.add(target)

        for name in archive.namelist():
            relevant = name in owned or name == 'xl/workbook.xml' or name == 'xl/calcChain.xml' or name.startswith(('xl/worksheets/', 'xl/charts/')) and name.endswith('.xml')
            if not relevant:
                continue
            doc = document(name)
            modified = name == part
            worksheet = name.startswith('xl/worksheets/') and name.endswith('.xml')
            current_sheet = shift.title if name == part else None
            if worksheet and name != part:
                # Unqualified references in other sheets must not move.
                current_sheet = ''
            chain_sheet = None
            target_id = None
            if name == 'xl/calcChain.xml':
                target_id = next(item.getAttribute('sheetId') for item in document('xl/workbook.xml').getElementsByTagNameNS(namespace, 'sheet')
                                 if item.getAttribute('name') == shift.title)
            for node in list(doc.getElementsByTagName('*')):
                if node.parentNode is None:
                    continue
                if name == part:
                    if node.localName == 'row' and node.hasAttribute('r'):
                        node.setAttribute('r', str(shift.number(int(node.getAttribute('r')))))
                    elif node.localName == 'c' and node.hasAttribute('r'):
                        node.setAttribute('r', shift.reference(node.getAttribute('r')))
                if name in owned:
                    for attribute in ('ref', 'sqref', 'activeCell', 'topLeftCell'):
                        if node.hasAttribute(attribute):
                            before = node.getAttribute(attribute)
                            after = shift.reference(before)
                            if deleting and after == '#REF!':
                                if attribute in ('activeCell', 'topLeftCell'):
                                    after = re.sub(r'\d+', lambda match: str(shift.number(int(match[0]))), before)
                                elif node.localName == 'dimension':
                                    after = 'A1'
                                else:
                                    node.parentNode.removeChild(node)
                                    modified = True
                                    break
                            if after != before:
                                node.setAttribute(attribute, after)
                                modified = True
                    if node.parentNode is None:
                        continue
                    # Drawing and VML anchors use zero-based row coordinates.
                    if node.localName in ('row', 'Row') and not node.hasAttribute('r') and node.firstChild and node.firstChild.nodeType == node.TEXT_NODE:
                        text = node.firstChild.data
                        if text.isdigit():
                            node.firstChild.data = str(shift.number(int(text) + 1) - 1)
                            modified = True
                    if node.localName == 'brk' and node.parentNode.localName == 'rowBreaks' and node.hasAttribute('id'):
                        node.setAttribute('id', str(shift.number(int(node.getAttribute('id')))))
                        modified = True
                    if node.localName == 'hyperlink' and node.hasAttribute('location'):
                        before = node.getAttribute('location')
                        after = shift.formula(before, current_sheet)
                        if before != after:
                            node.setAttribute('location', after)
                            modified = True
                    if node.localName == 'Anchor' and node.firstChild:
                        values = node.firstChild.data.split(',')
                        if len(values) == 8 and all(value.strip().isdigit() for value in values):
                            for index in (2, 6):
                                values[index] = str(shift.number(int(values[index]) + 1) - 1)
                            node.firstChild.data = ', '.join(value.strip() for value in values)
                            modified = True
                if name == 'xl/calcChain.xml' and node.localName == 'c':
                    if node.hasAttribute('i'):
                        chain_sheet = node.getAttribute('i')
                    if chain_sheet == target_id:
                        address = shift.reference(node.getAttribute('r'))
                        if address == '#REF!':
                            node.parentNode.removeChild(node)
                            modified = True
                            continue
                        node.setAttribute('r', address)
                        modified = True
                if node.localName in ('f', 'formula', 'formula1', 'formula2', 'definedName') and node.firstChild and node.firstChild.nodeType == node.TEXT_NODE:
                    before = node.firstChild.data
                    scope = current_sheet
                    if node.localName == 'definedName' and node.hasAttribute('localSheetId'):
                        sheets = doc.getElementsByTagNameNS(namespace, 'sheet')
                        index = int(node.getAttribute('localSheetId'))
                        scope = sheets[index].getAttribute('name') if index < len(sheets) else None
                    after = shift.formula(before, scope)
                    if before != after:
                        node.firstChild.data = after
                        modified = True
            if not modified:
                documents.pop(name, None)
            elif deleting:
                for container_name, child_name in (('mergeCells', 'mergeCell'), ('dataValidations', 'dataValidation'), ('rowBreaks', 'brk')):
                    for container in doc.getElementsByTagNameNS(namespace, container_name):
                        count = len(container.getElementsByTagNameNS(namespace, child_name))
                        if count:
                            container.setAttribute('count', str(count))
                        else:
                            container.parentNode.removeChild(container)

        # Insert only style/layout attributes from a matching source row.
        for record in sorted(added, key=lambda row: row['sheet_row']):
            number = record['sheet_row']
            donor = originals.get(record['style_row'])
            row = element('row')
            if donor:
                for key, value in donor.attributes.items():
                    if key not in ('r', 'spans'):
                        row.setAttribute(key, value)
                for old in donor.childNodes:
                    if old.nodeType == old.ELEMENT_NODE and old.localName == 'c':
                        cell = element('c')
                        column = re.match(r'[A-Z]+', old.getAttribute('r'))[0]
                        cell.setAttribute('r', f'{column}{number}')
                        if old.hasAttribute('s'):
                            cell.setAttribute('s', old.getAttribute('s'))
                        row.appendChild(cell)
            row.setAttribute('r', str(number))
            # Merged source cells often omit interior/top borders. New rows
            # are independent cells, so complete the outline of every field.
            for column in sorted({1, *(item['sheet_column'] for item in snapshot['columns'])}):
                address = f'{get_column_letter(column)}{number}'
                cell = next((item for item in row.childNodes if item.getAttribute('r') == address), None)
                if cell is None:
                    cell = element('c')
                    cell.setAttribute('r', address)
                    following = next((item for item in row.childNodes if item.nodeType == item.ELEMENT_NODE
                                      and column_index_from_string(re.match(r'[A-Z]+', item.getAttribute('r'))[0]) > column), None)
                    row.insertBefore(cell, following)
                style_id = int(cell.getAttribute('s') or row.getAttribute('s') or 0)
                cell.setAttribute('s', str(filled_style(bordered_style(style_id), record['background_color'])))
            write_label(row, record['label'])
            following = next((item for item in data.childNodes if item.nodeType == item.ELEMENT_NODE
                              and item.localName == 'row' and int(item.getAttribute('r')) > number), None)
            data.insertBefore(row, following)

        # Inserting a different category after an existing label-only row must
        # not relabel the following original rows that inherit its blank A cell.
        metadata = {(shift.number(row['sheet_row']) if deleting else row['sheet_row']): row
                    for row in snapshot['rows'] if not deleting or row.get('trash_id') is None}
        inserted = {row['sheet_row']: row for row in added}
        inherited = None
        for row in data.childNodes:
            if row.nodeType != row.ELEMENT_NODE or row.localName != 'row':
                continue
            number = int(row.getAttribute('r'))
            if number in inserted:
                inherited = inserted[number]['label']
                continue
            cell = next((item for item in row.childNodes if item.nodeType == item.ELEMENT_NODE
                         and item.localName == 'c' and item.getAttribute('r') == f'A{number}'), None)
            value = ''
            if cell is not None:
                nodes = cell.getElementsByTagNameNS(namespace, 'v') or cell.getElementsByTagNameNS(namespace, 't') or cell.getElementsByTagNameNS(namespace, 'f')
                value = ''.join(node.firstChild.data for node in nodes if node.firstChild)
                if cell.getAttribute('t') == 's' and value.isdigit():
                    value = shared[int(value)]
            if value.strip():
                inherited = value if deleting else None
            elif number in metadata and (deleting or inherited is not None) and metadata[number]['label'] != inherited:
                write_label(row, metadata[number]['label'])
                if deleting:
                    cell = next(item for item in row.childNodes if item.nodeType == item.ELEMENT_NODE
                                and item.localName == 'c' and item.getAttribute('r') == f'A{number}')
                    cell.setAttribute('s', str(filled_style(int(cell.getAttribute('s') or 0), metadata[number]['background_color'])))
                inherited = metadata[number]['label'] if deleting else None

        workbook = document('xl/workbook.xml')
        calculations = workbook.getElementsByTagNameNS(namespace, 'calcPr')
        if calculations:
            calculations[0].setAttribute('fullCalcOnLoad', '1')
            calculations[0].setAttribute('forceFullCalc', '1')
        output = BytesIO()
        with ZipFile(output, 'w') as exported:
            exported.comment = archive.comment
            for member in archive.infolist():
                doc = documents.get(member.filename)
                exported.writestr(member, doc.toxml(encoding='utf-8') if doc else archive.read(member.filename))
        return output.getvalue()
