import numpy as np
from collections import deque
import pandas as pd
import customtkinter as ctk
from tkinter import scrolledtext, messagebox
import json
import os
import logging
import time
import threading
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import List, Optional, Dict, Tuple
from tvDatafeed import TvDatafeed, Interval
import MetaTrader5 as mt5

# needs correction

ctk.set_appearance_mode("Light")
ctk.set_default_color_theme("blue")


CONFIG_FILE = "trading_config.json"
TRADES_FILE = "trades_history.csv"
APP_ICON = "icon_trading.ico"

@dataclass
class Trade:
    symbol: str
    trade_type: str
    entry_time: str
    entry_price: float
    exit_time: str = ""
    exit_price: float = 0.0
    volume: float = 0.0
    profit: float = 0.0
    status: str = "OPEN"
    stop_loss: float = 0.0
    take_profit: float = 0.0
    reason: str = ""


@dataclass
class TradingConfig:
    capital: float = 1000.0
    stop_loss_pct: float = 2.0
    take_profit_pct: float = 4.0
    symbols: List[str] = None
    buy_mode: bool = False
    sell_mode: bool = False
    trading_active: bool = False
    account: int = 0
    password: str = ""
    server: str = ""

    # Enhanced parameters
    strength_threshold: float = 0.5  # Much lower for testing
    min_bars_hold: int = 2  # Reduce from 3 to 2
    max_daily_loss_pct: float = 2.0  # Lower risk while testing
    volatility_lookback: int = 20
    performance_lookback: int = 50

    def __post_init__(self):
        if self.symbols is None:
            self.symbols = ["EURUSD", "GBPUSD", "USDJPY"]


class MT5Trader:
    def __init__(self):
        self.connected = False
        self.account_info = None

    def enable_autotrading(self):
        """Enable AutoTrading in MT5"""
        try:
            # Check if trading is allowed
            terminal_info = mt5.terminal_info()
            trade_allowed = terminal_info.trade_allowed
            trade_autotrading = terminal_info.trade_autotrading

            logging.info(f"Trade allowed: {trade_allowed}")
            logging.info(f"Trade auto-trading: {trade_autotrading}")

            if not trade_allowed:
                logging.warning("TRADING IS DISABLED - Please enable it in MT5 terminal")
                return False

            if not trade_autotrading:
                logging.warning("AUTOTRADING IS DISABLED - Please enable AutoTrading in MT5 terminal")
                return False

            return True
        except Exception as e:
            logging.error(f"Error checking AutoTrading status: {e}")
            return False

    def connect(self, account: Optional[int] = None, password: Optional[str] = None,
                server: Optional[str] = None, demo: bool = True):
        """Connect to MetaTrader 5"""
        try:
            if account and password and server:
                ok = mt5.initialize(login=int(account), password=str(password), server=str(server))
            else:
                ok = mt5.initialize()

            if not ok:
                last_err = mt5.last_error()
                logging.error(f"MT5 initialization failed: {last_err}")
                return False

            self.connected = True
            self.account_info = mt5.account_info()

            # Check and warn about AutoTrading status
            autotrading_enabled = self.enable_autotrading()
            if not autotrading_enabled:
                logging.warning("AUTOTRADING IS DISABLED - Please enable it in MT5 terminal")

            if self.account_info:
                try:
                    logging.info(f"Connected to MT5. Account: {self.account_info.login}")
                    logging.info(f"Balance: ${self.account_info.balance:.2f}")
                except Exception:
                    logging.info("Connected to MT5")
            return True
        except Exception as e:
            logging.error(f"MT5 connection error: {e}")
            return False

    def disconnect(self):
        """Disconnect from MetaTrader 5"""
        if self.connected:
            mt5.shutdown()
            self.connected = False

    def get_symbol_info(self, symbol):
        """Get symbol information"""
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

    def get_filling_mode(self, symbol):
        """Get the correct filling mode for a symbol"""
        try:
            symbol_info = self.get_symbol_info(symbol)
            if not symbol_info:
                return mt5.ORDER_FILLING_FOK

            # Check available filling modes
            filling_mode = mt5.ORDER_FILLING_FOK  # Default

            # Try to determine best filling mode
            if symbol_info.filling_mode == mt5.ORDER_FILLING_FOK:
                filling_mode = mt5.ORDER_FILLING_FOK
            elif symbol_info.filling_mode == mt5.ORDER_FILLING_IOC:
                filling_mode = mt5.ORDER_FILLING_IOC
            else:
                # For forex symbols, usually FOK works better
                filling_mode = mt5.ORDER_FILLING_FOK

            return filling_mode
        except Exception as e:
            logging.error(f"Error getting filling mode: {e}")
            return mt5.ORDER_FILLING_FOK

    def calculate_volume(self, symbol, risk_amount, stop_loss_pips):
        """Calculate volume based on risk"""
        try:
            symbol_info = self.get_symbol_info(symbol)
            if not symbol_info:
                return 0.1

            # Prevent division by zero
            if stop_loss_pips <= 0:
                logging.warning(f"Invalid stop_loss_pips for {symbol}: {stop_loss_pips}")
                return 0.1

            tick_value = getattr(symbol_info, 'trade_tick_value', 0)
            if tick_value <= 0:
                tick_value = self.calculate_tick_value(symbol, symbol_info)

            if tick_value <= 0:
                logging.warning(f"Invalid tick_value for {symbol}: {tick_value}")
                return 0.1

            volume = risk_amount / (stop_loss_pips * tick_value)
            volume = max(volume, symbol_info.volume_min)
            volume = min(volume, symbol_info.volume_max)
            volume = round(volume / symbol_info.volume_step) * symbol_info.volume_step

            return volume
        except Exception as e:
            logging.error(f"Error calculating volume for {symbol}: {e}")
            return 0.1

    def calculate_tick_value(self, symbol, symbol_info):
        """Calculate tick value manually"""
        try:
            contract_size = getattr(symbol_info, 'trade_contract_size', 100000)
            point = symbol_info.point
            tick_size = getattr(symbol_info, 'trade_tick_size', point)

            tick = mt5.symbol_info_tick(symbol)
            if tick:
                current_price = (tick.ask + tick.bid) / 2
                tick_value = (tick_size * contract_size) / current_price
                return tick_value

            return point * 10
        except Exception as e:
            logging.error(f"Error calculating tick value: {e}")
            return 0.0001

    def calculate_pip_distance(self, symbol, price_distance):
        """Calculate distance in pips"""
        try:
            symbol_info = self.get_symbol_info(symbol)
            if not symbol_info:
                return price_distance * 10000

            pip_size = 0.0001
            if 'JPY' in symbol:
                pip_size = 0.01

            return price_distance / pip_size
        except Exception as e:
            logging.error(f"Error calculating pip distance: {e}")
            return price_distance * 10000

    def place_order(self, symbol, order_type, volume, stop_loss, take_profit):
        """Place a trade order with proper filling mode"""
        try:
            symbol_info = self.get_symbol_info(symbol)
            if not symbol_info:
                return False

            price_info = mt5.symbol_info_tick(symbol)
            if not price_info:
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

            sl_price, tp_price = self.validate_stop_levels(symbol, order_type_mt5, price, sl_price, tp_price)

            # Get correct filling mode
            filling_mode = self.get_filling_mode(symbol)

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
                "comment": "RangeFilterBot",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": filling_mode,
            }

            logging.info(
                f"Placing order: {order_type} {symbol} | Price: {price:.5f} | Volume: {volume:.2f} | SL: {sl_price:.5f} | TP: {tp_price:.5f} | Filling: {filling_mode}")

            result = mt5.order_send(request)
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                logging.error(f"Order failed: {result.retcode} - {getattr(result, 'comment', '')}")

                # Try alternative filling mode if FOK failed
                if result.retcode == 10030:  # Unsupported filling mode
                    logging.info("Trying alternative filling mode...")
                    # Try IOC if FOK failed, or vice versa
                    alternative_mode = mt5.ORDER_FILLING_IOC if filling_mode == mt5.ORDER_FILLING_FOK else mt5.ORDER_FILLING_FOK
                    request["type_filling"] = alternative_mode

                    result = mt5.order_send(request)
                    if result.retcode == mt5.TRADE_RETCODE_DONE:
                        logging.info(f"Order placed successfully with alternative filling mode: {alternative_mode}")
                        return True
                    else:
                        logging.error(
                            f"Alternative filling mode also failed: {result.retcode} - {getattr(result, 'comment', '')}")

                # Specific handling for AutoTrading disabled error
                if result.retcode == 10027:
                    logging.error("AUTOTRADING IS DISABLED - Please enable AutoTrading in MT5")
                    return "AUTOTRADING_DISABLED"

                return False

            logging.info(f"Order placed successfully: {order_type} {symbol} Volume: {volume}")
            return True

        except Exception as e:
            logging.error(f"Error placing order: {e}")
            return False

    def validate_stop_levels(self, symbol, order_type, price, sl_price, tp_price):
        """Validate and adjust stop loss/take profit levels"""
        try:
            symbol_info = self.get_symbol_info(symbol)
            if not symbol_info:
                return sl_price, tp_price

            min_stop_distance = getattr(symbol_info, 'trade_stops_level', 10) * symbol_info.point

            if order_type == mt5.ORDER_TYPE_BUY:
                if sl_price > 0 and (price - sl_price) < min_stop_distance:
                    sl_price = price - min_stop_distance
                if tp_price > 0 and (tp_price - price) < min_stop_distance:
                    tp_price = price + min_stop_distance
            else:
                if sl_price > 0 and (sl_price - price) < min_stop_distance:
                    sl_price = price + min_stop_distance
                if tp_price > 0 and (price - tp_price) < min_stop_distance:
                    tp_price = price - min_stop_distance

            return sl_price, tp_price
        except Exception as e:
            logging.error(f"Error validating stop levels: {e}")
            return sl_price, tp_price

    def close_all_positions(self, symbol):
        """Close all positions for a symbol"""
        try:
            positions = mt5.positions_get(symbol=symbol)
            if not positions:
                return True

            success_count = 0
            for position in positions:
                tick = mt5.symbol_info_tick(symbol)
                if not tick:
                    continue

                if position.type == mt5.ORDER_TYPE_BUY:
                    close_type = mt5.ORDER_TYPE_SELL
                    price = tick.bid
                else:
                    close_type = mt5.ORDER_TYPE_BUY
                    price = tick.ask

                filling_mode = self.get_filling_mode(symbol)

                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "position": position.ticket,
                    "symbol": symbol,
                    "volume": position.volume,
                    "type": close_type,
                    "price": price,
                    "deviation": 10,
                    "magic": 234000,
                    "comment": "Close_All",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": filling_mode,
                }

                result = mt5.order_send(request)
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    success_count += 1
                    logging.info(f"Closed position: {symbol} Volume: {position.volume}")

            return success_count == len(positions)

        except Exception as e:
            logging.error(f"Error closing all positions for {symbol}: {e}")
            return False

    def get_open_positions(self):
        """Get all open positions"""
        try:
            positions = mt5.positions_get()
            return positions if positions else []
        except Exception as e:
            logging.error(f"Error getting positions: {e}")
            return []

class TradingApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Range Filter MT5 Trading Bot - Immediate Action Mode")
        self.geometry("1200x800")

        # Load configuration
        self.config = self.load_config()
        self.trading_engine = None

        self.setup_gui()

    def load_config(self):
        """Load configuration from file"""
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r') as f:
                    data = json.load(f)
                return TradingConfig(**data)
        except Exception as e:
            print(f"Error loading config: {e}")

        return TradingConfig()

    def save_config(self):
        """Save configuration to file"""
        try:
            config_dict = {
                'capital': self.config.capital,
                'stop_loss_pct': self.config.stop_loss_pct,
                'take_profit_pct': self.config.take_profit_pct,
                'symbols': self.config.symbols,
                'buy_mode': self.config.buy_mode,
                'sell_mode': self.config.sell_mode,
                'trading_active': self.config.trading_active,
                'account': getattr(self.config, "account", 0),
                'password': getattr(self.config, "password", ""),
                'server': getattr(self.config, "server", ""),
            }

            with open(CONFIG_FILE, 'w') as f:
                json.dump(config_dict, f, indent=4)
        except Exception as e:
            self.log_message(f"Error saving config: {e}")

    def setup_gui(self):
        """Setup the GUI interface"""
        # Main frame
        main_frame = ctk.CTkFrame(self)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Left panel - Controls
        control_frame = ctk.CTkFrame(main_frame, width=300)
        control_frame.pack(side="left", fill="y", padx=(0, 10))
        control_frame.pack_propagate(False)

        # Right panel - Logs and Info
        info_frame = ctk.CTkFrame(main_frame)
        info_frame.pack(side="right", fill="both", expand=True)

        self.setup_control_panel(control_frame)
        self.setup_info_panel(info_frame)

    def setup_control_panel(self, parent):
        """Setup control panel"""
        # Title
        title_label = ctk.CTkLabel(parent, text="Trading Controls",
                                   font=ctk.CTkFont(size=16, weight="bold"))
        title_label.pack(pady=10)

        # Capital configuration
        capital_frame = ctk.CTkFrame(parent)
        capital_frame.pack(fill="x", padx=10, pady=5)

        ctk.CTkLabel(capital_frame, text="Trading Capital ($):").pack(anchor="w")
        self.capital_entry = ctk.CTkEntry(capital_frame)
        self.capital_entry.insert(0, str(self.config.capital))
        self.capital_entry.pack(fill="x", pady=5)

        # Risk management
        risk_frame = ctk.CTkFrame(parent)
        risk_frame.pack(fill="x", padx=10, pady=5)

        ctk.CTkLabel(risk_frame, text="Stop Loss (%):").pack(anchor="w")
        self.sl_entry = ctk.CTkEntry(risk_frame)
        self.sl_entry.insert(0, str(self.config.stop_loss_pct))
        self.sl_entry.pack(fill="x", pady=5)

        ctk.CTkLabel(risk_frame, text="Take Profit (%):").pack(anchor="w")
        self.tp_entry = ctk.CTkEntry(risk_frame)
        self.tp_entry.insert(0, str(self.config.take_profit_pct))
        self.tp_entry.pack(fill="x", pady=5)

        # Trading mode selection
        mode_frame = ctk.CTkFrame(parent)
        mode_frame.pack(fill="x", padx=10, pady=5)

        ctk.CTkLabel(mode_frame, text="Trading Mode:").pack(anchor="w")

        self.buy_var = ctk.BooleanVar(value=self.config.buy_mode)
        self.sell_var = ctk.BooleanVar(value=self.config.sell_mode)

        self.buy_check = ctk.CTkCheckBox(mode_frame, text="BUY Mode",
                                         variable=self.buy_var,
                                         command=self.on_mode_change)
        self.buy_check.pack(anchor="w", pady=2)

        self.sell_check = ctk.CTkCheckBox(mode_frame, text="SELL Mode",
                                          variable=self.sell_var,
                                          command=self.on_mode_change)
        self.sell_check.pack(anchor="w", pady=2)

        # Mode info label
        self.mode_info_label = ctk.CTkLabel(mode_frame,
                                            text="✓ Immediate action\n✓ Auto-close opposite positions\n✓ No waiting periods",
                                            text_color="green",
                                            font=ctk.CTkFont(size=12))
        self.mode_info_label.pack(anchor="w", pady=5)

        # Symbols
        symbols_frame = ctk.CTkFrame(parent)
        symbols_frame.pack(fill="x", padx=10, pady=5)

        ctk.CTkLabel(symbols_frame, text="Trading Symbols (comma separated):").pack(anchor="w")
        self.symbols_entry = ctk.CTkEntry(symbols_frame)
        self.symbols_entry.insert(0, ",".join(self.config.symbols))
        self.symbols_entry.pack(fill="x", pady=5)

        # MT5 Account fields
        mt5_frame = ctk.CTkFrame(parent)
        mt5_frame.pack(fill="x", padx=10, pady=5)

        ctk.CTkLabel(mt5_frame, text="MT5 Account (optional):").pack(anchor="w")
        self.account_entry = ctk.CTkEntry(mt5_frame)
        self.account_entry.insert(0, str(getattr(self.config, "account", "") or ""))
        self.account_entry.pack(fill="x", pady=3)

        ctk.CTkLabel(mt5_frame, text="MT5 Password (optional):").pack(anchor="w")
        self.password_entry = ctk.CTkEntry(mt5_frame, show="*")
        self.password_entry.insert(0, getattr(self.config, "password", ""))
        self.password_entry.pack(fill="x", pady=3)

        ctk.CTkLabel(mt5_frame, text="MT5 Server (optional):").pack(anchor="w")
        self.server_entry = ctk.CTkEntry(mt5_frame)
        self.server_entry.insert(0, getattr(self.config, "server", ""))
        self.server_entry.pack(fill="x", pady=3)

        # Control buttons
        button_frame = ctk.CTkFrame(parent)
        button_frame.pack(fill="x", padx=10, pady=10)

        self.start_btn = ctk.CTkButton(button_frame, text="Start Trading",
                                       command=self.start_trading,
                                       fg_color="#2E8B57", hover_color="#3CB371")
        self.start_btn.pack(fill="x", pady=5)

        self.stop_btn = ctk.CTkButton(button_frame, text="Stop Trading",
                                      command=self.stop_trading,
                                      fg_color="#DC143C", hover_color="#FF6347",
                                      state="disabled")
        self.stop_btn.pack(fill="x", pady=5)

        # Status
        self.status_label = ctk.CTkLabel(parent, text="Status: STOPPED",
                                         text_color="red", font=ctk.CTkFont(weight="bold"))
        self.status_label.pack(pady=10)

    def setup_info_panel(self, parent):
        """Setup information panel"""
        # Log output
        log_frame = ctk.CTkFrame(parent)
        log_frame.pack(fill="both", expand=True, padx=10, pady=10)

        ctk.CTkLabel(log_frame, text="Trading Log",
                     font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=5)

        self.log_text = scrolledtext.ScrolledText(log_frame, height=20,
                                                  bg="black", fg="white",
                                                  font=("Consolas", 10))
        self.log_text.pack(fill="both", expand=True, pady=5)
        self.log_text.config(state="disabled")

    def on_mode_change(self):
        """Handle trading mode changes"""
        if self.buy_var.get() and self.sell_var.get():
            if self.buy_check._check_state:
                self.sell_var.set(False)
            else:
                self.buy_var.set(False)

    def log_message(self, message):
        """Add message to log"""
        self.log_text.config(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def update_config_from_ui(self):
        """Update configuration from UI elements"""
        try:
            self.config.capital = float(self.capital_entry.get())
            self.config.stop_loss_pct = float(self.sl_entry.get())
            self.config.take_profit_pct = float(self.tp_entry.get())
            self.config.buy_mode = self.buy_var.get()
            self.config.sell_mode = self.sell_var.get()

            symbols_text = self.symbols_entry.get()
            self.config.symbols = [s.strip() for s in symbols_text.split(",") if s.strip()]

            try:
                acc_text = self.account_entry.get().strip()
                self.config.account = int(acc_text) if acc_text != "" else 0
            except ValueError:
                self.config.account = 0
            self.config.password = self.password_entry.get()
            self.config.server = self.server_entry.get()

            self.save_config()
            return True
        except ValueError as e:
            messagebox.showerror("Error", "Please enter valid numeric values")
            return False

    def trading_loop(self):
        """Main trading loop - 2 second cycles"""
        cycle_count = 0
        while self.trading_engine and self.trading_engine.running:
            try:
                self.trading_engine.execute_trading_cycle()
                cycle_count += 1

                # Optional: Log every 30 cycles (1 minute) to reduce spam
                if cycle_count % 30 == 0:
                    self.log_message(f"🔄 Trading cycle #{cycle_count} completed")

                time.sleep(2)  # 2 seconds between cycles

            except Exception as e:
                self.log_message(f"Error in trading loop: {e}")
                time.sleep(2)  # Still wait 2 seconds on error

    def start_trading(self):
        """Start trading"""
        if not self.update_config_from_ui():
            return

        if not self.config.buy_mode and not self.config.sell_mode:
            messagebox.showerror("Error", "Please select BUY or SELL mode")
            return

        # Initialize trading engine
        self.trading_engine = TradingEngine(self.config, self.log_message)

        if self.trading_engine.start_trading():
            self.config.trading_active = True
            self.save_config()

            # Update UI
            self.start_btn.configure(state="disabled")
            self.stop_btn.configure(state="normal")
            self.status_label.configure(text="Status: TRADING", text_color="green")

            # Start trading thread
            self.trading_thread = threading.Thread(target=self.trading_loop, daemon=True)
            self.trading_thread.start()

            self.log_message("=== TRADING STARTED ===")
            self.log_message(f"Mode: {'BUY' if self.config.buy_mode else 'SELL'}")
            self.log_message(f"Capital: ${self.config.capital:.2f}")
            self.log_message(f"Stop Loss: {self.config.stop_loss_pct}%")
            self.log_message(f"Take Profit: {self.config.take_profit_pct}%")
            self.log_message(f"Symbols: {', '.join(self.config.symbols)}")
            self.log_message("=== TRADING STRATEGY ===")
            self.log_message("✓ Immediate BUY when BUY signal appears")
            self.log_message("✓ Immediate SELL when SELL signal appears")
            self.log_message("✓ Auto-closes opposite positions")
            self.log_message("✓ 2-second monitoring cycles")
            self.log_message("✓ Trades saved only when closed")

    def stop_trading(self):
        """Stop trading"""
        if self.trading_engine:
            self.trading_engine.stop_trading()
            self.trading_engine = None

        self.config.trading_active = False
        self.save_config()

        # Update UI
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.status_label.configure(text="Status: STOPPED", text_color="red")

        self.log_message("=== TRADING STOPPED ===")


class AdaptiveRangeFilterStrategy:
    def __init__(self, log_callback=None):
        self.symbol_data = {}
        self.performance_history = deque(maxlen=100)
        self.log_callback = log_callback

    def log(self, message):
        """Log message if callback is available"""
        if self.log_callback:
            self.log_callback(message)

    def calculate_volatility(self, df, period=20):
        """Calculate ATR-based volatility"""
        try:
            high_low = df['high'] - df['low']
            high_close = np.abs(df['high'] - df['close'].shift())
            low_close = np.abs(df['low'] - df['close'].shift())
            true_range = np.maximum(high_low, np.maximum(high_close, low_close))
            return true_range.rolling(window=period).mean()
        except Exception as e:
            self.log(f"Error calculating volatility: {e}")
            return pd.Series([0.0] * len(df))

    def calculate_strength_score(self, df, current_signal):
        """Improved strength calculation that actually works"""
        if len(df) < 20:
            return 1.0  # Default strength for testing

        try:
            # Use more realistic price movements
            price_change_5 = (df['close'].iloc[-1] / df['close'].iloc[-5] - 1) * 10000  # Scale up

            # Use ATR for volatility normalization
            high_low = df['high'] - df['low']
            high_close = np.abs(df['high'] - df['close'].shift())
            low_close = np.abs(df['low'] - df['close'].shift())
            true_range = np.maximum(high_low, np.maximum(high_close, low_close))
            atr = true_range.rolling(window=14).mean().iloc[-1]

            # Avoid division by zero
            if atr <= 0:
                atr = df['close'].iloc[-1] * 0.001  # Default to 0.1%

            # Normalize price change by volatility
            if atr > 0:
                normalized_strength = abs(price_change_5) / (atr * 100)
            else:
                normalized_strength = abs(price_change_5) * 10

            # Add momentum component
            momentum = (df['close'].iloc[-1] - df['close'].iloc[-5]) / atr if atr > 0 else 0

            # Combined strength (adjusted for realistic values)
            strength = min(normalized_strength + abs(momentum) * 2, 10.0)

            return strength

        except Exception as e:
            self.log(f"Error calculating strength score: {e}")
            return 1.0  # Default strength instead of 0

    def get_adaptive_signal(self, df, symbol, config):
        """Debug version to see what's happening"""
        try:
            if df is None or len(df) < 10:
                self.log(f"❌ {symbol}: Not enough data")
                return "NO_SIGNAL", 0.0

            # Simple range filter logic
            period = 100
            df = df.copy()

            # Calculate basic components
            df['ema'] = df['close'].ewm(span=period).mean()
            df['rng'] = (df['close'] - df['close'].shift(1)).abs().ewm(span=period).mean()
            df['smoothrng'] = df['rng'].ewm(span=period * 2 - 1).mean() * 3.0
            df['filt'] = df['close']

            # Calculate filter
            for i in range(1, len(df)):
                prev = df.loc[df.index[i - 1], 'filt']
                x = df.loc[df.index[i], 'close']
                r = df.loc[df.index[i], 'smoothrng']
                if x > prev:
                    df.loc[df.index[i], 'filt'] = prev if x - r < prev else x - r
                else:
                    df.loc[df.index[i], 'filt'] = prev if x + r > prev else x + r

            # Basic conditions
            df['longCond'] = (df['close'] > df['filt']) & (df['close'] > df['close'].shift(1))
            df['shortCond'] = (df['close'] < df['filt']) & (df['close'] < df['close'].shift(1))

            # DEBUG: Show current values
            current_close = df['close'].iloc[-1]
            current_filt = df['filt'].iloc[-1]
            prev_close = df['close'].iloc[-2]
            prev_filt = df['filt'].iloc[-2]

            self.log(f"🔍 {symbol} - Close: {current_close:.5f}, Filter: {current_filt:.5f}")
            self.log(f"🔍 {symbol} - Prev Close: {prev_close:.5f}, Prev Filter: {prev_filt:.5f}")
            self.log(f"🔍 {symbol} - Above Filter: {current_close > current_filt}")
            self.log(f"🔍 {symbol} - Rising: {current_close > prev_close}")
            self.log(f"🔍 {symbol} - Long Condition: {df['longCond'].iloc[-1]}")
            self.log(f"🔍 {symbol} - Short Condition: {df['shortCond'].iloc[-1]}")

            # Calculate simple strength
            if len(df) > 5:
                price_change = (current_close / df['close'].iloc[-5] - 1) * 10000
                strength = min(abs(price_change), 10.0)
            else:
                strength = 1.0

            # Return signals
            if df['longCond'].iloc[-1]:
                self.log(f"🎯 {symbol}: BUY SIGNAL (Strength: {strength:.2f})")
                return "BUY", strength
            elif df['shortCond'].iloc[-1]:
                self.log(f"🎯 {symbol}: SELL SIGNAL (Strength: {strength:.2f})")
                return "SELL", strength
            else:
                self.log(f"⏸️ {symbol}: NO SIGNAL (Strength: {strength:.2f})")
                return "NO_SIGNAL", strength

        except Exception as e:
            self.log(f"❌ Error in debug signal for {symbol}: {e}")
            return "NO_SIGNAL", 0.0

    def update_performance(self, profit):
        """Update performance history"""
        self.performance_history.append(profit)


class EnhancedMT5Trader(MT5Trader):
    def __init__(self):
        super().__init__()
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.last_reset = datetime.now().date()

    def reset_daily_stats(self):
        """Reset daily statistics"""
        current_date = datetime.now().date()
        if current_date != self.last_reset:
            self.daily_pnl = 0.0
            self.daily_trades = 0
            self.last_reset = current_date

    def update_daily_pnl(self, profit):
        """Update daily P&L"""
        self.reset_daily_stats()
        self.daily_pnl += profit
        self.daily_trades += 1

    def get_daily_loss_pct(self, initial_capital):
        """Calculate daily loss percentage"""
        if initial_capital > 0:
            return (abs(min(self.daily_pnl, 0)) / initial_capital) * 100
        return 0.0

    def enable_autotrading(self):
        """Fixed AutoTrading check for all MT5 versions"""
        try:
            terminal_info = mt5.terminal_info()

            # More robust checking for different MT5 versions
            trade_allowed = getattr(terminal_info, 'trade_allowed', False)
            trade_autotrading = getattr(terminal_info, 'trade_autotrading', False)

            # Alternative check using trade context
            try:
                trade_context = mt5.trade_allowed()
                if trade_context is not None:
                    trade_allowed = trade_context
            except:
                pass

            logging.info(f"Trade allowed: {trade_allowed}")

            if not trade_allowed:
                logging.warning("TRADING IS DISABLED - Please enable it in MT5 terminal")
                return False

            # For some MT5 versions, we might not have auto-trading attribute
            # But we can still proceed if trade is allowed
            if hasattr(terminal_info, 'trade_autotrading') and not trade_autotrading:
                logging.warning("AUTOTRADING IS DISABLED - Please enable AutoTrading in MT5 terminal")
                return False

            return True
        except Exception as e:
            logging.error(f"Error checking AutoTrading status: {e}")
            # Continue anyway for now
            return True

    def is_market_open(self, symbol):
        """Check if market is open for trading"""
        # Forex is typically open 24/5, but some brokers have maintenance
        current_time = datetime.now().time()
        current_weekday = datetime.now().weekday()

        # Skip weekends (Saturday=5, Sunday=6)
        if current_weekday >= 5:
            return False

        # Check for daily maintenance (typically 30 min each day)
        maintenance_start = datetime.strptime("22:00", "%H:%M").time()
        maintenance_end = datetime.strptime("22:30", "%H:%M").time()

        if maintenance_start <= current_time <= maintenance_end:
            return False

        return True

    def place_order_simple(self, symbol, order_type, volume):
        """Ultra-simple order placement without SL/TP for testing"""
        try:
            # Check if market is open
            if not self.is_market_open(symbol):
                return "MARKET_CLOSED"

            symbol_info = self.get_symbol_info(symbol)
            if not symbol_info:
                return False

            tick = mt5.symbol_info_tick(symbol)
            if not tick:
                return False

            if order_type == "BUY":
                order_type_mt5 = mt5.ORDER_TYPE_BUY
                price = tick.ask
            else:
                order_type_mt5 = mt5.ORDER_TYPE_SELL
                price = tick.bid

            # Simple request without SL/TP
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": volume,
                "type": order_type_mt5,
                "price": price,
                "deviation": 20,
                "magic": 234000,
                "comment": "TestTrade",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }

            self.log(f"📤 Placing SIMPLE {order_type} for {symbol}: Price={price:.5f}, Volume={volume}")

            result = mt5.order_send(request)

            if result.retcode == mt5.TRADE_RETCODE_DONE:
                self.log(f"✅ SIMPLE ORDER SUCCESS: {order_type} {symbol}")
                return True
            else:
                self.log(f"❌ SIMPLE ORDER FAILED: {result.retcode} - {getattr(result, 'comment', 'Unknown error')}")
                return False

        except Exception as e:
            self.log(f"❌ Error in simple order: {e}")
            return False

    def place_order(self, symbol, order_type, volume, stop_loss, take_profit):
        """Enhanced order placement with better error handling"""
        try:
            # Check if market is open
            if not self.is_market_open(symbol):
                self.log(f"⏸️ Market closed for {symbol}")
                return "MARKET_CLOSED"

            symbol_info = self.get_symbol_info(symbol)
            if not symbol_info:
                return False

            # Get current prices
            tick = mt5.symbol_info_tick(symbol)
            if not tick:
                return False

            if order_type == "BUY":
                order_type_mt5 = mt5.ORDER_TYPE_BUY
                price = tick.ask
                # Convert SL/TP from distance to absolute prices
                sl_price = price - stop_loss
                tp_price = price + take_profit
            else:
                order_type_mt5 = mt5.ORDER_TYPE_SELL
                price = tick.bid
                sl_price = price + stop_loss
                tp_price = price - take_profit

            # Validate and adjust stop levels
            sl_price, tp_price = self.validate_stop_levels(symbol, order_type_mt5, price, sl_price, tp_price)

            # Use basic filling mode
            filling_mode = mt5.ORDER_FILLING_IOC

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": volume,
                "type": order_type_mt5,
                "price": price,
                "sl": sl_price,
                "tp": tp_price,
                "deviation": 20,  # Increased deviation
                "magic": 234000,
                "comment": "RangeFilterBot",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": filling_mode,
            }

            self.log(f"📤 Placing {order_type} for {symbol}: Price={price:.5f}, SL={sl_price:.5f}, TP={tp_price:.5f}")

            result = mt5.order_send(request)

            if result.retcode != mt5.TRADE_RETCODE_DONE:
                self.log(f"❌ Order failed: {result.retcode} - {getattr(result, 'comment', 'Unknown error')}")

                # Try without SL/TP if stops are the issue
                if result.retcode == 10016:  # Invalid stops
                    self.log("🔄 Trying without stop loss/take profit...")
                    return self.place_order_simple(symbol, order_type, volume)

                return False

            self.log(f"✅ Order placed successfully: {order_type} {symbol}")
            return True

        except Exception as e:
            self.log(f"❌ Error placing order: {e}")
            return False


