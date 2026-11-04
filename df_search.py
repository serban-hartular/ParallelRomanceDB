"""Search and retrieve etymons from an excel_to_dataframe result."""

import pandas as pd

from text_normalization import remove_diacritics


LABEL_ORDER = (
    'ETIMON/ CORESPONDENTE ROMANICE',
    'SENSURI DE BAZĂ',
    'EXTENSII SEMANTICE (METAFORIZĂRI,  METONIMII)',
    'SENSURI SPECIALIZATE',
)

COLUMN_ORDER = (
    'LIMBA FRANCEZĂ',
    'LIMBA ROMÂNĂ',
    'LIMBA ITALIANĂ',
    'LIMBA SPANIOLĂ',
    'LIMBA PORTUGHEZĂ',
    'LIMBA CATALANĂ',
    'OBSERVAȚII',
    'CONCLUZII',
)


def search_dataframe(
    df: pd.DataFrame,
    text: str,
    column: str | None = None,
    label: str | None = None,
    *,
    case_sensitive: bool = True,
) -> list[int]:
    """Return matching etimon numbers, unique and sorted in ascending order.

    Search for a literal substring, ignoring diacritics in both the query
    and content. Uses nodiacritics_plaintext when present, otherwise derives
    it from plaintext_content without modifying df. Matching is case-sensitive
    by default; set case_sensitive=False to ignore case as well.
    Optional column and label filters match their exact values and both
    must match when supplied. Missing plaintext values do not match.
    An empty search string matches every nonmissing plaintext value.
    """
    if not isinstance(text, str):
        raise TypeError('text must be a string.')

    if 'nodiacritics_plaintext' in df.columns:
        searchable = df['nodiacritics_plaintext']
    else:
        searchable = df['plaintext_content'].map(remove_diacritics, na_action='ignore')

    matches = searchable.str.contains(
        remove_diacritics(text), case=case_sensitive, regex=False, na=False,
    )
    if column is not None:
        matches &= df['column'].eq(column)
    if label is not None:
        matches &= df['label'].eq(label)

    return sorted(df.loc[matches, 'etimon_number'].unique().tolist())


def get_etimon(
    df: pd.DataFrame,
    etimon_number: int,
    plaintext: bool = False,
) -> pd.DataFrame:
    """Reconstruct an etymon as a table suitable for display on a web page.

    The first two columns are label and label_number. They identify each
    row, ordered by LABEL_ORDER, then by ascending label_number. Other
    labels follow alphabetically. Only observed label/number pairs appear.

    The remaining columns follow COLUMN_ORDER, including columns with no
    data. Additional columns present in this etymon follow alphabetically.
    Cells contain content (HTML) by default, or plaintext_content when
    plaintext=True. Missing cells are empty strings. Original labels and
    content are preserved, and the input DataFrame is not modified.

    If the etymon is absent, returns an empty table with the standard
    columns. Raises ValueError for duplicate label/label_number/column
    entries, since multiple values cannot occupy the same table cell.
    """
    rows = df.loc[df['etimon_number'].eq(etimon_number)]
    if rows.empty:
        return pd.DataFrame(columns=['label', 'label_number', *COLUMN_ORDER])

    keys = ['label', 'label_number', 'column']
    if rows.duplicated(keys).any():
        raise ValueError(
            'Each label/label_number/column combination must be unique within an etymon.'
        )

    extra_columns = sorted(set(rows['column']) - set(COLUMN_ORDER))
    content_column = 'plaintext_content' if plaintext else 'content'
    table = (
        rows.pivot(
            index=['label', 'label_number'], columns='column', values=content_column,
        )
        .reindex(columns=[*COLUMN_ORDER, *extra_columns])
        .astype(object)
        .fillna('')
        .reset_index()
    )
    table.columns.name = None
    priorities = {label: index for index, label in enumerate(LABEL_ORDER)}

    def sort_key(values):
        if values.name == 'label':
            return values.map(lambda label: (priorities.get(label, len(LABEL_ORDER)), label))
        return values

    return table.sort_values(
        ['label', 'label_number'], key=sort_key, kind='stable',
    ).reset_index(drop=True)
