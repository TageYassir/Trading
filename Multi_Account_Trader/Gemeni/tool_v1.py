#!/usr/bin/env python3
"""
MT5 Stealth Manager - Parallel Multi-Account Prop Firm Trader
"""
import os
import sys
import json
import threading
import queue
import time
import datetime
import traceback
import logging
import subprocess
import shutil
import random
from pathlib import Path
import concurrent.futures

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

try:
    import MetaTrader5 as mt5
except Exception:
    mt5 = None

# --- CONFIGURATION ---
ACCOUNTS_FILE = "mt5_accounts.json"
SETTINGS_FILE = "mt5_settings.json"
BASE_MT5_PATH = r"C:\Program Files\MetaTrader 5"  # Change this if your base install is elsewhere
PORTABLE_DIR = r"C:\MT5_Portable_Terminals"  # Where the script will clone folders

DEFAULT_SETTINGS = {
    "init_delay": 1.0,
    "login_delay": 1.0,
    "trade_delay": 0.5,
    "retry_delay": 1.0,
    "max_retries": 2,
    "positions_refresh_interval": 30.0,
    "auto_refresh_positions": False,
    "debug_mode": True,
    "filling_mode": "FOK",
    "prop_safe_mode": True  # Enables Jitter and Lot Variance
}


def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                settings = json.load(f)
            for k, v in DEFAULT_SETTINGS.items():
                if k not in settings: settings[k] = v
            return settings
        except:
            pass
    return DEFAULT_SETTINGS.copy()


def save_settings(settings):
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=2)


SETTINGS = load_settings()


def setup_logging():
    log_dir = "logs"
    if not os.path.exists(log_dir): os.makedirs(log_dir)
    logger = logging.getLogger('MT5Manager')
    logger.setLevel(logging.DEBUG if SETTINGS.get('debug_mode', True) else logging.INFO)
    logger.handlers.clear()

    fh = logging.FileHandler(os.path.join(log_dir, f'mt5_manager_{datetime.datetime.now().strftime("%Y%m%d")}.log'),
                             encoding='utf-8')
    ch = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter('%(asctime)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)
    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


logger = setup_logging()


def default_store():
    return {"accounts": [], "groups": [{"name": "default", "vol_multiplier": 1.0, "active": True}]}


def load_store():
    if not os.path.exists(ACCOUNTS_FILE): return default_store()
    with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    if "accounts" not in data: data["accounts"] = []
    if "groups" not in data: data["groups"] = [{"name": "default", "vol_multiplier": 1.0, "active": True}]
    return data


def save_store(store):
    with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)


# --- AUTO PORTABLE GENERATOR ---
def ensure_portable_terminal(account_id):
    """Clones the base MT5 folder for a specific account to ensure isolated execution."""
    if not os.path.exists(PORTABLE_DIR):
        os.makedirs(PORTABLE_DIR)

    target_dir = os.path.join(PORTABLE_DIR, f"Acc_{account_id}")
    terminal_path = os.path.join(target_dir, "terminal64.exe")

    if not os.path.exists(target_dir):
        logger.info(f"Creating portable MT5 instance for account {account_id}...")
        try:
            shutil.copytree(BASE_MT5_PATH, target_dir)
            logger.info(f"Successfully cloned terminal to {target_dir}")
        except Exception as e:
            logger.error(f"Failed to clone MT5 directory: {e}")
            return None

    return terminal_path


