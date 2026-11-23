import os
import re
import math
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
import sys
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg


# --------------------------------------------------------------
# Helper functions for numeric extraction (unchanged semantics)
# --------------------------------------------------------------
def clean_numeric_string(s):
    if pd.isna(s):
        return s
    s = str(s)
    s = re.sub(r'\(https?://[^)]+\)', '', s)
    s = s.replace('$US', '').replace('US$', '').replace('$', '').replace('€', '')
    s = s.replace('\xa0', ' ').strip()
    return s


def extract_pnl(val):
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


# --------------------------------------------------------------
# Monte Carlo Simulator
# --------------------------------------------------------------
class MonteCarloSimulator:
    def __init__(self, r_multiples, initial_balance, risk_per_trade_pct):
        """
        r_multiples : array of R multiples (PnL / original_risk_dollar)
        initial_balance : starting cash
        risk_per_trade_pct : percent of current balance risked each trade (e.g., 1.0 for 1%)
        """
        self.r_multiples = np.array(r_multiples)
        self.initial_balance = initial_balance
        self.risk_pct = risk_per_trade_pct / 100.0

    def simulate(self, num_simulations=1000, num_trades=500):
        """
        Run Monte Carlo simulations. Returns equity_curves ndarray shape (n_sim, n_trades+1).
        """
        all_equity_curves = []

        for _ in range(num_simulations):
            balance = self.initial_balance
            equity = [balance]
            # randomly sample trades (with replacement)
            trades = np.random.choice(self.r_multiples, size=num_trades, replace=True)
            for r in trades:
                risk_amount = balance * self.risk_pct
                pnl = r * risk_amount
                balance = balance + pnl
                equity.append(balance)
            all_equity_curves.append(equity)

        return np.array(all_equity_curves)  # shape: (n_sim, n_trades+1)

    @staticmethod
    def aggregate_monthly(equity_curve, trades_per_month=20):
        """
        Convert an equity curve (list of balances after each trade) into monthly returns.
        Returns list of (percent_return, dollar_profit) for each month.
        """
        monthly = []
        n = len(equity_curve)
        # start points at trade index 0 then each trades_per_month
        for i in range(0, n - 1, trades_per_month):
            start = equity_curve[i]
            end = equity_curve[min(i + trades_per_month, n - 1)]
            if start != 0:
                pct = (end - start) / start * 100.0
                profit = end - start
                monthly.append((pct, profit))
        return monthly

    @staticmethod
    def compute_drawdown_stats(curve):
        """
        Compute max drawdown for single equity curve.
        Returns (max_drawdown_pct, max_drawdown_dollar)
        """
        peak = -np.inf
        max_dd_pct = 0.0
        max_dd_dollar = 0.0
        for val in curve:
            if val > peak:
                peak = val
            else:
                dd_dollar = peak - val
                if peak != 0:
                    dd_pct = dd_dollar / peak * 100.0
                else:
                    dd_pct = 0.0
                if dd_pct > max_dd_pct:
                    max_dd_pct = dd_pct
                    max_dd_dollar = dd_dollar
        return max_dd_pct, max_dd_dollar


