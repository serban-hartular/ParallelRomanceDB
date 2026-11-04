"""Extract worksheets, replace text, and flatten etymon tables."""

from collections import Counter
from colorsys import hls_to_rgb, rgb_to_hls
from html import escape
import json
from os import PathLike
from pathlib import Path
import re
from xml.etree import ElementTree

import pandas as pd
from openpyxl import load_workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.styles.colors import COLOR_INDEX
from openpyxl.utils.cell import range_boundaries

from text_normalization import remove_diacritics


def extract_sheet(
    original_path: str | PathLike[str],
    sheet_name: str,
    new_path: str | PathLike[str],
) -> Path:
    """Save the named sheet as a new .xlsx workbook and return its path.

    Keeps cell values, formulas, and formatting supported by openpyxl.
    References to other sheets are not rewritten or copied. A hidden sheet
    is made visible so it can be the only sheet in the new workbook.

    Raises ValueError if the sheet is missing or the paths identify the
    same file. Other file and workbook errors propagate to the caller.
    """
    source = Path(original_path)
    destination = Path(new_path)
    if source.resolve() == destination.resolve() or (
        source.exists() and destination.exists() and source.samefile(destination)
    ):
        raise ValueError("The output path must differ from the original file.")

    workbook = load_workbook(source)
    try:
        if sheet_name not in {sheet.title for sheet in workbook.worksheets}:
            raise ValueError(f"Worksheet {sheet_name!r} does not exist.")

        for name in list(workbook.sheetnames):
            if name != sheet_name:
                workbook.remove(workbook[name])

        workbook[sheet_name].sheet_state = "visible"
        workbook.active = 0
        workbook.save(destination)
    finally:
        workbook.close()

    return destination


def find_replace_excel(
    excel_path: str | PathLike[str],
    replace_dict: dict[str, str],
    sheet_name: str | None = None,
    output_file: str | PathLike[str] | bool | None = None,
    cell_range: str | None = None,
) -> Path:
    """Apply all find/replace pairs in a sheet and save the workbook once.

    Matching is literal and case-sensitive, including within formula text.
    Dictionary keys are search strings and values are their replacements.
    Pairs are applied in dictionary insertion order, so later pairs can
    replace text produced by earlier pairs. An empty dictionary saves an
    unchanged copy (or rewrites the original when output_file=False).
    Numeric, boolean, and empty cells are left unchanged. Other sheets and
    formatting supported by openpyxl are preserved.

    Defaults to the first worksheet and its entire used area. Set cell_range
    to an inclusive A1-style rectangle such as "A1:D20" (or a single cell).
    The default output is <original_stem>_replaced.<original_extension> beside
    the source. Pass output_file=False to overwrite the original. Returns
    the saved path. Macro-enabled .xlsm workbooks retain their VBA archive.
    """
    if not isinstance(replace_dict, dict):
        raise TypeError("replace_dict must be a dictionary of string pairs.")
    for search, replacement in replace_dict.items():
        if not isinstance(search, str) or not isinstance(replacement, str):
            raise TypeError("Search and replacement must be strings.")
        if not search:
            raise ValueError("Search strings must not be empty.")
    if output_file is True:
        raise TypeError("output_file must be a path, None, or False.")

    source = Path(excel_path)
    if output_file is False:
        destination = source
    elif output_file is None:
        destination = source.with_name(f"{source.stem}_replaced{source.suffix}")
    else:
        destination = Path(output_file)

    if output_file is not False and (
        source.resolve() == destination.resolve()
        or (source.exists() and destination.exists() and source.samefile(destination))
    ):
        raise ValueError("Pass output_file=False to overwrite the original file.")

    bounds = None
    if cell_range is not None:
        bounds = range_boundaries(cell_range)
        min_col, min_row, max_col, max_row = bounds
        if (
            any(value is None for value in bounds)
            or not (1 <= min_col <= max_col <= 16384)
            or not (1 <= min_row <= max_row <= 1048576)
        ):
            raise ValueError("cell_range must be a cell or rectangle such as A1:D20.")

    workbook = load_workbook(source, keep_vba=source.suffix.lower() == ".xlsm")
    try:
        if sheet_name is None:
            sheet = workbook.worksheets[0]
        else:
            if sheet_name not in {sheet.title for sheet in workbook.worksheets}:
                raise ValueError(f"Worksheet {sheet_name!r} does not exist.")
            sheet = workbook[sheet_name]

        if bounds is None:
            rows = sheet.iter_rows()
        else:
            # Avoid creating blank cells beyond the sheet's used area.
            rows = sheet.iter_rows(
                min_col=min_col,
                min_row=min_row,
                max_col=min(max_col, sheet.max_column),
                max_row=min(max_row, sheet.max_row),
            )

        for row in rows:
            for cell in row:
                if isinstance(cell.value, str):
                    value = cell.value
                    for search, replacement in replace_dict.items():
                        value = value.replace(search, replacement)
                    if value == cell.value:
                        continue
                    data_type = cell.data_type
                    cell.value = value
                    # Text starting with '=' must remain text, not a formula.
                    cell.data_type = data_type

        workbook.save(destination)
    finally:
        workbook.close()

    return destination


