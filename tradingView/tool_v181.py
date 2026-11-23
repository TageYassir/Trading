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

# ---------- Preferences File ----------
PREF_FILE = "preferences.json"

def load_preferences():
    if os.path.exists(PREF_FILE):
        try:
            with open(PREF_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_preferences(prefs):
    with open(PREF_FILE, "w") as f:
        json.dump(prefs, f, indent=4)

# ---------- Appearance ----------
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

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

def onclick(event, ax, df):
    if event.inaxes != ax:
        return

    if event.xdata is None:
        return
    nearest_idx = int(round(event.xdata))

    if nearest_idx < 0 or nearest_idx >= len(df):
        return

    if nearest_idx in selected_indices:
        return  # prevent duplicates

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
    if not selected_indices:
        return
    selected_indices.pop()
    selected_candles.pop()
    line = marker_lines.pop()
    line.remove()
    canvas.draw_idle()

def clear_all(ax, canvas):
    selected_indices.clear()
    selected_candles.clear()
    for line in marker_lines:
        line.remove()
    marker_lines.clear()
    canvas.draw_idle()

def save_selected():
    if not selected_candles:
        messagebox.showinfo("Save", "No candles selected!")
        return
    fname = f"selected_candles_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    pd.DataFrame(selected_candles).to_csv(fname, index=False)
    messagebox.showinfo("Saved", f"Saved {len(selected_candles)} candles to {fname}")

# ---------- Chart ----------
current_df, current_symbol, current_exchange = None, "", ""
chart_frame, chart_canvas = None, None

def plot_chart(chart_type="candle", style="classic", frame=None):
    global chart_canvas, current_df
    if current_df is None or current_df.empty:
        messagebox.showerror("Error", "No data to plot")
        return

    for widget in frame.winfo_children():
        widget.destroy()

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
    controls.grid_columnconfigure(7, weight=1)

    ctk.CTkLabel(controls, text="Chart Type:").grid(row=0, column=0, padx=5)
    ctk.CTkComboBox(controls, values=["candle","line","ohlc"], variable=chart_type_var).grid(row=0, column=1, padx=5)
    ctk.CTkLabel(controls, text="Style:").grid(row=0, column=2, padx=5)
    ctk.CTkComboBox(controls, values=["classic","yahoo","charles","mike"], variable=style_var).grid(row=0, column=3, padx=5)

    ctk.CTkButton(controls, text="Update Chart",
                  command=lambda: plot_chart(chart_type_var.get(), style_var.get(), chart_frame)).grid(row=0, column=4, padx=5)
    ctk.CTkButton(controls, text="Save Selections", command=save_selected).grid(row=0, column=5, padx=5)
    ctk.CTkButton(controls, text="Delete Last", command=lambda: delete_last(chart_canvas.figure.axes[0], chart_canvas)).grid(row=0, column=6, padx=5)
    ctk.CTkButton(controls, text="Clear All", command=lambda: clear_all(chart_canvas.figure.axes[0], chart_canvas)).grid(row=0, column=7, padx=5)

    global chart_frame
    chart_frame = ctk.CTkFrame(win)
    chart_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)

    plot_chart(chart_type_var.get(), style_var.get(), chart_frame)

# ---------- Main UI ----------
ICON_PATH = "TradingViewLoader/icon_trading.ico"  # Placez votre icône ici

root = ctk.CTk()
root.title("TradingView Data Loader avec Chart - Version conviviale")
root.geometry("1200x850")
root.grid_rowconfigure(3, weight=1)
root.grid_columnconfigure(0, weight=1)
root.iconbitmap(ICON_PATH)  # Affiche l’icône en haut à gauche ET dans la barre des tâ

# Variables (must be after root is created!)
chart_type_var = ctk.StringVar(value="candle")
style_var = ctk.StringVar(value="classic")
interval_var = ctk.StringVar(value="1 Hour")

header_frame = ctk.CTkFrame(root, fg_color="#2E86AB", corner_radius=0)
header_frame.grid(row=0, column=0, sticky="ew")
ctk.CTkLabel(header_frame, text="TradingView Data Loader avec Chart", font=ctk.CTkFont(size=22, weight="bold"), text_color="white").pack(padx=20, pady=15)
ctk.CTkButton(header_frame, text="Aide", command=show_help, fg_color="#3BB273").pack(side="right", padx=20, pady=15)

