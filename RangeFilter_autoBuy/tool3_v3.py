import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import customtkinter as ctk
import threading
import time
import json
import os
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from tvDatafeed import TvDatafeed, Interval
import MetaTrader5 as mt5
from dataclasses import dataclass
from typing import Optional, Dict, List
import logging

# -----------------------
# Constants and Configuration
# -----------------------
CONFIG_FILE = "trading_config.json"
TRADES_FILE = "trades_history.csv"
APP_ICON = "icon_trading.ico"

# Set appearance
ctk.set_appearance_mode("Light")
ctk.set_default_color_theme("blue")


# -----------------------
# Data Classes
# -----------------------
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
    status: str = "OPEN"  # OPEN, CLOSED, STOP_LOSS, TAKE_PROFIT, SIGNAL_CLOSE
    stop_loss: float = 0.0
    take_profit: float = 0.0
    reason: str = ""  # Reason for closing


@dataclass
class TradingConfig:
    capital: float = 1000.0
    stop_loss_pct: float = 2.0
    take_profit_pct: float = 4.0
    symbols: List[str] = None
    buy_mode: bool = False
    sell_mode: bool = False
    trading_active: bool = False

    # MT5 credentials
    account: int = 0
    password: str = ""
    server: str = ""

    def __post_init__(self):
        if self.symbols is None:
            self.symbols = ["EURUSD", "GBPUSD", "USDJPY"]


# -----------------------
# Strategy Implementation
# -----------------------
class RangeFilterStrategy:
    @staticmethod
    def calculate_range_filter(df, period=100, mult=3.0):
        """Calculate Range Filter signals"""
        try:
            df = df.copy()
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
        except Exception as e:
            logging.error(f"Error in range filter calculation: {e}")
            return df

    @staticmethod
    def get_signal(df):
        """Get BUY/SELL signal from the latest data"""
        if df is None or df.empty:
            return "NO_SIGNAL"

        try:
            df = RangeFilterStrategy.calculate_range_filter(df)

            if df['longCond'].iloc[-1]:
                return "BUY"
            elif df['shortCond'].iloc[-1]:
                return "SELL"
            else:
                return "NO_SIGNAL"
        except Exception as e:
            logging.error(f"Error getting signal: {e}")
            return "NO_SIGNAL"


# -----------------------
# MetaTrader 5 Integration
# -----------------------
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

            tick_value = getattr(symbol_info, 'trade_tick_value', 0)
            if tick_value <= 0:
                tick_value = self.calculate_tick_value(symbol, symbol_info)

            if tick_value <= 0:
                return 0.1

            volume = risk_amount / (stop_loss_pips * tick_value)
            volume = max(volume, symbol_info.volume_min)
            volume = min(volume, symbol_info.volume_max)
            volume = round(volume / symbol_info.volume_step) * symbol_info.volume_step

            return volume
        except Exception as e:
            logging.error(f"Error calculating volume: {e}")
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

    def close_position(self, position, reason=""):
        """Close a position"""
        try:
            tick = mt5.symbol_info_tick(position.symbol)
            if not tick:
                return False

            if position.type == mt5.ORDER_TYPE_BUY:
                order_type = mt5.ORDER_TYPE_SELL
                price = tick.bid
            else:
                order_type = mt5.ORDER_TYPE_BUY
                price = tick.ask

            # Get correct filling mode for closing
            filling_mode = self.get_filling_mode(position.symbol)

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "position": position.ticket,
                "symbol": position.symbol,
                "volume": position.volume,
                "type": order_type,
                "price": price,
                "deviation": 10,
                "magic": 234000,
                "comment": f"Close_{reason}",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": filling_mode,
            }

            result = mt5.order_send(request)
            success = result.retcode == mt5.TRADE_RETCODE_DONE
            if success:
                logging.info(f"Position closed: {position.symbol} - Reason: {reason}")
            return success

        except Exception as e:
            logging.error(f"Error closing position: {e}")
            return False

    def get_open_positions(self):
        """Get all open positions"""
        try:
            positions = mt5.positions_get()
            return positions if positions else []
        except Exception as e:
            logging.error(f"Error getting positions: {e}")
            return []