def _color_resolver(workbook):
    """Resolve Excel RGB, indexed, and theme colors to CSS hex colors."""
    theme = {}
    if workbook.loaded_theme:
        scheme = ElementTree.fromstring(workbook.loaded_theme).find('.//{*}clrScheme')
        if scheme is not None:
            for entry in scheme:
                color = next(iter(entry), None)
                if color is not None:
                    theme[entry.tag.rsplit('}', 1)[-1]] = (
                        color.get('lastClr') or color.get('val')
                    )
    theme_order = (
        'lt1', 'dk1', 'lt2', 'dk2', 'accent1', 'accent2',
        'accent3', 'accent4', 'accent5', 'accent6', 'hlink', 'folHlink',
    )
    palette = workbook._colors or COLOR_INDEX

    def resolve(color):
        if color is None:
            return None
        rgb = None
        if color.type == 'rgb':
            rgb = color.rgb
        elif color.type == 'theme' and 0 <= color.theme < len(theme_order):
            rgb = theme.get(theme_order[color.theme])
        elif color.type == 'indexed' and 0 <= color.indexed < len(palette):
            rgb = palette[color.indexed]
        if rgb is None or not re.fullmatch(r'(?:[0-9a-fA-F]{2})?[0-9a-fA-F]{6}', rgb):
            return None
        rgb = rgb[-6:]
        if color.tint:
            channels = [int(rgb[i:i + 2], 16) / 255 for i in (0, 2, 4)]
            hue, lightness, saturation = rgb_to_hls(*channels)
            tint = color.tint
            lightness = lightness * (1 + tint) if tint < 0 else lightness * (1 - tint) + tint
            rgb = ''.join(f'{round(channel * 255):02X}' for channel in hls_to_rgb(hue, lightness, saturation))
        return f'#{rgb.upper()}'

    return resolve


def _font_to_css(font, color_to_css, fallback=None) -> str:
    """Encode character formatting, including explicit rich-text resets."""
    def value(name):
        result = getattr(font, name)
        if result is None and fallback is not None:
            result = getattr(fallback, name)
        return result

    styles = [
        f"font-weight: {'bold' if value('b') else 'normal'}",
        f"font-style: {'italic' if value('i') else 'normal'}",
    ]
    family = font.rFont if isinstance(font, InlineFont) else font.name
    if family is None and fallback is not None:
        family = fallback.name
    if family:
        # Some imported font names already contain a CSS-style fallback list.
        if not re.search(r'[;{}<>]', family):
            styles.append(f'font-family: {family}')
        else:
            styles.append(f'font-family: {json.dumps(family)}')
    size = value('sz')
    if size is not None:
        styles.append(f'font-size: {size:g}pt')
    color = color_to_css(value('color'))
    if color:
        styles.append(f'color: {color}')
    decorations = []
    underline = value('u')
    if underline and underline != 'none':
        decorations.append('underline')
    if value('strike'):
        decorations.append('line-through')
    styles.append(f"text-decoration-line: {' '.join(decorations) or 'none'}")
    if underline in ('double', 'doubleAccounting'):
        styles.append('text-decoration-style: double')
    vertical = value('vertAlign')
    alignment = {'superscript': 'super', 'subscript': 'sub'}.get(vertical, 'baseline')
    styles.append(f'vertical-align: {alignment}')
    return '; '.join(styles)


