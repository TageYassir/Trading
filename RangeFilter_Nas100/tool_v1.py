import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, simpledialog
import customtkinter as ctk
import threading
import time
import json
import os
import pandas as pd
import numpy as np
from tvDatafeed import TvDatafeed, Interval
import MetaTrader5 as mt5
from dataclasses import dataclass
from typing import Optional, Dict, List, Tuple
import logging
from datetime import datetime, time, timedelta
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# -----------------------
# Configuration
# -----------------------
CONFIG_FILE = "parallel_trading_config.json"
TRADES_FILE = "parallel_trades_history.csv"
USERS_FILE = "parallel_trading_users.json"

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


# -----------------------
# Email Sender
# -----------------------
class EmailSender:
    def __init__(self, smtp_server: str, smtp_port: int, email: str, password: str):
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.email = email
        self.password = password

    def send_email(self, to_email: str, subject: str, message: str) -> bool:
        try:
            msg = MIMEMultipart()
            msg['From'] = self.email
            msg['To'] = to_email
            msg['Subject'] = subject
            msg.attach(MIMEText(message, 'plain'))

            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()
            server.login(self.email, self.password)
            text = msg.as_string()
            server.sendmail(self.email, to_email, text)
            server.quit()

            logging.info(f"Email sent to {to_email}")
            return True
        except Exception as e:
            logging.error(f"Failed to send email: {e}")
            return False


# -----------------------
# Data Classes
# -----------------------
@dataclass
class Trade:
    symbol: str
    trade_type: str
    entry_time: str
    entry_price: float
    volume: float
    stop_loss: float
    take_profit: float
    stop_type: str  # SwingStop, ReversalExit, BreakEven
    status: str = "OPEN"
    exit_time: str = ""
    exit_price: float = 0.0
    profit: float = 0.0
    reason: str = ""


@dataclass
class TradingConfig:
    name: str = "ParallelTrading"
    symbols: List[str] = None
    capital: float = 1000.0
    risk_per_trade: float = 0.5
    trading_active: bool = False
    email_notifications: bool = True
    start_time: str = "14:30"
    end_time: str = "18:00"
    recipients: List[Dict] = None

    # MT5 credentials
    account: int = 97178737
    password: str = "ZoZv*iY1"
    server: str = "MetaQuotes-Demo"

    def __post_init__(self):
        if self.symbols is None:
            self.symbols = ["TVC:NAS100"]
        if self.recipients is None:
            self.recipients = []


# -----------------------
# Utility Functions
# -----------------------
def save_json(file_path, data):
    try:
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=4)
        logging.info(f"Saved config to: {file_path}")
        return True
    except Exception as e:
        logging.error(f"Error saving {file_path}: {e}")
        return False


def load_json(file_path):
    try:
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                content = f.read().strip()
                if not content:
                    logging.warning(f"Empty file: {file_path}")
                    return {}
                data = json.loads(content)
            logging.info(f"Loaded config from: {file_path}")
            return data
        else:
            logging.info(f"Config file not found, creating new: {file_path}")
            return {}
    except Exception as e:
        logging.error(f"Error loading {file_path}: {e}")
        return {}


