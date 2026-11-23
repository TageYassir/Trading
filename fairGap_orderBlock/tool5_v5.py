import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
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
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import urllib.parse
import re
from tkinter import simpledialog
from collections import defaultdict
from datetime import datetime, timedelta

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
                content = f.read().strip()
                if not content:  # Handle empty files
                    return {}
                data = json.loads(content)

                # Clean up any invalid fields for TradingConfig
                if file_path == CONFIG_FILE:
                    for config_name, config_data in data.items():
                        # Remove any fields that don't belong in TradingConfig
                        valid_fields = {'name', 'symbols', 'recipients', 'capital', 'risk_per_trade',
                                        'trading_active', 'email_notifications', 'account', 'password', 'server'}
                        keys_to_remove = []
                        for key in config_data.keys():
                            if key not in valid_fields:
                                keys_to_remove.append(key)
                        for key in keys_to_remove:
                            del config_data[key]

                return data
    except Exception as e:
        logging.error(f"Error loading {file_path}: {e}")
        # Return empty dict instead of None to avoid further errors
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


class RateLimitedTvDatafeed:
    def __init__(self, tv_datafeed, max_requests_per_minute=20):  # Reduced to be safer
        self.tv = tv_datafeed
        self.max_requests = max_requests_per_minute
        self.requests = []
        self.data_cache = {}
        self.cache_duration = timedelta(minutes=5)  # Cache data for 5 minutes

    def get_hist(self, symbol, exchange, interval, n_bars):
        # Create cache key
        cache_key = f"{symbol}_{exchange}_{interval}_{n_bars}"

        # Check cache first
        if cache_key in self.data_cache:
            cached_data, timestamp = self.data_cache[cache_key]
            if datetime.now() - timestamp < self.cache_duration:
                return cached_data

        # Rate limiting
        self._wait_if_needed()

        try:
            data = self.tv.get_hist(symbol=symbol, exchange=exchange, interval=interval, n_bars=n_bars)
            # Cache the data
            self.data_cache[cache_key] = (data, datetime.now())
            self.requests.append(datetime.now())
            return data
        except Exception as e:
            logging.error(f"Error fetching data for {symbol}: {e}")
            return None

    def _wait_if_needed(self):
        """Wait if we've made too many requests recently"""
        now = datetime.now()
        one_min_ago = now - timedelta(minutes=1)

        # Remove requests older than 1 minute
        self.requests = [req for req in self.requests if req > one_min_ago]

        # If we've hit the limit, wait
        if len(self.requests) >= self.max_requests:
            sleep_time = 60 - (now - self.requests[0]).total_seconds()
            if sleep_time > 0:
                time.sleep(sleep_time + 1)  # Add 1 second buffer
            # Remove the oldest request after waiting
            if self.requests:
                self.requests.pop(0)


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
    status: str = "PENDING_TAIL"  # PENDING_TAIL, READY_FOR_5M, ACTIVE_5M, EXPIRED, CONFIRMED, STRUCTURE_BREAKING
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
        self.tv = RateLimitedTvDatafeed(tv_datafeed)  # Wrap with rate limiter

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

    def check_ob_break_condition(self, ob_setup: OBSetup):
        """Simplified OB break condition check"""
        try:
            # Get recent 4H data
            df = self.get_4h_data(ob_setup.symbol, n_bars=10)
            if df is None or df.empty:
                return False

            # Check the most recent candle for break condition
            current_candle = df.iloc[-1]

            if ob_setup.direction == "UP":
                # For OB Up: price dips below OB low but closes above OB body low
                return (current_candle['low'] < ob_setup.ob_candle_low and
                        current_candle['close'] > ob_setup.ob_candle_body_low)

            else:  # DOWN direction
                # For OB Down: price rises above OB high but closes below OB body high
                return (current_candle['high'] > ob_setup.ob_candle_high and
                        current_candle['close'] < ob_setup.ob_candle_body_high)

        except Exception as e:
            logging.error(f"Error checking OB break condition for {ob_setup.symbol}: {e}")
            return False

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

    # ENHANCED FVG DETECTION BASED ON PINE SCRIPT
    def detect_fvg_setup(self, symbol):
        """Enhanced FVG detection based on Pine Script logic"""
        try:
            df = self.get_4h_data(symbol, n_bars=10)
            if df is None or len(df) < 3:
                return None

            # Check for FVG Up (Bullish)
            if self._is_fvg_up(df):
                third_candle = df.iloc[-3]
                return FVGSetup(
                    symbol=symbol,
                    direction="UP",
                    third_candle_time=third_candle.name,
                    third_candle_high=third_candle['high'],
                    third_candle_low=third_candle['low'],
                    third_candle_body_high=max(third_candle['open'], third_candle['close']),
                    third_candle_body_low=min(third_candle['open'], third_candle['close'])
                )

            # Check for FVG Down (Bearish)
            if self._is_fvg_down(df):
                third_candle = df.iloc[-3]
                return FVGSetup(
                    symbol=symbol,
                    direction="DOWN",
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

    def _is_fvg_up(self, df):
        """Check for FVG Up condition (low[0] > high[2])"""
        if len(df) < 3:
            return False

        current = df.iloc[-1]
        two_bars_ago = df.iloc[-3]

        # FVG Up: low of current candle > high of candle 2 bars ago
        return current['low'] > two_bars_ago['high']

    def _is_fvg_down(self, df):
        """Check for FVG Down condition (high[0] < low[2])"""
        if len(df) < 3:
            return False

        current = df.iloc[-1]
        two_bars_ago = df.iloc[-3]

        # FVG Down: high of current candle < low of candle 2 bars ago
        return current['high'] < two_bars_ago['low']

    # ENHANCED ORDER BLOCK DETECTION BASED ON PINE SCRIPT
    def detect_ob_setup(self, symbol):
        """Enhanced Order Block detection based on Pine Script logic"""
        try:
            df = self.get_4h_data(symbol, n_bars=10)
            if df is None or len(df) < 3:
                return None

            # Check for OB Up (Bullish)
            if self._is_ob_up(df):
                current_candle = df.iloc[-1]
                return OBSetup(
                    symbol=symbol,
                    direction="UP",
                    ob_candle_time=current_candle.name,
                    ob_candle_high=current_candle['high'],
                    ob_candle_low=current_candle['low'],
                    ob_candle_body_high=max(current_candle['open'], current_candle['close']),
                    ob_candle_body_low=min(current_candle['open'], current_candle['close'])
                )

            # Check for OB Down (Bearish)
            if self._is_ob_down(df):
                current_candle = df.iloc[-1]
                return OBSetup(
                    symbol=symbol,
                    direction="DOWN",
                    ob_candle_time=current_candle.name,
                    ob_candle_high=current_candle['high'],
                    ob_candle_low=current_candle['low'],
                    ob_candle_body_high=max(current_candle['open'], current_candle['close']),
                    ob_candle_body_low=min(current_candle['open'], current_candle['close'])
                )

            return None

        except Exception as e:
            logging.error(f"Error detecting OB setup for {symbol}: {e}")
            return None

    def _is_ob_up(self, df):
        """Check for OB Up condition"""
        if len(df) < 2:
            return False

        current = df.iloc[-1]  # Current candle
        previous = df.iloc[-2]  # Previous candle

        # OB Up: Previous candle is down, current is up, and current close > previous high
        return (previous['close'] < previous['open'] and  # Previous is down
                current['close'] > current['open'] and  # Current is up
                current['close'] > previous['high'])  # Current close > previous high

    def _is_ob_down(self, df):
        """Check for OB Down condition"""
        if len(df) < 2:
            return False

        current = df.iloc[-1]  # Current candle
        previous = df.iloc[-2]  # Previous candle

        # OB Down: Previous candle is up, current is down, and current close < previous low
        return (previous['close'] > previous['open'] and  # Previous is up
                current['close'] < current['open'] and  # Current is down
                current['close'] < previous['low'])  # Current close < previous low

    # STRUCTURE BREAKING FVG DETECTION
    def detect_structure_breaking_fvg(self, symbol):
        """Detect structure-breaking FVGs with better error handling"""
        try:
            df = self.get_4h_data(symbol, n_bars=20)
            if df is None or len(df) < 10:
                return None

            # Get pivot points
            pivots_high, pivots_low = self._find_pivots(df, lookback=3)

            # Check if we have pivots
            if not pivots_high or not pivots_low:
                return None

            current = df.iloc[-1]
            previous = df.iloc[-2]
            two_bars_ago = df.iloc[-3]

            max_pivot_high = max(pivots_high)
            min_pivot_low = min(pivots_low)

            # Structure Breaking FVG Up
            if (self._is_fvg_up(df) and
                    previous['close'] > max_pivot_high and
                    previous['low'] < max_pivot_high and
                    two_bars_ago['high'] < max_pivot_high and
                    current['low'] > max_pivot_high):
                return FVGSetup(
                    symbol=symbol,
                    direction="UP",
                    third_candle_time=two_bars_ago.name,
                    third_candle_high=two_bars_ago['high'],
                    third_candle_low=two_bars_ago['low'],
                    third_candle_body_high=max(two_bars_ago['open'], two_bars_ago['close']),
                    third_candle_body_low=min(two_bars_ago['open'], two_bars_ago['close']),
                    status="STRUCTURE_BREAKING"
                )

            # Structure Breaking FVG Down
            if (self._is_fvg_down(df) and
                    previous['close'] < min_pivot_low and
                    previous['high'] > min_pivot_low and
                    two_bars_ago['low'] > min_pivot_low and
                    current['high'] < min_pivot_low):
                return FVGSetup(
                    symbol=symbol,
                    direction="DOWN",
                    third_candle_time=two_bars_ago.name,
                    third_candle_high=two_bars_ago['high'],
                    third_candle_low=two_bars_ago['low'],
                    third_candle_body_high=max(two_bars_ago['open'], two_bars_ago['close']),
                    third_candle_body_low=min(two_bars_ago['open'], two_bars_ago['close']),
                    status="STRUCTURE_BREAKING"
                )

            return None

        except Exception as e:
            logging.error(f"Error detecting structure breaking FVG for {symbol}: {e}")
            return None

    def _find_pivots(self, df, lookback=3):
        """Find pivot highs and lows"""
        highs = []
        lows = []

        for i in range(lookback, len(df) - lookback):
            window_high = df['high'].iloc[i - lookback:i + lookback + 1]
            window_low = df['low'].iloc[i - lookback:i + lookback + 1]

            if df['high'].iloc[i] == window_high.max():
                highs.append(df['high'].iloc[i])

            if df['low'].iloc[i] == window_low.min():
                lows.append(df['low'].iloc[i])

        return highs, lows

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

        self.open_trade_symbols = set()  # Track symbols with open trades
        self.recently_traded = {}  # Track recently traded symbols with timestamps
        self.recent_setups = defaultdict(list)  # Track recent setups per symbol
        self.setup_cooldown = timedelta(hours=4)  # 4-hour cooldown for same setup type

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

    def can_trade_symbol(self, symbol, setup_type):
        """Check if we can trade this symbol (no recent trades)"""
        current_time = datetime.now()

        # Check if symbol already has open trade
        if symbol in self.open_trade_symbols:
            return False

        # Check if symbol was recently traded (within last 2 hours)
        if symbol in self.recently_traded:
            last_trade_time = self.recently_traded[symbol]
            if (current_time - last_trade_time).total_seconds() < 7200:  # 2 hours
                return False

        return True

    def is_duplicate_setup(self, symbol, direction, setup_type):
        """Check if this is a duplicate setup"""
        current_time = datetime.now()
        key = f"{symbol}_{direction}_{setup_type}"

        # Clean old setups
        self.recent_setups[key] = [time for time in self.recent_setups[key]
                                   if current_time - time < self.setup_cooldown]

        # If we have recent setups of this type, it's a duplicate
        return len(self.recent_setups[key]) > 0

    def record_setup(self, symbol, direction, setup_type):
        """Record a new setup detection"""
        key = f"{symbol}_{direction}_{setup_type}"
        self.recent_setups[key].append(datetime.now())

        # Keep only recent setups
        self.recent_setups[key] = [time for time in self.recent_setups[key]
                                   if datetime.now() - time < self.setup_cooldown]

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
            # Check if we can trade this symbol
            if not self.can_trade_symbol(symbol, setup_type):
                self.log(f"⏸ Skipping {order_type} for {symbol} - already traded recently")
                return

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

                # Track this trade
                self.open_trade_symbols.add(symbol)
                self.recently_traded[symbol] = datetime.now()

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
        """Scan for new FVG setups with duplicate prevention"""
        for symbol in self.config.symbols:
            try:
                clean_symbol = symbol.split(":")[1] if ":" in symbol else symbol

                # Skip if already monitoring
                if clean_symbol in self.active_fvg_setups:
                    continue

                # Try regular FVG first
                fvg_setup = self.strategy.detect_fvg_setup(clean_symbol)
                if fvg_setup:
                    # Check for duplicates
                    if self.is_duplicate_setup(clean_symbol, fvg_setup.direction, "FVG"):
                        continue

                    self.record_setup(clean_symbol, fvg_setup.direction, "FVG")
                    self.active_fvg_setups[clean_symbol] = fvg_setup
                    setup_type = "STRUCTURE_BREAKING" if fvg_setup.status == "STRUCTURE_BREAKING" else "REGULAR"
                    self.log(f"🎯 FVG {fvg_setup.direction} {setup_type} setup detected for {clean_symbol}")
                    self.send_email_alert(
                        f"FVG {setup_type} Setup Detected - {clean_symbol}",
                        f"FVG {fvg_setup.direction} {setup_type} setup detected for {clean_symbol}\n"
                        f"Waiting for tail confirmation..."
                    )
            except Exception as e:
                self.log(f"Error scanning FVG for {symbol}: {e}")

    def cleanup_old_trades(self):
        """Clean up old trade records"""
        current_time = datetime.now()
        expired_symbols = []

        for symbol, trade_time in list(self.recently_traded.items()):
            if (current_time - trade_time).total_seconds() > 86400:  # 24 hours
                expired_symbols.append(symbol)

        for symbol in expired_symbols:
            self.recently_traded.pop(symbol, None)
            self.open_trade_symbols.discard(symbol)

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

    def scan_ob_setups_limited(self, symbols_to_scan):
        """Scan only specified symbols for OB setups"""
        for symbol in symbols_to_scan:
            try:
                clean_symbol = symbol.split(":")[1] if ":" in symbol else symbol

                # Skip if already monitoring
                if clean_symbol in self.active_ob_setups:
                    continue

                ob_setup = self.strategy.detect_ob_setup(clean_symbol)
                if ob_setup:
                    # Check for duplicates
                    if self.is_duplicate_setup(clean_symbol, ob_setup.direction, "OB"):
                        continue

                    self.record_setup(clean_symbol, ob_setup.direction, "OB")
                    self.active_ob_setups[clean_symbol] = ob_setup
                    self.log(f"🎯 OB {ob_setup.direction} setup detected for {clean_symbol}")
                    self.send_email_alert(
                        f"OB Setup Detected - {clean_symbol}",
                        f"OB {ob_setup.direction} setup detected for {clean_symbol}\n"
                        f"Monitoring for break condition..."
                    )
            except Exception as e:
                self.log(f"Error scanning OB for {symbol}: {e}")

    def run_strategy_cycle(self):
        """Run one complete strategy cycle - simplified version"""
        if not self.running:
            return

        try:
            # Clean up old trades
            self.cleanup_old_trades()

            # Get current minute to determine which symbols to scan
            current_minute = datetime.now().minute

            # Scan only a subset of symbols each cycle (every 3rd symbol)
            symbols_to_scan = []
            for i, symbol in enumerate(self.config.symbols):
                if i % 3 == current_minute % 3:
                    symbols_to_scan.append(symbol)

            # 1. Scan for new setups (limited set)
            for symbol in symbols_to_scan:
                try:
                    clean_symbol = symbol.split(":")[1] if ":" in symbol else symbol

                    # Skip if already monitoring
                    if clean_symbol not in self.active_fvg_setups:
                        fvg_setup = self.strategy.detect_fvg_setup(clean_symbol)
                        if fvg_setup and not self.is_duplicate_setup(clean_symbol, fvg_setup.direction, "FVG"):
                            self.record_setup(clean_symbol, fvg_setup.direction, "FVG")
                            self.active_fvg_setups[clean_symbol] = fvg_setup
                            self.log(f"🎯 FVG {fvg_setup.direction} setup detected for {clean_symbol}")

                    if clean_symbol not in self.active_ob_setups:
                        ob_setup = self.strategy.detect_ob_setup(clean_symbol)
                        if ob_setup and not self.is_duplicate_setup(clean_symbol, ob_setup.direction, "OB"):
                            self.record_setup(clean_symbol, ob_setup.direction, "OB")
                            self.active_ob_setups[clean_symbol] = ob_setup
                            self.log(f"🎯 OB {ob_setup.direction} setup detected for {clean_symbol}")

                except Exception as e:
                    self.log(f"Error scanning setups for {symbol}: {e}")

            # 2. Monitor active setups
            self.monitor_fvg_setups()
            self.monitor_ob_setups()

        except Exception as e:
            self.log(f"Error in strategy cycle: {e}")

    def scan_fvg_setups_limited(self, symbols_to_scan):
        """Scan only specified symbols for FVG setups"""
        for symbol in symbols_to_scan:
            try:
                clean_symbol = symbol.split(":")[1] if ":" in symbol else symbol

                # Skip if already monitoring
                if clean_symbol in self.active_fvg_setups:
                    continue

                # Try regular FVG first
                fvg_setup = self.strategy.detect_fvg_setup(clean_symbol)
                if fvg_setup:
                    # Check for duplicates
                    if self.is_duplicate_setup(clean_symbol, fvg_setup.direction, "FVG"):
                        continue

                    self.record_setup(clean_symbol, fvg_setup.direction, "FVG")
                    self.active_fvg_setups[clean_symbol] = fvg_setup
                    setup_type = "STRUCTURE_BREAKING" if fvg_setup.status == "STRUCTURE_BREAKING" else "REGULAR"
                    self.log(f"🎯 FVG {fvg_setup.direction} {setup_type} setup detected for {clean_symbol}")
                    self.send_email_alert(
                        f"FVG {setup_type} Setup Detected - {clean_symbol}",
                        f"FVG {fvg_setup.direction} {setup_type} setup detected for {clean_symbol}\n"
                        f"Waiting for tail confirmation..."
                    )
            except Exception as e:
                self.log(f"Error scanning FVG for {symbol}: {e}")

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
# Parameters Window
# -----------------------
class ParametersWindow(ctk.CTkToplevel):
    def __init__(self, parent, configs, users, workers, email_sender, main_app):
        super().__init__(parent)
        self.title("Trading Parameters & Configuration")
        self.geometry("1200x800")
        self.minsize(1000, 600)  # Minimum size

        # Make window modal
        self.transient(parent)
        self.grab_set()

        self.configs = configs
        self.users = users
        self.workers = workers
        self.email_sender = email_sender
        self.main_app = main_app  # Reference to main app for logging

        self.init_ui()
        self.refresh_users()
        self.refresh_tree()

    def init_ui(self):
        """Initialize parameters interface"""
        # Configure main window grid
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Main notebook for different sections
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)

        # Users tab
        users_tab = ctk.CTkFrame(notebook, corner_radius=8)
        notebook.add(users_tab, text="👥 Users Management")
        self.setup_users_tab(users_tab)

        # Configurations tab
        config_tab = ctk.CTkFrame(notebook, corner_radius=8)
        notebook.add(config_tab, text="⚙️ Configurations")
        self.setup_config_tab(config_tab)

        # Risk Management tab
        risk_tab = ctk.CTkFrame(notebook, corner_radius=8)
        notebook.add(risk_tab, text="📊 Risk Management")
        self.setup_risk_tab(risk_tab)

    def setup_users_tab(self, parent):
        """Setup users management tab"""
        # Configure parent grid
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)

        # Users list
        user_frame = ctk.CTkFrame(parent, corner_radius=8)
        user_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        user_frame.grid_columnconfigure(0, weight=1)
        user_frame.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(user_frame, text="Users Management",
                     font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, pady=10)

        # User listbox frame
        listbox_frame = ctk.CTkFrame(user_frame, corner_radius=6)
        listbox_frame.grid(row=1, column=0, sticky="nsew", pady=10, padx=10)
        listbox_frame.grid_columnconfigure(0, weight=1)
        listbox_frame.grid_rowconfigure(0, weight=1)

        self.user_listbox = tk.Listbox(listbox_frame, selectmode="multiple",
                                       bg="#2b2b2b", fg="white", font=("Arial", 11),
                                       relief="flat", highlightthickness=0)
        self.user_listbox.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

        # Add scrollbar to listbox
        scrollbar = ttk.Scrollbar(listbox_frame, orient="vertical", command=self.user_listbox.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.user_listbox.configure(yscrollcommand=scrollbar.set)

        # User buttons
        btn_frame = ctk.CTkFrame(user_frame)
        btn_frame.grid(row=2, column=0, sticky="ew", pady=10, padx=10)

        ctk.CTkButton(btn_frame, text="➕ Add User",
                      command=self.add_user, width=120).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="🗑️ Delete User",
                      command=self.delete_user, width=120,
                      fg_color="#D35B58", hover_color="#C77B78").pack(side="left", padx=5)

    def setup_config_tab(self, parent):
        """Setup configurations tab"""
        main_frame = ctk.CTkFrame(parent)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)
        main_frame.grid_columnconfigure(0, weight=1)
        main_frame.grid_rowconfigure(1, weight=1)

        # Config tree
        tree_frame = ctk.CTkFrame(main_frame)
        tree_frame.grid(row=0, column=0, sticky="nsew", pady=10)
        tree_frame.grid_columnconfigure(0, weight=1)
        tree_frame.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(tree_frame, text="Configurations",
                     font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, pady=10, sticky="w")

        # Treeview with scrollbar
        tree_container = ctk.CTkFrame(tree_frame)
        tree_container.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        tree_container.grid_columnconfigure(0, weight=1)
        tree_container.grid_rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(tree_container, columns=("Symbols", "Recipients", "Active"), height=8,
                                 show="tree headings")
        self.tree.heading("#0", text="Config Name")
        self.tree.heading("Symbols", text="Symbols")
        self.tree.heading("Recipients", text="Recipients")
        self.tree.heading("Active", text="Active")

        # Configure column widths
        self.tree.column("#0", width=200)
        self.tree.column("Symbols", width=250)
        self.tree.column("Recipients", width=200)
        self.tree.column("Active", width=80)

        self.tree.grid(row=0, column=0, sticky="nsew")

        # Add scrollbar to treeview
        tree_scroll = ttk.Scrollbar(tree_container, orient="vertical", command=self.tree.yview)
        tree_scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=tree_scroll.set)

        # Config buttons - Two rows for better organization
        btn_frame1 = ctk.CTkFrame(main_frame)
        btn_frame1.grid(row=1, column=0, sticky="ew", pady=5)

        btn_frame2 = ctk.CTkFrame(main_frame)
        btn_frame2.grid(row=2, column=0, sticky="ew", pady=5)

        # First row of buttons
        ctk.CTkButton(btn_frame1, text="➕ Add Config",
                      command=self.add_config, width=120).pack(side="left", padx=2)
        ctk.CTkButton(btn_frame1, text="🗑️ Delete Config",
                      command=self.delete_config, width=120,
                      fg_color="#D35B58", hover_color="#C77B78").pack(side="left", padx=2)
        ctk.CTkButton(btn_frame1, text="👥 Manage Users",
                      command=self.manage_users_config, width=120).pack(side="left", padx=2)
        ctk.CTkButton(btn_frame1, text="✏️ Rename Config",
                      command=self.rename_config, width=120).pack(side="left", padx=2)

        # Second row of buttons
        ctk.CTkButton(btn_frame2, text="🔄 Refresh Config",
                      command=self.refresh_config, width=120).pack(side="left", padx=2)
        ctk.CTkButton(btn_frame2, text="🔓 Unhold Messages",
                      command=self.unhold_config, width=120).pack(side="left", padx=2)
        ctk.CTkButton(btn_frame2, text="🟢 Start Config",
                      command=self.start_config, width=120,
                      fg_color="#2E8B57", hover_color="#3CB371").pack(side="left", padx=2)
        ctk.CTkButton(btn_frame2, text="🔴 Stop Config",
                      command=self.stop_config, width=120,
                      fg_color="#D35B58", hover_color="#C77B78").pack(side="left", padx=2)

    def delete_config(self):
        """Delete selected configuration"""
        selected = self.tree.selection()
        if not selected:
            messagebox.showerror("Error", "Select a configuration to delete")
            return

        config_name = selected[0]

        # Confirm deletion
        if not messagebox.askyesno("Confirm Delete",
                                   f"Are you sure you want to delete configuration '{config_name}'?"):
            return

        try:
            # Stop worker if running
            if config_name in self.workers:
                worker = self.workers[config_name]
                if hasattr(worker, 'stop'):
                    worker.stop()
                del self.workers[config_name]

            # Remove from configs
            if config_name in self.configs:
                del self.configs[config_name]

            # Save updated configs
            save_json(CONFIG_FILE, self.configs)

            self.refresh_tree()
            messagebox.showinfo("Success", f"Configuration '{config_name}' deleted successfully!")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to delete configuration: {e}")

    def safe_log(self, message):
        """Safe logging that works with both main app and standalone"""
        if hasattr(self, 'main_app') and hasattr(self.main_app, 'log_message'):
            self.main_app.log_message(message)
        else:
            print(f"[ParametersWindow] {message}")

    def setup_risk_tab(self, parent):
        """Setup risk management tab"""
        main_frame = ctk.CTkFrame(parent)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Stop Loss & Take Profit
        sl_tp_frame = ctk.CTkFrame(main_frame)
        sl_tp_frame.pack(fill="x", padx=10, pady=10)

        ctk.CTkLabel(sl_tp_frame, text="Stop Loss & Take Profit",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(pady=10)

        # Stop Loss
        sl_frame = ctk.CTkFrame(sl_tp_frame)
        sl_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(sl_frame, text="Stop Loss Type:").pack(side="left")
        self.sl_type = ctk.CTkComboBox(sl_frame,
                                       values=["Lowest 30min Low/Highest 30min High", "Fixed Percentage", "ATR Based"])
        self.sl_type.pack(side="right", fill="x", padx=10)
        self.sl_type.set("Lowest 30min Low/Highest 30min High")

        # Take Profit
        tp_frame = ctk.CTkFrame(sl_tp_frame)
        tp_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(tp_frame, text="Take Profit Multiplier:").pack(side="left")
        self.tp_multiplier = ctk.CTkEntry(tp_frame, placeholder_text="2.0")
        self.tp_multiplier.insert(0, "2.0")
        self.tp_multiplier.pack(side="right", fill="x", padx=10)

        # Risk per trade
        risk_frame = ctk.CTkFrame(sl_tp_frame)
        risk_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(risk_frame, text="Risk Per Trade (%):").pack(side="left")
        self.risk_entry = ctk.CTkEntry(risk_frame, placeholder_text="0.5")
        self.risk_entry.insert(0, "0.5")
        self.risk_entry.pack(side="right", fill="x", padx=10)

        # Capital
        capital_frame = ctk.CTkFrame(sl_tp_frame)
        capital_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(capital_frame, text="Trading Capital ($):").pack(side="left")
        self.capital_entry = ctk.CTkEntry(capital_frame, placeholder_text="1000")
        self.capital_entry.insert(0, "1000")
        self.capital_entry.pack(side="right", fill="x", padx=10)

        # Save risk settings
        ctk.CTkButton(sl_tp_frame, text="Save Risk Settings",
                      command=self.save_risk_settings).pack(pady=10)

    # User Management Methods
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

            # Remove from all configurations
            for cfg in self.configs.values():
                cfg['recipients'] = [u for u in cfg['recipients'] if u['email'] != email]

        save_json(USERS_FILE, self.users)
        save_json(CONFIG_FILE, self.configs)
        self.refresh_users()
        self.refresh_tree()

    # Config Management Methods
    def refresh_tree(self):
        """Refresh configurations tree"""
        for item in self.tree.get_children():
            self.tree.delete(item)
        for name, cfg in self.configs.items():
            self.tree.insert("", "end", iid=name, text=name,
                             values=(",".join(cfg['symbols']),
                                     ",".join([r['name'] for r in cfg['recipients']]),
                                     "Yes" if self.workers.get(name, None) and self.workers[name].running else "No"))

    def add_config(self):
        """Add new configuration"""
        selected_indices = self.user_listbox.curselection()
        if not selected_indices:
            messagebox.showerror("Error", "Select at least one user")
            return
        recipients = [list(self.users.values())[i] for i in selected_indices]

        win = ctk.CTkToplevel(self)
        win.title("New Configuration")
        win.geometry("500x300")
        win.transient(self)
        win.grab_set()

        # Configure grid for proper layout
        win.grid_columnconfigure(0, weight=1)

        row = 0

        ctk.CTkLabel(win, text="Config Name:").grid(row=row, column=0, padx=20, pady=5, sticky="w")
        entry_name = ctk.CTkEntry(win, width=300)
        entry_name.grid(row=row, column=0, padx=20, pady=5, sticky="ew")
        row += 1

        ctk.CTkLabel(win, text="Symbols (comma separated URLs or EXCHANGE:SYMBOL):").grid(row=row, column=0, padx=20,
                                                                                          pady=5, sticky="w")
        entry_symbols = ctk.CTkEntry(win, width=400)
        entry_symbols.grid(row=row, column=0, padx=20, pady=5, sticky="ew")
        row += 1

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

            # Only include valid TradingConfig fields
            config_data = {
                "name": name,
                "symbols": symbols,
                "recipients": recipients,
                "trading_active": False,
                "email_notifications": True,
                "capital": 1000.0,  # Default values
                "risk_per_trade": 0.5
            }

            self.configs[name] = config_data
            save_json(CONFIG_FILE, self.configs)

            # Create worker with valid fields only
            config_obj = TradingConfig(
                name=name,
                symbols=symbols,
                recipients=recipients,
                capital=1000.0,
                risk_per_trade=0.5,
                trading_active=False
            )
            worker = AdvancedTradeWorker(config_obj, self.email_sender,
                                         self.main_app.log_message if hasattr(self.main_app, 'log_message') else print)
            self.workers[name] = worker

            # Start worker thread using main app's worker loop
            threading.Thread(target=self.main_app.worker_loop, args=(name,), daemon=True).start()

            self.refresh_tree()
            win.destroy()
            messagebox.showinfo("Success", f"Configuration '{name}' added successfully!")

        btn_frame = ctk.CTkFrame(win)
        btn_frame.grid(row=row, column=0, padx=20, pady=20, sticky="ew")
        btn_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkButton(btn_frame, text="Save Config", command=save).pack(pady=10)

    def manage_users_config(self):
        """Manage users in selected configuration"""
        selected = self.tree.selection()
        if not selected:
            messagebox.showerror("Error", "Select a configuration")
            return
        config_name = selected[0]
        config = self.configs.get(config_name)
        if not config:
            messagebox.showerror("Error", f"Config {config_name} not found")
            return

        win = ctk.CTkToplevel(self)
        win.title(f"Manage Users in {config_name}")
        win.geometry("400x400")

        listbox = tk.Listbox(win, selectmode="multiple", bg="#2b2b2b", fg="white")
        listbox.pack(fill="both", expand=True, padx=10, pady=10)

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
            if config_name in self.workers:
                self.workers[config_name].refresh_new_users()

        def delete_users():
            selected_indices = listbox.curselection()
            for i in reversed(selected_indices):
                del config['recipients'][i]
            save_json(CONFIG_FILE, self.configs)
            listbox.delete(0, tk.END)
            for u in config['recipients']:
                listbox.insert(tk.END, f"{u['name']} ({u['email']})")

        btn_frame = ctk.CTkFrame(win)
        btn_frame.pack(fill="x", pady=10)

        ctk.CTkButton(btn_frame, text="Add Selected Users", command=add_users).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="Remove Selected Users", command=delete_users,
                      fg_color="#D35B58", hover_color="#C77B78").pack(side="left", padx=5)

    def rename_config(self):
        """Rename selected configuration"""
        selected = self.tree.selection()
        if not selected:
            messagebox.showerror("Error", "Select a configuration")
            return
        old_name = selected[0]
        new_name = simpledialog.askstring("Rename Config", "Enter new name:", parent=self)
        if not new_name or new_name in self.configs:
            messagebox.showerror("Error", "Invalid name or name exists")
            return
        cfg = self.configs.pop(old_name)
        cfg['name'] = new_name
        self.configs[new_name] = cfg
        if old_name in self.workers:
            self.workers[new_name] = self.workers.pop(old_name)
        save_json(CONFIG_FILE, self.configs)
        self.refresh_tree()

    def start_config(self):
        """Start selected configuration"""
        selected = self.tree.selection()
        if not selected:
            messagebox.showerror("Error", "Select a configuration to start")
            return

        for name in selected:
            worker = self.workers.get(name)
            if worker:
                if worker.start_trading():  # Use start_trading instead of start
                    if hasattr(self.main_app, 'log_message'):
                        self.main_app.log_message(f"✅ STARTED: {name}")
                    else:
                        print(f"✅ STARTED: {name}")
                else:
                    if hasattr(self.main_app, 'log_message'):
                        self.main_app.log_message(f"❌ Failed to start: {name}")
                    else:
                        print(f"❌ Failed to start: {name}")
            else:
                if hasattr(self.main_app, 'log_message'):
                    self.main_app.log_message(f"⚠️ No worker found for: {name}")
                else:
                    print(f"⚠️ No worker found for: {name}")
        self.refresh_tree()

    def stop_config(self):
        """Stop selected configuration"""
        selected = self.tree.selection()
        if not selected:
            messagebox.showerror("Error", "Select a configuration to stop")
            return

        for name in selected:
            worker = self.workers.get(name)
            if worker:
                worker.stop_trading()  # Use stop_trading instead of stop
                if hasattr(self.main_app, 'log_message'):
                    self.main_app.log_message(f"⏸ STOPPED: {name}")
                else:
                    print(f"⏸ STOPPED: {name}")
            else:
                if hasattr(self.main_app, 'log_message'):
                    self.main_app.log_message(f"⚠️ No worker found for: {name}")
                else:
                    print(f"⚠️ No worker found for: {name}")
        self.refresh_tree()

    def unhold_config(self):
        """Unhold messages for selected configuration"""
        selected = self.tree.selection()
        for name in selected:
            worker = self.workers.get(name)
            if worker:
                worker.unhold()
        self.refresh_tree()

    def refresh_config(self):
        """Refresh selected configuration"""
        selected = self.tree.selection()
        for name in selected:
            worker = self.workers.get(name)
            if worker:
                worker.refresh_new_users()
                worker.start()

    def save_risk_settings(self):
        """Save risk management settings to all workers"""
        try:
            capital = float(self.capital_entry.get() or "1000")
            risk_per_trade = float(self.risk_entry.get() or "0.5")

            # Update all workers with new risk settings
            for worker_name, worker in self.workers.items():
                worker.config.capital = capital
                worker.config.risk_per_trade = risk_per_trade

            messagebox.showinfo("Success",
                                f"Risk settings updated globally!\nCapital: ${capital}\nRisk per trade: {risk_per_trade}%")

        except ValueError as e:
            messagebox.showerror("Error", "Please enter valid numbers for capital and risk")


