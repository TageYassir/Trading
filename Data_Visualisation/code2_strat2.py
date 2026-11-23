import os
import re
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
import sys

import pandas as pd
import numpy as np


# ---- Helper functions for numeric extraction ----
def clean_numeric_string(s):
    """
    Clean a string from common formatting that would hinder numeric conversion:
    - Remove Notion links (anything like (https://...))
    - Remove currency symbols ($, US$, $US, €, etc.)
    - Replace non-breaking spaces with normal spaces
    - Strip whitespace
    """
    if pd.isna(s):
        return s
    s = str(s)
    # Remove Notion links
    s = re.sub(r'\(https?://[^)]+\)', '', s)
    # Remove common currency symbols and labels
    s = s.replace('$US', '').replace('US$', '').replace('$', '').replace('€', '')
    # Replace non-breaking space with normal space
    s = s.replace('\xa0', ' ').strip()
    return s


def extract_pnl(val):
    """
    Convert Gross/Net PnL values (e.g., "88,00 $US", "-50,00 $US", "(50,00)") to float.
    Handles commas as decimal separators, thousands separators, and negative numbers.
    """
    if pd.isna(val) or str(val).strip() == "":
        return np.nan

    s = clean_numeric_string(val)
    if not s:
        return np.nan

    # Detect negative: minus sign or parentheses
    is_neg = '-' in s or '(' in s

    # Remove parentheses if present (for negative numbers)
    if '(' in s and ')' in s:
        s = s.replace('(', '').replace(')', '')

    # Handle comma as decimal separator or thousands separator
    # If both comma and dot present, assume comma is thousands separator (remove it)
    if ',' in s and '.' in s:
        s = s.replace(',', '')
    else:
        # Otherwise, treat comma as decimal separator
        s = s.replace(',', '.')

    # Remove all non-digit characters except dot (keep the decimal point)
    s = re.sub(r'[^\d\.]', '', s)

    # If after cleaning we have nothing, return NaN
    if not s:
        return np.nan

    try:
        num = float(s)
        return -num if is_neg else num
    except ValueError:
        return np.nan


def parse_number_generic(val):
    """
    Parse numbers from various columns (e.g., "% Risk", "SL Management", "Actual RR").
    Handles percentages, negative numbers, parentheses, and European formatting.
    """
    if pd.isna(val):
        return np.nan

    s = clean_numeric_string(val)
    if not s:
        return np.nan

    # Check for percentage sign
    is_percent = '%' in s
    s = s.replace('%', '')

    # Detect negative: minus sign or parentheses
    is_neg = s.startswith('-')
    # If it's in parentheses (e.g., "(12,34)"), convert to negative
    if re.match(r'^\(.*\)$', s):
        s = '-' + s.strip('()')
        is_neg = True

    # Remove leading minus/plus signs for parsing (keep negativity flag)
    s = s.lstrip('-+')

    # Handle comma as decimal separator or thousands separator
    if ',' in s and '.' in s:
        s = s.replace(',', '')
    else:
        s = s.replace(',', '.')

    # Remove all non-digit characters except dot
    s = re.sub(r'[^\d\.]', '', s)

    if not s:
        return np.nan

    try:
        num = float(s)
        if is_neg:
            num = -num
        if is_percent:
            num = num / 100.0
        return num
    except ValueError:
        return np.nan


