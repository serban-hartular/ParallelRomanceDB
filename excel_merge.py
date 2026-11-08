"""Combine selected worksheet packages without reserializing their cell contents."""

from i18n import gettext as _

from io import BytesIO
from decimal import Decimal
import posixpath
import re
from types import SimpleNamespace
from xml.dom import minidom
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

from openpyxl import Workbook
from openpyxl.formula.tokenizer import Tokenizer, TokenizerError
from openpyxl.styles import Color
from openpyxl.styles.numbers import BUILTIN_FORMATS, is_datetime

from extract_sheet import _color_resolver


S = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
P = 'http://schemas.openxmlformats.org/package/2006/relationships'
C = 'http://schemas.openxmlformats.org/package/2006/content-types'
A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
STYLE_ORDER = ('numFmts','fonts','fills','borders','cellStyleXfs','cellXfs','cellStyles','dxfs','tableStyles','colors','extLst')


def children(node, name=None):
    return [item for item in node.childNodes if item.nodeType==item.ELEMENT_NODE and
            (name is None or item.localName==name)]


def sheet_titles(names):
    """Excel tab names are limited, case-insensitively unique, and independent of labels."""
    used, titles = set(), []
    for name in names:
        stem = re.sub(r'[\[\]:*?/\\\x00-\x1f]', '_',name).strip("'") or 'Collection'
        if stem.casefold()=='history':
            stem += '_'
        def shorten(value, limit):
            result = ''
            for character in value:
                if len((result+character).encode('utf-16-le'))//2>limit:
                    break
                result += character
            return result[:-1]+'_' if result.endswith("'") else result
        title, number = shorten(stem,31), 1
        while title.casefold() in used:
            number += 1
            suffix = f' ({number})'
            title = shorten(stem,31-len(suffix))+suffix
        used.add(title.casefold()); titles.append(title)
    return titles


def _formula(value, names, tables):
    if not value:
        return value
    if '!' not in value and not any(name.casefold()+'[' in value.casefold() for name in tables):
        return value
    equals = value.startswith('=')
    result = []
    try:
        tokens = Tokenizer(value if equals else '='+value).items
    except TokenizerError:
        raise ValueError(_('A selected sheet has a formula that cannot be renamed safely. Export that collection separately to retain it.')) from None
    for token in tokens:
        text = token.value
        if token.type=='OPERAND' and token.subtype=='RANGE':
            prefix, separator, reference = text.rpartition('!')
            if separator and '[' not in prefix:
                original = prefix.strip("'").replace("''", "'")
                title = names.get(original.casefold())
                text = "'"+title.replace("'","''")+"'!"+reference if title else '#REF!'
            elif not separator:
                for original, replacement in tables.items():
                    if text.casefold().startswith(original.casefold()+'['):
                        text = replacement+text[len(original):]
                        break
        result.append(text)
    return ('=' if equals else '')+''.join(result)


