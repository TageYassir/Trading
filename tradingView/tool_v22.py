import customtkinter as ctk
from tkinter import ttk, messagebox
from matplotlib.backends._backend_tk import NavigationToolbar2Tk
from tvDatafeed import TvDatafeed, Interval
import pandas as pd
import re
import urllib.parse
import json
import os
from datetime import datetime
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import mplfinance as mpf
import sys
from pathlib import Path
import numpy as np


# ---------- App Data Directory ----------
def get_app_data_dir():
    if getattr(sys, 'frozen', False):
        if sys.platform == "win32":
            app_data = Path(os.getenv('APPDATA'))
        elif sys.platform == "darwin":
            app_data = Path.home() / "Library" / "Application Support"
        else:
            app_data = Path.home() / ".config"
    else:
        app_data = Path(__file__).parent
    app_dir = app_data / "TradingViewLoader"
    app_dir.mkdir(exist_ok=True, parents=True)
    return app_dir


APP_DATA_DIR = get_app_data_dir()
PREF_FILE = APP_DATA_DIR / "preferences.json"


def load_preferences():
    if PREF_FILE.exists():
        try:
            with open(PREF_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}


def save_preferences(prefs):
    try:
        with open(PREF_FILE, "w") as f:
            json.dump(prefs, f, indent=4)
    except Exception as e:
        print(f"Erreur sauvegarde préférences: {e}")


# ---------- Appearance ----------
ctk.set_appearance_mode("Light")  # Light mode
ctk.set_default_color_theme("blue")  # blue accent


# ---------- Tooltips Helper ----------
def add_tooltip(widget, text):
    def enter(event):
        x = widget.winfo_rootx() + 25
        y = widget.winfo_rooty() + 20
        widget.tooltip = ctk.CTkToplevel(widget)
        widget.tooltip.wm_overrideredirect(True)
        widget.tooltip.wm_geometry(f"+{x}+{y}")
        label = ctk.CTkLabel(widget.tooltip, text=text, justify='left', fg_color="#ffffe0", text_color="#202020")
        label.pack(ipadx=1)

    def leave(event):
        if hasattr(widget, 'tooltip'):
            widget.tooltip.destroy()

    widget.bind('<Enter>', enter)
    widget.bind('<Leave>', leave)


# ---------- Help Window ----------
def show_help():
    help_text = (
        "\nUtilisation rapide :\n"
        "1. Collez le lien TradingView dans le champ prévu.\n"
        "2. Choisissez l'intervalle et le nombre de bougies.\n"
        "3. Cliquez sur 'Télécharger' pour charger les données.\n"
        "4. Utilisez 'Ouvrir le graphique' pour visualiser et sélectionner des bougies.\n"
        "5. Sauvegardez vos sélections ou les données complètes.\n"
        "\nRaccourcis clavier :\n"
        "Ctrl+F : Télécharger\nCtrl+S : Sauvegarder\nCtrl+C : Ouvrir graphique\nEsc : Quitter\n"
    )
    messagebox.showinfo("Aide", help_text)


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


