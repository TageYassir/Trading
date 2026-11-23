# mt5_multi_manager_with_positions_diag.py
"""
MT5 Multi Account Manager (Positions + Diagnostics)

Sequential per-account initialize/login/action/shutdown flow:
- Ensures each account uses its own MT5 login session
- Avoids conflicts when one account login is accepted and another is refused
- GUI-session mode still supported (when you log into MT5 manually)

Requires: pip install MetaTrader5
Run with the MetaTrader 5 terminal available on the same machine.

Author: assistant (updated for sequential per-account processing)
"""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import json, os, threading, queue, time, datetime
import platform

try:
    import MetaTrader5 as mt5
except Exception:
    mt5 = None

ACCOUNTS_FILE = "version2/mt5_accounts.json"
POSITIONS_REFRESH_INTERVAL = 5.0  # seconds default for auto-refresh

# ---------- MT5/helpers ----------
# Note: we still expose initialize/shutdown helpers but for per-account operations
# we use the explicit per-account initialize/login/shutdown helpers below.

def mt5_available():
    return mt5 is not None

def initialize_terminal(path=None):
    """Initialize MT5 API (returns ok, last_error). Does NOT attempt login."""
    try:
        mt5.shutdown()
    except Exception:
        pass
    try:
        ok = mt5.initialize(path=path) if path else mt5.initialize()
    except Exception:
        ok = False
    return bool(ok), mt5.last_error() if mt5 else ("mt5 module missing",)

def shutdown_terminal():
    try:
        mt5.shutdown()
    except Exception:
        pass

def symbol_pip_value(symbol):
    info = mt5.symbol_info(symbol)
    if info is None:
        return None
    digits = getattr(info, "digits", None)
    if digits is None:
        return None
    return 0.0001 if digits > 3 else 0.01

def get_tick(symbol):
    return mt5.symbol_info_tick(symbol)

def close_all_positions_for_account(log_fn=None):
    """Close all open positions on the currently logged-in account (MT5 session)."""
    positions = mt5.positions_get()
    if positions is None:
        return False, "positions_get returned None"
    if len(positions) == 0:
        return True, "no open positions"
    success = True
    errors = []
    for pos in positions:
        sym = pos.symbol
        vol = pos.volume
        pos_type = pos.type  # 0 buy, 1 sell
        tick = get_tick(sym)
        if tick is None:
            errors.append(f"No tick for {sym}")
            continue
        if pos_type == 0:  # buy -> close with sell
            price = tick.bid
            order_type = mt5.ORDER_TYPE_SELL
        else:
            price = tick.ask
            order_type = mt5.ORDER_TYPE_BUY
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": sym,
            "volume": float(vol),
            "type": order_type,
            "position": int(pos.ticket),
            "price": price,
            "deviation": 50,
            "magic": 0,
            "comment": "close_by_mt5_multi_manager",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        r = mt5.order_send(request)
        if r is None or getattr(r, "retcode", None) not in (10009, 10008, None):
            errors.append(f"Failed to close pos {pos.ticket} on {sym}: {r}")
            success = False
        else:
            if log_fn:
                log_fn(f"Closed position {pos.ticket} symbol={sym} vol={vol}")
        time.sleep(0.15)
    if errors:
        return success, "\n".join(errors)
    return success, "closed all (or none were open)"

def close_position_by_ticket(ticket, log_fn=None):
    """Close a single position by ticket on the currently logged-in account."""
    try:
        positions = mt5.positions_get()
        if not positions:
            return False, "no positions"
        pos = None
        for p in positions:
            if int(p.ticket) == int(ticket):
                pos = p
                break
        if pos is None:
            return False, f"ticket {ticket} not found on this account"
        sym = pos.symbol
        vol = pos.volume
        pos_type = pos.type
        tick = get_tick(sym)
        if tick is None:
            return False, f"no tick for {sym}"
        if pos_type == 0:
            price = tick.bid
            order_type = mt5.ORDER_TYPE_SELL
        else:
            price = tick.ask
            order_type = mt5.ORDER_TYPE_BUY
        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": sym,
            "volume": float(vol),
            "type": order_type,
            "position": int(pos.ticket),
            "price": price,
            "deviation": 50,
            "magic": 0,
            "comment": "close_selected_mt5_multi_manager",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        r = mt5.order_send(req)
        if r is None:
            return False, "order_send returned None"
        ret = getattr(r, "retcode", None)
        if ret is not None and ret not in (10009, 10008):
            return False, f"retcode {ret} result: {r}"
        if log_fn:
            log_fn(f"Closed position {ticket} symbol={sym} vol={vol}")
        return True, f"closed {ticket}"
    except Exception as e:
        return False, str(e)

