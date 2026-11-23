"""
mt5_multi_manager_with_groups_fixed.py
Tkinter UI to manage multiple MT5 accounts with grouping, place orders across them,
save accounts+groups to JSON, and close positions across accounts.

Requires: pip install MetaTrader5
Run with the MetaTrader 5 terminal open on the same machine.

Author: assistant (corrected Treeview columns)
"""
import tkinter as tk
from tkinter import ttk, messagebox
import json, os, threading, queue, time

try:
    import MetaTrader5 as mt5
except Exception:
    mt5 = None

ACCOUNTS_FILE = "version2/mt5_accounts.json"

# ---------- MT5 helpers ----------
def mt5_available():
    return mt5 is not None

def mt5_init():
    if not mt5.initialize():
        return False, mt5.last_error()
    return True, None

def mt5_shutdown_safe():
    try:
        mt5.shutdown()
    except Exception:
        pass

def login_account(account, password, server):
    # Re-init and login per account (works when MT5 terminal allows it)
    mt5_shutdown_safe()
    ok, err = mt5_init()
    if not ok:
        return False, f"initialize failed: {err}"
    try:
        res = mt5.login(int(account), password=str(password), server=str(server))
    except Exception as e:
        return False, f"login exception: {e}"
    if res:
        info = mt5.account_info()
        if info is None:
            return False, "login succeeded but account_info() returned None"
        return True, info
    else:
        return False, mt5.last_error()

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

def place_market_order(symbol, order_side, volume, sl, tp, deviation=20, magic=0):
    tick = get_tick(symbol)
    if tick is None:
        return None
    price = tick.ask if order_side == "buy" else tick.bid
    mt_type = mt5.ORDER_TYPE_BUY if order_side == "buy" else mt5.ORDER_TYPE_SELL
    req = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": float(volume),
        "type": mt_type,
        "price": price,
        "sl": float(sl) if sl else 0.0,
        "tp": float(tp) if tp else 0.0,
        "deviation": int(deviation),
        "magic": int(magic),
        "comment": "mt5_multi_manager",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    return mt5.order_send(req)

def place_pending_order(symbol, pending_type, price, volume, sl, tp, deviation=20, magic=0):
    req = {
        "action": mt5.TRADE_ACTION_PENDING,
        "symbol": symbol,
        "volume": float(volume),
        "type": int(pending_type),
        "price": float(price),
        "sl": float(sl) if sl else 0.0,
        "tp": float(tp) if tp else 0.0,
        "deviation": int(deviation),
        "magic": int(magic),
        "comment": "mt5_multi_manager_pending",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_RETURN,
    }
    return mt5.order_send(req)

def close_all_positions_for_account(log_fn=None):
    positions = mt5.positions_get()
    if positions is None:
        return False, "positions_get returned None"
    if len(positions) == 0:
        return True, "no open positions"
    errors = []
    for pos in positions:
        sym = pos.symbol
        vol = pos.volume
        pos_type = pos.type  # 0 buy, 1 sell
        tick = get_tick(sym)
        if tick is None:
            errors.append(f"No tick for {sym}")
            continue
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
            "comment": "close_by_mt5_multi_manager",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        r = mt5.order_send(req)
        if r is None or getattr(r, "retcode", None) not in (10009, 10008, None):
            errors.append(f"Failed to close pos {pos.ticket} on {sym}: {r}")
        else:
            if log_fn:
                log_fn(f"Closed position {pos.ticket} symbol={sym} vol={vol}")
        time.sleep(0.15)
    if errors:
        return False, "\n".join(errors)
    return True, "closed all (or none were open)"

