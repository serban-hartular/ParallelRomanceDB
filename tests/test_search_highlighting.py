"""Normalized highlighting, original text preservation, and markup safety."""

from html.parser import HTMLParser
import unittest

from search_highlighting import _normalized_with_offsets, highlight_content, match_ranges
from text_normalization import remove_diacritics


MARK = '<mark class="search-highlight">'


class Text(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.text = ''
        self.tags = []
        self.feed(html)

    def handle_data(self, data):
        self.text += data

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)


class SearchHighlightingTests(unittest.TestCase):
    def test_normalized_ranges_retain_original_characters(self):
        for text, query in [
            ('Prăjitură', 'PRAJITURA'), ('cœur', 'coeur'), ('encyclopædia', 'encyclopaedia'),
            ('col·laboració', 'collaboracio'), ('coŀlaboració', 'collaboracio'),
            ('cafe\u0301', 'café'), ('Øresund Łódź', 'oresund lodz'),
            ('Straße', 'strasse'), ('가', '가'),
        ]:
            with self.subTest(text=text):
                self.assertEqual(match_ranges(text, query), [(0, len(text))])
                self.assertEqual(highlight_content(text, query, plaintext=True), f'{MARK}{text}</mark>')
        # A query matching part of a ligature must mark the original character.
        self.assertEqual(match_ranges('œ', 'e'), [(0, 1)])
        self.assertEqual(match_ranges('ß', 's'), [(0, 1)])

    def test_literal_multiple_empty_and_missing_matches(self):
        self.assertEqual(match_ranges('Café café cafè', 'cafe'), [(0, 4), (5, 9), (10, 14)])
        self.assertEqual(match_ranges('a [x].* b', '[x].*'), [(2, 7)])
        for query in ('', '\u0301', 'absent'):
            with self.subTest(query=query):
                self.assertEqual(match_ranges('café', query), [])
                self.assertIsNone(highlight_content('<b>café</b>', query))
        self.assertEqual(match_ranges('', 'cafe'), [])

    def test_matches_cross_rich_text_runs_without_changing_formatting(self):
        source = '<div style="white-space: pre-wrap"><span>  Prăji</span><span style="font-style: italic">tură</span><sup>2</sup>\n</div>'
        rendered = highlight_content(source, 'prajitura')
        self.assertEqual(rendered.count(MARK), 2)
        self.assertIn(f'{MARK}Prăji</mark>', rendered)
        self.assertIn(f'{MARK}tură</mark>', rendered)
        self.assertEqual(rendered.replace(MARK, '').replace('</mark>', ''), source)
        self.assertEqual(Text(rendered).text, Text(source).text)

    def test_html_entities_are_decoded_but_attributes_are_not_searched(self):
        source = '<div style="color: red">A &amp; &lt;b&gt; café</div>'
        rendered = highlight_content(source, '& <b> CAFE')
        self.assertEqual(Text(rendered).text, 'A & <b> café')
        self.assertEqual(Text(rendered).tags, ['div', 'mark'])
        self.assertIn(f'{MARK}&amp; &lt;b&gt; café</mark>', rendered)
        self.assertIsNone(highlight_content(source, 'color'))
        self.assertIsNone(highlight_content(source, 'div'))

    def test_plaintext_is_escaped_and_queries_cannot_create_markup(self):
        text = '  <script>alert("café")</script> & café\n'
        rendered = highlight_content(text, '<script>', plaintext=True)
        self.assertEqual(Text(rendered).text, text)
        self.assertEqual(Text(rendered).tags, ['mark'])
        self.assertIn(f'{MARK}&lt;script&gt;</mark>', rendered)
        self.assertNotIn('<script>', rendered)
        escaped = highlight_content('<span>&lt;img src=x onerror=alert(1)&gt;</span>', '<img')
        self.assertNotIn('<img', escaped)
        self.assertEqual(Text(escaped).tags, ['span', 'mark'])

    def test_offset_normalization_agrees_with_search_normalization(self):
        for text in (
            '  ĂÂÎȘȚ ŞŢ cafe\u0301\n', 'œ Œ æ Æ ø Ø ł Ł l·l L·L ŀl ĿL a·b',
            '\u0301e\u0301\u0327', 'Straße ﬃ', '가 각', '🙂 français العربية বাংলা',
        ):
            with self.subTest(text=text):
                normalized, offsets = _normalized_with_offsets(text)
                self.assertEqual(normalized, remove_diacritics(text).upper())
                self.assertEqual(len(offsets), len(normalized))
                self.assertTrue(all(0 <= start < end <= len(text) for start, end in offsets))


if __name__ == '__main__':
    unittest.main()
