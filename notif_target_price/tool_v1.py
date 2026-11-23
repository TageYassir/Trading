"""
Pip Alert Notifier — Updated to use target price instead of pips

Changes from previous version:
- Replaced the "pips" input with a direct "target price" input.
- When creating/editing a notification the user provides:
    - Pair (e.g., EURUSD or EXCHANGE:SYMBOL)
    - Target price (absolute price level to watch)
    - (Optional) Direction radio stays to clarify intended crossing direction,
      but the target will be validated against the current market price and
      direction will be auto-corrected if inconsistent.
- Worker monitors the market price and sends email when the target is crossed.
- After sending, notification is marked SENT and monitoring stops (reset).
- Users/recipients management and EmailSender are kept as before.

Notes:
- Ensure tvDatafeed credentials/environment are configured for price fetching.
- Email credentials remain hard-coded in this sample (same as before). Replace or
  add UI to configure credentials for production use.
"""
import tkinter as tk
from tkinter import messagebox, ttk, simpledialog
import threading
import time
import json
import os
from tvDatafeed import TvDatafeed, Interval
import urllib.parse
import re
import uuid
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

CONFIG_FILE = "configs.json"
USERS_FILE = "users.json"
APP_ICON = "icon_notif.ico"

def save_json(file, data):
    with open(file, "w") as f:
        json.dump(data, f, indent=4)

def load_json(file):
    if os.path.exists(file):
        with open(file, "r") as f:
            return json.load(f)
    return {}

def parse_pair_input(text: str):
    text = text.strip()
    if ":" in text:
        parts = text.split(":")
        if len(parts) == 2:
            a, b = parts[0].upper(), parts[1].upper()
            if re.match(r"^[A-Z_0-9]+$", a) and re.search(r"[A-Z]", b):
                return a, b
            else:
                return b, a
    if "symbol=" in text:
        query = text.split("symbol=")[-1]
        decoded = urllib.parse.unquote(query)
        if ":" in decoded:
            exchange, symbol = decoded.split(":", 1)
            return exchange.upper(), symbol.upper()
        else:
            return "OANDA", decoded.upper()
    match = re.search(r"/symbols/([^/]+)/?", text)
    if match:
        raw = match.group(1)
        if "-" in raw:
            parts = raw.split("-")
            exchange = parts[0]
            symbol = "-".join(parts[1:])
            return exchange.upper(), symbol.upper()
        else:
            return "OANDA", raw.upper()
    if re.match(r"^[A-Za-z]{6,7}$", text):
        return "OANDA", text.upper()
    return None, None

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
            server = smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=30)
            server.starttls()
            server.login(self.email, self.password)
            server.send_message(msg)
            server.quit()
            return True
        except Exception as e:
            print(f"Failed to send email to {to_email}: {e}")
            return False

