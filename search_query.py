"""One effective query for selection and rich-text highlighting.

Regex literals use the same normalization as stored search text. Syntax is
preserved; expansions are grouped before repetition, and ambiguous sets fail
with a user-facing error instead of silently changing their meaning.
"""

from contextlib import contextmanager
from dataclasses import dataclass
import re
from time import monotonic
import unicodedata

import regex as engine

from i18n import gettext as _
from text_normalization import remove_diacritics

MAX_PATTERN_LENGTH = 500
MAX_EFFECTIVE_LENGTH = 500
MAX_RANGE = 256
MAX_DEPTH = 32
MAX_REPETITION = 1000
MAX_REPEAT_PRODUCT = 10000
DEFAULT_TIMEOUT = 1.0


class SearchError(ValueError):
    pass


def _literal(text):
    return "".join(
        f"\\x{ord(char):02x}" if ord(char) < 32 or ord(char) == 127 else re.escape(char)
        for char in text
    )


@dataclass
class _Token:
    kind: str
    value: str
    raw: str | None = None


class _Pattern:
    def __init__(self, pattern, fold):
        self.pattern, self.fold, self.index = pattern, fold, 0
        self.tokens = []
        self.depth, self.repeat_product = 0, 1

    def error(self):
        raise SearchError(_("Invalid regex. Check brackets, escapes, and repetition operators."))

    def escape(self, in_class=False):
        start = self.index
        self.index += 1
        if self.index >= len(self.pattern):
            self.error()
        char = self.pattern[self.index]
        self.index += 1
        widths = {"x": 2, "u": 4, "U": 8}
        if char in widths:
            digits = self.pattern[self.index : self.index + widths[char]]
            if len(digits) != widths[char] or not re.fullmatch("[0-9a-fA-F]+", digits):
                self.error()
            self.index += widths[char]
            try:
                value = chr(int(digits, 16))
            except ValueError:
                self.error()
            if 0xD800 <= ord(value) <= 0xDFFF:
                self.error()
            return _Token("literal", value, self.pattern[start : self.index])
        if char == "N" and self.pattern[self.index : self.index + 1] == "{":
            end = self.pattern.find("}", self.index)
            if end < 0:
                self.error()
            try:
                value = unicodedata.lookup(self.pattern[self.index + 1 : end])
            except KeyError:
                self.error()
            self.index = end + 1
            return _Token("literal", value, self.pattern[start : self.index])
        if char in "pP" and self.pattern[self.index : self.index + 1] == "{":
            end = self.pattern.find("}", self.index)
            if end < 0:
                self.error()
            self.index = end + 1
            return _Token("syntax", self.pattern[start : self.index])
        if char in "01234567":
            digits = char
            while (
                len(digits) < 3
                and self.index < len(self.pattern)
                and self.pattern[self.index] in "01234567"
            ):
                digits += self.pattern[self.index]
                self.index += 1
            if in_class or char == "0" or len(digits) == 3:
                return _Token("literal", chr(int(digits, 8)), self.pattern[start : self.index])
            return _Token("syntax", self.pattern[start : self.index])
        escapes = {"n": "\n", "r": "\r", "t": "\t", "f": "\f", "v": "\v", "a": "\a"}
        if char in escapes:
            return _Token("literal", escapes[char], self.pattern[start : self.index])
        if char == "b" and in_class:
            return _Token("literal", "\b", self.pattern[start : self.index])
        if not char.isascii() or not char.isalnum():
            return _Token("literal", char, self.pattern[start : self.index])
        # Group references and categories retain their exact syntax/case.
        if char in "gk" and self.pattern[self.index : self.index + 1] == "<":
            end = self.pattern.find(">", self.index)
            if end < 0:
                self.error()
            self.index = end + 1
        return _Token("syntax", self.pattern[start : self.index])

    def character_class(self):
        start = self.index
        self.index += 1
        negative = self.pattern[self.index : self.index + 1] == "^"
        if negative:
            self.index += 1
        items = []
        if self.pattern[self.index : self.index + 1] == "]":
            items.append(_Token("literal", "]"))
            self.index += 1
        while self.index < len(self.pattern) and self.pattern[self.index] != "]":
            char = self.pattern[self.index]
            if self.pattern[self.index : self.index + 2] == "[:":
                end = self.pattern.find(":]", self.index)
                if end < 0:
                    self.error()
                items.append(_Token("syntax", self.pattern[self.index : end + 2]))
                self.index = end + 2
            elif char == "\\":
                items.append(self.escape(True))
            else:
                items.append(_Token("dash" if char == "-" else "literal", char))
                self.index += 1
        if self.index >= len(self.pattern):
            self.error()
        self.index += 1
        if not self.fold:
            return self.pattern[start : self.index]
        chars, syntax = [], []
        index = 0
        while index < len(items):
            item = items[index]
            if index + 2 < len(items) and items[index + 1].kind == "dash":
                last = items[index + 2]
                if (
                    item.kind != "literal"
                    or last.kind != "literal"
                    or len(item.value) != 1
                    or len(last.value) != 1
                ):
                    self.error()
                count = ord(last.value) - ord(item.value) + 1
                if count <= 0:
                    self.error()
                if count > MAX_RANGE:
                    raise SearchError(
                        _(
                            "This character range is too large to normalize. Narrow it or enable Match diacritics."
                        )
                    )
                chars.extend(chr(code) for code in range(ord(item.value), ord(last.value) + 1))
                index += 3
            else:
                (syntax if item.kind == "syntax" else chars).append(item.value)
                index += 1
        if "·" in chars:
            raise SearchError(
                _(
                    "A middle dot inside a character class cannot be normalized safely. Enable Match diacritics or use the normalized spelling."
                )
            )
        images = list(dict.fromkeys(remove_diacritics(char) for char in chars))
        if any(not image for image in images):
            raise SearchError(
                _(
                    "A standalone combining mark cannot be normalized safely. Enable Match diacritics or remove it."
                )
            )
        singles = [image for image in images if len(image) == 1]
        expanded = [image for image in images if len(image) > 1]
        if negative and expanded:
            raise SearchError(
                _(
                    "A negated character class containing a ligature cannot be normalized safely. Enable Match diacritics or rewrite the pattern."
                )
            )
        if all(remove_diacritics(char) == char for char in chars):
            return self.pattern[start : self.index]
        body = "".join(
            "\\" + char if char in "\\]-^" else _literal(char) for char in singles
        ) + "".join(syntax)
        branches = []
        if body:
            branches.append("[" + ("^" if negative else "") + body + "]")
        branches.extend(_literal(image) for image in expanded)
        if not branches:
            self.error()
        return (
            branches[0] if len(branches) == 1 and not expanded else "(?:" + "|".join(branches) + ")"
        )

    def parse(self):
        while self.index < len(self.pattern):
            char = self.pattern[self.index]
            if char == "\\":
                self.tokens.append(self.escape())
                continue
            if char == "[":
                self.tokens.append(_Token("atom", self.character_class()))
                continue
            if char == "(":
                # Only well-defined group headers/flags are accepted. In particular
                # recursive/fuzzy/verbose constructs cannot bypass our complexity scan.
                rest = self.pattern[self.index :]
                header = re.match(r"\(\?(?:P<\w+>|<\w+>|P=\w+\)|[:=!]|<[=!]|[imsafu-]+[:)])", rest)
                if rest.startswith("(?") and not header:
                    raise SearchError(
                        _(
                            "Unsupported regex group or inline flag. Use ordinary groups and the i, m, s, f, a, or u flags."
                        )
                    )
                value = header[0] if header else "("
                self.tokens.append(_Token("syntax", value))
                self.index += len(value)
                if not value.endswith(")"):
                    self.depth += 1
                    if self.depth > MAX_DEPTH:
                        raise SearchError(
                            _("The regex is too deeply nested. Simplify the pattern.")
                        )
                continue
            if char == ")":
                self.depth -= 1
            if char == "{":
                repeat = re.match(r"\{(\d+)(?:,(\d*))?\}", self.pattern[self.index :])
                if repeat:
                    count = max(int(repeat[1]), int(repeat[2] or repeat[1]))
                    self.repeat_product *= max(count, 1)
                    if count > MAX_REPETITION or self.repeat_product > MAX_REPEAT_PRODUCT:
                        raise SearchError(
                            _("The regex repetition limit was exceeded. Simplify the pattern.")
                        )
                    self.tokens.append(_Token("repeat", repeat[0]))
                    self.index += len(repeat[0])
                    continue
                self.error()
            self.tokens.append(
                _Token(
                    "repeat" if char in "*+?" else "syntax" if char in ".^$|)" else "literal", char
                )
            )
            self.index += 1
        if self.fold:
            # NFC also composes consecutive non-mark characters (Hangul Jamo).
            # Keep these literal syllables consistent with stored normalized
            # text. Combining marks remain separate so a repeated mark is still
            # rejected rather than silently attaching its repeat to a letter.
            composed = []
            for token in self.tokens:
                previous = composed[-1] if composed else None
                if previous and previous.kind == token.kind == "literal":
                    pair = previous.value + token.value
                    combined = unicodedata.normalize("NFC", pair)
                    if combined != pair and all(unicodedata.category(c) != "Mn" for c in pair):
                        composed[-1] = _Token("literal", combined)
                        continue
                composed.append(token)
            self.tokens = composed
        result = []
        for index, token in enumerate(self.tokens):
            if token.kind != "literal":
                result.append(token.value)
                continue
            value = remove_diacritics(token.value) if self.fold else token.value
            repeated = index + 1 < len(self.tokens) and self.tokens[index + 1].kind == "repeat"
            # Catalan l·l uses context-dependent normalization. Handle literal
            # runs, and reject dots whose context is hidden inside regex structure.
            if self.fold and value == "·":
                # Combining marks disappear before the shared whole-text
                # normalizer examines l·l, including decomposed accents.
                def neighbor(step):
                    position = index + step
                    while 0 <= position < len(self.tokens):
                        candidate = self.tokens[position]
                        if candidate.kind != "literal" or remove_diacritics(candidate.value):
                            return candidate
                        position += step
                    return None

                left, right = neighbor(-1), neighbor(1)
                if left and right and left.kind == right.kind == "literal":
                    if remove_diacritics(left.value) in ("l", "L") and remove_diacritics(
                        right.value
                    ) in ("l", "L"):
                        value = ""
                elif (
                    repeated
                    or (left and left.kind != "literal")
                    or (right and right.kind != "literal")
                ):
                    raise SearchError(
                        _(
                            "This middle dot cannot be normalized safely in its regex context. Enable Match diacritics or use the normalized spelling."
                        )
                    )
            if self.fold and not value and (repeated or token.value != "·"):
                if repeated or len(self.tokens) == 1:
                    raise SearchError(
                        _(
                            "A standalone combining mark cannot be normalized safely. Enable Match diacritics or remove it."
                        )
                    )
            value = (
                (token.raw if token.raw is not None else token.value)
                if value == token.value
                else _literal(value)
            )
            if repeated and len(remove_diacritics(token.value) if self.fold else token.value) > 1:
                value = "(?:" + value + ")"
            result.append(value)
        return "".join(result) if self.fold else self.pattern