# ---------- Data Handling ----------
def parse_tv_link(link: str):
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
        status_label.configure(text="Veuillez entrer un lien TradingView", text_color="#C73E1D")
        messagebox.showerror("Erreur", "Veuillez entrer un lien TradingView")
        return
    exchange, symbol = parse_tv_link(link)
    if not exchange or not symbol:
        status_label.configure(text="Lien TradingView invalide", text_color="#C73E1D")
        messagebox.showerror("Erreur", "Lien TradingView invalide")
        return
    try:
        interval_key = interval_var.get()
        interval = INTERVAL_MAP.get(interval_key, Interval.in_1_hour)
        n_bars = int(bars_entry.get())
        status_label.configure(text="Téléchargement en cours...", text_color="#2E86AB")
        root.update()
        tv = TvDatafeed()
        df = tv.get_hist(symbol=symbol, exchange=exchange,
                         interval=interval, n_bars=n_bars)
        if df is None or df.empty:
            status_label.configure(text="Aucune donnée trouvée", text_color="#C73E1D")
            messagebox.showerror("Erreur", f"Aucune donnée pour {exchange}:{symbol}")
            return
        df = df.reset_index()
        show_data(df, symbol, exchange)
        status_label.configure(text=f"Chargé {exchange}:{symbol} ({interval_key}, {n_bars} bougies)",
                               text_color="#3BB273")
        save_btn.configure(state="normal")
        prefs = {
            "link": link,
            "interval": interval_key,
            "bars": n_bars,
            "chart_type": chart_type_var.get(),
            "style": style_var.get()
        }
        save_preferences(prefs)
    except Exception as e:
        status_label.configure(text=f"Erreur: {e}", text_color="#C73E1D")
        messagebox.showerror("Erreur", f"Échec: {e}")


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
    if df.empty: return
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else latest
    price_change = latest['close'] - prev['close']
    percent_change = (price_change / prev['close']) * 100 if prev['close'] != 0 else 0
    ctk.CTkLabel(details_frame, text=f"Symbol: {symbol}", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, padx=5,
                                                                                                pady=2, sticky="w")
    ctk.CTkLabel(details_frame, text=f"Exchange: {exchange}").grid(row=0, column=1, padx=5, pady=2, sticky="w")
    ctk.CTkLabel(details_frame, text=f"Latest Price: {latest['close']:.4f}", font=ctk.CTkFont(weight="bold")).grid(
        row=1, column=0, padx=5, pady=2, sticky="w")
    change_color = "#3BB273" if price_change >= 0 else "#C73E1D"
    ctk.CTkLabel(details_frame, text=f"Change: {price_change:+.4f} ({percent_change:+.2f}%)",
                 text_color=change_color).grid(row=1, column=1, padx=5, pady=2, sticky="w")


# ---------- Color Categories ----------
color_categories = []
current_selected_color = None
selected_candles = []
selected_indices = []
marker_lines = []


def add_color_category():
    color_name = color_name_entry.get().strip()
    if not color_name:
        messagebox.showwarning("Warning", "Please enter a category name")
        return

    color_code = color_picker.get()
    if not color_code:
        messagebox.showwarning("Warning", "Please select a color")
        return

    # Check if color name already exists
    for category in color_categories:
        if category["name"] == color_name:
            messagebox.showwarning("Warning", "Category name already exists")
            return

    color_categories.append({
        "name": color_name,
        "color": color_code,
        "selected": False
    })
    update_color_list()
    color_name_entry.delete(0, "end")


def update_color_list():
    for widget in color_list_frame.winfo_children():
        widget.destroy()

    for i, category in enumerate(color_categories):
        frame = ctk.CTkFrame(color_list_frame, fg_color="#f0f0f0")
        frame.pack(fill="x", padx=5, pady=2)

        # Color preview
        color_preview = ctk.CTkFrame(frame, width=20, height=20, fg_color=category["color"])
        color_preview.pack(side="left", padx=5, pady=5)

        # Category name
        name_label = ctk.CTkLabel(frame, text=category["name"])
        name_label.pack(side="left", padx=5, pady=5)

        # Select button
        btn_text = "✓" if category["selected"] else "Select"
        btn_color = "#3BB273" if category["selected"] else "#4a90e2"
        btn = ctk.CTkButton(frame, text=btn_text, width=60, fg_color=btn_color,
                            command=lambda idx=i: select_color_category(idx))
        btn.pack(side="right", padx=5, pady=5)


def select_color_category(index):
    global current_selected_color

    # Deselect all others
    for i in range(len(color_categories)):
        color_categories[i]["selected"] = (i == index)

    current_selected_color = color_categories[index]
    update_color_list()


def delete_color_category():
    if not color_categories:
        return

    # Find selected category
    selected_index = None
    for i, category in enumerate(color_categories):
        if category["selected"]:
            selected_index = i
            break

    if selected_index is not None:
        color_categories.pop(selected_index)
        global current_selected_color
        current_selected_color = None
        update_color_list()


# ---------- Chart Selection ----------
select_mode = False


def toggle_select_mode(btn):
    global select_mode
    select_mode = not select_mode
    if select_mode:
        btn.configure(text="Select Mode: ON", fg_color="#3BB273")
    else:
        btn.configure(text="Select Mode: OFF", fg_color="#C73E1D")


