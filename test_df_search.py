"""Tests for text searches and etymon ordering."""

from pathlib import Path
import unittest

import pandas as pd

from df_search import COLUMN_ORDER, LABEL_ORDER, get_etimon, search_dataframe
from extract_sheet import excel_to_dataframe
from text_normalization import remove_diacritics


class DataFrameSearchTests(unittest.TestCase):
    def setUp(self):
        self.df = pd.DataFrame([
            (3, 'ROMÂNĂ', 'Basic', 1, 'Cremă [fină]'),
            (1, 'FRANCEZĂ', 'Basic', 1, 'Cremă [fină]'),
            (3, 'ROMÂNĂ', 'Special', 1, 'Cremă [fină]'),
            (2, 'ROMÂNĂ', 'Basic', 1, 'cremă [fină]'),
            (4, 'ROMÂNĂ', 'Basic', 1, None),
            (5, 'ROMÂNĂ', 'Basic', 1, 'Cremă f'),
        ], columns=[
            'etimon_number', 'column', 'label', 'label_number', 'plaintext_content',
        ])

    def test_literal_search_unique_order_and_case(self):
        self.assertEqual(search_dataframe(self.df, 'Cremă [fină]'), [1, 3])
        self.assertEqual(
            search_dataframe(self.df, 'Cremă [fină]', case_sensitive=False), [1, 2, 3],
        )
        self.assertEqual(search_dataframe(self.df, 'absent'), [])
        self.assertEqual(search_dataframe(self.df, ''), [1, 2, 3, 5])
        self.assertEqual(search_dataframe(self.df.iloc[:0], 'Cremă'), [])

    def test_exact_filters_and_no_mutation(self):
        original = self.df.copy(deep=True)
        self.assertEqual(search_dataframe(self.df, 'Cremă', column='ROMÂNĂ'), [3, 5])
        self.assertEqual(search_dataframe(self.df, 'Cremă', label='Special'), [3])
        self.assertEqual(
            search_dataframe(self.df, 'Cremă', column='FRANCEZĂ', label='Special'), [],
        )
        self.assertEqual(search_dataframe(self.df, 'Cremă', column='ROM'), [])
        pd.testing.assert_frame_equal(self.df, original)

    def test_diacritic_free_queries_with_cached_and_legacy_dataframes(self):
        frame = pd.DataFrame([
            (2, 'ROMÂNĂ', 'Basic', 'Prăjitură cu înghețată și frișcă'),
            (3, 'ROMÂNĂ', 'Basic', 'Ştiinţă şi Țară'),
            (9, 'FRANÇAIS', 'Basic', 'café'),
            (4, 'FRANÇAIS', 'Basic', 'cafe\u0301'),
            (5, 'FRANÇAIS', 'Basic', 'cafe'),
            (6, 'FRANÇAIS', 'Basic', None),
        ], columns=['etimon_number', 'column', 'label', 'plaintext_content'])
        cached = frame.assign(
            nodiacritics_plaintext=frame.plaintext_content.map(remove_diacritics, na_action='ignore'),
        )
        for candidate in (frame, cached):
            with self.subTest(precomputed='nodiacritics_plaintext' in candidate):
                original = candidate.copy(deep=True)
                self.assertEqual(search_dataframe(candidate, 'Prajitura cu inghetata si frisca'), [2])
                self.assertEqual(search_dataframe(candidate, 'PRAJITURA', case_sensitive=False), [2])
                self.assertEqual(search_dataframe(candidate, 'Stiinta si Tara'), [3])
                self.assertEqual(search_dataframe(candidate, 'cafe'), [4, 5, 9])
                self.assertEqual(search_dataframe(candidate, 'café'), [4, 5, 9])
                self.assertEqual(search_dataframe(candidate, 'cafe\u0301'), [4, 5, 9])
                # Column/label filters retain their exact-match semantics.
                self.assertEqual(search_dataframe(candidate, 'Prajitura', column='ROMÂNĂ', label='Basic'), [2])
                self.assertEqual(search_dataframe(candidate, 'Prajitura', column='ROMANA'), [])
                pd.testing.assert_frame_equal(candidate, original)

    def test_normalization_preserves_case_and_whitespace(self):
        self.assertEqual(
            remove_diacritics('  ĂÂÎȘȚ ăâîșț ŞŢ şţ\néèêë áàäã çñ üö œ  '),
            '  AAIST aaist ST st\neeee aaaa cn uo oe  ',
        )

    def test_latin_expansions_and_catalan_middle_dots(self):
        self.assertEqual(
            remove_diacritics('œ Œ æ Æ ø Ø ł Ł l·l L·L l·L ŀl ĿL a·b'),
            'oe OE ae AE o O l L ll LL lL ll LL a·b',
        )
        frame = pd.DataFrame([
            (1, 'cœur'), (2, 'coeur'), (3, 'encyclopædia'),
            (4, 'col·laboració'), (5, 'Øresund Łódź'),
        ], columns=['etimon_number', 'plaintext_content'])
        cached = frame.assign(nodiacritics_plaintext=frame.plaintext_content.map(remove_diacritics))
        for candidate in (frame, cached):
            with self.subTest(precomputed='nodiacritics_plaintext' in candidate):
                for query in ('coeur', 'cœur', 'CŒUR'):
                    self.assertEqual(search_dataframe(candidate, query, case_sensitive=False), [1, 2])
                self.assertEqual(search_dataframe(candidate, 'encyclopaedia'), [3])
                self.assertEqual(search_dataframe(candidate, 'collaboracio'), [4])
                self.assertEqual(search_dataframe(candidate, 'col·laboració'), [4])
                self.assertEqual(search_dataframe(candidate, 'oresund lodz', case_sensitive=False), [5])

    def test_example_workbook(self):
        frame = excel_to_dataframe(Path(__file__).parent / 'db' / 'example.xlsx')
        self.assertEqual(search_dataframe(
            frame, 'Prăjitură cu cremă', column='LIMBA ROMÂNĂ', label='SENSURI DE BAZĂ',
        ), [2])
        result = get_etimon(frame, 2)
        selected = frame.loc[frame.etimon_number == 2]
        self.assertEqual(len(result), len(selected[['label', 'label_number']].drop_duplicates()))
        self.assertEqual(list(result.columns), ['label', 'label_number', *COLUMN_ORDER])
        self.assertEqual(result.label.drop_duplicates().tolist(), [
            LABEL_ORDER[0], LABEL_ORDER[1], LABEL_ORDER[2],
        ])
        self.assertFalse(result.isna().any().any())
        for plaintext in (False, True):
            table = get_etimon(frame, 2, plaintext=plaintext)
            indexed = table.set_index(['label', 'label_number'])
            content_column = 'plaintext_content' if plaintext else 'content'
            for record in selected.to_dict('records'):
                self.assertEqual(
                    indexed.loc[(record['label'], record['label_number']), record['column']],
                    record[content_column],
                )


