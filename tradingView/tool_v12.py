import customtkinter as ctk
from tkinter import ttk, messagebox
from tvDatafeed import TvDatafeed, Interval
import pandas as pd
import re
import urllib.parse

# Set appearance mode and color theme
ctk.set_appearance_mode("Dark")  # Modes: "System", "Dark", "Light"
ctk.set_default_color_theme("blue")  # Themes: "blue", "green", "dark-blue"


def parse_tv_link(link: str):
    """
    Parse TradingView link to extract exchange and symbol.
    Works for both ?symbol=FX%3ANAS100 and /symbols/NASDAQ-AAPL/
    """
    # Case 1: link has ?symbol=
    if "symbol=" in link:
        query = link.split("symbol=")[-1]
        decoded = urllib.parse.unquote(query)  # decode %3A to :
        if ":" in decoded:
            exchange, symbol = decoded.split(":", 1)
            return exchange.upper(), symbol.upper()
        else:
            # No exchange, assume FX_IDC
            return "FX_IDC", decoded.upper()

    # Case 2: /symbols/EXCHANGE-SYMBOL/
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
        status_label.configure(text="Fetching data...")
        root.update()

        tv = TvDatafeed()
        df = tv.get_hist(symbol=symbol, exchange=exchange,
                         interval=Interval.in_1_hour, n_bars=200)
        if df is None or df.empty:
            messagebox.showerror("Error", f"No data fetched for {exchange}:{symbol}")
            status_label.configure(text="Ready")
            return

        df = df.reset_index()
        show_data(df)
        status_label.configure(text=f"Data loaded for {exchange}:{symbol}")

    except Exception as e:
        messagebox.showerror("Error", f"Failed to fetch data: {e}")
        status_label.configure(text="Error occurred")


def show_data(df: pd.DataFrame):
    # Clear old data
    for row in tree.get_children():
        tree.delete(row)

    # Insert new rows with alternating colors
    for i, row in df.iterrows():
        tag = 'even' if i % 2 == 0 else 'odd'
        tree.insert("", "end", values=(
            row['datetime'].strftime("%Y-%m-%d %H:%M"),
            row['open'], row['high'], row['low'], row['close'], row['volume']
        ), tags=(tag,))


# ---------------- CustomTkinter UI ---------------- #
root = ctk.CTk()
root.title("TradingView Data Loader")
root.geometry("1000x700")

# Configure grid
root.grid_columnconfigure(0, weight=1)
root.grid_rowconfigure(1, weight=1)

# Header frame
header_frame = ctk.CTkFrame(root, fg_color="#2E86AB", corner_radius=0)
header_frame.grid(row=0, column=0, sticky="ew", padx=0, pady=0)
header_frame.grid_columnconfigure(1, weight=1)

title_label = ctk.CTkLabel(header_frame, text="TradingView Data Loader",
                           font=ctk.CTkFont(size=20, weight="bold"),
                           text_color="white")
title_label.grid(row=0, column=0, padx=20, pady=15)

# Input frame
input_frame = ctk.CTkFrame(root, fg_color="#2c3e50")
input_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
input_frame.grid_columnconfigure(1, weight=1)

# Link entry
link_label = ctk.CTkLabel(input_frame, text="TradingView Link:",
                          font=ctk.CTkFont(weight="bold"))
link_label.grid(row=0, column=0, sticky="w", padx=10, pady=10)

link_entry = ctk.CTkEntry(input_frame, placeholder_text="Paste TradingView link here...",
                          width=500, height=35)
link_entry.grid(row=0, column=1, padx=10, pady=10, sticky="ew")

fetch_btn = ctk.CTkButton(input_frame, text="Fetch Data", command=fetch_data,
                          height=35, width=100, fg_color="#A23B72", hover_color="#8A2C5B")
fetch_btn.grid(row=0, column=2, padx=10, pady=10)

# Sample links
samples_frame = ctk.CTkFrame(input_frame, fg_color="#34495e")
samples_frame.grid(row=1, column=0, columnspan=3, sticky="ew", padx=10, pady=10)
samples_frame.grid_columnconfigure(0, weight=1)

