"""Search modes, safe normalization, highlighting, and request persistence.

Every workbook/database in this file is disposable.
"""

from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
import unittest
from unittest.mock import patch

from openpyxl import Workbook
import pandas as pd

from df_search import search_dataframe
from main import create_app
from search_highlighting import highlight_content, match_ranges
from search_query import SearchError, SearchQuery
from text_normalization import remove_diacritics
from tests.test_flask_app import Page


class RegexQueryTests(unittest.TestCase):
    def test_four_modes_and_case(self):
        for regex in (False, True):
            for diacritics in (False, True):
                with self.subTest(regex=regex, diacritics=diacritics):
                    query = SearchQuery("CAFÉ", diacritics=diacritics, regex=regex)
                    self.assertEqual(query.query, "CAFÉ" if diacritics else "CAFE")
                    normalize = (lambda text: text) if diacritics else remove_diacritics
                    self.assertTrue(query.matches(normalize("café")))
                    self.assertEqual(query.matches("cafe"), not diacritics)
        self.assertFalse(SearchQuery("cafe|vin").matches("vin"))
        self.assertTrue(SearchQuery("cafe|vin", regex=True).matches("vin"))
        self.assertFalse(
            SearchQuery("CAFÉ", regex=True, diacritics=True, case_sensitive=True).matches("café")
        )

    def test_unicode_boundaries_and_casefold(self):
        query = SearchQuery(r"\bcafé\b", regex=True, diacritics=True)
        self.assertTrue(query.matches("CAFÉ et vin"))
        self.assertFalse(query.matches("caféteria"))
        self.assertEqual(match_ranges("Straße", r"strasse", regex=True, diacritics=True), [(0, 6)])
        self.assertEqual(
            match_ranges("café caféteria", r"\bcafé\b", regex=True, diacritics=True), [(0, 4)]
        )

    def test_normalized_pattern_is_visible_and_idempotent(self):
        examples = {
            "café|cœur": "cafe|coeur",
            "œ+": "(?:oe)+",
            "Æ{2}": "(?:AE){2}",
            "[éœx]+": "(?:[ex]|oe)+",
            "[^é]": "[^e]",
            r"caf\u00e9": "cafe",
            r"\N{LATIN SMALL LIGATURE OE}+": "(?:oe)+",
            r"\é": "e",
            r"\œ+": "(?:oe)+",
            r"[\éœ]": "(?:[e]|oe)",
            "e\u0301": "e",
            "l·l": "ll",
            "l\u0301·l": "ll",
            "l·\u0301l": "ll",
            "가": "가",
            r"\u1100\u1161\u11a8": "각",
            "(?P<word>café)\\s+(?P=word)": r"(?P<word>cafe)\s+(?P=word)",
            r"\p{L}+\Wcafé": r"\p{L}+\Wcafe",
            r"café\+\[\]": "cafe" + r"\+\[\]",
        }
        for original, effective in examples.items():
            with self.subTest(original=original):
                query = SearchQuery(original, regex=True)
                self.assertEqual(query.query, effective)
                self.assertEqual(SearchQuery(query.query, regex=True).query, effective)
        self.assertTrue(SearchQuery("œ+", regex=True).matches("oeoe"))
        self.assertFalse(SearchQuery("^œ+$", regex=True).matches("oeee"))
        self.assertTrue(SearchQuery("[éœx]+", regex=True).matches("oeex"))
        self.assertTrue(SearchQuery("가+", regex=True).matches("가가"))

    def test_normalized_ranges_and_unchanged_syntax(self):
        query = SearchQuery("^[à-å]+$", regex=True)
        self.assertEqual(query.query, "^[a]+$")
        self.assertTrue(query.matches("aaa"))
        for pattern in (
            r"[a-z]+",
            r"[^\W\d_]+",
            r"[[:alpha:]]+",
            r"\d{2,4}",
            r"\b[A-Z]\w*",
            r"\{é\}",
            r"\141",
            r"\t+",
            r"[]-]+",
            r"[\1-\3]",
        ):
            with self.subTest(pattern=pattern):
                query = SearchQuery(pattern, regex=True)
                self.assertEqual(query.query, pattern.replace("é", "e"))
        for pattern in ("cœur", "[^œ]", "[a-\uffff]", "[·]"):
            self.assertEqual(SearchQuery(pattern, regex=True, diacritics=True).query, pattern)

    def test_reject_ambiguous_and_invalid_patterns(self):
        for pattern in (
            "[",
            "(",
            "\\",
            "*a",
            "a{bogus}",
            r"\xGG",
            r"\uD800",
            "[^œ]",
            "[·]",
            r"l·[l]",
            r"e\u0301+",
            "\u0301",
            "[\u0301]",
            r"(?R)",
            r"(?x)café",
            r"(?V1)a",
            r"a{e<=1}",
            r"[a-\uffff]",
        ):
            with self.subTest(pattern=pattern):
                with self.assertRaises(SearchError):
                    SearchQuery(pattern, regex=True)

    def test_pattern_complexity_limits(self):
        for pattern in (
            "a" * 501,
            "œ" * 251,
            "(" * 33 + "a" + ")" * 33,
            "a{1001}",
            "(a{101}){100}",
        ):
            with self.subTest(pattern=pattern):
                with self.assertRaises(SearchError):
                    SearchQuery(pattern, regex=True)
        self.assertTrue(SearchQuery("^a{1000}$", regex=True).matches("a" * 1000))
        self.assertTrue(SearchQuery("", regex=True).matches("anything"))
        self.assertEqual(match_ranges("anything", "^", regex=True), [])

    def test_timeout_bounds_pathological_matching_and_highlighting(self):
        text = "a" * 10000 + "!"
        for operation in ("matches", "ranges"):
            started = monotonic()
            with self.assertRaisesRegex(SearchError, "too long"):
                getattr(SearchQuery("(a|aa)+$", regex=True, timeout=0.005), operation)(text)
            self.assertLess(monotonic() - started, 1)
        # Matching time is shared across every cell, not reset per call.
        query = SearchQuery("a", regex=True, timeout=0.1)
        with patch("search_query.monotonic", side_effect=[10, 10.06, 10.06, 10.12]):
            self.assertTrue(query.matches("a"))
            self.assertTrue(query.matches("a"))
        with self.assertRaisesRegex(SearchError, "too long"):
            query.matches("a")

    def test_deadline_covers_scanning_and_highlight_count_is_bounded(self):
        query = SearchQuery("a", regex=True, timeout=0.01)
        with patch("search_query.monotonic", side_effect=[10, 10, 10.02]):
            with query.scanning():
                with self.assertRaises(SearchError):
                    query.matches("a")
        with self.assertRaisesRegex(SearchError, "Too many"):
            SearchQuery("a", regex=True).ranges("a " * 10001)

    def test_highlights_keep_original_characters_and_formatting(self):
        html = "<b>ca</b><i>fé &amp; cœur</i>"
        result = highlight_content(html, r"café\s+&\s+cœur", regex=True)
        self.assertEqual(
            result,
            '<b><mark class="search-highlight">ca</mark></b><i><mark class="search-highlight">fé &amp; cœur</mark></i>',
        )
        self.assertEqual(match_ranges("œœ café", r"œ+", regex=True), [(0, 2)])
        self.assertEqual(match_ranges("e\u0301", r"é", regex=True), [(0, 2)])
        self.assertEqual(match_ranges("l·l", r"l·l", regex=True), [(0, 3)])
        self.assertEqual(match_ranges("cafe café", r"café", regex=True, diacritics=True), [(5, 9)])
        self.assertEqual(match_ranges("café cafe", r"cafe"), [(0, 4), (5, 9)])
        self.assertIsNone(highlight_content('<a title="café">wine</a>', r"café", regex=True))
        self.assertEqual(
            highlight_content("<script>", r"<.*>", plaintext=True, regex=True),
            '<mark class="search-highlight">&lt;script&gt;</mark>',
        )
        self.assertEqual(
            highlight_content('  <b>café</b>\n', '^café$', regex=True, search_text='café'),
            '  <b><mark class="search-highlight">café</mark></b>\n',
        )


class RegexRequestTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        workbook = Workbook()
        sheet = workbook.active
        sheet.append([None, "LIMBA FRANCEZĂ", "LIMBA ROMÂNĂ"])
        for name, text, other in (
            ("FIRST", "  café cœur  ", "ceai"),
            ("SECOND", "cafe vin", "café"),
            ("THIRD", "vin", "apă"),
        ):
            sheet.append(["ETIMON/", name, None])
            sheet.append(["SENSURI DE BAZĂ", text, other])
        source = Path(self.directory.name) / "search.xlsx"
        workbook.save(source)
        workbook.close()
        self.app = create_app(
            source,
            test_config={"TESTING": True, "SECRET_KEY": "test-search", "DEFAULT_UI_LANGUAGE": "en"},
        )
        self.addCleanup(self.app.extensions["lexicon_store"].close)
        self.client = self.app.test_client()

    def search(self, query, **options):
        return self.client.get("/", query_string={"search": "1", "q": query, **options})

    def test_database_and_dataframe_parity_with_filters(self):
        store = self.app.extensions["lexicon_store"]
        frame = store.to_dataframe()
        original = frame.copy(deep=True)
        for diacritics in (False, True):
            for regex in (False, True):
                for query in ("café", "^cafe$", "café|vin", "œ", ""):
                    with self.subTest(query=query, diacritics=diacritics, regex=regex):
                        actual = store.matching_numbers(
                            query,
                            ("SENSURI DE BAZĂ",),
                            ("LIMBA FRANCEZĂ",),
                            diacritics=diacritics,
                            regex=regex,
                        )
                        expected = search_dataframe(
                            frame,
                            query,
                            label="SENSURI DE BAZĂ",
                            column="LIMBA FRANCEZĂ",
                            diacritics=diacritics,
                            regex=regex,
                            case_sensitive=False,
                        )
                        self.assertEqual(list(actual), expected)
        self.assertEqual(
            store.matching_numbers(
                "café", columns=("LIMBA FRANCEZĂ",), diacritics=True, regex=True
            ),
            (1,),
        )
        self.assertEqual(
            store.matching_numbers("café", columns=("LIMBA ROMÂNĂ",), diacritics=True, regex=True),
            (2,),
        )
        pd.testing.assert_frame_equal(frame, original)
        fallback = frame.drop(columns="nodiacritics_plaintext")
        self.assertEqual(search_dataframe(fallback, "café", case_sensitive=False), [1, 2])

    def test_normalized_form_payload_and_saved_switches(self):
        response = self.search("café|cœur", regex=1, column="LIMBA FRANCEZĂ")
        self.assertEqual(response.status_code, 200)
        page = Page(response)
        self.assertEqual(page.query, "cafe|coeur")
        self.assertEqual(page.matches, [1, 2])
        self.assertTrue(page.payload["criteria"]["regex"])
        self.assertFalse(page.payload["criteria"]["diacritics"])
        self.assertIsNone(page.payload["search_notice"])
        self.assertIn("checked", response.text.split('name="regex"')[1].split(">")[0])
        self.assertEqual(
            Page(self.client.get("/?etimon=2")).payload["criteria"], page.payload["criteria"]
        )
        self.assertEqual(
            Page(self.client.get("/?plaintext=1", headers={"HX-Request": "true"})).payload[
                "criteria"
            ],
            page.payload["criteria"],
        )
        response = self.search(r"\bcafé\b", regex=1, diacritics=1, column="LIMBA FRANCEZĂ")
        self.assertEqual(Page(response).matches, [1])
        self.assertEqual(Page(response).query, r"\bcafé\b")
        self.assertFalse(Page(self.client.get("/?reset=1")).payload["criteria"]["regex"])
        self.assertFalse(Page(self.client.get("/")).payload["criteria"]["diacritics"])
        self.app.config["SEARCH_SHOW_NOTICES"] = True
        for headers in ({}, {"HX-Request": "true"}):
            response = self.client.get("/", query_string={"search": 1, "q": "café", "regex": 1},
                                       headers=headers)
            page = Page(response)
            self.assertIn("normalized query", page.payload["search_notice"])
            self.assertEqual(page.payload["criteria"]["query"], "cafe")
            self.assertIsNone(page.payload["search_error"])

    def test_searches_preserve_stored_content_and_export_and_exclude_trash(self):
        from excel_export import workbook_bytes

        store = self.app.extensions["lexicon_store"]
        original = store.to_dataframe().copy(deep=True)
        source = Path(self.directory.name) / "search.xlsx"
        workbook = source.read_bytes()
        for regex in (False, True):
            for diacritics in (False, True):
                self.search("café", regex=int(regex), diacritics=int(diacritics))
        pd.testing.assert_frame_equal(store.to_dataframe(), original)
        self.assertEqual(source.read_bytes(), workbook)
        self.assertEqual(workbook_bytes(store), workbook)
        store.delete_etymon(1)
        self.assertEqual(store.matching_numbers("cœur", regex=True), ())
        self.assertEqual(store.matching_numbers("café", regex=True, diacritics=True), (2,))

    def test_regex_anchors_use_stored_plaintext_and_preserve_outer_spacing(self):
        for plaintext in (0, 1):
            page = Page(self.search('^café cœur$', regex=1, diacritics=1,
                                    column='LIMBA FRANCEZĂ', plaintext=plaintext))
            self.assertEqual(page.matches, [1])
            row = next(row for row in page.payload['rows'] if row['label'] == 'SENSURI DE BAZĂ')
            highlight = row['highlights']['content_0']
            self.assertIn('<mark class="search-highlight">café cœur</mark>', highlight)
            self.assertEqual('  café cœur  ' in row['content_0'], not plaintext)

    def test_errors_are_inline_localized_and_do_not_replace_good_preferences(self):
        self.search("vin", regex=1, diacritics=1)
        good = Page(self.client.get("/")).payload["criteria"]
        for headers in ({}, {"HX-Request": "true"}):
            response = self.client.get("/?search=1&q=[&regex=1", headers=headers)
            self.assertEqual(response.status_code, 200)
            page = Page(response)
            self.assertEqual(page.matches, [])
            self.assertIn("Invalid regex", page.payload["search_error"])
            self.assertIn("Correct the search", response.text)
            self.assertEqual(Page(self.client.get("/")).payload["criteria"], good)
        response = self.client.get("/?search=1&q=[&regex=1", headers={"X-Interface-Language": "ro"})
        self.assertIn("Expresie regulată nevalidă", Page(response).payload["search_error"])
        self.assertIn(self.app.extensions["translations"]["Match diacritics"]["ro"], response.text)
        self.assertNotIn("unterminated", response.text)

    def test_legacy_preferences_and_unchecked_switches(self):
        with self.client.session_transaction() as session:
            session["search"] = {"query": "cafe", "label": [], "column": []}
        self.assertEqual(
            Page(self.client.get("/")).payload["criteria"],
            {"query": "cafe", "label": [], "column": [], "regex": False, "diacritics": False},
        )
        self.search("café", diacritics=1, regex=1)
        page = Page(self.search("cafe"))
        self.assertFalse(page.payload["criteria"]["regex"])
        self.assertFalse(page.payload["criteria"]["diacritics"])

    def test_live_requests_keep_switches_without_overwriting_preferences(self):
        self.search("vin")
        response = self.client.get(
            "/",
            query_string={
                "live": "1",
                "search": "1",
                "q": "café",
                "regex": "1",
                "diacritics": "1",
                "column": "LIMBA FRANCEZĂ",
            },
            headers={"HX-Request": "true"},
        )
        page = Page(response)
        self.assertEqual(page.matches, [1])
        self.assertTrue(page.payload["criteria"]["regex"])
        self.assertTrue(page.payload["criteria"]["diacritics"])
        self.assertEqual(Page(self.client.get("/")).query, "vin")

    def test_switches_are_saved_separately_for_each_collection(self):
        from collection_catalog import CollectionCatalog

        catalog_path = Path(self.directory.name) / "catalog.sqlite3"
        catalog = CollectionCatalog(catalog_path)
        a = catalog.create("One", Path(self.directory.name) / "search.xlsx")
        b = catalog.create("Two", Path(self.directory.name) / "search.xlsx")
        catalog.close()
        app = create_app(
            catalog_path=catalog_path,
            test_config={"TESTING": True, "SECRET_KEY": "regex-collections"},
        )
        self.addCleanup(app.extensions["collection_catalog"].close)
        client = app.test_client()
        url_a = f"/collections/{a['id']}/"
        url_b = f"/collections/{b['id']}/"
        client.get(url_a, query_string={"search": 1, "q": "café", "regex": 1, "diacritics": 1})
        self.assertFalse(Page(client.get(url_b)).payload["criteria"]["regex"])
        client.get(url_b, query_string={"search": 1, "q": "vin"})
        saved = Page(client.get(url_a)).payload["criteria"]
        self.assertTrue(saved["regex"])
        self.assertTrue(saved["diacritics"])
        self.assertEqual(saved["query"], "café")

    def test_timeout_reports_failure_without_partial_matches_or_new_preferences(self):
        self.search("vin")
        with patch(
            "lexicon_db.SearchQuery.matches",
            side_effect=SearchError(
                "Regex search took too long. Simplify the pattern or narrow the filters."
            ),
        ):
            page = Page(self.search("cafe", regex=1))
        self.assertEqual(page.matches, [])
        self.assertIn("too long", page.payload["search_error"])
        self.assertEqual(Page(self.client.get("/")).query, "vin")
        with patch(
            "main.highlight_content",
            side_effect=SearchError("Too many regex highlights. Narrow the pattern or filters."),
        ):
            page = Page(self.search("cafe", regex=1))
        self.assertEqual(page.matches, [1, 2])
        self.assertTrue(all(not row["highlights"] for row in page.payload["rows"]))
        self.assertIn("Too many", page.payload["search_error"])
        self.assertEqual(Page(self.client.get("/")).query, "vin")


if __name__ == "__main__":
    unittest.main()
