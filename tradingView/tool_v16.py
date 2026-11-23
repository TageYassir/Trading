import customtkinter as ctk
from tkinter import ttk, messagebox

from matplotlib.backends._backend_tk import NavigationToolbar2Tk
from tvDatafeed import TvDatafeed, Interval
import pandas as pd
import re
import urllib.parse
from datetime import datetime
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import mplfinance as mpf

# Set appearance mode and color theme
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# Interval mapping
INTERVAL_MAP = {
    "1 Minute": Interval.in_1_minute,
    "5 Minutes": Interval.in_5_minute,
    "15 Minutes": Interval.in_15_minute,
    "30 Minutes": Interval.in_30_minute,
    "1 Hour": Interval.in_1_hour,
    "2 Hours": Interval.in_2_hour,
    "4 Hours": Interval.in_4_hour,
    "1 Day": Interval.in_daily,
    "1 Week": Interval.in_weekly,
    "1 Month": Interval.in_monthly
}

# ----------------- Data Handling ----------------- #
def parse_tv_link(link: str):
    """Parse TradingView link to extract exchange and symbol."""
    if "symbol=" in link:
        query = link.split("symbol=")[-1]
        decoded = urllib.parse.unquote(query)
        if ":" in decoded:
            exchange, symbol = decoded.split(":", 1)
            return exchange.upper(), symbol.upper()
        else:
            return "FX_IDC", decoded.upper()

    match = re.search(r"/symbols/([^/]+)/?", link)
    if match:
        raw = match.group(1)
        if "-" in raw:
            parts = raw.split("-")
            exchange = parts[0]
            symbol = "-".join(parts[1:])
            return exchange.upper(), symbol.upper()
        else:
            return "FX_IDC", raw.upper()

    return None, None


def fetch_data():
    link = link_entry.get().strip()
    if not link:
        messagebox.showerror("Error", "Please enter a TradingView link")
        return

    exchange, symbol = parse_tv_link(link)
    if not exchange or not symbol:
        messagebox.showerror("Error", "Invalid TradingView link")
        return

    try:
        interval_key = interval_var.get()
        interval = INTERVAL_MAP.get(interval_key, Interval.in_1_hour)

        try:
            n_bars = int(bars_entry.get())
            if n_bars <= 0:
                raise ValueError("Number of bars must be positive")
            if n_bars > 100000:
                messagebox.showwarning("Warning", "Maximum bars limited to 100,000")
                n_bars = 100000
                bars_entry.delete(0, "end")
                bars_entry.insert(0, "100000")
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid number for bars")
            return

        status_label.configure(text="Fetching data...")
        root.update()

        tv = TvDatafeed()
        df = tv.get_hist(symbol=symbol, exchange=exchange,
                         interval=interval, n_bars=n_bars)
        if df is None or df.empty:
            messagebox.showerror("Error", f"No data fetched for {exchange}:{symbol}")
            status_label.configure(text="Ready")
            return

        df = df.reset_index()
        show_data(df, symbol, exchange)
        status_label.configure(text=f"Data loaded for {exchange}:{symbol} ({interval_key}, {n_bars} bars)")
        save_btn.configure(state="normal")

    except Exception as e:
        messagebox.showerror("Error", f"Failed to fetch data: {e}")
        status_label.configure(text="Error occurred")


def show_data(df: pd.DataFrame, symbol: str, exchange: str):
    for row in tree.get_children():
        tree.delete(row)

    update_details(df, symbol, exchange)

    for i, row in df.iterrows():
        tag = 'even' if i % 2 == 0 else 'odd'
        tree.insert("", "end", values=(
            row['datetime'].strftime("%Y-%m-%d %H:%M"),
            f"{row['open']:.4f}",
            f"{row['high']:.4f}",
            f"{row['low']:.4f}",
            f"{row['close']:.4f}",
            f"{row['volume']:.0f}" if pd.notna(row['volume']) else "N/A"
        ), tags=(tag,))


def update_details(df: pd.DataFrame, symbol: str, exchange: str):
    for widget in details_frame.winfo_children():
        widget.destroy()

    if df.empty:
        return

    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else latest
    price_change = latest['close'] - prev['close']
    percent_change = (price_change / prev['close']) * 100 if prev['close'] != 0 else 0

    ctk.CTkLabel(details_frame, text=f"Symbol: {symbol}", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, sticky="w", padx=5, pady=2)
    ctk.CTkLabel(details_frame, text=f"Exchange: {exchange}").grid(row=0, column=1, sticky="w", padx=5, pady=2)
    ctk.CTkLabel(details_frame, text=f"Latest Price: {latest['close']:.4f}", font=ctk.CTkFont(weight="bold")).grid(row=1, column=0, sticky="w", padx=5, pady=2)
    change_color = "#3BB273" if price_change >= 0 else "#C73E1D"
    ctk.CTkLabel(details_frame, text=f"Change: {price_change:+.4f} ({percent_change:+.2f}%)", text_color=change_color).grid(row=1, column=1, sticky="w", padx=5, pady=2)


