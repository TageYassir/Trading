import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, simpledialog
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
from typing import Optional, Dict, List, Tuple
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import urllib.parse
import re

# -----------------------
# Constants and Configuration
# -----------------------
CONFIG_FILE = "trading_config.json"
TRADES_FILE = "trades_history.csv"
USERS_FILE = "users_config.json"

# Set appearance
ctk.set_appearance_mode("Light")
ctk.set_default_color_theme("blue")


# -----------------------
# Utility Functions
# -----------------------
def save_json(file_path, data):
    try:
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=4)
        return True
    except Exception as e:
        logging.error(f"Error saving {file_path}: {e}")
        return False


def load_json(file_path):
    try:
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                return json.load(f)
    except Exception as e:
        logging.error(f"Error loading {file_path}: {e}")
    return {}


# -----------------------
# Email Notification System
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
    exit_time: str = ""
    exit_price: float = 0.0
    volume: float = 0.0
    profit: float = 0.0
    status: str = "OPEN"
    stop_loss: float = 0.0
    take_profit: float = 0.0
    reason: str = ""
    setup_type: str = ""


@dataclass
class FVGSetup:
    symbol: str
    direction: str  # "UP" or "DOWN"
    third_candle_time: datetime
    third_candle_high: float
    third_candle_low: float
    third_candle_body_high: float
    third_candle_body_low: float
    status: str = "PENDING_TAIL"  # PENDING_TAIL, READY_FOR_5M, ACTIVE_5M, EXPIRED, CONFIRMED
    detection_time: datetime = None
    tail_confirmation_time: datetime = None
    five_min_start_time: datetime = None

    def __post_init__(self):
        if self.detection_time is None:
            self.detection_time = datetime.now()


@dataclass
class OBSetup:
    symbol: str
    direction: str  # "UP" or "DOWN"
    ob_candle_time: datetime
    ob_candle_high: float
    ob_candle_low: float
    ob_candle_body_high: float
    ob_candle_body_low: float
    candles_since_ob: int = 0
    status: str = "PENDING_BREAK"  # PENDING_BREAK, READY_FOR_5M, ACTIVE_5M, EXPIRED, CONFIRMED
    detection_time: datetime = None
    break_confirmation_time: datetime = None
    five_min_start_time: datetime = None

    def __post_init__(self):
        if self.detection_time is None:
            self.detection_time = datetime.now()


@dataclass
class TradingConfig:
    name: str = "DefaultConfig"
    capital: float = 1000.0
    risk_per_trade: float = 0.5  # 0.5% as specified
    symbols: List[str] = None
    trading_active: bool = False  # Start in stopped state
    email_notifications: bool = True
    recipients: List[Dict] = None

    # MT5 credentials
    account: int = 0
    password: str = ""
    server: str = ""

    def __post_init__(self):
        if self.symbols is None:
            self.symbols = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"]
        if self.recipients is None:
            self.recipients = []


