import os
import re
from pathlib import Path

import pandas as pd
import numpy as np

# ---- Config
INPUT = "Data2.csv" # Updated to match your uploaded filename
dataset_name = Path(INPUT).stem
OUT_DIR = Path(dataset_name)
OUT_DIR.mkdir(exist_ok=True)

# ---- Helper functions (based on your provided code) ----
def clean_notion_link(val):
    if pd.isna(val):
        return val
    val = str(val)
    # Remove the URLs enclosed in parentheses
    return re.sub(r'\s*\(https://.*?\)', '', val).strip()

def extract_pnl(val):
    """Parse strings like '-50,00 $US' or '282,00 $US' into float (US decimal point)."""
    if pd.isna(val):
        return np.nan
    s = str(val).replace('$US', '').replace('\xa0', '').strip()
    # Keep minus sign if present, convert comma decimals to dot
    is_neg = s.startswith('-')
    s = s.replace('-', '')
    s = s.replace(',', '.')
    # remove any characters except digits and dot and minus
    s = re.sub(r'[^\d\.]', '', s)
    if s == '':
        return np.nan
    try:
        v = float(s)
        return -v if is_neg else v
    except Exception:
        return np.nan

def parse_number_generic(val):
    """
    Generic number parser for columns that may include percent signs, commas, currency text.
    Returns float or NaN.
    """
    if pd.isna(val):
        return np.nan
    s = str(val).strip()
    s = s.replace('\xa0', '').replace('$US', '').replace('US$', '')
    # capture negative in parentheses like (50) -> -50
    if re.match(r'^\(.*\)$', s):
        s = '-' + s.strip('()')
    is_percent = '%' in s
    s = s.replace('%', '')
    is_neg = s.startswith('-')
    s = s.lstrip('-+')
    # if both comma and dot appear assume comma is thousand separator
    if ',' in s and '.' in s:
        s = s.replace(',', '')
    else:
        s = s.replace(',', '.')
    s = re.sub(r'[^0-9\.]', '', s)
    if s == '':
        return np.nan
    try:
        num = float(s)
        if is_percent:
            num = num / 100.0
        return -num if is_neg else num
    except Exception:
        return np.nan

# ---- 1. Load data ----
df = pd.read_csv(INPUT)

# ---- 2. Clean text columns that may contain Notion links ----
cols_to_clean = [
    'Account', 'Symbol', 'Model', 'News Impact', 'Bias', 'Market Conditions', 'Type of Trade', 'Session',
    'Entry TimeFrame', 'Confluences', 'Key Levels', 'Entry Signal', 'Order Type',
    'SL Management', 'TP Management', 'Setup Grade', 'Outcome'
]
for col in cols_to_clean:
    if col in df.columns:
        df[col] = df[col].apply(clean_notion_link)

# ---- 3. Clean financial columns: Net PnL, Gross PnL (use extract_pnl) ----
for pnl_col in ('Net PnL', 'Gross PnL'):
    if pnl_col in df.columns:
        df[pnl_col] = df[pnl_col].apply(extract_pnl)

# ---- 4. Parse dates if present ----
if 'Entry / Exit Date' in df.columns:
    df['Entry / Exit Date'] = pd.to_datetime(df['Entry / Exit Date'], errors='coerce')
    df['Month'] = df['Entry / Exit Date'].dt.to_period('M').astype(str)
    df['Day'] = df['Entry / Exit Date'].dt.date
    df['Day Name'] = df['Entry / Exit Date'].dt.day_name()

# ---- 5. Detect numeric columns (only keep those intended for math) ----
numeric_candidates = []
numeric_series_map = {}

for col in df.columns:
    # skip obvious textual/date columns
    if col in cols_to_clean or 'Date' in col or col in ('Month', 'Day', 'Day Name', 'Entry / Exit Date'):
        continue
    if df[col].dtype == object:
        cleaned = df[col].apply(parse_number_generic)
    else:
        cleaned = pd.to_numeric(df[col], errors='coerce')
    non_null = int(cleaned.notna().sum())
    # Heuristic: at least 2 numeric values or >=30% of rows numeric
    if non_null >= 2 and (non_null >= 0.3 * len(df) or non_null >= 2):
        numeric_candidates.append(col)
        numeric_series_map[col] = cleaned

# Ensure Net PnL and Gross PnL included
for special in ('Net PnL', 'Gross PnL'):
    if special in df.columns and special not in numeric_candidates:
        numeric_candidates.append(special)
        numeric_series_map[special] = df[special].astype(float)

# Create numeric columns in dataframe with _num suffix to keep original intact
for col, ser in numeric_series_map.items():
    df[col + "_num"] = ser.astype(float)

numeric_cols = [c + "_num" for c in numeric_series_map.keys()]

# ---- 6. Compute simple statistics for numeric columns ----
if not numeric_cols:
    print("No numeric/calculation-related columns detected. Exiting.")
