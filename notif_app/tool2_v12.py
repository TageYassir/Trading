import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
from tvDatafeed import TvDatafeed, Interval
import pandas as pd
import urllib.parse
import re
import pyautogui
import webbrowser

# -----------------------
# Parse TradingView URL or symbol
# -----------------------
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
        print(entry)

# -----------------------
# WhatsApp Sender
# -----------------------
class WhatsAppSender:
    def __init__(self):
        self.base_url = "https://web.whatsapp.com/send?phone={}&text={}"

    def send_message(self, number, message):
        # Open WhatsApp Web in a new tab
        url = self.base_url.format(number.replace("+", ""), message)
        webbrowser.open_new_tab(url)
        time.sleep(8)  # wait for WhatsApp Web to load
        # Focus on the text box
        pyautogui.press("tab")  # tab usually focuses message input
        time.sleep(0.5)
        pyautogui.press("enter")  # send the message
        time.sleep(1)
        pyautogui.hotkey("ctrl", "w")  # close the tab


# -----------------------
# Worker
# -----------------------
def run_config(config, log_widget, wa_sender):
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
                    for r in config.recipients:
                        wa_sender.send_message(r, msg)
                if df['shortCond'].iloc[-1]:
                    msg = f"SELL {sym}"
                    config.log(f"📩 {msg} → {config.recipients}")
                    for r in config.recipients:
                        wa_sender.send_message(r, msg)
            except Exception as e:
                config.log(f"❌ Error with {sym}: {e}")
        log_widget.delete("1.0", tk.END)
        log_widget.insert(tk.END, config.log_text)
        time.sleep(60)

# -----------------------
# GUI App
# -----------------------
class TradingApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Range Filter Notifier")
        self.geometry("900x600")

        self.configs = {}
        self.wa_sender = WhatsAppSender()

        # Tree view (standard ttk inside CTk)
        self.tree_frame = ctk.CTkFrame(self)
        self.tree_frame.pack(fill="x", padx=10, pady=10)
        self.tree = ttk.Treeview(self.tree_frame, columns=("Symbols", "Recipients"))
        self.tree.heading("#0", text="Config Name")
        self.tree.heading("Symbols", text="Symbols")
        self.tree.heading("Recipients", text="Recipients")
        self.tree.pack(fill="x")

        # Log panel
        self.log_box = ctk.CTkTextbox(self, height=200)
        self.log_box.pack(fill="both", expand=True, padx=10, pady=10)

        # Add config button
        ctk.CTkButton(self, text="Add Config", command=self.add_config).pack(pady=5)

        # Test message button
        ctk.CTkButton(self, text="Send Test Message", command=self.send_test_message).pack(pady=5)

    def add_config(self):
        win = ctk.CTkToplevel(self)
        win.title("New Config")
        win.geometry("500x400")

        ctk.CTkLabel(win, text="Config Name:").pack(pady=5)
        entry_name = ctk.CTkEntry(win)
        entry_name.pack(pady=5)

        ctk.CTkLabel(win, text="Symbols (comma separated URLs or EXCHANGE:SYMBOL):").pack(pady=5)
        entry_symbols = ctk.CTkEntry(win)
        entry_symbols.pack(pady=5)

        ctk.CTkLabel(win, text="Recipients (comma separated, full number with +212...):").pack(pady=5)
        entry_recipients = ctk.CTkEntry(win)
        entry_recipients.pack(pady=5)

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
            threading.Thread(target=run_config, args=(config, self.log_box, self.wa_sender), daemon=True).start()
            win.destroy()

        ctk.CTkButton(win, text="Save", command=save).pack(pady=10)

    def send_test_message(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showerror("Error", "Select a config first")
            return
        for cfg_name in selected:
            cfg = self.configs[cfg_name]
            for r in cfg.recipients:
                self.wa_sender.send_message(r, f"Test message from {cfg.name}")
            cfg.log("✅ Test message sent")
            self.log_box.delete("1.0", tk.END)
            self.log_box.insert(tk.END, cfg.log_text)

# -----------------------
# Run App
# -----------------------
if __name__ == "__main__":
    app = TradingApp()
    app.mainloop()