# -----------------------
# MT5 Trader (YOUR EXACT CLASS)
# -----------------------
class MT5Trader:
    def __init__(self):
        self.connected = False
        self.account_info = None

    def connect(self, account: Optional[int] = None, password: Optional[str] = None,
                server: Optional[str] = None) -> bool:
        try:
            # Initialize MT5 if not already initialized
            if not mt5.initialize():
                logging.error(f"MT5 initialization failed: {mt5.last_error()}")
                return False

            # Login if credentials provided
            if account and password and server:
                login_result = mt5.login(account=int(account), password=str(password), server=str(server))
                if not login_result:
                    logging.error(f"MT5 login failed: {mt5.last_error()}")
                    return False
            else:
                # Try to login with existing credentials
                if not mt5.login():
                    logging.warning(f"MT5 auto-login failed: {mt5.last_error()}")

            self.connected = True
            self.account_info = mt5.account_info()

            if self.account_info:
                logging.info(
                    f"✅ MT5 Connected - Account: {self.account_info.login}, Balance: {self.account_info.balance}")
            else:
                logging.info("✅ MT5 Connected - Account info not available")

            return True
        except Exception as e:
            logging.error(f"MT5 connection error: {e}")
            return False

    def disconnect(self):
        if self.connected:
            mt5.shutdown()
            self.connected = False

    def get_symbol_info(self, symbol):
        try:
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info is None:
                logging.error(f"Symbol {symbol} not found")
                return None

            if not symbol_info.visible:
                mt5.symbol_select(symbol, True)

            return symbol_info
        except Exception as e:
            logging.error(f"Error getting symbol info for {symbol}: {e}")
            return None

    def calculate_volume(self, symbol, risk_amount, stop_loss_pips):
        try:
            symbol_info = self.get_symbol_info(symbol)
            if not symbol_info:
                return 0.1

            tick_value = getattr(symbol_info, 'trade_tick_value', 0)
            if tick_value <= 0:
                # Simplified fallback
                tick_value = 0.0001

            volume = risk_amount / (stop_loss_pips * tick_value)
            volume = max(volume, symbol_info.volume_min)
            volume = min(volume, symbol_info.volume_max)
            volume = round(volume / symbol_info.volume_step) * symbol_info.volume_step

            return volume
        except Exception as e:
            logging.error(f"Error calculating volume: {e}")
            return 0.1

    def calculate_pip_distance(self, symbol, price_distance):
        pip_size = 0.0001
        if 'JPY' in symbol:
            pip_size = 0.01
        return price_distance / pip_size

    def place_order(self, symbol, order_type, volume, stop_loss, take_profit):
        """REAL TRADING: Execute actual MT5 orders"""
        try:
            symbol_info = self.get_symbol_info(symbol)
            if not symbol_info:
                print(f"❌ Symbol {symbol} not found")
                return False

            price_info = mt5.symbol_info_tick(symbol)
            if not price_info:
                print(f"❌ Cannot get price for {symbol}")
                return False

            if order_type == "BUY":
                order_type_mt5 = mt5.ORDER_TYPE_BUY
                price = price_info.ask
                sl_price = price - stop_loss
                tp_price = price + take_profit
            else:
                order_type_mt5 = mt5.ORDER_TYPE_SELL
                price = price_info.bid
                sl_price = price + stop_loss
                tp_price = price - take_profit

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": volume,
                "type": order_type_mt5,
                "price": price,
                "sl": sl_price,
                "tp": tp_price,
                "deviation": 10,
                "magic": 234000,
                "comment": "ParallelBot",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_FOK,
            }

            result = mt5.order_send(request)
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                logging.error(f"❌ Order failed: {result.retcode} - {result.comment}")
                return False

            logging.info(f"✅ Order placed successfully: {order_type} {symbol}")
            return True

        except Exception as e:
            logging.error(f"❌ Error placing order: {e}")
            return False