# ---------- Per-account helpers (sequential) ----------
def fetch_positions_for_account(acc, terminal_path, log_fn=None):
    """
    Initialize, login to acc, fetch positions, then shutdown.
    Returns list of position dicts or None on failure.
    """
    login_id = acc.get("account")
    pwd = acc.get("password", "")
    srv = acc.get("server", "")
    # shutdown any existing session
    try:
        mt5.shutdown()
    except Exception:
        pass
    ok, ierr = initialize_terminal(terminal_path)
    if not ok:
        if log_fn:
            log_fn(f"initialize failed for account {login_id}: {ierr}")
        return None, ierr
    try:
        res = mt5.login(int(login_id), pwd, srv)
    except Exception as e:
        mt5.shutdown()
        if log_fn:
            log_fn(f"login exception for {login_id}: {e}")
        return None, str(e)
    if not res:
        le = mt5.last_error()
        mt5.shutdown()
        if log_fn:
            log_fn(f"login failed for {login_id}: {le}")
        return None, le
    # success: fetch positions
    try:
        positions = mt5.positions_get()
    except Exception as e:
        positions = None
        if log_fn:
            log_fn(f"positions_get error for {login_id}: {e}")
    # collect records
    recs = []
    if positions:
        for p in positions:
            try:
                recs.append({
                    "account": str(login_id),
                    "ticket": int(p.ticket),
                    "symbol": p.symbol,
                    "type": "buy" if int(p.type) == 0 else "sell",
                    "volume": float(p.volume),
                    "price": float(getattr(p, "price_open", getattr(p, "price", 0.0))),
                    "sl": float(getattr(p, "sl", 0.0) or 0.0),
                    "tp": float(getattr(p, "tp", 0.0) or 0.0),
                    "profit": float(getattr(p, "profit", 0.0) or 0.0),
                    "time": int(getattr(p, "time", getattr(p, "time_msc", 0)) or 0)
                })
            except Exception:
                continue
    # shutdown session for this account
    mt5.shutdown()
    # small pause to let terminal settle
    time.sleep(0.25)
    return recs, "ok"

def perform_close_all_for_account(acc, terminal_path, log_fn=None):
    """
    Initialize, login to acc, close all positions, shutdown.
    Returns (ok, message).
    """
    login_id = acc.get("account")
    pwd = acc.get("password", "")
    srv = acc.get("server", "")
    try:
        mt5.shutdown()
    except Exception:
        pass
    ok, ierr = initialize_terminal(terminal_path)
    if not ok:
        if log_fn:
            log_fn(f"initialize failed for account {login_id}: {ierr}")
        return False, ierr
    try:
        res = mt5.login(int(login_id), pwd, srv)
    except Exception as e:
        mt5.shutdown()
        if log_fn:
            log_fn(f"login exception for {login_id}: {e}")
        return False, str(e)
    if not res:
        le = mt5.last_error()
        mt5.shutdown()
        if log_fn:
            log_fn(f"login failed for {login_id}: {le}")
        return False, le
    # logged in: close positions
    ok2, msg = close_all_positions_for_account(log_fn=log_fn)
    # shutdown after operation
    mt5.shutdown()
    time.sleep(0.25)
    return ok2, msg

def perform_close_ticket_for_account(acc, ticket, terminal_path, log_fn=None):
    """
    Initialize, login to acc, close specific ticket, shutdown.
    Returns (ok, msg).
    """
    login_id = acc.get("account")
    pwd = acc.get("password", "")
    srv = acc.get("server", "")
    try:
        mt5.shutdown()
    except Exception:
        pass
    ok, ierr = initialize_terminal(terminal_path)
    if not ok:
        if log_fn:
            log_fn(f"initialize failed for account {login_id}: {ierr}")
        return False, ierr
    try:
        res = mt5.login(int(login_id), pwd, srv)
    except Exception as e:
        mt5.shutdown()
        if log_fn:
            log_fn(f"login exception for {login_id}: {e}")
        return False, str(e)
    if not res:
        le = mt5.last_error()
        mt5.shutdown()
        if log_fn:
            log_fn(f"login failed for {login_id}: {le}")
        return False, le
    # try to close ticket
    ok2, msg = close_position_by_ticket(ticket, log_fn=log_fn)
    mt5.shutdown()
    time.sleep(0.25)
    return ok2, msg

# ---------- Storage ----------
def default_store():
    return {"accounts": [], "groups": [{"name": "default", "vol_multiplier": 1.0, "forced_volume": 0.0, "active": True}]}

def load_store(path=ACCOUNTS_FILE):
    if not os.path.exists(path):
        return default_store()
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return {"accounts": data, "groups": [{"name": "default", "vol_multiplier": 1.0, "forced_volume": 0.0, "active": True}]}
    if "accounts" not in data:
        data["accounts"] = []
    if "groups" not in data or not data["groups"]:
        data["groups"] = [{"name": "default", "vol_multiplier": 1.0, "forced_volume": 0.0, "active": True}]
    return data

def save_store(store, path=ACCOUNTS_FILE):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)