# ---------- Storage (accounts + groups) ----------
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
        self.root.title("MT5 Multi Account Manager (with Groups) - Fixed")
        self.store = load_store()
        self.ensure_account_defaults()
        self.log_q = queue.Queue()
        self._build_ui()
        self._refresh_lists()
        self._start_log_consumer()

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
        main = ttk.Frame(self.root)
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        left = ttk.Frame(main)
        left.pack(side=tk.LEFT, fill=tk.Y)

        right = ttk.Frame(main)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8,0))

        # Groups frame (FIXED: include name column)
        group_frame = ttk.LabelFrame(left, text="Groups")
        group_frame.pack(fill=tk.X, pady=(0,8))
        self.groups_tree = ttk.Treeview(group_frame, columns=("name","vol","forced","active"), show="headings", height=6)
        self.groups_tree.heading("name", text="Name")
        self.groups_tree.heading("vol", text="VolX")
        self.groups_tree.heading("forced", text="ForcedVol")
        self.groups_tree.heading("active", text="Active")
        self.groups_tree.pack(fill=tk.X)
        gbtns = ttk.Frame(group_frame)
        gbtns.pack(fill=tk.X, pady=4)
        ttk.Button(gbtns, text="Add Group", command=self.add_group).pack(side=tk.LEFT)
        ttk.Button(gbtns, text="Edit Group", command=self.edit_group).pack(side=tk.LEFT, padx=4)
        ttk.Button(gbtns, text="Remove Group", command=self.remove_group).pack(side=tk.LEFT)

        # Accounts frame
        acct_frame = ttk.LabelFrame(left, text="Accounts")
        acct_frame.pack(fill=tk.BOTH, expand=True)
        self.accounts_tree = ttk.Treeview(acct_frame, columns=("id","server","group","active"), show="headings", height=12)
        self.accounts_tree.heading("id", text="Account")
        self.accounts_tree.heading("server", text="Server")
        self.accounts_tree.heading("group", text="Group")
        self.accounts_tree.heading("active", text="Active")
        self.accounts_tree.pack(fill=tk.BOTH, expand=True)
        abtns = ttk.Frame(acct_frame)
        abtns.pack(fill=tk.X, pady=4)
        ttk.Button(abtns, text="Add Account", command=self.add_account).pack(side=tk.LEFT)
        ttk.Button(abtns, text="Edit Account", command=self.edit_account).pack(side=tk.LEFT, padx=4)
        ttk.Button(abtns, text="Remove Account", command=self.remove_account).pack(side=tk.LEFT)
        ttk.Button(abtns, text="Save", command=self.save_store_now).pack(side=tk.LEFT, padx=4)

        # Trade panel (right)
        trade_frame = ttk.LabelFrame(right, text="Trade / Orders")
        trade_frame.pack(fill=tk.BOTH, expand=True)

        f = ttk.Frame(trade_frame)
        f.pack(fill=tk.X, padx=6, pady=6)

        r = 0
        ttk.Label(f, text="Symbol:").grid(row=r, column=0, sticky=tk.W)
        self.symbol_e = ttk.Entry(f); self.symbol_e.grid(row=r, column=1, sticky=tk.W)
        r += 1

        ttk.Label(f, text="Side:").grid(row=r, column=0, sticky=tk.W)
        self.side_var = tk.StringVar(value="buy")
        ttk.Radiobutton(f, text="Buy", variable=self.side_var, value="buy").grid(row=r, column=1, sticky=tk.W)
        ttk.Radiobutton(f, text="Sell", variable=self.side_var, value="sell").grid(row=r, column=2, sticky=tk.W)
        r += 1

        # Base volume prefilled (so user doesn't need to enter each time). Default 0.1
        ttk.Label(f, text="Base volume (lot) - default used for all accounts:").grid(row=r, column=0, sticky=tk.W)
        self.base_vol_e = ttk.Entry(f); self.base_vol_e.grid(row=r, column=1, sticky=tk.W)
        self.base_vol_e.insert(0, "0.1")
        r += 1

        ttk.Label(f, text="Or total volume to distribute (optional):").grid(row=r, column=0, sticky=tk.W)
        self.total_vol_e = ttk.Entry(f); self.total_vol_e.grid(row=r, column=1, sticky=tk.W)
        r += 1

        ttk.Label(f, text="Distribution:").grid(row=r, column=0, sticky=tk.W)
        self.dist_var = tk.StringVar(value="equal")
        ttk.Radiobutton(f, text="Equal", variable=self.dist_var, value="equal").grid(row=r, column=1, sticky=tk.W)
        ttk.Radiobutton(f, text="By balance", variable=self.dist_var, value="by_balance").grid(row=r, column=2, sticky=tk.W)
        r += 1

        ttk.Label(f, text="Stop Loss (pips or exact price):").grid(row=r, column=0, sticky=tk.W)
        self.sl_e = ttk.Entry(f); self.sl_e.grid(row=r, column=1, sticky=tk.W)
        r += 1
        ttk.Label(f, text="Take Profit (pips or exact price):").grid(row=r, column=0, sticky=tk.W)
        self.tp_e = ttk.Entry(f); self.tp_e.grid(row=r, column=1, sticky=tk.W)
        r += 1
        ttk.Label(f, text="Entry price (leave blank for market):").grid(row=r, column=0, sticky=tk.W)
        self.entry_price_e = ttk.Entry(f); self.entry_price_e.grid(row=r, column=1, sticky=tk.W)
        r += 1

        ttk.Label(f, text="Deviation (slippage) in points (optional):").grid(row=r, column=0, sticky=tk.W)
        self.dev_e = ttk.Entry(f); self.dev_e.grid(row=r, column=1, sticky=tk.W)
        self.dev_e.insert(0, "20")
        r += 1
        ttk.Label(f, text="Magic number (optional override):").grid(row=r, column=0, sticky=tk.W)
        self.magic_e = ttk.Entry(f); self.magic_e.grid(row=r, column=1, sticky=tk.W)
        r += 1

        act_f = ttk.Frame(trade_frame); act_f.pack(fill=tk.X, padx=6, pady=6)
        ttk.Button(act_f, text="Place Orders on Active Accounts", command=self.place_orders_clicked).pack(side=tk.LEFT)
        ttk.Button(act_f, text="Close All on Active Accounts", command=self.close_all_clicked).pack(side=tk.LEFT, padx=8)

        # log
        log_frame = ttk.LabelFrame(self.root, text="Log")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0,8))
        self.log_txt = tk.Text(log_frame, height=12, state=tk.DISABLED)
        self.log_txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(log_frame, command=self.log_txt.yview); sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_txt.configure(yscrollcommand=sb.set)

    def _refresh_lists(self):
        # refresh groups tree (FIXED: insert name as first value)
        for i in self.groups_tree.get_children(): self.groups_tree.delete(i)
        for idx, g in enumerate(self.store["groups"]):
            active = "yes" if g.get("active", True) else "no"
            self.groups_tree.insert("", "end", iid=str(idx),
                                    values=(g.get("name"),
                                            g.get("vol_multiplier", 1.0),
                                            g.get("forced_volume", 0.0),
                                            active))
        # refresh accounts tree
        for i in self.accounts_tree.get_children(): self.accounts_tree.delete(i)
        for idx, a in enumerate(self.store["accounts"]):
            active = "yes" if a.get("active", True) else "no"
            self.accounts_tree.insert("", "end", iid=str(idx),
                                      values=(a.get("account",""),
                                              a.get("server",""),
                                              a.get("group","default"),
                                              active))

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

    # ---------- Group management ----------
    def add_group(self):
        dlg = GroupDialog(self.root, None)
        self.root.wait_window(dlg.top)
        if dlg.result:
            self.store["groups"].append(dlg.result)
            save_store(self.store)
            self._refresh_lists()

    def edit_group(self):
        sel = self.groups_tree.selection()
        if not sel:
            messagebox.showinfo("Edit Group", "Select a group to edit")
            return
        idx = int(sel[0])
        dlg = GroupDialog(self.root, self.store["groups"][idx])
        self.root.wait_window(dlg.top)
        if dlg.result:
            self.store["groups"][idx] = dlg.result
            save_store(self.store)
            self._refresh_lists()

    def remove_group(self):
        sel = self.groups_tree.selection()
        if not sel:
            messagebox.showinfo("Remove Group", "Select a group to remove")
            return
        idx = int(sel[0])
        name = self.store["groups"][idx]["name"]
        if name == "default":
            messagebox.showwarning("Remove Group", "Default group cannot be removed.")
            return
        for a in self.store["accounts"]:
            if a.get("group") == name:
                a["group"] = "default"
        del self.store["groups"][idx]
        save_store(self.store)
        self._refresh_lists()

    # ---------- Accounts ----------
    def add_account(self):
        dlg = AccountDialog(self.root, None, self.store["groups"])
        self.root.wait_window(dlg.top)
        if dlg.result:
            self.store["accounts"].append(dlg.result)
            save_store(self.store)
            self._refresh_lists()

    def edit_account(self):
        sel = self.accounts_tree.selection()
        if not sel:
            messagebox.showinfo("Edit Account", "Select an account to edit")
            return
        idx = int(sel[0])
        dlg = AccountDialog(self.root, self.store["accounts"][idx], self.store["groups"])
        self.root.wait_window(dlg.top)
        if dlg.result:
            self.store["accounts"][idx] = dlg.result
            save_store(self.store)
            self._refresh_lists()

    def remove_account(self):
        sel = self.accounts_tree.selection()
        if not sel:
            messagebox.showinfo("Remove Account", "Select an account to remove")
            return
        idx = int(sel[0])
        del self.store["accounts"][idx]
        save_store(self.store)
        self._refresh_lists()

    def save_store_now(self):
        save_store(self.store)
        messagebox.showinfo("Saved", f"Saved data to {ACCOUNTS_FILE}")

    def get_active_accounts(self):
        return [a for a in self.store["accounts"] if a.get("active", True)]

    # ---------- Order logic ----------
    def parse_float(self, s):
        try:
            return float(s)
        except:
            return None

    def place_orders_clicked(self):
        if not mt5_available():
            messagebox.showerror("MT5 missing", "Install MetaTrader5 Python package and ensure MT5 terminal is running.")
            return
        accounts = self.get_active_accounts()
        if not accounts:
            messagebox.showinfo("No accounts", "No active accounts.")
            return
        symbol = self.symbol_e.get().strip()
        if not symbol:
            messagebox.showinfo("Symbol", "Enter symbol.")
            return
        side = self.side_var.get()
        base_vol_text = self.base_vol_e.get().strip()
        total_vol_text = self.total_vol_e.get().strip()
        distribution = self.dist_var.get()
        sl_text = self.sl_e.get().strip()
        tp_text = self.tp_e.get().strip()
        entry_price_text = self.entry_price_e.get().strip()
        deviation = int(self.dev_e.get().strip() or 20)
        magic_override = self.magic_e.get().strip()

        threading.Thread(target=self._place_orders_worker, args=(accounts, symbol, side, base_vol_text, total_vol_text, distribution, sl_text, tp_text, entry_price_text, deviation, magic_override), daemon=True).start()

    def _place_orders_worker(self, accounts, symbol, side, base_vol_text, total_vol_text, distribution, sl_text, tp_text, entry_price_text, deviation, magic_override):
        self.log("Starting order placement on", len(accounts), "accounts for", symbol)
        balances = []
        for a in accounts:
            ok, info = login_account(a["account"], a.get("password",""), a.get("server",""))
            if not ok:
                self.log("Login to fetch balance failed for", a["account"], ":", info)
                balances.append(0.0)
            else:
                balances.append(float(info.balance))

        base_vol = self.parse_float(base_vol_text) if base_vol_text else None
        total_vol = self.parse_float(total_vol_text) if total_vol_text else None
        per_account_vols = []

        group_map = {g["name"]: g for g in self.store["groups"]}

        if total_vol and (not base_vol or base_vol == 0.0):
            if distribution == "equal":
                per = total_vol / max(1, len(accounts))
                per_account_vols = [per] * len(accounts)
            else:
                s = sum(balances) if sum(balances) > 0 else len(accounts)
                if s == 0:
                    per_account_vols = [total_vol / len(accounts)] * len(accounts)
                else:
                    per_account_vols = [total_vol * (b / s if s > 0 else 1.0/len(accounts)) for b in balances]
            for i, a in enumerate(accounts):
                g = group_map.get(a.get("group","default"), {"vol_multiplier":1.0, "forced_volume":0.0})
                forced = float(g.get("forced_volume",0.0) or 0.0) or float(a.get("forced_volume",0.0) or 0.0)
                if forced and forced > 0.0:
                    per_account_vols[i] = forced
                else:
                    mult = float(g.get("vol_multiplier",1.0) or 1.0) * float(a.get("vol_multiplier",1.0) or 1.0)
                    per_account_vols[i] = per_account_vols[i] * mult
        else:
            if base_vol is None:
                self.log("No base volume provided; using default 0.1")
                base_vol = 0.1
            for i, a in enumerate(accounts):
                g = group_map.get(a.get("group","default"), {"vol_multiplier":1.0, "forced_volume":0.0})
                forced = float(g.get("forced_volume",0.0) or 0.0) or float(a.get("forced_volume",0.0) or 0.0)
                if forced and forced > 0.0:
                    vol = forced
                else:
                    vol = base_vol * float(g.get("vol_multiplier",1.0) or 1.0) * float(a.get("vol_multiplier",1.0) or 1.0)
                per_account_vols.append(vol)

        for v in per_account_vols:
            if v <= 0:
                self.log("Computed non-positive volume; aborting")
                return

        for idx, a in enumerate(accounts):
            vol = per_account_vols[idx]
            self.log("Logging into account", a["account"])
            ok, info = login_account(a["account"], a.get("password",""), a.get("server",""))
            if not ok:
                self.log("Login failed for", a["account"], ":", info)
                continue
            self.log("Logged in", a["account"], "Balance=", info.balance)

            sym_info = mt5.symbol_info(symbol)
            if sym_info is None:
                self.log("Symbol", symbol, "not present on", a["account"], "trying to select")
                try:
                    mt5.symbol_select(symbol, True)
                    time.sleep(0.2)
                    sym_info = mt5.symbol_info(symbol)
                except Exception:
                    sym_info = None
            if sym_info is None:
                self.log("Symbol not available on", a["account"], "- skipping")
                continue

            tick = get_tick(symbol)
            if tick is None:
                self.log("No tick for symbol on", a["account"], "- skipping")
                continue

            entry_price = self.parse_float(entry_price_text) if entry_price_text else None
            def compute_sl_tp(price, side, val_text):
                if not val_text:
                    return None
                val = self.parse_float(val_text)
                if val is None:
                    return None
                pip = symbol_pip_value(symbol) or (0.0001 if getattr(sym_info,'digits',5) > 3 else 0.01)
                if abs(val - price) > pip * 10:
                    return val
                if side == "buy":
                    return price - val * pip
                else:
                    return price + val * pip

            market_price = tick.ask if side == "buy" else tick.bid

            if entry_price is None:
                slp = compute_sl_tp(market_price, side, sl_text)
                tpp = compute_sl_tp(market_price, side, tp_text)
                magic = int(magic_override) if magic_override else int(a.get("magic_number", 0))
                res = place_market_order(symbol, side, vol, slp, tpp, deviation=int(deviation), magic=magic)
                self.log("Order send result for", a["account"], ":", res)
            else:
                price = entry_price
                if side == "buy":
                    pending_type = mt5.ORDER_TYPE_BUY_LIMIT if price < market_price else mt5.ORDER_TYPE_BUY_STOP
                else:
                    pending_type = mt5.ORDER_TYPE_SELL_LIMIT if price > market_price else mt5.ORDER_TYPE_SELL_STOP
                slp = compute_sl_tp(price, side, sl_text)
                tpp = compute_sl_tp(price, side, tp_text)
                magic = int(magic_override) if magic_override else int(a.get("magic_number", 0))
                res = place_pending_order(symbol, pending_type, price, vol, slp, tpp, deviation=int(deviation), magic=magic)
                self.log("Pending order result for", a["account"], ":", res)
            time.sleep(0.4)
        self.log("Finished placing orders.")

    def close_all_clicked(self):
        if not mt5_available():
            messagebox.showerror("MT5 missing", "MetaTrader5 package not available.")
            return
        accounts = self.get_active_accounts()
        if not accounts:
            messagebox.showinfo("No accounts", "No active accounts.")
            return
        if not messagebox.askyesno("Confirm", f"Close all positions on {len(accounts)} accounts?"):
            return
        threading.Thread(target=self._close_all_worker, args=(accounts,), daemon=True).start()

    def _close_all_worker(self, accounts):
        self.log("Starting close-all on", len(accounts), "accounts")
        for a in accounts:
            ok, info = login_account(a["account"], a.get("password",""), a.get("server",""))
            if not ok:
                self.log("Login failed for", a["account"], ":", info)
                continue
            self.log("Logged in", a["account"], "Balance=", info.balance)
            ok2, msg = close_all_positions_for_account(log_fn=self.log)
            if ok2:
                self.log("Closed on", a["account"], ":", msg)
            else:
                self.log("Error closing on", a["account"], ":", msg)
            time.sleep(0.4)
        self.log("Finished close-all.")

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
        if not n:
            messagebox.showerror("Error", "Group name required")
            return
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
        if not group_names:
            self.group_cb['values'] = ["default"]
            self.group_cb.set("default")
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
        if not accid:
            messagebox.showerror("Error", "Account ID required")
            return
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