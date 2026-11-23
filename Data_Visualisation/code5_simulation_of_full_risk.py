import os
import re
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
from tkinter import ttk
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
    Convert Gross/Net PnL values (e.g., "88,00 $US", "-50,00 $US", "(50,00)") to float.
    Handles commas as decimal separators, thousands separators, and negative numbers.
    """
    if pd.isna(val) or str(val).strip() == "":
        return np.nan

    s = clean_numeric_string(val)
    if not s:
        return np.nan

    is_neg = '-' in s or '(' in s

    if '(' in s and ')' in s:
        s = s.replace('(', '').replace(')', '')

    if ',' in s and '.' in s:
        s = s.replace(',', '')
    else:
        s = s.replace(',', '.')

    s = re.sub(r'[^\d\.]', '', s)

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

    is_percent = '%' in s
    s = s.replace('%', '')

    is_neg = s.startswith('-')
    if re.match(r'^\(.*\)$', s):
        s = '-' + s.strip('()')
        is_neg = True

    s = s.lstrip('-+')

    if ',' in s and '.' in s:
        s = s.replace(',', '')
    else:
        s = s.replace(',', '.')

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


# ---- Main Processing Class ----
class TradingStatsApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Trading Toolkit: Stats Analyzer & Prop Simulator")
        self.root.geometry("900x750")

        # Global Filepath Variable
        self.filepath_var = tk.StringVar(value="test.xlsx - Sheet1.csv")

        # Set up Tabbed Interface
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.tab_stats = ttk.Frame(self.notebook)
        self.tab_sim = ttk.Frame(self.notebook)

        self.notebook.add(self.tab_stats, text="1. Original Data Analyzer")
        self.notebook.add(self.tab_sim, text="2. 3-Step Payout Simulator")

        # --- Variables for Tab 1 (Original App) ---
        self.old_balance_var = tk.DoubleVar(value=5000.0)
        self.old_risk_var = tk.DoubleVar(value=1.0)
        self.new_balance_var = tk.DoubleVar(value=100000.0)
        self.new_risk_var = tk.DoubleVar(value=1.0)
        self.grade_vars = {
            "A+": tk.BooleanVar(value=True),
            "A": tk.BooleanVar(value=True),
            "b": tk.BooleanVar(value=True),
            "C": tk.BooleanVar(value=True)
        }

        # --- Variables for Tab 2 (Simulator) ---
        self.sim_acc_cost = tk.DoubleVar(value=49.0)
        self.sim_acc_multiplier = tk.IntVar(value=1)
        self.sim_payout_amount = tk.DoubleVar(value=8000.0)  # E.g., 8% of 100k

        self.setup_global_ui()
        self.setup_ui_stats()
        self.setup_ui_sim()

    def setup_global_ui(self):
        # File Selection (Shared above tabs)
        file_frame = tk.Frame(self.root, padx=10, pady=5)
        file_frame.pack(fill=tk.X, side=tk.TOP, before=self.notebook)

        tk.Label(file_frame, text="Input CSV File:", font=("Arial", 10, "bold")).pack(side=tk.LEFT)
        tk.Entry(file_frame, textvariable=self.filepath_var, width=50).pack(side=tk.LEFT, padx=10)
        tk.Button(file_frame, text="Browse", command=self.browse_file).pack(side=tk.LEFT)

    # =========================================================
    # TAB 1: YOUR ORIGINAL APP UI & LOGIC
    # =========================================================
    def setup_ui_stats(self):
        input_frame = tk.Frame(self.tab_stats, padx=10, pady=10)
        input_frame.pack(fill=tk.X)

        tk.Label(input_frame, text="Original Account Balance ($):").grid(row=1, column=0, sticky="e", pady=2)
        tk.Entry(input_frame, textvariable=self.old_balance_var).grid(row=1, column=1, sticky="w", padx=5, pady=2)
        tk.Label(input_frame, text="Original Risk (%):").grid(row=2, column=0, sticky="e", pady=2)
        tk.Entry(input_frame, textvariable=self.old_risk_var).grid(row=2, column=1, sticky="w", padx=5, pady=2)

        tk.Label(input_frame, text="New Account Balance ($):").grid(row=3, column=0, sticky="e", pady=2)
        tk.Entry(input_frame, textvariable=self.new_balance_var).grid(row=3, column=1, sticky="w", padx=5, pady=2)
        tk.Label(input_frame, text="New Risk (%):").grid(row=4, column=0, sticky="e", pady=2)
        tk.Entry(input_frame, textvariable=self.new_risk_var).grid(row=4, column=1, sticky="w", padx=5, pady=2)

        filter_frame = tk.LabelFrame(self.tab_stats, text="Filter by Setup Grade (Uncheck to exclude)", padx=10, pady=5)
        filter_frame.pack(fill=tk.X, padx=10, pady=5)

        col_idx = 0
        for grade, var in self.grade_vars.items():
            tk.Checkbutton(filter_frame, text=f"Grade {grade}", variable=var).grid(row=0, column=col_idx, padx=15)
            col_idx += 1

        btn_frame = tk.Frame(self.tab_stats)
        btn_frame.pack(fill=tk.X, pady=5)
        tk.Button(btn_frame, text="Run Analysis", command=self.run_analysis, bg="green", fg="white",
                  font=("Arial", 10, "bold")).pack()

        self.console_stats = scrolledtext.ScrolledText(self.tab_stats, wrap=tk.WORD, font=("Consolas", 9))
        self.console_stats.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    def log(self, message=""):
        self.console_stats.insert(tk.END, message + "\n")
        self.console_stats.see(tk.END)
        self.root.update()

    def run_analysis(self):
        self.console_stats.delete(1.0, tk.END)
        input_path = self.filepath_var.get()
        if not os.path.exists(input_path):
            messagebox.showerror("Error", f"File not found: {input_path}")
            return

        try:
            old_b = self.old_balance_var.get()
            old_r = self.old_risk_var.get()
            new_b = self.new_balance_var.get()
            new_r = self.new_risk_var.get()
            old_risk_dollar = old_b * (old_r / 100)
            new_risk_dollar = new_b * (new_r / 100)

            if old_risk_dollar == 0: raise ValueError("Original balance or risk cannot be zero.")
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

            if 'Entry Time' in df.columns and 'Entry / Exit Date' not in df.columns:
                df.rename(columns={'Entry Time': 'Entry / Exit Date'}, inplace=True)

            if 'Result' in df.columns and 'R:R' in df.columns and 'Net PnL' not in df.columns:
                def calculate_pnl(row):
                    res = str(row['Result']).strip().upper()
                    try:
                        rr = float(row['R:R'])
                    except:
                        rr = 0.0
                    if abs(rr) < 0.1: return 0.0
                    if res == 'WIN':
                        return rr * old_risk_dollar
                    elif res == 'LOSS':
                        return -1.0 * old_risk_dollar
                    return 0.0

                df['Net PnL'] = df.apply(calculate_pnl, axis=1)

            cols_to_clean = ['Account', 'Symbol', 'Model', 'News Impact', 'Bias', 'Market Conditions', 'Type of Trade',
                             'Session', 'Entry TimeFrame', 'Confluences', 'Key Levels', 'Entry Signal', 'Order Type',
                             'SL Management', 'TP Management', 'Setup Grade', 'Outcome']
            for col in df.columns:
                if df[col].dtype == object: df[col] = df[col].apply(clean_numeric_string)

            if 'Setup Grade' in df.columns:
                selected_grades = [grade for grade, var in self.grade_vars.items() if var.get()]
                df = df[df['Setup Grade'].isin(selected_grades)]
                if df.empty:
                    self.log("ERROR: No trades found with the selected Setup Grades. Exiting analysis.")
                    return

            for pnl_col in ('Net PnL', 'Gross PnL'):
                if pnl_col in df.columns: df[pnl_col] = df[pnl_col].apply(extract_pnl)

            if 'Entry / Exit Date' in df.columns:
                df['Entry / Exit Date'] = pd.to_datetime(df['Entry / Exit Date'], errors='coerce')
                df['Month'] = df['Entry / Exit Date'].dt.to_period('M').astype(str)
                df['Day'] = df['Entry / Exit Date'].dt.date
                df['Day Name'] = df['Entry / Exit Date'].dt.day_name()

            numeric_candidates = []
            numeric_series_map = {}
            for col in df.columns:
                if col in cols_to_clean or 'Date' in col or col in ('Month', 'Day', 'Day Name', 'Entry / Exit Date'):
                    continue
                if df[col].dtype == object:
                    cleaned = df[col].apply(parse_number_generic)
                else:
                    cleaned = pd.to_numeric(df[col], errors='coerce')
                non_null = int(cleaned.notna().sum())
                if non_null >= 2 and (non_null >= 0.3 * len(df) or non_null >= 2):
                    numeric_candidates.append(col)
                    numeric_series_map[col] = cleaned

            for special in ('Net PnL', 'Gross PnL'):
                if special in df.columns and special not in numeric_candidates:
                    numeric_candidates.append(special)
                    numeric_series_map[special] = df[special].astype(float)

            for col, ser in numeric_series_map.items():
                if col in ('Net PnL', 'Gross PnL'):
                    df[col + "_num"] = ser.astype(float) * multiplier
                else:
                    df[col + "_num"] = ser.astype(float)

            numeric_cols = [c + "_num" for c in numeric_series_map.keys()]
            if not numeric_cols: return

            stats = df[numeric_cols].describe().T
            stats['sum'] = df[numeric_cols].sum()
            stats['missing'] = df[numeric_cols].isna().sum()
            stats.index = [idx.replace('_num', '') for idx in stats.index]
            stats_display = stats.copy()
            for c in stats_display.columns:
                if stats_display[c].dtype.kind in 'f': stats_display[c] = stats_display[c].round(4)

            self.log("\n==== Numeric columns detected and their statistics ====\n")
            self.log(stats_display.to_string())
            self.log("\n")

            df.to_csv(out_dir / f"{dataset_name}_cleaned.csv", index=False)
            messagebox.showinfo("Success", f"Analysis complete!\nOutputs saved to:\n{out_dir}")

        except Exception as e:
            self.log(f"ERROR: {str(e)}")

    # =========================================================
    # TAB 2: NEW 3-STEP PAYOUT SIMULATOR UI & LOGIC
    # =========================================================
    def setup_ui_sim(self):
        input_frame = tk.Frame(self.tab_sim, padx=10, pady=10)
        input_frame.pack(fill=tk.X)

        tk.Label(input_frame, text="Cost to Buy 1 Account ($):", font=("Arial", 10)).grid(row=0, column=0, sticky="e",
                                                                                          pady=5, padx=5)
        tk.Entry(input_frame, textvariable=self.sim_acc_cost, width=15).grid(row=0, column=1, sticky="w", pady=5)

        tk.Label(input_frame, text="Payout Amount Received per Funded Win ($):", font=("Arial", 10)).grid(row=1,
                                                                                                          column=0,
                                                                                                          sticky="e",
                                                                                                          pady=5,
                                                                                                          padx=5)
        tk.Entry(input_frame, textvariable=self.sim_payout_amount, width=15).grid(row=1, column=1, sticky="w", pady=5)

        tk.Label(input_frame, text="Simultaneous Accounts (Multiplier):", font=("Arial", 10)).grid(row=2, column=0,
                                                                                                   sticky="e", pady=5,
                                                                                                   padx=5)
        tk.Entry(input_frame, textvariable=self.sim_acc_multiplier, width=15).grid(row=2, column=1, sticky="w", pady=5)

        btn_frame = tk.Frame(self.tab_sim)
        btn_frame.pack(fill=tk.X, pady=10)
        tk.Button(btn_frame, text="Run Payout Streak Simulation", command=self.run_simulation, bg="blue", fg="white",
                  font=("Arial", 10, "bold")).pack()

        self.console_sim = scrolledtext.ScrolledText(self.tab_sim, wrap=tk.WORD, font=("Consolas", 10))
        self.console_sim.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    def log_sim(self, message=""):
        self.console_sim.insert(tk.END, message + "\n")
        self.console_sim.see(tk.END)
        self.root.update()

    def browse_file(self):
        filepath = filedialog.askopenfilename(filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")])
        if filepath:
            self.filepath_var.set(filepath)

    def run_simulation(self):
        self.console_sim.delete(1.0, tk.END)
        input_path = self.filepath_var.get()
        if not os.path.exists(input_path):
            messagebox.showerror("Error", "File not found.")
            return

        acc_cost = self.sim_acc_cost.get()
        payout_amt = self.sim_payout_amount.get()
        multiplier = max(1, self.sim_acc_multiplier.get())  # at least 1

        self.log_sim("--- Starting 3-Step Payout Simulation ---")
        self.log_sim("Logic: 3 consecutive Wins required for Payout.")
        self.log_sim(" Trade 1 Win -> Phase 1 Passed")
        self.log_sim(" Trade 2 Win -> Phase 2 Passed (Funded)")
        self.log_sim(" Trade 3 Win -> Payout Achieved!")
        self.log_sim(" Any Loss = Account Blown. Buy new account.\n")

        df = pd.read_csv(input_path)

        if 'Entry Time' in df.columns and 'Entry / Exit Date' not in df.columns:
            df.rename(columns={'Entry Time': 'Entry / Exit Date'}, inplace=True)
        if 'Entry / Exit Date' not in df.columns:
            self.log_sim("ERROR: Could not find 'Entry / Exit Date' column.")
            return

        df['Entry / Exit Date'] = pd.to_datetime(df['Entry / Exit Date'], errors='coerce')
        df = df.dropna(subset=['Entry / Exit Date']).sort_values('Entry / Exit Date')
        df['Month_Str'] = df['Entry / Exit Date'].dt.to_period('M').astype(str)

        def is_win(row):
            res = str(row.get('Result', '')).strip().upper()
            if res == 'WIN': return True
            if res == 'LOSS': return False
            if 'R:R' in row:
                try:
                    rr = float(str(row['R:R']).replace(',', '.'))
                    if rr >= 0.1: return True
                    if rr <= -0.1: return False
                except:
                    pass
            return None  # Breakeven, ignored

        # State Machine Tracking
        state = 'PHASE_1'  # Can be: PHASE_1, PHASE_2, FUNDED

        # Monthly Tracking Dictionary
        monthly_data = {}

        total_accs_bought = 0
        total_payouts_achieved = 0

        for _, row in df.iterrows():
            win = is_win(row)
            if win is None: continue  # Skip breakevens

            month = row['Month_Str']
            if month not in monthly_data:
                monthly_data[month] = {'accounts_bought': 0, 'payouts': 0, 'funded_reached': 0}

            if state == 'PHASE_1':
                # First trade on a fresh account
                monthly_data[month]['accounts_bought'] += 1
                total_accs_bought += 1

                if win:
                    state = 'PHASE_2'
                else:
                    state = 'PHASE_1'  # Blown, start over on next trade

            elif state == 'PHASE_2':
                if win:
                    state = 'FUNDED'
                    monthly_data[month]['funded_reached'] += 1
                else:
                    state = 'PHASE_1'  # Failed Phase 2, blown

            elif state == 'FUNDED':
                if win:
                    monthly_data[month]['payouts'] += 1
                    total_payouts_achieved += 1
                    # Stay funded for the next trade to potentially get consecutive payouts
                    state = 'FUNDED'
                else:
                    state = 'PHASE_1'  # Funded account blown, start over

        # ----------------------------------------------------
        # Display Results
        # ----------------------------------------------------
        self.log_sim("======================================================")
        self.log_sim("                MONTHLY BUDGET & PAYOUTS              ")
        self.log_sim("======================================================")

        total_expenses = 0
        total_revenue = 0

        for month in sorted(monthly_data.keys()):
            stats = monthly_data[month]

            # Apply user multiplier
            accs_bought = stats['accounts_bought'] * multiplier
            funded = stats['funded_reached'] * multiplier
            payouts = stats['payouts'] * multiplier

            cost_this_month = accs_bought * acc_cost
            revenue_this_month = payouts * payout_amt
            net_this_month = revenue_this_month - cost_this_month

            total_expenses += cost_this_month
            total_revenue += revenue_this_month

            self.log_sim(f"► Month: {month}")
            self.log_sim(
                f"  Accounts Bought (Budget for failures/starts): {accs_bought} (Cost: ${cost_this_month:,.2f})")
            self.log_sim(f"  Accounts passed to Funded Phase:              {funded}")
            self.log_sim(
                f"  Payouts Achieved (3rd win+):                  {payouts} (Revenue: ${revenue_this_month:,.2f})")

            # Formatting color indicator text for profit vs loss
            pl_text = f"+${net_this_month:,.2f}" if net_this_month >= 0 else f"-${abs(net_this_month):,.2f}"
            self.log_sim(f"  Month Net P/L:                                {pl_text}\n")

        self.log_sim("======================================================")
        self.log_sim("                    GRAND TOTALS                      ")
        self.log_sim("======================================================")
        self.log_sim(f"Total Accounts Bought (x{multiplier}):  {total_accs_bought * multiplier}")
        self.log_sim(f"Total Payouts Achieved (x{multiplier}): {total_payouts_achieved * multiplier}")
        self.log_sim(f"Total Capital Risked (Cost):   ${total_expenses:,.2f}")
        self.log_sim(f"Total Payout Revenue:          ${total_revenue:,.2f}")

        grand_net = total_revenue - total_expenses
        net_text = f"+${grand_net:,.2f} (PROFIT)" if grand_net >= 0 else f"-${abs(grand_net):,.2f} (LOSS)"
        self.log_sim(f"\nGRAND NET ROI:                 {net_text}")


if __name__ == "__main__":
    root = tk.Tk()
    app = TradingStatsApp(root)
    root.mainloop()