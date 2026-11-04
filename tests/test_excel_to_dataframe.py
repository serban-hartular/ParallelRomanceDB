"""Checks for etymon extraction and lossless HTML text conversion."""

from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from openpyxl import Workbook, load_workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.styles import Color, Font

from extract_sheet import excel_to_dataframe


class HTMLText(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.feed(html)

    def handle_data(self, data):
        self.parts.append(data)

    @property
    def text(self):
        return ''.join(self.parts)


class ExcelToDataFrameTests(unittest.TestCase):
    def test_search_expansions_preserve_original_cell_content(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / 'ligatures.xlsx'
            workbook = Workbook()
            sheet = workbook.active
            sheet.append([None, 'LIMBA FRANCEZĂ'])
            sheet.append(['ETIMON/ CORESPONDENTE ROMANICE', 'ŒUF Æ Ø Ł L·L ĿL'])
            text = 'cœur encyclopædia col·laboració'
            sheet.append(['SENSURI DE BAZĂ', text])
            workbook.save(source)
            workbook.close()

            frame = excel_to_dataframe(source)
            self.assertEqual(frame.nodiacritics_plaintext.tolist(), [
                'OEUF AE O L LL LL', 'coeur encyclopaedia collaboracio',
            ])
            self.assertEqual(frame.iloc[1].plaintext_content, text)
            self.assertEqual(HTMLText(frame.iloc[1].content).text, text)

    def test_example_and_all_original_text(self):
        source = Path(__file__).resolve().parents[1] / 'db' / 'example.xlsx'
        before = source.read_bytes()
        frame = excel_to_dataframe(source, 'Sheet1')
        self.assertEqual(list(frame.columns), [
            'etimon_number', 'column', 'label', 'label_number',
            'content', 'plaintext_content', 'nodiacritics_plaintext',
        ])
        example = frame.loc[frame.plaintext_content.str.startswith('Prăjitură cu cremă')]
        self.assertEqual(len(example), 1)
        record = example.iloc[0]
        self.assertEqual(record.etimon_number, 2)
        self.assertEqual(record['column'], 'LIMBA ROMÂNĂ')
        self.assertEqual(record.label_number, 2)
        self.assertEqual(
            record.nodiacritics_plaintext,
            'Prajitura cu crema, cu inghetata si cu frisca (DEX, DCR3)',
        )
        self.assertIn('OBSERVAȚII', frame['column'].values)
        self.assertIn('CONCLUZII', frame['column'].values)
        self.assertIn('SENSURI DE BAZĂ', frame.label.values)
        self.assertIn('EXTENSII SEMANTICE (METAFORIZĂRI,  METONIMII)', frame.label.values)

        workbook = load_workbook(source, rich_text=True)
        try:
            self.assertEqual(record.label, workbook['Sheet1']['A7'].value)
            original = [
                str(cell.value)
                for row in workbook['Sheet1'].iter_rows(min_row=2)
                for cell in row[1:]
                if cell.value is not None and str(cell.value).strip()
            ]
            self.assertEqual(len(frame), len(original))
            for record, text in zip(frame.to_dict('records'), original):
                self.assertEqual(HTMLText(record['content']).text, text)
                self.assertEqual(record['plaintext_content'], text.strip())
        finally:
            workbook.close()
        self.assertEqual(source.read_bytes(), before)

    def test_numbering_sparse_rows_and_rich_text(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / 'source.xlsx'
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = 'Data'
            sheet.append([None, ' FRANÇAIS ', 'ROMÂNĂ', 'OBSERVAȚII'])
            sheet.append(['ETIMON/ CCORESPONDENTE ROMANICE', 'WORD', 'CUVÂNT'])
            sheet.append(['SENS DE BAZĂ', 'one', '  plain <tag> & text\n  '])
            sheet.append([None, 'two'])
            sheet.append([None, None, None])  # Does not increment numbering.
            sheet.append([None, None, 'three', ' \t\n'])
            sheet.append(['SENSURI SPECIALIZATE', 0, False])
            sheet.append(['SENS DE BAZĂ', 'four'])
            sheet.append(['ETIMON/ CORESPONDENTE ROMANICE', 'NEXT'])
            sheet.append(['SENS DE BAZĂ', 'new first'])
            sheet.append([None, CellRichText([
                '  ',
                TextBlock(InlineFont(b=True, i=True, color='FFFF0000'), '<&>'),
                TextBlock(InlineFont(b=False, u='double', strike=True), 'under'),
                TextBlock(InlineFont(vertAlign='superscript'), '2'),
                TextBlock(InlineFont(vertAlign='subscript'), '3'),
                TextBlock(InlineFont(color=Color(theme=1)), 'theme'),
                TextBlock(InlineFont(color=Color(indexed=4)), 'indexed'),
                TextBlock(InlineFont(color=Color(rgb='FF000000', tint=0.5)), 'tinted'),
                '\n  ',
            ])])
            sheet['B11'].font = Font(name='Times New Roman', sz=12)
            sheet['C3'].font = Font(b=True, i=True)
            workbook.create_sheet('Other').append(['Unrelated data'])
            workbook.save(source)
            workbook.close()

            frame = excel_to_dataframe(source)
            romanian = frame.loc[
                (frame.etimon_number == 1)
                & (frame['column'] == 'ROMÂNĂ')
                & (frame.label == 'SENS DE BAZĂ')
            ]
            self.assertEqual(romanian.label_number.tolist(), [1, 3])
            self.assertNotIn('OBSERVAȚII', frame['column'].values)
            self.assertIn(' FRANÇAIS ', frame['column'].values)
            self.assertEqual(
                frame.loc[frame.plaintext_content == 'four', 'label_number'].item(), 4,
            )
            self.assertEqual(
                frame.loc[frame.plaintext_content == 'new first', 'label_number'].item(), 1,
            )
            self.assertIn('0', frame.plaintext_content.values)
            self.assertIn('False', frame.plaintext_content.values)
            plain = frame.loc[frame.plaintext_content == 'plain <tag> & text'].iloc[0]
            self.assertEqual(HTMLText(plain.content).text, '  plain <tag> & text\n  ')
            self.assertIn('&lt;tag&gt; &amp; text', plain.content)
            self.assertIn('font-weight: bold', plain.content)
            rich = frame.iloc[-1].content
            for style in (
                'white-space: pre-wrap', 'font-weight: bold', 'font-style: italic',
                'font-weight: normal', 'color: #FF0000', 'font-size: 12pt',
                'text-decoration-line: underline line-through',
                'text-decoration-style: double', 'vertical-align: super',
                'vertical-align: sub', 'color: #000000', 'color: #0000FF',
                'color: #808080',
            ):
                self.assertIn(style, rich)
            self.assertEqual(
                HTMLText(rich).text, '  <&>under23themeindexedtinted\n  ',
            )

    def test_empty_and_invalid_layouts(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / 'empty.xlsx'
            workbook = Workbook()
            workbook.save(source)
            self.assertEqual(excel_to_dataframe(source).shape, (0, 7))
            with self.assertRaisesRegex(ValueError, 'does not exist'):
                excel_to_dataframe(source, 'Missing')

            sheet = workbook.active
            sheet.append([None, 'Language'])
            sheet.append([None, 'Content without etymon'])
            workbook.save(source)
            with self.assertRaisesRegex(ValueError, 'before the first ETIMON/'):
                excel_to_dataframe(source)

            sheet['A2'] = 'ETIMON/ CORESPONDENTE ROMANICE'
            sheet['B1'] = None
            workbook.save(source)
            workbook.close()
            with self.assertRaisesRegex(ValueError, 'no column heading'):
                excel_to_dataframe(source)


if __name__ == '__main__':
    unittest.main()