samples_label = ctk.CTkLabel(samples_frame, text="Sample Links:",
                             font=ctk.CTkFont(weight="bold", size=12))
samples_label.grid(row=0, column=0, sticky="w", padx=10, pady=(5, 2))

sample1 = ctk.CTkLabel(samples_frame, text="• https://www.tradingview.com/chart/?symbol=FX%3ANAS100",
                       text_color="#BDC3C7", font=ctk.CTkFont(size=12))
sample1.grid(row=1, column=0, sticky="w", padx=20, pady=2)

sample2 = ctk.CTkLabel(samples_frame, text="• https://www.tradingview.com/symbols/NASDAQ-AAPL/",
                       text_color="#BDC3C7", font=ctk.CTkFont(size=12))
sample2.grid(row=2, column=0, sticky="w", padx=20, pady=(2, 5))

# Table frame
table_frame = ctk.CTkFrame(root)
table_frame.grid(row=2, column=0, sticky="nsew", padx=10, pady=10)
table_frame.grid_columnconfigure(0, weight=1)
table_frame.grid_rowconfigure(0, weight=1)

# Create a style for the treeview
style = ttk.Style()
style.theme_use("clam")

# Configure the treeview colors
style.configure("Treeview",
                background="#ECF0F1",
                foreground="#2C3E50",
                rowheight=25,
                fieldbackground="#ECF0F1",
                font=('Helvetica', 10))

style.configure("Treeview.Heading",
                background="#2E86AB",
                foreground="white",
                padding=5,
                font=('Helvetica', 11, 'bold'))

style.map('Treeview',
          background=[('selected', '#3498DB')],
          foreground=[('selected', 'white')])

# Define rainbow colors for each column
column_colors = {
    "Datetime": "#F18F01",  # Orange
    "Open": "#2E86AB",  # Blue
    "High": "#A23B72",  # Purple
    "Low": "#C73E1D",  # Red
    "Close": "#3BB273",  # Green
    "Volume": "#7768AE"  # Lavender
}

# Create the treeview with columns
columns = ("Datetime", "Open", "High", "Low", "Close", "Volume")
tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=15)

# Configure column headings with colors
for col in columns:
    tree.heading(col, text=col)
    tree.column(col, width=120, anchor="center")
    # Set the heading color
    style.configure(f"Treeview.Heading.{col}",
                    background=column_colors[col],
                    foreground="white")

# Configure tags for alternating row colors
tree.tag_configure('odd', background='#F8F9F9')
tree.tag_configure('even', background='#E5E8E8')

# Add scrollbars
v_scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
h_scrollbar = ttk.Scrollbar(table_frame, orient="horizontal", command=tree.xview)
tree.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)

# Grid the tree and scrollbars
tree.grid(row=0, column=0, sticky="nsew")
v_scrollbar.grid(row=0, column=1, sticky="ns")
h_scrollbar.grid(row=1, column=0, sticky="ew")

# Status bar
status_frame = ctk.CTkFrame(root, height=30, corner_radius=0)
status_frame.grid(row=3, column=0, sticky="ew", padx=0, pady=0)
status_frame.grid_columnconfigure(0, weight=1)

status_label = ctk.CTkLabel(status_frame, text="Ready",
                            text_color="white",
                            font=ctk.CTkFont(size=12))
status_label.grid(row=0, column=0, sticky="w", padx=10, pady=5)

# Apply the column-specific heading styles
for col in columns:
    tree.heading(col, command=lambda _col=col: treeview_sort_column(tree, _col, False))


def treeview_sort_column(tv, col, reverse):
    """Function to sort treeview columns"""
    l = [(tv.set(k, col), k) for k in tv.get_children('')]
    try:
        # Try to convert to float for numerical sorting
        l.sort(key=lambda t: float(t[0].replace(',', '')), reverse=reverse)
    except ValueError:
        # If it fails, do string sorting
        l.sort(reverse=reverse)

    # Rearrange items in sorted positions
    for index, (val, k) in enumerate(l):
        tv.move(k, '', index)

    # Reverse sort next time
    tv.heading(col, command=lambda: treeview_sort_column(tv, col, not reverse))


root.mainloop()