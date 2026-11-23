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
        status_label.configure(text=f"Chargé {exchange}:{symbol} ({interval_key}, {n_bars} bougies)", text_color="#3BB273")
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
    ctk.CTkLabel(details_frame, text=f"Symbol: {symbol}", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, padx=5, pady=2, sticky="w")
    ctk.CTkLabel(details_frame, text=f"Exchange: {exchange}").grid(row=0, column=1, padx=5, pady=2, sticky="w")
    ctk.CTkLabel(details_frame, text=f"Latest Price: {latest['close']:.4f}", font=ctk.CTkFont(weight="bold")).grid(row=1, column=0, padx=5, pady=2, sticky="w")
    change_color = "#3BB273" if price_change >= 0 else "#C73E1D"
    ctk.CTkLabel(details_frame, text=f"Change: {price_change:+.4f} ({percent_change:+.2f}%)", text_color=change_color).grid(row=1, column=1, padx=5, pady=2, sticky="w")

# ---------- Chart Selection ----------
selected_candles = []
selected_indices = []
marker_lines = []

select_mode = False

def toggle_select_mode(btn):
    global select_mode
    select_mode = not select_mode
    if select_mode:
        btn.configure(text="Select Mode: ON", fg_color="#3BB273")
    else:
        btn.configure(text="Select Mode: OFF", fg_color="#C73E1D")

def onclick(event, ax, df):
    if not select_mode: return
    if event.inaxes != ax or event.xdata is None: return
    nearest_idx = int(round(event.xdata))
    if nearest_idx < 0 or nearest_idx >= len(df): return
    if nearest_idx in selected_indices: return
    row = df.iloc[nearest_idx]
    selected_indices.append(nearest_idx)
    selected_candles.append({
        "datetime": str(row.name),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "volume": float(row["volume"])
    })
    marker, = ax.plot(nearest_idx, row["close"], "ro", markersize=6, zorder=5)
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
    fname = APP_DATA_DIR / f"selected_candles_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    try:
        pd.DataFrame(selected_candles).to_csv(fname, index=False)
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

def plot_chart(chart_type="candle", style="classic", frame=None):
    global chart_canvas, current_df
    if current_df is None or current_df.empty:
        messagebox.showerror("Error", "No data to plot")
        return
    for widget in frame.winfo_children(): widget.destroy()
    df = current_df.copy()
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True, errors="coerce")
    df.set_index("datetime", inplace=True)
    fig, axlist = mpf.plot(
        df, type=chart_type, style=style, volume=True,
        title=f"{current_symbol} - {current_exchange} ({interval_var.get()})",
        ylabel="Price", ylabel_lower="Volume", figsize=(10, 6), returnfig=True
    )
    ax = axlist[0]
    chart_canvas = FigureCanvasTkAgg(fig, master=frame)
    chart_canvas.draw()
    chart_canvas.get_tk_widget().pack(fill="both", expand=True)
    toolbar = NavigationToolbar2Tk(chart_canvas, frame)
    toolbar.update()
    chart_canvas.get_tk_widget().pack(fill="both", expand=True)
    fig.canvas.mpl_connect("button_press_event", lambda e: onclick(e, ax, df))