else:
    stats = df[numeric_cols].describe().T
    stats['sum'] = df[numeric_cols].sum()
    stats['missing'] = df[numeric_cols].isna().sum()
    stats.index = [idx.replace('_num', '') for idx in stats.index]

    # Round for console readability
    stats_display = stats.copy()
    for c in stats_display.columns:
        if stats_display[c].dtype.kind in 'f':
            stats_display[c] = stats_display[c].round(4)

    print("\n==== Numeric columns detected and their statistics ====\n")
    print(stats_display.to_string(), "\n")

    # ---- 7. Trading KPIs if Net PnL is available ----
    if 'Net PnL_num' in df.columns:
        net = df['Net PnL_num'].fillna(0.0)
        total_pnl = net.sum()
        total_trades = len(df)
        wins = int((net > 0).sum())
        losses = int((net < 0).sum())
        breakeven = int((net == 0).sum())
        win_rate = wins / total_trades if total_trades > 0 else 0.0
        avg_win = float(net[net > 0].mean()) if wins > 0 else 0.0
        avg_loss = float(net[net < 0].mean()) if losses > 0 else 0.0  # negative
        sum_wins = float(net[net > 0].sum()) if wins > 0 else 0.0
        sum_losses = float(net[net < 0].sum()) if losses > 0 else 0.0  # negative
        profit_factor = (sum_wins / abs(sum_losses)) if abs(sum_losses) > 0 else np.inf
        expectancy = win_rate * avg_win + (1 - win_rate) * avg_loss

        print("==== Trading KPIs (from Net PnL) ====\n")
        print(f"Total Trades: {total_trades}")
        print(f"Total Net PnL: ${total_pnl:.2f}")
        print(f"Wins: {wins}, Losses: {losses}, Breakeven: {breakeven}")
        print(f"Win Rate: {win_rate * 100:.2f}%")
        print(f"Average Win: ${avg_win:.2f}")
        print(f"Average Loss: ${avg_loss:.2f}")
        print(f"Sum Wins: ${sum_wins:.2f}, Sum Losses: ${sum_losses:.2f}")
        print(f"Profit Factor: {profit_factor if profit_factor != np.inf else 'inf'}")
        print(f"Expectancy per trade: ${expectancy:.4f}\n")

    # ---- 8. Grouped summaries with percentages ----
    def make_group_summary(key):
        grp = df.groupby(key)['Net PnL_num'].agg(['count', 'sum', 'mean']).rename(columns={
            'count': 'trades',
            'sum': 'sum_net_pnl',
            'mean': 'avg_net_pnl'
        })
        total_net = df['Net PnL_num'].sum()
        grp['pct_of_total_net_pnl'] = (grp['sum_net_pnl'] / total_net * 100).replace([np.inf, -np.inf], np.nan)
        grp['pct_of_trades'] = grp['trades'] / len(df) * 100
        # cumulative percent contribution sorted by sum_net_pnl desc
        grp = grp.sort_values('sum_net_pnl', ascending=False)
        grp['cumulative_pct_net_pnl'] = grp['pct_of_total_net_pnl'].cumsum()
        # fill NA pct_of_total_net_pnl with 0 if total net = 0
        if total_net == 0:
            grp['pct_of_total_net_pnl'] = 0.0
            grp['cumulative_pct_net_pnl'] = grp['pct_of_total_net_pnl'].cumsum()
        # round for display
        grp_display = grp.round(4)
        return grp, grp_display

    group_keys = []
    # ADDED 'Setup Grade' and 'Bias' here
    for k in ('Symbol', 'Month', 'Day Name', 'Day', 'Setup Grade', 'Bias'):
        if k in df.columns:
            group_keys.append(k)

    for key in group_keys:
        grp, grp_display = make_group_summary(key)
        print(f"==== Net PnL by {key} (with % of total net PnL and % of trades) ====")
        # Print top rows for console readability
        print(grp_display.to_string(), "\n")
        # Save to CSV
        grp.to_csv(OUT_DIR / f"{dataset_name}_groupby_{key.replace(' ', '_')}_with_pct.csv")

    # ---- 9. Additionally: per-day contribution (for each calendar day) ----
    if 'Day' in df.columns:
        daily = df.groupby('Day')['Net PnL_num'].agg(['count', 'sum', 'mean']).rename(columns={
            'count': 'trades',
            'sum': 'sum_net_pnl',
            'mean': 'avg_net_pnl'
        }).sort_index()
        total_net = df['Net PnL_num'].sum()
        daily['pct_of_total_net_pnl'] = (daily['sum_net_pnl'] / total_net * 100).replace([np.inf, -np.inf], np.nan)
        daily['pct_of_trades'] = daily['trades'] / len(df) * 100
        if total_net == 0:
            daily['pct_of_total_net_pnl'] = 0.0
        daily_display = daily.round(4)
        print("==== Per-calendar-day Net PnL summary ====")
        print(daily_display.to_string(), "\n")
        daily.to_csv(OUT_DIR / f"{dataset_name}_per_day_summary_with_pct.csv")

    # ---- 10. Save cleaned data and numeric summary to OUT_DIR (CSV) ----
    cleaned_path = OUT_DIR / f"{dataset_name}_cleaned.csv"
    numeric_summary_path = OUT_DIR / f"{dataset_name}_numeric_summary.csv"

    df.to_csv(cleaned_path, index=False)
    stats.to_csv(numeric_summary_path)

    print(f"Saved cleaned data to: {cleaned_path}")
    print(f"Saved numeric summary to: {numeric_summary_path}")
    print(f"Saved groupby files (with percentage columns) to folder: {OUT_DIR}")