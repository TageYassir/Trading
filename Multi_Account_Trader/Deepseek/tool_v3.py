#!/usr/bin/env python3
"""
MT5 Manager - Multi Account Trader with Group Trading this code is good only for brocker and has multiple problems
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
from pathlib import Path

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

try:
    import MetaTrader5 as mt5
except Exception:
    mt5 = None

# Config
ACCOUNTS_FILE = "version2/mt5_accounts.json"
SETTINGS_FILE = "version2/mt5_settings.json"

# Default settings - YOU CAN MODIFY THESE DELAYS
DEFAULT_SETTINGS = {
    "init_delay": 3.0,  # Seconds to wait after MT5 initialization
    "login_delay": 2.0,  # Seconds to wait after login before trading
    "trade_delay": 2.0,  # Seconds to wait between trade attempts
    "shutdown_delay": 2.0,  # Seconds to wait after shutdown before next account
    "between_accounts_delay": 3.0,  # Seconds between processing different accounts
    "retry_delay": 2.0,  # Seconds between trade retries on same account
    "max_retries": 2,  # Max trade retry attempts
    "positions_refresh_interval": 30.0,  # Seconds between position refreshes
    "auto_refresh_positions": False,  # Auto-refresh positions by default
    "debug_mode": True,  # Show detailed debug info
    "filling_mode": "FOK",  # Default filling mode: FOK, IOC, or RETURN
}


def load_settings():
    """Load settings from file or create defaults"""
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                settings = json.load(f)
            # Merge with defaults in case new settings were added
            for key, value in DEFAULT_SETTINGS.items():
                if key not in settings:
                    settings[key] = value
            return settings
        except:
            return DEFAULT_SETTINGS.copy()
    return DEFAULT_SETTINGS.copy()


def save_settings(settings):
    """Save settings to file"""
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=2)


# Load settings at startup
SETTINGS = load_settings()


# Setup logging
def setup_logging():
    """Setup logging to file and console"""
    log_dir = "../logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    logger = logging.getLogger('MT5Manager')
    logger.setLevel(logging.DEBUG if SETTINGS.get('debug_mode', True) else logging.INFO)
    logger.handlers.clear()

    # File handler
    log_file = os.path.join(log_dir, f'mt5_manager_{datetime.datetime.now().strftime("%Y%m%d")}.log')
    fh = logging.FileHandler(log_file, encoding='utf-8')
    fh.setLevel(logging.DEBUG)

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)

    # Same format as app log
    formatter = logging.Formatter('%(asctime)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)

    logger.addHandler(fh)
    logger.addHandler(ch)

    return logger


logger = setup_logging()


def log_message(message, level='INFO'):
    """Unified logging"""
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    full_message = f"{timestamp} - {message}"

    if level == 'ERROR':
        logger.error(message)
    elif level == 'WARNING':
        logger.warning(message)
    elif level == 'DEBUG':
        logger.debug(message)
    else:
        logger.info(message)

    return full_message


def default_store():
    return {"accounts": [],
            "groups": [{"name": "default", "vol_multiplier": 1.0, "forced_volume": 0.0, "active": True}],
            "source_package": ""}


def load_store(path=ACCOUNTS_FILE):
    if not os.path.exists(path):
        return default_store()
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return {"accounts": data,
                "groups": [{"name": "default", "vol_multiplier": 1.0, "forced_volume": 0.0, "active": True}],
                "source_package": ""}
    if "accounts" not in data:
        data["accounts"] = []
    if "groups" not in data or not data["groups"]:
        data["groups"] = [{"name": "default", "vol_multiplier": 1.0, "forced_volume": 0.0, "active": True}]
    if "source_package" not in data:
        data["source_package"] = ""
    return data


def save_store(store, path=ACCOUNTS_FILE):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)


def safe_shutdown_mt5():
    """Safely shutdown MT5 - force kill if needed"""
    try:
        # First try normal shutdown
        try:
            terminal_info = mt5.terminal_info()
            if terminal_info is not None:
                log_message("Shutting down MT5 normally...", 'DEBUG')
                mt5.shutdown()
                time.sleep(1)
        except:
            pass

        # Always force kill MT5 processes to ensure clean state
        log_message("Force killing MT5 processes...", 'DEBUG')

        if os.name == 'nt':  # Windows
            # Method 1: Kill specific process names
            processes_to_kill = [
                'terminal64.exe',
                'terminal.exe',
                'metatrader5.exe',
                'metaeditor64.exe',
                'metaeditor.exe'
            ]

            for proc in processes_to_kill:
                try:
                    result = subprocess.run(
                        ['taskkill', '/F', '/IM', proc],
                        capture_output=True,
                        text=True,
                        timeout=10
                    )
                    if result.returncode == 0:
                        log_message(f"Killed: {proc}", 'DEBUG')
                except subprocess.TimeoutExpired:
                    log_message(f"Timeout killing {proc}", 'WARNING')
                except Exception as e:
                    pass  # Process might not be running

            # Method 2: Kill by window title (more aggressive)
            try:
                subprocess.run(
                    ['taskkill', '/F', '/FI', 'WINDOWTITLE eq *MetaTrader*'],
                    capture_output=True,
                    timeout=10
                )
            except:
                pass

            # Method 3: Kill all processes with "terminal" or "metatrader" in name
            try:
                result = subprocess.run(
                    'wmic process where "name like \'%terminal%\' or name like \'%metatrader%\'" delete',
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=10
                )
            except:
                pass

        else:  # Linux/Mac
            try:
                subprocess.run(['pkill', '-9', '-f', 'terminal64'], timeout=10)
                subprocess.run(['pkill', '-9', '-f', 'terminal.exe'], timeout=10)
                subprocess.run(['pkill', '-9', '-f', 'metatrader'], timeout=10)
            except:
                pass

        # Wait for processes to actually die
        time.sleep(2)

        # Verify no MT5 processes are running
        if os.name == 'nt':
            try:
                result = subprocess.run(
                    ['tasklist', '/FI', 'IMAGENAME eq terminal64.exe'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if 'terminal64.exe' in result.stdout:
                    log_message("WARNING: terminal64.exe still running!", 'WARNING')
                else:
                    log_message("MT5 processes successfully killed", 'DEBUG')
            except:
                pass

    except Exception as e:
        log_message(f"Error in safe_shutdown: {e}", 'ERROR')


def initialize_mt5(path=None):
    """Initialize MT5 with proper cleanup first"""
    try:
        # ALWAYS force kill before initializing
        safe_shutdown_mt5()

        # Wait longer to ensure clean state
        wait_time = SETTINGS['init_delay']
        log_message(f"Waiting {wait_time}s for cleanup...", 'DEBUG')
        time.sleep(wait_time)

        log_message("Initializing MT5...", 'DEBUG')

        # Try initialization
        if path and os.path.exists(path):
            ok = mt5.initialize(path=path)
        else:
            ok = mt5.initialize()

        if ok:
            log_message("MT5 initialized successfully")
            # Wait for terminal to fully load
            time.sleep(2)
            return True, mt5.last_error() if hasattr(mt5, 'last_error') else (1, 'Success')
        else:
            error = mt5.last_error()
            log_message(f"MT5 initialization failed: {error}", 'ERROR')
            return False, error

    except Exception as e:
        log_message(f"initialize exception: {e}", 'ERROR')
        return False, f"initialize exception: {e}"


def login_mt5(login, password, server):
    """Login to MT5 account"""
    try:
        # Check if terminal is actually running
        terminal_info = mt5.terminal_info()
        if terminal_info is None:
            log_message("Terminal not running, cannot login", 'ERROR')
            return False, "Terminal not running"

        log_message(f"Logging in account {login}...")
        res = mt5.login(int(login), password, server)

        if res:
            log_message(f"Login successful for account {login}")
            time.sleep(SETTINGS['login_delay'])
        else:
            error = mt5.last_error()
            log_message(f"Login failed for {login}: {error}", 'ERROR')

            # If authorization failed, terminal might be in bad state
            if error and error[0] == -6:
                log_message("Authorization failed - terminal may need restart", 'WARNING')

        return bool(res), mt5.last_error() if hasattr(mt5, 'last_error') else None

    except Exception as e:
        log_message(f"Login exception for {login}: {e}", 'ERROR')
        return False, str(e)


def get_account_info():
    """Get account info"""
    try:
        return mt5.account_info()
    except:
        return None


def get_positions():
    """Get open positions"""
    try:
        return mt5.positions_get()
    except:
        return None


def symbol_pip_value(symbol):
    """Calculate pip value for a symbol"""
    try:
        info = mt5.symbol_info(symbol)
        if info is None:
            return None
        digits = getattr(info, "digits", None)
        if digits is None:
            return None
        return 0.0001 if digits > 3 else 0.01
    except:
        return None


def get_filling_mode():
    """Get filling mode from settings"""
    mode = SETTINGS.get('filling_mode', 'FOK')
    if mode == 'IOC':
        return mt5.ORDER_FILLING_IOC
    elif mode == 'RETURN':
        return mt5.ORDER_FILLING_RETURN
    else:
        return mt5.ORDER_FILLING_FOK


def place_order_market(symbol, side, volume, deviation=50, price=None, sl=0.0, tp=0.0, magic=0,
                       comment="mt5_seq_trade"):
    """Place market order"""
    max_retries = SETTINGS['max_retries']
    filling_mode = get_filling_mode()

    log_message(f"Placing {side} order: {symbol} {volume}")

    try:
        si = mt5.symbol_info(symbol)
        if si is None:
            log_message(f"Symbol {symbol} not found", 'ERROR')
            return False, f"symbol {symbol} not found"

        if not si.visible:
            mt5.symbol_select(symbol, True)

        # Print symbol info
        log_message(f"Symbol: {symbol} - Min vol: {si.volume_min}, Step: {si.volume_step}")

        # Normalize volume
        vol_step = getattr(si, 'volume_step', 0.01)
        min_vol = getattr(si, 'volume_min', 0.01)
        max_vol = getattr(si, 'volume_max', 100000.0)
        normalized_volume = max(min_vol, min(max_vol, round(float(volume) / vol_step) * vol_step))
        log_message(f"Volume: {normalized_volume}")

        for retry in range(max_retries):
            if retry > 0:
                log_message(f"Retry {retry + 1}/{max_retries}")
                time.sleep(SETTINGS['retry_delay'])

            # Get fresh price
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                log_message(f"No tick data for {symbol}", 'ERROR')
                continue

            log_message(f"Bid: {tick.bid}, Ask: {tick.ask}")

            if tick.bid == 0.0 and tick.ask == 0.0:
                log_message("⚠ Market closed - Bid/Ask are 0", 'WARNING')
                return False, "Market closed"

            if side.lower() == "buy":
                order_type = mt5.ORDER_TYPE_BUY
                price_to_use = tick.ask if price is None else price
            else:
                order_type = mt5.ORDER_TYPE_SELL
                price_to_use = tick.bid if price is None else price

            req = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": normalized_volume,
                "type": order_type,
                "price": float(price_to_use),
                "sl": float(sl) if sl else 0.0,
                "tp": float(tp) if tp else 0.0,
                "deviation": int(deviation),
                "magic": int(magic),
                "comment": comment,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": filling_mode,
            }

            try:
                result = mt5.order_send(req)
            except Exception as e:
                log_message(f"Order send exception: {e}", 'ERROR')
                continue

            if result is None:
                log_message(f"Order failed: {mt5.last_error()}", 'ERROR')
                continue

            log_message(f"Retcode: {result.retcode}, Comment: {result.comment}")

            # Handle retcodes
            if result.retcode == 10009:
                log_message("✓ TRADE SUCCESS - Order executed!")
                return True, result
            elif result.retcode == 10018:
                log_message("✗ Market is closed right now", 'WARNING')
                return False, "Market closed"
            elif result.retcode == 10030:
                log_message(f"✗ Unsupported filling mode ({SETTINGS.get('filling_mode', 'FOK')})", 'ERROR')
                return False, "Unsupported filling mode"
            elif result.retcode == 10016:
                log_message("✗ Invalid stops", 'ERROR')
                return True, result
            elif result.retcode == 10019:
                log_message("✗ No quotes", 'ERROR')
                return False, "No quotes"
            else:
                log_message(f"Retcode: {result.retcode}")
                return True, result

        return False, "All retries failed"

    except Exception as e:
        log_message(f"Exception in order: {e}", 'ERROR')
        return False, str(e)


def close_position(ticket, symbol, volume, position_type):
    """Close a specific position"""
    try:
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return False, f"no tick for {symbol}"

        if int(position_type) == 0:
            price = tick.bid
            order_type = mt5.ORDER_TYPE_SELL
        else:
            price = tick.ask
            order_type = mt5.ORDER_TYPE_BUY

        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(volume),
            "type": order_type,
            "position": int(ticket),
            "price": price,
            "deviation": 50,
            "magic": 0,
            "comment": "close_mt5_manager",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        res = mt5.order_send(req)
        return True, res
    except Exception as e:
        return False, str(e)


# GUI Application
class MT5ManagerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("MT5 Manager — Multi Account Trader")
        self.root.geometry("1100x750")

        self.store = load_store()
        self.settings = load_settings()

        if "accounts" not in self.store:
            self.store = default_store()
        self.ensure_account_defaults()

        self.positions_q = queue.Queue()
        self.prev_positions_map = {}
        self.auto_refresh = tk.BooleanVar(value=self.settings.get('auto_refresh_positions', False))
        self.refresh_interval = tk.DoubleVar(value=self.settings.get('positions_refresh_interval', 30))
        self.refresh_paused = not self.settings.get('auto_refresh_positions', False)

        self.use_gui_session = tk.BooleanVar(value=False)
        self.terminal_path_var = tk.StringVar(value="")

        # Trading parameters
        self.symbol_var = tk.StringVar(value="EURUSD")
        self.side_var = tk.StringVar(value="buy")
        self.volume_var = tk.StringVar(value="0.1")
        self.deviation_var = tk.StringVar(value="50")
        self.sl_var = tk.StringVar(value="")
        self.tp_var = tk.StringVar(value="")
        self.magic_var = tk.StringVar(value="0")
        self.entry_price_var = tk.StringVar(value="")
        self.sl_mode_var = tk.StringVar(value="pips")
        self.tp_mode_var = tk.StringVar(value="pips")
        self.order_type_var = tk.StringVar(value="market")
        self.pending_type_var = tk.StringVar(value="limit")

        # Delay settings variables
        self.init_delay_var = tk.DoubleVar(value=self.settings['init_delay'])
        self.login_delay_var = tk.DoubleVar(value=self.settings['login_delay'])
        self.trade_delay_var = tk.DoubleVar(value=self.settings['trade_delay'])
        self.shutdown_delay_var = tk.DoubleVar(value=self.settings['shutdown_delay'])
        self.between_accounts_delay_var = tk.DoubleVar(value=self.settings['between_accounts_delay'])
        self.retry_delay_var = tk.DoubleVar(value=self.settings['retry_delay'])
        self.max_retries_var = tk.IntVar(value=self.settings['max_retries'])
        self.filling_mode_var = tk.StringVar(value=self.settings.get('filling_mode', 'FOK'))

        self._build_ui()
        self._refresh_lists()
        self._start_positions_refresher_thread()
        self._start_positions_queue_processor()

        log_message("MT5 Manager initialized")

    def ensure_account_defaults(self):
        for a in self.store.get("accounts", []):
            a.setdefault("name", str(a.get("account", "")))
            a.setdefault("account", a.get("account", ""))
            a.setdefault("password", a.get("password", ""))
            a.setdefault("server", a.get("server", ""))
            a.setdefault("active", a.get("active", True))
            a.setdefault("group", a.get("group", "default"))

    def log(self, *parts, level='INFO'):
        """Unified logging - shows in UI AND file/console"""
        message = " ".join(str(p) for p in parts)
        full_message = log_message(message, level)

        # Show in UI text widget
        self.log_txt.configure(state=tk.NORMAL)
        self.log_txt.insert(tk.END, full_message + "\n")
        self.log_txt.see(tk.END)
        self.log_txt.configure(state=tk.DISABLED)

    def _build_ui(self):
        main = ttk.Frame(self.root)
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Top controls
        top_controls = ttk.Frame(main)
        top_controls.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(top_controls, text="Terminal exe:").pack(side=tk.LEFT)
        self.terminal_entry = ttk.Entry(top_controls, textvariable=self.terminal_path_var, width=50)
        self.terminal_entry.pack(side=tk.LEFT, padx=4)
        ttk.Button(top_controls, text="Browse...", command=self.browse_terminal).pack(side=tk.LEFT)

        # Main container
        paned = ttk.PanedWindow(main, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # Left panel - Accounts and Groups
        left = ttk.Frame(paned)
        paned.add(left, weight=1)

        # Groups
        group_frame = ttk.LabelFrame(left, text="Groups")
        group_frame.pack(fill=tk.X, pady=(0, 8))
        self.groups_tree = ttk.Treeview(group_frame, columns=("name", "vol", "forced", "active"), show="headings",
                                        height=4)
        for col, text in [("name", "Name"), ("vol", "VolX"), ("forced", "ForcedVol"), ("active", "Active")]:
            self.groups_tree.heading(col, text=text)
            self.groups_tree.column(col, width=80, anchor="center")
        self.groups_tree.pack(fill=tk.X)
        gbtns = ttk.Frame(group_frame)
        gbtns.pack(fill=tk.X, pady=4)
        ttk.Button(gbtns, text="+", width=3, command=self.add_group).pack(side=tk.LEFT)
        ttk.Button(gbtns, text="Edit", command=self.edit_group).pack(side=tk.LEFT, padx=2)
        ttk.Button(gbtns, text="Del", command=self.remove_group).pack(side=tk.LEFT)

        # Accounts
        acct_frame = ttk.LabelFrame(left, text="Accounts")
        acct_frame.pack(fill=tk.BOTH, expand=True)
        self.accounts_tree = ttk.Treeview(acct_frame, columns=("id", "server", "group", "active"), show="headings",
                                          height=8)
        for col, text in [("id", "Account"), ("server", "Server"), ("group", "Group"), ("active", "Active")]:
            self.accounts_tree.heading(col, text=text)
            self.accounts_tree.column(col, width=100, anchor="center")
        self.accounts_tree.pack(fill=tk.BOTH, expand=True)
        abtns = ttk.Frame(acct_frame)
        abtns.pack(fill=tk.X, pady=4)
        ttk.Button(abtns, text="+", width=3, command=self.add_account).pack(side=tk.LEFT)
        ttk.Button(abtns, text="Edit", command=self.edit_account).pack(side=tk.LEFT, padx=2)
        ttk.Button(abtns, text="Del", command=self.remove_account).pack(side=tk.LEFT)
        ttk.Button(abtns, text="Save", command=self.save_store_now).pack(side=tk.RIGHT)

        # Right panel
        right = ttk.Frame(paned)
        paned.add(right, weight=2)

        # Notebook for tabs
        notebook = ttk.Notebook(right)
        notebook.pack(fill=tk.BOTH, expand=True)

        # Trading Tab
        trade_tab = ttk.Frame(notebook)
        notebook.add(trade_tab, text="Trading")

        # Trading parameters
        trade_frame = ttk.LabelFrame(trade_tab, text="Order Parameters")
        trade_frame.pack(fill=tk.X, padx=4, pady=4)

        # Row 1: Symbol, Volume, Deviation
        row1 = ttk.Frame(trade_frame)
        row1.pack(fill=tk.X, pady=2)
        ttk.Label(row1, text="Symbol:").pack(side=tk.LEFT)
        ttk.Entry(row1, textvariable=self.symbol_var, width=10).pack(side=tk.LEFT, padx=4)
        ttk.Label(row1, text="Volume:").pack(side=tk.LEFT, padx=(8, 0))
        ttk.Entry(row1, textvariable=self.volume_var, width=8).pack(side=tk.LEFT, padx=4)
        ttk.Label(row1, text="Deviation:").pack(side=tk.LEFT, padx=(8, 0))
        ttk.Entry(row1, textvariable=self.deviation_var, width=5).pack(side=tk.LEFT, padx=4)

        # Row 2: Buy/Sell, Market/Pending
        row2 = ttk.Frame(trade_frame)
        row2.pack(fill=tk.X, pady=2)
        ttk.Radiobutton(row2, text="BUY", variable=self.side_var, value="buy").pack(side=tk.LEFT)
        ttk.Radiobutton(row2, text="SELL", variable=self.side_var, value="sell").pack(side=tk.LEFT, padx=8)
        ttk.Separator(row2, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Radiobutton(row2, text="Market", variable=self.order_type_var, value="market").pack(side=tk.LEFT)
        ttk.Radiobutton(row2, text="Pending", variable=self.order_type_var, value="pending").pack(side=tk.LEFT, padx=8)
        ttk.Label(row2, text="Magic:").pack(side=tk.LEFT, padx=(8, 0))
        ttk.Entry(row2, textvariable=self.magic_var, width=6).pack(side=tk.LEFT, padx=4)

        # Row 3: SL, TP
        row3 = ttk.Frame(trade_frame)
        row3.pack(fill=tk.X, pady=2)
        ttk.Label(row3, text="SL:").pack(side=tk.LEFT)
        ttk.Entry(row3, textvariable=self.sl_var, width=8).pack(side=tk.LEFT, padx=2)
        ttk.Radiobutton(row3, text="Pips", variable=self.sl_mode_var, value="pips").pack(side=tk.LEFT)
        ttk.Radiobutton(row3, text="Price", variable=self.sl_mode_var, value="price").pack(side=tk.LEFT, padx=4)
        ttk.Label(row3, text="TP:").pack(side=tk.LEFT, padx=(8, 0))
        ttk.Entry(row3, textvariable=self.tp_var, width=8).pack(side=tk.LEFT, padx=2)
        ttk.Radiobutton(row3, text="Pips", variable=self.tp_mode_var, value="pips").pack(side=tk.LEFT)
        ttk.Radiobutton(row3, text="Price", variable=self.tp_mode_var, value="price").pack(side=tk.LEFT)

        # Action Buttons
        act_frame = ttk.LabelFrame(trade_tab, text="Trade Actions")
        act_frame.pack(fill=tk.X, padx=4, pady=4)

        btn_frame = ttk.Frame(act_frame)
        btn_frame.pack(fill=tk.X, pady=6)
        ttk.Button(btn_frame, text="Trade Selected Account", command=self.start_selected).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Trade ALL Active Accounts", command=self.bid_all_accounts).pack(side=tk.LEFT,
                                                                                                    padx=4)
        ttk.Button(btn_frame, text="Trade GROUP", command=self.trade_group).pack(side=tk.LEFT, padx=4)

        # Group selection for group trading
        group_frame2 = ttk.Frame(act_frame)
        group_frame2.pack(fill=tk.X, pady=2)
        ttk.Label(group_frame2, text="Select Group:").pack(side=tk.LEFT)
        self.group_trade_var = tk.StringVar(value="default")
        group_names = [g["name"] for g in self.store.get("groups", [])] or ["default"]
        self.group_trade_cb = ttk.Combobox(group_frame2, values=group_names, textvariable=self.group_trade_var,
                                           state="readonly", width=15)
        self.group_trade_cb.pack(side=tk.LEFT, padx=4)

        # Settings Tab
        settings_tab = ttk.Frame(notebook)
        notebook.add(settings_tab, text="Settings")

        settings_frame = ttk.LabelFrame(settings_tab, text="Timing Delays (seconds)")
        settings_frame.pack(fill=tk.X, padx=4, pady=4)

        # Create settings entries
        delays = [
            ("MT5 Init Delay:", self.init_delay_var, "Wait after initializing MT5"),
            ("After Login Delay:", self.login_delay_var, "Wait after login before trading"),
            ("Between Trades Delay:", self.trade_delay_var, "Wait between trade attempts"),
            ("Shutdown Delay:", self.shutdown_delay_var, "Wait after shutdown before next"),
            ("Between Accounts Delay:", self.between_accounts_delay_var, "Wait between processing accounts"),
            ("Retry Delay:", self.retry_delay_var, "Wait between retry attempts"),
        ]

        for i, (label, var, tooltip) in enumerate(delays):
            frame = ttk.Frame(settings_frame)
            frame.pack(fill=tk.X, pady=2)
            ttk.Label(frame, text=label, width=22).pack(side=tk.LEFT)
            ttk.Entry(frame, textvariable=var, width=10).pack(side=tk.LEFT, padx=4)
            ttk.Label(frame, text=tooltip, foreground="gray").pack(side=tk.LEFT, padx=4)

        # Max retries
        retry_frame = ttk.Frame(settings_frame)
        retry_frame.pack(fill=tk.X, pady=2)
        ttk.Label(retry_frame, text="Max Trade Retries:", width=22).pack(side=tk.LEFT)
        ttk.Entry(retry_frame, textvariable=self.max_retries_var, width=10).pack(side=tk.LEFT, padx=4)

        # Filling mode
        fill_frame = ttk.Frame(settings_frame)
        fill_frame.pack(fill=tk.X, pady=2)
        ttk.Label(fill_frame, text="Filling Mode:", width=22).pack(side=tk.LEFT)
        filling_cb = ttk.Combobox(fill_frame, values=["FOK", "IOC", "RETURN"], textvariable=self.filling_mode_var,
                                  state="readonly", width=10)
        filling_cb.pack(side=tk.LEFT, padx=4)
        ttk.Label(fill_frame, text="FOK=Fill or Kill, IOC=Immediate or Cancel", foreground="gray").pack(side=tk.LEFT,
                                                                                                        padx=4)

        # Save settings button
        ttk.Button(settings_tab, text="Save Settings", command=self.save_settings_now).pack(pady=10)

        # Positions Tab
        pos_tab = ttk.Frame(notebook)
        notebook.add(pos_tab, text="Positions")

        pos_frame = ttk.LabelFrame(pos_tab, text="Open Positions")
        pos_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        cols = ("account", "ticket", "symbol", "type", "volume", "price", "profit")
        self.positions_tree = ttk.Treeview(pos_frame, columns=cols, show="headings", selectmode="extended")
        for c, lab in [("account", "Account"), ("ticket", "Ticket"), ("symbol", "Symbol"),
                       ("type", "Type"), ("volume", "Vol"), ("price", "Price"), ("profit", "Profit")]:
            self.positions_tree.heading(c, text=lab)
            self.positions_tree.column(c, width=90, anchor="center")
        self.positions_tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)

        pos_scroll = ttk.Scrollbar(pos_frame, command=self.positions_tree.yview)
        pos_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.positions_tree.configure(yscrollcommand=pos_scroll.set)

        pos_btns = ttk.Frame(pos_tab)
        pos_btns.pack(fill=tk.X, pady=4)
        ttk.Button(pos_btns, text="Refresh Now", command=self.refresh_positions_now).pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(pos_btns, text="Auto-Refresh", variable=self.auto_refresh).pack(side=tk.LEFT, padx=4)
        ttk.Button(pos_btns, text="Close Selected", command=self.close_selected_positions).pack(side=tk.RIGHT, padx=4)

        # Log Tab
        log_tab = ttk.Frame(notebook)
        notebook.add(log_tab, text="Log")

        log_frame = ttk.LabelFrame(log_tab, text="Activity Log")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self.log_txt = tk.Text(log_frame, height=15, state=tk.DISABLED, bg='black', fg='#00FF00')
        self.log_txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        log_scroll = ttk.Scrollbar(log_frame, command=self.log_txt.yview)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_txt.configure(yscrollcommand=log_scroll.set)

    def browse_terminal(self):
        p = filedialog.askopenfilename(title="Select terminal executable", filetypes=[("EXE files", "*.exe")])
        if p:
            self.terminal_path_var.set(p)

    def save_settings_now(self):
        """Save settings to file"""
        self.settings = {
            'init_delay': self.init_delay_var.get(),
            'login_delay': self.login_delay_var.get(),
            'trade_delay': self.trade_delay_var.get(),
            'shutdown_delay': self.shutdown_delay_var.get(),
            'between_accounts_delay': self.between_accounts_delay_var.get(),
            'retry_delay': self.retry_delay_var.get(),
            'max_retries': self.max_retries_var.get(),
            'positions_refresh_interval': self.refresh_interval.get(),
            'auto_refresh_positions': self.auto_refresh.get(),
            'debug_mode': SETTINGS.get('debug_mode', True),
            'filling_mode': self.filling_mode_var.get(),
        }
        save_settings(self.settings)
        SETTINGS.update(self.settings)
        self.log("Settings saved successfully")

    def _refresh_lists(self):
        """Refresh account and group lists"""
        for i in self.groups_tree.get_children(): self.groups_tree.delete(i)
        for idx, g in enumerate(self.store.get("groups", [])):
            active = "yes" if g.get("active", True) else "no"
            self.groups_tree.insert("", "end", iid=str(idx),
                                    values=(g.get("name"), g.get("vol_multiplier", 1.0),
                                            g.get("forced_volume", 0.0), active))

        for i in self.accounts_tree.get_children(): self.accounts_tree.delete(i)
        for idx, a in enumerate(self.store.get("accounts", [])):
            active = "yes" if a.get("active", True) else "no"
            self.accounts_tree.insert("", "end", iid=str(idx),
                                      values=(a.get("account", ""), a.get("server", ""),
                                              a.get("group", "default"), active))

        # Update group combobox
        group_names = [g["name"] for g in self.store.get("groups", [])] or ["default"]
        if hasattr(self, 'group_trade_cb'):
            self.group_trade_cb['values'] = group_names
            if self.group_trade_var.get() not in group_names:
                self.group_trade_var.set(group_names[0])

    # Account/Group management
    def add_group(self):
        dlg = GroupDialog(self.root, None)
        self.root.wait_window(dlg.top)
        if dlg.result:
            self.store["groups"].append(dlg.result)
            save_store(self.store)
            self._refresh_lists()

    def edit_group(self):
        sel = self.groups_tree.selection()
        if not sel: messagebox.showinfo("Edit Group", "Select a group"); return
        idx = int(sel[0])
        dlg = GroupDialog(self.root, self.store["groups"][idx])
        self.root.wait_window(dlg.top)
        if dlg.result: self.store["groups"][idx] = dlg.result; save_store(self.store); self._refresh_lists()

    def remove_group(self):
        sel = self.groups_tree.selection()
        if not sel: messagebox.showinfo("Remove Group", "Select a group"); return
        idx = int(sel[0])
        name = self.store["groups"][idx]["name"]
        if name == "default": messagebox.showwarning("Remove Group", "Default group cannot be removed."); return
        for a in self.store["accounts"]:
            if a.get("group") == name: a["group"] = "default"
        del self.store["groups"][idx]
        save_store(self.store)
        self._refresh_lists()

    def add_account(self):
        dlg = AccountDialog(self.root, None, self.store["groups"])
        self.root.wait_window(dlg.top)
        if dlg.result:
            self.store["accounts"].append(dlg.result)
            save_store(self.store)
            self._refresh_lists()

    def edit_account(self):
        sel = self.accounts_tree.selection()
        if not sel: messagebox.showinfo("Edit Account", "Select an account"); return
        idx = int(sel[0])
        dlg = AccountDialog(self.root, self.store["accounts"][idx], self.store["groups"])
        self.root.wait_window(dlg.top)
        if dlg.result:
            self.store["accounts"][idx] = dlg.result
            save_store(self.store)
            self._refresh_lists()

    def remove_account(self):
        sel = self.accounts_tree.selection()
        if not sel: messagebox.showinfo("Remove Account", "Select an account"); return
        idx = int(sel[0])
        a = self.store["accounts"][idx]
        if not messagebox.askyesno("Confirm delete", f"Delete account {a.get('account')}?"): return
        del self.store["accounts"][idx]
        save_store(self.store)
        self._refresh_lists()

    def save_store_now(self):
        save_store(self.store)
        self.log("Accounts saved successfully")

    def get_active_accounts(self):
        return [a for a in self.store.get("accounts", []) if a.get("active", True)]

    def get_accounts_by_group(self, group_name):
        """Get accounts belonging to a specific group"""
        return [a for a in self.store.get("accounts", []) if
                a.get("active", True) and a.get("group", "default") == group_name]

    def compute_sl_tp(self, symbol, side, value_text, mode):
        """Compute SL/TP price"""
        if not value_text or value_text.strip() == "":
            return 0.0
        try:
            value = float(value_text)
        except ValueError:
            return 0.0

        if mode == "price":
            return value

        pip_val = symbol_pip_value(symbol)
        if pip_val is None:
            pip_val = 0.0001

        if side.lower() == "buy":
            if value > 0:
                return -value * pip_val
            return 0.0
        else:
            if value > 0:
                return value * pip_val
            return 0.0

    # Trading methods
    def start_selected(self):
        sel = self.accounts_tree.selection()
        if not sel:
            messagebox.showinfo("Trade", "Select an account first")
            return
        idx = int(sel[0])
        acc = self.store["accounts"][idx]
        threading.Thread(target=self._trade_single_account, args=(acc,), daemon=True).start()

    def bid_all_accounts(self):
        accounts = self.get_active_accounts()
        if not accounts:
            messagebox.showinfo("Trade All", "No active accounts")
            return
        if not messagebox.askyesno("Confirm", f"Execute trade on {len(accounts)} accounts?"):
            return
        threading.Thread(target=self._trade_multiple_accounts, args=(accounts, "ALL ACTIVE"), daemon=True).start()

    def trade_group(self):
        """Trade all accounts in a selected group"""
        group_name = self.group_trade_var.get()
        accounts = self.get_accounts_by_group(group_name)
        if not accounts:
            messagebox.showinfo("Trade Group", f"No active accounts in group '{group_name}'")
            return
        if not messagebox.askyesno("Confirm", f"Execute trade on {len(accounts)} accounts in group '{group_name}'?"):
            return
        threading.Thread(target=self._trade_multiple_accounts, args=(accounts, f"GROUP: {group_name}"),
                         daemon=True).start()

    def _trade_single_account(self, acc):
        """Trade on a single account"""
        self._process_account_trade(acc, 1, 1)

    def _trade_multiple_accounts(self, accounts, label):
        """Trade on multiple accounts with proper delays"""
        self.log(f"=== Starting batch trade: {label} ({len(accounts)} accounts) ===")

        for i, a in enumerate(accounts):
            self.log(f"--- Account {i + 1}/{len(accounts)}: {a.get('account')} ---")

            success = self._process_account_trade(a, i + 1, len(accounts))

            # Extra wait between accounts to ensure clean state
            if i < len(accounts) - 1:  # Don't wait after last account
                wait_time = SETTINGS['between_accounts_delay']
                self.log(f"Waiting {wait_time}s before next account (cleanup)...")

                # Additional force kill during wait
                if os.name == 'nt':
                    try:
                        subprocess.run(['taskkill', '/F', '/IM', 'terminal64.exe'],
                                       capture_output=True, timeout=5)
                    except:
                        pass

                time.sleep(wait_time)

        # Final cleanup
        safe_shutdown_mt5()
        self.log(f"=== Batch trade complete: {label} ===")

    def _process_account_trade(self, acc, current_num, total):
        """Process trade for a single account"""
        if mt5 is None:
            self.log("MetaTrader5 module missing", level='ERROR')
            return False

        terminal = self.terminal_path_var.get().strip() or None
        symbol = self.symbol_var.get().strip()
        side = self.side_var.get()

        try:
            vol = float(self.volume_var.get())
        except:
            self.log("Invalid volume", level='ERROR')
            return False

        dev = int(self.deviation_var.get() or 50)
        magic = int(self.magic_var.get() or 0)
        order_type = self.order_type_var.get()

        # Initialize - this will force kill any existing MT5 processes
        self.log(f"Initializing MT5 for account {acc.get('account')}...")
        ok, ierr = initialize_mt5(terminal)
        if not ok:
            self.log(f"Init failed for {acc.get('account')}: {ierr}", level='ERROR')
            safe_shutdown_mt5()  # Make sure to cleanup
            return False

        # Verify terminal is running
        terminal_info = mt5.terminal_info()
        if terminal_info is None:
            self.log("Terminal failed to start properly", level='ERROR')
            safe_shutdown_mt5()
            return False

        # Check symbol
        si = mt5.symbol_info(symbol)
        if si is None:
            self.log(f"Symbol {symbol} not found", level='ERROR')
            safe_shutdown_mt5()
            return False

        if not si.visible:
            mt5.symbol_select(symbol, True)
            time.sleep(0.5)

        self.log(f"Symbol: {symbol} - Min vol: {si.volume_min}, Step: {si.volume_step}")

        # Login with retry
        login_attempts = 0
        max_login_attempts = 2
        logged = False

        while login_attempts < max_login_attempts:
            self.log(f"Login attempt {login_attempts + 1}/{max_login_attempts} for account {acc.get('account')}...")
            logged, le = login_mt5(acc.get("account"), acc.get("password", ""), acc.get("server", ""))

            if logged:
                break

            login_attempts += 1

            if login_attempts < max_login_attempts:
                # If login failed, try to restart the terminal
                self.log("Login failed, restarting terminal...", 'WARNING')
                safe_shutdown_mt5()
                time.sleep(3)

                # Reinitialize
                ok, ierr = initialize_mt5(terminal)
                if not ok:
                    self.log(f"Reinit failed: {ierr}", level='ERROR')
                    safe_shutdown_mt5()
                    return False

        if not logged:
            self.log(f"Login failed after {max_login_attempts} attempts for {acc.get('account')}", level='ERROR')
            safe_shutdown_mt5()
            return False

        # Get price
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            self.log(f"Failed to get tick data for {symbol}", level='ERROR')
            safe_shutdown_mt5()
            return False

        self.log(f"Bid: {tick.bid}, Ask: {tick.ask}")

        # Calculate SL/TP
        sl_price = 0.0
        tp_price = 0.0

        if order_type == "market":
            sl_val = self.sl_var.get().strip()
            tp_val = self.tp_var.get().strip()

            if sl_val:
                sl_offset = self.compute_sl_tp(symbol, side, sl_val, self.sl_mode_var.get())
                if side == "buy":
                    sl_price = tick.ask + sl_offset if sl_offset < 0 else 0.0
                else:
                    sl_price = tick.bid + sl_offset if sl_offset > 0 else 0.0

            if tp_val:
                tp_offset = self.compute_sl_tp(symbol, side, tp_val, self.tp_mode_var.get())
                if side == "buy":
                    tp_price = tick.ask + tp_offset if tp_offset > 0 else 0.0
                else:
                    tp_price = tick.bid + tp_offset if tp_offset < 0 else 0.0

            # Wait before trade
            time.sleep(SETTINGS['trade_delay'])

            self.log(f"Placing {side} order: {symbol} {vol}")
            ok2, res = place_order_market(symbol, side, vol, deviation=dev,
                                          sl=sl_price, tp=tp_price, magic=magic)

            if ok2 and hasattr(res, 'retcode'):
                if res.retcode == 10009:
                    self.log("SUCCESS - Trade executed!")
                elif res.retcode == 10018:
                    self.log("Market is closed right now", level='WARNING')
                else:
                    self.log(f"Retcode: {res.retcode}, Comment: {res.comment}")
            elif "Market closed" in str(res):
                self.log("Market is closed right now", level='WARNING')
            else:
                self.log(f"Trade failed: {res}", level='ERROR')

        # Get account status
        try:
            info = mt5.account_info()
            if info:
                self.log(f"Balance: ${info.balance:.2f} | Equity: ${info.equity:.2f}")
        except:
            pass

        try:
            positions = mt5.positions_get()
            if positions:
                self.log(f"Open positions: {len(positions)}")
            else:
                self.log("No open positions")
        except:
            pass

        # FORCE SHUTDOWN - Always kill the terminal
        self.log(f"Force closing MT5 for account {acc.get('account')}...")
        safe_shutdown_mt5()

        # Extra wait to ensure clean state for next account
        time.sleep(SETTINGS['shutdown_delay'])

        return True

    # Positions methods
    def _start_positions_refresher_thread(self):
        def refresher():
            logger.info("Positions refresh thread ready")
            while True:
                if self.auto_refresh.get() and not self.refresh_paused:
                    self._collect_positions_across_accounts()
                time.sleep(max(10, self.refresh_interval.get()))

        t = threading.Thread(target=refresher, daemon=True)
        t.start()

    def _collect_positions_across_accounts(self):
        if not self.auto_refresh.get():
            return

        accounts = self.get_active_accounts()
        if not accounts:
            return

        all_positions = []
        terminal_path = self.terminal_path_var.get().strip() or None

        for a in accounts:
            try:
                ok, ierr = initialize_mt5(terminal_path)
                if not ok:
                    safe_shutdown_mt5()
                    time.sleep(SETTINGS['shutdown_delay'])
                    continue

                if not mt5.login(int(a.get("account")), a.get("password", ""), a.get("server", "")):
                    safe_shutdown_mt5()
                    time.sleep(SETTINGS['shutdown_delay'])
                    continue

                positions = mt5.positions_get()
                if positions:
                    for p in positions:
                        all_positions.append({
                            "account": str(a.get("account")),
                            "ticket": int(p.ticket),
                            "symbol": p.symbol,
                            "type": "buy" if int(p.type) == 0 else "sell",
                            "volume": float(p.volume),
                            "price": float(getattr(p, "price_open", 0.0)),
                            "profit": float(getattr(p, "profit", 0.0)),
                        })

                safe_shutdown_mt5()
                time.sleep(SETTINGS['between_accounts_delay'])

            except Exception as e:
                log_message(f"Error collecting positions: {e}", 'ERROR')
                try:
                    safe_shutdown_mt5()
                except:
                    pass

        self.positions_q.put({"positions": all_positions, "ts": time.time()})

    def _start_positions_queue_processor(self):
        def processor():
            while True:
                try:
                    item = self.positions_q.get(timeout=0.5)
                except:
                    time.sleep(0.1)
                    continue
                self.root.after(0, self._update_positions_ui, item["positions"], item["ts"])

        t = threading.Thread(target=processor, daemon=True)
        t.start()

    def _update_positions_ui(self, positions, ts):
        for i in self.positions_tree.get_children():
            self.positions_tree.delete(i)
        for p in positions:
            values = (p["account"], p["ticket"], p["symbol"], p["type"],
                      f"{p['volume']:.2f}", f"{p['price']:.5f}", f"{p['profit']:.2f}")
            self.positions_tree.insert("", "end", iid=f"{p['account']}_{p['ticket']}", values=values)

    def refresh_positions_now(self):
        threading.Thread(target=self._collect_positions_across_accounts, daemon=True).start()

    def close_selected_positions(self):
        sel = self.positions_tree.selection()
        if not sel:
            messagebox.showinfo("Close", "Select positions to close")
            return
        if not messagebox.askyesno("Confirm", f"Close {len(sel)} positions?"):
            return

        tasks = []
        for iid in sel:
            try:
                acct, ticket = iid.split("_", 1)
                tasks.append((acct, ticket))
            except:
                pass

        threading.Thread(target=self._close_positions_worker, args=(tasks,), daemon=True).start()

    def _close_positions_worker(self, tasks):
        terminal = self.terminal_path_var.get().strip() or None

        for acct, ticket in tasks:
            acct_info = next((a for a in self.store["accounts"] if str(a.get("account")) == acct), None)
            if not acct_info:
                continue

            ok, ierr = initialize_mt5(terminal)
            if not ok:
                safe_shutdown_mt5()
                continue

            if not mt5.login(int(acct_info.get("account")), acct_info.get("password", ""), acct_info.get("server", "")):
                safe_shutdown_mt5()
                continue

            positions = mt5.positions_get()
            pos = next((p for p in (positions or []) if int(p.ticket) == int(ticket)), None)
            if pos:
                ok2, res = close_position(pos.ticket, pos.symbol, pos.volume, pos.type)
                self.log(f"Close result: {res}")

            safe_shutdown_mt5()
            time.sleep(SETTINGS['shutdown_delay'])

        self.refresh_positions_now()

    def on_closing(self):
        """Clean shutdown"""
        self.refresh_paused = True
        self.auto_refresh.set(False)
        safe_shutdown_mt5()
        self.root.destroy()


# Dialogs
class GroupDialog:
    def __init__(self, parent, group):
        self.top = tk.Toplevel(parent)
        self.top.transient(parent)
        self.top.grab_set()
        self.result = None
        self.group = dict(group) if group else {"name": "", "vol_multiplier": 1.0, "forced_volume": 0.0, "active": True}
        self._build()

    def _build(self):
        f = ttk.Frame(self.top)
        f.pack(padx=8, pady=8)
        ttk.Label(f, text="Group name:").grid(row=0, column=0, sticky=tk.W)
        self.name_e = ttk.Entry(f)
        self.name_e.grid(row=0, column=1)
        ttk.Label(f, text="Volume multiplier:").grid(row=1, column=0, sticky=tk.W)
        self.vol_e = ttk.Entry(f)
        self.vol_e.grid(row=1, column=1)
        ttk.Label(f, text="Forced volume (0=none):").grid(row=2, column=0, sticky=tk.W)
        self.forced_e = ttk.Entry(f)
        self.forced_e.grid(row=2, column=1)
        self.active_var = tk.BooleanVar(value=self.group.get("active", True))
        ttk.Checkbutton(f, text="Active", variable=self.active_var).grid(row=3, column=0, columnspan=2)
        self.name_e.insert(0, self.group.get("name", ""))
        self.vol_e.insert(0, str(self.group.get("vol_multiplier", 1.0)))
        self.forced_e.insert(0, str(self.group.get("forced_volume", 0.0)))
        ttk.Button(self.top, text="OK", command=self.ok).pack(pady=6)

    def ok(self):
        n = self.name_e.get().strip()
        if not n: messagebox.showerror("Error", "Group name required"); return
        try:
            vol = float(self.vol_e.get() or 1.0)
            forced = float(self.forced_e.get() or 0.0)
            self.result = {"name": n, "vol_multiplier": vol, "forced_volume": forced,
                           "active": bool(self.active_var.get())}
            self.top.destroy()
        except Exception as e:
            messagebox.showerror("Error", f"Invalid numbers: {e}")


class AccountDialog:
    def __init__(self, parent, account, groups):
        self.top = tk.Toplevel(parent)
        self.top.transient(parent)
        self.top.grab_set()
        self.result = None
        self.account = dict(account) if account else {"name": "", "account": "", "password": "", "server": "",
                                                      "active": True, "group": "default"}
        self.groups = groups
        self._build()

    def _build(self):
        f = ttk.Frame(self.top)
        f.pack(padx=8, pady=8)
        ttk.Label(f, text="Account ID:").grid(row=0, column=0, sticky=tk.W)
        self.acc_e = ttk.Entry(f)
        self.acc_e.grid(row=0, column=1)
        ttk.Label(f, text="Password:").grid(row=1, column=0, sticky=tk.W)
        self.pwd_e = ttk.Entry(f, show="*")
        self.pwd_e.grid(row=1, column=1)
        ttk.Label(f, text="Server:").grid(row=2, column=0, sticky=tk.W)
        self.serv_e = ttk.Entry(f)
        self.serv_e.grid(row=2, column=1)
        self.active_var = tk.BooleanVar(value=self.account.get("active", True))
        ttk.Checkbutton(f, text="Active", variable=self.active_var).grid(row=3, column=0, columnspan=2)
        ttk.Label(f, text="Group:").grid(row=4, column=0, sticky=tk.W)
        self.group_var = tk.StringVar(value=self.account.get("group", "default"))
        group_names = [g["name"] for g in self.groups] or ["default"]
        self.group_cb = ttk.Combobox(f, values=group_names, textvariable=self.group_var, state="readonly")
        self.group_cb.grid(row=4, column=1)
        self.acc_e.insert(0, self.account.get("account", ""))
        self.pwd_e.insert(0, self.account.get("password", ""))
        self.serv_e.insert(0, self.account.get("server", ""))
        ttk.Button(self.top, text="OK", command=self.ok).pack(pady=6)

    def ok(self):
        accid = self.acc_e.get().strip()
        if not accid: messagebox.showerror("Error", "Account ID required"); return
        self.result = {"name": accid, "account": accid, "password": self.pwd_e.get().strip(),
                       "server": self.serv_e.get().strip(), "active": bool(self.active_var.get()),
                       "group": self.group_var.get() or "default"}
        self.top.destroy()


def main():
    root = tk.Tk()
    app = MT5ManagerApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    log_message("Application started")
    root.mainloop()
    log_message("Application closed")


if __name__ == "__main__":
    main()