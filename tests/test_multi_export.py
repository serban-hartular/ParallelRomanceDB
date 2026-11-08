"""Combined exports preserve independent worksheet styles, packages and text."""

from datetime import datetime
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from openpyxl import Workbook, load_workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.comments import Comment
from openpyxl.chart import BarChart, Reference
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Font, PatternFill, Color
from openpyxl.worksheet.table import Table
from openpyxl.utils.datetime import MAC_EPOCH

from collection_catalog import CollectionCatalog
from excel_export import combined_workbook_bytes, export_collections_timestamped, workbook_bytes
from excel_merge import sheet_titles
from main import create_app


class MultiExportTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory(); self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.catalog = CollectionCatalog(self.root/'catalog.sqlite3'); self.addCleanup(self.catalog.close)
        self.entries, self.originals = [], []
        for number, color in enumerate(('AA1122','1177CC')):
            source = self.root/f'original{number}.xlsx'
            book = Workbook(); sheet = book.active; sheet.title = 'Terms'
            sheet.append(['Label','LIMBA FRANCEZĂ',' Notes ','Extra','More'])
            sheet.append([' ETIMON/ CORESPONDENTE ROMANICE ','  café  ',"=Terms!B2"])
            sheet.append([' SENSURI DE BAZĂ ','sense','text'])
            sheet['B2'].fill = PatternFill('solid',fgColor=color)
            sheet['B2'].font = Font(name='Times New Roman',sz=14,bold=True,color=color)
            sheet['B2'].number_format = '"custom '+str(number)+'" 0.00'
            sheet['B3'] = CellRichText('  ',TextBlock(InlineFont(b=True,color=color),'rich'),'\n\n\t  ')
            sheet['B2'].comment = Comment('comment '+str(number),'author')
            sheet.row_dimensions[2].height = 47
            sheet.column_dimensions['B'].width = 38
            sheet.freeze_panes = 'B2'; sheet.merge_cells('D4:E4')
            sheet['D4'] = 'merge'
            sheet.print_title_rows = '1:1'
            sheet.conditional_formatting.add('B2:B3',CellIsRule(operator='equal',formula=['1'],fill=PatternFill('solid',fgColor=color)))
            book.create_sheet('Other')['A1'] = 'unrelated'
            book.save(source); book.close()
            self.originals.append(source.read_bytes())
            entry = self.catalog.create('Collection '+str(number),source,'Terms')
            self.entries.append(entry)
        self.stores = [self.catalog.store(entry['id']) for entry in self.entries]
        self.app = create_app(catalog_path=self.catalog.path,test_config={'DEFAULT_UI_LANGUAGE':'en', 'TESTING':True,'SECRET_KEY':'multi-export',
            'EXPORT_DIRECTORY':str(self.root/'exports')})
        self.addCleanup(self.app.extensions['collection_catalog'].close)
        self.addCleanup(self.app.extensions['access_control'].close)
        self.client = self.app.test_client()
        self.url = f"/collections/{self.entries[0]['id']}/export"

    def combined(self,names=None):
        payload = combined_workbook_bytes(zip(names or ['Collection 0','Collection 1'],self.stores))
        book = load_workbook(BytesIO(payload),rich_text=True); self.addCleanup(book.close)
        return payload,book

    def test_combines_only_selected_sheets_preserving_formats_and_related_parts(self):
        payload, book = self.combined()
        self.assertEqual(book.sheetnames,['Collection 0','Collection 1'])
        self.assertLessEqual(len(book._fonts),4)
        for number, (name,color) in enumerate(zip(book.sheetnames,('AA1122','1177CC'))):
            sheet = book[name]
            self.assertEqual(sheet['A2'].value,' ETIMON/ CORESPONDENTE ROMANICE ')
            self.assertEqual(sheet['B2'].value,'  café  ')
            self.assertEqual(sheet['B2'].fill.fgColor.rgb[-6:],color)
            self.assertEqual(sheet['B2'].font.color.rgb[-6:],color)
            self.assertEqual(sheet['B2'].font.name,'Times New Roman')
            self.assertTrue(sheet['B2'].font.bold)
            self.assertEqual(sheet['B2'].number_format,'"custom '+str(number)+'" 0.00')
            self.assertEqual(str(sheet['B3'].value),'  rich\n\n\t  ')
            self.assertEqual(sheet['B2'].comment.text,'comment '+str(number))
            self.assertEqual(sheet.row_dimensions[2].height,47)
            self.assertEqual(sheet.column_dimensions['B'].width,38)
            self.assertEqual(sheet.freeze_panes,'B2')
            self.assertIn('D4:E4',sheet.merged_cells)
            self.assertEqual(sheet.print_title_rows,'$1:$1')
            self.assertEqual(sheet['C2'].value,f"='{name}'!B2")
            rule = next(iter(sheet.conditional_formatting._cf_rules.values()))[0]
            self.assertEqual(rule.dxf.fill.fgColor.rgb[-6:],color)
        with ZipFile(BytesIO(payload)) as archive:
            self.assertEqual(len(archive.namelist()),len(set(archive.namelist())))
            self.assertTrue(any('comments' in name for name in archive.namelist()))
        for number, store in enumerate(self.stores):
            self.assertEqual(workbook_bytes(store),self.originals[number])

    def test_saved_edits_new_rows_and_trash_are_reflected_in_all_selected_sheets(self):
        for number,store in enumerate(self.stores):
            key = (1,' ETIMON/ CORESPONDENTE ROMANICE ',1,'LIMBA FRANCEZĂ')
            store.save_cell(key,0,[{'insert':'saved '+str(number),'attributes':{'bold':True}},{'insert':'\n\n  \n'}])
            store.add_etymon('new '+str(number))
            store.delete_row(1,' SENSURI DE BAZĂ ',1)
        _, book = self.combined()
        for number,sheet in enumerate(book):
            texts = [str(cell.value or '') for row in sheet for cell in row]
            self.assertIn('saved '+str(number)+'\n\n  ',texts)
            self.assertIn('new '+str(number),texts)
            self.assertNotIn('sense',texts)

    def test_tab_names_are_valid_unique_and_do_not_change_labels(self):
        names = ["'bad/name:[]*?\\'",'X'*45,'x'*45,'', 'History','😀'*25]
        titles = sheet_titles(names)
        self.assertEqual(len({title.casefold() for title in titles}),len(names))
        for title in titles:
            self.assertLessEqual(len(title.encode('utf-16-le'))//2,31)
            self.assertFalse(any(character in title for character in ('[',']',':','*','?','/',chr(92))))
        _, book = self.combined(['A'*45,'a'*45])
        self.assertNotEqual(book.sheetnames[0].casefold(),book.sheetnames[1].casefold())
        self.assertEqual(book.active['A2'].value,' ETIMON/ CORESPONDENTE ROMANICE ')

    def test_form_defaults_current_and_single_download_keeps_original_workbook(self):
        response = self.client.get(self.url+'?choose=1')
        self.assertEqual(response.status_code,200)
        self.assertIn('Collections to export',response.text)
        from html.parser import HTMLParser
        class Checkboxes(HTMLParser):
            def __init__(self, text):
                super().__init__(); self.selected=[]; self.feed(text)
            def handle_starttag(self, tag, attrs):
                attrs=dict(attrs)
                if tag=='input' and attrs.get('name')=='collection' and 'checked' in attrs:
                    self.selected.append(attrs['value'])
        self.assertEqual(Checkboxes(response.text).selected,[self.entries[0]['id']])
        response = self.client.get(self.url)
        self.addCleanup(response.close)
        self.assertEqual(response.data,self.originals[0])
        other = self.client.get(self.url,query_string={'selection':'1','collection':self.entries[1]['id']})
        self.addCleanup(other.close)
        self.assertEqual(other.data,self.originals[1])

    def test_public_multi_download_validation_and_archived_collections(self):
        query = {'selection':'1','collection':[entry['id'] for entry in reversed(self.entries)]}
        response = self.client.get(self.url,query_string=query); self.addCleanup(response.close)
        self.assertEqual(response.status_code,200)
        self.assertIn('Parallel_Words_',response.headers['Content-Disposition'])
        self.assertEqual(response.headers['Cache-Control'],'no-store')
        book = load_workbook(BytesIO(response.data)); self.addCleanup(book.close)
        self.assertEqual(book.sheetnames,['Collection 0','Collection 1'])
        self.assertEqual(len(list((self.root/'exports/combined').glob('*.xlsx'))),1)
        self.assertEqual(self.client.get(self.url+'?selection=1').status_code,400)
        self.assertEqual(self.client.get(self.url+'?selection=1&collection=missing').status_code,404)
        self.app.extensions['collection_catalog'].move_to_trash(self.entries[1]['id'],0)
        self.assertEqual(self.client.get(self.url,query_string=query).status_code,404)
        self.assertNotIn('Collection 1',self.client.get(self.url+'?choose=1').text)
        self.assertEqual(len(list((self.root/'exports/combined').glob('*.xlsx'))),1)

    def test_combined_timestamp_names_never_overwrite_files(self):
        now = datetime(2026,11,8,12,30)
        collections = list(zip(['First','Second'],self.stores))
        one = export_collections_timestamped(collections,self.root/'combined',now=now)
        two = export_collections_timestamped(collections,self.root/'combined',now=now)
        self.assertNotEqual(one,two)
        self.assertEqual(one.suffix,'.xlsx'); self.assertEqual(two.suffix,'.xlsx')

    def test_themes_tables_and_charts_remain_independent(self):
        stores = []
        for number,color in enumerate(('19AB45','CA8732')):
            book = load_workbook(BytesIO(self.originals[number]),rich_text=True)
            theme = ET.fromstring(book.loaded_theme)
            theme.find('.//{*}accent1/{*}srgbClr').set('val',color)
            book.loaded_theme = ET.tostring(theme)
            sheet = book['Terms']
            sheet['B2'].fill = PatternFill('solid',fgColor=Color(theme=4))
            sheet['B2'].font = Font(color=Color(theme=4))
            if number: book.epoch = MAC_EPOCH
            sheet['C2'] = datetime(2025,1,2,12,30)
            sheet.add_table(Table(displayName='Words',ref='A1:C3'))
            sheet['C3'] = '=SUM(Words[Label])'
            chart = BarChart(); chart.add_data(Reference(sheet,min_col=2,min_row=1,max_row=3),titles_from_data=True)
            sheet.add_chart(chart,'G2')
            path = self.root/f'theme{number}.xlsx'; book.save(path); book.close()
            entry = self.catalog.create('Theme '+str(number),path,'Terms')
            stores.append(self.catalog.store(entry['id']))
        payload = combined_workbook_bytes(zip(['First','Second'],stores))
        book = load_workbook(BytesIO(payload),rich_text=True); self.addCleanup(book.close)
        for sheet, color, number in zip(book,('19AB45','CA8732'),(1,2)):
            self.assertEqual(sheet['B2'].fill.fgColor.rgb,'FF'+color)
            self.assertEqual(sheet['B2'].font.color.rgb,'FF'+color)
            self.assertEqual(list(sheet.tables),[f'Collection{number}_Words'])
            self.assertEqual(sheet['C3'].value,f'=SUM(Collection{number}_Words[Label])')
            self.assertEqual(len(sheet._charts),1)
            self.assertIn(sheet.title,sheet._charts[0].series[0].val.numRef.f)
            self.assertEqual(sheet['C2'].value,datetime(2025,1,2,12,30))

    def test_cross_collection_formulas_use_selected_sheets_from_the_same_template(self):
        path = self.root/'related.xlsx'
        book = Workbook(); book.active.title='First'
        for sheet in (book.active,book.create_sheet('Second')):
            sheet.append(['Label','LIMBA FRANCEZĂ','Notes'])
            sheet.append(['ETIMON/','word',"='First'!B2&'Second'!B2&'Omitted'!B2"])
        book.create_sheet('Omitted')['B2']='not selected'
        book.save(path); book.close()
        stores = [self.catalog.store(self.catalog.create('Related '+title,path,title)['id']) for title in ('First','Second')]
        payload = combined_workbook_bytes(zip(["Name's first",'Other collection'],stores))
        book = load_workbook(BytesIO(payload)); self.addCleanup(book.close)
        for sheet in book:
            self.assertEqual(sheet['C2'].value,"='Name''s first'!B2&'Other collection'!B2&#REF!")

    def test_shared_strings_and_prefixed_worksheet_xml_are_inlined_without_losing_text(self):
        content = BytesIO()
        namespace = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
        with ZipFile(BytesIO(self.originals[0])) as original, ZipFile(content,'w') as output:
            for item in original.infolist():
                payload = original.read(item.filename)
                if item.filename=='xl/worksheets/sheet1.xml':
                    tree = ET.fromstring(payload)
                    cell = tree.find(f'.//{{{namespace}}}c[@r="B2"]')
                    for child in list(cell): cell.remove(child)
                    cell.set('t','s'); ET.SubElement(cell,'{'+namespace+'}v').text='0'
                    payload = ET.tostring(tree)
                if item.filename=='[Content_Types].xml':
                    tree = ET.fromstring(payload)
                    ET.SubElement(tree,'{http://schemas.openxmlformats.org/package/2006/content-types}Override',
                        PartName='/xl/sharedStrings.xml',ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml')
                    payload = ET.tostring(tree)
                if item.filename=='xl/_rels/workbook.xml.rels':
                    tree = ET.fromstring(payload)
                    ET.SubElement(tree,'{http://schemas.openxmlformats.org/package/2006/relationships}Relationship',
                        Id='shared',Target='sharedStrings.xml',Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings')
                    payload = ET.tostring(tree)
                output.writestr(item,payload)
            output.writestr('xl/sharedStrings.xml',f'<sst xmlns="{namespace}" count="1" uniqueCount="1"><si><r><rPr><b/></rPr><t xml:space="preserve">  shared\n\n  </t></r></si></sst>')
        path = self.root/'shared.xlsx'; path.write_bytes(content.getvalue())
        entry = self.catalog.create('Shared',path,'Terms')
        payload = combined_workbook_bytes([('Shared',self.catalog.store(entry['id'])),('Other',self.stores[1])])
        book = load_workbook(BytesIO(payload),rich_text=True); self.addCleanup(book.close)
        self.assertEqual(str(book['Shared']['B2'].value),'  shared\n\n  ')
        self.assertTrue(book['Shared']['B2'].value[0].font.b)


if __name__=='__main__':
    unittest.main()
