"""Validate Quill's text-only Delta and render escaped, inline-formatted HTML."""

from i18n import gettext as _

from html import escape
import re


def validate_line_height(value):
    """Allow a unitless whole-cell line height, or the stylesheet default."""
    if value is None:
        return None
    if (
        isinstance(value, bool) or not isinstance(value, (int, float))
        or not 0.5 <= value <= 4
    ):
        raise ValueError(_('Line spacing must be a number between 0.5 and 4.'))
    return float(value)


def _color(value):
    if isinstance(value, str):
        if re.fullmatch(r'#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?', value):
            return value
        match = re.fullmatch(r'rgb\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)', value)
        if match and all(int(part) <= 255 for part in match.groups()):
            return value
    raise ValueError(_('Unsupported text color.'))


def _styles(attributes):
    if not isinstance(attributes, dict):
        raise ValueError(_('Invalid text formatting.'))
    styles = []
    decorations = []
    for name, value in attributes.items():
        if name in ('bold', 'italic', 'underline', 'strike'):
            if not isinstance(value, bool):
                raise ValueError(_('Invalid text formatting.'))
            if name == 'bold':
                styles.append(f"font-weight: {'bold' if value else 'normal'}")
            elif name == 'italic':
                styles.append(f"font-style: {'italic' if value else 'normal'}")
            elif value:
                decorations.append('underline' if name == 'underline' else 'line-through')
        elif name == 'script' and value in ('sub', 'super'):
            styles.append(f'vertical-align: {value}')
            styles.append('font-size: smaller')
        elif name == 'font' and isinstance(value, str) and re.fullmatch(r'[\w ,\'"-]{1,200}', value):
            styles.append(f'font-family: {value}')
        elif name == 'size' and isinstance(value, str) and re.fullmatch(r'\d+(?:\.\d+)?(?:pt|px)', value):
            if not 1 <= float(value[:-2]) <= 200:
                raise ValueError(_('Font size must be between 1 and 200 pt/px.'))
            styles.append(f'font-size: {value}')
        elif name in ('color', 'background'):
            styles.append(f"{'color' if name == 'color' else 'background-color'}: {_color(value)}")
        else:
            raise ValueError(_('Unsupported text format: {value1}.', value1=name))
    if decorations:
        styles.append(f"text-decoration-line: {' '.join(decorations)}")
    return '; '.join(styles)


def render_delta(ops, *, line_height=None):
    """Accept only inserted text and supported inline styles, never client HTML.

    Quill always includes one final document newline; it is not cell content.
    Other newlines and all leading/trailing spaces belong to the user's text.
    """
    line_height = validate_line_height(line_height)
    if not isinstance(ops, list) or not 1 <= len(ops) <= 4096:
        raise ValueError(_('Invalid editor document.'))
    parts = []
    length = 0
    for op in ops:
        if not isinstance(op, dict) or set(op) - {'insert', 'attributes'}:
            raise ValueError(_('Invalid editor operation.'))
        text = op.get('insert')
        if not isinstance(text, str):
            raise ValueError(_('Only text can be inserted into a cell.'))
        try:
            text.encode('utf-8')
        except UnicodeError as error:
            raise ValueError(_('Cell text contains an invalid Unicode character.')) from error
        length += len(text)
        if length > 65536:
            raise ValueError(_('Cell text is too long.'))
        parts.append([text, _styles(op.get('attributes', {}))])
    # The final newline may be an operation of its own, or follow cell text.
    if not parts[-1][0].endswith('\n'):
        raise ValueError(_('The editor document must end with a newline.'))
    parts[-1][0] = parts[-1][0][:-1]
    plaintext = ''.join(text for text, _ in parts)
    if not plaintext:
        return '', ''
    html = []
    for text, style in parts:
        if not text:
            continue
        escaped = escape(text)
        html.append(f'<span style="{escape(style, quote=True)}">{escaped}</span>' if style else escaped)
    style = 'white-space: pre-wrap'
    if line_height is not None:
        style += f'; line-height: {line_height:g}'
    return f'<div style="{style}">' + ''.join(html) + '</div>', plaintext
