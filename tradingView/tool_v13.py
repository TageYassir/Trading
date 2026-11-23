import customtkinter as ctk
from tkinter import ttk, messagebox, filedialog
from tvDatafeed import TvDatafeed, Interval
import pandas as pd
import re
import urllib.parse
import threading
import time
from datetime import datetime
import os

# Set appearance mode and color theme
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# Global variables for streaming
streaming = False
stream_thread = None


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
        show_data(df, symbol, exchange)
        status_label.configure(text=f"Data loaded for {exchange}:{symbol}")

        # Enable save button
        save_btn.configure(state="normal")

    except Exception as e:
        messagebox.showerror("Error", f"Failed to fetch data: {e}")
        status_label.configure(text="Error occurred")


def show_data(df: pd.DataFrame, symbol: str, exchange: str):
    # Clear old data
    for row in tree.get_children():
        tree.delete(row)

    # Update details frame
    update_details(df, symbol, exchange)

    # Insert new rows with alternating colors
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
    """Update the details frame with comprehensive information"""
    if df.empty:
        return

    # Clear previous details
    for widget in details_frame.winfo_children():
        widget.destroy()

    # Current price details
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else latest

    price_change = latest['close'] - prev['close']
    percent_change = (price_change / prev['close']) * 100 if prev['close'] != 0 else 0

    # Create details labels
    ctk.CTkLabel(details_frame, text=f"Symbol: {symbol}",
                 font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, sticky="w", padx=5, pady=2)
    ctk.CTkLabel(details_frame, text=f"Exchange: {exchange}").grid(row=0, column=1, sticky="w", padx=5, pady=2)

    ctk.CTkLabel(details_frame, text=f"Latest Price: {latest['close']:.4f}",
                 font=ctk.CTkFont(weight="bold")).grid(row=1, column=0, sticky="w", padx=5, pady=2)

    change_color = "#3BB273" if price_change >= 0 else "#C73E1D"
    ctk.CTkLabel(details_frame, text=f"Change: {price_change:+.4f} ({percent_change:+.2f}%)",
                 text_color=change_color).grid(row=1, column=1, sticky="w", padx=5, pady=2)

    ctk.CTkLabel(details_frame, text=f"Open: {latest['open']:.4f}").grid(row=2, column=0, sticky="w", padx=5, pady=2)
    ctk.CTkLabel(details_frame, text=f"High: {latest['high']:.4f}").grid(row=2, column=1, sticky="w", padx=5, pady=2)

    ctk.CTkLabel(details_frame, text=f"Low: {latest['low']:.4f}").grid(row=3, column=0, sticky="w", padx=5, pady=2)
    volume_text = f"Volume: {latest['volume']:.0f}" if pd.notna(latest['volume']) else "Volume: N/A"
    ctk.CTkLabel(details_frame, text=volume_text).grid(row=3, column=1, sticky="w", padx=5, pady=2)

    # Statistics
    ctk.CTkLabel(details_frame, text="Statistics:",
                 font=ctk.CTkFont(weight="bold")).grid(row=4, column=0, sticky="w", padx=5, pady=(10, 2))

    ctk.CTkLabel(details_frame, text=f"Period High: {df['high'].max():.4f}").grid(row=5, column=0, sticky="w", padx=5,
                                                                                  pady=2)
    ctk.CTkLabel(details_frame, text=f"Period Low: {df['low'].min():.4f}").grid(row=5, column=1, sticky="w", padx=5,
                                                                                pady=2)

    avg_volume = df['volume'].mean()
    avg_volume_text = f"Avg Volume: {avg_volume:.0f}" if pd.notna(avg_volume) else "Avg Volume: N/A"
    ctk.CTkLabel(details_frame, text=avg_volume_text).grid(row=6, column=0, sticky="w", padx=5, pady=2)
    ctk.CTkLabel(details_frame, text=f"Total Bars: {len(df)}").grid(row=6, column=1, sticky="w", padx=5, pady=2)