# -----------------------
# Trading Engine
# -----------------------
class TradingEngine:
    def __init__(self, config: TradingConfig, log_callback):
        self.config = config
        self.log_callback = log_callback
        self.strategy = RangeFilterStrategy()
        self.mt5_trader = MT5Trader()
        self.tv = TvDatafeed()

        self.running = False
        self.last_signals = {}
        self.open_trades = {}
        self.trade_history = []
        self.last_check_time = {}
        self.position_monitoring = {}  # Track positions being monitored
        self.autotrading_warning_shown = False  # Track if warning was shown

        self.load_trade_history()

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

            self.trade_history.append(trade)
            self.log(f"Trade saved: {trade.symbol} {trade.trade_type} Profit: ${trade.profit:.2f}")

        except Exception as e:
            self.log(f"Error saving trade: {e}")

    def update_trade_status(self, trade: Trade, exit_price: float, status: str, reason: str):
        """Update trade status when closed"""
        trade.exit_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        trade.exit_price = exit_price
        trade.status = status
        trade.reason = reason

        # Calculate profit
        if trade.trade_type == "BUY":
            trade.profit = (exit_price - trade.entry_price) * trade.volume * 100000  # Approximate for forex
        else:
            trade.profit = (trade.entry_price - exit_price) * trade.volume * 100000

        self.save_trade(trade)

    def calculate_stop_loss_take_profit(self, symbol, price, order_type):
        """Calculate stop loss and take profit levels in price units"""
        try:
            if order_type == "BUY":
                stop_loss_distance = price * (self.config.stop_loss_pct / 100)
                take_profit_distance = price * (self.config.take_profit_pct / 100)
            else:
                stop_loss_distance = price * (self.config.stop_loss_pct / 100)
                take_profit_distance = price * (self.config.take_profit_pct / 100)

            min_distance = price * 0.0005
            stop_loss_distance = max(stop_loss_distance, min_distance)
            take_profit_distance = max(take_profit_distance, min_distance)

            return stop_loss_distance, take_profit_distance

        except Exception as e:
            self.log(f"Error calculating SL/TP: {e}")
            return price * 0.01, price * 0.02

    def check_position_management(self):
        """Check and manage existing positions according to the new logic"""
        try:
            open_positions = self.mt5_trader.get_open_positions()
            current_time = datetime.now()

            for position in open_positions:
                symbol = position.symbol

                # Initialize monitoring for new positions
                if symbol not in self.position_monitoring:
                    self.position_monitoring[symbol] = {
                        'position': position,
                        'entry_time': current_time,
                        'last_signal_check': current_time,
                        'monitoring_active': True
                    }
                    self.log(f"Started monitoring position for {symbol}")
                    continue

                monitoring_data = self.position_monitoring[symbol]

                # Check if 15 minutes have passed since last signal check
                time_since_last_check = (current_time - monitoring_data['last_signal_check']).total_seconds()

                if time_since_last_check >= 900:  # 15 minutes
                    self.log(f"15-minute check for {symbol}")
                    current_signal = self.get_current_signal(symbol)

                    # Get position type
                    position_type = "BUY" if position.type == mt5.ORDER_TYPE_BUY else "SELL"

                    # Check if we should close based on signal
                    if position_type == "BUY" and current_signal == "SELL":
                        self.log(f"Closing BUY position for {symbol} - Signal changed to SELL")
                        if self.mt5_trader.close_position(position, "SIGNAL_CHANGE"):
                            # Update trade record
                            trade = self.find_trade_by_position(position)
                            if trade:
                                tick = mt5.symbol_info_tick(symbol)
                                exit_price = tick.bid if tick else position.price_current
                                self.update_trade_status(trade, exit_price, "SIGNAL_CLOSE", "Signal changed to SELL")
                            del self.position_monitoring[symbol]

                    elif position_type == "SELL" and current_signal == "BUY":
                        self.log(f"Closing SELL position for {symbol} - Signal changed to BUY")
                        if self.mt5_trader.close_position(position, "SIGNAL_CHANGE"):
                            trade = self.find_trade_by_position(position)
                            if trade:
                                tick = mt5.symbol_info_tick(symbol)
                                exit_price = tick.ask if tick else position.price_current
                                self.update_trade_status(trade, exit_price, "SIGNAL_CLOSE", "Signal changed to BUY")
                            del self.position_monitoring[symbol]

                    # Update last check time
                    monitoring_data['last_signal_check'] = current_time

        except Exception as e:
            self.log(f"Error in position management: {e}")

    def find_trade_by_position(self, position):
        """Find trade record by position details"""
        try:
            for trade in self.trade_history:
                if (trade.symbol == position.symbol and
                        trade.status == "OPEN" and
                        abs(trade.entry_price - position.price_open) < 0.0001):
                    return trade
        except Exception as e:
            self.log(f"Error finding trade: {e}")
        return None

    def get_current_signal(self, symbol):
        """Get current trading signal for symbol"""
        try:
            exchange = "FX_IDC" if "USD" in symbol else "OANDA"
            df = self.tv.get_hist(symbol=symbol, exchange=exchange,
                                  interval=Interval.in_5_minute, n_bars=200)

            if df is None or df.empty:
                self.log(f"No data for {symbol}")
                return "NO_SIGNAL"

            signal = self.strategy.get_signal(df)

            if symbol in self.last_signals and self.last_signals[symbol] != signal:
                self.log(f"Signal changed for {symbol}: {self.last_signals[symbol]} -> {signal}")

            self.last_signals[symbol] = signal
            return signal

        except Exception as e:
            self.log(f"Error getting signal for {symbol}: {e}")
            return "NO_SIGNAL"

    def check_for_new_entries(self):
        """Check for new trade entries (only if no existing position for symbol)"""
        try:
            open_positions = self.mt5_trader.get_open_positions()
            occupied_symbols = {pos.symbol for pos in open_positions}

            for symbol in self.config.symbols:
                if symbol in occupied_symbols:
                    continue  # Skip symbols with open positions

                signal = self.get_current_signal(symbol)

                if signal == "BUY" and self.config.buy_mode:
                    self.execute_trade(symbol, "BUY")
                elif signal == "SELL" and self.config.sell_mode:
                    self.execute_trade(symbol, "SELL")

        except Exception as e:
            self.log(f"Error checking for new entries: {e}")

    def execute_trade(self, symbol, order_type):
        """Execute a trade"""
        try:
            # Get current price
            symbol_info = self.mt5_trader.get_symbol_info(symbol)
            if not symbol_info:
                self.log(f"Could not get symbol info for {symbol}")
                return

            tick = mt5.symbol_info_tick(symbol)
            if not tick:
                self.log(f"Could not get tick data for {symbol}")
                return

            current_price = tick.ask if order_type == "BUY" else tick.bid

            # Calculate position size and SL/TP
            stop_loss_distance, take_profit_distance = self.calculate_stop_loss_take_profit(
                symbol, current_price, order_type)

            # Calculate volume based on risk
            risk_amount = (self.config.stop_loss_pct / 100) * self.config.capital
            pip_distance = self.mt5_trader.calculate_pip_distance(symbol, stop_loss_distance)
            volume = self.mt5_trader.calculate_volume(symbol, risk_amount, pip_distance)

            self.log(f"Preparing {order_type} order for {symbol}: "
                     f"Price={current_price:.5f}, Volume={volume:.2f}, "
                     f"SL={stop_loss_distance:.5f}, TP={take_profit_distance:.5f}")

            # Place order
            result = self.mt5_trader.place_order(symbol, order_type, volume, stop_loss_distance, take_profit_distance)

            if result == "AUTOTRADING_DISABLED":
                if not self.autotrading_warning_shown:
                    self.log("❌ AUTOTRADING IS DISABLED IN MT5 - Please enable AutoTrading")
                    self.log("📍 In MT5: Click 'AutoTrading' button or go to Tools → Options → Trading")
                    self.autotrading_warning_shown = True
                return
            elif result:
                self.log(f"✅ Order executed: {order_type} {symbol} at {current_price:.5f}")

                # Create trade record
                trade = Trade(
                    symbol=symbol,
                    trade_type=order_type,
                    entry_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    entry_price=current_price,
                    volume=volume,
                    stop_loss=current_price - stop_loss_distance if order_type == "BUY" else current_price + stop_loss_distance,
                    take_profit=current_price + take_profit_distance if order_type == "BUY" else current_price - take_profit_distance
                )

                self.save_trade(trade)
            else:
                self.log(f"❌ Failed to execute {order_type} order for {symbol}")

        except Exception as e:
            self.log(f"Error executing trade for {symbol}: {e}")

    def start_trading(self):
        """Start the trading engine"""
        if not self.mt5_trader.connect(
                account=self.config.account if getattr(self.config, "account", None) else None,
                password=self.config.password if getattr(self.config, "password", "") else None,
                server=self.config.server if getattr(self.config, "server", "") else None
        ):
            self.log("Failed to connect to MT5")
            return False

        self.running = True
        self.log("Trading engine started - Single position mode active")
        return True

    def stop_trading(self):
        """Stop the trading engine"""
        self.running = False
        self.mt5_trader.disconnect()
        self.position_monitoring.clear()
        self.log("Trading engine stopped")

    def execute_trading_cycle(self):
        """Execute one trading cycle"""
        if not self.config.trading_active:
            return

        try:
            # 1. Check and manage existing positions (15-minute signal checks)
            self.check_position_management()

            # 2. Check for new trade entries (only if no existing position)
            self.check_for_new_entries()

        except Exception as e:
            self.log(f"Error in trading cycle: {e}")