class PackageMerger:
    def __init__(self):
        book = Workbook(); buffer = BytesIO(); book.save(buffer); book.close()
        with ZipFile(BytesIO(buffer.getvalue())) as archive:
            self.parts = {name:archive.read(name) for name in archive.namelist()
                          if name not in ('xl/worksheets/sheet1.xml',)}
        self.workbook = minidom.parseString(self.parts['xl/workbook.xml'])
        self.sheets = self.workbook.getElementsByTagNameNS(S,'sheets')[0]
        for node in list(self.sheets.childNodes): self.sheets.removeChild(node)
        self.relationships = minidom.parseString(self.parts['xl/_rels/workbook.xml.rels'])
        for node in children(self.relationships.documentElement):
            if node.getAttribute('Type').endswith('/worksheet'):
                node.parentNode.removeChild(node)
        self.types = minidom.parseString(self.parts['[Content_Types].xml'])
        for node in children(self.types.documentElement):
            if node.getAttribute('PartName')=='/xl/worksheets/sheet1.xml':
                node.parentNode.removeChild(node)
        self.styles = minidom.parseString(self.parts['xl/styles.xml'])
        self.style_cache = {(section.localName,node.toxml()):number
                            for section in children(self.styles.documentElement)
                            for number,node in enumerate(children(section))}
        self.defined_names = self.workbook.getElementsByTagNameNS(S,'definedNames')[0]
        self.table_id = 0
        self.titles = []

    def section(self, name):
        root = self.styles.documentElement
        existing = children(root,name)
        if existing: return existing[0]
        node = self.styles.createElementNS(S,name)
        following = next((item for item in children(root) if STYLE_ORDER.index(item.localName)>STYLE_ORDER.index(name)),None)
        root.insertBefore(node,following)
        return node

    def append_style(self, section, node):
        key = (section,node.toxml())
        if key in self.style_cache:
            return self.style_cache[key]
        target = self.section(section)
        index = len(children(target))
        imported = self.styles.importNode(node,True)
        for attribute in node.ownerDocument.documentElement.attributes.keys():
            if attribute.startswith('xmlns:'):
                imported.setAttribute(attribute,node.ownerDocument.documentElement.getAttribute(attribute))
        target.appendChild(imported)
        target.setAttribute('count',str(index+1))
        self.style_cache[key] = index
        return index

    def add(self, archive, part, title, source_title, names, index):
        prefix = f'xl/collections/{index}/'
        source_types = ET.fromstring(archive.read('[Content_Types].xml'))
        overrides = {node.get('PartName').lstrip('/'):node.get('ContentType') for node in source_types if node.tag.endswith('Override')}
        defaults = {node.get('Extension'):node.get('ContentType') for node in source_types if node.tag.endswith('Default')}
        source_styles = minidom.parseString(archive.read('xl/styles.xml'))
        source_formats = {int(node.getAttribute('numFmtId')):node.getAttribute('formatCode')
                          for node in source_styles.getElementsByTagNameNS(S,'numFmt')}
        source_xfs = children(children(source_styles.documentElement,'cellXfs')[0])
        date_styles = {number for number,node in enumerate(source_xfs)
                       if is_datetime(source_formats.get(int(node.getAttribute('numFmtId') or 0),
                           BUILTIN_FORMATS.get(int(node.getAttribute('numFmtId') or 0),''))) in ('date','datetime')}
        palette_nodes = source_styles.getElementsByTagNameNS(S,'indexedColors')
        palette = [node.getAttribute('rgb') for node in children(palette_nodes[0])] if palette_nodes else None
        theme = archive.read('xl/theme/theme1.xml') if 'xl/theme/theme1.xml' in archive.namelist() else None
        resolve = _color_resolver(SimpleNamespace(loaded_theme=theme,_colors=palette))
        theme_root = ET.fromstring(theme) if theme else None
        theme_fonts = {}
        if theme_root is not None:
            for kind in ('major','minor'):
                latin = theme_root.find(f'.//{{*}}{kind}Font/{{*}}latin')
                if latin is not None: theme_fonts[kind] = latin.get('typeface')

        def colors(document):
            for node in list(document.getElementsByTagName('*')):
                if node.namespaceURI==S and node.localName in ('color','fgColor','bgColor'):
                    attributes = {key:node.getAttribute(key) for key in ('theme','indexed','tint') if node.hasAttribute(key)}
                    if 'theme' in attributes or 'indexed' in attributes:
                        for key in ('theme','indexed'): 
                            if key in attributes: attributes[key] = int(attributes[key])
                        if 'tint' in attributes: attributes['tint'] = float(attributes['tint'])
                        rgb = resolve(Color(**attributes))
                        if rgb:
                            for key in list(node.attributes.keys()): node.removeAttribute(key)
                            node.setAttribute('rgb','FF'+rgb[1:])
                if node.namespaceURI==S and node.localName in ('font','rPr'):
                    schemes = children(node,'scheme')
                    if schemes:
                        family = theme_fonts.get(schemes[0].getAttribute('val'))
                        if family:
                            font_name = children(node,'name' if node.localName=='font' else 'rFont')
                            if font_name: font_name[0].setAttribute('val',family)
                        node.removeChild(schemes[0])
                if node.namespaceURI==S and node.localName=='t':
                    node.setAttributeNS('http://www.w3.org/XML/1998/namespace','xml:space','preserve')
                if node.namespaceURI==A and node.localName=='schemeClr':
                    order = ('lt1','dk1','lt2','dk2','accent1','accent2','accent3','accent4','accent5','accent6','hlink','folHlink')
                    name = {'tx1':'dk1','bg1':'lt1','tx2':'dk2','bg2':'lt2'}.get(node.getAttribute('val'),node.getAttribute('val'))
                    if name in order:
                        rgb = resolve(Color(theme=order.index(name)))
                        if rgb:
                            replacement = document.createElementNS(A,f'{node.prefix}:srgbClr' if node.prefix else 'srgbClr')
                            replacement.setAttribute('val',rgb[1:])
                            for child in list(node.childNodes): replacement.appendChild(child)
                            node.parentNode.replaceChild(replacement,node)
        colors(source_styles)
        maps = {section:{} for section in ('fonts','fills','borders','cellStyleXfs','cellXfs','dxfs')}
        formats = {}
        for section in children(source_styles.documentElement,'numFmts'):
            for node in children(section):
                existing = next((item for item in children(self.section('numFmts'))
                                 if item.getAttribute('formatCode')==node.getAttribute('formatCode')),None)
                number = (int(existing.getAttribute('numFmtId')) if existing else
                          164+len(children(self.section('numFmts'))))
                formats[int(node.getAttribute('numFmtId'))] = number
                node.setAttribute('numFmtId',str(number))
                if existing is None: self.append_style('numFmts',node)
        for section in ('fonts','fills','borders','cellStyleXfs','cellXfs','dxfs'):
            for group in children(source_styles.documentElement,section):
                for number,node in enumerate(children(group)):
                    if node.localName=='xf':
                        for attribute, mapping in [('fontId','fonts'),('fillId','fills'),('borderId','borders'),('xfId','cellStyleXfs')]:
                            if node.hasAttribute(attribute): node.setAttribute(attribute,str(maps[mapping][int(node.getAttribute(attribute))]))
                        old = int(node.getAttribute('numFmtId') or 0)
                        if old in formats: node.setAttribute('numFmtId',str(formats[old]))
                    # dxf custom number formats also refer to workbook-level IDs.
                    for number_format in node.getElementsByTagNameNS(S,'numFmt'):
                        old = int(number_format.getAttribute('numFmtId'))
                        if old in formats: number_format.setAttribute('numFmtId',str(formats[old]))
                    maps[section][number] = self.append_style(section,node)
        table_styles = {}
        for group in children(source_styles.documentElement,'tableStyles'):
            for node in children(group):
                old = node.getAttribute('name'); new = f'Collection{index}_{old}'
                table_styles[old] = new; node.setAttribute('name',new)
                for item in node.getElementsByTagNameNS(S,'tableStyleElement'):
                    if item.hasAttribute('dxfId'): item.setAttribute('dxfId',str(maps['dxfs'][int(item.getAttribute('dxfId'))]))
                self.append_style('tableStyles',node)
        shared = []
        shared_root = None
        if 'xl/sharedStrings.xml' in archive.namelist():
            shared_root = minidom.parseString(archive.read('xl/sharedStrings.xml')).documentElement
            shared = children(shared_root,'si')
        workbook = minidom.parseString(archive.read('xl/workbook.xml'))
        properties = workbook.getElementsByTagNameNS(S,'workbookPr')
        date_1904 = bool(properties and properties[0].getAttribute('date1904') in ('1','true'))
        source_sheets = workbook.getElementsByTagNameNS(S,'sheet')
        source_index = next(number for number,node in enumerate(source_sheets) if node.getAttribute('name')==source_title)
        # These workbook-global features cannot be safely scoped to one sheet.
        if workbook.getElementsByTagNameNS(S,'externalReference'):
            raise ValueError(_('A selected workbook has external workbook links. Export that collection separately to retain them.'))
        copied, tables = set(), {}
        def relationship_path(path):
            directory, filename = posixpath.split(path)
            return posixpath.join(directory,'_rels',filename+'.rels')
        def copy_part(path):
            if path in copied: return
            copied.add(path)
            payload = archive.read(path)
            content_type = overrides.get(path) or defaults.get(path.rsplit('.',1)[-1])
            if content_type is None: raise ValueError(_('A workbook part has no content type.'))
            node = self.types.createElementNS(C,'Override')
            node.setAttribute('PartName','/'+prefix+path); node.setAttribute('ContentType',content_type)
            self.types.documentElement.appendChild(node)
            self.parts[prefix+path] = payload
            rel_path = relationship_path(path)
            if rel_path in archive.namelist():
                rels = minidom.parseString(archive.read(rel_path))
                for relationship in children(rels.documentElement):
                    if relationship.getAttribute('TargetMode')=='External': continue
                    target = relationship.getAttribute('Target')
                    dependency = posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join(posixpath.dirname(path),target))
                    copy_part(dependency)
                    relationship.setAttribute('Target','/'+prefix+dependency)
                self.parts[prefix+rel_path] = rels.toxml(encoding='utf-8')
        copy_part(part)
        for path in copied:
            if overrides.get(path,'').endswith('.table+xml'):
                doc = minidom.parseString(self.parts[prefix+path]); root = doc.documentElement
                old = root.getAttribute('displayName'); new = f'Collection{index}_{old}'
                tables[old] = new; root.setAttribute('displayName',new); root.setAttribute('name',new)
                self.table_id += 1; root.setAttribute('id',str(self.table_id))
                self.parts[prefix+path] = doc.toxml(encoding='utf-8')
        for path in copied:
            content_type = overrides.get(path) or defaults.get(path.rsplit('.',1)[-1])
            if not content_type.endswith(('+xml','/xml')): continue
            doc = minidom.parseString(self.parts[prefix+path]); colors(doc)
            for node in doc.getElementsByTagName('*'):
                if node.namespaceURI==S:
                    if node.hasAttribute('cm') or node.hasAttribute('vm'):
                        raise ValueError(_('A selected sheet uses workbook-level cell metadata. Export that collection separately to retain it.'))
                    attribute = 's' if node.localName in ('c','row') else 'style' if node.localName=='col' else None
                    if (date_1904 and node.localName=='c' and node.getAttribute('t') in ('','n') and
                            int(node.getAttribute('s') or 0) in date_styles):
                        values = children(node,'v')
                        if values and values[0].firstChild:
                            values[0].firstChild.data = str(Decimal(values[0].firstChild.data)+1462)
                    if attribute and (node.localName=='c' or node.hasAttribute(attribute)):
                        node.setAttribute(attribute,str(maps['cellXfs'][int(node.getAttribute(attribute) or 0)]))
                    if node.hasAttribute('dxfId'): node.setAttribute('dxfId',str(maps['dxfs'][int(node.getAttribute('dxfId'))]))
                    if node.localName=='tableStyleInfo' and node.getAttribute('name') in table_styles:
                        node.setAttribute('name',table_styles[node.getAttribute('name')])
                    if node.localName=='c' and node.getAttribute('t')=='s':
                        value = children(node,'v')[0]; number = int(value.firstChild.data)
                        inline = doc.createElementNS(S,'is')
                        inline.setAttribute('xmlns',S)
                        for key in shared_root.attributes.keys():
                            if key.startswith('xmlns:'): inline.setAttribute(key,shared_root.getAttribute(key))
                        for child in shared[number].childNodes: inline.appendChild(doc.importNode(child,True))
                        node.replaceChild(inline,value); node.setAttribute('t','inlineStr')
                if node.localName in ('f','formula','formula1','formula2','calculatedColumnFormula','totalsRowFormula'):
                    if node.firstChild and node.firstChild.nodeType==node.TEXT_NODE:
                        before = node.firstChild.data
                        node.firstChild.data = _formula(before,names,tables)
                        if before!=node.firstChild.data and node.parentNode.localName=='c':
                            for value in children(node.parentNode,'v'): node.parentNode.removeChild(value)
                if node.localName=='hyperlink' and node.hasAttribute('location'):
                    node.setAttribute('location',_formula(node.getAttribute('location'),names,tables))
            colors(doc)  # Shared strings introduced above need source theme colors too.
            self.parts[prefix+path] = doc.toxml(encoding='utf-8')
        definitions = {}
        for node in workbook.getElementsByTagNameNS(S,'definedName'):
            if node.hasAttribute('localSheetId') and int(node.getAttribute('localSheetId'))!=source_index: continue
            imported = self.workbook.importNode(node,True)
            imported.setAttribute('localSheetId',str(index-1))
            if imported.firstChild: imported.firstChild.data = _formula(imported.firstChild.data,names,tables)
            definitions[imported.getAttribute('name')] = imported
        for node in definitions.values(): self.defined_names.appendChild(node)
        sheet = self.workbook.createElementNS(S,'sheet')
        sheet.setAttribute('name',title); sheet.setAttribute('sheetId',str(index))
        identifier = f'collection{index}'
        sheet.setAttributeNS(R,'r:id',identifier); sheet.setAttribute('xmlns:r',R)
        self.sheets.appendChild(sheet)
        relationship = self.relationships.createElementNS(P,'Relationship')
        for key,value in [('Id',identifier),('Type',R+'/worksheet'),('Target','/'+prefix+part)]: relationship.setAttribute(key,value)
        self.relationships.documentElement.appendChild(relationship)
        self.titles.append(title)

    def finish(self):
        properties = minidom.parseString(self.parts['docProps/app.xml'])
        vectors = properties.getElementsByTagNameNS('http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes','vector')
        # openpyxl's minimal package omits these optional properties. Keep any
        # titles/counts consistent if a future base package supplies them.
        for vector in vectors:
            if vector.parentNode.localName=='TitlesOfParts':
                for child in list(vector.childNodes): vector.removeChild(child)
                vector.setAttribute('size',str(len(self.titles)))
                for title in self.titles:
                    node = properties.createElementNS(vector.namespaceURI,'vt:lpstr')
                    node.appendChild(properties.createTextNode(title)); vector.appendChild(node)
            if vector.parentNode.localName=='HeadingPairs':
                for node in vector.getElementsByTagNameNS(vector.namespaceURI,'i4'):
                    if node.firstChild: node.firstChild.data = str(len(self.titles))
        self.parts['docProps/app.xml'] = properties.toxml(encoding='utf-8')
        for path,document in [('xl/workbook.xml',self.workbook),('xl/_rels/workbook.xml.rels',self.relationships),
                              ('xl/styles.xml',self.styles),('[Content_Types].xml',self.types)]:
            self.parts[path] = document.toxml(encoding='utf-8')
        output = BytesIO()
        with ZipFile(output,'w',ZIP_DEFLATED) as archive:
            for path,payload in self.parts.items(): archive.writestr(path,payload)
        return output.getvalue()