def onclick(event, ax, df, visible_data):
    if not select_mode or current_selected_color is None:
        return
    if event.inaxes != ax or event.xdata is None: return

    # Convert xdata to index in the visible data
    nearest_idx = int(round(event.xdata))
    if nearest_idx < 0 or nearest_idx >= len(visible_data): return

    # Get the actual global index
    global_idx = visible_data.index[nearest_idx]

    # Check if this candle is already selected
    for i, candle in enumerate(selected_candles):
        if candle["global_index"] == global_idx:
            # Update existing selection
            selected_candles[i]["category"] = current_selected_color["name"]
            selected_candles[i]["color"] = current_selected_color["color"]
            # Update marker color
            marker_lines[i].set_color(current_selected_color["color"])
            event.canvas.draw_idle()
            return

    # New selection
    row = df.loc[global_idx]
    selected_candles.append({
        "global_index": global_idx,
        "datetime": str(row.name),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "volume": float(row["volume"]),
        "category": current_selected_color["name"],
        "color": current_selected_color["color"]
    })
    selected_indices.append(global_idx)

    marker, = ax.plot(nearest_idx, row["close"], "o",
                      markersize=8,
                      color=current_selected_color["color"],
                      markeredgecolor="black",
                      markeredgewidth=1,
                      zorder=5)
    marker_lines.append(marker)
    event.canvas.draw_idle()


def delete_last(ax, canvas):
    if not selected_indices: return
    selected_indices.pop()
    selected_candles.pop()
    line = marker_lines.pop()
    line.remove()
    canvas.draw_idle()


def clear_all(ax, canvas):
    selected_indices.clear()
    selected_candles.clear()
    for line in marker_lines: line.remove()
    marker_lines.clear()
    canvas.draw_idle()


def save_selected():
    if not selected_candles:
        messagebox.showinfo("Save", "No candles selected!")
        return

    # Create DataFrame with category column
    save_data = []
    for candle in selected_candles:
        candle_data = candle.copy()
        # Remove internal fields
        candle_data.pop("global_index", None)
        candle_data.pop("color", None)
        save_data.append(candle_data)

    df = pd.DataFrame(save_data)
    fname = APP_DATA_DIR / f"selected_candles_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    try:
        df.to_csv(fname, index=False)
        messagebox.showinfo("Saved", f"Saved {len(selected_candles)} candles to {fname}")
    except Exception as e:
        messagebox.showerror("Erreur", f"Impossible de sauvegarder le fichier: {e}")


def save_all_data():
    rows = [tree.item(r)["values"] for r in tree.get_children()]
    if not rows:
        messagebox.showinfo("Sauvegarde", "Aucune donnée à sauvegarder")
        return
    df = pd.DataFrame(rows, columns=["datetime", "open", "high", "low", "close", "volume"])
    fname = APP_DATA_DIR / f"all_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    try:
        df.to_csv(fname, index=False)
        messagebox.showinfo("Sauvegarde", f"Données sauvegardées dans {fname}")
    except Exception as e:
        messagebox.showerror("Erreur", f"Impossible de sauvegarder le fichier: {e}")


# ---------- Chart ----------
current_df, current_symbol, current_exchange = None, "", ""
chart_frame, chart_canvas = None, None
current_visible_data = None
chunk_size = 200  # Number of bars to display at once
current_chunk = 0
total_chunks = 0


def get_data_chunk(df, chunk_index, chunk_size):
    """Get a chunk of data for display"""
    start_idx = chunk_index * chunk_size
    end_idx = min((chunk_index + 1) * chunk_size, len(df))
    return df.iloc[start_idx:end_idx]


def update_chunk_navigation():
    """Update the chunk navigation buttons state"""
    if total_chunks <= 1:
        prev_btn.configure(state="disabled")
        next_btn.configure(state="disabled")
    else:
        prev_btn.configure(state="normal" if current_chunk > 0 else "disabled")
        next_btn.configure(state="normal" if current_chunk < total_chunks - 1 else "disabled")


def prev_chunk():
    global current_chunk, current_visible_data
    if current_chunk > 0:
        current_chunk -= 1
        current_visible_data = get_data_chunk(current_df, current_chunk, chunk_size)
        plot_chart(chart_type_var.get(), style_var.get(), chart_frame)
        update_chunk_navigation()


def next_chunk():
    global current_chunk, current_visible_data
    if current_chunk < total_chunks - 1:
        current_chunk += 1
        current_visible_data = get_data_chunk(current_df, current_chunk, chunk_size)
        plot_chart(chart_type_var.get(), style_var.get(), chart_frame)
        update_chunk_navigation()