# ----------------- Chart Section ----------------- #
current_df = None
current_symbol = ""
current_exchange = ""
chart_frame = None
chart_canvas = None

def plot_chart(chart_type="candle", style="classic", frame=None):
    global chart_canvas, current_df, current_symbol, current_exchange
    if current_df is None or current_df.empty:
        messagebox.showerror("Error", "No data available to plot")
        return

    for widget in frame.winfo_children():
        widget.destroy()

    # Clean DataFrame
    df = current_df.copy()
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True, errors="coerce")
    df = df.dropna(subset=["datetime"])
    df.set_index("datetime", inplace=True)
    df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float})

    # Create figure with mplfinance
    fig, axes = mpf.plot(
        df,
        type=chart_type,
        style=style,
        volume=True,
        title=f"{current_symbol} - {current_exchange} ({interval_var.get()})",
        ylabel="Price",
        ylabel_lower="Volume",
        figsize=(10, 8),
        returnfig=True
    )

    # Embed in Tkinter
    chart_canvas = FigureCanvasTkAgg(fig, master=frame)
    chart_canvas.draw()
    chart_canvas.get_tk_widget().pack(fill="both", expand=True)

    toolbar = NavigationToolbar2Tk(chart_canvas, frame)
    toolbar.update()
    chart_canvas.get_tk_widget().pack(fill="both", expand=True)


def create_chart_tab():
    global chart_frame
    chart_window = ctk.CTkToplevel(root)
    chart_window.title("Chart View")
    chart_window.geometry("1000x700")

    main_frame = ctk.CTkFrame(chart_window)
    main_frame.pack(fill="both", expand=True, padx=10, pady=10)

    control_frame = ctk.CTkFrame(main_frame, height=50)
    control_frame.pack(fill="x", pady=(0, 10))
    control_frame.pack_propagate(False)

    ctk.CTkLabel(control_frame, text="Chart Type:").pack(side="left", padx=(10, 5))
    chart_type_var = ctk.StringVar(value="candle")
    chart_type_combo = ctk.CTkComboBox(control_frame, values=["candle", "line", "ohlc"], variable=chart_type_var, width=100)
    chart_type_combo.pack(side="left", padx=5)

    ctk.CTkLabel(control_frame, text="Style:").pack(side="left", padx=(20, 5))
    style_var = ctk.StringVar(value="classic")
    style_combo = ctk.CTkComboBox(control_frame, values=["classic", "yahoo", "charles", "mike"], variable=style_var, width=120)
    style_combo.pack(side="left", padx=5)

    update_btn = ctk.CTkButton(control_frame, text="Update Chart",
                               command=lambda: plot_chart(chart_type_var.get(), style_var.get(), chart_frame),
                               width=120)
    update_btn.pack(side="right", padx=10)

    chart_frame = ctk.CTkFrame(main_frame)
    chart_frame.pack(fill="both", expand=True)

    return chart_window


def open_chart_window():
    global current_df, current_symbol, current_exchange
    rows = []
    for row_id in tree.get_children():
        values = tree.item(row_id)["values"]
        if values:
            rows.append(values)

    if not rows:
        messagebox.showerror("Error", "No data available to plot. Please fetch data first.")
        return

    df = pd.DataFrame(rows, columns=["datetime", "open", "high", "low", "close", "volume"])
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True, errors="coerce")
    df["open"] = df["open"].astype(float)
    df["high"] = df["high"].astype(float)
    df["low"] = df["low"].astype(float)
    df["close"] = df["close"].astype(float)
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")

    current_df = df
    for widget in details_frame.winfo_children():
        if isinstance(widget, ctk.CTkLabel):
            text = widget.cget("text")
            if text.startswith("Symbol:"):
                current_symbol = text.split(":")[1].strip()
            elif text.startswith("Exchange:"):
                current_exchange = text.split(":")[1].strip()

    chart_window = create_chart_tab()
    plot_chart("candle", "classic", chart_frame)


# ----------------- UI ----------------- #
root = ctk.CTk()
root.title("TradingView Data Loader with Chart")
root.geometry("1200x800")