# -----------------------
# GUI Application
# -----------------------
class TradingApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Range Filter MT5 Trading Bot - Single Position Mode")
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

        self.buy_check = ctk.CTkCheckBox(mode_frame, text="BUY Mode Only",
                                         variable=self.buy_var,
                                         command=self.on_mode_change)
        self.buy_check.pack(anchor="w", pady=2)

        self.sell_check = ctk.CTkCheckBox(mode_frame, text="SELL Mode Only",
                                          variable=self.sell_var,
                                          command=self.on_mode_change)
        self.sell_check.pack(anchor="w", pady=2)

        # Mode info label
        self.mode_info_label = ctk.CTkLabel(mode_frame,
                                            text="✓ Single position per symbol\n✓ 15-min signal checks",
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
        """Main trading loop - 1 minute cycles"""
        while self.trading_engine and self.trading_engine.running:
            try:
                self.trading_engine.execute_trading_cycle()
                time.sleep(60)  # 1 minute between cycles
            except Exception as e:
                self.log_message(f"Error in trading loop: {e}")
                time.sleep(30)

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
            self.log_message(f"Mode: {'BUY ONLY' if self.config.buy_mode else 'SELL ONLY'}")
            self.log_message(f"Capital: ${self.config.capital:.2f}")
            self.log_message(f"Stop Loss: {self.config.stop_loss_pct}%")
            self.log_message(f"Take Profit: {self.config.take_profit_pct}%")
            self.log_message(f"Symbols: {', '.join(self.config.symbols)}")
            self.log_message("=== IMPORTANT ===")
            self.log_message("📍 Make sure AutoTrading is ENABLED in MT5:")
            self.log_message("   - Click 'AutoTrading' button (should be GREEN)")
            self.log_message("   - Or: Tools → Options → Trading → Allow algorithmic trading")
            self.log_message("=== TRADING RULES ===")
            self.log_message("✓ Single position per symbol")
            self.log_message("✓ New trades only when no existing position")
            self.log_message("✓ 15-minute signal checks for open positions")
            self.log_message("✓ Position closed if signal reverses")
            self.log_message("✓ 1-minute cycle for new entry checks")

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


# -----------------------
# Application Entry Point
# -----------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s - %(levelname)s - %(message)s')

    app = TradingApp()

    try:
        app.mainloop()
    except KeyboardInterrupt:
        print("Application interrupted by user")
    finally:
        if app.trading_engine:
            app.trading_engine.stop_trading()