class AdvancedTradingStrategy:
    def __init__(self, tv_datafeed: TvDatafeed):
        self.tv = tv_datafeed

    def calculate_range_filter(self, df, period=100, mult=3.0):
        """Calculate Range Filter signals for 5-minute timeframe"""
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

    def get_5min_signal(self, symbol):
        """Get 5-minute range filter signal"""
        try:
            exchange = self.get_exchange(symbol)
            df = self.tv.get_hist(symbol=symbol, exchange=exchange,
                                  interval=Interval.in_5_minute, n_bars=200)

            if df is None or df.empty:
                return "NO_SIGNAL"

            df = self.calculate_range_filter(df)

            if df['longCond'].iloc[-1]:
                return "BUY"
            elif df['shortCond'].iloc[-1]:
                return "SELL"
            else:
                return "NO_SIGNAL"

        except Exception as e:
            logging.error(f"Error getting 5min signal for {symbol}: {e}")
            return "NO_SIGNAL"

    def get_4h_data(self, symbol, n_bars=100):
        """Get 4-hour data for FVG and OB detection"""
        try:
            exchange = self.get_exchange(symbol)
            df = self.tv.get_hist(symbol=symbol, exchange=exchange,
                                  interval=Interval.in_4_hour, n_bars=n_bars)
            return df
        except Exception as e:
            logging.error(f"Error getting 4h data for {symbol}: {e}")
            return None

    # EXACT FVG RULES IMPLEMENTATION
    def detect_fvg_setup(self, symbol):
        """Detect Fair Value Gap setups according to EXACT rules"""
        try:
            df = self.get_4h_data(symbol, n_bars=10)
            if df is None or len(df) < 6:
                return None

            candles = df.iloc[-6:]  # Last 6 candles

            # Check for FVG Down (Sell setup)
            fvg_down = self._detect_fvg_down(candles)
            if fvg_down:
                third_candle = candles.iloc[2]
                return FVGSetup(
                    symbol=symbol,
                    direction="DOWN",
                    third_candle_time=third_candle.name,
                    third_candle_high=third_candle['high'],
                    third_candle_low=third_candle['low'],
                    third_candle_body_high=max(third_candle['open'], third_candle['close']),
                    third_candle_body_low=min(third_candle['open'], third_candle['close'])
                )

            # Check for FVG Up (Buy setup)
            fvg_up = self._detect_fvg_up(candles)
            if fvg_up:
                third_candle = candles.iloc[2]
                return FVGSetup(
                    symbol=symbol,
                    direction="UP",
                    third_candle_time=third_candle.name,
                    third_candle_high=third_candle['high'],
                    third_candle_low=third_candle['low'],
                    third_candle_body_high=max(third_candle['open'], third_candle['close']),
                    third_candle_body_low=min(third_candle['open'], third_candle['close'])
                )

            return None

        except Exception as e:
            logging.error(f"Error detecting FVG setup for {symbol}: {e}")
            return None

    def _detect_fvg_down(self, candles):
        """EXACT FVG Down rules"""
        if len(candles) < 6:
            return False

        # Check if trending down (price moving down)
        if candles['close'].iloc[0] <= candles['close'].iloc[5]:
            return False

        second_candle = candles.iloc[1]
        third_candle = candles.iloc[2]

        # Third candle doesn't reach more than 1/2 of second candle's body
        second_body_size = abs(second_candle['close'] - second_candle['open'])
        third_retracement = abs(third_candle['close'] - min(second_candle['open'], second_candle['close']))

        if third_retracement > (second_body_size * 0.5):
            return False

        # Check 4th or 5th candle tail condition
        for i in [3, 4]:  # 4th and 5th candles
            if i < len(candles):
                candle = candles.iloc[i]
                current_tail_high = candle['high'] - max(candle['open'], candle['close'])
                third_tail_high = third_candle['high'] - max(third_candle['open'], third_candle['close'])

                # Tail should be higher than third candle's tail but body not above
                if (current_tail_high > third_tail_high and
                        max(candle['open'], candle['close']) <= third_candle['high']):
                    return True

        return False

    def _detect_fvg_up(self, candles):
        """EXACT FVG Up rules"""
        if len(candles) < 6:
            return False

        # Check if trending up (price moving up)
        if candles['close'].iloc[0] >= candles['close'].iloc[5]:
            return False

        second_candle = candles.iloc[1]
        third_candle = candles.iloc[2]

        # Third candle doesn't reach more than 1/2 of second candle's body
        second_body_size = abs(second_candle['close'] - second_candle['open'])
        third_retracement = abs(third_candle['close'] - max(second_candle['open'], second_candle['close']))

        if third_retracement > (second_body_size * 0.5):
            return False

        # Check 4th or 5th candle tail condition
        for i in [3, 4]:  # 4th and 5th candles
            if i < len(candles):
                candle = candles.iloc[i]
                current_tail_low = min(candle['open'], candle['close']) - candle['low']
                third_tail_low = min(third_candle['open'], third_candle['close']) - third_candle['low']

                # Tail should be lower than third candle's tail but body not below
                if (current_tail_low > third_tail_low and
                        min(candle['open'], candle['close']) >= third_candle['low']):
                    return True

        return False

    # EXACT ORDER BLOCK RULES IMPLEMENTATION
    def detect_ob_setup(self, symbol):
        """Detect Order Block setups according to EXACT rules"""
        try:
            df = self.get_4h_data(symbol, n_bars=100)
            if df is None or len(df) < 25:
                return None

            # Look for order blocks in recent 25 candles
            ob_up = self._find_ob_up(df.tail(25))
            if ob_up:
                return OBSetup(
                    symbol=symbol,
                    direction="UP",
                    ob_candle_time=ob_up.name,
                    ob_candle_high=ob_up['high'],
                    ob_candle_low=ob_up['low'],
                    ob_candle_body_high=max(ob_up['open'], ob_up['close']),
                    ob_candle_body_low=min(ob_up['open'], ob_up['close'])
                )

            ob_down = self._find_ob_down(df.tail(25))
            if ob_down:
                return OBSetup(
                    symbol=symbol,
                    direction="DOWN",
                    ob_candle_time=ob_down.name,
                    ob_candle_high=ob_down['high'],
                    ob_candle_low=ob_down['low'],
                    ob_candle_body_high=max(ob_down['open'], ob_down['close']),
                    ob_candle_body_low=min(ob_down['open'], ob_down['close'])
                )

            return None

        except Exception as e:
            logging.error(f"Error detecting OB setup for {symbol}: {e}")
            return None

    def _find_ob_up(self, df):
        """EXACT Order Block Up rules - 65% green, 35% red, starts with red, ends with green"""
        for i in range(10, len(df)):
            window = df.iloc[i - 10:i + 1]  # 11-candle window

            # Count red and green candles
            green_candles = len(window[window['close'] > window['open']])
            red_candles = len(window[window['close'] < window['open']])
            total_candles = len(window)

            # Check percentages: max 35% red, min 65% green
            if red_candles / total_candles > 0.35:
                continue
            if green_candles / total_candles < 0.65:
                continue

            # Check start with red and end with green
            first_candle = window.iloc[0]
            last_candle = window.iloc[-1]

            if (first_candle['close'] < first_candle['open'] and  # Starts with red
                    last_candle['close'] > last_candle['open']):  # Ends with green
                return last_candle

        return None

    def _find_ob_down(self, df):
        """EXACT Order Block Down rules - 65% red, 35% green, starts with green, ends with red"""
        for i in range(10, len(df)):
            window = df.iloc[i - 10:i + 1]  # 11-candle window

            # Count red and green candles
            green_candles = len(window[window['close'] > window['open']])
            red_candles = len(window[window['close'] < window['open']])
            total_candles = len(window)

            # Check percentages: max 35% green, min 65% red
            if green_candles / total_candles > 0.35:
                continue
            if red_candles / total_candles < 0.65:
                continue

            # Check start with green and end with red
            first_candle = window.iloc[0]
            last_candle = window.iloc[-1]

            if (first_candle['close'] > first_candle['open'] and  # Starts with green
                    last_candle['close'] < last_candle['open']):  # Ends with red
                return last_candle

        return None

    def check_ob_break_condition(self, ob_setup: OBSetup):
        """Check if OB break condition is met (tail-only break)"""
        try:
            df = self.get_4h_data(ob_setup.symbol, n_bars=ob_setup.candles_since_ob + 5)
            if df is None:
                return False

            # Get candles after OB detection
            recent_candles = df.tail(ob_setup.candles_since_ob + 1)

            for i in range(len(recent_candles)):
                candle = recent_candles.iloc[i]

                if ob_setup.direction == "UP":
                    # For OB Up: wait for tail-only dip below OB candle's upper tail
                    # Ignore if both body and tail go below
                    if (candle['low'] < ob_setup.ob_candle_low and
                            candle['close'] >= ob_setup.ob_candle_body_low):  # Only tail dips below
                        return True

                else:  # DOWN
                    # For OB Down: wait for tail-only rise above OB candle's upper tail
                    # Ignore if both body and tail go above
                    if (candle['high'] > ob_setup.ob_candle_high and
                            candle['close'] <= ob_setup.ob_candle_body_high):  # Only tail rises above
                        return True

            return False

        except Exception as e:
            logging.error(f"Error checking OB break condition: {e}")
            return False

    def get_exchange(self, symbol):
        """Get exchange for symbol"""
        if "XAU" in symbol:
            return "TVC"
        return "FX_IDC" if "USD" in symbol else "OANDA"