# ---------- GUI ----------
class MT5ManagerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("MT5 Multi Account Manager (Positions + Diagnostics)")
        self.store = load_store()
        self.ensure_account_defaults()
        self.log_q = queue.Queue()
        self.positions_q = queue.Queue()
        self.prev_positions_map = {}
        self.auto_refresh = tk.BooleanVar(value=True)
        self.refresh_interval = tk.DoubleVar(value=POSITIONS_REFRESH_INTERVAL)
        self.use_gui_session = tk.BooleanVar(value=False)
        self.terminal_path_var = tk.StringVar(value="")
        self._build_ui()
        self._refresh_lists()
        self._start_log_consumer()
        self._start_positions_refresher_thread()
        self._start_positions_queue_processor()

    def ensure_account_defaults(self):
        for a in self.store["accounts"]:
            a.setdefault("name", str(a.get("account", "")))
            a.setdefault("account", a.get("account", ""))
            a.setdefault("password", a.get("password", ""))
            a.setdefault("server", a.get("server", ""))
            a.setdefault("active", a.get("active", True))
            a.setdefault("vol_multiplier", a.get("vol_multiplier", 1.0))
            a.setdefault("forced_volume", a.get("forced_volume", 0.0))
            a.setdefault("group", a.get("group", "default"))
            a.setdefault("magic_number", a.get("magic_number", 0))

    def _build_ui(self):
        main = ttk.Frame(self.root); main.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        top_controls = ttk.Frame(main); top_controls.pack(fill=tk.X, pady=(0,6))

        # Terminal path and init controls
        ttk.Label(top_controls, text="Terminal exe:").pack(side=tk.LEFT)
        self.terminal_path_entry = ttk.Entry(top_controls, textvariable=self.terminal_path_var, width=50)
        self.terminal_path_entry.pack(side=tk.LEFT, padx=4)
        ttk.Button(top_controls, text="Browse...", command=self.browse_terminal).pack(side=tk.LEFT)
        ttk.Button(top_controls, text="Initialize Terminal", command=self.initialize_terminal_clicked).pack(side=tk.LEFT, padx=6)
        ttk.Button(top_controls, text="Shutdown Terminal", command=self.shutdown_terminal_clicked).pack(side=tk.LEFT)
        ttk.Checkbutton(top_controls, text="Use GUI session (do not programmatic login)", variable=self.use_gui_session).pack(side=tk.LEFT, padx=8)
        ttk.Button(top_controls, text="Test login all accounts", command=self.test_login_all_accounts).pack(side=tk.LEFT, padx=6)

        # Rest of UI (split left and right)
        left = ttk.Frame(main); left.pack(side=tk.LEFT, fill=tk.Y)
        right = ttk.Frame(main); right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8,0))

        # Groups and accounts (left)
        group_frame = ttk.LabelFrame(left, text="Groups"); group_frame.pack(fill=tk.X, pady=(0,8))
        self.groups_tree = ttk.Treeview(group_frame, columns=("name","vol","forced","active"), show="headings", height=6)
        for col, text in [("name","Name"), ("vol","VolX"), ("forced","ForcedVol"), ("active","Active")]:
            self.groups_tree.heading(col, text=text)
        self.groups_tree.pack(fill=tk.X)
        gbtns = ttk.Frame(group_frame); gbtns.pack(fill=tk.X, pady=4)
        ttk.Button(gbtns, text="Add Group", command=self.add_group).pack(side=tk.LEFT)
        ttk.Button(gbtns, text="Edit Group", command=self.edit_group).pack(side=tk.LEFT, padx=4)
        ttk.Button(gbtns, text="Remove Group", command=self.remove_group).pack(side=tk.LEFT)

        acct_frame = ttk.LabelFrame(left, text="Accounts"); acct_frame.pack(fill=tk.BOTH, expand=True)
        self.accounts_tree = ttk.Treeview(acct_frame, columns=("id","server","group","active"), show="headings", height=12)
        for col, text in [("id","Account"), ("server","Server"), ("group","Group"), ("active","Active")]:
            self.accounts_tree.heading(col, text=text)
        self.accounts_tree.pack(fill=tk.BOTH, expand=True)
        abtns = ttk.Frame(acct_frame); abtns.pack(fill=tk.X, pady=4)
        ttk.Button(abtns, text="Add Account", command=self.add_account).pack(side=tk.LEFT)
        ttk.Button(abtns, text="Edit Account", command=self.edit_account).pack(side=tk.LEFT, padx=4)
        ttk.Button(abtns, text="Remove Account", command=self.remove_account).pack(side=tk.LEFT)
        ttk.Button(abtns, text="Save", command=self.save_store_now).pack(side=tk.LEFT, padx=4)

        # Trade controls (right top)
        trade_frame = ttk.LabelFrame(right, text="Trade / Orders"); trade_frame.pack(fill=tk.X, padx=4, pady=4)
        f = ttk.Frame(trade_frame); f.pack(fill=tk.X, padx=6, pady=6)
        r = 0
        ttk.Label(f, text="Symbol:").grid(row=r, column=0, sticky=tk.W); self.symbol_e = ttk.Entry(f); self.symbol_e.grid(row=r, column=1, sticky=tk.W); r+=1
        ttk.Label(f, text="Side:").grid(row=r, column=0, sticky=tk.W); self.side_var = tk.StringVar(value="buy")
        ttk.Radiobutton(f, text="Buy", variable=self.side_var, value="buy").grid(row=r, column=1, sticky=tk.W)
        ttk.Radiobutton(f, text="Sell", variable=self.side_var, value="sell").grid(row=r, column=2, sticky=tk.W); r+=1
        ttk.Label(f, text="Base volume (lot):").grid(row=r, column=0, sticky=tk.W); self.base_vol_e = ttk.Entry(f); self.base_vol_e.grid(row=r, column=1, sticky=tk.W); self.base_vol_e.insert(0, "0.1"); r+=1
        ttk.Label(f, text="Entry price (leave blank = market):").grid(row=r, column=0, sticky=tk.W); self.entry_e = ttk.Entry(f); self.entry_e.grid(row=r, column=1, sticky=tk.W); r+=1
        act_f = ttk.Frame(trade_frame); act_f.pack(fill=tk.X, padx=6, pady=6)
        ttk.Button(act_f, text="Place Orders on Active Accounts", command=self.place_orders_clicked).pack(side=tk.LEFT)
        ttk.Button(act_f, text="Close All on Active Accounts", command=self.close_all_clicked).pack(side=tk.LEFT, padx=8)

        # Positions frame (right bottom)
        pos_frame = ttk.LabelFrame(right, text="Open Positions (across active accounts)")
        pos_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        cols = ("account","ticket","symbol","type","volume","price","sl","tp","profit","time")
        self.positions_tree = ttk.Treeview(pos_frame, columns=cols, show="headings", selectmode="extended")
        for c, lab in [("account","Account"), ("ticket","Ticket"), ("symbol","Symbol"), ("type","Type"),
                       ("volume","Volume"), ("price","OpenPrice"), ("sl","SL"), ("tp","TP"),
                       ("profit","Profit"), ("time","OpenTime")]:
            self.positions_tree.heading(c, text=lab)
            self.positions_tree.column(c, width=90 if c!="symbol" else 120, anchor="center")
        self.positions_tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        p_sb = ttk.Scrollbar(pos_frame, command=self.positions_tree.yview); p_sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.positions_tree.configure(yscrollcommand=p_sb.set)

        pos_buttons = ttk.Frame(pos_frame); pos_buttons.pack(fill=tk.X, pady=4)
        ttk.Button(pos_buttons, text="Refresh Positions Now", command=self.refresh_positions_now).pack(side=tk.LEFT)
        ttk.Checkbutton(pos_buttons, text="Auto-refresh", variable=self.auto_refresh).pack(side=tk.LEFT, padx=8)
        ttk.Label(pos_buttons, text="Interval (s):").pack(side=tk.LEFT)
        self.interval_e = ttk.Entry(pos_buttons, width=6, textvariable=self.refresh_interval); self.interval_e.pack(side=tk.LEFT, padx=4)
        ttk.Button(pos_buttons, text="Close Selected Position(s)", command=self.close_selected_positions).pack(side=tk.RIGHT)

        # status / log
        status_frame = ttk.Frame(self.root); status_frame.pack(fill=tk.X, padx=8, pady=(0,4))
        self.last_refresh_lbl = ttk.Label(status_frame, text="Last refresh: never")
        self.last_refresh_lbl.pack(side=tk.LEFT)
        log_frame = ttk.LabelFrame(self.root, text="Log"); log_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0,8))
        self.log_txt = tk.Text(log_frame, height=12, state=tk.DISABLED); self.log_txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        lsb = ttk.Scrollbar(log_frame, command=self.log_txt.yview); lsb.pack(side=tk.RIGHT, fill=tk.Y); self.log_txt.configure(yscrollcommand=lsb.set)

    # ---------- Terminal controls ----------
    def browse_terminal(self):
        p = filedialog.askopenfilename(title="Select terminal executable", filetypes=[("EXE files", "*.exe")])
        if p:
            self.terminal_path_var.set(p)

    def initialize_terminal_clicked(self):
        path = self.terminal_path_var.get().strip() or None
        ok, err = initialize_terminal(path)
        self.log("initialize ->", ok, err)
        if ok:
            messagebox.showinfo("Initialized", f"MT5 initialized (path={path or 'default'})")
        else:
            messagebox.showerror("Initialize failed", f"{err}")

    def shutdown_terminal_clicked(self):
        shutdown_terminal()
        self.log("Terminal shutdown requested")
        messagebox.showinfo("Shutdown", "MT5 shutdown called (if running)")

    def test_login_all_accounts(self):
        """Try programmatic login for every saved account and log mt5.last_error()"""
        if not mt5_available():
            messagebox.showerror("MT5 missing", "MetaTrader5 module not installed.")
            return
        t = threading.Thread(target=self._test_login_worker, daemon=True)
        t.start()

    def _test_login_worker(self):
        accounts = self.store.get("accounts", [])
        if not accounts:
            self.log("No accounts saved to test")
            return
        for a in accounts:
            acct = a.get("account")
            pwd = a.get("password","")
            srv = a.get("server","")
            # perform sequential initialize/login/shutdown using the helper functions
            ok, ierr = initialize_terminal(self.terminal_path_var.get().strip() or None)
            if not ok:
                self.log(f"Init failed before login for {acct}: {ierr}")
                continue
            try:
                res = mt5.login(int(acct), pwd, srv)
            except Exception as e:
                res = False
                self.log(f"Login exception for {acct}: {e}")
                mt5.shutdown()
                continue
            le = mt5.last_error()
            self.log(f"Login result for {acct}: {res} last_error: {le}")
            if res:
                try:
                    info = mt5.account_info()
                    self.log(f"Account {acct} info: login successful, balance={getattr(info,'balance', 'n/a')}")
                except Exception as e:
                    self.log(f"account_info error for {acct}: {e}")
            mt5.shutdown()
            time.sleep(0.3)

    # ---------- lists and logging ----------
    def _refresh_lists(self):
        for i in self.groups_tree.get_children(): self.groups_tree.delete(i)
        for idx, g in enumerate(self.store["groups"]):
            active = "yes" if g.get("active", True) else "no"
            self.groups_tree.insert("", "end", iid=str(idx), values=(g.get("name"), g.get("vol_multiplier", 1.0), g.get("forced_volume", 0.0), active))
        for i in self.accounts_tree.get_children(): self.accounts_tree.delete(i)
        for idx, a in enumerate(self.store["accounts"]):
            active = "yes" if a.get("active", True) else "no"
            self.accounts_tree.insert("", "end", iid=str(idx), values=(a.get("account",""), a.get("server",""), a.get("group","default"), active))

    def log(self, *parts):
        self.log_q.put(" ".join(str(p) for p in parts))

    def _start_log_consumer(self):
        def consumer():
            while True:
                try:
                    msg = self.log_q.get(timeout=0.1)
                except queue.Empty:
                    time.sleep(0.05)
                    continue
                self.log_txt.configure(state=tk.NORMAL)
                self.log_txt.insert(tk.END, f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {msg}\n")
                self.log_txt.see(tk.END)
                self.log_txt.configure(state=tk.DISABLED)
        t = threading.Thread(target=consumer, daemon=True)
        t.start()

    # ---------- Group/account dialogs ----------
    def add_group(self):
        dlg = GroupDialog(self.root, None); self.root.wait_window(dlg.top)
        if dlg.result: self.store["groups"].append(dlg.result); save_store(self.store); self._refresh_lists()
    def edit_group(self):
        sel = self.groups_tree.selection();
        if not sel: messagebox.showinfo("Edit Group","Select a group"); return
        idx = int(sel[0]); dlg = GroupDialog(self.root, self.store["groups"][idx]); self.root.wait_window(dlg.top)
        if dlg.result: self.store["groups"][idx] = dlg.result; save_store(self.store); self._refresh_lists()
    def remove_group(self):
        sel = self.groups_tree.selection();
        if not sel: messagebox.showinfo("Remove Group","Select a group"); return
        idx = int(sel[0]); name = self.store["groups"][idx]["name"]
        if name == "default": messagebox.showwarning("Remove Group","Default group cannot be removed."); return
        for a in self.store["accounts"]:
            if a.get("group")==name: a["group"]="default"
        del self.store["groups"][idx]; save_store(self.store); self._refresh_lists()

    def add_account(self):
        dlg = AccountDialog(self.root, None, self.store["groups"]); self.root.wait_window(dlg.top)
        if dlg.result: self.store["accounts"].append(dlg.result); save_store(self.store); self._refresh_lists()
    def edit_account(self):
        sel = self.accounts_tree.selection();
        if not sel: messagebox.showinfo("Edit Account","Select an account"); return
        idx = int(sel[0]); dlg = AccountDialog(self.root, self.store["accounts"][idx], self.store["groups"]); self.root.wait_window(dlg.top)
        if dlg.result: self.store["accounts"][idx] = dlg.result; save_store(self.store); self._refresh_lists()
    def remove_account(self):
        sel = self.accounts_tree.selection();
        if not sel: messagebox.showinfo("Remove Account","Select an account"); return
        idx = int(sel[0]); del self.store["accounts"][idx]; save_store(self.store); self._refresh_lists()
    def save_store_now(self): save_store(self.store); messagebox.showinfo("Saved", f"Saved data to {ACCOUNTS_FILE}")
    def get_active_accounts(self): return [a for a in self.store["accounts"] if a.get("active", True)]

    # ---------- Trading (placeholder) ----------
    def parse_float(self, s):
        try: return float(s)
        except: return None

    def place_orders_clicked(self):
        messagebox.showinfo("Place Orders", "Placing orders feature unchanged from earlier script. Use previous code to place orders.")

    def close_all_clicked(self):
        if not mt5_available():
            messagebox.showerror("MT5 missing", "MetaTrader5 package not available."); return
        accounts = self.get_active_accounts()
        if not accounts:
            messagebox.showinfo("No accounts", "No active accounts."); return
        if not messagebox.askyesno("Confirm", f"Close all positions on {len(accounts)} accounts?"): return
        threading.Thread(target=self._close_all_worker, args=(accounts,), daemon=True).start()

    def _close_all_worker(self, accounts):
        """Sequentially initialize/login/close/shutdown on each account."""
        self.log("Starting sequential close-all on", len(accounts), "accounts")
        terminal_path = self.terminal_path_var.get().strip() or None
        for a in accounts:
            acct_id = a.get("account")
            self.log("Processing account", acct_id)
            ok, msg = perform_close_all_for_account(a, terminal_path, log_fn=self.log)
            if ok:
                self.log(f"Closed positions on account {acct_id}: {msg}")
            else:
                self.log(f"Failed to close on account {acct_id}: {msg}")
            # small pause between accounts
            time.sleep(0.5)
        self.log("Finished sequential close-all.")
        self.refresh_positions_now()

    # ---------- Positions refresh ----------
    def _start_positions_refresher_thread(self):
        def refresher():
            while True:
                if self.auto_refresh.get():
                    self._collect_positions_across_accounts()
                time.sleep(max(0.5, float(self.refresh_interval.get())))
        t = threading.Thread(target=refresher, daemon=True)
        t.start()

    def _collect_positions_across_accounts(self):
        """Collect positions depending on mode:
           - If use_gui_session is True -> use current terminal session (single account)
           - Else -> attempt programmatic login per saved account sequentially
        """
        accounts = self.get_active_accounts()
        all_positions = []
        terminal_path = self.terminal_path_var.get().strip() or None

        if self.use_gui_session.get():
            # Use current terminal's session (single account)
            ok, ierr = initialize_terminal(terminal_path)
            if not ok:
                self.log("GUI session initialize failed:", ierr)
                return
            try:
                info = mt5.account_info()
            except Exception as e:
                self.log("account_info error (GUI):", e); mt5.shutdown(); return
            if info is None:
                self.log("GUI session not logged in or account_info() None"); mt5.shutdown(); return
            acc_id = str(getattr(info, "login", "gui"))
            try:
                positions = mt5.positions_get()
            except Exception as e:
                self.log("positions_get error (GUI):", e); positions = None
            if positions:
                for p in positions:
                    try:
                        all_positions.append({
                            "account": acc_id,
                            "ticket": int(p.ticket),
                            "symbol": p.symbol,
                            "type": "buy" if int(p.type) == 0 else "sell",
                            "volume": float(p.volume),
                            "price": float(getattr(p, "price_open", getattr(p, "price", 0.0))),
                            "sl": float(getattr(p, "sl", 0.0) or 0.0),
                            "tp": float(getattr(p, "tp", 0.0) or 0.0),
                            "profit": float(getattr(p, "profit", 0.0) or 0.0),
                            "time": int(getattr(p, "time", getattr(p, "time_msc", 0)) or 0)
                        })
                    except Exception:
                        continue
            mt5.shutdown()
        else:
            # Programmatic per-account login sequentially
            for a in accounts:
                recs, msg = fetch_positions_for_account(a, terminal_path, log_fn=self.log)
                if recs is None:
                    self.log(f"Positions fetch failed for {a.get('account')}: {msg}")
                    continue
                all_positions.extend(recs)

        self.positions_q.put({"positions": all_positions, "ts": time.time()})

    def _start_positions_queue_processor(self):
        def processor():
            while True:
                try:
                    item = self.positions_q.get(timeout=0.5)
                except queue.Empty:
                    time.sleep(0.05)
                    continue
                positions = item.get("positions", [])
                ts = item.get("ts", time.time())
                self.root.after(0, self._update_positions_ui, positions, ts)
        t = threading.Thread(target=processor, daemon=True)
        t.start()

    def _update_positions_ui(self, positions, ts):
        new_map = {}
        for p in positions:
            key = (p["account"], p["ticket"])
            new_map[key] = p
        for key, p in new_map.items():
            if key not in self.prev_positions_map:
                self.log("New position detected:", p["account"], p["ticket"], p["symbol"], p["type"], p["volume"])
        for key, p in list(self.prev_positions_map.items()):
            if key not in new_map:
                self.log("Position closed (or disappeared):", p.get("account"), p.get("ticket"), p.get("symbol"))
        for i in self.positions_tree.get_children(): self.positions_tree.delete(i)
        for p in positions:
            ts_val = p.get("time", 0)
            try:
                if ts_val and ts_val > 1000000000:
                    tstr = datetime.datetime.fromtimestamp(ts_val).strftime("%Y-%m-%d %H:%M:%S")
                else:
                    tstr = ""
            except Exception:
                tstr = ""
            values = (p["account"], p["ticket"], p["symbol"], p["type"], f"{p['volume']:.2f}", f"{p['price']:.5f}", f"{p['sl']:.5f}" if p['sl'] else "", f"{p['tp']:.5f}" if p['tp'] else "", f"{p['profit']:.2f}", tstr)
            self.positions_tree.insert("", "end", iid=f"{p['account']}_{p['ticket']}", values=values)
        self.prev_positions_map = new_map
        self.last_refresh_lbl.config(text=f"Last refresh: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))}")

    def refresh_positions_now(self):
        threading.Thread(target=self._collect_positions_across_accounts, daemon=True).start()

    # ---------- Close selected ----------
    def close_selected_positions(self):
        sel = self.positions_tree.selection()
        if not sel:
            messagebox.showinfo("No selection", "Select positions to close"); return
        if not messagebox.askyesno("Confirm", f"Close {len(sel)} selected position(s)?"): return
        tasks = []
        for iid in sel:
            try:
                acct, ticket = iid.split("_", 1)
            except Exception:
                vals = self.positions_tree.item(iid, "values"); acct = vals[0]; ticket = vals[1]
            tasks.append((acct, ticket))
        threading.Thread(target=self._close_selected_worker, args=(tasks,), daemon=True).start()

    def _close_selected_worker(self, tasks):
        terminal_path = self.terminal_path_var.get().strip() or None
        for acct, ticket in tasks:
            acct_info = next((a for a in self.store["accounts"] if str(a.get("account")) == str(acct)), None)
            if acct_info is None:
                # If using GUI session, and the ticket belongs to the GUI account, use current session
                if self.use_gui_session.get():
                    okg, info = (False, None)
                    okg, info = (lambda: get_terminal_account_info())() if 'get_terminal_account_info' in globals() else (False, "N/A")
                    # fallback: try to use initialize + account_info directly
                    try:
                        okg = True
                        info = mt5.account_info()
                    except Exception:
                        okg = False
                    if okg and str(getattr(info, "login", "")) == str(acct):
                        okc, msg = close_position_by_ticket(ticket, log_fn=self.log)
                        if okc: self.log("Closed ticket", ticket, "on GUI account", acct)
                        else: self.log("Failed to close ticket", ticket, "on GUI account", acct, ":", msg)
                        continue
                self.log("Credentials for account", acct, "not found. Skipping"); continue
            self.log("Processing close ticket", ticket, "for account", acct)
            okc, msg = perform_close_ticket_for_account(acct_info, ticket, terminal_path, log_fn=self.log)
            if okc:
                self.log("Closed ticket", ticket, "on account", acct)
            else:
                self.log("Failed to close ticket", ticket, "on account", acct, ":", msg)
        self.refresh_positions_now()

# ---------- Dialogs ----------
class GroupDialog:
    def __init__(self, parent, group):
        self.top = tk.Toplevel(parent); self.top.transient(parent); self.top.grab_set()
        self.result = None
        self.group = dict(group) if group else {"name":"", "vol_multiplier":1.0, "forced_volume":0.0, "active":True}
        self._build()
    def _build(self):
        f = ttk.Frame(self.top); f.pack(padx=8, pady=8)
        ttk.Label(f, text="Group name:").grid(row=0, column=0, sticky=tk.W)
        self.name_e = ttk.Entry(f); self.name_e.grid(row=0,column=1)
        ttk.Label(f, text="Group vol multiplier:").grid(row=1,column=0, sticky=tk.W)
        self.vol_e = ttk.Entry(f); self.vol_e.grid(row=1,column=1)
        ttk.Label(f, text="Group forced volume (0 for none):").grid(row=2,column=0, sticky=tk.W)
        self.forced_e = ttk.Entry(f); self.forced_e.grid(row=2,column=1)
        self.active_var = tk.BooleanVar(value=self.group.get("active", True))
        ttk.Checkbutton(f, text="Active", variable=self.active_var).grid(row=3, column=0, columnspan=2, sticky=tk.W)
        self.name_e.insert(0, self.group.get("name", ""))
        self.vol_e.insert(0, str(self.group.get("vol_multiplier",1.0)))
        self.forced_e.insert(0, str(self.group.get("forced_volume",0.0)))
        btns = ttk.Frame(self.top); btns.pack(pady=6)
        ttk.Button(btns, text="OK", command=self.ok).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Cancel", command=self.top.destroy).pack(side=tk.LEFT, padx=4)
    def ok(self):
        n = self.name_e.get().strip()
        if not n: messagebox.showerror("Error","Group name required"); return
        try:
            vol = float(self.vol_e.get().strip() or 1.0)
            forced = float(self.forced_e.get().strip() or 0.0)
            self.result = {"name": n, "vol_multiplier": vol, "forced_volume": forced, "active": bool(self.active_var.get())}
            self.top.destroy()
        except Exception as e:
            messagebox.showerror("Error", f"Invalid numbers: {e}")

class AccountDialog:
    def __init__(self, parent, account, groups):
        self.top = tk.Toplevel(parent); self.top.transient(parent); self.top.grab_set()
        self.result = None
        self.account = dict(account) if account else {"name":"", "account":"", "password":"", "server":"", "active":True, "vol_multiplier":1.0, "forced_volume":0.0, "group":"default", "magic_number":0}
        self.groups = groups
        self._build()
    def _build(self):
        f = ttk.Frame(self.top); f.pack(padx=8, pady=8)
        ttk.Label(f, text="Name (optional):").grid(row=0,column=0, sticky=tk.W)
        self.name_e = ttk.Entry(f); self.name_e.grid(row=0,column=1)
        ttk.Label(f, text="Account ID:").grid(row=1,column=0, sticky=tk.W)
        self.acc_e = ttk.Entry(f); self.acc_e.grid(row=1,column=1)
        ttk.Label(f, text="Password:").grid(row=2,column=0, sticky=tk.W)
        self.pwd_e = ttk.Entry(f, show="*"); self.pwd_e.grid(row=2,column=1)
        ttk.Label(f, text="Server:").grid(row=3,column=0, sticky=tk.W)
        self.serv_e = ttk.Entry(f); self.serv_e.grid(row=3,column=1)
        self.active_var = tk.BooleanVar(value=self.account.get("active", True))
        ttk.Checkbutton(f, text="Active", variable=self.active_var).grid(row=4,column=0, columnspan=2, sticky=tk.W)
        ttk.Label(f, text="Group:").grid(row=5,column=0, sticky=tk.W)
        self.group_var = tk.StringVar(value=self.account.get("group","default"))
        group_names = [g["name"] for g in self.groups]
        self.group_cb = ttk.Combobox(f, values=group_names, textvariable=self.group_var, state="readonly")
        if not group_names: self.group_cb['values'] = ["default"]; self.group_cb.set("default")
        self.group_cb.grid(row=5,column=1)
        ttk.Label(f, text="Vol multiplier (optional):").grid(row=6,column=0, sticky=tk.W)
        self.vm_e = ttk.Entry(f); self.vm_e.grid(row=6,column=1)
        ttk.Label(f, text="Forced volume (optional):").grid(row=7,column=0, sticky=tk.W)
        self.forced_e = ttk.Entry(f); self.forced_e.grid(row=7,column=1)
        ttk.Label(f, text="Magic number (optional):").grid(row=8,column=0, sticky=tk.W)
        self.magic_e = ttk.Entry(f); self.magic_e.grid(row=8,column=1)
        self.name_e.insert(0, self.account.get("name",""))
        self.acc_e.insert(0, self.account.get("account",""))
        self.pwd_e.insert(0, self.account.get("password",""))
        self.serv_e.insert(0, self.account.get("server",""))
        self.vm_e.insert(0, str(self.account.get("vol_multiplier",1.0)))
        self.forced_e.insert(0, str(self.account.get("forced_volume",0.0)))
        self.magic_e.insert(0, str(self.account.get("magic_number",0)))
        btns = ttk.Frame(self.top); btns.pack(pady=6)
        ttk.Button(btns, text="OK", command=self.ok).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Cancel", command=self.top.destroy).pack(side=tk.LEFT, padx=4)
    def ok(self):
        accid = self.acc_e.get().strip()
        if not accid: messagebox.showerror("Error","Account ID required"); return
        try:
            data = {
                "name": self.name_e.get().strip() or accid,
                "account": accid,
                "password": self.pwd_e.get().strip(),
                "server": self.serv_e.get().strip(),
                "active": bool(self.active_var.get()),
                "group": self.group_var.get() or "default",
                "vol_multiplier": float(self.vm_e.get().strip() or 1.0),
                "forced_volume": float(self.forced_e.get().strip() or 0.0),
                "magic_number": int(self.magic_e.get().strip() or 0)
            }
            self.result = data
            self.top.destroy()
        except Exception as e:
            messagebox.showerror("Error", f"Invalid input: {e}")

# ---------- Main ----------
if __name__ == "__main__":
    root = tk.Tk()
    app = MT5ManagerApp(root)
    root.mainloop()