def save_to_file():
    """Save the current data to a CSV file"""
    if not tree.get_children():
        messagebox.showwarning("Warning", "No data to save")
        return

    # Get file path from user
    file_path = filedialog.asksaveasfilename(
        defaultextension=".csv",
        filetypes=[("CSV files", "*.csv"), ("Text files", "*.txt"), ("All files", "*.*")],
        title="Save data to file"
    )

    if not file_path:
        return  # User canceled

    try:
        # Get exchange and symbol from details if available
        symbol = "Unknown"
        exchange = "Unknown"

        # Try to extract from details frame
        for widget in details_frame.winfo_children():
            if isinstance(widget, ctk.CTkLabel):
                text = widget.cget("text")
                if text.startswith("Symbol:"):
                    symbol = text.split(":")[1].strip()
                elif text.startswith("Exchange:"):
                    exchange = text.split(":")[1].strip()

        # Prepare data for saving
        with open(file_path, 'w') as f:
            f.write(f"TradingView Data Export\n")
            f.write(f"Symbol: {symbol}\n")
            f.write(f"Exchange: {exchange}\n")
            f.write(f"Exported on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 50 + "\n\n")

            # Write column headers with commas
            headers = [tree.heading(col)["text"] for col in tree["columns"]]
            f.write(",".join(headers) + "\n")

            # Write data rows - convert all values to strings
            for row_id in tree.get_children():
                values = tree.item(row_id)["values"]
                # Convert all values to strings before joining with commas
                str_values = [str(value) for value in values]
                f.write(",".join(str_values) + "\n")

            # Add summary statistics if available
            if details_frame.winfo_children():
                f.write("\n" + "=" * 50 + "\n")
                f.write("SUMMARY STATISTICS\n")
                f.write("=" * 50 + "\n")

                for widget in details_frame.winfo_children():
                    if isinstance(widget, ctk.CTkLabel):
                        text = widget.cget("text")
                        f.write(text + "\n")

        status_label.configure(text=f"Data saved to {os.path.basename(file_path)}")
        messagebox.showinfo("Success", f"Data successfully saved to {file_path}")

    except Exception as e:
        messagebox.showerror("Error", f"Failed to save file: {e}")


def toggle_stream():
    """Toggle real-time data streaming"""
    global streaming, stream_thread

    if not streaming:
        # Start streaming
        link = link_entry.get().strip()
        if not link:
            messagebox.showerror("Error", "Please enter a TradingView link first")
            return

        exchange, symbol = parse_tv_link(link)
        if not exchange or not symbol:
            messagebox.showerror("Error", "Invalid TradingView link")
            return

        streaming = True
        stream_btn.configure(text="Stop Streaming", fg_color="#C73E1D", hover_color="#A23B72")
        status_label.configure(text=f"Streaming data for {exchange}:{symbol}")

        # Start streaming in a separate thread
        stream_thread = threading.Thread(target=stream_data, args=(exchange, symbol), daemon=True)
        stream_thread.start()

    else:
        # Stop streaming
        streaming = False
        stream_btn.configure(text="Start Streaming", fg_color="#3BB273", hover_color="#2E86AB")
        status_label.configure(text="Streaming stopped")


def stream_data(exchange, symbol):
    """Stream real-time data in the background"""
    tv = TvDatafeed()
    refresh_interval = 60  # seconds

    while streaming:
        try:
            # Fetch latest data
            df = tv.get_hist(symbol=symbol, exchange=exchange,
                             interval=Interval.in_1_hour, n_bars=10)  # Just get recent data for streaming

            if df is not None and not df.empty:
                df = df.reset_index()

                # Update UI in the main thread
                root.after(0, lambda: update_streaming_data(df, symbol, exchange))

            # Wait for the next update
            time.sleep(refresh_interval)

        except Exception as e:
            print(f"Streaming error: {e}")
            time.sleep(refresh_interval)


def update_streaming_data(df: pd.DataFrame, symbol: str, exchange: str):
    """Update the UI with new streaming data"""
    if not streaming:
        return

    # Update the treeview
    for row in tree.get_children():
        tree.delete(row)

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

    # Update details
    update_details(df, symbol, exchange)
    status_label.configure(text=f"Streaming {exchange}:{symbol} - Last update: {datetime.now().strftime('%H:%M:%S')}")


# ---------------- UI Setup ---------------- #
root = ctk.CTk()
root.title("TradingView Data Loader with Streaming")
root.geometry("1200x800")

# Configure grid
root.grid_columnconfigure(0, weight=1)
root.grid_rowconfigure(2, weight=1)

# Header frame
header_frame = ctk.CTkFrame(root, fg_color="#2E86AB", corner_radius=0)
header_frame.grid(row=0, column=0, sticky="ew", padx=0, pady=0)
header_frame.grid_columnconfigure(1, weight=1)

title_label = ctk.CTkLabel(header_frame, text="TradingView Data Loader with Streaming",
                           font=ctk.CTkFont(size=20, weight="bold"),
                           text_color="white")
title_label.grid(row=0, column=0, padx=20, pady=15)

# Input frame
input_frame = ctk.CTkFrame(root, fg_color="#2c3e50")
input_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=10)
input_frame.grid_columnconfigure(1, weight=1)

# Link entry
link_label = ctk.CTkLabel(input_frame, text="TradingView Link:",
                          font=ctk.CTkFont(weight="bold"))
link_label.grid(row=0, column=0, sticky="w", padx=10, pady=10)

link_entry = ctk.CTkEntry(input_frame, placeholder_text="Paste TradingView link here...",
                          width=500, height=35)
link_entry.grid(row=0, column=1, padx=10, pady=10, sticky="ew")

fetch_btn = ctk.CTkButton(input_frame, text="Fetch Data", command=fetch_data,
                          height=35, width=120, fg_color="#A23B72", hover_color="#8A2C5B")
fetch_btn.grid(row=0, column=2, padx=5, pady=10)

stream_btn = ctk.CTkButton(input_frame, text="Start Streaming", command=toggle_stream,
                           height=35, width=120, fg_color="#3BB273", hover_color="#2E86AB")
stream_btn.grid(row=0, column=3, padx=5, pady=10)

save_btn = ctk.CTkButton(input_frame, text="Save to File", command=save_to_file,
                         height=35, width=120, fg_color="#F18F01", hover_color="#C76B15",
                         state="disabled")
save_btn.grid(row=0, column=4, padx=5, pady=10)

# Details frame
details_frame = ctk.CTkFrame(root, fg_color="#34495e", height=120)
details_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))
details_frame.grid_columnconfigure(0, weight=1)
details_frame.grid_columnconfigure(1, weight=1)

# Table frame
table_frame = ctk.CTkFrame(root)
table_frame.grid(row=3, column=0, sticky="nsew", padx=10, pady=(0, 10))
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
status_frame.grid(row=4, column=0, sticky="ew", padx=0, pady=0)
status_frame.grid_columnconfigure(0, weight=1)

status_label = ctk.CTkLabel(status_frame, text="Ready to fetch data",
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


# Start the application
root.mainloop()