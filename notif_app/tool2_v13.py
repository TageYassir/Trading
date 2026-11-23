import tkinter as tk
from tkinter import messagebox, ttk
import threading
import time
from tvDatafeed import TvDatafeed, Interval
import pandas as pd
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import urllib.parse
import re

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
        self.active = True  # message sending enabled by default

    def log(self, msg):
        entry = f"[{self.name}] {msg}\n"
        self.log_text += entry
        print(entry)

# -----------------------
# Email sender
# -----------------------
class EmailSender:
    def __init__(self, smtp_server, smtp_port, email, password):
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.email = email
        self.password = password

    def send_email(self, to_email, subject, message):
        try:
            msg = MIMEMultipart()
            msg['From'] = self.email
            msg['To'] = to_email
            msg['Subject'] = subject
            msg.attach(MIMEText(message, 'plain'))

            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()
            server.login(self.email, self.password)
            server.send_message(msg)
            server.quit()
            return True
        except Exception as e:
            print(f"Failed to send email to {to_email}: {e}")
            return False

# -----------------------
# Worker
# -----------------------
def run_config(config, log_widget, email_sender):
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
                msg = None
                if df['longCond'].iloc[-1]:
                    msg = f"BUY {sym}"
                elif df['shortCond'].iloc[-1]:
                    msg = f"SELL {sym}"

                if msg:
                    for recipient in config.recipients:
                        config.log(f"Preparing to send to {recipient}: {msg}")
                        if config.active:
                            success = email_sender.send_email(recipient, f"Trade Alert {sym}", msg)
                            if success:
                                config.log(f"✅ Email sent to {recipient}")
                            else:
                                config.log(f"❌ Failed to send to {recipient}")
                        else:
                            config.log(f"⏸ Sending disabled for {recipient}")

            except Exception as e:
                config.log(f"❌ Error with {sym}: {e}")

        # Update GUI log
        log_widget.delete("1.0", tk.END)
        log_widget.insert(tk.END, config.log_text)
        time.sleep(60)

# -----------------------
# GUI App
# -----------------------
class TradingApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Range Filter Email Notifier")
        self.geometry("900x600")
        self.configs = {}

        # Email sender setup (enter your credentials here)
        self.email_sender = EmailSender(
            smtp_server="smtp.gmail.com",
            smtp_port=587,
            email="fftt7252@gmail.com",
            password="soaewjwyyvdziwwc"
        )

        # Treeview
        self.tree = ttk.Treeview(self, columns=("Symbols", "Recipients", "Active"))
        self.tree.heading("#0", text="Config Name")
        self.tree.heading("Symbols", text="Symbols")
        self.tree.heading("Recipients", text="Recipients")
        self.tree.heading("Active", text="Active")
        self.tree.pack(fill="x")

        # Buttons
        tk.Button(self, text="Add Config", command=self.add_config).pack(pady=5)
        tk.Button(self, text="Toggle Active", command=self.toggle_active).pack(pady=5)

        # Log panel
        self.log_box = tk.Text(self, height=15, bg="black", fg="lime")
        self.log_box.pack(fill="both", expand=True)

    def add_config(self):
        win = tk.Toplevel(self)
        win.title("New Config")
        win.geometry("500x400")

        tk.Label(win, text="Config Name:").pack()
        entry_name = tk.Entry(win, width=40)
        entry_name.pack()

        tk.Label(win, text="Symbols (comma separated URLs or EXCHANGE:SYMBOL):").pack()
        entry_symbols = tk.Entry(win, width=50)
        entry_symbols.pack()

        tk.Label(win, text="Recipients (comma separated emails):").pack()
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
            self.tree.insert("", "end", iid=name, text=name, values=(",".join(symbols), ",".join(recips), "Yes"))
            threading.Thread(target=run_config, args=(config, self.log_box, self.email_sender), daemon=True).start()
            win.destroy()

        tk.Button(win, text="Save", command=save).pack(pady=10)

    def toggle_active(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showerror("Error", "Select a config first")
            return
        for item in selected:
            config = self.configs[item]
            config.active = not config.active
            self.tree.set(item, "Active", "Yes" if config.active else "No")
            self.log_box.insert(tk.END, f"⏸ Toggled active for {config.name} → {config.active}\n")

# -----------------------
# Run
# -----------------------
if __name__ == "__main__":
    app = TradingApp()
    app.mainloop()
