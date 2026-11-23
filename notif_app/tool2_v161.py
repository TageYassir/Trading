import tkinter as tk
from tkinter import messagebox, ttk, simpledialog
import threading
import time
import json
import os
from tvDatafeed import TvDatafeed, Interval
import pandas as pd
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import urllib.parse
import re

# -----------------------
# Helpers
# -----------------------
CONFIG_FILE = "configs.json"
USERS_FILE = "users.json"

def save_json(file, data):
    with open(file, "w") as f:
        json.dump(data, f, indent=4)

def load_json(file):
    if os.path.exists(file):
        with open(file, "r") as f:
            return json.load(f)
    return {}

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
# Worker
# -----------------------
class TradeWorker:
    def __init__(self, config, email_sender, log_widget):
        self.config = config
        self.email_sender = email_sender
        self.log_widget = log_widget
        self.tv = TvDatafeed()
        self.status = {}
        self.running = True

    def log(self, msg):
        entry = f"{msg}\n"
        self.config['log_text'] += entry
        self.log_widget.delete("1.0", tk.END)
        self.log_widget.insert(tk.END, self.config['log_text'])

    def run(self):
        while True:
            if self.running:
                for sym in self.config['symbols']:
                    try:
                        exchange, symbol = sym.split(":")
                        df = self.tv.get_hist(symbol=symbol, exchange=exchange, interval=Interval.in_5_minute, n_bars=200)
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
                                key = (user['email'], sym)
                                last = self.status.get(key)
                                if last != current_status:
                                    message = f"Hello {user['name']},\n\n" \
                                              f"Config: {self.config['name']}\n" \
                                              f"Trade Signal: {current_status}\n" \
                                              f"Symbol: {symbol}\n" \
                                              f"Broker/Exchange: {exchange}\n\n" \
                                              f"Best regards,\nTrading Alert Bot"
                                    sent = self.email_sender.send_email(user['email'], f"Trade Alert {symbol}", message)
                                    if sent:
                                        self.log(f"✅ Sent {current_status} for {symbol} to {user['name']}")
                                        self.status[key] = current_status
                                    else:
                                        self.log(f"❌ Failed to send {current_status} for {symbol} to {user['name']}")
                    except Exception as e:
                        self.log(f"❌ Error processing {sym}: {e}")
            time.sleep(60)

    def stop(self):
        self.running = False

    def start(self):
        self.running = True

    def refresh_new_users(self):
        for sym in self.config['symbols']:
            for user in self.config['recipients']:
                key = (user['email'], sym)
                if key not in self.status:
                    self.status[key] = None