class SearchQuery:
    def __init__(
        self, query, *, diacritics=False, regex=False, case_sensitive=False, timeout=DEFAULT_TIMEOUT
    ):
        self.original = query
        self.diacritics, self.regex = diacritics, regex
        self.remaining = float(timeout)
        self.compiled = None
        self.deadline = None
        if regex:
            if len(query) > MAX_PATTERN_LENGTH:
                raise SearchError(_("The regex is too long. Use at most 500 characters."))
            self.query = _Pattern(query, not diacritics).parse()
            if query and not self.query:
                raise SearchError(
                    _("The regex becomes empty after normalization. Enter a searchable pattern.")
                )
            if len(self.query) > MAX_EFFECTIVE_LENGTH:
                raise SearchError(_("The normalized regex is too long. Simplify the pattern."))
            try:
                flags = (
                    engine.VERSION0 | engine.FULLCASE | (0 if case_sensitive else engine.IGNORECASE)
                )
                self.compiled = engine.compile(self.query, flags)
            except (engine.error, RecursionError, OverflowError):
                raise SearchError(
                    _("Invalid regex. Check brackets, escapes, and repetition operators.")
                ) from None
        else:
            self.query = query if diacritics else remove_diacritics(query)
        if len(self.query) > MAX_EFFECTIVE_LENGTH:
            raise SearchError(_("The normalized query is too long. Use at most 500 characters."))
        self.case_sensitive = case_sensitive
        self.changed = self.query != query

    @contextmanager
    def scanning(self):
        self.deadline = monotonic() + self.remaining
        try:
            yield
        finally:
            self.deadline = None

    def _available(self):
        return (
            min(self.remaining, self.deadline - monotonic())
            if self.deadline is not None
            else self.remaining
        )

    def _run(self, function, text):
        started = monotonic()
        available = self._available()
        if available <= 0:
            raise SearchError(
                _("Regex search took too long. Simplify the pattern or narrow the filters.")
            )
        try:
            return function(text, timeout=available, concurrent=True)
        except TimeoutError:
            raise SearchError(
                _("Regex search took too long. Simplify the pattern or narrow the filters.")
            ) from None
        finally:
            self.remaining -= monotonic() - started

    def matches(self, text):
        if self.regex:
            return self._run(self.compiled.search, text) is not None
        return self.query in text if self.case_sensitive else self.query.upper() in text.upper()

    def ranges(self, text):
        if not self.regex:
            haystack = text if self.case_sensitive else text.upper()
            needle = self.query if self.case_sensitive else self.query.upper()
            if not needle:
                return []
            result = []
            position = 0
            while (start := haystack.find(needle, position)) != -1:
                result.append((start, start + len(needle)))
                position = start + len(needle)
            return result
        # Consume the iterator within one timed operation: each individual match
        # must not receive a fresh full timeout. Zero-length hits are not marked.
        started = monotonic()
        available = self._available()
        if available <= 0:
            raise SearchError(
                _("Regex search took too long. Simplify the pattern or narrow the filters.")
            )
        try:
            ranges = []
            for match in self.compiled.finditer(text, timeout=available, concurrent=True):
                start, end = match.span()
                if start == end:
                    continue
                if ranges and start <= ranges[-1][1]:
                    ranges[-1] = (ranges[-1][0], max(end, ranges[-1][1]))
                else:
                    ranges.append((start, end))
                if len(ranges) > 10000:
                    raise SearchError(
                        _("Too many regex highlights. Narrow the pattern or filters.")
                    )
            return ranges
        except TimeoutError:
            raise SearchError(
                _("Regex search took too long. Simplify the pattern or narrow the filters.")
            ) from None
        finally:
            self.remaining -= monotonic() - started