def plot_chart(chart_type="candle", style="classic", frame=None):
    global chart_canvas, current_df, current_visible_data, current_chunk, total_chunks

    if current_df is None or current_df.empty:
        messagebox.showerror("Error", "No data to plot")
        return

    for widget in frame.winfo_children():
        widget.destroy()

    # Calculate chunks
    total_chunks = (len(current_df) + chunk_size - 1) // chunk_size

    # Get current chunk data
    if current_visible_data is None:
        current_chunk = total_chunks - 1  # Start with the most recent data
        current_visible_data = get_data_chunk(current_df, current_chunk, chunk_size)

    df_plot = current_visible_data.copy()

    # Create the plot
    fig, axlist = mpf.plot(
        df_plot, type=chart_type, style=style, volume=True,
        title=f"{current_symbol} - {current_exchange} ({interval_var.get()}) - Chunk {current_chunk + 1}/{total_chunks}",
        ylabel="Price", ylabel_lower="Volume", figsize=(10, 6), returnfig=True
    )

    ax = axlist[0]
    chart_canvas = FigureCanvasTkAgg(fig, master=frame)
    chart_canvas.draw()
    chart_canvas.get_tk_widget().pack(fill="both", expand=True)

    # Custom toolbar with zoom improvements
    toolbar = CustomNavigationToolbar(chart_canvas, frame)
    toolbar.update()

    # Plot existing selections for this chunk
    plot_existing_selections(ax, df_plot)

    # Connect events
    fig.canvas.mpl_connect("button_press_event", lambda e: onclick(e, ax, current_df, current_visible_data))

    # Update navigation buttons
    update_chunk_navigation()


def plot_existing_selections(ax, visible_data):
    """Plot existing selections on the current visible data"""
    for candle in selected_candles:
        if candle["global_index"] in visible_data.index:
            # Find the position in the visible data
            visible_idx = visible_data.index.get_loc(candle["global_index"])
            ax.plot(visible_idx, candle["close"], "o",
                    markersize=8,
                    color=candle["color"],
                    markeredgecolor="black",
                    markeredgewidth=1,
                    zorder=5)


class CustomNavigationToolbar(NavigationToolbar2Tk):
    """Custom toolbar with improved zoom behavior"""

    def __init__(self, canvas, window):
        super().__init__(canvas, window)

    def press_zoom(self, event):
        """Override zoom press to improve performance"""
        if event.inaxes is None:
            return
        if event.button == 1:
            self._button_press = event.x, event.y
        elif event.button == 3:
            self._button_press = event.x, event.y

    def release_zoom(self, event):
        """Override zoom release with better performance"""
        if self._button_press is None or event.inaxes is None:
            return

        startx, starty = self._button_press
        x, y = event.x, event.y

        # Calculate zoom factor
        zoom_factor = 1.2 if event.button == 1 else 1 / 1.2

        # Get current axes limits
        xlim = self.canvas.figure.axes[0].get_xlim()
        ylim = self.canvas.figure.axes[0].get_ylim()

        # Calculate new limits
        x_center = (xlim[0] + xlim[1]) / 2
        y_center = (ylim[0] + ylim[1]) / 2
        x_range = (xlim[1] - xlim[0]) / zoom_factor
        y_range = (ylim[1] - ylim[0]) / zoom_factor

        new_xlim = (x_center - x_range / 2, x_center + x_range / 2)
        new_ylim = (y_center - y_range / 2, y_center + y_range / 2)

        # Apply new limits
        self.canvas.figure.axes[0].set_xlim(new_xlim)
        self.canvas.figure.axes[0].set_ylim(new_ylim)

        # Redraw only what's necessary
        self.canvas.draw_idle()
        self._button_press = None