# -----------------------
# GUI App
# -----------------------
class TradingApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Range Filter Email Notifier")
        self.geometry("1200x700")

        # Set app icon (replace 'icon.ico' with your ICO file)
        if os.path.exists("icon_notif.ico"):
            self.iconbitmap("icon_notif.ico")

        self.configs = load_json(CONFIG_FILE)
        self.users = load_json(USERS_FILE)
        self.workers = {}
        self.email_sender = EmailSender(
            smtp_server="smtp.gmail.com",
            smtp_port=587,
            email="fftt7252@gmail.com",
            password="soaewjwyyvdziwwc"
        )
        self.init_ui()
        self.start_existing_configs()

    # -----------------------
    # GUI Init
    # -----------------------
    def init_ui(self):
        # Users
        user_frame = tk.LabelFrame(self, text="Users", fg="blue", padx=10, pady=5)
        user_frame.pack(side="top", fill="x", padx=10, pady=5)
        self.user_listbox = tk.Listbox(user_frame, selectmode="multiple", width=50, bg="#e8f0ff")
        self.user_listbox.pack(side="left")
        btn_frame = tk.Frame(user_frame)
        btn_frame.pack(side="left", padx=10)
        tk.Button(btn_frame, text="Add User", bg="#4caf50", fg="white", command=self.add_user).pack(pady=2)
        tk.Button(btn_frame, text="Delete User", bg="#f44336", fg="white", command=self.delete_user).pack(pady=2)

        # Config Tree
        tree_frame = tk.LabelFrame(self, text="Configurations", fg="green", padx=10, pady=5)
        tree_frame.pack(fill="x", padx=10, pady=5)
        self.tree = ttk.Treeview(tree_frame, columns=("Symbols", "Recipients", "Active"), height=6)
        self.tree.heading("#0", text="Config Name")
        self.tree.heading("Symbols", text="Symbols")
        self.tree.heading("Recipients", text="Recipients")
        self.tree.heading("Active", text="Active")
        self.tree.pack(fill="x")
        tk.Button(tree_frame, text="Add Config", bg="#2196f3", fg="white", command=self.add_config).pack(pady=5)
        tk.Button(tree_frame, text="Manage Users in Config", bg="#ff9800", fg="white", command=self.manage_users_config).pack(pady=5)

        # Config control buttons
        control_frame = tk.Frame(self)
        control_frame.pack(pady=5)
        tk.Button(control_frame, text="Refresh Config / Send to New Users", bg="#4caf50", fg="white", command=self.refresh_config).pack(side="left", padx=5)
        tk.Button(control_frame, text="Stop Config", bg="#f44336", fg="white", command=self.stop_config).pack(side="left", padx=5)
        tk.Button(control_frame, text="Start Config", bg="#2196f3", fg="white", command=self.start_config).pack(side="left", padx=5)

        # Log
        log_frame = tk.LabelFrame(self, text="Logs", fg="purple", padx=10, pady=5)
        log_frame.pack(fill="both", expand=True, padx=10, pady=5)
        self.log_box = tk.Text(log_frame, height=20, bg="black", fg="lime")
        self.log_box.pack(fill="both", expand=True)

        self.refresh_users()

    # -----------------------
    # User Management
    # -----------------------
    def refresh_users(self):
        self.user_listbox.delete(0, tk.END)
        for u in self.users.values():
            self.user_listbox.insert(tk.END, f"{u['name']} ({u['email']})")

    def add_user(self):
        name = simpledialog.askstring("Add User", "Enter user name:", parent=self)
        email = simpledialog.askstring("Add User", "Enter user email:", parent=self)
        if not name or not email:
            return
        self.users[email] = {"name": name, "email": email}
        save_json(USERS_FILE, self.users)
        self.refresh_users()

    def delete_user(self):
        selected = self.user_listbox.curselection()
        if not selected:
            messagebox.showerror("Error", "Select a user to delete")
            return
        for i in reversed(selected):
            email = list(self.users.keys())[i]
            del self.users[email]
        save_json(USERS_FILE, self.users)
        self.refresh_users()

    # -----------------------
    # Config Management
    # -----------------------
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
            config_data = {"name": name, "symbols": symbols, "recipients": recipients, "log_text": ""}
            self.configs[name] = config_data
            save_json(CONFIG_FILE, self.configs)
            self.tree.insert("", "end", iid=name, text=name, values=(",".join(symbols), ",".join([r['name'] for r in recipients]), "Yes"))
            worker = TradeWorker(config_data, self.email_sender, self.log_box)
            self.workers[name] = worker
            threading.Thread(target=worker.run, daemon=True).start()
            win.destroy()

        tk.Button(win, text="Save Config", bg="#4caf50", fg="white", command=save).pack(pady=10)

    def manage_users_config(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showerror("Error", "Select a configuration")
            return
        config_name = selected[0]
        config = self.configs[config_name]

        win = tk.Toplevel(self)
        win.title(f"Manage Users in {config_name}")
        win.geometry("400x400")
        listbox = tk.Listbox(win, selectmode="multiple")
        listbox.pack(fill="both", expand=True)
        for u in config['recipients']:
            listbox.insert(tk.END, f"{u['name']} ({u['email']})")

        def add_users():
            selected_users = self.user_listbox.curselection()
            for i in selected_users:
                u = list(self.users.values())[i]
                if u not in config['recipients']:
                    config['recipients'].append(u)
            save_json(CONFIG_FILE, self.configs)
            listbox.delete(0, tk.END)
            for u in config['recipients']:
                listbox.insert(tk.END, f"{u['name']} ({u['email']})")
            self.workers[config_name].refresh_new_users()

        def delete_users():
            selected_indices = listbox.curselection()
            for i in reversed(selected_indices):
                del config['recipients'][i]
            save_json(CONFIG_FILE, self.configs)
            listbox.delete(0, tk.END)
            for u in config['recipients']:
                listbox.insert(tk.END, f"{u['name']} ({u['email']})")

        tk.Button(win, text="Add Selected Users", bg="#4caf50", fg="white", command=add_users).pack(pady=5)
        tk.Button(win, text="Remove Selected Users", bg="#f44336", fg="white", command=delete_users).pack(pady=5)

    # -----------------------
    # Config Control Buttons
    # -----------------------
    def refresh_config(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showerror("Error", "Select a configuration")
            return
        for name in selected:
            worker = self.workers.get(name)
            if worker:
                worker.refresh_new_users()
                worker.start()
                self.tree.set(name, column="Active", value="Yes")  # Update status to active
                self.log_box.insert(tk.END, f"🔄 Config {name} refreshed, sending to new users\n")

    def stop_config(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showerror("Error", "Select a configuration")
            return
        for name in selected:
            worker = self.workers.get(name)
            if worker:
                worker.stop()
                self.tree.set(name, column="Active", value="No")  # Update status to inactive
                self.log_box.insert(tk.END, f"⏸ Config {name} stopped\n")

    def start_config(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showerror("Error", "Select a configuration")
            return
        for name in selected:
            worker = self.workers.get(name)
            if worker:
                worker.start()
                self.tree.set(name, column="Active", value="Yes")  # Update status to active
                self.log_box.insert(tk.END, f"▶️ Config {name} started\n")

    # -----------------------
    # Start existing configs
    # -----------------------
    def start_existing_configs(self):
        for config_name, config_data in self.configs.items():
            worker = TradeWorker(config_data, self.email_sender, self.log_box)
            self.workers[config_name] = worker
            threading.Thread(target=worker.run, daemon=True).start()
            self.tree.insert("", "end", iid=config_name, text=config_name, values=(",".join(config_data['symbols']), ",".join([r['name'] for r in config_data['recipients']]), "Yes"))

if __name__ == "__main__":
    app = TradingApp()
    app.mainloop()
