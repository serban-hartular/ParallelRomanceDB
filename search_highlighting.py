"""Highlight literal normalized matches without changing stored cell content."""

from html import escape
from html.parser import HTMLParser
import unicodedata

from text_normalization import LATIN_EXPANSIONS, remove_diacritics


def _normalized_with_offsets(text):
    """Map normalized, uppercased characters back to original text ranges."""
    decomposed = []
    offsets = []
    for index, character in enumerate(text):
        for part in unicodedata.normalize('NFD', character):
            if unicodedata.category(part) == 'Mn':
                if offsets:
                    offsets[-1] = (offsets[-1][0], index + 1)
            else:
                decomposed.append(part)
                offsets.append((index, index + 1))

    # NFC can combine multiple source characters, including decomposed Hangul.
    expanded = []
    position = 0
    for character in unicodedata.normalize('NFC', ''.join(decomposed)):
        length = len(unicodedata.normalize('NFD', character))
        source = (offsets[position][0], offsets[position + length - 1][1])
        expanded.extend((part, source) for part in character.translate(LATIN_EXPANSIONS))
        position += length

    normalized = []
    mapping = []
    for index, (character, source) in enumerate(expanded):
        if (
            character == '·' and 0 < index < len(expanded) - 1
            and expanded[index - 1][0] in 'lL' and expanded[index + 1][0] in 'lL'
        ):
            continue
        # pandas literal, case-insensitive searching uses uppercase comparisons.
        for part in character.upper():
            normalized.append(part)
            mapping.append(source)
    return ''.join(normalized), mapping


def match_ranges(text, query):
    """Return original text ranges matching the website's normalized search."""
    needle = remove_diacritics(query).upper()
    if not needle:
        return []
    normalized, offsets = _normalized_with_offsets(text)
    ranges = []
    position = 0
    while (found := normalized.find(needle, position)) != -1:
        start = offsets[found][0]
        end = offsets[found + len(needle) - 1][1]
        if ranges and start <= ranges[-1][1]:
            ranges[-1] = (ranges[-1][0], max(end, ranges[-1][1]))
        else:
            ranges.append((start, end))
        position = found + len(needle)
    return ranges


class _CellHTML(HTMLParser):
    """Separate escaped importer HTML into markup and decoded text nodes."""

    def __init__(self, content):
        super().__init__(convert_charrefs=True)
        self.tokens = []
        self.feed(content)
        self.close()

    def handle_starttag(self, tag, attrs):
        self.tokens.append((False, self.get_starttag_text()))

    def handle_startendtag(self, tag, attrs):
        self.tokens.append((False, self.get_starttag_text()))

    def handle_endtag(self, tag):
        self.tokens.append((False, f'</{tag}>'))

    def handle_comment(self, data):
        self.tokens.append((False, f'<!--{data}-->'))

    def handle_data(self, data):
        self.tokens.append((True, data))


def highlight_content(content, query, *, plaintext=False):
    """Return highlighted HTML, or None if the cell has no matching text.

    Formatted input must be trusted HTML from the escaped workbook converter.
    Plaintext is escaped before inserting marks. Match across rich-text runs,
    wrapping each affected text node separately to preserve valid formatting.
    Query text is never inserted as markup, and attributes are never searched.
    """
    if not query:
        return None
    tokens = [(True, content)] if plaintext else _CellHTML(content).tokens
    text = ''.join(value for is_text, value in tokens if is_text)
    ranges = match_ranges(text, query)
    if not ranges:
        return None

    output = []
    offset = 0
    match = 0
    for is_text, value in tokens:
        if not is_text:
            output.append(value)
            continue
        end = offset + len(value)
        cursor = 0
        while match < len(ranges) and ranges[match][0] < end:
            start, stop = ranges[match]
            if stop <= offset:
                match += 1
                continue
            local_start = max(0, start - offset)
            local_stop = min(len(value), stop - offset)
            output.append(escape(value[cursor:local_start], quote=False))
            output.append('<mark class="search-highlight">')
            output.append(escape(value[local_start:local_stop], quote=False))
            output.append('</mark>')
            cursor = local_stop
            if stop > end:
                break
            match += 1
        output.append(escape(value[cursor:], quote=False))
        offset = end
    return ''.join(output)