# --- PARALLEL WORKER FUNCTION ---
# This MUST be a top-level function so ProcessPoolExecutor can pickle it
def execute_trade_worker(acc, trade_params, prop_safe_mode):
    """Executes a single trade in an isolated process to prevent MT5 API blocking."""
    try:
        import MetaTrader5 as mt5_worker

        # 1. Prop Safe Layer: Jitter
        if prop_safe_mode:
            jitter = random.uniform(0.1, 0.4)
            time.sleep(jitter)

            # Slight Lot Variance (+0.00 or +0.01) to avoid identical trade sizes
            variance = random.choice([0.0, 0.01])
            trade_params['volume'] = round(trade_params['volume'] + variance, 2)

        # 2. Initialize Terminal (Will start it in background if closed)
        path = acc.get('portable_path')
        if not path or not os.path.exists(path):
            return {"acc": acc['account'], "status": "Error", "msg": "Invalid terminal path"}

        # Use subprocess to enforce /portable flag just in case
        subprocess.Popen([path, '/portable'])
        time.sleep(1)  # Let the process start

        if not mt5_worker.initialize(path=path, login=int(acc['account']), password=acc['password'],
                                     server=acc['server']):
            return {"acc": acc['account'], "status": "Error", "msg": f"Init failed: {mt5_worker.last_error()}"}

        # 3. Execution
        filling_mode = mt5_worker.ORDER_FILLING_FOK if SETTINGS.get(
            'filling_mode') == 'FOK' else mt5_worker.ORDER_FILLING_IOC
        order_type = mt5_worker.ORDER_TYPE_BUY if trade_params['side'] == 'buy' else mt5_worker.ORDER_TYPE_SELL

        tick = mt5_worker.symbol_info_tick(trade_params['symbol'])
        if not tick:
            mt5_worker.shutdown()
            return {"acc": acc['account'], "status": "Error", "msg": "No tick data"}

        price = tick.ask if trade_params['side'] == 'buy' else tick.bid

        req = {
            "action": mt5_worker.TRADE_ACTION_DEAL,
            "symbol": trade_params['symbol'],
            "volume": trade_params['volume'],
            "type": order_type,
            "price": price,
            "deviation": trade_params['deviation'],
            "magic": trade_params['magic'],
            "comment": "Stealth_Copier",
            "type_time": mt5_worker.ORDER_TIME_GTC,
            "type_filling": filling_mode,
        }

        res = mt5_worker.order_send(req)

        # 4. Graceful Disconnect (Leaves terminal running in background)
        mt5_worker.shutdown()

        if res and res.retcode == 10009:
            return {"acc": acc['account'], "status": "Success", "msg": "Trade Executed"}
        else:
            err = res.comment if res else "Unknown Error"
            return {"acc": acc['account'], "status": "Failed", "msg": err}

    except Exception as e:
        return {"acc": acc.get('account', 'Unknown'), "status": "Error", "msg": str(e)}


def close_position_worker(acc, ticket):
    """Worker for closing positions in parallel"""
    try:
        import MetaTrader5 as mt5_worker
        path = acc.get('portable_path')
        if not mt5_worker.initialize(path=path, login=int(acc['account']), password=acc['password'],
                                     server=acc['server']):
            return False

        positions = mt5_worker.positions_get(ticket=ticket)
        if positions:
            pos = positions[0]
            tick = mt5_worker.symbol_info_tick(pos.symbol)
            order_type = mt5_worker.ORDER_TYPE_SELL if pos.type == mt5_worker.ORDER_TYPE_BUY else mt5_worker.ORDER_TYPE_BUY
            price = tick.bid if order_type == mt5_worker.ORDER_TYPE_SELL else tick.ask

            req = {
                "action": mt5_worker.TRADE_ACTION_DEAL,
                "symbol": pos.symbol,
                "volume": pos.volume,
                "type": order_type,
                "position": pos.ticket,
                "price": price,
                "deviation": 50,
                "magic": 0,
                "comment": "Stealth_Close",
                "type_time": mt5_worker.ORDER_TIME_GTC,
                "type_filling": mt5_worker.ORDER_FILLING_IOC,
            }
            res = mt5_worker.order_send(req)
            mt5_worker.shutdown()
            return res.retcode == 10009 if res else False
        mt5_worker.shutdown()
        return False
    except:
        return False