class GetEtimonTests(unittest.TestCase):
    def setUp(self):
        records = [
            (2, 'Z other', 1, COLUMN_ORDER[0], 'z'),
            (2, LABEL_ORDER[3], 2, COLUMN_ORDER[0], 'special second'),
            (2, LABEL_ORDER[1], 2, COLUMN_ORDER[0], 'basic second'),
            (2, 'A other', 2, COLUMN_ORDER[0], 'a second'),
            (2, LABEL_ORDER[0], 1, COLUMN_ORDER[0], 'etymon'),
            (1, LABEL_ORDER[0], 1, 'Other etymon column', 'different etymon'),
            (2, LABEL_ORDER[1], 1, COLUMN_ORDER[1], 'basic first, Romanian'),
            (2, LABEL_ORDER[2], 1, COLUMN_ORDER[0], 'extension'),
            (2, LABEL_ORDER[1], 1, COLUMN_ORDER[0], 'basic first, French'),
            (2, 'A other', 1, COLUMN_ORDER[0], 'a first'),
            (2, LABEL_ORDER[3], 1, COLUMN_ORDER[0], 'special first'),
            (2, 'SENS DE BAZĂ', 1, COLUMN_ORDER[0], 'original singular label'),
            (2, LABEL_ORDER[0], 1, 'Z extra', 'extra z'),
            (2, LABEL_ORDER[0], 1, 'A extra', 'extra a'),
            (2, LABEL_ORDER[3], 1, COLUMN_ORDER[7], None),
        ]
        self.df = pd.DataFrame([
            {
                'etimon_number': etymon, 'label': label, 'label_number': number,
                'column': column, 'content': f'<b>{text}</b>' if text is not None else None,
                'plaintext_content': text,
            }
            for etymon, label, number, column, text in records
        ])

    def test_table_order_and_cell_placement(self):
        original = self.df.copy(deep=True)
        result = get_etimon(self.df, 2)
        self.assertEqual(list(result.columns), [
            'label', 'label_number', *COLUMN_ORDER, 'A extra', 'Z extra',
        ])
        self.assertEqual(list(zip(result.label, result.label_number)), [
            (LABEL_ORDER[0], 1), (LABEL_ORDER[1], 1), (LABEL_ORDER[1], 2),
            (LABEL_ORDER[2], 1), (LABEL_ORDER[3], 1), (LABEL_ORDER[3], 2),
            ('A other', 1), ('A other', 2), ('SENS DE BAZĂ', 1), ('Z other', 1),
        ])
        self.assertEqual(result.loc[1, COLUMN_ORDER[0]], '<b>basic first, French</b>')
        self.assertEqual(result.loc[1, COLUMN_ORDER[1]], '<b>basic first, Romanian</b>')
        self.assertEqual(result.loc[0, 'A extra'], '<b>extra a</b>')
        self.assertEqual(result.loc[0, 'Z extra'], '<b>extra z</b>')
        self.assertEqual(result.loc[2, COLUMN_ORDER[1]], '')
        self.assertEqual(result.loc[4, COLUMN_ORDER[7]], '')
        self.assertTrue(result[COLUMN_ORDER[2]].eq('').all())
        self.assertFalse(result.isna().any().any())
        self.assertIsNone(result.columns.name)
        self.assertEqual(result.index.tolist(), list(range(len(result))))
        pd.testing.assert_frame_equal(self.df, original)
        result.loc[0, COLUMN_ORDER[0]] = 'edited'
        pd.testing.assert_frame_equal(self.df, original)

    def test_plaintext_flag(self):
        table = get_etimon(self.df, 2, plaintext=True)
        self.assertEqual(table.loc[1, COLUMN_ORDER[0]], 'basic first, French')
        self.assertEqual(table.loc[4, COLUMN_ORDER[7]], '')
        self.assertEqual(table.loc[0, 'A extra'], 'extra a')

    def test_absent_etymon_and_empty_dataframe(self):
        expected = pd.DataFrame(columns=['label', 'label_number', *COLUMN_ORDER])
        pd.testing.assert_frame_equal(get_etimon(self.df, 999), expected)
        pd.testing.assert_frame_equal(get_etimon(self.df.iloc[:0], 2), expected)

    def test_duplicate_cells_are_reported(self):
        duplicates = pd.concat([self.df, self.df.iloc[[0]]], ignore_index=True)
        with self.assertRaisesRegex(ValueError, 'must be unique'):
            get_etimon(duplicates, 2)


if __name__ == '__main__':
    unittest.main()