# -----------------------
# Simplified GUI Application
# -----------------------
class AdvancedTradingApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Advanced MT5 Trading Bot - EXACT RULES")
        self.geometry("1400x900")
        self.minsize(1200, 800)  # Minimum size

        # Configure grid for proper resizing
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Set modern color theme
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("dark-blue")

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
        # Create menu bar
        self.create_menu_bar()

        main_frame = ctk.CTkFrame(self)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Configure main frame grid
        main_frame.grid_columnconfigure(1, weight=1)
        main_frame.grid_rowconfigure(0, weight=1)

        # Left panel - Simple Controls
        control_frame = ctk.CTkFrame(main_frame, width=350, corner_radius=10)
        control_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        control_frame.grid_propagate(False)

        # Right panel - Logs and Info
        info_frame = ctk.CTkFrame(main_frame, corner_radius=10)
        info_frame.grid(row=0, column=1, sticky="nsew")
        info_frame.grid_columnconfigure(0, weight=1)
        info_frame.grid_rowconfigure(1, weight=1)

        self.setup_simple_control_panel(control_frame)
        self.setup_info_panel(info_frame)

    def create_menu_bar(self):
        """Create menu bar"""
        menu_bar = tk.Menu(self)
        self.config(menu=menu_bar)

        # Parameters menu
        params_menu = tk.Menu(menu_bar, tearoff=0)
        menu_bar.add_cascade(label="Parameters", menu=params_menu)
        params_menu.add_command(label="Open Parameters", command=self.open_parameters)

    def open_parameters(self):
        """Open parameters window"""
        ParametersWindow(self, self.configs, self.users, self.workers, self.email_sender, self)

    def setup_simple_control_panel(self, parent):
        """Setup simplified control panel"""
        # Configure parent grid
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(3, weight=1)  # Give weight to setups frame

        # Title
        title_label = ctk.CTkLabel(parent, text="Trading Bot Control",
                                   font=ctk.CTkFont(size=20, weight="bold"))
        title_label.grid(row=0, column=0, pady=(20, 10), padx=20, sticky="ew")

        # Strategy Info with better styling
        strategy_info = """
    🤖 EXACT TRADING RULES:

    🔹 STOP LOSS:
    • BUY: Lowest 30min low
    • SELL: Highest 30min high

    🔹 TAKE PROFIT:
    • 2× Stop Loss distance

    🔹 RISK MANAGEMENT:
    • 0.5% risk per trade
    • Capital protection
            """
        info_frame = ctk.CTkFrame(parent, fg_color="#2b2b2b", corner_radius=8)
        info_frame.grid(row=1, column=0, sticky="ew", padx=15, pady=10)

        info_label = ctk.CTkLabel(info_frame, text=strategy_info, justify="left",
                                  font=ctk.CTkFont(size=12))
        info_label.pack(padx=10, pady=10)

        # Active setups display
        setups_frame = ctk.CTkFrame(parent, corner_radius=8)
        setups_frame.grid(row=2, column=0, sticky="nsew", padx=15, pady=10)
        setups_frame.grid_columnconfigure(0, weight=1)
        setups_frame.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(setups_frame, text="Active Setups:",
                     font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, sticky="w", padx=10, pady=(10, 5))

        self.setups_text = ctk.CTkTextbox(setups_frame, height=200, corner_radius=6,
                                          fg_color="#1a1a1a", text_color="white")
        self.setups_text.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.setups_text.insert("1.0", "No active setups")
        self.setups_text.configure(state="disabled")

        # Status and Control buttons
        status_frame = ctk.CTkFrame(parent, corner_radius=8)
        status_frame.grid(row=3, column=0, sticky="ew", padx=15, pady=10)

        self.status_label = ctk.CTkLabel(status_frame, text="🔴 SYSTEM STOPPED",
                                         text_color="#ff6b6b", font=ctk.CTkFont(size=16, weight="bold"))
        self.status_label.pack(pady=15)

        # Control buttons
        button_frame = ctk.CTkFrame(parent)
        button_frame.grid(row=4, column=0, sticky="ew", padx=15, pady=(0, 20))

        self.start_btn = ctk.CTkButton(button_frame, text="START TRADING",
                                       command=self.start_all_trading,
                                       fg_color="#2E8B57", hover_color="#3CB371",
                                       height=40, font=ctk.CTkFont(weight="bold"))
        self.start_btn.pack(fill="x", pady=(0, 10))

        self.stop_btn = ctk.CTkButton(button_frame, text="STOP TRADING",
                                      command=self.stop_all_trading,
                                      fg_color="#DC143C", hover_color="#FF6347",
                                      height=40, font=ctk.CTkFont(weight="bold"))
        self.stop_btn.pack(fill="x", pady=0)

    def setup_info_panel(self, parent):
        """Setup information panel"""
        # Configure parent grid
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)

        # Title
        title_label = ctk.CTkLabel(parent, text="Trading Log",
                                   font=ctk.CTkFont(size=16, weight="bold"))
        title_label.grid(row=0, column=0, sticky="w", padx=15, pady=(15, 5))

        # Log area
        log_frame = ctk.CTkFrame(parent, corner_radius=8)
        log_frame.grid(row=1, column=0, sticky="nsew", padx=15, pady=(0, 15))
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(0, weight=1)

        self.log_text = scrolledtext.ScrolledText(log_frame,
                                                  bg="#1a1a1a", fg="#00ff00",  # Green text on dark background
                                                  font=("Consolas", 11),
                                                  insertbackground="white",
                                                  selectbackground="#3b3b3b")
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
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
        """Worker execution loop with longer intervals"""
        worker = self.workers[config_name]
        cycle_count = 0

        while True:
            try:
                if worker.running and worker.config.trading_active:
                    worker.run_strategy_cycle()
                    self.update_setups_display()

                # Every 3rd cycle, do full cleanup (every 3 minutes)
                cycle_count += 1
                if cycle_count >= 3:
                    worker.cleanup_old_trades()
                    cycle_count = 0

                time.sleep(60)  # Keep 1 minute but scan fewer symbols each cycle
            except Exception as e:
                self.log_message(f"Error in worker {config_name}: {e}")
                time.sleep(30)

    def start_existing_configs_stopped(self):
        """Start existing configurations in STOPPED state"""
        for config_name, config_data in self.configs.items():
            try:
                # Only pass valid fields to TradingConfig
                valid_fields = {k: v for k, v in config_data.items()
                                if k in ['name', 'symbols', 'recipients', 'capital', 'risk_per_trade',
                                         'trading_active', 'email_notifications', 'account', 'password', 'server']}

                config_obj = TradingConfig(**valid_fields)
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