def open_chart_window():
    global current_df, current_symbol, current_exchange
    rows = [tree.item(r)["values"] for r in tree.get_children()]
    if not rows:
        messagebox.showerror("Error", "Fetch data first")
        return
    df = pd.DataFrame(rows, columns=["datetime", "open", "high", "low", "close", "volume"])
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True, errors="coerce")
    df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float})
    current_df = df
    for w in details_frame.winfo_children():
        if isinstance(w, ctk.CTkLabel):
            t = w.cget("text")
            if t.startswith("Symbol:"): current_symbol = t.split(":")[1].strip()
            if t.startswith("Exchange:"): current_exchange = t.split(":")[1].strip()
    win = ctk.CTkToplevel(root)
    win.title("Chart View")
    win.geometry("1200x800")
    win.grid_rowconfigure(1, weight=1)
    win.grid_columnconfigure(0, weight=1)
    controls = ctk.CTkFrame(win)
    controls.grid(row=0, column=0, sticky="ew", padx=10, pady=5)
    controls.grid_columnconfigure(8, weight=1)
    ctk.CTkLabel(controls, text="Chart Type:").grid(row=0, column=0, padx=5)
    ctk.CTkComboBox(controls, values=["candle","line","ohlc"], variable=chart_type_var).grid(row=0, column=1, padx=5)
    ctk.CTkLabel(controls, text="Style:").grid(row=0, column=2, padx=5)
    ctk.CTkComboBox(controls, values=["classic","yahoo","charles","mike"], variable=style_var).grid(row=0, column=3, padx=5)
    ctk.CTkButton(controls, text="Update Chart",
                  command=lambda: plot_chart(chart_type_var.get(), style_var.get(), chart_frame)).grid(row=0, column=4, padx=5)
    ctk.CTkButton(controls, text="Save Selections", command=save_selected).grid(row=0, column=5, padx=5)
    ctk.CTkButton(controls, text="Delete Last", command=lambda: delete_last(chart_canvas.figure.axes[0], chart_canvas)).grid(row=0, column=6, padx=5)
    ctk.CTkButton(controls, text="Clear All", command=lambda: clear_all(chart_canvas.figure.axes[0], chart_canvas)).grid(row=0, column=7, padx=5)
    select_btn = ctk.CTkButton(controls, text="Select Mode: OFF", fg_color="#C73E1D",
                               command=lambda: toggle_select_mode(select_btn))
    select_btn.grid(row=0, column=8, padx=5)
    global chart_frame
    chart_frame = ctk.CTkFrame(win, fg_color="#f9f9f9")
    chart_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
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
        print(f"Impossible de charger l’icône: {e}")
        try:
            import tkinter as tk
            icon = tk.PhotoImage(width=16, height=16)
            root.iconphoto(False, icon)
        except: pass

# ---------- Main UI ----------
root = ctk.CTk()
root.title("TradingView Data Loader avec Chart - Light Theme")
root.geometry("1200x850")
root.grid_rowconfigure(3, weight=1)
root.grid_columnconfigure(0, weight=1)
setup_icons(root)

chart_type_var = ctk.StringVar(value="candle")
style_var = ctk.StringVar(value="classic")
interval_var = ctk.StringVar(value="1 Hour")

# Header
header_frame = ctk.CTkFrame(root, fg_color="#4a90e2", corner_radius=0)
header_frame.grid(row=0, column=0, sticky="ew")
ctk.CTkLabel(header_frame, text="TradingView Data Loader avec Chart",
             font=ctk.CTkFont(size=22, weight="bold"), text_color="white").pack(padx=20, pady=15)

# Input frame
input_frame = ctk.CTkFrame(root)
input_frame.grid(row=1, column=0, sticky="ew", padx=15, pady=10)
ctk.CTkLabel(input_frame, text="Lien TradingView:").grid(row=0, column=0, padx=5)
link_entry = ctk.CTkEntry(input_frame, width=400, placeholder_text="Collez le lien TradingView ici")
link_entry.grid(row=0, column=1, padx=5)
ctk.CTkLabel(input_frame, text="Intervalle:").grid(row=0, column=2, padx=5)
ctk.CTkComboBox(input_frame, values=list(INTERVAL_MAP.keys()), variable=interval_var).grid(row=0, column=3, padx=5)
ctk.CTkLabel(input_frame, text="Nombre de bougies:").grid(row=0, column=4, padx=5)
bars_entry = ctk.CTkEntry(input_frame, width=100)
bars_entry.grid(row=0, column=5, padx=5)
bars_entry.insert(0, "500")

fetch_btn = ctk.CTkButton(input_frame, text="Télécharger (Ctrl+F)", command=fetch_data, fg_color="#4a90e2", hover_color="#357ab7", text_color="white")
fetch_btn.grid(row=0, column=6, padx=5)
add_tooltip(fetch_btn, "Télécharge les données du lien TradingView")
chart_btn = ctk.CTkButton(input_frame, text="Ouvrir le graphique (Ctrl+C)", command=open_chart_window, fg_color="#4a90e2", hover_color="#357ab7", text_color="white")
chart_btn.grid(row=0, column=7, padx=5)
save_btn = ctk.CTkButton(input_frame, text="Sauvegarder les données (Ctrl+S)", command=save_all_data, state="disabled", fg_color="#2e7d32", hover_color="#1b5e20", text_color="white")
save_btn.grid(row=0, column=8, padx=5)
help_btn = ctk.CTkButton(input_frame, text="Aide", command=show_help, fg_color="#f39c12", hover_color="#d68910", text_color="white")
help_btn.grid(row=0, column=9, padx=5)

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
    tree.column(col, anchor="center")
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
