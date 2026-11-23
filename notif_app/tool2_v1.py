import tkinter as tk
from tkinter import messagebox, Listbox, MULTIPLE, ttk
import threading
import time
from tvDatafeed import TvDatafeed, Interval
import pandas as pd
import keyboard
import urllib.parse
import re


# -----------------------
# Parse TradingView URL or symbol
# -----------------------
def parse_tv_link(link: str):
    """
    Extract exchange and symbol from a TradingView URL or a symbol string.
    Returns (exchange, symbol) both uppercased.
    """
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

    if ":" in link:
        exchange, symbol = link.split(":", 1)
        return exchange.upper(), symbol.upper()

    return None, None


# -----------------------
# Strategy logic
# -----------------------
def range_filter(df, period=100, mult=3.0):
    df['ema'] = df['close'].ewm(span=period).mean()
    df['rng'] = (df['close'] - df['close'].shift(1)).abs().ewm(span=period).mean()
    df['smoothrng'] = df['rng'].ewm(span=period * 2 - 1).mean() * mult
    df['filt'] = df['close']

    for i in range(1, len(df)):
        prev = df.loc[df.index[i - 1], 'filt']
        x = df.loc[df.index[i], 'close']
        r = df.loc[df.index[i], 'smoothrng']
        if x > prev:
            df.loc[df.index[i], 'filt'] = prev if x - r < prev else x - r
        else:
            df.loc[df.index[i], 'filt'] = prev if x + r > prev else x + r

    df['longCond'] = (df['close'] > df['filt']) & (df['close'] > df['close'].shift(1))
    df['shortCond'] = (df['close'] < df['filt']) & (df['close'] < df['close'].shift(1))
    return df


# -----------------------
# Config class
# -----------------------
class Config:
    def __init__(self, name, symbols, recipients):
        self.name = name
        self.symbols = symbols
        self.recipients = recipients
        self.log_text = ""

    def log(self, msg):
        entry = f"[{self.name}] {msg}\n"
        self.log_text += entry
        print(entry)  # console fallback


# -----------------------
# Worker
# -----------------------
def run_config(config, log_widget):
    tv = TvDatafeed()
    while True:
        for sym in config.symbols:
            try:
                exchange, symbol = sym.split(":")
                df = tv.get_hist(symbol=symbol, exchange=exchange, interval=Interval.in_5_minute, n_bars=200)
                if df is None or df.empty:
                    config.log(f"⚠️ No data for {sym}")
                    continue

                df = range_filter(df)
                if df['longCond'].iloc[-1]:
                    msg = f"BUY {sym}"
                    config.log(f"📩 {msg} → {config.recipients}")
                if df['shortCond'].iloc[-1]:
                    msg = f"SELL {sym}"
                    config.log(f"📩 {msg} → {config.recipients}")

            except Exception as e:
                config.log(f"❌ Error with {sym}: {e}")

        # Update GUI log
        log_widget.delete("1.0", tk.END)
        log_widget.insert(tk.END, config.log_text)
        time.sleep(60)


# -----------------------
# GUI App
# -----------------------
class TradingApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Range Filter Notifier")
        self.root.geometry("900x600")

        # Configs storage
        self.configs = {}

        # UI Layout
        self.tree = ttk.Treeview(root, columns=("Symbols", "Recipients"))
        self.tree.heading("#0", text="Config Name")
        self.tree.heading("Symbols", text="Symbols")
        self.tree.heading("Recipients", text="Recipients")
        self.tree.pack(fill="x")

        # Log panel
        self.log_box = tk.Text(root, height=15, bg="black", fg="lime")
        self.log_box.pack(fill="both", expand=True)

        # Add config button
        tk.Button(root, text="Add Config", command=self.add_config).pack(pady=5)

        # Toggle app visibility with F12
        threading.Thread(target=self.hotkey_listener, daemon=True).start()

    def add_config(self):
        win = tk.Toplevel(self.root)
        win.title("New Config")
        win.geometry("500x400")

        tk.Label(win, text="Config Name:").pack()
        entry_name = tk.Entry(win, width=40)
        entry_name.pack()

        tk.Label(win, text="Symbols (comma separated URLs or EXCHANGE:SYMBOL):").pack()
        entry_symbols = tk.Entry(win, width=50)
        entry_symbols.pack()

        tk.Label(win, text="Recipients (comma separated, +212... or email):").pack()
        entry_recipients = tk.Entry(win, width=50)
        entry_recipients.pack()

        def save():
            name = entry_name.get()
            raw_symbols = [s.strip() for s in entry_symbols.get().split(",") if s.strip()]
            symbols = []
            for s in raw_symbols:
                exchange, symbol = parse_tv_link(s)
                if exchange and symbol:
                    symbols.append(f"{exchange}:{symbol}")
                else:
                    messagebox.showerror("Error", f"Cannot parse symbol/URL: {s}")
                    return
            recips = [r.strip() for r in entry_recipients.get().split(",") if r.strip()]
            if not name or not symbols or not recips:
                messagebox.showerror("Error", "All fields required")
                return
            config = Config(name, symbols, recips)
            self.configs[name] = config
            self.tree.insert("", "end", iid=name, text=name, values=(",".join(symbols), ",".join(recips)))
            threading.Thread(target=run_config, args=(config, self.log_box), daemon=True).start()
            win.destroy()

        tk.Button(win, text="Save", command=save).pack(pady=10)

    def hotkey_listener(self):
        while True:
            if keyboard.is_pressed("f12"):
                if self.root.state() == "normal":
                    self.root.withdraw()
                else:
                    self.root.deiconify()
                time.sleep(0.5)


# -----------------------
# Run
# -----------------------
if __name__ == "__main__":
    root = tk.Tk()
    app = TradingApp(root)
    root.mainloop()