# --------------------------------------------------------------
# Main Application with Monte Carlo integration and UI
# --------------------------------------------------------------
class TradingStatsApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Trading Analyzer + Monte Carlo Simulator")
        self.root.geometry("1100x800")

        # Data storage
        self.filtered_df = None
        self.r_multiples = None
        self.original_risk_dollar = None

        # Variables for original analysis
        self.filepath_var = tk.StringVar(value="test.csv")
        self.old_balance_var = tk.DoubleVar(value=5000.0)
        self.old_risk_var = tk.DoubleVar(value=1.0)
        self.new_balance_var = tk.DoubleVar(value=100000.0)
        self.new_risk_var = tk.DoubleVar(value=1.0)

        # Grade filter
        self.grade_vars = {
            "A+": tk.BooleanVar(value=True),
            "A": tk.BooleanVar(value=True),
            "B": tk.BooleanVar(value=True),
            "C": tk.BooleanVar(value=True)
        }

        # Monte Carlo parameters
        self.mc_start_balance = tk.DoubleVar(value=1000.0)
        self.mc_risk_per_trade = tk.DoubleVar(value=1.0)
        self.mc_num_simulations = tk.IntVar(value=500)
        self.mc_num_trades = tk.IntVar(value=500)
        self.mc_trades_per_month = tk.IntVar(value=20)

        # Option to risk percent of initial starting balance (fixed $) instead of percent of current balance
        self.mc_use_initial_for_risk = tk.BooleanVar(value=False)

        # UI elements to be created later
        self.mc_canvas_fig = None
        self.kpi_labels = {}

        self.setup_ui()

    def setup_ui(self):
        # Notebook (tabs)
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Tab 1: Data & original analysis
        tab_data = ttk.Frame(notebook)
        notebook.add(tab_data, text="1. Load Data & Basic Stats")

        # Tab 2: Monte Carlo Simulation
        tab_mc = ttk.Frame(notebook)
        notebook.add(tab_mc, text="2. Monte Carlo Simulation")

        # ========== Tab 1 ==========
        input_frame = tk.Frame(tab_data, padx=10, pady=10)
        input_frame.pack(fill=tk.X)

        # File selection
        tk.Label(input_frame, text="Input CSV File:").grid(row=0, column=0, sticky="e", pady=2)
        tk.Entry(input_frame, textvariable=self.filepath_var, width=70).grid(row=0, column=1, padx=5, pady=2)
        tk.Button(input_frame, text="Browse", command=self.browse_file).grid(row=0, column=2, pady=2)

        # Original settings
        tk.Label(input_frame, text="Original Account Balance ($):").grid(row=1, column=0, sticky="e", pady=2)
        tk.Entry(input_frame, textvariable=self.old_balance_var).grid(row=1, column=1, sticky="w", padx=5, pady=2)
        tk.Label(input_frame, text="Original Risk (%):").grid(row=2, column=0, sticky="e", pady=2)
        tk.Entry(input_frame, textvariable=self.old_risk_var).grid(row=2, column=1, sticky="w", padx=5, pady=2)

        tk.Label(input_frame, text="New Account Balance ($):").grid(row=3, column=0, sticky="e", pady=2)
        tk.Entry(input_frame, textvariable=self.new_balance_var).grid(row=3, column=1, sticky="w", padx=5, pady=2)
        tk.Label(input_frame, text="New Risk (%):").grid(row=4, column=0, sticky="e", pady=2)
        tk.Entry(input_frame, textvariable=self.new_risk_var).grid(row=4, column=1, sticky="w", padx=5, pady=2)

        # Grade filter
        filter_frame = tk.LabelFrame(tab_data, text="Filter by Setup Grade (Uncheck to exclude)", padx=10, pady=5)
        filter_frame.pack(fill=tk.X, padx=10, pady=5)
        col_idx = 0
        for grade, var in self.grade_vars.items():
            tk.Checkbutton(filter_frame, text=f"Grade {grade}", variable=var).grid(row=0, column=col_idx, padx=15)
            col_idx += 1

        btn_frame = tk.Frame(tab_data)
        btn_frame.pack(fill=tk.X, pady=5)
        tk.Button(btn_frame, text="Run Historical Analysis", command=self.run_analysis,
                  bg="green", fg="white", font=("Arial", 10, "bold")).pack()

        # Console output
        self.console = scrolledtext.ScrolledText(tab_data, wrap=tk.WORD, font=("Consolas", 9), height=18)
        self.console.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # ========== Tab 2 ==========
        mc_frame = tk.Frame(tab_mc, padx=10, pady=10)
        mc_frame.pack(fill=tk.X)

        left_frame = tk.Frame(mc_frame)
        left_frame.grid(row=0, column=0, sticky="nw")

        right_frame = tk.Frame(mc_frame)
        right_frame.grid(row=0, column=1, sticky="ne", padx=10)

        # Monte Carlo parameters (left)
        tk.Label(left_frame, text="Simulation Starting Balance ($):").grid(row=0, column=0, sticky="e", pady=5)
        tk.Entry(left_frame, textvariable=self.mc_start_balance).grid(row=0, column=1, sticky="w", padx=5, pady=5)

        tk.Label(left_frame, text="Risk per Trade (%):").grid(row=1, column=0, sticky="e", pady=5)
        tk.Entry(left_frame, textvariable=self.mc_risk_per_trade).grid(row=1, column=1, sticky="w", padx=5, pady=5)
        tk.Checkbutton(left_frame, text="Risk % of initial balance (fixed $)", variable=self.mc_use_initial_for_risk).grid(row=1, column=2, sticky="w", padx=5)

        tk.Label(left_frame, text="Number of Simulations:").grid(row=2, column=0, sticky="e", pady=5)
        tk.Entry(left_frame, textvariable=self.mc_num_simulations).grid(row=2, column=1, sticky="w", padx=5, pady=5)

        tk.Label(left_frame, text="Number of Trades (total):").grid(row=3, column=0, sticky="e", pady=5)
        tk.Entry(left_frame, textvariable=self.mc_num_trades).grid(row=3, column=1, sticky="w", padx=5, pady=5)

        tk.Label(left_frame, text="Trades per Month:").grid(row=4, column=0, sticky="e", pady=5)
        tk.Entry(left_frame, textvariable=self.mc_trades_per_month).grid(row=4, column=1, sticky="w", padx=5, pady=5)

        tk.Button(left_frame, text="Run Monte Carlo Simulation", command=self.run_monte_carlo,
                  bg="blue", fg="white", font=("Arial", 10, "bold")).grid(row=5, column=0, columnspan=2, pady=15)

        # KPI summary (right)
        kpi_frame = tk.LabelFrame(right_frame, text="Simulation KPIs", padx=10, pady=10)
        kpi_frame.pack(fill=tk.BOTH, expand=False)
        kpis = [
            ("Account start, $", "account_start"),
            ("Avg. gain per trade, %", "avg_gain_pct"),
            ("End balance, $", "end_balance"),
            ("Return of investment, %", "roi_pct"),
            ("Number of trades, qty", "n_trades"),
            ("Profitable trades, qty", "profitable_trades"),
            ("Losing trade, qty", "losing_trades"),
            ("Max Drawdown, $", "max_dd_dollar"),
            ("Max Drawdown, %", "max_dd_pct"),
        ]
        for i, (lbl, key) in enumerate(kpis):
            tk.Label(kpi_frame, text=lbl).grid(row=i, column=0, sticky="w", padx=5, pady=2)
            v = tk.Label(kpi_frame, text="-", anchor="e", width=14, font=("Consolas", 9, "bold"))
            v.grid(row=i, column=1, sticky="e", padx=5, pady=2)
            self.kpi_labels[key] = v

        # Plot area - use FigureCanvasTkAgg
        plot_frame = tk.LabelFrame(tab_mc, text="Equity curves and distribution", padx=5, pady=5)
        plot_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.figure = plt.Figure(figsize=(9, 5), dpi=100)
        self.ax_equity = self.figure.add_subplot(121)
        self.ax_hist = self.figure.add_subplot(122)
        plt.style.use('dark_background')

        self.canvas = FigureCanvasTkAgg(self.figure, master=plot_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # Monthly projection area (scrollable horizontally)
        monthly_frame = tk.LabelFrame(tab_mc, text="Projected Monthly Returns (by year) - Average Simulation", padx=5,
                                      pady=5)
        monthly_frame.pack(fill=tk.BOTH, expand=False, padx=10, pady=5)

        self.monthly_canvas = tk.Canvas(monthly_frame, height=220)
        self.monthly_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.monthly_scroll_x = tk.Scrollbar(monthly_frame, orient=tk.HORIZONTAL, command=self.monthly_canvas.xview)
        self.monthly_scroll_x.pack(side=tk.BOTTOM, fill=tk.X)
        self.monthly_canvas.configure(xscrollcommand=self.monthly_scroll_x.set)

        self.monthly_inner = tk.Frame(self.monthly_canvas)
        self.monthly_canvas.create_window((0, 0), window=self.monthly_inner, anchor="nw")
        self.monthly_inner.bind("<Configure>",
                                lambda e: self.monthly_canvas.configure(scrollregion=self.monthly_canvas.bbox("all")))

        # Console log for MC
        self.mc_console = scrolledtext.ScrolledText(tab_mc, wrap=tk.WORD, font=("Consolas", 9), height=8)
        self.mc_console.pack(fill=tk.BOTH, expand=False, padx=10, pady=5)

    def browse_file(self):
        filepath = filedialog.askopenfilename(filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")])
        if filepath:
            self.filepath_var.set(filepath)

    def log(self, message, console=None):
        if console is None:
            console = self.console
        console.insert(tk.END, message + "\n")
        console.see(tk.END)
        self.root.update()

    # ----------------------------------------------------------
    # Load, filter and compute R-multiples (reused by both tabs)
    # ----------------------------------------------------------
    def load_and_filter_data(self):
        """Load CSV, apply Account and Grade filters, compute R-multiples.
        Returns (df_filtered, original_risk_dollar) or (None, None) on failure."""
        input_path = self.filepath_var.get()
        if not os.path.exists(input_path):
            messagebox.showerror("Error", f"File not found: {input_path}")
            return None, None

        try:
            df = pd.read_csv(input_path)

            # Clean strings from Notion links
            for col in df.columns:
                if df[col].dtype == object:
                    df[col] = df[col].apply(clean_numeric_string)

            # Keep only BACKTEST 2 account if column present
            if 'Account' in df.columns:
                mask = df['Account'].astype(str).str.contains('BACKTEST 2', case=False, na=False)
                df = df[mask]
                if df.empty:
                    self.log("ERROR: No trades found with Account == BACKTEST 2.", self.console)
                    return None, None
            else:
                self.log("WARNING: 'Account' column not found. Proceeding without account filter.", self.console)

            # Filter by Setup Grade
            if 'Setup Grade' in df.columns:
                selected_grades = [g for g, var in self.grade_vars.items() if var.get()]
                df = df[df['Setup Grade'].isin(selected_grades)]
                if df.empty:
                    self.log("ERROR: No trades with selected Setup Grades.", self.console)
                    return None, None

            # Extract Net PnL (original, unscaled)
            if 'Net PnL' not in df.columns:
                self.log("ERROR: 'Net PnL' column missing.", self.console)
                return None, None
            df['Net PnL_original'] = df['Net PnL'].apply(extract_pnl)
            df = df.dropna(subset=['Net PnL_original'])

            # Compute original risk per trade in dollars
            old_bal = self.old_balance_var.get()
            old_r_pct = self.old_risk_var.get()
            self.original_risk_dollar = old_bal * (old_r_pct / 100.0)
            if self.original_risk_dollar <= 0:
                self.log("ERROR: Original risk per trade must be > 0.", self.console)
                return None, None

            # R-multiple = PnL / original_risk_dollar
            df['R_multiple'] = df['Net PnL_original'] / self.original_risk_dollar
            return df, self.original_risk_dollar

        except Exception as e:
            self.log(f"Error loading data: {str(e)}", self.console)
            return None, None

    # ----------------------------------------------------------
    # Original analysis (scaled to new balance/risk)
    # ----------------------------------------------------------
    def run_analysis(self):
        self.console.delete(1.0, tk.END)
        self.log("--- Loading and filtering data ---")
        df, orig_risk_dollar = self.load_and_filter_data()
        if df is None:
            return

        # Scale Net PnL to new balance/risk
        old_risk_dollar = self.original_risk_dollar
        new_bal = self.new_balance_var.get()
        new_r_pct = self.new_risk_var.get()
        new_risk_dollar = new_bal * (new_r_pct / 100.0)
        multiplier = new_risk_dollar / old_risk_dollar
        df['Net PnL_scaled'] = df['Net PnL_original'] * multiplier

        self.log(f"Original risk per trade: ${old_risk_dollar:.2f}")
        self.log(f"New risk per trade: ${new_risk_dollar:.2f}")
        self.log(f"PnL scaling multiplier: {multiplier:.4f}\n")

        # Basic stats on scaled PnL
        net = df['Net PnL_scaled']
        total_pnl = net.sum()
        total_trades = len(df)
        wins = (net > 0).sum()
        losses = (net < 0).sum()
        breakeven = (net == 0).sum()
        win_rate = wins / total_trades if total_trades else 0
        avg_win = net[net > 0].mean() if wins else 0
        avg_loss = net[net < 0].mean() if losses else 0
        profit_factor = (net[net > 0].sum() / abs(net[net < 0].sum())) if losses else np.inf

        self.log("==== Trading KPIs (Scaled to New Parameters) ====")
        self.log(f"Total Trades: {total_trades}")
        self.log(f"Total Net PnL: ${total_pnl:.2f}")
        self.log(f"Wins: {wins}, Losses: {losses}, Breakeven: {breakeven}")
        self.log(f"Win Rate: {win_rate * 100:.2f}%")
        self.log(f"Average Win: ${avg_win:.2f}")
        self.log(f"Average Loss: ${avg_loss:.2f}")
        self.log(f"Profit Factor: {profit_factor:.2f}")
        self.log(f"Expectancy per trade: ${(win_rate * avg_win + (1 - win_rate) * avg_loss):.2f}")

        # Save filtered data for later Monte Carlo (R-multiples)
        self.filtered_df = df
        self.r_multiples = df['R_multiple'].values
        self.log("\nData ready for Monte Carlo simulation (R-multiples computed).")

    # ----------------------------------------------------------
    # Monte Carlo simulation (new functionality)
    # ----------------------------------------------------------
    def run_monte_carlo(self):
        """
        Robust Monte Carlo run that:
        - computes per-trade $ pnl and per-trade percent returns (pnl / balance_before *100)
        - calculates ROI, average per-trade gain %, median/percentiles, blow-up probability for 10% loss
        - optionally aggregates trades into a calendar of days (trading_days_per_month)
        - fills KPI labels reliably and writes CSVs to monte_carlo_outputs/
        """
        import math
        from pathlib import Path

        self.mc_console.delete(1.0, tk.END)
        if self.r_multiples is None or len(self.r_multiples) == 0:
            self.log("No R-multiples available. Please run 'Run Historical Analysis' first.", self.mc_console)
            return

        # Parameters
        start_bal = float(self.mc_start_balance.get())
        risk_pct = float(self.mc_risk_per_trade.get())
        n_sim = int(self.mc_num_simulations.get())
        n_trades = int(self.mc_num_trades.get())
        trades_per_month = int(self.mc_trades_per_month.get())
        trading_days_per_month = int(getattr(self, "mc_trading_days_per_month", tk.IntVar(value=20)).get())

        if start_bal <= 0 or risk_pct <= 0 or n_trades <= 0 or n_sim <= 0:
            self.log("Starting balance, risk %, number of trades and number of simulations must be positive.",
                     self.mc_console)
            return

        self.log(f"Running {n_sim} sims × {n_trades} trades (start ${start_bal:,.0f}, risk {risk_pct}%)")
        rng = np.random.default_rng()

        # Pre-allocate arrays
        equity_curves = np.empty((n_sim, n_trades + 1), dtype=float)
        per_trade_pnls = np.empty((n_sim, n_trades), dtype=float)
        per_trade_pct = np.empty((n_sim, n_trades), dtype=float)  # pnl / balance_before * 100
        hit_blowup = np.zeros(n_sim, dtype=bool)
        blowup_first_trade_idx = np.full(n_sim, -1, dtype=int)

        blowup_threshold = start_bal * (1.0 - 0.10)  # 10% loss threshold

        # Simulate
        for s in range(n_sim):
            bal = start_bal
            equity_curves[s, 0] = bal
            trades_r = rng.choice(self.r_multiples, size=n_trades, replace=True)
            # fixed risk amount based on starting balance (if user selected fixed mode)
            fixed_risk_amount = start_bal * (risk_pct / 100.0)
            for t_idx, r in enumerate(trades_r):
                bal_before = bal
                if getattr(self, 'mc_use_initial_for_risk', None) and self.mc_use_initial_for_risk.get():
                    risk_amount = fixed_risk_amount
                else:
                    risk_amount = bal_before * (risk_pct / 100.0)
                pnl = r * risk_amount
                bal = bal_before + pnl
                per_trade_pnls[s, t_idx] = pnl
                # per-trade percent relative to account before trade:
                per_trade_pct[s, t_idx] = 100.0 * pnl / bal_before if bal_before != 0 else 0.0
                equity_curves[s, t_idx + 1] = bal
                # blow-up check (first time)
                if (not hit_blowup[s]) and (bal <= blowup_threshold):
                    hit_blowup[s] = True
                    blowup_first_trade_idx[s] = t_idx + 1

        final_balances = equity_curves[:, -1]

        # Basic summary stats
        mean_final = float(np.mean(final_balances))
        median_final = float(np.median(final_balances))
        roi = (mean_final - start_bal) / start_bal * 100.0
        p5, p95 = np.percentile(final_balances, [5, 95])
        best_idx = int(np.argmax(final_balances))
        worst_idx = int(np.argmin(final_balances))
        best_curve = equity_curves[best_idx]
        worst_curve = equity_curves[worst_idx]
        avg_curve = np.mean(equity_curves, axis=0)

        # Max drawdown across sims
        max_dd_pct = 0.0
        max_dd_dollar = 0.0
        for curve in equity_curves:
            dd_pct, dd_dollar = MonteCarloSimulator.compute_drawdown_stats(curve)
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct
                max_dd_dollar = dd_dollar

        # Avg gain per trade as mean of per_trade_pct across all sims/trades (robust)
        valid_pct_mask = np.isfinite(per_trade_pct)
        if valid_pct_mask.sum() > 0:
            avg_gain_pct = float(np.nanmean(per_trade_pct[valid_pct_mask]))
        else:
            avg_gain_pct = 0.0

        # Profitable / losing trades (average per simulation)
        wins_per_sim = np.sum(per_trade_pnls > 0, axis=1)
        losses_per_sim = np.sum(per_trade_pnls < 0, axis=1)
        avg_profitable = float(np.mean(wins_per_sim))
        avg_losing = float(np.mean(losses_per_sim))

        # Blow-up statistics
        prob_ever_blow = float(np.mean(hit_blowup))
        prob_end_below_90pct = float(np.mean(final_balances <= blowup_threshold))
        blowup_times = blowup_first_trade_idx[hit_blowup]
        median_blowup_time = int(np.median(blowup_times)) if len(blowup_times) > 0 else None

        # Log summary
        self.log("==== MONTE CARLO RESULTS ====")
        self.log(f"Mean final balance: ${mean_final:,.2f}  Median final: ${median_final:,.2f}")
        self.log(f"ROI (mean final vs start): {roi:.2f}%   90% CI of finals: [${p5:,.2f}, ${p95:,.2f}]")
        self.log(f"Probability EVER <= -10% (blow-up): {prob_ever_blow * 100:.3f}%")
        self.log(f"Probability END below -10%: {prob_end_below_90pct * 100:.3f}%")
        if median_blowup_time is not None:
            self.log(f"Median blowup time (trade index among blown sims): {median_blowup_time}")

        # Update KPI labels reliably
        self.kpi_labels["account_start"].config(text=f"${start_bal:,.2f}")
        self.kpi_labels["avg_gain_pct"].config(text=f"{avg_gain_pct:.2f}%")
        self.kpi_labels["end_balance"].config(text=f"${mean_final:,.2f}")
        self.kpi_labels["roi_pct"].config(text=f"{roi:.2f}%")
        self.kpi_labels["n_trades"].config(text=f"{n_trades}")
        self.kpi_labels["profitable_trades"].config(text=f"{avg_profitable:.1f} (avg/sim)")
        self.kpi_labels["losing_trades"].config(text=f"{avg_losing:.1f} (avg/sim)")
        self.kpi_labels["max_dd_dollar"].config(text=f"${max_dd_dollar:,.2f}")
        self.kpi_labels["max_dd_pct"].config(text=f"{max_dd_pct:.2f}%")

        # Calendar / daily aggregation (optional) — same approach as earlier: allocate trades to days via multinomial
        months_needed = int(math.ceil(n_trades / max(1, trades_per_month)))
        total_days = months_needed * trading_days_per_month
        day_counts_all = np.zeros((n_sim, total_days), dtype=int)
        daily_pnls = np.zeros((n_sim, total_days), dtype=float)
        daily_is_loss = np.zeros((n_sim, total_days), dtype=int)
        for s in range(n_sim):
            day_counts = rng.multinomial(n_trades, [1.0 / total_days] * total_days)
            day_counts_all[s] = day_counts
            tpos = 0
            for d in range(total_days):
                c = day_counts[d]
                if c == 0:
                    continue
                chunk = per_trade_pnls[s, tpos:tpos + c]
                daily_pnls[s, d] = float(chunk.sum())
                daily_is_loss[s, d] = 1 if daily_pnls[s, d] < 0 else 0
                tpos += c

        avg_daily_pnl = daily_pnls.mean(axis=0)
        prob_no_trade_by_day = (day_counts_all == 0).mean(axis=0)
        prob_day_is_loss = (daily_is_loss).mean(axis=0)
        avg_trades_per_day = day_counts_all.mean(axis=0)

        # Save CSVs
        out_dir = Path("monte_carlo_outputs")
        out_dir.mkdir(exist_ok=True)
        # daily calendar averages
        rows = []
        month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        for d in range(total_days):
            month_idx = (d // trading_days_per_month) + 1
            day_of_month = (d % trading_days_per_month) + 1
            rows.append({
                "MonthIndex": month_idx,
                "DayOfMonth": day_of_month,
                "DayIndex": d + 1,
                "Avg_PnL_$": avg_daily_pnl[d],
                "Avg_Trades": avg_trades_per_day[d],
                "Prob_No_Trades": prob_no_trade_by_day[d],
                "Prob_Day_Is_Loss": prob_day_is_loss[d]
            })
        day_df = pd.DataFrame(rows)
        day_df.to_csv(out_dir / "daily_calendar_averages.csv", index=False)
        self.log(f"Daily averages saved to {out_dir / 'daily_calendar_averages.csv'}", self.mc_console)

        # simulation summary
        sim_summary = pd.DataFrame({
            "final_balance": final_balances,
            "ever_blow": hit_blowup.astype(int),
            "blow_trade_index": blowup_first_trade_idx
        })
        sim_summary.to_csv(out_dir / "simulation_summaries.csv", index=False)
        self.log(f"Per-simulation summary saved to {out_dir / 'simulation_summaries.csv'}", self.mc_console)

        # Plot with existing function
        self.plot_equity_and_hist(equity_curves, best_curve, worst_curve, avg_curve, start_bal)

        # Call the updated monthly tables logic here. (Make sure this relies on a proper 'monthly' list).
        # We need a proper representation of the monthly returns to pass in here.
        # (Assuming you generate a 'monthly' array of tuples somewhere previously in the class).
        # self.build_monthly_year_tables(monthly_data, out_dir)

    def plot_equity_and_hist(self, equity_curves, best_curve, worst_curve, avg_curve, start_bal):
        self.ax_equity.clear()
        self.ax_hist.clear()

        # Plot many thin grey curves
        n_sim, n_points = equity_curves.shape
        for i in range(n_sim):
            self.ax_equity.plot(equity_curves[i], color='gray', linewidth=0.8, alpha=0.25)

        # Important highlighted curves
        self.ax_equity.plot(worst_curve, label="Worst Case", color="red", linewidth=1.8)
        self.ax_equity.plot(avg_curve, label="Average Case", color="dodgerblue", linewidth=2.2)
        self.ax_equity.plot(best_curve, label="Best Case", color="limegreen", linewidth=1.8)

        self.ax_equity.set_title("Monte Carlo Trading Sim — Equity Curves")
        self.ax_equity.set_xlabel("Number of Trades")
        self.ax_equity.set_ylabel("Account Balance ($)")
        self.ax_equity.grid(True, alpha=0.25)
        self.ax_equity.legend(loc="upper left", fontsize='small')

        # Histogram
        final_balances = equity_curves[:, -1]
        self.ax_hist.hist(final_balances, bins=50, color='tab:gray', edgecolor='black', alpha=0.7)
        self.ax_hist.axvline(start_bal, color='red', linestyle='--', label=f"Start: ${start_bal:,.0f}")
        self.ax_hist.axvline(np.mean(final_balances), color='blue', linestyle='--',
                             label=f"Mean: ${np.mean(final_balances):,.0f}")
        self.ax_hist.set_title("Distribution of Final Balances")
        self.ax_hist.set_xlabel("Final Balance ($)")
        self.ax_hist.set_ylabel("Frequency")
        self.ax_hist.legend(fontsize='small')
        self.ax_hist.grid(True, alpha=0.25)

        self.figure.tight_layout()
        self.canvas.draw()

    def build_monthly_year_tables(self, monthly, out_dir):
        # Clear previous children in monthly_inner
        for child in self.monthly_inner.winfo_children():
            child.destroy()

        # Determine number of years
        n_months = len(monthly)
        n_years = math.ceil(n_months / 12)

        # For each year, create a frame with Treeview
        month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        for y in range(n_years):
            year_frame = tk.Frame(self.monthly_inner, bd=1, relief=tk.RAISED)
            year_frame.grid(row=0, column=y, padx=6, pady=6)

            year_label = tk.Label(year_frame, text=f"Year {y + 1}", bg="#2c7bd9", fg="white", width=18)
            year_label.pack(fill=tk.X)

            cols = ("Month", "Return %", "Results $")
            tree = ttk.Treeview(year_frame, columns=cols, show='headings', height=13)
            for c in cols:
                tree.heading(c, text=c)
                tree.column(c, anchor="center", width=110)
            tree.pack()

            # Add months for this year
            start_idx = y * 12
            for m in range(12):
                idx = start_idx + m
                if idx >= n_months:
                    break
                pct, profit = monthly[idx]
                pct_text = f"{pct:.1f}%"
                profit_text = f"${profit:,.0f}"
                tag = "pos" if pct >= 0 else "neg"
                tree.insert("", "end", values=(month_names[m], pct_text, profit_text), tags=(tag,))

            # Add total row for the year
            year_months = monthly[start_idx:start_idx + 12]
            if len(year_months) > 0:
                # FIX: Use geometric compounding for percentages instead of summing
                compounded = 1.0
                for p, _ in year_months:
                    compounded *= (1 + (p / 100.0))
                total_pct = (compounded - 1.0) * 100.0

                total_dollar = sum([d for _, d in year_months])
                tree.insert("", "end", values=("Total", f"{total_pct:.1f}%", f"${total_dollar:,.0f}"), tags=("total",))

            # Tag styling
            tree.tag_configure("pos", foreground="green")
            tree.tag_configure("neg", foreground="red")
            tree.tag_configure("total", background="#2f5597", foreground="white")

        # Save a nicely-formatted CSV (yearly split)
        rows = []
        for i, (pct, profit) in enumerate(monthly):
            rows.append({"MonthIndex": i + 1, "Month": month_names[(i % 12)], "Return_%": pct, "Profit_$": profit,
                         "Year": (i // 12) + 1})
        monthly_by_year_df = pd.DataFrame(rows)
        monthly_by_year_df.to_csv(out_dir / "monthly_projection_by_year.csv", index=False)
        self.log(f"Monthly-by-year CSV saved to {out_dir / 'monthly_projection_by_year.csv'}", self.mc_console)


# --------------------------------------------------------------
# Run GUI
# --------------------------------------------------------------
if __name__ == "__main__":
    root = tk.Tk()
    app = TradingStatsApp(root)
    root.mainloop()