"""Spreadsheet reading + analysis. Files are parsed as data, never executed."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from worker.tools.path_utils import PathPolicyError, validate_path

MAX_SAMPLE_ROWS = 5
MAX_MATCHED_ROWS = 50

COMPARATORS = {
    ">=": lambda s, v: s >= v,
    "<=": lambda s, v: s <= v,
    ">": lambda s, v: s > v,
    "<": lambda s, v: s < v,
    "==": lambda s, v: s == v,
}

# "greater than 2", "exceeds 4400", "above 90", "below 10", "under 5"
_THRESHOLD_RE = re.compile(
    r"\b(?:(greater than|more than|above|over|exceed(?:s|ing)?|higher than)|"
    r"(less than|below|under|lower than))\s+(-?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


class ReadSpreadsheetInput(BaseModel):
    file_path: str = Field(..., description="Workspace-relative path, e.g. inputs/readings.xlsx")
    run_id: str = Field(..., description="Run ID")
    sheet_name: str | None = Field(None, description="Sheet to read; defaults to the first")


class AnalyzeSpreadsheetInput(BaseModel):
    file_path: str = Field(..., description="Workspace-relative path to the spreadsheet")
    query: str = Field(..., description="Natural-language question about the data")
    run_id: str = Field(..., description="Run ID")
    sheet_name: str | None = Field(None, description="Sheet to analyse; defaults to the first")


def _load(resolved: Path, sheet_name: str | None):
    import pandas as pd

    if resolved.suffix.lower() == ".csv":
        return pd.read_csv(resolved), ["CSV"], "CSV"

    xl = pd.ExcelFile(resolved)
    sheets = list(xl.sheet_names)
    target = sheet_name if sheet_name in sheets else sheets[0]
    return xl.parse(target), sheets, target


def _jsonable(value: Any) -> Any:
    import pandas as pd

    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    return value


def _records(df, limit: int) -> List[Dict[str, Any]]:
    return [
        {str(k): _jsonable(v) for k, v in row.items()}
        for row in df.head(limit).to_dict(orient="records")
    ]


@tool("read_spreadsheet", args_schema=ReadSpreadsheetInput)
def read_spreadsheet(file_path: str, run_id: str, sheet_name: str | None = None) -> Dict[str, Any]:
    """Inspect a local XLSX/CSV: sheet names, columns, dtypes, row count, sample rows."""
    try:
        resolved = validate_path(file_path, run_id)
    except PathPolicyError as e:
        return {"status": "rejected", "error": str(e)}

    if not resolved.exists():
        return {"status": "error", "error": f"Spreadsheet not found: {file_path}"}

    try:
        df, sheets, active = _load(resolved, sheet_name)
    except Exception as e:
        return {"status": "error", "error": f"Could not parse spreadsheet: {e}"}

    return {
        "status": "success",
        "file_path": file_path,
        "sheet_names": sheets,
        "active_sheet": active,
        "columns": [str(c) for c in df.columns],
        "dtypes": {str(c): str(t) for c, t in df.dtypes.items()},
        "row_count": int(len(df)),
        "numeric_columns": [str(c) for c in df.select_dtypes(include="number").columns],
        "sample_rows": _records(df, MAX_SAMPLE_ROWS),
    }


# Words people actually use for a quantity, mapped to the token a column name
# uses. "running above 85 degrees C" has to reach a column called `temperature_c`.
_COLUMN_SYNONYMS = {
    "temperature": ("temp", "degree", "degrees", "celsius", "hot", "heat", "deg"),
    "vibration": ("vibration", "vibrating", "shaking"),
    "downtime": ("downtime", "stopped", "idle", "outage"),
    "units": ("units", "output", "produced", "production", "throughput"),
    "pressure": ("pressure", "psi", "bar"),
    "loss": ("loss", "wear", "thinning"),
}

_COLUMN_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _pick_column(df, query: str, candidates: list[str] | None = None) -> str | None:
    """Find the column a question is about.

    Tried in order: the exact column name, then token overlap between the column
    name and the question (so `temperature_c` matches both "temperature" and
    "degrees C"), then an explicit "column D" reference.

    `candidates` restricts the search — when the question carries a numeric
    threshold, only numeric columns can satisfy it, and without that restriction
    "Which machines are above 85 C" picks the `machine_id` text column.
    """
    q = query.lower()
    columns = [str(c) for c in (candidates if candidates is not None else df.columns)]
    if not columns:
        return None

    # 1. Exact name. Longest wins, so `variance_pct` beats `variance`.
    exact = sorted((c for c in columns if c.lower() in q), key=len, reverse=True)
    if exact:
        return exact[0]

    # 2. Token overlap, plus synonyms for the words people actually type.
    best, best_score = None, 0
    for column in columns:
        tokens = [t for t in _COLUMN_TOKEN_RE.findall(column.lower()) if len(t) > 2]
        if not tokens:
            continue
        score = sum(1 for token in tokens if token in q)
        for canonical, synonyms in _COLUMN_SYNONYMS.items():
            if any(canonical in token for token in tokens) and any(s in q for s in synonyms):
                # A unit word ("degrees C") is stronger evidence than an
                # incidental noun that happens to appear in a column name.
                score += 2
        if score > best_score:
            best, best_score = column, score
    if best is not None:
        return best

    # 3. Spreadsheet-style reference: "column D" always counts from the sheet's
    # first column, never from the filtered candidate list.
    match = re.search(r"\bcolumn\s+([a-z])\b", q)
    if match:
        all_columns = [str(c) for c in df.columns]
        index = ord(match.group(1)) - ord("a")
        if 0 <= index < len(all_columns):
            return all_columns[index]

    return None


@tool("analyze_spreadsheet", args_schema=AnalyzeSpreadsheetInput)
def analyze_spreadsheet(
    file_path: str, query: str, run_id: str, sheet_name: str | None = None
) -> Dict[str, Any]:
    """Answer a question about a local spreadsheet — threshold breaches, aggregates
    and per-column statistics — returning the actual matching rows as evidence."""
    try:
        resolved = validate_path(file_path, run_id)
    except PathPolicyError as e:
        return {"status": "rejected", "error": str(e)}

    if not resolved.exists():
        return {"status": "error", "error": f"Spreadsheet not found: {file_path}"}

    try:
        import pandas as pd

        df, sheets, active = _load(resolved, sheet_name)
    except Exception as e:
        return {"status": "error", "error": f"Could not parse spreadsheet: {e}"}

    numeric_cols = [str(c) for c in df.select_dtypes(include="number").columns]
    stats = {
        col: {
            "min": _jsonable(df[col].min()),
            "max": _jsonable(df[col].max()),
            "mean": round(float(df[col].mean()), 4) if len(df) else None,
            "count": int(df[col].count()),
        }
        for col in numeric_cols
    }

    answer: Dict[str, Any] = {
        "status": "success",
        "file_path": file_path,
        "active_sheet": active,
        "sheet_names": sheets,
        "query": query,
        "row_count": int(len(df)),
        "numeric_columns": numeric_cols,
        "column_statistics": stats,
        "matched_rows": [],
        "match_count": 0,
    }

    threshold_match = _THRESHOLD_RE.search(query)
    # A threshold can only apply to a numeric column, so don't let a text column
    # win the match and silently drop the filter.
    target_col = _pick_column(df, query, numeric_cols if threshold_match else None)

    if target_col and threshold_match and target_col in numeric_cols:
        above, below, raw_value = threshold_match.groups()
        value = float(raw_value)
        op = ">" if above else "<"
        # "exceeds 2mm" reads naturally as strictly greater; keep it explicit.
        mask = COMPARATORS[op](df[target_col], value)
        matched = df[mask]
        answer.update({
            "interpretation": f"rows where `{target_col}` {op} {value}",
            "filter": {"column": target_col, "operator": op, "value": value},
            "match_count": int(len(matched)),
            "matched_rows": _records(matched, MAX_MATCHED_ROWS),
            "truncated": bool(len(matched) > MAX_MATCHED_ROWS),
        })
    elif target_col and target_col in numeric_cols:
        answer.update({
            "interpretation": f"summary statistics for `{target_col}`",
            "focus_column": target_col,
            "focus_statistics": stats.get(target_col),
            "top_rows_by_column": _records(
                df.sort_values(target_col, ascending=False), MAX_SAMPLE_ROWS
            ),
        })
    else:
        answer.update({
            "interpretation": "no explicit column/threshold detected in the question; "
                              "returning whole-sheet statistics and a sample",
            "sample_rows": _records(df, MAX_SAMPLE_ROWS),
        })

    return answer