# --- GUI APPLICATION ---
class MT5ManagerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("MT5 Stealth Manager — Parallel Trader")
        self.root.geometry("1150x750")

        self.store = load_store()
        self.ensure_account_defaults()

        self.positions_q = queue.Queue()
        self.auto_refresh = tk.BooleanVar(value=SETTINGS.get('auto_refresh_positions', False))
        self.refresh_interval = tk.DoubleVar(value=SETTINGS.get('positions_refresh_interval', 30))
        self.prop_safe_var = tk.BooleanVar(value=SETTINGS.get('prop_safe_mode', True))

        # Trading parameters
        self.symbol_var = tk.StringVar(value="EURUSD")
        self.side_var = tk.StringVar(value="buy")
        self.volume_var = tk.StringVar(value="0.1")
        self.deviation_var = tk.StringVar(value="50")
        self.magic_var = tk.StringVar(value="123456")

        self._build_ui()
        self._refresh_lists()
        self._start_positions_refresher_thread()
        self._start_positions_queue_processor()

    def ensure_account_defaults(self):
        for a in self.store.get("accounts", []):
            a.setdefault("account", "")
            a.setdefault("password", "")
            a.setdefault("server", "")
            a.setdefault("active", True)
            a.setdefault("group", "default")
            a.setdefault("portable_path", "")

    def log(self, msg, level='INFO'):
        formatted = f"{datetime.datetime.now().strftime('%H:%M:%S')} [{level}] {msg}"
        self.log_txt.configure(state=tk.NORMAL)
        self.log_txt.insert(tk.END, formatted + "\n")
        self.log_txt.see(tk.END)
        self.log_txt.configure(state=tk.DISABLED)
        logger.info(msg)

    def _build_ui(self):
        main = ttk.Frame(self.root)
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        paned = ttk.PanedWindow(main, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # Left panel - Accounts
        left = ttk.Frame(paned)
        paned.add(left, weight=1)

        acct_frame = ttk.LabelFrame(left, text="Prop Firm Accounts")
        acct_frame.pack(fill=tk.BOTH, expand=True)
        self.accounts_tree = ttk.Treeview(acct_frame, columns=("id", "server", "group", "active", "path"),
                                          show="headings", height=12)
        for col, text, width in [("id", "Account", 80), ("server", "Server", 100), ("group", "Group", 60),
                                 ("active", "Active", 50), ("path", "Portable Path", 150)]:
            self.accounts_tree.heading(col, text=text)
            self.accounts_tree.column(col, width=width, anchor="center" if col != "path" else "w")
        self.accounts_tree.pack(fill=tk.BOTH, expand=True)

        abtns = ttk.Frame(acct_frame)
        abtns.pack(fill=tk.X, pady=4)
        ttk.Button(abtns, text="Add Account", command=self.add_account).pack(side=tk.LEFT, padx=2)
        ttk.Button(abtns, text="Edit", command=self.edit_account).pack(side=tk.LEFT, padx=2)
        ttk.Button(abtns, text="Delete", command=self.remove_account).pack(side=tk.LEFT, padx=2)

        # Right panel
        right = ttk.Frame(paned)
        paned.add(right, weight=2)
        notebook = ttk.Notebook(right)
        notebook.pack(fill=tk.BOTH, expand=True)

        # Trading Tab
        trade_tab = ttk.Frame(notebook)
        notebook.add(trade_tab, text="Stealth Trading (Parallel)")

        trade_frame = ttk.LabelFrame(trade_tab, text="Order Parameters")
        trade_frame.pack(fill=tk.X, padx=4, pady=4)

        row1 = ttk.Frame(trade_frame)
        row1.pack(fill=tk.X, pady=4)
        ttk.Label(row1, text="Symbol:").pack(side=tk.LEFT)
        ttk.Entry(row1, textvariable=self.symbol_var, width=10).pack(side=tk.LEFT, padx=4)
        ttk.Label(row1, text="Volume:").pack(side=tk.LEFT, padx=(8, 0))
        ttk.Entry(row1, textvariable=self.volume_var, width=8).pack(side=tk.LEFT, padx=4)
        ttk.Label(row1, text="Deviation:").pack(side=tk.LEFT, padx=(8, 0))
        ttk.Entry(row1, textvariable=self.deviation_var, width=5).pack(side=tk.LEFT, padx=4)

        row2 = ttk.Frame(trade_frame)
        row2.pack(fill=tk.X, pady=4)
        ttk.Radiobutton(row2, text="BUY", variable=self.side_var, value="buy").pack(side=tk.LEFT)
        ttk.Radiobutton(row2, text="SELL", variable=self.side_var, value="sell").pack(side=tk.LEFT, padx=8)
        ttk.Label(row2, text="Magic:").pack(side=tk.LEFT, padx=(8, 0))
        ttk.Entry(row2, textvariable=self.magic_var, width=8).pack(side=tk.LEFT, padx=4)

        act_frame = ttk.LabelFrame(trade_tab, text="Execution")
        act_frame.pack(fill=tk.X, padx=4, pady=4)
        ttk.Checkbutton(act_frame, text="Enable Prop Safe Mode (Jitter + Lot Variance)",
                        variable=self.prop_safe_var).pack(pady=4)

        btn_frame = ttk.Frame(act_frame)
        btn_frame.pack(fill=tk.X, pady=6)
        ttk.Button(btn_frame, text="FIRE TRADE: All Active Accounts", command=self.bid_all_accounts).pack(fill=tk.X,
                                                                                                          padx=10,
                                                                                                          pady=5)

        # Positions Tab
        pos_tab = ttk.Frame(notebook)
        notebook.add(pos_tab, text="Positions")
        pos_frame = ttk.LabelFrame(pos_tab, text="Open Positions")
        pos_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self.positions_tree = ttk.Treeview(pos_frame,
                                           columns=("account", "ticket", "symbol", "type", "volume", "profit"),
                                           show="headings")
        for c, lab in [("account", "Account"), ("ticket", "Ticket"), ("symbol", "Symbol"), ("type", "Type"),
                       ("volume", "Vol"), ("profit", "Profit")]:
            self.positions_tree.heading(c, text=lab)
            self.positions_tree.column(c, width=90, anchor="center")
        self.positions_tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)

        pos_btns = ttk.Frame(pos_tab)
        pos_btns.pack(fill=tk.X, pady=4)
        ttk.Button(pos_btns, text="Refresh Now",
                   command=lambda: threading.Thread(target=self._collect_positions_across_accounts,
                                                    daemon=True).start()).pack(side=tk.LEFT, padx=4)
        ttk.Button(pos_btns, text="Close Selected", command=self.close_selected_positions).pack(side=tk.RIGHT, padx=4)

        # Log Tab
        log_tab = ttk.Frame(notebook)
        notebook.add(log_tab, text="Log")
        self.log_txt = tk.Text(log_tab, height=15, state=tk.DISABLED, bg='black', fg='#00FF00')
        self.log_txt.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

    def _refresh_lists(self):
        for i in self.accounts_tree.get_children(): self.accounts_tree.delete(i)
        for idx, a in enumerate(self.store.get("accounts", [])):
            active = "Yes" if a.get("active", True) else "No"
            path = a.get("portable_path", "Not Set")
            self.accounts_tree.insert("", "end", iid=str(idx),
                                      values=(a.get("account", ""), a.get("server", ""), a.get("group", "default"),
                                              active, path))

    def add_account(self):
        dlg = AccountDialog(self.root, None, self.store["groups"])
        self.root.wait_window(dlg.top)
        if dlg.result:
            self.store["accounts"].append(dlg.result)
            save_store(self.store)
            self._refresh_lists()

    def edit_account(self):
        sel = self.accounts_tree.selection()
        if not sel: return
        idx = int(sel[0])
        dlg = AccountDialog(self.root, self.store["accounts"][idx], self.store["groups"])
        self.root.wait_window(dlg.top)
        if dlg.result:
            self.store["accounts"][idx] = dlg.result
            save_store(self.store)
            self._refresh_lists()

    def remove_account(self):
        sel = self.accounts_tree.selection()
        if not sel: return
        idx = int(sel[0])
        del self.store["accounts"][idx]
        save_store(self.store)
        self._refresh_lists()

    # --- PARALLEL EXECUTION ENGINE ---
    def bid_all_accounts(self):
        accounts = [a for a in self.store.get("accounts", []) if a.get("active", True)]
        if not accounts:
            messagebox.showinfo("Trade All", "No active accounts")
            return

        trade_params = {
            "symbol": self.symbol_var.get().strip(),
            "side": self.side_var.get(),
            "volume": float(self.volume_var.get()),
            "deviation": int(self.deviation_var.get() or 50),
            "magic": int(self.magic_var.get() or 0)
        }

        self.log(
            f"🚀 FIRING PARALLEL TRADE: {trade_params['side'].upper()} {trade_params['symbol']} across {len(accounts)} accounts...")
        threading.Thread(target=self._run_parallel_pool, args=(accounts, trade_params), daemon=True).start()

    def _run_parallel_pool(self, accounts, trade_params):
        prop_safe = self.prop_safe_var.get()

        # ProcessPoolExecutor achieves true parallelism bypassing the Python GIL and MT5 module locks
        with concurrent.futures.ProcessPoolExecutor(max_workers=len(accounts)) as executor:
            futures = {executor.submit(execute_trade_worker, acc, dict(trade_params), prop_safe): acc for acc in
                       accounts}

            for future in concurrent.futures.as_completed(futures):
                try:
                    res = future.result()
                    symbol = "✅" if res['status'] == "Success" else "❌"
                    self.log(f"{symbol} Account {res['acc']}: {res['status']} | {res['msg']}")
                except Exception as exc:
                    self.log(f"❌ Thread Exception: {exc}", "ERROR")

    # --- POSITIONS (Also parallelized) ---
    def close_selected_positions(self):
        sel = self.positions_tree.selection()
        if not sel: return

        tasks = []
        for iid in sel:
            try:
                acct, ticket = iid.split("_", 1)
                acct_info = next((a for a in self.store["accounts"] if str(a.get("account")) == acct), None)
                if acct_info: tasks.append((acct_info, int(ticket)))
            except:
                pass

        if not tasks: return
        self.log(f"Closing {len(tasks)} positions in parallel...")

        def run_close_pool():
            with concurrent.futures.ProcessPoolExecutor(max_workers=len(tasks)) as executor:
                futures = [executor.submit(close_position_worker, acc, tick) for acc, tick in tasks]
                concurrent.futures.wait(futures)
            self._collect_positions_across_accounts()

        threading.Thread(target=run_close_pool, daemon=True).start()

    def _collect_positions_across_accounts(self):
        # Fallback to sequential for background monitoring to save CPU
        accounts = [a for a in self.store.get("accounts", []) if a.get("active", True)]
        all_positions = []

        for a in accounts:
            path = a.get("portable_path")
            if not path: continue
            try:
                if mt5.initialize(path=path, login=int(a["account"]), password=a["password"], server=a["server"]):
                    positions = mt5.positions_get()
                    if positions:
                        for p in positions:
                            all_positions.append({
                                "account": str(a["account"]), "ticket": int(p.ticket), "symbol": p.symbol,
                                "type": "buy" if int(p.type) == 0 else "sell", "volume": float(p.volume),
                                "profit": float(getattr(p, "profit", 0.0)),
                            })
                    mt5.shutdown()
            except:
                pass

        self.positions_q.put({"positions": all_positions, "ts": time.time()})

    def _start_positions_refresher_thread(self):
        def refresher():
            while True:
                if self.auto_refresh.get(): self._collect_positions_across_accounts()
                time.sleep(self.refresh_interval.get())

        threading.Thread(target=refresher, daemon=True).start()

    def _start_positions_queue_processor(self):
        def processor():
            while True:
                try:
                    item = self.positions_q.get(timeout=0.5)
                except:
                    continue
                self.root.after(0, self._update_positions_ui, item["positions"])

        threading.Thread(target=processor, daemon=True).start()

    def _update_positions_ui(self, positions):
        for i in self.positions_tree.get_children(): self.positions_tree.delete(i)
        for p in positions:
            self.positions_tree.insert("", "end", iid=f"{p['account']}_{p['ticket']}",
                                       values=(p["account"], p["ticket"], p["symbol"], p["type"], f"{p['volume']:.2f}",
                                               f"{p['profit']:.2f}"))

    def on_closing(self):
        self.root.destroy()