# -----------------------
# Range Filter Strategy
# -----------------------
class RangeFilterStrategy:
    def __init__(self):
        self.tv = TvDatafeed()

    def get_5min_signal(self, symbol):
        """Get range filter signal from completed 5-minute candle"""
        try:
            exchange = self.get_exchange(symbol)
            df = self.tv.get_hist(symbol=symbol, exchange=exchange,
                                  interval=Interval.in_5_minute, n_bars=100)

            if df is None or df.empty or len(df) < 2:
                return "NO_SIGNAL"

            # Calculate range filter on all but current forming candle
            df_completed = df.iloc[:-1].copy()
            df_completed = self.calculate_range_filter(df_completed)

            # Get signal from last completed candle
            last_candle = df_completed.iloc[-1]

            if last_candle.get('longCond', False):
                return "BUY"
            elif last_candle.get('shortCond', False):
                return "SELL"
            else:
                return "NO_SIGNAL"

        except Exception as e:
            logging.error(f"Error getting range filter signal for {symbol}: {e}")
            return "NO_SIGNAL"

    def calculate_range_filter(self, df, period=100, mult=3.0):
        """Calculate range filter indicators"""
        try:
            result_df = df.copy()

            # Calculate smooth range
            result_df['rng'] = result_df['close'].diff().abs().ewm(span=period).mean()
            result_df['smoothrng'] = result_df['rng'].ewm(span=period * 2 - 1).mean() * mult

            # Calculate filter
            filt_values = [result_df['close'].iloc[0]]
            for i in range(1, len(result_df)):
                prev_filt = filt_values[-1]
                current_close = result_df['close'].iloc[i]
                current_smoothrng = result_df['smoothrng'].iloc[i]

                if current_close > prev_filt:
                    new_filt = max(prev_filt, current_close - current_smoothrng)
                else:
                    new_filt = min(prev_filt, current_close + current_smoothrng)

                filt_values.append(new_filt)

            result_df['filt'] = filt_values

            # Calculate conditions
            result_df['filt_diff'] = result_df['filt'].diff()
            result_df['upward'] = (result_df['filt_diff'] > 0).astype(int)
            result_df['downward'] = (result_df['filt_diff'] < 0).astype(int)

            # Cumulative counts
            result_df['upward_cum'] = result_df['upward'].groupby((result_df['upward'] == 0).cumsum()).cumsum()
            result_df['downward_cum'] = result_df['downward'].groupby((result_df['downward'] == 0).cumsum()).cumsum()

            # Trading conditions
            result_df['longCond'] = (
                    (result_df['close'] > result_df['filt']) &
                    (result_df['close'] > result_df['close'].shift(1)) &
                    (result_df['upward_cum'] > 0)
            )

            result_df['shortCond'] = (
                    (result_df['close'] < result_df['filt']) &
                    (result_df['close'] < result_df['close'].shift(1)) &
                    (result_df['downward_cum'] > 0)
            )

            return result_df

        except Exception as e:
            logging.error(f"Error calculating range filter: {e}")
            return df

    def find_nearest_swing_point(self, symbol, current_price, direction, lookback_bars=30):
        """Find nearest swing point for SwingStop"""
        try:
            exchange = self.get_exchange(symbol)
            df = self.tv.get_hist(symbol=symbol, exchange=exchange,
                                  interval=Interval.in_5_minute, n_bars=lookback_bars)

            if df is None or len(df) < 10:
                # Fallback to 1% stop loss
                return current_price * 0.99 if direction == "BUY" else current_price * 1.01

            if direction == "BUY":
                # Find recent low for buy (stop below entry)
                recent_low = df['low'].tail(10).min()
                return recent_low * 0.999  # Slightly below recent low

            else:  # SELL
                # Find recent high for sell (stop above entry)
                recent_high = df['high'].tail(10).max()
                return recent_high * 1.001  # Slightly above recent high

        except Exception as e:
            logging.error(f"Error finding swing point for {symbol}: {e}")
            # Fallback to fixed percentage
            return current_price * 0.99 if direction == "BUY" else current_price * 1.01

    def get_exchange(self, symbol):
        """Get exchange for symbol"""
        if "NAS100" in symbol:
            return "TVC"
        return "OANDA"