def _cell_to_html(cell, color_to_css) -> str:
    """Preserve text and its whitespace using escaped HTML and inline CSS."""
    value = cell.value
    base_style = _font_to_css(cell.font, color_to_css)
    style = 'white-space: pre-wrap'
    if isinstance(value, CellRichText):
        parts = []
        for part in value:
            if isinstance(part, TextBlock):
                run_style = _font_to_css(part.font, color_to_css, fallback=cell.font)
                parts.append(f'<span style="{escape(run_style, quote=True)}">{escape(part.text)}</span>')
            else:
                parts.append(f'<span style="{escape(base_style, quote=True)}">{escape(part)}</span>')
        text = ''.join(parts)
    else:
        text = escape(str(value))
        style += '; ' + base_style
    return f'<div style="{escape(style, quote=True)}">{text}</div>'


def excel_to_dataframe(
    excel_path: str | PathLike[str],
    sheet_name: str | None = None,
) -> pd.DataFrame:
    """Flatten an etymon worksheet into one record per nonempty data cell.

    Row 1 supplies column names; column A supplies labels. Each label
    beginning with "ETIMON/" (also allowing spaces before the slash) starts
    a new, 1-based etymon. Blank labels inherit the preceding label. Labels
    and column names retain their original wording and whitespace.

    label_number counts nonempty data rows for each exact label within an
    etymon, starting at 1, and is shared by every cell on that row. Entirely
    blank rows do not increment it. Includes etymon rows and all named
    columns, including observations and conclusions. Whitespace-only cells
    are skipped. Populated cells without a column heading or preceding
    etymon raise ValueError instead of being silently discarded.

    content contains escaped HTML with font formatting (including rich-text
    runs, colors, size, bold, italics, underlining, strike, and sub/superscript)
    and preserved whitespace. Cell borders, fills, and worksheet layout are
    not represented. plaintext_content is str(cell.value).strip(), retaining
    internal whitespace. nodiacritics_plaintext is its accent-free search
    equivalent, preserving case and internal whitespace. Formulas are
    retained as expressions, not evaluated.
    The source workbook is never modified. Defaults to the first worksheet.
    Requires openpyxl >= 3.1 for rich-text loading.
    """
    columns = [
        'etimon_number', 'column', 'label', 'label_number', 'content',
        'plaintext_content', 'nodiacritics_plaintext',
    ]
    workbook = load_workbook(excel_path, rich_text=True)
    try:
        if sheet_name is None:
            sheet = workbook.worksheets[0]
        else:
            if sheet_name not in {sheet.title for sheet in workbook.worksheets}:
                raise ValueError(f'Worksheet {sheet_name!r} does not exist.')
            sheet = workbook[sheet_name]

        headers = {
            cell.column: str(cell.value)
            for cell in sheet[1][1:]
            if cell.value is not None and str(cell.value).strip()
        }
        color_to_css = _color_resolver(workbook)
        records = []
        etimon_number = 0
        label = None
        counts = Counter()
        for row in sheet.iter_rows(min_row=2):
            row_label = row[0].value
            if row_label is not None and str(row_label).strip():
                label = str(row_label)
                if re.match(r'^\s*ETIMON\s*/', label, flags=re.IGNORECASE):
                    etimon_number += 1
                    counts.clear()

            populated = [cell for cell in row[1:] if cell.value is not None and str(cell.value).strip()]
            if not populated:
                continue
            if not etimon_number:
                raise ValueError(f'Row {row[0].row} has content before the first ETIMON/ label.')
            counts[label] += 1
            for cell in populated:
                if cell.column not in headers:
                    raise ValueError(f'Cell {cell.coordinate} has content but no column heading.')
                plaintext = str(cell.value).strip()
                records.append({
                    'etimon_number': etimon_number,
                    'column': headers[cell.column],
                    'label': label,
                    'label_number': counts[label],
                    'content': _cell_to_html(cell, color_to_css),
                    'plaintext_content': plaintext,
                    'nodiacritics_plaintext': remove_diacritics(plaintext),
                })

        return pd.DataFrame.from_records(records, columns=columns)
    finally:
        workbook.close()