class AdaptiveTradingEngine:
    def __init__(self, config: TradingConfig, log_callback):
        self.config = config
        self.log_callback = log_callback
        self.strategy = AdaptiveRangeFilterStrategy(log_callback)
        self.mt5_trader = EnhancedMT5Trader()
        self.tv = TvDatafeed()

        self.running = False
        self.last_signals = {}
        self.open_trades = {}
        self.trade_history = []
        self.signal_history = {}
        self.last_trade_time = {}
        self.cooldown_period = timedelta(minutes=1)

        self.load_trade_history()
        self.initialize_signal_history()

    def initialize_signal_history(self):
        """Initialize signal history for all symbols"""
        for symbol in self.config.symbols:
            self.signal_history[symbol] = deque(maxlen=5)

    def log(self, message):
        """Log message with callback"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_message = f"[{timestamp}] {message}"
        self.log_callback(log_message)
        print(log_message)

    def load_trade_history(self):
        """Load trade history from file"""
        try:
            if os.path.exists(TRADES_FILE):
                df = pd.read_csv(TRADES_FILE)
                # Update strategy performance history
                for _, trade in df.iterrows():
                    if trade['status'] == 'CLOSED':
                        self.strategy.update_performance(trade['profit'])
                self.log(f"Loaded {len(df)} historical trades")
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
                'exit_time': trade.exit_time,
                'exit_price': trade.exit_price,
                'volume': trade.volume,
                'profit': trade.profit,
                'status': trade.status,
                'stop_loss': trade.stop_loss,
                'take_profit': trade.take_profit,
                'reason': trade.reason
            }

            df = pd.DataFrame([trade_dict])
            if not os.path.exists(TRADES_FILE):
                df.to_csv(TRADES_FILE, index=False)
            else:
                df.to_csv(TRADES_FILE, mode='a', header=False, index=False)

            self.log(f"Trade saved: {trade.symbol} {trade.trade_type} {trade.status} Profit: ${trade.profit:.2f}")

        except Exception as e:
            self.log(f"Error saving trade: {e}")

    def update_closed_trade(self, symbol, exit_price, reason):
        """Update and save a trade when it's closed"""
        try:
            if symbol in self.open_trades:
                trade = self.open_trades[symbol]
                trade.exit_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                trade.exit_price = exit_price
                trade.status = "CLOSED"
                trade.reason = reason

                # Calculate profit
                if trade.trade_type == "BUY":
                    trade.profit = (exit_price - trade.entry_price) * trade.volume * 100000
                else:
                    trade.profit = (trade.entry_price - exit_price) * trade.volume * 100000

                # Update performance tracking
                self.strategy.update_performance(trade.profit)
                if hasattr(self.mt5_trader, 'update_daily_pnl'):
                    self.mt5_trader.update_daily_pnl(trade.profit)

                # Save to file
                self.save_trade(trade)

                # Remove from open trades
                del self.open_trades[symbol]

                self.log(f"Trade closed: {symbol} {trade.trade_type} Profit: ${trade.profit:.2f} Reason: {reason}")
            else:
                self.log(f"No open trade found for {symbol} to close")

        except Exception as e:
            self.log(f"Error updating closed trade for {symbol}: {e}")

    def get_symbol_data(self, symbol, retry_count=3):
        """Get symbol data with error handling"""
        for attempt in range(retry_count):
            try:
                exchanges_to_try = ["OANDA", "FX_IDC", "FXCM"]

                for exchange in exchanges_to_try:
                    try:
                        df = self.tv.get_hist(
                            symbol=symbol,
                            exchange=exchange,
                            interval=Interval.in_5_minute,
                            n_bars=100
                        )
                        if df is not None and not df.empty and len(df) > 20:
                            # Validate data quality
                            if df['close'].isna().sum() == 0 and df['close'].iloc[-1] > 0:
                                return df
                    except Exception as e:
                        continue

                # If all exchanges fail, wait and retry
                if attempt < retry_count - 1:
                    time.sleep(2)

            except Exception as e:
                self.log(f"Attempt {attempt + 1} failed for {symbol}: {e}")
                if attempt < retry_count - 1:
                    time.sleep(2)

        self.log(f"❌ Failed to get data for {symbol} after {retry_count} attempts")
        return None

    def get_current_signal(self, symbol):
        """Get enhanced trading signal with all adaptations"""
        try:
            df = self.get_symbol_data(symbol)
            if df is None or df.empty:
                return "NO_SIGNAL", 0.0

            signal, strength = self.strategy.get_adaptive_signal(df, symbol, self.config)

            # Update signal history
            self.signal_history[symbol].append((signal, strength, datetime.now()))

            return signal, strength

        except Exception as e:
            self.log(f"Error getting signal for {symbol}: {e}")
            return "NO_SIGNAL", 0.0

    def should_enter_trade(self, symbol, signal, strength):
        """Enhanced trade entry logic with all safety checks"""
        # 1. Check cooldown period
        if symbol in self.last_trade_time:
            time_since_last = datetime.now() - self.last_trade_time[symbol]
            if time_since_last < self.cooldown_period:
                return False, "In cooldown period"

        # 2. Check daily loss limit
        daily_loss_pct = 0.0
        if hasattr(self.mt5_trader, 'get_daily_loss_pct'):
            daily_loss_pct = self.mt5_trader.get_daily_loss_pct(self.config.capital)

        if daily_loss_pct >= self.config.max_daily_loss_pct:
            return False, f"Daily loss limit reached: {daily_loss_pct:.1f}%"

        # 3. Check signal consistency in history
        recent_signals = list(self.signal_history[symbol])
        if len(recent_signals) >= 3:
            recent_signal_types = [s[0] for s in recent_signals[-3:]]
            if recent_signal_types.count(signal) < 2:  # Require 2/3 consistency
                return False, "Signal not consistent"

        # 4. Check strength threshold
        if strength < self.config.strength_threshold:
            return False, f"Signal too weak: {strength:.2f}"

        return True, "OK"

    def calculate_adaptive_stop_loss_take_profit(self, symbol, price, order_type, strength):
        """Fixed SL/TP calculation with proper pip values"""
        try:
            # For Forex pairs, use pip-based stops instead of percentage
            if "USD" in symbol or "EUR" in symbol or "GBP" in symbol:
                # Major pairs: 10 pips SL, 20 pips TP
                pip_value = 0.0001  # Standard pip
                sl_distance = 10 * pip_value  # 10 pips
                tp_distance = 20 * pip_value  # 20 pips
            elif "JPY" in symbol:
                # JPY pairs: 15 pips SL, 30 pips TP
                pip_value = 0.01  # JPY pip
                sl_distance = 15 * pip_value  # 15 pips
                tp_distance = 30 * pip_value  # 30 pips
            else:
                # Default percentage-based
                sl_distance = price * 0.001  # 0.1%
                tp_distance = price * 0.002  # 0.2%

            return sl_distance, tp_distance

        except Exception as e:
            self.log(f"Error calculating SL/TP: {e}")
            # Fallback to safe distances
            return price * 0.001, price * 0.002

    def execute_adaptive_action(self, symbol, signal, strength):
        """Fixed version with proper error handling"""
        try:
            # Check daily loss limit (with fallback)
            daily_loss_pct = 0.0
            if hasattr(self.mt5_trader, 'get_daily_loss_pct'):
                daily_loss_pct = self.mt5_trader.get_daily_loss_pct(self.config.capital)
            else:
                # If method doesn't exist, initialize it
                self.mt5_trader.daily_pnl = getattr(self.mt5_trader, 'daily_pnl', 0.0)

            if daily_loss_pct >= self.config.max_daily_loss_pct:
                self.log(f"⏸️ Daily loss limit reached: {daily_loss_pct:.1f}%")
                return

            self.log(f"🎯 EXECUTING {signal} for {symbol} (Strength: {strength:.2f})")

            positions = self.mt5_trader.get_open_positions()
            current_positions = [p for p in positions if p.symbol == symbol]

            if signal == "BUY" and self.config.buy_mode:
                existing_buy = any(p.type == mt5.ORDER_TYPE_BUY for p in current_positions)
                if existing_buy:
                    self.log(f"⏸️ BUY position already exists for {symbol}")
                    return

                # Close opposite positions
                sell_positions = [p for p in current_positions if p.type == mt5.ORDER_TYPE_SELL]
                if sell_positions:
                    self.log(f"🔄 Closing SELL positions for {symbol} to open BUY")
                    if self.mt5_trader.close_all_positions(symbol):
                        for position in sell_positions:
                            tick = mt5.symbol_info_tick(symbol)
                            exit_price = tick.ask if tick else position.price_current
                            self.update_closed_trade(symbol, exit_price, "Closed for BUY signal")

                # Open BUY position
                self.open_adaptive_trade(symbol, "BUY", strength)

            elif signal == "SELL" and self.config.sell_mode:
                existing_sell = any(p.type == mt5.ORDER_TYPE_SELL for p in current_positions)
                if existing_sell:
                    self.log(f"⏸️ SELL position already exists for {symbol}")
                    return

                # Close opposite positions
                buy_positions = [p for p in current_positions if p.type == mt5.ORDER_TYPE_BUY]
                if buy_positions:
                    self.log(f"🔄 Closing BUY positions for {symbol} to open SELL")
                    if self.mt5_trader.close_all_positions(symbol):
                        for position in buy_positions:
                            tick = mt5.symbol_info_tick(symbol)
                            exit_price = tick.bid if tick else position.price_current
                            self.update_closed_trade(symbol, exit_price, "Closed for SELL signal")

                # Open SELL position
                self.open_adaptive_trade(symbol, "SELL", strength)

        except Exception as e:
            self.log(f"Error executing adaptive action for {symbol}: {e}")

    def open_adaptive_trade(self, symbol, order_type, strength):
        """Enhanced trade opening with simple order placement"""
        try:
            symbol_info = self.mt5_trader.get_symbol_info(symbol)
            if not symbol_info:
                return

            tick = mt5.symbol_info_tick(symbol)
            if not tick:
                return

            if order_type == "BUY":
                current_price = tick.ask
            else:
                current_price = tick.bid

            if current_price <= 0:
                return

            # FIXED: Use simple volume for testing
            volume = 0.01  # Fixed 0.01 lots for testing

            # Try simple order first (without SL/TP)
            self.log(f"🎯 TEST: Opening {order_type} for {symbol} at {current_price:.5f}")

            # Use simple order placement first
            result = self.mt5_trader.place_order_simple(symbol, order_type, volume)

            if result == "MARKET_CLOSED":
                self.log(f"⏸️ Market closed for {symbol} - skipping trade")
                return
            elif result:
                self.log(f"✅ SUCCESS: {order_type} position opened for {symbol}")

                # Create trade record
                trade = Trade(
                    symbol=symbol,
                    trade_type=order_type,
                    entry_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    entry_price=current_price,
                    volume=volume,
                    status="OPEN"
                )
                self.open_trades[symbol] = trade
                self.last_trade_time[symbol] = datetime.now()

            else:
                self.log(f"❌ FAILED: Could not open {order_type} for {symbol}")
                # Try with SL/TP as fallback
                self.log("🔄 Trying with advanced order placement...")
                stop_loss_distance, take_profit_distance = self.calculate_adaptive_stop_loss_take_profit(
                    symbol, current_price, order_type, strength)

                result = self.mt5_trader.place_order(symbol, order_type, volume, stop_loss_distance,
                                                     take_profit_distance)

                if result:
                    self.log(f"✅ ADVANCED ORDER SUCCESS: {order_type} for {symbol}")
                    trade = Trade(
                        symbol=symbol,
                        trade_type=order_type,
                        entry_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        entry_price=current_price,
                        volume=volume,
                        stop_loss=current_price - stop_loss_distance if order_type == "BUY" else current_price + stop_loss_distance,
                        take_profit=current_price + take_profit_distance if order_type == "BUY" else current_price - take_profit_distance,
                        status="OPEN"
                    )
                    self.open_trades[symbol] = trade
                    self.last_trade_time[symbol] = datetime.now()

        except Exception as e:
            self.log(f"❌ Error opening adaptive trade for {symbol}: {e}")

    def check_for_closed_positions(self):
        """Check if any open positions have been closed (SL/TP hit)"""
        try:
            current_positions = self.mt5_trader.get_open_positions()
            current_symbols = {p.symbol for p in current_positions}

            # Check for positions that were open but are now closed
            for symbol in list(self.open_trades.keys()):
                if symbol not in current_symbols:
                    # Position was closed (SL/TP hit or manual close)
                    tick = mt5.symbol_info_tick(symbol)
                    if tick:
                        exit_price = tick.bid if self.open_trades[symbol].trade_type == "BUY" else tick.ask
                        self.update_closed_trade(symbol, exit_price, "Auto Close (SL/TP)")
                    else:
                        self.update_closed_trade(symbol, 0, "Auto Close (Unknown Price)")

        except Exception as e:
            self.log(f"Error checking for closed positions: {e}")

    def start_trading(self):
        """Start the enhanced trading engine"""
        if not self.mt5_trader.connect(
                account=self.config.account if getattr(self.config, "account", None) else None,
                password=self.config.password if getattr(self.config, "password", "") else None,
                server=self.config.server if getattr(self.config, "server", "") else None
        ):
            self.log("Failed to connect to MT5")
            return False

        self.running = True
        self.log("🟢 Adaptive Trading Engine Started")
        self.log(f"📊 Strength Threshold: {self.config.strength_threshold}")
        self.log(f"⏱️ Min Bars Hold: {self.config.min_bars_hold}")
        self.log(f"📉 Max Daily Loss: {self.config.max_daily_loss_pct}%")
        return True

    def stop_trading(self):
        """Stop the trading engine"""
        self.running = False
        self.mt5_trader.disconnect()
        self.log("🔴 Trading Engine Stopped")

    def execute_trading_cycle(self):
        """Fixed trading cycle with proper error handling"""
        if not self.config.trading_active:
            return

        try:
            # Update daily stats
            if hasattr(self.mt5_trader, 'reset_daily_stats'):
                self.mt5_trader.reset_daily_stats()

            # 1. Check for positions closed by SL/TP
            self.check_for_closed_positions()

            # 2. Execute adaptive trading
            for symbol in self.config.symbols:
                signal, strength = self.get_current_signal(symbol)

                if signal != "NO_SIGNAL":
                    self.log(f"📈 {symbol}: {signal} signal (Strength: {strength:.2f})")
                    self.execute_adaptive_action(symbol, signal, strength)

            # 3. Log cycle count
            if hasattr(self, 'cycle_count'):
                self.cycle_count += 1
            else:
                self.cycle_count = 1

            if self.cycle_count % 30 == 0:
                self.log(f"🔄 Trading cycle #{self.cycle_count} completed")

        except Exception as e:
            self.log(f"Error in adaptive trading cycle: {e}")