header_frame = ctk.CTkFrame(root, fg_color="#2E86AB", corner_radius=0)
header_frame.grid(row=0, column=0, sticky="ew")
title_label = ctk.CTkLabel(header_frame, text="TradingView Data Loader with Chart", font=ctk.CTkFont(size=20, weight="bold"), text_color="white")
title_label.grid(row=0, column=0, padx=20, pady=15)

input_frame = ctk.CTkFrame(root, fg_color="#2c3e50")
input_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=10)
input_frame.grid_columnconfigure(1, weight=1)

link_label = ctk.CTkLabel(input_frame, text="TradingView Link:", font=ctk.CTkFont(weight="bold"))
link_label.grid(row=0, column=0, sticky="w", padx=10, pady=10)

link_entry = ctk.CTkEntry(input_frame, placeholder_text="Paste TradingView link here...", width=400, height=35)
link_entry.grid(row=0, column=1, padx=10, pady=10, sticky="ew")

interval_label = ctk.CTkLabel(input_frame, text="Timeframe:", font=ctk.CTkFont(weight="bold"))
interval_label.grid(row=1, column=0, sticky="w", padx=10, pady=5)

interval_var = ctk.StringVar(value="1 Hour")
interval_combo = ctk.CTkComboBox(input_frame, variable=interval_var, values=list(INTERVAL_MAP.keys()), width=120, height=30)
interval_combo.grid(row=1, column=1, sticky="w", padx=10, pady=5)

bars_label = ctk.CTkLabel(input_frame, text="Number of Bars:", font=ctk.CTkFont(weight="bold"))
bars_label.grid(row=1, column=2, sticky="w", padx=10, pady=5)

bars_entry = ctk.CTkEntry(input_frame, placeholder_text="200", width=80, height=30)
bars_entry.insert(0, "200")
bars_entry.grid(row=1, column=3, sticky="w", padx=10, pady=5)

fetch_btn = ctk.CTkButton(input_frame, text="Fetch Data", command=fetch_data, height=35, width=100, fg_color="#A23B72", hover_color="#8A2C5B")
fetch_btn.grid(row=0, column=2, padx=5, pady=10)

save_btn = ctk.CTkButton(input_frame, text="Save to File", command=lambda: None, height=35, width=100, fg_color="#F18F01", hover_color="#C76B15", state="disabled")
save_btn.grid(row=0, column=3, padx=5, pady=10)

chart_btn = ctk.CTkButton(input_frame, text="Open Chart", command=open_chart_window, height=35, width=100, fg_color="#2E86AB", hover_color="#1F618D")
chart_btn.grid(row=0, column=4, padx=5, pady=10)

details_frame = ctk.CTkFrame(root, fg_color="#34495e", height=120)
details_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))
details_frame.grid_columnconfigure(0, weight=1)
details_frame.grid_columnconfigure(1, weight=1)

table_frame = ctk.CTkFrame(root)
table_frame.grid(row=3, column=0, sticky="nsew", padx=10, pady=(0, 10))
table_frame.grid_columnconfigure(0, weight=1)
table_frame.grid_rowconfigure(0, weight=1)

style = ttk.Style()
style.theme_use("clam")
style.configure("Treeview", background="#ECF0F1", foreground="#2C3E50", rowheight=25, fieldbackground="#ECF0F1", font=('Helvetica', 10))
style.configure("Treeview.Heading", background="#2E86AB", foreground="white", padding=5, font=('Helvetica', 11, 'bold'))
style.map('Treeview', background=[('selected', '#3498DB')], foreground=[('selected', 'white')])

columns = ("Datetime", "Open", "High", "Low", "Close", "Volume")
tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=15)
for col in columns:
    tree.heading(col, text=col)
    tree.column(col, width=120, anchor="center")

tree.tag_configure('odd', background='#F8F9F9')
tree.tag_configure('even', background='#E5E8E8')

v_scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
h_scrollbar = ttk.Scrollbar(table_frame, orient="horizontal", command=tree.xview)
tree.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)
tree.grid(row=0, column=0, sticky="nsew")
v_scrollbar.grid(row=0, column=1, sticky="ns")
h_scrollbar.grid(row=1, column=0, sticky="ew")

status_frame = ctk.CTkFrame(root, height=30, corner_radius=0)
status_frame.grid(row=4, column=0, sticky="ew")
status_label = ctk.CTkLabel(status_frame, text="Ready to fetch data", text_color="white", font=ctk.CTkFont(size=12))
status_label.grid(row=0, column=0, sticky="w", padx=10, pady=5)

root.mainloop()