# ---- Main Processing Class (unchanged except account filter) ----
class TradingStatsApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Trading Statistics Analyzer")
        self.root.geometry("800x650")

        # Variables
        self.filepath_var = tk.StringVar(value="test.xlsx - Sheet1.csv")
        self.old_balance_var = tk.DoubleVar(value=5000.0)
        self.old_risk_var = tk.DoubleVar(value=1.0)
        self.new_balance_var = tk.DoubleVar(value=100000.0)
        self.new_risk_var = tk.DoubleVar(value=1.0)

        # Grade Filter Variables (Default all to True)
        self.grade_vars = {
            "A+": tk.BooleanVar(value=True),
            "A": tk.BooleanVar(value=True),
            "b": tk.BooleanVar(value=True),
            "C": tk.BooleanVar(value=True)
        }

        self.setup_ui()

    def setup_ui(self):
        # Input Frame
        input_frame = tk.Frame(self.root, padx=10, pady=10)
        input_frame.pack(fill=tk.X)

        # File Selection
        tk.Label(input_frame, text="Input CSV File:").grid(row=0, column=0, sticky="e", pady=2)
        tk.Entry(input_frame, textvariable=self.filepath_var, width=50).grid(row=0, column=1, padx=5, pady=2)
        tk.Button(input_frame, text="Browse", command=self.browse_file).grid(row=0, column=2, pady=2)

        # Old Settings
        tk.Label(input_frame, text="Original Account Balance ($):").grid(row=1, column=0, sticky="e", pady=2)
        tk.Entry(input_frame, textvariable=self.old_balance_var).grid(row=1, column=1, sticky="w", padx=5, pady=2)
        tk.Label(input_frame, text="Original Risk (%):").grid(row=2, column=0, sticky="e", pady=2)
        tk.Entry(input_frame, textvariable=self.old_risk_var).grid(row=2, column=1, sticky="w", padx=5, pady=2)

        # New Settings
        tk.Label(input_frame, text="New Account Balance ($):").grid(row=3, column=0, sticky="e", pady=2)
        tk.Entry(input_frame, textvariable=self.new_balance_var).grid(row=3, column=1, sticky="w", padx=5, pady=2)
        tk.Label(input_frame, text="New Risk (%):").grid(row=4, column=0, sticky="e", pady=2)
        tk.Entry(input_frame, textvariable=self.new_risk_var).grid(row=4, column=1, sticky="w", padx=5, pady=2)

        # Grade Filter Section
        filter_frame = tk.LabelFrame(self.root, text="Filter by Setup Grade (Uncheck to exclude)", padx=10, pady=5)
        filter_frame.pack(fill=tk.X, padx=10, pady=5)

        col_idx = 0
        for grade, var in self.grade_vars.items():
            tk.Checkbutton(filter_frame, text=f"Grade {grade}", variable=var).grid(row=0, column=col_idx, padx=15)
            col_idx += 1

        # Run Button Frame
        btn_frame = tk.Frame(self.root)
        btn_frame.pack(fill=tk.X, pady=5)
        tk.Button(btn_frame, text="Run Analysis", command=self.run_analysis, bg="green", fg="white",
                  font=("Arial", 10, "bold")).pack()

        # Console Output Box
        self.console = scrolledtext.ScrolledText(self.root, wrap=tk.WORD, font=("Consolas", 9))
        self.console.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    def browse_file(self):
        filepath = filedialog.askopenfilename(filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")])
        if filepath:
            self.filepath_var.set(filepath)

    def log(self, message=""):
        self.console.insert(tk.END, message + "\n")
        self.console.see(tk.END)
        self.root.update()

    def run_analysis(self):
        self.console.delete(1.0, tk.END)  # Clear console
        input_path = self.filepath_var.get()

        if not os.path.exists(input_path):
            messagebox.showerror("Error", f"File not found: {input_path}")
            return

        try:
            # Calculate Multiplier
            old_b = self.old_balance_var.get()
            old_r = self.old_risk_var.get()
            new_b = self.new_balance_var.get()
            new_r = self.new_risk_var.get()

            old_risk_dollar = old_b * (old_r / 100)
            new_risk_dollar = new_b * (new_r / 100)

            if old_risk_dollar == 0:
                raise ValueError("Original balance or risk cannot be zero.")

            multiplier = new_risk_dollar / old_risk_dollar

            self.log(f"--- Analysis Started ---")
            self.log(f"Original Risk Value: ${old_risk_dollar:.2f}")
            self.log(f"New Risk Value: ${new_risk_dollar:.2f}")
            self.log(f"Applied PnL Multiplier: {multiplier:.4f}\n")

            dataset_name = Path(input_path).stem
            dir_name = f"{dataset_name}_{int(new_b)}_{new_r}pct"
            out_dir = Path(dir_name)
            out_dir.mkdir(exist_ok=True)

            self.log(f"Loading data from {input_path}...")
            df = pd.read_csv(input_path)

            # Clean Notion links from known text columns
            cols_to_clean = [
                'Account', 'Symbol', 'Model', 'News Impact', 'Bias', 'Market Conditions', 'Type of Trade', 'Session',
                'Entry TimeFrame', 'Confluences', 'Key Levels', 'Entry Signal', 'Order Type',
                'SL Management', 'TP Management', 'Setup Grade', 'Outcome'
            ]
            # Also clean any string column that might contain links (optional but safe)
            for col in df.columns:
                if df[col].dtype == object:
                    df[col] = df[col].apply(clean_numeric_string)  # This also removes links

            # --- NEW: Filter only rows where Account is BACKTEST 2 ---
            if 'Account' in df.columns:
                # Use case-insensitive contains to match values like "BACKTEST 2" or "BACKTEST 2 "
                mask = df['Account'].astype(str).str.contains('BACKTEST 2', case=False, na=False)
                df = df[mask]
                self.log("FILTER APPLIED: Processing only rows where Account contains 'BACKTEST 2'")
                if df.empty:
                    self.log("ERROR: No trades found with Account == BACKTEST 2. Exiting analysis.")
                    return
            else:
                self.log("WARNING: 'Account' column not found. Proceeding without Account filter (but you asked to filter for BACKTEST 2).")

            # --- Filter by Setup Grade ---
            if 'Setup Grade' in df.columns:
                selected_grades = [grade for grade, var in self.grade_vars.items() if var.get()]
                df = df[df['Setup Grade'].isin(selected_grades)]
                self.log(f"FILTER APPLIED: Processing only Setup Grades: {', '.join(selected_grades)}")
                if df.empty:
                    self.log("ERROR: No trades found with the selected Setup Grades. Exiting analysis.")
                    return
            else:
                self.log("WARNING: 'Setup Grade' column not found. Analyzing all trades.")

            # Convert PnL columns using extract_pnl
            for pnl_col in ('Net PnL', 'Gross PnL'):
                if pnl_col in df.columns:
                    df[pnl_col] = df[pnl_col].apply(extract_pnl)

            # Parse dates if available
            if 'Entry / Exit Date' in df.columns:
                df['Entry / Exit Date'] = pd.to_datetime(df['Entry / Exit Date'], errors='coerce')
                df['Month'] = df['Entry / Exit Date'].dt.to_period('M').astype(str)
                df['Day'] = df['Entry / Exit Date'].dt.date
                df['Day Name'] = df['Entry / Exit Date'].dt.day_name()

            # Detect numeric columns (including those already numeric)
            numeric_candidates = []
            numeric_series_map = {}

            for col in df.columns:
                # Skip columns that are obviously text or date-related
                if col in cols_to_clean or 'Date' in col or col in ('Month', 'Day', 'Day Name', 'Entry / Exit Date'):
                    continue

                if df[col].dtype == object:
                    cleaned = df[col].apply(parse_number_generic)
                else:
                    cleaned = pd.to_numeric(df[col], errors='coerce')

                non_null = int(cleaned.notna().sum())
                # Consider it numeric if at least 2 non-null and at least 30% of rows or at least 2 (for small data)
                if non_null >= 2 and (non_null >= 0.3 * len(df) or non_null >= 2):
                    numeric_candidates.append(col)
                    numeric_series_map[col] = cleaned

            # Ensure PnL columns are included even if they weren't detected (they should be)
            for special in ('Net PnL', 'Gross PnL'):
                if special in df.columns and special not in numeric_candidates:
                    numeric_candidates.append(special)
                    numeric_series_map[special] = df[special].astype(float)

            # Apply multiplier to PnL columns and create scaled numeric columns
            for col, ser in numeric_series_map.items():
                if col in ('Net PnL', 'Gross PnL'):
                    df[col + "_num"] = ser.astype(float) * multiplier
                else:
                    df[col + "_num"] = ser.astype(float)

            numeric_cols = [c + "_num" for c in numeric_series_map.keys()]

            if not numeric_cols:
                self.log("No numeric/calculation-related columns detected. Exiting.")
                return

            # Basic statistics
            stats = df[numeric_cols].describe().T
            stats['sum'] = df[numeric_cols].sum()
            stats['missing'] = df[numeric_cols].isna().sum()
            stats.index = [idx.replace('_num', '') for idx in stats.index]

            stats_display = stats.copy()
            for c in stats_display.columns:
                if stats_display[c].dtype.kind in 'f':
                    stats_display[c] = stats_display[c].round(4)

            self.log("\n==== Numeric columns detected and their statistics ====\n")
            self.log(stats_display.to_string())
            self.log("\n")

            # KPIs
            if 'Net PnL_num' in df.columns:
                net = df['Net PnL_num'].fillna(0.0)
                total_pnl = net.sum()
                total_trades = len(df)
                wins = int((net > 0).sum())
                losses = int((net < 0).sum())
                breakeven = int((net == 0).sum())
                win_rate = wins / total_trades if total_trades > 0 else 0.0
                avg_win = float(net[net > 0].mean()) if wins > 0 else 0.0
                avg_loss = float(net[net < 0].mean()) if losses > 0 else 0.0
                sum_wins = float(net[net > 0].sum()) if wins > 0 else 0.0
                sum_losses = float(net[net < 0].sum()) if losses > 0 else 0.0
                profit_factor = (sum_wins / abs(sum_losses)) if abs(sum_losses) > 0 else np.inf
                expectancy = win_rate * avg_win + (1 - win_rate) * avg_loss

                self.log("==== Trading KPIs (Scaled by New Parameters) ====\n")
                self.log(f"Total Trades: {total_trades}")
                self.log(f"Total Net PnL: ${total_pnl:.2f}")
                self.log(f"Wins: {wins}, Losses: {losses}, Breakeven: {breakeven}")
                self.log(f"Win Rate: {win_rate * 100:.2f}%")
                self.log(f"Average Win: ${avg_win:.2f}")
                self.log(f"Average Loss: ${avg_loss:.2f}")
                self.log(f"Sum Wins: ${sum_wins:.2f}, Sum Losses: ${sum_losses:.2f}")
                self.log(f"Profit Factor: {profit_factor if profit_factor != np.inf else 'inf'}")
                self.log(f"Expectancy per trade: ${expectancy:.4f}\n")

            # Add this after the existing group summaries logic
            if 'Month' in df.columns and 'Symbol' in df.columns:
                # Group by Month and Symbol to count trades
                trades_per_month_pair = df.groupby(['Month', 'Symbol'])['Net PnL_num'].agg(['count']).rename(columns={
                    'count': 'trades'
                }).sort_index()

                # Log the results
                self.log("==== Number of Trades per Pair per Month ====")
                self.log(trades_per_month_pair.to_string())
                self.log("\n")

                # Save to CSV
                trades_per_month_pair.to_csv(out_dir / f"{dataset_name}_trades_per_month_pair.csv")

            # Group summaries
            def make_group_summary(key):
                grp = df.groupby(key)['Net PnL_num'].agg(['count', 'sum', 'mean']).rename(columns={
                    'count': 'trades',
                    'sum': 'sum_net_pnl',
                    'mean': 'avg_net_pnl'
                })
                total_net = df['Net PnL_num'].sum()
                grp['pct_of_total_net_pnl'] = (grp['sum_net_pnl'] / total_net * 100).replace([np.inf, -np.inf], np.nan)
                grp['pct_of_trades'] = grp['trades'] / len(df) * 100
                grp = grp.sort_values('sum_net_pnl', ascending=False)
                grp['cumulative_pct_net_pnl'] = grp['pct_of_total_net_pnl'].cumsum()
                if total_net == 0:
                    grp['pct_of_total_net_pnl'] = 0.0
                    grp['cumulative_pct_net_pnl'] = grp['pct_of_total_net_pnl'].cumsum()
                return grp, grp.round(4)

            group_keys = [k for k in ('Symbol', 'Month', 'Day Name', 'Day', 'Setup Grade', 'Bias') if k in df.columns]

            for key in group_keys:
                grp, grp_display = make_group_summary(key)
                self.log(f"==== Net PnL by {key} (with % of total net PnL and % of trades) ====")
                self.log(grp_display.to_string())
                self.log("\n")
                grp.to_csv(out_dir / f"{dataset_name}_groupby_{key.replace(' ', '_')}_with_pct.csv")

            if 'Day' in df.columns:
                daily = df.groupby('Day')['Net PnL_num'].agg(['count', 'sum', 'mean']).rename(columns={
                    'count': 'trades',
                    'sum': 'sum_net_pnl',
                    'mean': 'avg_net_pnl'
                }).sort_index()
                total_net = df['Net PnL_num'].sum()
                daily['pct_of_total_net_pnl'] = (daily['sum_net_pnl'] / total_net * 100).replace([np.inf, -np.inf],
                                                                                                 np.nan)
                daily['pct_of_trades'] = daily['trades'] / len(df) * 100
                if total_net == 0:
                    daily['pct_of_total_net_pnl'] = 0.0
                daily_display = daily.round(4)
                self.log("==== Per-calendar-day Net PnL summary ====")
                self.log(daily_display.to_string())
                self.log("\n")
                daily.to_csv(out_dir / f"{dataset_name}_per_day_summary_with_pct.csv")

            # Save outputs
            cleaned_path = out_dir / f"{dataset_name}_cleaned.csv"
            numeric_summary_path = out_dir / f"{dataset_name}_numeric_summary.csv"

            df.to_csv(cleaned_path, index=False)
            stats.to_csv(numeric_summary_path)

            self.log(f"Saved cleaned data to: {cleaned_path}")
            self.log(f"Saved numeric summary to: {numeric_summary_path}")
            self.log(f"Saved groupby files to folder: {out_dir}")

            messagebox.showinfo("Success", f"Analysis complete!\nOutputs saved to:\n{out_dir}")

        except Exception as e:
            self.log(f"ERROR: {str(e)}")
            messagebox.showerror("Error", str(e))


if __name__ == "__main__":
    root = tk.Tk()
    app = TradingStatsApp(root)
    root.mainloop()