# -----------------------
# Parallel Trading Worker
# -----------------------
class ParallelTradingWorker:
    def __init__(self, config: TradingConfig, email_sender: EmailSender, log_callback):
        self.config = config
        self.email_sender = email_sender
        self.log_callback = log_callback
        self.strategy = RangeFilterStrategy()
        self.mt5_trader = MT5Trader()

        self.running = False
        self.active_trades = {}
        self.trade_history = []

        # Parse trading hours
        self.start_time = datetime.strptime(config.start_time, "%H:%M").time()
        self.end_time = datetime.strptime(config.end_time, "%H:%M").time()

        self.load_trade_history()

    def log(self, message):
        """Log message with callback"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_message = f"[{timestamp}] {message}"
        self.log_callback(log_message)
        print(log_message)

    def is_trading_hours(self):
        """Check if current time is within trading hours"""
        current_time = datetime.now().time()
        return self.start_time <= current_time <= self.end_time

    def load_trade_history(self):
        """Load trade history from file"""
        try:
            if os.path.exists(TRADES_FILE):
                df = pd.read_csv(TRADES_FILE)
                for _, row in df.iterrows():
                    trade = Trade(
                        symbol=row['symbol'],
                        trade_type=row['trade_type'],
                        entry_time=row['entry_time'],
                        entry_price=row['entry_price'],
                        volume=row['volume'],
                        stop_loss=row['stop_loss'],
                        take_profit=row['take_profit'],
                        stop_type=row['stop_type'],
                        status=row.get('status', 'CLOSED'),
                        exit_time=row.get('exit_time', ''),
                        exit_price=row.get('exit_price', 0.0),
                        profit=row.get('profit', 0.0),
                        reason=row.get('reason', '')
                    )
                    self.trade_history.append(trade)
        except Exception as e:
            self.log(f"Error loading trade history: {e}")

    def save_trade(self, trade: Trade):
        """Save trade to history file"""
        try:
            trade_dict = {
                'symbol': trade.symbol,
                'trade_type': trade.trade_type,
                'entry_time': trade.entry_time,
                'entry_price': trade.entry_price,
                'volume': trade.volume,
                'stop_loss': trade.stop_loss,
                'take_profit': trade.take_profit,
                'stop_type': trade.stop_type,
                'status': trade.status,
                'exit_time': trade.exit_time,
                'exit_price': trade.exit_price,
                'profit': trade.profit,
                'reason': trade.reason
            }

            df = pd.DataFrame([trade_dict])
            if not os.path.exists(TRADES_FILE):
                df.to_csv(TRADES_FILE, index=False)
            else:
                df.to_csv(TRADES_FILE, mode='a', header=False, index=False)

            self.trade_history.append(trade)
            self.log(f"Trade saved: {trade.symbol} {trade.trade_type} ({trade.stop_type})")

        except Exception as e:
            self.log(f"Error saving trade: {e}")

    def execute_parallel_trades(self, symbol, direction):
        """Execute 3 parallel trades with different stop loss types"""
        if not self.is_trading_hours():
            self.log(f"⏰ Outside trading hours: {self.start_time} - {self.end_time}")
            return False

        try:
            # Get current price
            tick = mt5.symbol_info_tick(symbol)
            if not tick:
                self.log(f"❌ Cannot get tick data for {symbol}")
                return False

            entry_price = tick.ask if direction == "BUY" else tick.bid
            self.log(f"🎯 Executing {direction} at {entry_price:.2f} for {symbol}")

            # Execute three parallel trades
            trades_executed = []

            # 1. SwingStop Trade
            if self.execute_trade(symbol, direction, "SwingStop", entry_price):
                trades_executed.append("SwingStop")

            # 2. ReversalExit Trade
            if self.execute_trade(symbol, direction, "ReversalExit", entry_price):
                trades_executed.append("ReversalExit")

            # 3. BreakEven Trade
            if self.execute_trade(symbol, direction, "BreakEven", entry_price):
                trades_executed.append("BreakEven")

            if trades_executed:
                self.log(f"✅ Executed {len(trades_executed)} trades: {', '.join(trades_executed)}")
                return True
            else:
                self.log("❌ No trades were executed")
                return False

        except Exception as e:
            self.log(f"❌ Error executing parallel trades: {e}")
            return False

    def execute_trade(self, symbol, direction, stop_type, entry_price):
        """Execute single trade with specific stop loss type"""
        try:
            # Calculate stop loss based on type
            if stop_type == "SwingStop":
                stop_loss = self.strategy.find_nearest_swing_point(symbol, entry_price, direction)

            elif stop_type == "ReversalExit":
                # Initial wide stop loss
                if direction == "BUY":
                    stop_loss = entry_price * 0.98
                else:
                    stop_loss = entry_price * 1.02

            elif stop_type == "BreakEven":
                # Initial stop loss
                if direction == "BUY":
                    stop_loss = entry_price * 0.995
                else:
                    stop_loss = entry_price * 1.005
            else:
                return False

            # Calculate take profit (2:1 risk reward)
            risk_distance = abs(entry_price - stop_loss)
            if direction == "BUY":
                take_profit = entry_price + (2 * risk_distance)
            else:
                take_profit = entry_price - (2 * risk_distance)

            # Calculate position size
            risk_amount = (self.config.risk_per_trade / 100) * self.config.capital
            pip_distance = self.mt5_trader.calculate_pip_distance(symbol, risk_distance)
            volume = self.mt5_trader.calculate_volume(symbol, risk_amount, pip_distance)

            # Use MT5 trader to place order
            success = self.mt5_trader.place_order(symbol, direction, volume, risk_distance, risk_distance * 2)

            if success:
                # Create trade record
                trade = Trade(
                    symbol=symbol,
                    trade_type=direction,
                    entry_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    entry_price=entry_price,
                    volume=volume,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    stop_type=stop_type
                )

                self.save_trade(trade)
                self.log(f"✅ {stop_type} {direction} executed: Entry={entry_price:.2f}")
                return True
            else:
                return False

        except Exception as e:
            self.log(f"❌ Error executing {stop_type} trade: {e}")
            return False

    def run_trading_cycle(self):
        """Main trading cycle"""
        if not self.running or not self.config.trading_active:
            return

        try:
            # Check for new signals
            for symbol in self.config.symbols:
                clean_symbol = symbol.split(":")[1] if ":" in symbol else symbol

                # Skip if symbol has active trades
                if clean_symbol in self.active_trades:
                    continue

                # Get range filter signal
                signal = self.strategy.get_5min_signal(clean_symbol)

                if signal in ["BUY", "SELL"]:
                    self.log(f"🎯 New {signal} signal detected for {clean_symbol}")
                    self.execute_parallel_trades(clean_symbol, signal)

        except Exception as e:
            self.log(f"Error in trading cycle: {e}")

    def start_trading(self):
        """Start trading"""
        try:
            # First ensure MT5 is not running
            try:
                mt5.shutdown()
                time.sleep(1)
            except:
                pass

            # Connect to MT5 using your exact method
            success = self.mt5_trader.connect(
                account=self.config.account,
                password=self.config.password,
                server=self.config.server
            )

            if not success:
                self.log("❌ Failed to connect to MT5 - Make sure:")
                self.log("   • MT5 is installed and running")
                self.log("   • Your account credentials are correct")
                self.log("   • The server name is correct")
                return False

            self.running = True
            self.config.trading_active = True

            self.log("✅ PARALLEL TRADING STARTED")
            self.log(f"📈 Symbols: {', '.join(self.config.symbols)}")
            self.log(f"🕒 Trading Hours: {self.config.start_time} - {self.config.end_time}")
            self.log("🔧 Strategy: 3 Parallel Trades per Signal")

            return True

        except Exception as e:
            self.log(f"❌ Error starting trading: {e}")
            return False

    def stop_trading(self):
        """Stop trading"""
        self.running = False
        self.config.trading_active = False
        self.mt5_trader.disconnect()
        self.log("⏸ Parallel trading STOPPED")

    def set_trading_hours(self, start_time: str, end_time: str):
        """Update trading hours"""
        self.config.start_time = start_time
        self.config.end_time = end_time
        self.start_time = datetime.strptime(start_time, "%H:%M").time()
        self.end_time = datetime.strptime(end_time, "%H:%M").time()
        self.log(f"🕒 Trading hours updated: {start_time} - {end_time}")


# -----------------------
# Parameters Window
# -----------------------
class ParametersWindow(ctk.CTkToplevel):
    def __init__(self, parent, config, users, worker, email_sender):
        super().__init__(parent)
        self.title("Trading Parameters & Configuration")
        self.geometry("800x600")

        self.config = config
        self.users = users
        self.worker = worker
        self.email_sender = email_sender

        self.transient(parent)
        self.grab_set()

        self.init_ui()
        self.refresh_users()

    def init_ui(self):
        """Initialize parameters interface"""
        # Main notebook
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)

        # Users tab
        users_tab = ctk.CTkFrame(notebook)
        notebook.add(users_tab, text="👥 Users & Emails")
        self.setup_users_tab(users_tab)

        # Trading tab
        trading_tab = ctk.CTkFrame(notebook)
        notebook.add(trading_tab, text="⚙️ Trading Settings")
        self.setup_trading_tab(trading_tab)

    def setup_users_tab(self, parent):
        """Setup users management tab"""
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)

        # Title
        ctk.CTkLabel(parent, text="Email Recipients Management",
                     font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, pady=10)

        # Users listbox frame
        listbox_frame = ctk.CTkFrame(parent)
        listbox_frame.grid(row=1, column=0, sticky="nsew", pady=10, padx=10)
        listbox_frame.grid_columnconfigure(0, weight=1)
        listbox_frame.grid_rowconfigure(0, weight=1)

        self.user_listbox = tk.Listbox(listbox_frame, selectmode="multiple",
                                       bg="#2b2b2b", fg="white", font=("Arial", 11))
        self.user_listbox.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

        # Scrollbar for listbox
        scrollbar = ttk.Scrollbar(listbox_frame, orient="vertical", command=self.user_listbox.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.user_listbox.configure(yscrollcommand=scrollbar.set)

        # User buttons
        btn_frame = ctk.CTkFrame(parent)
        btn_frame.grid(row=2, column=0, sticky="ew", pady=10, padx=10)

        ctk.CTkButton(btn_frame, text="➕ Add User",
                      command=self.add_user).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="🗑️ Delete User",
                      command=self.delete_user,
                      fg_color="#D35B58", hover_color="#C77B78").pack(side="left", padx=5)

        # Email settings
        email_frame = ctk.CTkFrame(parent)
        email_frame.grid(row=3, column=0, sticky="ew", pady=10, padx=10)

        self.email_notifications = ctk.CTkCheckBox(email_frame, text="Enable Email Notifications")
        self.email_notifications.pack(pady=10)

        # Set current state
        self.email_notifications.select() if self.config.email_notifications else self.email_notifications.deselect()

        # Save button
        ctk.CTkButton(parent, text="Save Email Settings",
                      command=self.save_email_settings).pack(pady=10)

    def setup_trading_tab(self, parent):
        """Setup trading settings tab"""
        parent.grid_columnconfigure(0, weight=1)

        # Title
        ctk.CTkLabel(parent, text="Trading Configuration",
                     font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, pady=10)

        # Settings frame
        settings_frame = ctk.CTkFrame(parent)
        settings_frame.grid(row=1, column=0, sticky="ew", pady=10, padx=10)

        # Trading Hours
        hours_frame = ctk.CTkFrame(settings_frame)
        hours_frame.pack(fill="x", pady=5, padx=10)

        ctk.CTkLabel(hours_frame, text="Trading Hours:").pack(side="left")

        self.start_time_entry = ctk.CTkEntry(hours_frame, width=80)
        self.start_time_entry.pack(side="left", padx=(10, 5))
        self.start_time_entry.insert(0, self.config.start_time)

        ctk.CTkLabel(hours_frame, text="to").pack(side="left", padx=5)

        self.end_time_entry = ctk.CTkEntry(hours_frame, width=80)
        self.end_time_entry.pack(side="left", padx=(5, 0))
        self.end_time_entry.insert(0, self.config.end_time)

        # Capital
        capital_frame = ctk.CTkFrame(settings_frame)
        capital_frame.pack(fill="x", pady=5, padx=10)

        ctk.CTkLabel(capital_frame, text="Capital ($):").pack(side="left")
        self.capital_entry = ctk.CTkEntry(capital_frame)
        self.capital_entry.pack(side="right")
        self.capital_entry.insert(0, str(self.config.capital))

        # Risk
        risk_frame = ctk.CTkFrame(settings_frame)
        risk_frame.pack(fill="x", pady=5, padx=10)

        ctk.CTkLabel(risk_frame, text="Risk per Trade (%):").pack(side="left")
        self.risk_entry = ctk.CTkEntry(risk_frame)
        self.risk_entry.pack(side="right")
        self.risk_entry.insert(0, str(self.config.risk_per_trade))

        # Symbols
        symbols_frame = ctk.CTkFrame(settings_frame)
        symbols_frame.pack(fill="x", pady=5, padx=10)

        ctk.CTkLabel(symbols_frame, text="Trading Symbols (comma separated):").pack(anchor="w")
        self.symbols_entry = ctk.CTkEntry(symbols_frame)
        self.symbols_entry.pack(fill="x", pady=5)
        self.symbols_entry.insert(0, ", ".join(self.config.symbols))

        # Save button
        ctk.CTkButton(settings_frame, text="Save Trading Settings",
                      command=self.save_trading_settings).pack(pady=10)

    def refresh_users(self):
        """Refresh users listbox"""
        self.user_listbox.delete(0, tk.END)
        for user_data in self.users.values():
            self.user_listbox.insert(tk.END, f"{user_data['name']} ({user_data['email']})")

    def add_user(self):
        """Add new user"""
        name = simpledialog.askstring("Add User", "Enter user name:", parent=self)
        if not name:
            return

        email = simpledialog.askstring("Add User", "Enter user email:", parent=self)
        if not email:
            return

        self.users[email] = {"name": name, "email": email}
        save_json(USERS_FILE, self.users)
        self.refresh_users()

    def delete_user(self):
        """Delete selected users"""
        selected = self.user_listbox.curselection()
        if not selected:
            messagebox.showerror("Error", "Select a user to delete")
            return

        for i in reversed(selected):
            email = list(self.users.keys())[i]
            del self.users[email]

        save_json(USERS_FILE, self.users)
        self.refresh_users()

    def save_email_settings(self):
        """Save email settings"""
        try:
            self.config.email_notifications = self.email_notifications.get()
            self.config.recipients = list(self.users.values())

            save_json(CONFIG_FILE, {
                'name': self.config.name,
                'symbols': self.config.symbols,
                'capital': self.config.capital,
                'risk_per_trade': self.config.risk_per_trade,
                'trading_active': self.config.trading_active,
                'email_notifications': self.config.email_notifications,
                'start_time': self.config.start_time,
                'end_time': self.config.end_time,
                'recipients': self.config.recipients
            })

            # Update worker
            self.worker.config.email_notifications = self.config.email_notifications
            self.worker.config.recipients = self.config.recipients

            messagebox.showinfo("Success", "Email settings saved successfully!")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to save email settings: {e}")

    def save_trading_settings(self):
        """Save trading settings"""
        try:
            self.config.start_time = self.start_time_entry.get()
            self.config.end_time = self.end_time_entry.get()
            self.config.capital = float(self.capital_entry.get())
            self.config.risk_per_trade = float(self.risk_entry.get())
            self.config.symbols = [s.strip() for s in self.symbols_entry.get().split(",")]

            # Update worker
            self.worker.set_trading_hours(self.config.start_time, self.config.end_time)
            self.worker.config.capital = self.config.capital
            self.worker.config.risk_per_trade = self.config.risk_per_trade
            self.worker.config.symbols = self.config.symbols

            save_json(CONFIG_FILE, {
                'name': self.config.name,
                'symbols': self.config.symbols,
                'capital': self.config.capital,
                'risk_per_trade': self.config.risk_per_trade,
                'trading_active': self.config.trading_active,
                'email_notifications': self.config.email_notifications,
                'start_time': self.config.start_time,
                'end_time': self.config.end_time,
                'recipients': self.config.recipients
            })

            messagebox.showinfo("Success", "Trading settings saved successfully!")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to save trading settings: {e}")


# -----------------------
# GUI Application
# -----------------------
class ParallelTradingApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Parallel Trading Bot - 3 Trades per Signal")
        self.geometry("1000x700")
        self.minsize(900, 600)

        # Load configuration and users
        self.config = self.load_config()
        self.users = load_json(USERS_FILE)

        # Initialize email sender (using Gmail as default)
        self.email_sender = EmailSender(
            smtp_server="smtp.gmail.com",
            smtp_port=587,
            email="your_email@gmail.com",  # User should configure this
            password="your_app_password"  # User should configure this
        )

        self.worker = ParallelTradingWorker(self.config, self.email_sender, self.log_message)

        self.init_ui()

    def load_config(self):
        """Load configuration from file"""
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r') as f:
                    config_data = json.load(f)
                return TradingConfig(**config_data)
        except:
            pass

        # Default configuration
        return TradingConfig()

    def save_config(self):
        """Save configuration to file"""
        try:
            config_dict = {
                'name': self.config.name,
                'symbols': self.config.symbols,
                'capital': self.config.capital,
                'risk_per_trade': self.config.risk_per_trade,
                'trading_active': self.config.trading_active,
                'email_notifications': self.config.email_notifications,
                'start_time': self.config.start_time,
                'end_time': self.config.end_time,
                'recipients': self.config.recipients
            }

            with open(CONFIG_FILE, 'w') as f:
                json.dump(config_dict, f, indent=4)

        except Exception as e:
            self.log_message(f"Error saving config: {e}")

    def init_ui(self):
        """Initialize user interface"""
        # Configure main grid
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Left panel - Controls (Scrollable)
        control_frame = ctk.CTkFrame(self, width=350, corner_radius=10)
        control_frame.grid(row=0, column=0, sticky="nsew", padx=(10, 5), pady=10)
        control_frame.grid_propagate(False)

        # Right panel - Logs
        log_frame = ctk.CTkFrame(self, corner_radius=10)
        log_frame.grid(row=0, column=1, sticky="nsew", padx=(5, 10), pady=10)
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(1, weight=1)

        self.setup_control_panel(control_frame)
        self.setup_log_panel(log_frame)

    def setup_control_panel(self, parent):
        """Setup scrollable control panel"""
        # Create scrollable frame
        scrollable_frame = ctk.CTkScrollableFrame(parent, corner_radius=0)
        scrollable_frame.pack(fill="both", expand=True)
        scrollable_frame.grid_columnconfigure(0, weight=1)

        # Title
        title = ctk.CTkLabel(scrollable_frame, text="Parallel Trading Bot",
                             font=ctk.CTkFont(size=20, weight="bold"))
        title.grid(row=0, column=0, pady=20, padx=20)

        # Strategy Info
        info_text = """