def open_chart_window():
    global current_df, current_symbol, current_exchange, current_visible_data, current_chunk, total_chunks
    rows = [tree.item(r)["values"] for r in tree.get_children()]
    if not rows:
        messagebox.showerror("Error", "Fetch data first")
        return

    df = pd.DataFrame(rows, columns=["datetime", "open", "high", "low", "close", "volume"])
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True, errors="coerce")
    df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float})

    # Set index for proper plotting
    df.set_index("datetime", inplace=True)
    current_df = df

    # Reset chunk navigation
    current_visible_data = None
    current_chunk = 0

    for w in details_frame.winfo_children():
        if isinstance(w, ctk.CTkLabel):
            t = w.cget("text")
            if t.startswith("Symbol:"): current_symbol = t.split(":")[1].strip()
            if t.startswith("Exchange:"): current_exchange = t.split(":")[1].strip()

    win = ctk.CTkToplevel(root)
    win.title("Chart View - Optimized")
    win.geometry("1300x700")  # More reasonable default size
    win.minsize(1000, 600)  # Minimum size

    # Configure grid for responsiveness
    win.grid_rowconfigure(1, weight=1)
    win.grid_columnconfigure(1, weight=1)
    win.grid_columnconfigure(0, weight=0)

    # Color Panel on the left
    color_panel = ctk.CTkFrame(win, width=250)
    color_panel.grid(row=0, column=0, rowspan=2, sticky="ns", padx=5, pady=5)
    color_panel.grid_propagate(False)

    # Color categories section
    ctk.CTkLabel(color_panel, text="Color Categories", font=ctk.CTkFont(weight="bold")).pack(pady=10)

    # Add category form
    add_frame = ctk.CTkFrame(color_panel)
    add_frame.pack(fill="x", padx=10, pady=5)

    ctk.CTkLabel(add_frame, text="Category Name:").pack(anchor="w")
    global color_name_entry
    color_name_entry = ctk.CTkEntry(add_frame)
    color_name_entry.pack(fill="x", pady=2)

    ctk.CTkLabel(add_frame, text="Select Color:").pack(anchor="w", pady=(10, 0))
    global color_picker
    color_picker = ctk.CTkEntry(add_frame, placeholder_text="Enter hex color or click picker")
    color_picker.pack(fill="x", pady=2)

    # Simple color buttons for quick selection
    color_buttons_frame = ctk.CTkFrame(add_frame)
    color_buttons_frame.pack(fill="x", pady=5)

    common_colors = ["#FF0000", "#00FF00", "#0000FF", "#FFFF00", "#FF00FF", "#00FFFF",
                     "#FFA500", "#800080", "#008000", "#FFC0CB"]

    def set_color(color):
        color_picker.delete(0, "end")
        color_picker.insert(0, color)

    for i in range(0, len(common_colors), 2):
        row_frame = ctk.CTkFrame(color_buttons_frame)
        row_frame.pack(fill="x", pady=1)

        btn1 = ctk.CTkButton(row_frame, text="", width=30, height=30, fg_color=common_colors[i],
                             command=lambda c=common_colors[i]: set_color(c))
        btn1.pack(side="left", padx=2)

        if i + 1 < len(common_colors):
            btn2 = ctk.CTkButton(row_frame, text="", width=30, height=30, fg_color=common_colors[i + 1],
                                 command=lambda c=common_colors[i + 1]: set_color(c))
            btn2.pack(side="left", padx=2)

    add_btn = ctk.CTkButton(add_frame, text="Add Category", command=add_color_category)
    add_btn.pack(fill="x", pady=5)

    delete_btn = ctk.CTkButton(add_frame, text="Delete Selected", command=delete_color_category, fg_color="#C73E1D")
    delete_btn.pack(fill="x", pady=5)

    # Color list
    ctk.CTkLabel(color_panel, text="Available Categories:").pack(anchor="w", padx=10, pady=(20, 5))

    global color_list_frame
    color_list_frame = ctk.CTkFrame(color_panel)
    color_list_frame.pack(fill="both", expand=True, padx=10, pady=5)

    # Main content area (right side)
    main_content = ctk.CTkFrame(win)
    main_content.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=5, pady=5)
    main_content.grid_rowconfigure(1, weight=1)
    main_content.grid_columnconfigure(0, weight=1)

    # Responsive controls frame with wrapping
    controls = ctk.CTkFrame(main_content)
    controls.grid(row=0, column=0, sticky="ew", padx=10, pady=5)
    controls.grid_columnconfigure((0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10), weight=1, uniform="controls")

    # Chart controls - First row
    ctk.CTkLabel(controls, text="Chart Type:").grid(row=0, column=0, padx=2, pady=2, sticky="w")
    ctk.CTkComboBox(controls, values=["candle", "line", "ohlc"], variable=chart_type_var, width=100).grid(row=0,
                                                                                                          column=1,
                                                                                                          padx=2,
                                                                                                          pady=2,
                                                                                                          sticky="ew")

    ctk.CTkLabel(controls, text="Style:").grid(row=0, column=2, padx=2, pady=2, sticky="w")
    ctk.CTkComboBox(controls, values=["classic", "yahoo", "charles", "mike"], variable=style_var, width=100).grid(row=0,
                                                                                                                  column=3,
                                                                                                                  padx=2,
                                                                                                                  pady=2,
                                                                                                                  sticky="ew")

    ctk.CTkButton(controls, text="Update Chart", width=100,
                  command=lambda: plot_chart(chart_type_var.get(), style_var.get(), chart_frame)).grid(row=0, column=4,
                                                                                                       padx=2, pady=2,
                                                                                                       sticky="ew")

    # Chunk navigation - First row continued
    global prev_btn, next_btn
    prev_btn = ctk.CTkButton(controls, text="◀ Prev", command=prev_chunk, state="disabled", width=80)
    prev_btn.grid(row=0, column=5, padx=2, pady=2, sticky="ew")
    next_btn = ctk.CTkButton(controls, text="Next ▶", command=next_chunk, state="disabled", width=80)
    next_btn.grid(row=0, column=6, padx=2, pady=2, sticky="ew")

    # Selection controls - Second row
    ctk.CTkButton(controls, text="Save Selections", command=save_selected, width=100).grid(row=1, column=0, padx=2,
                                                                                           pady=2, sticky="ew")
    ctk.CTkButton(controls, text="Delete Last", width=80,
                  command=lambda: delete_last(chart_canvas.figure.axes[0], chart_canvas)).grid(row=1, column=1, padx=2,
                                                                                               pady=2, sticky="ew")
    ctk.CTkButton(controls, text="Clear All", width=80,
                  command=lambda: clear_all(chart_canvas.figure.axes[0], chart_canvas)).grid(row=1, column=2, padx=2,
                                                                                             pady=2, sticky="ew")

    select_btn = ctk.CTkButton(controls, text="Select: OFF", fg_color="#C73E1D", width=100,
                               command=lambda: toggle_select_mode(select_btn))
    select_btn.grid(row=1, column=3, padx=2, pady=2, sticky="ew")

    global chart_frame
    chart_frame = ctk.CTkFrame(main_content, fg_color="#f9f9f9")
    chart_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)

    # Initial plot
    plot_chart(chart_type_var.get(), style_var.get(), chart_frame)