# -----------------------
# Trading Engine with EXACT Rules Implementation
# -----------------------
class AdvancedTradeWorker:
    def __init__(self, config: TradingConfig, email_sender: EmailSender, log_callback):
        self.config = config
        self.email_sender = email_sender
        self.log_callback = log_callback
        self.strategy = AdvancedTradingStrategy(TvDatafeed())
        self.mt5_trader = MT5Trader()

        # Start in stopped state
        self.running = False
        self.hold_messages = False

        # Setup tracking
        self.active_fvg_setups = {}
        self.active_ob_setups = {}
        self.open_trades = {}
        self.trade_history = []

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
                'reason': trade.reason,
                'setup_type': trade.setup_type
            }

            df = pd.DataFrame([trade_dict])
            if not os.path.exists(TRADES_FILE):
                df.to_csv(TRADES_FILE, index=False)
            else:
                df.to_csv(TRADES_FILE, mode='a', header=False, index=False)

            self.trade_history.append(trade)
            self.log(f"Trade saved: {trade.symbol} {trade.trade_type}")

        except Exception as e:
            self.log(f"Error saving trade: {e}")

    def send_email_alert(self, subject: str, message: str):
        """Send email alert to all recipients"""
        if self.hold_messages or not self.config.email_notifications:
            return

        for recipient in self.config.recipients:
            try:
                self.email_sender.send_email(
                    recipient['email'],
                    subject,
                    message
                )
            except Exception as e:
                self.log(f"Error sending email to {recipient['email']}: {e}")

    def calculate_stop_loss_take_profit(self, symbol, price, order_type):
        """EXACT Stop Loss and Take Profit rules"""
        try:
            # Get 30-minute data for SL calculation
            exchange = self.strategy.get_exchange(symbol)
            df_30min = self.strategy.tv.get_hist(symbol=symbol, exchange=exchange,
                                                 interval=Interval.in_30_minute, n_bars=20)

            if df_30min is None or df_30min.empty:
                # Fallback to percentage-based
                sl_distance = price * (self.config.risk_per_trade / 100)
                tp_distance = 2 * sl_distance
                return sl_distance, tp_distance

            if order_type == "BUY":
                # SL = lowest low in last 30 minutes
                stop_loss_price = df_30min['low'].min()
                sl_distance = price - stop_loss_price
            else:
                # SL = highest high in last 30 minutes
                stop_loss_price = df_30min['high'].max()
                sl_distance = stop_loss_price - price

            # TP = 2 × SL (double the SL distance)
            tp_distance = 2 * sl_distance

            # Ensure minimum distance
            min_distance = price * 0.0001
            sl_distance = max(sl_distance, min_distance)
            tp_distance = max(tp_distance, min_distance * 2)

            return sl_distance, tp_distance

        except Exception as e:
            self.log(f"Error calculating SL/TP: {e}")
            # Fallback to percentage
            sl_distance = price * (self.config.risk_per_trade / 100)
            tp_distance = 2 * sl_distance
            return sl_distance, tp_distance

    def calculate_position_size(self, symbol, stop_loss_distance):
        """Calculate position size based on 0.5% risk"""
        risk_amount = (self.config.risk_per_trade / 100) * self.config.capital
        pip_distance = self.mt5_trader.calculate_pip_distance(symbol, stop_loss_distance)
        volume = self.mt5_trader.calculate_volume(symbol, risk_amount, pip_distance)
        return volume

    def execute_trade(self, symbol, order_type, setup_type):
        """Execute trade with EXACT rules"""
        try:
            # Get current price
            tick = mt5.symbol_info_tick(symbol)
            if not tick:
                self.log(f"Could not get tick data for {symbol}")
                return

            current_price = tick.ask if order_type == "BUY" else tick.bid

            # Calculate SL/TP using EXACT rules
            stop_loss_distance, take_profit_distance = self.calculate_stop_loss_take_profit(
                symbol, current_price, order_type)

            # Calculate position size
            volume = self.calculate_position_size(symbol, stop_loss_distance)

            self.log(f"Executing {order_type} for {symbol} ({setup_type}): "
                     f"Price={current_price:.5f}, SL Dist={stop_loss_distance:.5f}, TP Dist={take_profit_distance:.5f}")

            # Send email alert
            self.send_email_alert(
                f"Trade Alert - {symbol} {order_type}",
                f"Config: {self.config.name}\n"
                f"Signal: {order_type}\n"
                f"Symbol: {symbol}\n"
                f"Setup: {setup_type}\n"
                f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )

            # Place order
            result = self.mt5_trader.place_order(symbol, order_type, volume, stop_loss_distance, take_profit_distance)

            if result:
                self.log(f"✅ Trade executed: {order_type} {symbol}")

                # Create trade record
                trade = Trade(
                    symbol=symbol,
                    trade_type=order_type,
                    entry_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    entry_price=current_price,
                    volume=volume,
                    stop_loss=current_price - stop_loss_distance if order_type == "BUY" else current_price + stop_loss_distance,
                    take_profit=current_price + take_profit_distance if order_type == "BUY" else current_price - take_profit_distance,
                    setup_type=setup_type
                )

                self.save_trade(trade)

                # Send execution email
                self.send_email_alert(
                    f"Trade Executed - {symbol} {order_type}",
                    f"TRADE EXECUTED:\n"
                    f"Config: {self.config.name}\n"
                    f"Symbol: {symbol}\n"
                    f"Type: {order_type}\n"
                    f"Setup: {setup_type}\n"
                    f"Entry Price: {current_price:.5f}\n"
                    f"Volume: {volume:.2f}\n"
                    f"Stop Loss: {trade.stop_loss:.5f}\n"
                    f"Take Profit: {trade.take_profit:.5f}\n"
                    f"Time: {trade.entry_time}"
                )
            else:
                self.log(f"❌ Failed to execute {order_type} for {symbol}")

        except Exception as e:
            self.log(f"Error executing trade for {symbol}: {e}")

    def scan_fvg_setups(self):
        """Scan for new FVG setups"""
        for symbol in self.config.symbols:
            try:
                clean_symbol = symbol.split(":")[1] if ":" in symbol else symbol

                # Skip if already monitoring
                if clean_symbol in self.active_fvg_setups:
                    continue

                fvg_setup = self.strategy.detect_fvg_setup(clean_symbol)
                if fvg_setup:
                    self.active_fvg_setups[clean_symbol] = fvg_setup
                    self.log(f"🎯 FVG {fvg_setup.direction} setup detected for {clean_symbol}")
                    self.send_email_alert(
                        f"FVG Setup Detected - {clean_symbol}",
                        f"FVG {fvg_setup.direction} setup detected for {clean_symbol}\n"
                        f"Waiting for tail confirmation..."
                    )
            except Exception as e:
                self.log(f"Error scanning FVG for {symbol}: {e}")

    def monitor_fvg_setups(self):
        """Monitor FVG setups according to EXACT rules"""
        current_time = datetime.now()
        expired_setups = []

        for symbol, setup in list(self.active_fvg_setups.items()):
            try:
                if setup.status == "PENDING_TAIL":
                    # Already detected during setup detection, move to 5M monitoring
                    setup.status = "READY_FOR_5M"
                    setup.tail_confirmation_time = current_time
                    self.log(f"✅ FVG {setup.direction} tail confirmed for {symbol}, starting 5M monitoring")

                elif setup.status in ["READY_FOR_5M", "ACTIVE_5M"]:
                    # Check if we need to start 5M monitoring
                    if setup.status == "READY_FOR_5M":
                        setup.status = "ACTIVE_5M"
                        setup.five_min_start_time = current_time
                        self.log(f"🔍 Starting 5M monitoring for FVG {setup.direction} on {symbol}")

                    # Check 5-minute signal
                    signal = self.strategy.get_5min_signal(symbol)
                    target_signal = "SELL" if setup.direction == "DOWN" else "BUY"

                    if signal == target_signal:
                        self.log(f"✅ FVG {setup.direction} confirmed by 5M signal for {symbol}")
                        self.execute_trade(symbol, target_signal, f"FVG_{setup.direction}")
                        expired_setups.append(symbol)

                    else:
                        # Check if 4 hours have passed
                        if (current_time - setup.five_min_start_time).total_seconds() >= 4 * 3600:
                            self.log(f"⏰ FVG {setup.direction} setup expired for {symbol} (4 hours)")
                            expired_setups.append(symbol)

            except Exception as e:
                self.log(f"Error monitoring FVG setup for {symbol}: {e}")

        # Clean up expired setups
        for symbol in expired_setups:
            if symbol in self.active_fvg_setups:
                del self.active_fvg_setups[symbol]

    def scan_ob_setups(self):
        """Scan for new Order Block setups"""
        for symbol in self.config.symbols:
            try:
                clean_symbol = symbol.split(":")[1] if ":" in symbol else symbol

                # Skip if already monitoring
                if clean_symbol in self.active_ob_setups:
                    continue

                ob_setup = self.strategy.detect_ob_setup(clean_symbol)
                if ob_setup:
                    self.active_ob_setups[clean_symbol] = ob_setup
                    self.log(f"🎯 OB {ob_setup.direction} setup detected for {clean_symbol}")
                    self.send_email_alert(
                        f"OB Setup Detected - {clean_symbol}",
                        f"OB {ob_setup.direction} setup detected for {clean_symbol}\n"
                        f"Monitoring for break condition..."
                    )
            except Exception as e:
                self.log(f"Error scanning OB for {symbol}: {e}")

    def monitor_ob_setups(self):
        """Monitor OB setups according to EXACT rules"""
        current_time = datetime.now()
        expired_setups = []

        for symbol, setup in list(self.active_ob_setups.items()):
            try:
                setup.candles_since_ob += 1

                # Check 25 candle limit
                if setup.candles_since_ob > 25:
                    self.log(f"⏰ OB {setup.direction} setup expired for {symbol} (25 candles)")
                    expired_setups.append(symbol)
                    continue

                if setup.status == "PENDING_BREAK":
                    # Check for tail-only break condition
                    if self.strategy.check_ob_break_condition(setup):
                        setup.status = "READY_FOR_5M"
                        setup.break_confirmation_time = current_time
                        self.log(f"✅ OB {setup.direction} break confirmed for {symbol}, starting 5M monitoring")

                elif setup.status in ["READY_FOR_5M", "ACTIVE_5M"]:
                    # Start 5M monitoring
                    if setup.status == "READY_FOR_5M":
                        setup.status = "ACTIVE_5M"
                        setup.five_min_start_time = current_time
                        self.log(f"🔍 Starting 5M monitoring for OB {setup.direction} on {symbol}")

                    # Check 5-minute signal
                    signal = self.strategy.get_5min_signal(symbol)
                    target_signal = "SELL" if setup.direction == "DOWN" else "BUY"

                    if signal == target_signal:
                        self.log(f"✅ OB {setup.direction} confirmed by 5M signal for {symbol}")
                        self.execute_trade(symbol, target_signal, f"OB_{setup.direction}")
                        expired_setups.append(symbol)

                    else:
                        # Check if 4 hours have passed
                        if (current_time - setup.five_min_start_time).total_seconds() >= 4 * 3600:
                            self.log(f"⏰ OB {setup.direction} setup expired for {symbol} (4 hours)")
                            expired_setups.append(symbol)

            except Exception as e:
                self.log(f"Error monitoring OB setup for {symbol}: {e}")

        # Clean up expired setups
        for symbol in expired_setups:
            if symbol in self.active_ob_setups:
                del self.active_ob_setups[symbol]

    def run_strategy_cycle(self):
        """Run one complete strategy cycle"""
        if not self.running:
            return

        try:
            # 1. Scan for new setups
            self.scan_fvg_setups()
            self.scan_ob_setups()

            # 2. Monitor active setups
            self.monitor_fvg_setups()
            self.monitor_ob_setups()

        except Exception as e:
            self.log(f"Error in strategy cycle: {e}")

    def start_trading(self):
        """Start trading (change from stopped state)"""
        if not self.mt5_trader.connect():
            self.log("Failed to connect to MT5")
            return False

        self.running = True
        self.config.trading_active = True
        self.log(f"✅ Trading STARTED for config: {self.config.name}")
        return True

    def stop_trading(self):
        """Stop trading"""
        self.running = False
        self.config.trading_active = False
        self.mt5_trader.disconnect()
        self.log(f"⏸ Trading STOPPED for config: {self.config.name}")

    def start(self):
        """Start the worker"""
        self.running = True
        self.hold_messages = False
        self.log(f"▶️ Config {self.config.name} started")

    def stop(self):
        """Stop the worker"""
        self.running = False
        self.hold_messages = True
        self.log(f"⏸ Config {self.config.name} stopped, messages on hold")

    def unhold(self):
        """Release message hold"""
        self.hold_messages = False
        self.log(f"🔓 Messages released for {self.config.name}")

    def refresh_new_users(self):
        """Refresh for new recipients"""
        # Implementation for new user refresh
        pass


