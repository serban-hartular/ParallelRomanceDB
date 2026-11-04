"""Shared Unicode normalization for search text."""

import re
import unicodedata


LATIN_EXPANSIONS = str.maketrans({
    'œ': 'oe', 'Œ': 'OE',
    'æ': 'ae', 'Æ': 'AE',
    'ø': 'o', 'Ø': 'O',
    'ł': 'l', 'Ł': 'L',
    'ŀ': 'l', 'Ŀ': 'L',
})


def remove_diacritics(text: str) -> str:
    """Remove accents and expand common Latin ligatures and letter variants.

    Handles composed/decomposed diacritics, œ/æ ligatures, ø/ł letters,
    and Catalan l·l (including the older ŀl spelling). Preserves case,
    whitespace, and middle dots that are not between two l/L letters.
    """
    decomposed = unicodedata.normalize('NFD', text)
    unaccented = ''.join(
        character for character in decomposed
        if unicodedata.category(character) != 'Mn'
    )
    expanded = unicodedata.normalize('NFC', unaccented).translate(LATIN_EXPANSIONS)
    return re.sub(r'(?<=[lL])·(?=[lL])', '', expanded)