# ---------- Icon ----------
def setup_icons(root):
    try:
        icon_path = os.path.join(os.path.dirname(__file__), "icon_trading.ico")
        root.iconbitmap(icon_path)
        if os.name == 'nt':
            try:
                from ctypes import windll
                windll.shell32.SetCurrentProcessExplicitAppUserModelID('com.tagemouati.tradingviewloader')
            except Exception as e:
                print(f"Erreur icône barre des tâches: {e}")
    except Exception as e:
        print(f"Impossible de charger l'icône: {e}")
        try:
            import tkinter as tk
            icon = tk.PhotoImage(width=16, height=16)
            root.iconphoto(False, icon)
        except:
            pass


# ---------- Main UI ----------
root = ctk.CTk()
root.title("TradingView Data Loader avec Chart - Light Theme")
root.geometry("1100x750")  # More reasonable default size
root.minsize(900, 600)  # Minimum size for smaller screens
root.grid_rowconfigure(3, weight=1)
root.grid_columnconfigure(0, weight=1)

chart_type_var = ctk.StringVar(value="candle")
style_var = ctk.StringVar(value="classic")
interval_var = ctk.StringVar(value="1 Hour")

# Header
header_frame = ctk.CTkFrame(root, fg_color="#4a90e2", corner_radius=0)
header_frame.grid(row=0, column=0, sticky="ew")
ctk.CTkLabel(header_frame, text="TradingView Data Loader avec Chart",
             font=ctk.CTkFont(size=20, weight="bold"), text_color="white").pack(padx=20, pady=12)

# Input frame - Made responsive with grid weights
input_frame = ctk.CTkFrame(root)
input_frame.grid(row=1, column=0, sticky="ew", padx=15, pady=10)
input_frame.grid_columnconfigure((1, 3, 5, 7, 9), weight=1)  # Make entry fields expandable