class NotificationWorker(threading.Thread):
    def __init__(self, notif, email_sender, ui_log_callback):
        super().__init__(daemon=True)
        self.notif = notif
        self.email_sender = email_sender
        self.ui_log = ui_log_callback
        self.tv = TvDatafeed()
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def stopped(self):
        return self._stop_event.is_set()

    def fetch_price(self):
        exchange = self.notif.get("exchange") or "OANDA"
        symbol = self.notif.get("symbol")
        try:
            df = self.tv.get_hist(symbol=symbol, exchange=exchange, interval=Interval.in_1_minute, n_bars=1)
            if df is None or df.empty:
                if exchange != "OANDA":
                    df = self.tv.get_hist(symbol=symbol, exchange="OANDA", interval=Interval.in_1_minute, n_bars=1)
            if df is None or df.empty:
                return None
            price = df['close'].iloc[-1]
            return float(price)
        except Exception as e:
            print(f"Price fetch error for {exchange}:{symbol} -> {e}")
            return None

    def run(self):
        while not self.stopped() and self.notif.get("active", True) and self.notif.get("status") != "SENT":
            price = self.fetch_price()
            if price is None:
                self.ui_log(f"⚠️ Could not fetch price for {self.notif['exchange']}:{self.notif['symbol']}")
            else:
                target = float(self.notif.get("target_price"))
                direction = self.notif.get("direction", "AUTO")
                pair_display = f"{self.notif['exchange']}:{self.notif['symbol']}"
                self.ui_log(f"ℹ️ {pair_display} current {price:.6f} target {target:.6f} ({direction})")
                crossed = False
                # Determine crossing based on target and direction
                if direction == "UP":
                    if price >= target:
                        crossed = True
                elif direction == "DOWN":
                    if price <= target:
                        crossed = True
                else:  # AUTO: infer direction
                    if target >= self.notif.get("start_price"):
                        if price >= target:
                            crossed = True
                    else:
                        if price <= target:
                            crossed = True

                if crossed:
                    recipients = self.notif.get("recipients", [])
                    message_body = (f"Pair {self.notif['symbol']} ({self.notif['exchange']}) hit the target.\n\n"
                                    f"Start price: {self.notif.get('start_price')}\n"
                                    f"Current price: {price}\n"
                                    f"Target price: {target}\n\n"
                                    "Regards,\nTrading Alert Bot")
                    success_all = True
                    for r in recipients:
                        sent = self.email_sender.send_email(r['email'], f"Trade Alert {self.notif['symbol']}", message_body)
                        if sent:
                            self.ui_log(f"✅ Sent alert for {self.notif['symbol']} to {r['email']}")
                        else:
                            self.ui_log(f"❌ Failed to send alert for {self.notif['symbol']} to {r['email']}")
                            success_all = False
                    self.notif['status'] = "SENT" if success_all else "FAILED"
                    self.notif['active'] = False
                    self.stop()
                    break
            for _ in range(10):
                if self.stopped():
                    break
                time.sleep(1)

class TradingApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Target Price Alert Notifier")
        self.geometry("1000x650")
        if os.path.exists(APP_ICON):
            try:
                self.iconbitmap(APP_ICON)
            except Exception:
                pass

        self.notifs = load_json(CONFIG_FILE)
        self.users = load_json(USERS_FILE)
        self.workers = {}

        self.email_sender = EmailSender(
            smtp_server="smtp.gmail.com",
            smtp_port=587,
            email="fftt7252@gmail.com",
            password="soaewjwyyvdziwwc"
        )

        self.init_ui()
        self.start_existing_notifs()
        self.after(500, self.prompt_add_on_start)

    def prompt_add_on_start(self):
        if messagebox.askyesno("Add Notification", "Do you want to add a new notification now?"):
            self.add_notif_dialog()

    def init_ui(self):
        user_frame = tk.LabelFrame(self, text="Users (recipients)", padx=10, pady=5)
        user_frame.pack(side="top", fill="x", padx=10, pady=5)
        self.user_listbox = tk.Listbox(user_frame, selectmode="multiple", width=60, bg="#eef6ff")
        self.user_listbox.pack(side="left", padx=5)
        btn_user_frame = tk.Frame(user_frame)
        btn_user_frame.pack(side="left", padx=10)
        tk.Button(btn_user_frame, text="Add User", bg="#4caf50", fg="white", command=self.add_user).pack(pady=2, fill="x")
        tk.Button(btn_user_frame, text="Delete User", bg="#f44336", fg="white", command=self.delete_user).pack(pady=2, fill="x")
        tk.Button(btn_user_frame, text="Refresh Users", command=self.refresh_users).pack(pady=2, fill="x")

        notif_frame = tk.LabelFrame(self, text="Notifications", padx=10, pady=5)
        notif_frame.pack(fill="both", expand=False, padx=10, pady=5)
        self.notif_tree = ttk.Treeview(notif_frame, columns=("Pair", "Target", "Direction", "Status"), height=8)
        self.notif_tree.heading("#0", text="ID")
        self.notif_tree.heading("Pair", text="Pair")
        self.notif_tree.heading("Target", text="Target Price")
        self.notif_tree.heading("Direction", text="Dir")
        self.notif_tree.heading("Status", text="Status")
        self.notif_tree.column("#0", width=120)
        self.notif_tree.pack(fill="x")
        btn_notif_frame = tk.Frame(notif_frame)
        btn_notif_frame.pack(fill="x", pady=5)
        tk.Button(btn_notif_frame, text="Add Notif", bg="#2196f3", fg="white", command=self.add_notif_dialog).pack(side="left", padx=4)
        tk.Button(btn_notif_frame, text="Edit Notif", bg="#9c27b0", fg="white", command=self.edit_selected_notif).pack(side="left", padx=4)
        tk.Button(btn_notif_frame, text="Delete Notif", bg="#f44336", fg="white", command=self.delete_selected_notif).pack(side="left", padx=4)
        tk.Button(btn_notif_frame, text="Start Notif", bg="#4caf50", fg="white", command=self.start_selected_notif).pack(side="left", padx=4)
        tk.Button(btn_notif_frame, text="Stop Notif", bg="#ff9800", fg="white", command=self.stop_selected_notif).pack(side="left", padx=4)
        tk.Button(btn_notif_frame, text="Refresh", command=self.refresh_notif_tree).pack(side="left", padx=4)

        log_frame = tk.LabelFrame(self, text="Logs", padx=10, pady=5)
        log_frame.pack(fill="both", expand=True, padx=10, pady=5)
        self.log_box = tk.Text(log_frame, height=18, bg="black", fg="lime")
        self.log_box.pack(fill="both", expand=True)

        self.refresh_users()
        self.refresh_notif_tree()

    def ui_log(self, msg):
        entry = f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {msg}\n"
        self.log_box.insert(tk.END, entry)
        self.log_box.see(tk.END)

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
            for nid, n in list(self.notifs.items()):
                n['recipients'] = [r for r in n.get('recipients', []) if r['email'] != email]
        save_json(USERS_FILE, self.users)
        save_json(CONFIG_FILE, self.notifs)
        self.refresh_users()
        self.refresh_notif_tree()

    def refresh_notif_tree(self):
        for item in self.notif_tree.get_children():
            self.notif_tree.delete(item)
        for nid, n in self.notifs.items():
            pair = f"{n.get('exchange')}:{n.get('symbol')}"
            target = n.get('target_price')
            direction = n.get('direction', 'AUTO')
            status = n.get('status', 'WAITING')
            self.notif_tree.insert("", "end", iid=nid, text=nid,
                                   values=(pair, f"{target:.6f}" if target else "", direction, status))

    def add_notif_dialog(self):
        win = tk.Toplevel(self)
        win.title("Add Notification (Target Price)")
        win.geometry("420x420")

        tk.Label(win, text="Pair (e.g., EURUSD or EXCHANGE:SYMBOL):").pack(pady=4)
        entry_pair = tk.Entry(win, width=40)
        entry_pair.pack()

        tk.Label(win, text="Target Price (absolute):").pack(pady=4)
        entry_target = tk.Entry(win, width=20)
        entry_target.pack()

        tk.Label(win, text="Direction (optional):").pack(pady=4)
        dir_var = tk.StringVar(value="AUTO")
        tk.Radiobutton(win, text="AUTO (infer from start price)", variable=dir_var, value="AUTO").pack()
        tk.Radiobutton(win, text="UP (price rises to target)", variable=dir_var, value="UP").pack()
        tk.Radiobutton(win, text="DOWN (price falls to target)", variable=dir_var, value="DOWN").pack()

        tk.Label(win, text="Select recipients (users):").pack(pady=4)
        rec_listbox = tk.Listbox(win, selectmode="multiple", width=40, height=6)
        rec_listbox.pack()
        for u in self.users.values():
            rec_listbox.insert(tk.END, f"{u['name']} ({u['email']})")

        def save():
            pair_text = entry_pair.get().strip()
            target_text = entry_target.get().strip()
            if not pair_text or not target_text:
                messagebox.showerror("Error", "Fill pair and target")
                return
            try:
                target_price = float(target_text)
            except Exception:
                messagebox.showerror("Error", "Invalid target price")
                return
            exchange, symbol = parse_pair_input(pair_text)
            if not exchange or not symbol:
                messagebox.showerror("Error", "Cannot parse pair")
                return
            # get current price
            tv = TvDatafeed()
            try:
                df = tv.get_hist(symbol=symbol, exchange=exchange, interval=Interval.in_1_minute, n_bars=1)
                if df is None or df.empty:
                    if exchange != "OANDA":
                        df = tv.get_hist(symbol=symbol, exchange="OANDA", interval=Interval.in_1_minute, n_bars=1)
                if df is None or df.empty:
                    messagebox.showerror("Error", f"Could not fetch price for {exchange}:{symbol}")
                    return
                start_price = float(df['close'].iloc[-1])
            except Exception as e:
                messagebox.showerror("Error", f"Failed to fetch current price: {e}")
                return

            selected = rec_listbox.curselection()
            if not selected:
                messagebox.showerror("Error", "Select at least one recipient")
                return
            recipients = []
            all_users = list(self.users.values())
            for i in selected:
                recipients.append(all_users[i])

            direction = dir_var.get()
            # auto-correct direction if inconsistent
            if direction == "AUTO":
                direction_label = "AUTO"
            else:
                # check if direction consistent with target vs start
                if direction == "UP" and target_price <= start_price:
                    if not messagebox.askyesno("Inconsistent direction", "Target is not above current price. Continue with UP?"):
                        return
                if direction == "DOWN" and target_price >= start_price:
                    if not messagebox.askyesno("Inconsistent direction", "Target is not below current price. Continue with DOWN?"):
                        return
                direction_label = direction

            nid = str(uuid.uuid4())
            notif = {
                "id": nid,
                "exchange": exchange,
                "symbol": symbol,
                "direction": direction_label,
                "start_price": start_price,
                "target_price": target_price,
                "recipients": recipients,
                "active": True,
                "status": "WAITING"
            }
            self.notifs[nid] = notif
            save_json(CONFIG_FILE, self.notifs)
            self.refresh_notif_tree()
            self.start_notif_worker(nid)
            win.destroy()

        tk.Button(win, text="Save Notification", bg="#4caf50", fg="white", command=save).pack(pady=8)

    def edit_selected_notif(self):
        selected = self.notif_tree.selection()
        if not selected:
            messagebox.showerror("Error", "Select a notification")
            return
        nid = selected[0]
        notif = self.notifs.get(nid)
        if not notif:
            messagebox.showerror("Error", "Notification not found")
            return

        win = tk.Toplevel(self)
        win.title("Edit Notification (Target Price)")
        win.geometry("420x420")

        tk.Label(win, text="Pair:").pack(pady=4)
        lbl_pair = tk.Label(win, text=f"{notif['exchange']}:{notif['symbol']}")
        lbl_pair.pack()

        tk.Label(win, text="Target Price:").pack(pady=4)
        entry_target = tk.Entry(win, width=20)
        entry_target.insert(0, str(notif.get('target_price')))
        entry_target.pack()

        tk.Label(win, text="Direction:").pack(pady=4)
        dir_var = tk.StringVar(value=notif.get('direction', 'AUTO'))
        tk.Radiobutton(win, text="AUTO (infer)", variable=dir_var, value="AUTO").pack()
        tk.Radiobutton(win, text="UP", variable=dir_var, value="UP").pack()
        tk.Radiobutton(win, text="DOWN", variable=dir_var, value="DOWN").pack()

        tk.Label(win, text="Recipients:").pack(pady=4)
        rec_listbox = tk.Listbox(win, selectmode="multiple", width=40, height=6)
        rec_listbox.pack()
        all_users = list(self.users.values())
        for u in all_users:
            rec_listbox.insert(tk.END, f"{u['name']} ({u['email']})")
        existing_emails = {r['email'] for r in notif.get('recipients', [])}
        for idx, u in enumerate(all_users):
            if u['email'] in existing_emails:
                rec_listbox.selection_set(idx)

        def save_edit():
            target_text = entry_target.get().strip()
            try:
                target_price = float(target_text)
            except Exception:
                messagebox.showerror("Error", "Invalid target price")
                return
            selected_idx = rec_listbox.curselection()
            if not selected_idx:
                messagebox.showerror("Error", "Select at least one recipient")
                return
            recipients = [all_users[i] for i in selected_idx]

            # recalc start price (reset start to now)
            exchange = notif['exchange']
            symbol = notif['symbol']
            tv = TvDatafeed()
            try:
                df = tv.get_hist(symbol=symbol, exchange=exchange, interval=Interval.in_1_minute, n_bars=1)
                if df is None or df.empty and exchange != "OANDA":
                    df = tv.get_hist(symbol=symbol, exchange="OANDA", interval=Interval.in_1_minute, n_bars=1)
                if df is None or df.empty:
                    messagebox.showerror("Error", "Could not fetch current price")
                    return
                start_price = float(df['close'].iloc[-1])
            except Exception as e:
                messagebox.showerror("Error", f"Failed to fetch current price: {e}")
                return

            direction = dir_var.get()
            if direction != "AUTO":
                if direction == "UP" and target_price <= start_price:
                    if not messagebox.askyesno("Inconsistent direction", "Target is not above current price. Continue with UP?"):
                        return
                if direction == "DOWN" and target_price >= start_price:
                    if not messagebox.askyesno("Inconsistent direction", "Target is not below current price. Continue with DOWN?"):
                        return

            notif['target_price'] = target_price
            notif['direction'] = direction
            notif['start_price'] = start_price
            notif['recipients'] = recipients
            notif['active'] = True
            notif['status'] = "WAITING"
            save_json(CONFIG_FILE, self.notifs)
            self.refresh_notif_tree()
            self.stop_notif_worker(nid)
            self.start_notif_worker(nid)
            win.destroy()

        tk.Button(win, text="Save Changes", bg="#4caf50", fg="white", command=save_edit).pack(pady=8)

    def delete_selected_notif(self):
        selected = self.notif_tree.selection()
        if not selected:
            messagebox.showerror("Error", "Select a notification")
            return
        for nid in selected:
            self.stop_notif_worker(nid)
            if nid in self.notifs:
                del self.notifs[nid]
        save_json(CONFIG_FILE, self.notifs)
        self.refresh_notif_tree()

    def start_selected_notif(self):
        selected = self.notif_tree.selection()
        if not selected:
            messagebox.showerror("Error", "Select a notification")
            return
        for nid in selected:
            if nid in self.notifs:
                self.notifs[nid]['active'] = True
                self.notifs[nid]['status'] = "WAITING"
                save_json(CONFIG_FILE, self.notifs)
                self.start_notif_worker(nid)
        self.refresh_notif_tree()

    def stop_selected_notif(self):
        selected = self.notif_tree.selection()
        if not selected:
            messagebox.showerror("Error", "Select a notification")
            return
        for nid in selected:
            self.stop_notif_worker(nid)
            if nid in self.notifs:
                self.notifs[nid]['active'] = False
                save_json(CONFIG_FILE, self.notifs)
        self.refresh_notif_tree()

    def start_notif_worker(self, nid):
        if nid in self.workers:
            self.stop_notif_worker(nid)
        notif = self.notifs.get(nid)
        if not notif:
            return
        worker = NotificationWorker(notif, self.email_sender, self.ui_log)
        self.workers[nid] = worker
        worker.start()
        self.ui_log(f"▶️ Started monitoring {notif['exchange']}:{notif['symbol']} target {notif['target_price']}")
        self.refresh_notif_tree()

    def stop_notif_worker(self, nid):
        worker = self.workers.get(nid)
        if worker:
            try:
                worker.stop()
            except Exception:
                pass
            del self.workers[nid]
            self.ui_log(f"⏸ Stopped monitoring {nid}")
        self.refresh_notif_tree()

    def start_existing_notifs(self):
        for nid, notif in self.notifs.items():
            if notif.get('active', True) and notif.get('status') != "SENT":
                self.start_notif_worker(nid)

if __name__ == "__main__":
    app = TradingApp()
    app.mainloop()