import hashlib
import pandas as pd
import numpy as np

def _normalize_cell(value):
    """Convert a cell value to a normalized string for hashing."""
    if pd.isna(value) or value is None:
        return "__null__"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, np.integer)):
        return str(value)
    if isinstance(value, (float, np.floating)):
        # Strip unnecessary trailing zeros and decimal point
        s = str(value)
        if '.' in s:
            s = s.rstrip('0').rstrip('.')
        return s
    # For strings and other types, strip surrounding whitespace
    return str(value).strip()

def hash_row(row: pd.Series) -> str:
    """
    Compute a deterministic SHA-256 hash for a pandas Series representing a row.
    Column order is preserved as in the Series index.
    """
    parts = []
    for col in row.index:
        normalized = _normalize_cell(row[col])
        parts.append(f"{col}:{normalized}")
    # Join with a delimiter that does not appear in normalized cells
    serialized = "|".join(parts)
    return hashlib.sha256(serialized.encode('utf-8')).hexdigest()