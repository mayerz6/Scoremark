"""
Column occupancy: how "dense" a dataset is -- for each column, the share of
rows holding a real value. Ported from the exploratory notebook's
column_occupancy_report(), with these changes:

  - Values are read as text (dtype=str, keep_default_na=False), so pandas'
    own NaN guessing can't decide what counts as missing, and nothing is
    converted on the way in.
  - "Missing" = empty/whitespace, or a null placeholder in any letter case
    (the notebook's "", "None", "null", plus "NaN", "N/A", "NA", "-") --
    the same set the Scoremark web app's occupancy chart uses, so the two
    tools agree on what "filled" means. Defined here rather than imported:
    this tool is kept free of imports from the web app's rules/ package.
  - The chart is saved into the dataset's reports/ folder (plt.show()
    needs a display -- see ValidationEngine.visualize()).
  - A file with no rows yields an empty result instead of dividing by zero.
"""

from __future__ import annotations

import os

import matplotlib.pyplot as plt
import pandas as pd

NULL_PLACEHOLDERS = {"", "none", "null", "nan", "n/a", "na", "-"}


def column_occupancy(file_path, exclude_columns=()) -> pd.DataFrame:
    """
    Returns a DataFrame indexed by column with "Filled" and "Occupancy %",
    sorted lowest occupancy first (as the notebook did).
    """
    df = pd.read_csv(file_path, dtype=str, keep_default_na=False)
    df = df[[c for c in df.columns if c not in set(exclude_columns)]]
    total_rows = len(df)

    rows = {}
    for column in df.columns:
        filled = int((~df[column].str.strip().str.lower().isin(NULL_PLACEHOLDERS)).sum())
        rows[column] = {
            "Filled": filled,
            "Occupancy %": round(filled / total_rows * 100, 2) if total_rows else 0.0,
        }

    result = pd.DataFrame.from_dict(rows, orient="index", columns=["Filled", "Occupancy %"])
    result.attrs["total_rows"] = total_rows
    return result.sort_values(by="Occupancy %", kind="stable")


def visualize_occupancy(occupancy: pd.DataFrame, reports_dir, filename="occupancy.png", title="Dataset"):
    """
    Horizontal bar chart, densest column at the top. Returns the chart's
    path, or None if there was nothing to chart.
    """
    if occupancy.empty or not occupancy.attrs.get("total_rows"):
        print(f"No rows in {title} -- no occupancy chart.")
        return None

    os.makedirs(reports_dir, exist_ok=True)
    output_path = os.path.join(reports_dir, filename)

    plt.figure(figsize=(12, max(4, 0.45 * len(occupancy) + 1.5)))
    bars = plt.barh(occupancy.index, occupancy["Occupancy %"])
    for bar, pct in zip(bars, occupancy["Occupancy %"]):
        plt.text(min(pct + 1, 92), bar.get_y() + bar.get_height() / 2, f"{pct:.1f}%", va="center")
    plt.xlabel("Field Occupancy (%)")
    plt.title(f"{title} | Column Occupancy Analysis ({occupancy.attrs['total_rows']:,} rows)")
    plt.xlim(0, 100)
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()
    print(f"Occupancy chart saved to {output_path}")
    return output_path


def occupancy_report(file_path, reports_dir, filename="occupancy.png", title="Dataset", exclude_columns=()):
    """column_occupancy() + visualize_occupancy() in one call. Returns
    (occupancy_dict, chart_path) -- the dict is JSON-ready for provenance."""
    occupancy = column_occupancy(file_path, exclude_columns=exclude_columns)
    chart = visualize_occupancy(occupancy, reports_dir, filename=filename, title=title)
    return occupancy["Occupancy %"].to_dict(), chart