# -----------------------
# MT5 Trader
# -----------------------
class MT5Trader:
    def __init__(self):
        self.connected = False
        self.account_info = None

    def connect(self, account: Optional[int] = None, password: Optional[str] = None,
                server: Optional[str] = None) -> bool:
        try:
            if account and password and server:
                ok = mt5.initialize(login=int(account), password=str(password), server=str(server))
            else:
                ok = mt5.initialize()

            if not ok:
                logging.error(f"MT5 initialization failed: {mt5.last_error()}")
                return False

            self.connected = True
            self.account_info = mt5.account_info()
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
                # Simplified calculation
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
                "comment": "AdvancedBot",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_FOK,
            }

            result = mt5.order_send(request)
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                logging.error(f"Order failed: {result.retcode}")
                return False

            logging.info(f"Order placed successfully: {order_type} {symbol}")
            return True

        except Exception as e:
            logging.error(f"Error placing order: {e}")
            return False


# -----------------------
# GUI Application
# -----------------------
class AdvancedTradingApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Advanced MT5 Trading Bot - EXACT RULES")
        self.geometry("1400x900")

        # Load configurations
        self.configs = load_json(CONFIG_FILE)
        self.users = load_json(USERS_FILE)
        self.workers = {}

        # Initialize current_config with default values
        self.current_config = TradingConfig()

        # If there are saved configs, use the first one as current
        if self.configs:
            first_config_name = list(self.configs.keys())[0]
            self.current_config = TradingConfig(**self.configs[first_config_name])

        # Initialize email sender
        self.email_sender = EmailSender(
            smtp_server="smtp.gmail.com",
            smtp_port=587,
            email="fftt7252@gmail.com",
            password="soaewjwyyvdziwwc"
        )

        self.init_ui()
        self.start_existing_configs_stopped()

    def init_ui(self):
        """Initialize the user interface"""
        main_frame = ctk.CTkFrame(self)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Left panel - Controls
        control_frame = ctk.CTkFrame(main_frame, width=400)
        control_frame.pack(side="left", fill="y", padx=(0, 10))
        control_frame.pack_propagate(False)

        # Right panel - Logs and Info
        info_frame = ctk.CTkFrame(main_frame)
        info_frame.pack(side="right", fill="both", expand=True)

        self.setup_control_panel(control_frame)
        self.setup_info_panel(info_frame)

    def setup_control_panel(self, parent):
        """Setup scrollable control panel"""
        # Create main scrollable frame for configuration sections
        main_scrollable = ctk.CTkScrollableFrame(parent, width=400)
        main_scrollable.pack(fill="both", expand=True)

        # Title
        title_label = ctk.CTkLabel(main_scrollable, text="Advanced Trading Bot",
                                   font=ctk.CTkFont(size=16, weight="bold"))
        title_label.pack(pady=15)

        # Strategy Info
        strategy_info = """
    🤖 EXACT TRADING RULES:

    🔹 STOP LOSS:
    • BUY: Lowest 30min low
    • SELL: Highest 30min high
    • Risk: 0.5% of capital

    🔹 TAKE PROFIT:
    • 2× Stop Loss distance
    • 1% of capital

    🔹 FAIR VALUE GAP (FVG):
    • 4H setup + 5M confirmation
    • 4-hour monitoring window
    • Tail-only break conditions

    🔹 ORDER BLOCK (OB):
    • 65%/35% candle ratio
    • 25-candle monitoring limit
    • Tail-only break conditions
            """
        info_label = ctk.CTkLabel(main_scrollable, text=strategy_info, justify="left")
        info_label.pack(pady=10)

        # ========== USER MANAGEMENT SECTION ==========
        user_frame = ctk.CTkFrame(main_scrollable)
        user_frame.pack(fill="x", padx=10, pady=5)

        ctk.CTkLabel(user_frame, text="Users Management",
                     font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(5, 10))

        # User listbox
        user_list_frame = ctk.CTkFrame(user_frame)
        user_list_frame.pack(fill="x", pady=5)

        ctk.CTkLabel(user_list_frame, text="Users:").pack(anchor="w")
        self.user_listbox = tk.Listbox(user_list_frame, selectmode="multiple",
                                       height=4, bg="#2b2b2b", fg="white")
        self.user_listbox.pack(fill="x", pady=5)

        # User buttons
        user_btn_frame = ctk.CTkFrame(user_frame)
        user_btn_frame.pack(fill="x", pady=5)

        ctk.CTkButton(user_btn_frame, text="Add User",
                      command=self.add_user, width=120).pack(side="left", padx=2)
        ctk.CTkButton(user_btn_frame, text="Delete User",
                      command=self.delete_user, width=120,
                      fg_color="#D35B58", hover_color="#C77B78").pack(side="left", padx=2)

        # Refresh users
        self.refresh_users()

        # ========== SYMBOLS CONFIGURATION ==========
        symbols_frame = ctk.CTkFrame(main_scrollable)
        symbols_frame.pack(fill="x", padx=10, pady=5)

        ctk.CTkLabel(symbols_frame, text="Trading Symbols",
                     font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(5, 0))

        ctk.CTkLabel(symbols_frame,
                     text="Enter TradingView URLs or EXCHANGE:SYMBOL (comma separated):").pack(anchor="w")

        self.symbols_entry = ctk.CTkEntry(symbols_frame,
                                          placeholder_text="FX_IDC:EURUSD, TVC:XAUUSD, or TradingView URLs")
        self.symbols_entry.pack(fill="x", pady=5)

        # ========== EMAIL CONFIGURATION ==========
        email_frame = ctk.CTkFrame(main_scrollable)
        email_frame.pack(fill="x", padx=10, pady=5)

        ctk.CTkLabel(email_frame, text="Email Configuration",
                     font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(5, 0))

        # SMTP Server
        smtp_frame = ctk.CTkFrame(email_frame)
        smtp_frame.pack(fill="x", pady=3)

        ctk.CTkLabel(smtp_frame, text="SMTP Server:").pack(side="left")
        self.smtp_server_entry = ctk.CTkEntry(smtp_frame, width=200,
                                              placeholder_text="smtp.gmail.com")
        self.smtp_server_entry.insert(0, "smtp.gmail.com")
        self.smtp_server_entry.pack(side="right", fill="x", padx=(10, 0))

        # SMTP Port
        port_frame = ctk.CTkFrame(email_frame)
        port_frame.pack(fill="x", pady=3)

        ctk.CTkLabel(port_frame, text="SMTP Port:").pack(side="left")
        self.smtp_port_entry = ctk.CTkEntry(port_frame, width=200, placeholder_text="587")
        self.smtp_port_entry.insert(0, "587")
        self.smtp_port_entry.pack(side="right", fill="x", padx=(10, 0))

        # Email
        email_acc_frame = ctk.CTkFrame(email_frame)
        email_acc_frame.pack(fill="x", pady=3)

        ctk.CTkLabel(email_acc_frame, text="Email:").pack(side="left")
        self.email_entry = ctk.CTkEntry(email_acc_frame, width=200,
                                        placeholder_text="your.email@gmail.com")
        self.email_entry.insert(0, "fftt7252@gmail.com")
        self.email_entry.pack(side="right", fill="x", padx=(10, 0))

        # Password
        password_frame = ctk.CTkFrame(email_frame)
        password_frame.pack(fill="x", pady=3)

        ctk.CTkLabel(password_frame, text="Password:").pack(side="left")
        self.password_entry = ctk.CTkEntry(password_frame, width=200, show="*",
                                           placeholder_text="App password")
        self.password_entry.insert(0, "soaewjwyyvdziwwc")
        self.password_entry.pack(side="right", fill="x", padx=(10, 0))

        # Email toggle
        self.email_var = ctk.BooleanVar(value=True)
        email_check = ctk.CTkCheckBox(email_frame, text="Enable Email Notifications",
                                      variable=self.email_var)
        email_check.pack(anchor="w", pady=5)

        # ========== TRADING CAPITAL ==========
        capital_frame = ctk.CTkFrame(main_scrollable)
        capital_frame.pack(fill="x", padx=10, pady=5)

        ctk.CTkLabel(capital_frame, text="Trading Capital ($):").pack(anchor="w")
        self.capital_entry = ctk.CTkEntry(capital_frame)
        capital_value = getattr(self, 'current_config', TradingConfig()).capital
        self.capital_entry.insert(0, str(capital_value))
        self.capital_entry.pack(fill="x", pady=5)

        # ========== ACTIVE SETUPS DISPLAY ==========
        setups_frame = ctk.CTkFrame(main_scrollable)
        setups_frame.pack(fill="x", padx=10, pady=5)

        ctk.CTkLabel(setups_frame, text="Active Setups:",
                     font=ctk.CTkFont(weight="bold")).pack(anchor="w")

        self.setups_text = ctk.CTkTextbox(setups_frame, height=150)
        self.setups_text.pack(fill="x", pady=5)
        self.setups_text.insert("1.0", "No active setups")
        self.setups_text.configure(state="disabled")

        # ========== STATUS AND CONTROL BUTTONS ==========
        # Status and Control buttons (fixed at bottom of main panel, not scrollable)
        self.status_label = ctk.CTkLabel(parent, text="🔴 SYSTEM STOPPED",
                                         text_color="red", font=ctk.CTkFont(size=14, weight="bold"))
        self.status_label.pack(pady=10)

        # Control buttons
        button_frame = ctk.CTkFrame(parent)
        button_frame.pack(fill="x", padx=10, pady=10)

        self.start_btn = ctk.CTkButton(button_frame, text="START TRADING",
                                       command=self.start_all_trading,
                                       fg_color="#2E8B57", hover_color="#3CB371")
        self.start_btn.pack(fill="x", pady=5)

        self.stop_btn = ctk.CTkButton(button_frame, text="STOP TRADING",
                                      command=self.stop_all_trading,
                                      fg_color="#DC143C", hover_color="#FF6347")
        self.stop_btn.pack(fill="x", pady=5)

    # ========== USER MANAGEMENT METHODS ==========
    def refresh_users(self):
        """Refresh users listbox"""
        self.user_listbox.delete(0, tk.END)
        for user_data in self.users.values():
            self.user_listbox.insert(tk.END, f"{user_data['name']} ({user_data['email']})")

    def add_user(self):
        """Add new user"""
        from tkinter import simpledialog

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

            # Remove from all configurations
            for cfg in self.configs.values():
                cfg['recipients'] = [u for u in cfg['recipients'] if u['email'] != email]

        save_json(USERS_FILE, self.users)
        save_json(CONFIG_FILE, self.configs)
        self.refresh_users()

    def parse_tv_link(self, link: str):
        """Parse TradingView link or symbol"""
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

    def setup_info_panel(self, parent):
        """Setup information panel"""
        log_frame = ctk.CTkFrame(parent)
        log_frame.pack(fill="both", expand=True, padx=10, pady=10)

        ctk.CTkLabel(log_frame, text="Trading Log",
                     font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=5)

        self.log_text = scrolledtext.ScrolledText(log_frame, height=25,
                                                  bg="black", fg="white",
                                                  font=("Consolas", 10))
        self.log_text.pack(fill="both", expand=True, pady=5)
        self.log_text.config(state="disabled")

    def log_message(self, message):
        """Add message to log"""
        self.log_text.config(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def update_setups_display(self):
        """Update active setups display"""
        try:
            self.setups_text.configure(state="normal")
            self.setups_text.delete("1.0", "end")

            all_setups = []

            for worker_name, worker in self.workers.items():
                if hasattr(worker, 'active_fvg_setups'):
                    for symbol, setup in worker.active_fvg_setups.items():
                        all_setups.append(f"FVG {setup.direction} - {symbol} ({setup.status})")

                if hasattr(worker, 'active_ob_setups'):
                    for symbol, setup in worker.active_ob_setups.items():
                        all_setups.append(
                            f"OB {setup.direction} - {symbol} ({setup.candles_since_ob}/25) - {setup.status}")

            if not all_setups:
                self.setups_text.insert("1.0", "No active setups")
            else:
                self.setups_text.insert("1.0", "\n".join(all_setups))

            self.setups_text.configure(state="disabled")
        except Exception as e:
            print(f"Error updating setups display: {e}")

    def start_all_trading(self):
        """Start all trading workers"""
        for worker_name, worker in self.workers.items():
            if worker.start_trading():
                self.log_message(f"✅ STARTED: {worker_name}")

        self.status_label.configure(text="🟢 SYSTEM RUNNING", text_color="green")
        self.log_message("=== TRADING SYSTEM STARTED ===")

    def stop_all_trading(self):
        """Stop all trading workers"""
        for worker_name, worker in self.workers.items():
            worker.stop_trading()
            self.log_message(f"⏸ STOPPED: {worker_name}")

        self.status_label.configure(text="🔴 SYSTEM STOPPED", text_color="red")
        self.log_message("=== TRADING SYSTEM STOPPED ===")

    def worker_loop(self, config_name):
        """Worker execution loop"""
        worker = self.workers[config_name]
        while True:
            try:
                worker.run_strategy_cycle()
                self.update_setups_display()
                time.sleep(60)  # 1 minute between cycles
            except Exception as e:
                self.log_message(f"Error in worker {config_name}: {e}")
                time.sleep(30)

    def start_existing_configs_stopped(self):
        """Start existing configurations in STOPPED state"""
        for config_name, config_data in self.configs.items():
            try:
                # Convert dict to TradingConfig object
                config_obj = TradingConfig(**config_data)
                # Ensure it starts stopped
                config_obj.trading_active = False

                worker = AdvancedTradeWorker(config_obj, self.email_sender, self.log_message)
                self.workers[config_name] = worker

                # Start worker thread but it won't trade until explicitly started
                threading.Thread(target=self.worker_loop, args=(config_name,), daemon=True).start()

            except Exception as e:
                self.log_message(f"Error starting config {config_name}: {e}")

        self.log_message("=== SYSTEM INITIALIZED ===")
        self.log_message("🔴 All configurations started in STOPPED state")
        self.log_message("Click 'START TRADING' to begin")

    def on_closing(self):
        """Handle application closing"""
        self.stop_all_trading()
        self.destroy()

    def start_all_trading(self):
        """Start all trading workers"""
        for worker_name, worker in self.workers.items():
            if worker.start_trading():
                self.log_message(f"✅ STARTED: {worker_name}")

        self.status_label.configure(text="🟢 SYSTEM RUNNING", text_color="green")
        self.log_message("=== TRADING SYSTEM STARTED ===")

    def stop_all_trading(self):
        """Stop all trading workers"""
        for worker_name, worker in self.workers.items():
            worker.stop_trading()
            self.log_message(f"⏸ STOPPED: {worker_name}")

        self.status_label.configure(text="🔴 SYSTEM STOPPED", text_color="red")
        self.log_message("=== TRADING SYSTEM STOPPED ===")


# -----------------------
# Application Entry Point
# -----------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s - %(levelname)s - %(message)s')

    app = AdvancedTradingApp()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)

    try:
        app.mainloop()
    except KeyboardInterrupt:
        print("Application interrupted by user")
    finally:
        app.stop_all_trading()