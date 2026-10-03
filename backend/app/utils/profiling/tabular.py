import pandas as pd
from typing import Dict, Any
import json

def profile_tabular(file_path: str) -> Dict[str, Any]:
    """
    Profile a CSV or XLSX file.
    Returns a dict with basic statistics.
    """
    try:
        if file_path.lower().endswith('.csv'):
            df = pd.read_csv(file_path)
        elif file_path.lower().endswith('.xlsx'):
            df = pd.read_excel(file_path)
        else:
            raise ValueError("Unsupported tabular format")
    except Exception as e:
        return {"error": f"Failed to read file: {str(e)}"}

    profile = {
        "row_count": int(len(df)),
        "column_count": int(len(df.columns)),
        "columns": [str(col) for col in df.columns],
        # Optional: basic dtypes
        "dtypes": {str(col): str(dtype) for col, dtype in df.dtypes.items()}
    }
    return profile