# --- DIALOGS ---
class AccountDialog:
    def __init__(self, parent, account, groups):
        self.top = tk.Toplevel(parent)
        self.top.transient(parent)
        self.top.grab_set()
        self.result = None
        self.account = dict(account) if account else {"account": "", "password": "", "server": "", "active": True,
                                                      "portable_path": ""}
        self.groups = groups
        self._build()

    def _build(self):
        f = ttk.Frame(self.top)
        f.pack(padx=8, pady=8)

        ttk.Label(f, text="Account ID:").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.acc_e = ttk.Entry(f)
        self.acc_e.grid(row=0, column=1, pady=2)

        ttk.Label(f, text="Password:").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.pwd_e = ttk.Entry(f, show="*")
        self.pwd_e.grid(row=1, column=1, pady=2)

        ttk.Label(f, text="Server:").grid(row=2, column=0, sticky=tk.W, pady=2)
        self.serv_e = ttk.Entry(f)
        self.serv_e.grid(row=2, column=1, pady=2)

        ttk.Label(f, text="Portable Path:").grid(row=3, column=0, sticky=tk.W, pady=2)
        self.path_e = ttk.Entry(f, width=30)
        self.path_e.grid(row=3, column=1, pady=2)
        ttk.Button(f, text="Auto-Create Folder", command=self.auto_create_path).grid(row=3, column=2, padx=4)

        self.active_var = tk.BooleanVar(value=self.account.get("active", True))
        ttk.Checkbutton(f, text="Active", variable=self.active_var).grid(row=4, column=0, columnspan=2, pady=4)

        self.acc_e.insert(0, self.account.get("account", ""))
        self.pwd_e.insert(0, self.account.get("password", ""))
        self.serv_e.insert(0, self.account.get("server", ""))
        self.path_e.insert(0, self.account.get("portable_path", ""))

        ttk.Button(self.top, text="Save Account", command=self.ok).pack(pady=6)

    def auto_create_path(self):
        acc_id = self.acc_e.get().strip()
        if not acc_id:
            messagebox.showerror("Error", "Enter Account ID first")
            return
        path = ensure_portable_terminal(acc_id)
        if path:
            self.path_e.delete(0, tk.END)
            self.path_e.insert(0, path)

    def ok(self):
        accid = self.acc_e.get().strip()
        if not accid: return
        self.result = {
            "account": accid, "password": self.pwd_e.get().strip(),
            "server": self.serv_e.get().strip(), "active": bool(self.active_var.get()),
            "portable_path": self.path_e.get().strip()
        }
        self.top.destroy()


if __name__ == "__main__":
    # Required for multiprocessing on Windows
    import multiprocessing

    multiprocessing.freeze_support()

    root = tk.Tk()
    app = MT5ManagerApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()