# First row of inputs
ctk.CTkLabel(input_frame, text="Lien TradingView:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
link_entry = ctk.CTkEntry(input_frame, placeholder_text="Collez le lien TradingView ici")
link_entry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

ctk.CTkLabel(input_frame, text="Intervalle:").grid(row=0, column=2, padx=5, pady=5, sticky="w")
ctk.CTkComboBox(input_frame, values=list(INTERVAL_MAP.keys()), variable=interval_var, width=120).grid(row=0, column=3,
                                                                                                      padx=5, pady=5,
                                                                                                      sticky="w")

ctk.CTkLabel(input_frame, text="Bougies:").grid(row=0, column=4, padx=5, pady=5, sticky="w")
bars_entry = ctk.CTkEntry(input_frame, width=80)
bars_entry.grid(row=0, column=5, padx=5, pady=5, sticky="w")
bars_entry.insert(0, "500")

# Second row of buttons - evenly distributed
fetch_btn = ctk.CTkButton(input_frame, text="Télécharger (Ctrl+F)", command=fetch_data,
                          fg_color="#4a90e2", hover_color="#357ab7", text_color="white", height=32)
fetch_btn.grid(row=1, column=0, columnspan=2, padx=5, pady=5, sticky="ew")

chart_btn = ctk.CTkButton(input_frame, text="Graphique (Ctrl+C)", command=open_chart_window,
                          fg_color="#4a90e2", hover_color="#357ab7", text_color="white", height=32)
chart_btn.grid(row=1, column=2, columnspan=2, padx=5, pady=5, sticky="ew")

save_btn = ctk.CTkButton(input_frame, text="Sauvegarder (Ctrl+S)", command=save_all_data, state="disabled",
                         fg_color="#2e7d32", hover_color="#1b5e20", text_color="white", height=32)
save_btn.grid(row=1, column=4, columnspan=2, padx=5, pady=5, sticky="ew")

help_btn = ctk.CTkButton(input_frame, text="Aide", command=show_help,
                         fg_color="#f39c12", hover_color="#d68910", text_color="white", height=32)
help_btn.grid(row=1, column=6, columnspan=2, padx=5, pady=5, sticky="ew")

# Add tooltips
add_tooltip(fetch_btn, "Télécharge les données du lien TradingView")
add_tooltip(chart_btn, "Ouvre la fenêtre de graphique avec les outils de sélection")
add_tooltip(save_btn, "Sauvegarde toutes les données dans un fichier CSV")
add_tooltip(help_btn, "Affiche l'aide et les raccourcis clavier")

# Details frame
details_frame = ctk.CTkFrame(root, fg_color="#f0f0f0")
details_frame.grid(row=2, column=0, sticky="ew", padx=15, pady=5)

# Table frame
table_frame = ctk.CTkFrame(root, fg_color="#f9f9f9")
table_frame.grid(row=3, column=0, sticky="nsew", padx=15, pady=10)
table_frame.grid_rowconfigure(0, weight=1)
table_frame.grid_columnconfigure(0, weight=1)
cols = ("Datetime", "Open", "High", "Low", "Close", "Volume")
tree = ttk.Treeview(table_frame, columns=cols, show="headings")
for col in cols:
    tree.heading(col, text=col)
    tree.column(col, anchor="center", width=120)
vsb = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
tree.configure(yscroll=vsb.set)
tree.grid(row=0, column=0, sticky="nsew")
vsb.grid(row=0, column=1, sticky="ns")
tree.tag_configure('even', background="#ffffff")
tree.tag_configure('odd', background="#f0f0f0")

# Status label
status_label = ctk.CTkLabel(root, text="Prêt", text_color="#2e7d32")
status_label.grid(row=4, column=0, pady=10)

# Shortcuts
root.bind_all("<Control-f>", lambda e: fetch_data())
root.bind_all("<Control-F>", lambda e: fetch_data())
root.bind_all("<Control-s>", lambda e: save_all_data())
root.bind_all("<Control-S>", lambda e: save_all_data())
root.bind_all("<Control-c>", lambda e: open_chart_window())
root.bind_all("<Control-C>", lambda e: open_chart_window())
root.bind_all("<Escape>", lambda e: root.destroy())

# Load preferences
prefs = load_preferences()
if prefs:
    link_entry.insert(0, prefs.get("link", ""))
    interval_var.set(prefs.get("interval", "1 Hour"))
    bars_entry.delete(0, "end")
    bars_entry.insert(0, prefs.get("bars", "500"))
    chart_type_var.set(prefs.get("chart_type", "candle"))
    style_var.set(prefs.get("style", "classic"))

root.mainloop()