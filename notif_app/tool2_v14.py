import tkinter as tk
from tkinter import messagebox, ttk
import threading
import time
import json
from tvDatafeed import TvDatafeed, Interval
import pandas as pd
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import urllib.parse
import re
import os

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
# Config / User management
# -----------------------
CONFIG_FILE = "trading_config.json"
USERS_FILE = "users.json"

def save_json(file, data):
    with open(file, "w") as f:
        json.dump(data, f, indent=4)

def load_json(file):
    if os.path.exists(file):
        with open(file, "r") as f:
            return json.load(f)
    return {}

# -----------------------
# Worker
# -----------------------
class TradeWorker:
    def __init__(self, config, email_sender, log_widget):
        self.config = config
        self.email_sender = email_sender
        self.log_widget = log_widget
        self.tv = TvDatafeed()
        self.status = {}  # keep last status per symbol per user

    def log(self, msg):
        entry = f"{msg}\n"
        self.config['log_text'] += entry
        print(entry)
        self.log_widget.delete("1.0", tk.END)
        self.log_widget.insert(tk.END, self.config['log_text'])

    def run(self):
        while True:
            for sym in self.config['symbols']:
                try:
                    exchange, symbol = sym.split(":")
                    df = self.tv.get_hist(symbol=symbol, exchange=exchange,
                                          interval=Interval.in_5_minute, n_bars=200)
                    if df is None or df.empty:
                        self.log(f"⚠️ No data for {sym}")
                        continue

                    df = range_filter(df)
                    current_status = None
                    if df['longCond'].iloc[-1]:
                        current_status = "BUY"
                    elif df['shortCond'].iloc[-1]:
                        current_status = "SELL"

                    if current_status:
                        for user in self.config['recipients']:
                            last = self.status.get((user['email'], sym))
                            if last != current_status:
                                message = f"Hello {user['name']},\n\n" \
                                          f"Trade Signal: {current_status}\n" \
                                          f"Symbol: {symbol}\n" \
                                          f"Broker/Exchange: {exchange}\n\n" \
                                          f"Best regards,\nTrading Alert Bot"
                                sent = self.email_sender.send_email(user['email'],
                                                                    f"Trade Alert {symbol}",
                                                                    message)
                                if sent:
                                    self.log(f"✅ Sent {current_status} for {symbol} to {user['name']}")
                                    self.status[(user['email'], sym)] = current_status
                                else:
                                    self.log(f"❌ Failed to send {current_status} for {symbol} to {user['name']}")
                    # if no signal, do not reset last status, only send on change
                except Exception as e:
                    self.log(f"❌ Error processing {sym}: {e}")
            time.sleep(60)

# -----------------------
# GUI App
# -----------------------
class TradingApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Range Filter Email Notifier")
        self.geometry("1000x600")
        self.configs = load_json(CONFIG_FILE)
        self.users = load_json(USERS_FILE)
        self.log_text = ""

        # Email sender setup
        self.email_sender = EmailSender(
            smtp_server="smtp.gmail.com",
            smtp_port=587,
            email="fftt7252@gmail.com",
            password="soaewjwyyvdziwwc"
        )

        # Users list
        self.user_frame = tk.Frame(self)
        self.user_frame.pack(side="top", fill="x")
        tk.Label(self.user_frame, text="Users:").pack()
        self.user_listbox = tk.Listbox(self.user_frame, selectmode="multiple", width=50)
        self.user_listbox.pack()
        self.refresh_users()

        tk.Button(self.user_frame, text="Add User", command=self.add_user).pack(pady=5)

        # Symbols & configs
        self.tree = ttk.Treeview(self, columns=("Symbols", "Active"))
        self.tree.heading("#0", text="Config Name")
        self.tree.heading("Symbols", text="Symbols")
        self.tree.heading("Active", text="Active")
        self.tree.pack(fill="x")

        tk.Button(self, text="Add Config", command=self.add_config).pack(pady=5)

        # Log panel
        self.log_box = tk.Text(self, height=20, bg="black", fg="lime")
        self.log_box.pack(fill="both", expand=True)

    def refresh_users(self):
        self.user_listbox.delete(0, tk.END)
        for u in self.users.values():
            self.user_listbox.insert(tk.END, f"{u['name']} ({u['email']})")

    def add_user(self):
        win = tk.Toplevel(self)
        win.title("Add User")
        tk.Label(win, text="Name:").pack()
        entry_name = tk.Entry(win)
        entry_name.pack()
        tk.Label(win, text="Email:").pack()
        entry_email = tk.Entry(win)
        entry_email.pack()

        def save_user():
            name = entry_name.get().strip()
            email = entry_email.get().strip()
            if not name or not email:
                messagebox.showerror("Error", "All fields required")
                return
            key = email
            self.users[key] = {"name": name, "email": email}
            save_json(USERS_FILE, self.users)
            self.refresh_users()
            win.destroy()

        tk.Button(win, text="Save", command=save_user).pack(pady=10)

    def add_config(self):
        selected_indices = self.user_listbox.curselection()
        if not selected_indices:
            messagebox.showerror("Error", "Select at least one user")
            return
        recipients = [list(self.users.values())[i] for i in selected_indices]

        win = tk.Toplevel(self)
        win.title("New Config")
        win.geometry("500x400")

        tk.Label(win, text="Config Name:").pack()
        entry_name = tk.Entry(win, width=40)
        entry_name.pack()

        tk.Label(win, text="Symbols (comma separated URLs or EXCHANGE:SYMBOL):").pack()
        entry_symbols = tk.Entry(win, width=50)
        entry_symbols.pack()

        def save():
            name = entry_name.get().strip()
            raw_symbols = [s.strip() for s in entry_symbols.get().split(",") if s.strip()]
            symbols = []
            for s in raw_symbols:
                exchange, symbol = parse_tv_link(s)
                if exchange and symbol:
                    symbols.append(f"{exchange}:{symbol}")
                else:
                    messagebox.showerror("Error", f"Cannot parse symbol/URL: {s}")
                    return
            if not name or not symbols:
                messagebox.showerror("Error", "All fields required")
                return
            config_data = {
                "name": name,
                "symbols": symbols,
                "recipients": recipients,
                "log_text": ""
            }
            self.configs[name] = config_data
            save_json(CONFIG_FILE, self.configs)
            self.tree.insert("", "end", iid=name, text=name, values=(",".join(symbols), "Yes"))
            worker = TradeWorker(config_data, self.email_sender, self.log_box)
            threading.Thread(target=worker.run, daemon=True).start()
            win.destroy()

        tk.Button(win, text="Save", command=save).pack(pady=10)

if __name__ == "__main__":
    app = TradingApp()
    app.mainloop()