🎯 TRADING STRATEGY:

• Monitor 5min Range Filter signals
• Wait for candle completion
• Execute 3 parallel trades:
  1. SwingStop - Nearest swing point
  2. ReversalExit - Next candle reversal
  3. BreakEven - Always break-even SL

• Trading Hours: 14:30 - 18:00
• Symbol: NAS100
        """

        info_frame = ctk.CTkFrame(scrollable_frame, fg_color="#2b2b2b")
        info_frame.grid(row=1, column=0, sticky="ew", padx=15, pady=10)

        info_label = ctk.CTkLabel(info_frame, text=info_text, justify="left")
        info_label.pack(padx=10, pady=10)

        # Current Settings Frame
        settings_frame = ctk.CTkFrame(scrollable_frame)
        settings_frame.grid(row=2, column=0, sticky="ew", padx=15, pady=10)

        ctk.CTkLabel(settings_frame, text="Current Settings:",
                     font=ctk.CTkFont(weight="bold")).pack(pady=5)

        # Display current settings
        settings_text = f"""
• Trading Hours: {self.config.start_time} - {self.config.end_time}
• Capital: ${self.config.capital:.2f}
• Risk per Trade: {self.config.risk_per_trade}%
• Email Notifications: {'ON' if self.config.email_notifications else 'OFF'}
• Recipients: {len(self.config.recipients)} users
• Symbols: {', '.join(self.config.symbols)}
        """

        settings_label = ctk.CTkLabel(settings_frame, text=settings_text, justify="left")
        settings_label.pack(padx=10, pady=10)

        # Control Buttons
        button_frame = ctk.CTkFrame(scrollable_frame)
        button_frame.grid(row=3, column=0, sticky="ew", padx=15, pady=10)

        self.start_btn = ctk.CTkButton(button_frame, text="START TRADING",
                                       command=self.start_trading,
                                       fg_color="#2E8B57", hover_color="#3CB371",
                                       height=40, font=ctk.CTkFont(weight="bold"))
        self.start_btn.pack(fill="x", pady=(0, 10))

        self.stop_btn = ctk.CTkButton(button_frame, text="STOP TRADING",
                                      command=self.stop_trading,
                                      fg_color="#DC143C", hover_color="#FF6347",
                                      height=40, font=ctk.CTkFont(weight="bold"))
        self.stop_btn.pack(fill="x", pady=5)

        # Parameters Button
        ctk.CTkButton(button_frame, text="⚙️ PARAMETERS & SETTINGS",
                      command=self.open_parameters,
                      height=35).pack(fill="x", pady=(10, 0))

        # Status
        self.status_label = ctk.CTkLabel(scrollable_frame, text="🔴 STOPPED",
                                         text_color="#ff6b6b",
                                         font=ctk.CTkFont(size=16, weight="bold"))
        self.status_label.grid(row=4, column=0, pady=20)

    def setup_log_panel(self, parent):
        """Setup log panel"""
        ctk.CTkLabel(parent, text="Trading Log",
                     font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, sticky="w", padx=15, pady=15)

        self.log_text = scrolledtext.ScrolledText(parent,
                                                  bg="#1a1a1a", fg="#00ff00",
                                                  font=("Consolas", 10),
                                                  insertbackground="white")
        self.log_text.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.log_text.config(state="disabled")

    def log_message(self, message):
        """Add message to log"""
        self.log_text.config(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def open_parameters(self):
        """Open parameters window"""
        ParametersWindow(self, self.config, self.users, self.worker, self.email_sender)

    def start_trading(self):
        """Start trading"""
        if self.worker.start_trading():
            self.status_label.configure(text="🟢 RUNNING", text_color="green")
            self.log_message("=== TRADING STARTED ===")

            # Start background thread
            threading.Thread(target=self.trading_loop, daemon=True).start()
        else:
            self.log_message("❌ Failed to start trading")

    def stop_trading(self):
        """Stop trading"""
        self.worker.stop_trading()
        self.status_label.configure(text="🔴 STOPPED", text_color="#ff6b6b")
        self.log_message("=== TRADING STOPPED ===")

    def trading_loop(self):
        """Main trading loop"""
        while self.worker.running:
            self.worker.run_trading_cycle()
            time.sleep(60)  # Check every minute

    def on_closing(self):
        """Handle application closing"""
        self.stop_trading()
        self.destroy()


# -----------------------
# Main Application
# -----------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    app = ParallelTradingApp()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)

    try:
        app.mainloop()
    except KeyboardInterrupt:
        print("Application interrupted by user")
    finally:
        app.stop_trading()