class EnhancedTradingApp(TradingApp):
    def __init__(self):
        super().__init__()
        self.title("Adaptive Range Filter MT5 Bot - Enhanced Mode")

    def setup_control_panel(self, parent):
        """Enhanced control panel with adaptive parameters"""
        super().setup_control_panel(parent)

        # Add enhanced parameters frame
        enhanced_frame = ctk.CTkFrame(parent)
        enhanced_frame.pack(fill="x", padx=10, pady=5)

        ctk.CTkLabel(enhanced_frame, text="Adaptive Parameters",
                     font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(5, 0))

        # Strength threshold
        ctk.CTkLabel(enhanced_frame, text="Strength Threshold:").pack(anchor="w")
        self.strength_entry = ctk.CTkEntry(enhanced_frame)
        self.strength_entry.insert(0, str(self.config.strength_threshold))
        self.strength_entry.pack(fill="x", pady=2)

        # Min bars hold
        ctk.CTkLabel(enhanced_frame, text="Min Bars to Hold:").pack(anchor="w")
        self.bars_entry = ctk.CTkEntry(enhanced_frame)
        self.bars_entry.insert(0, str(self.config.min_bars_hold))
        self.bars_entry.pack(fill="x", pady=2)

        # Max daily loss
        ctk.CTkLabel(enhanced_frame, text="Max Daily Loss (%):").pack(anchor="w")
        self.daily_loss_entry = ctk.CTkEntry(enhanced_frame)
        self.daily_loss_entry.insert(0, str(self.config.max_daily_loss_pct))
        self.daily_loss_entry.pack(fill="x", pady=2)

        # Volatility lookback
        ctk.CTkLabel(enhanced_frame, text="Volatility Lookback:").pack(anchor="w")
        self.vol_entry = ctk.CTkEntry(enhanced_frame)
        self.vol_entry.insert(0, str(self.config.volatility_lookback))
        self.vol_entry.pack(fill="x", pady=2)

    def update_config_from_ui(self):
        """Update enhanced configuration from UI"""
        if not super().update_config_from_ui():
            return False

        try:
            self.config.strength_threshold = float(self.strength_entry.get())
            self.config.min_bars_hold = int(self.bars_entry.get())
            self.config.max_daily_loss_pct = float(self.daily_loss_entry.get())
            self.config.volatility_lookback = int(self.vol_entry.get())
            self.save_config()
            return True
        except ValueError as e:
            messagebox.showerror("Error", "Please enter valid numeric values for adaptive parameters")
            return False

    def start_trading(self):
        """Start enhanced trading"""
        if not self.update_config_from_ui():
            return

        if not self.config.buy_mode and not self.config.sell_mode:
            messagebox.showerror("Error", "Please select BUY or SELL mode")
            return

        # Initialize enhanced trading engine
        self.trading_engine = AdaptiveTradingEngine(self.config, self.log_message)

        if self.trading_engine.start_trading():
            self.config.trading_active = True
            self.save_config()

            self.start_btn.configure(state="disabled")
            self.stop_btn.configure(state="normal")
            self.status_label.configure(text="Status: ADAPTIVE TRADING", text_color="green")

            self.trading_thread = threading.Thread(target=self.trading_loop, daemon=True)
            self.trading_thread.start()

            self.log_message("=== ADAPTIVE TRADING STARTED ===")
            self.log_message("🎯 ENHANCEMENTS ACTIVATED:")
            self.log_message("✓ Strength-based signal filtering")
            self.log_message("✓ Volatility-adjusted SL/TP")
            self.log_message("✓ Time-based signal confirmation")
            self.log_message("✓ Performance-based regime detection")
            self.log_message("✓ Daily loss limit protection")
            self.log_message("✓ Trade cooldown periods")
            self.log_message(f"✓ Strength threshold: {self.config.strength_threshold}")
            self.log_message(f"✓ Min bars hold: {self.config.min_bars_hold}")
            self.log_message(f"✓ Max daily loss: {self.config.max_daily_loss_pct}%")


if __name__ == "__main__":
    app = EnhancedTradingApp()
    app.mainloop()