input_frame = ctk.CTkFrame(root)
input_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=10)
input_frame.grid_columnconfigure(1, weight=1)

ctk.CTkLabel(input_frame, text="Lien TradingView:").grid(row=0, column=0, padx=5)
link_entry = ctk.CTkEntry(input_frame, width=400)
link_entry.grid(row=0, column=1, padx=5, sticky="ew")
add_tooltip(link_entry, "Collez ici le lien TradingView du symbole")

ctk.CTkLabel(input_frame, text="Intervalle:").grid(row=1, column=0, padx=5)
interval_box = ctk.CTkComboBox(input_frame, variable=interval_var, values=list(INTERVAL_MAP.keys()), width=120)
interval_box.grid(row=1, column=1, padx=5, sticky="w")
add_tooltip(interval_box, "Sélectionnez l'intervalle de temps")

ctk.CTkLabel(input_frame, text="Bougies:").grid(row=1, column=2, padx=5)
bars_entry = ctk.CTkEntry(input_frame, width=80)
bars_entry.insert(0,"200")
bars_entry.grid(row=1, column=3, padx=5)
add_tooltip(bars_entry, "Nombre de bougies à récupérer")

actions_frame = ctk.CTkFrame(input_frame)
actions_frame.grid(row=0, column=4, rowspan=2, padx=10)
ctk.CTkButton(actions_frame, text="Télécharger", command=fetch_data, fg_color="#2E86AB").pack(pady=2)
ctk.CTkButton(actions_frame, text="Ouvrir graphique", command=open_chart_window, fg_color="#2E86AB").pack(pady=2)
save_btn = ctk.CTkButton(actions_frame, text="Sauvegarder", state="disabled", fg_color="#3BB273")
save_btn.pack(pady=2)
add_tooltip(save_btn, "Sauvegarder les données téléchargées")

ctk.CTkLabel(actions_frame, text="(Ctrl+F: Télécharger, Ctrl+C: Graphique, Ctrl+S: Sauvegarder)", text_color="#888888", font=ctk.CTkFont(size=12)).pack(pady=2)

details_frame = ctk.CTkFrame(root, height=100)
details_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=5)

table_frame = ctk.CTkFrame(root)
table_frame.grid(row=3, column=0, sticky="nsew", padx=10, pady=10)
table_frame.grid_rowconfigure(0, weight=1)
table_frame.grid_columnconfigure(0, weight=1)

columns = ("Datetime","Open","High","Low","Close","Volume")
tree = ttk.Treeview(table_frame, columns=columns, show="headings")
for col in columns:
    tree.heading(col, text=col)
    tree.column(col, width=120, anchor="center")
tree.grid(row=0, column=0, sticky="nsew")

scroll_y = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
scroll_y.grid(row=0, column=1, sticky="ns")
tree.configure(yscrollcommand=scroll_y.set)

status_frame = ctk.CTkFrame(root, height=30)
status_frame.grid(row=4, column=0, sticky="ew")
status_label = ctk.CTkLabel(status_frame, text="Prêt", text_color="white")
status_label.pack(side="left", padx=10)

# ---------- Load preferences ----------
prefs = load_preferences()
if prefs:
    link_entry.insert(0, prefs.get("link",""))
    interval_var.set(prefs.get("interval","1 Hour"))
    bars_entry.delete(0,"end")
    bars_entry.insert(0, str(prefs.get("bars",200)))
    chart_type_var.set(prefs.get("chart_type","candle"))
    style_var.set(prefs.get("style","classic"))

# ---------- Shortcuts ----------
def shortcut_download(event=None):
    fetch_data()
def shortcut_save(event=None):
    save_btn.invoke()
def shortcut_chart(event=None):
    open_chart_window()
def shortcut_quit(event=None):
    root.quit()
root.bind("<Control-f>", shortcut_download)
root.bind("<Control-s>", shortcut_save)
root.bind("<Control-c>", shortcut_chart)
root.bind("<Escape>", shortcut_quit)

# ---------- Run ----------
root.mainloop()