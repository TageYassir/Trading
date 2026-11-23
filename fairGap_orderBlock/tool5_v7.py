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
# -----------------------
# Constants and Configuration - VERSION SPECIFIC
# -----------------------
CONFIG_FILE = "trading_config_tool5_v7.json"
TRADES_FILE = "trade_history_tool5_v7.csv"
USERS_FILE = "users_config_tool5_v7.json"
APP_ICON = "icon_trading.ico"

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
    def __init__(self, tv_datafeed, max_requests_per_minute=15):  # Reduced further
        self.tv = tv_datafeed
        self.max_requests = max_requests_per_minute
        self.requests = []
        self.data_cache = {}
        self.cache_duration = timedelta(minutes=10)  # Increased cache duration
        self.lock = threading.Lock()

    def get_hist(self, symbol, exchange, interval, n_bars):
        # Create cache key
        cache_key = f"{symbol}_{exchange}_{interval}_{n_bars}"

        # Check cache first with thread safety
        with self.lock:
            if cache_key in self.data_cache:
                cached_data, timestamp = self.data_cache[cache_key]
                if datetime.now() - timestamp < self.cache_duration:
                    return cached_data

        # Enhanced rate limiting with backoff
        self._wait_if_needed()

        try:
            # Add retry logic with exponential backoff
            for attempt in range(3):
                try:
                    data = self.tv.get_hist(symbol=symbol, exchange=exchange,
                                            interval=interval, n_bars=n_bars)

                    if data is not None and not data.empty:
                        # Cache the data with thread safety
                        with self.lock:
                            self.data_cache[cache_key] = (data, datetime.now())
                            self.requests.append(datetime.now())
                        return data

                    # If data is empty, wait and retry
                    time.sleep(2 ** attempt)  # Exponential backoff

                except Exception as e:
                    if "429" in str(e) or "Too Many Requests" in str(e):
                        wait_time = (2 ** attempt) * 30  # Longer wait for rate limits
                        logging.warning(f"Rate limit hit, waiting {wait_time}s (attempt {attempt + 1})")
                        time.sleep(wait_time)
                    else:
                        logging.error(f"Error fetching data for {symbol} (attempt {attempt + 1}): {e}")
                        time.sleep(2 ** attempt)

            logging.error(f"Failed to fetch data for {symbol} after 3 attempts")
            return None

        except Exception as e:
            logging.error(f"Unexpected error in get_hist for {symbol}: {e}")
            return None

    def _wait_if_needed(self):
        """Wait if we've made too many requests recently with improved logic"""
        with self.lock:
            now = datetime.now()
            one_min_ago = now - timedelta(minutes=1)

            # Remove requests older than 1 minute
            self.requests = [req for req in self.requests if req > one_min_ago]

            # If we've hit the limit, wait
            if len(self.requests) >= self.max_requests:
                oldest_request = self.requests[0]
                sleep_time = 60 - (now - oldest_request).total_seconds()
                if sleep_time > 0:
                    logging.info(f"Rate limit approaching, waiting {sleep_time:.1f}s")
                    time.sleep(sleep_time + 2)  # Add buffer
                # Remove the oldest request after waiting
                if self.requests:
                    self.requests.pop(0)


class GlobalRateLimitedTvDatafeed:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, tv_datafeed, max_requests_per_minute=10):  # Very conservative
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance.tv = tv_datafeed
                cls._instance.max_requests = max_requests_per_minute
                cls._instance.requests = []
                cls._instance.data_cache = {}
                cls._instance.cache_duration = timedelta(minutes=15)  # Longer cache
                cls._instance.global_lock = threading.Lock()
                cls._instance.last_request_time = None
                cls._instance.min_request_interval = 6.0  # Minimum 6 seconds between requests
        return cls._instance

    def get_hist(self, symbol, exchange, interval, n_bars):
        time.sleep(10)  # Initial wait to stagger requests
        # Create cache key
        cache_key = f"{symbol}_{exchange}_{interval}_{n_bars}"

        # Check cache first
        with self.global_lock:
            if cache_key in self.data_cache:
                cached_data, timestamp = self.data_cache[cache_key]
                if datetime.now() - timestamp < self.cache_duration:
                    return cached_data

        # Global rate limiting with minimum interval
        self._global_wait_if_needed()

        try:
            # Single attempt with proper waiting
            data = self.tv.get_hist(symbol=symbol, exchange=exchange,
                                    interval=interval, n_bars=n_bars)

            if data is not None and not data.empty:
                # Cache the data
                with self.global_lock:
                    self.data_cache[cache_key] = (data, datetime.now())
                    self.requests.append(datetime.now())
                    self.last_request_time = datetime.now()
                return data

            logging.warning(f"No data returned for {symbol}, returning None")
            return None

        except Exception as e:
            if "429" in str(e) or "Too Many Requests" in str(e):
                logging.error(f"🚨 CRITICAL: Rate limit exceeded for {symbol}. Waiting 5 minutes.")
                time.sleep(300)  # Wait 5 minutes on hard rate limit
            else:
                logging.error(f"Error fetching data for {symbol}: {e}")
            return None

    def _global_wait_if_needed(self):
        """Global rate limiting with minimum interval between requests"""
        with self.global_lock:
            now = datetime.now()

            # Enforce minimum interval between requests
            if self.last_request_time:
                time_since_last = (now - self.last_request_time).total_seconds()
                if time_since_last < self.min_request_interval:
                    sleep_time = self.min_request_interval - time_since_last
                    logging.debug(f"Enforcing minimum interval, waiting {sleep_time:.1f}s")
                    time.sleep(sleep_time)
                    now = datetime.now()  # Update time after sleep

            # Remove requests older than 1 minute
            one_min_ago = now - timedelta(minutes=1)
            self.requests = [req for req in self.requests if req > one_min_ago]

            # If we've hit the limit, wait
            if len(self.requests) >= self.max_requests:
                oldest_request = self.requests[0]
                sleep_time = 60 - (now - oldest_request).total_seconds()
                if sleep_time > 0:
                    logging.warning(f"🔄 Global rate limit reached, waiting {sleep_time:.1f}s")
                    time.sleep(sleep_time + 5)  # Extra buffer

                # Update time and clean up
                now = datetime.now()
                one_min_ago = now - timedelta(minutes=1)
                self.requests = [req for req in self.requests if req > one_min_ago]

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
# Enhanced Data Classes with New Indicator Support
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
    status: str = "SIMULATED"  # Changed from "OPEN" to "SIMULATED"
    stop_loss: float = 0.0
    take_profit: float = 0.0
    reason: str = "SIMULATION MODE"
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
    # States:
    #   AWAITING_CANDIDATE -> waiting for next closed 4H candle(s) to test wick-only
    #   AWAITING_5M        -> 5m window waiting for Range Filter confirmation (max 4h)
    #   CONFIRMED          -> 5m confirmed (email sent)
    #   EXPIRED            -> invalidated after max attempts
    status: str = "AWAITING_CANDIDATE"
    detection_time: datetime = None

    # Candidate tracking: 4th, 5th, and next 3 (6th–8th) => 5 attempts max
    candidate_index: int = 1     # 1 => 4th candle, 2 => 5th, ..., 5 => 8th
    max_candidates: int = 5

    # 5m confirmation window timestamps
    rf_window_start: datetime = None
    rf_window_deadline: datetime = None

    # Last 4H candle we evaluated to avoid duplicate checks
    last_checked_4h_close: datetime = None

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
    # New state fields
    status: str = "AWAITING_RETEST"  # AWAITING_RETEST, AWAITING_5M, CONFIRMED, EXPIRED
    candidate_index: int = 1         # 1..25 subsequent 4H candles
    max_candidates: int = 25
    rf_window_start: datetime = None
    rf_window_deadline: datetime = None
    last_checked_4h_close: datetime = None
    detection_time: datetime = None

    def __post_init__(self):
        if self.detection_time is None:
            self.detection_time = datetime.now()


@dataclass
class RJBSetup:  # Rejection Block Setup
    symbol: str
    direction: str  # "UP" or "DOWN"
    rjb_candle_time: datetime
    rjb_candle_high: float
    rjb_candle_low: float
    rjb_candle_body_high: float
    rjb_candle_body_low: float
    status: str = "PENDING_CONFIRMATION"
    detection_time: datetime = None

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
    # New state fields
    status: str = "AWAITING_RETEST"  # AWAITING_RETEST, AWAITING_5M, CONFIRMED, EXPIRED
    candidate_index: int = 1         # 1..25 subsequent 4H candles
    max_candidates: int = 25
    rf_window_start: datetime = None
    rf_window_deadline: datetime = None
    last_checked_4h_close: datetime = None
    detection_time: datetime = None

    def __post_init__(self):
        if self.detection_time is None:
            self.detection_time = datetime.now()


@dataclass
class TradingConfig:
    name: str = "DefaultConfig"
    capital: float = 1000.0
    risk_per_trade: float = 0.5
    symbols: List[str] = None
    trading_active: bool = False
    email_notifications: bool = True
    recipients: List[Dict] = None

    # Fixed percentage risk management
    sl_percentage: float = 0.5
    tp_percentage: float = 1.0

    # Enhanced indicator settings - ONLY THESE TWO
    use_super_ob_fvg: bool = True
    use_range_filter: bool = True

    fvg_tiny_body_tolerance_pct: float = 0.05
    ob_min_body_overlap_pct: float = 0.05

    # MT5 credentials
    account: int = 0
    password: str = ""
    server: str = ""

    def __post_init__(self):
        if self.symbols is None:
            self.symbols = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"]
        if self.recipients is None:
            self.recipients = []

    @classmethod
    def from_dict(cls, config_dict):
        valid_fields = {
            'name', 'symbols', 'recipients', 'capital', 'risk_per_trade',
            'trading_active', 'email_notifications', 'account', 'password', 'server',
            'use_super_ob_fvg', 'use_range_filter', 'sl_percentage', 'tp_percentage',
            'fvg_tiny_body_tolerance_pct', 'ob_min_body_overlap_pct'
        }
        filtered_config = {k: v for k, v in config_dict.items() if k in valid_fields}
        if 'use_super_ob_fvg' not in filtered_config:
            filtered_config['use_super_ob_fvg'] = True
        if 'use_range_filter' not in filtered_config:
            filtered_config['use_range_filter'] = True
        return cls(**filtered_config)


@dataclass
class BOSSetup:
    symbol: str
    direction: str
    bos_time: datetime
    pivot_high: float
    pivot_low: float
    status: str = "PENDING_CONFIRMATION"
    detection_time: datetime = None

    def __post_init__(self):
        if self.detection_time is None:
            self.detection_time = datetime.now()

# -----------------------
# Enhanced Trading Strategy with Both Indicators
# -----------------------
class AdvancedTradingStrategy:
    def __init__(self, tv_datafeed: TvDatafeed):
        self.tv = GlobalRateLimitedTvDatafeed(tv_datafeed)

    # =========================================================================
    # RANGE FILTER IMPLEMENTATION (From Pine Script)
    # =========================================================================
    def calculate_range_filter(self, df, period=100, mult=3.0):
        """Simplified Range Filter without chained assignment warnings"""
        try:
            # Create a copy to avoid warnings
            result_df = df.copy()

            # Calculate smooth range using vectorized operations
            result_df['rng'] = result_df['close'].diff().abs().ewm(span=period).mean()
            result_df['smoothrng'] = result_df['rng'].ewm(span=period * 2 - 1).mean() * mult

            # Initialize filter column
            result_df['filt'] = result_df['close']

            # Calculate filter using list comprehension (avoids chained assignment)
            filt_values = [result_df['close'].iloc[0]]  # Start with first value

            for i in range(1, len(result_df)):
                prev_filt = filt_values[-1]
                current_close = result_df['close'].iloc[i]
                current_smoothrng = result_df['smoothrng'].iloc[i]

                if current_close > prev_filt:
                    new_filt = prev_filt if (current_close - current_smoothrng) < prev_filt else (
                                current_close - current_smoothrng)
                else:
                    new_filt = prev_filt if (current_close + current_smoothrng) > prev_filt else (
                                current_close + current_smoothrng)

                filt_values.append(new_filt)

            # Assign the calculated values
            result_df['filt'] = filt_values

            # Calculate upward/downward using vectorized operations
            result_df['filt_diff'] = result_df['filt'].diff()
            result_df['upward'] = (result_df['filt_diff'] > 0).astype(int)
            result_df['downward'] = (result_df['filt_diff'] < 0).astype(int)

            # Calculate cumulative counts
            result_df['upward_cum'] = result_df['upward'].groupby((result_df['upward'] == 0).cumsum()).cumsum()
            result_df['downward_cum'] = result_df['downward'].groupby((result_df['downward'] == 0).cumsum()).cumsum()

            # Target bands
            result_df['hband'] = result_df['filt'] + result_df['smoothrng']
            result_df['lband'] = result_df['filt'] - result_df['smoothrng']

            # Breakout conditions
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

            # Clean up temporary columns
            result_df.drop(['rng', 'filt_diff', 'upward', 'downward'], axis=1, inplace=True)

            return result_df

        except Exception as e:
            logging.error(f"Error in simplified range filter calculation: {e}")
            return df

    def get_range_filter_signal(self, symbol, interval=Interval.in_5_minute):
        """Get Range Filter trading signal"""
        try:
            exchange = self.get_exchange(symbol)
            df = self.tv.get_hist(symbol=symbol, exchange=exchange,
                                  interval=interval, n_bars=200)

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
            logging.error(f"Error getting range filter signal for {symbol}: {e}")
            return "NO_SIGNAL"

    # =========================================================================
    # SUPER ORDERBLOCK/FVG/BOS IMPLEMENTATION (From Pine Script)
    # =========================================================================

    def detect_super_ob_setup(self, symbol):
        """Enhanced Order Block detection with multiple types"""
        try:
            df = self.get_4h_data(symbol, n_bars=20)
            if df is None or len(df) < 10:
                return None

            setups = []

            # Regular OB detection
            ob_setup = self.detect_ob_setup(symbol)
            if ob_setup:
                setups.append(ob_setup)

            # Rejection Block detection
            rjb_setup = self.detect_rjb_setup(symbol)
            if rjb_setup:
                setups.append(rjb_setup)

            # TEMPORARILY DISABLE BOS DETECTION
            # bos_setup = self.detect_bos_setup(symbol)
            # if bos_setup:
            #     setups.append(bos_setup)

            return setups if setups else None

        except Exception as e:
            logging.error(f"Error detecting super OB setup for {symbol}: {e}")
            return None

    def detect_rjb_setup(self, symbol):
        """Rejection Block detection based on Pine Script logic"""
        try:
            df = self.get_4h_data(symbol, n_bars=10)
            if df is None or len(df) < 3:
                return None

            # Bearish RJB conditions
            is_down_rjb_ob_condition = self._is_ob_down(df)

            if is_down_rjb_ob_condition:
                current = df.iloc[-1]
                previous = df.iloc[-2]
                two_bars_ago = df.iloc[-3]

                # RJB condition 1: on trapped's wick with <50% coverage
                is_down_rjb1 = (is_down_rjb_ob_condition and
                                (previous['high'] < (two_bars_ago['close'] + 0.2 * (
                                            two_bars_ago['high'] - two_bars_ago['close']))))

                # RJB condition 2: on signal's wick
                is_down_rjb2 = (is_down_rjb_ob_condition and
                                (previous['high'] > two_bars_ago['high']))

                if is_down_rjb1 or is_down_rjb2:
                    return RJBSetup(
                        symbol=symbol,
                        direction="DOWN",
                        rjb_candle_time=current.name,
                        rjb_candle_high=current['high'],
                        rjb_candle_low=current['low'],
                        rjb_candle_body_high=max(current['open'], current['close']),
                        rjb_candle_body_low=min(current['open'], current['close'])
                    )

            # Bullish RJB conditions
            is_up_rjb_ob_condition = self._is_ob_up(df)

            if is_up_rjb_ob_condition:
                current = df.iloc[-1]
                previous = df.iloc[-2]
                two_bars_ago = df.iloc[-3]

                # RJB condition 1: on trapped's wick with <50% coverage
                is_up_rjb1 = (is_up_rjb_ob_condition and
                              (previous['low'] > (
                                          two_bars_ago['close'] - 0.2 * (two_bars_ago['close'] - two_bars_ago['low']))))

                # RJB condition 2: on signal's wick
                is_up_rjb2 = (is_up_rjb_ob_condition and
                              (previous['low'] < two_bars_ago['low']))

                if is_up_rjb1 or is_up_rjb2:
                    return RJBSetup(
                        symbol=symbol,
                        direction="UP",
                        rjb_candle_time=current.name,
                        rjb_candle_high=current['high'],
                        rjb_candle_low=current['low'],
                        rjb_candle_body_high=max(current['open'], current['close']),
                        rjb_candle_body_low=min(current['open'], current['close'])
                    )

            return None

        except Exception as e:
            logging.error(f"Error detecting RJB setup for {symbol}: {e}")
            return None

    def detect_bos_setup(self, symbol, lookback=3):
        """Break of Structure detection - with enhanced error handling"""
        try:
            df = self.get_4h_data(symbol, n_bars=50)
            if df is None or len(df) < lookback * 2 + 1:
                return None

            # Find pivot points
            pivots_high, pivots_low = self._find_pivots(df, lookback=lookback)

            if not pivots_high or not pivots_low:
                return None

            current_price = df['close'].iloc[-1]
            last_pivot_high = max(pivots_high[-5:]) if len(pivots_high) >= 5 else max(pivots_high)
            last_pivot_low = min(pivots_low[-5:]) if len(pivots_low) >= 5 else min(pivots_low)

            # Bullish BOS: Break above pivot high
            if current_price > last_pivot_high:
                return BOSSetup(
                    symbol=symbol,
                    direction="UP",
                    bos_time=df.index[-1],
                    pivot_high=last_pivot_high,
                    pivot_low=last_pivot_low
                )

            # Bearish BOS: Break below pivot low
            elif current_price < last_pivot_low:
                return BOSSetup(
                    symbol=symbol,
                    direction="DOWN",
                    bos_time=df.index[-1],
                    pivot_high=last_pivot_high,
                    pivot_low=last_pivot_low
                )

            return None

        except Exception as e:
            logging.error(f"Error detecting BOS setup for {symbol}: {e}")
            return None  # Always return None on error

    def detect_enhanced_fvg_setup(self, symbol):
        """Enhanced FVG detection with structure-breaking FVGs"""
        try:
            df = self.get_4h_data(symbol, n_bars=20)
            if df is None or len(df) < 10:
                return None

            setups = []

            # Regular FVG
            fvg_setup = self.detect_fvg_setup(symbol)
            if fvg_setup:
                setups.append(fvg_setup)

            # Structure-breaking FVG
            structure_fvg = self.detect_structure_breaking_fvg(symbol)
            if structure_fvg:
                setups.append(structure_fvg)

            return setups if setups else None

        except Exception as e:
            logging.error(f"Error detecting enhanced FVG setup for {symbol}: {e}")
            return None

    # =========================================================================
    # EXISTING METHODS (Keep all your existing methods)
    # =========================================================================

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
        return self.get_range_filter_signal(symbol, Interval.in_5_minute)

    # Align FVG detection to your Pine (isFvgUp(0)/isFvgDown(0))
    # and anchor the "third candle" to the current 4H bar.

    # Align FVG detection to your Pine (isFvgUp(0)/isFvgDown(0))
    # and anchor the "third candle" to the current 4H bar.

    def detect_fvg_setup(self, symbol):
        try:
            df = self.get_4h_data(symbol, n_bars=10)
            if df is None or len(df) < 3:
                return None

            current = df.iloc[-1]  # bar 0 in Pine
            two_bars_ago = df.iloc[-3]  # bar 2 in Pine

            # Bullish FVG: low[0] > high[2]
            if current['low'] > two_bars_ago['high']:
                return FVGSetup(
                    symbol=symbol,
                    direction="UP",
                    third_candle_time=current.name,
                    third_candle_high=current['high'],
                    third_candle_low=current['low'],
                    third_candle_body_high=max(current['open'], current['close']),
                    third_candle_body_low=min(current['open'], current['close'])
                )

            # Bearish FVG: high[0] < low[2]
            if current['high'] < two_bars_ago['low']:
                return FVGSetup(
                    symbol=symbol,
                    direction="DOWN",
                    third_candle_time=current.name,
                    third_candle_high=current['high'],
                    third_candle_low=current['low'],
                    third_candle_body_high=max(current['open'], current['close']),
                    third_candle_body_low=min(current['open'], current['close'])
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
        """Structure-breaking FVG aligned with Pine pivots and FVG, anchoring 'third candle' to the current bar."""
        try:
            df = self.get_4h_data(symbol, n_bars=20)
            if df is None or len(df) < 10:
                return None

            pivots_high, pivots_low = self._find_pivots(df, lookback=3)
            if not pivots_high or not pivots_low:
                return None

            current = df.iloc[-1]  # bar 0
            previous = df.iloc[-2]  # bar 1
            two_bars_ago = df.iloc[-3]  # bar 2

            max_pivot_high = max(pivots_high)
            min_pivot_low = min(pivots_low)

            # Structure-Breaking FVG Up (same logic as your Pine gate)
            # Keep your original gating but anchor the 'third candle' to current for the setup.
            if (current['low'] > two_bars_ago['high'] and  # FVG Up condition low[0] > high[2]
                    previous['close'] > max_pivot_high and
                    previous['low'] < max_pivot_high and
                    two_bars_ago['high'] < max_pivot_high and
                    current['low'] > max_pivot_high):
                return FVGSetup(
                    symbol=symbol,
                    direction="UP",
                    third_candle_time=current.name,
                    third_candle_high=current['high'],
                    third_candle_low=current['low'],
                    third_candle_body_high=max(current['open'], current['close']),
                    third_candle_body_low=min(current['open'], current['close']),
                    status="STRUCTURE_BREAKING"
                )

            # Structure-Breaking FVG Down
            if (current['high'] < two_bars_ago['low'] and  # FVG Down condition high[0] < low[2]
                    previous['close'] < min_pivot_low and
                    previous['high'] > min_pivot_low and
                    two_bars_ago['low'] > min_pivot_low and
                    current['high'] < min_pivot_low):
                return FVGSetup(
                    symbol=symbol,
                    direction="DOWN",
                    third_candle_time=current.name,
                    third_candle_high=current['high'],
                    third_candle_low=current['low'],
                    third_candle_body_high=max(current['open'], current['close']),
                    third_candle_body_low=min(current['open'], current['close']),
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
# Enhanced Trading Engine with Both Indicators
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

        # Enhanced setup tracking
        self.active_fvg_setups = {}
        self.active_ob_setups = {}
        self.active_rjb_setups = {}
        self.active_bos_setups = {}
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
        """Load trade history from version-specific file - SILENT MODE"""
        try:
            if os.path.exists(TRADES_FILE):
                df = pd.read_csv(TRADES_FILE)
                # Silent mode - no logging unless there's an actual error
            # else: No file is normal - don't log anything
        except Exception as e:
            self.log(f"Error loading trade history from {TRADES_FILE}: {e}")

    def calculate_stop_loss_take_profit(self, symbol, price, order_type):
        """Use fixed percentage values from config"""
        try:
            # Get fixed percentages from config
            sl_percentage = self.config.sl_percentage / 100  # Convert to decimal
            tp_percentage = self.config.tp_percentage / 100  # Convert to decimal

            sl_distance = price * sl_percentage
            tp_distance = price * tp_percentage

            # Ensure minimum distance for forex pairs
            min_distance = price * 0.0001  # 1 pip for most pairs
            sl_distance = max(sl_distance, min_distance)
            tp_distance = max(tp_distance, min_distance * 2)

            self.log(
                f"Fixed SL/TP: SL={self.config.sl_percentage}% ({sl_distance:.5f}), TP={self.config.tp_percentage}% ({tp_distance:.5f})")

            return sl_distance, tp_distance

        except Exception as e:
            self.log(f"Error calculating SL/TP: {e}")
            # Fallback to default fixed values
            sl_distance = price * 0.005  # 0.5%
            tp_distance = price * 0.010  # 1.0%
            return sl_distance, tp_distance

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
        """Save trade to version-specific history file"""
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
                'setup_type': trade.setup_type,
                'version': 'tool5_v7',  # Add version info
                'config': self.config.name
            }

            df = pd.DataFrame([trade_dict])
            if not os.path.exists(TRADES_FILE):
                df.to_csv(TRADES_FILE, index=False)
                self.log(f"Created new trade history file: {TRADES_FILE}")
            else:
                df.to_csv(TRADES_FILE, mode='a', header=False, index=False)

            self.trade_history.append(trade)
            self.log(f"Trade saved to {TRADES_FILE}: {trade.symbol} {trade.trade_type}")

        except Exception as e:
            self.log(f"Error saving trade to {TRADES_FILE}: {e}")

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

    def _simulate_trade_execution(self, symbol, entry_price, signal, risk_per_trade, df_5min, equity, setup):
        """Use fixed percentage values from config"""
        try:
            # Get fixed percentages (same as live trading)
            sl_percentage = 0.005  # 0.5% fixed
            tp_percentage = 0.010  # 1.0% fixed

            sl_distance = entry_price * sl_percentage
            tp_distance = entry_price * tp_percentage

            if signal == "BUY":
                sl_price = entry_price - sl_distance
                tp_price = entry_price + tp_distance
            else:
                sl_price = entry_price + sl_distance
                tp_price = entry_price - tp_distance

            # Simulate trade outcome
            if len(df_5min) > 1:
                future_high = df_5min['high'].max()
                future_low = df_5min['low'].min()

                if signal == "BUY":
                    if future_high >= tp_price:
                        # Hit Take Profit
                        profit = tp_distance
                        exit_price = tp_price
                        outcome = "TP"
                    elif future_low <= sl_price:
                        # Hit Stop Loss
                        profit = -sl_distance
                        exit_price = sl_price
                        outcome = "SL"
                    else:
                        # No trigger, use last price
                        exit_price = df_5min['close'].iloc[-1]
                        profit = exit_price - entry_price
                        outcome = "CLOSE"
                else:  # SELL
                    if future_low <= tp_price:
                        # Hit Take Profit
                        profit = tp_distance
                        exit_price = tp_price
                        outcome = "TP"
                    elif future_high >= sl_price:
                        # Hit Stop Loss
                        profit = -sl_distance
                        exit_price = sl_price
                        outcome = "SL"
                    else:
                        # No trigger, use last price
                        exit_price = df_5min['close'].iloc[-1]
                        profit = entry_price - exit_price
                        outcome = "CLOSE"

                # Convert to monetary value based on risk percentage
                risk_amount = equity * risk_per_trade
                monetary_profit = profit * (risk_amount / sl_distance) if sl_distance > 0 else 0

                trade = {
                    'symbol': symbol,
                    'type': signal,
                    'entry_time': df_5min.index[0],
                    'entry_price': entry_price,
                    'exit_time': df_5min.index[-1],
                    'exit_price': exit_price,
                    'profit': monetary_profit,
                    'setup': setup['type'],
                    'direction': setup['direction'],
                    'outcome': outcome,
                    'sl_price': sl_price,
                    'tp_price': tp_price,
                    'risk_reward': tp_distance / sl_distance if sl_distance > 0 else 0
                }

                return trade

            return None

        except Exception as e:
            return None

    def calculate_position_size(self, symbol, stop_loss_distance):
        """Calculate position size based on 0.5% risk"""
        risk_amount = (self.config.risk_per_trade / 100) * self.config.capital
        pip_distance = self.mt5_trader.calculate_pip_distance(symbol, stop_loss_distance)
        volume = self.mt5_trader.calculate_volume(symbol, risk_amount, pip_distance)
        return volume

    def execute_trade(self, symbol, order_type, setup_type):
        """REAL TRADING MODE: Execute actual trades on MT5"""
        try:
            # Check if we can trade this symbol
            if not self.can_trade_symbol(symbol, setup_type):
                self.log(f"⏸ Skipping {order_type} for {symbol} - already traded recently")
                return

            # Get current price from MT5
            tick = mt5.symbol_info_tick(symbol)
            if not tick:
                self.log(f"❌ Cannot get tick data for {symbol}")
                return

            current_price = tick.ask if order_type == "BUY" else tick.bid

            # Calculate SL/TP
            stop_loss_distance, take_profit_distance = self.calculate_stop_loss_take_profit(
                symbol, current_price, order_type)

            # Calculate position size
            volume = self.calculate_position_size(symbol, stop_loss_distance)

            self.log(f"🎯 EXECUTING {order_type} for {symbol} ({setup_type}): "
                     f"Price={current_price:.5f}, SL Dist={stop_loss_distance:.5f}, "
                     f"TP Dist={take_profit_distance:.5f}, Volume={volume:.2f}")

            # Execute trade via MT5
            success = self.mt5_trader.place_order(
                symbol=symbol,
                order_type=order_type,
                volume=volume,
                stop_loss=stop_loss_distance,
                take_profit=take_profit_distance
            )

            if success:
                # Send execution alert
                self.send_email_alert(
                    f"TRADE EXECUTED - {symbol} {order_type}",
                    f"✅ LIVE TRADE EXECUTED:\n"
                    f"Config: {self.config.name}\n"
                    f"Symbol: {symbol}\n"
                    f"Type: {order_type}\n"
                    f"Setup: {setup_type}\n"
                    f"Entry Price: {current_price:.5f}\n"
                    f"Volume: {volume:.2f}\n"
                    f"Stop Loss: {current_price - stop_loss_distance if order_type == 'BUY' else current_price + stop_loss_distance:.5f}\n"
                    f"Take Profit: {current_price + take_profit_distance if order_type == 'BUY' else current_price - take_profit_distance:.5f}\n"
                    f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                    f"💰 REAL MONEY TRADE - Monitor positions carefully!"
                )

                # Track this trade
                self.open_trade_symbols.add(symbol)
                self.recently_traded[symbol] = datetime.now()

                # Create trade record for history
                trade = Trade(
                    symbol=symbol,
                    trade_type=order_type,
                    entry_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    entry_price=current_price,
                    volume=volume,
                    stop_loss=current_price - stop_loss_distance if order_type == "BUY" else current_price + stop_loss_distance,
                    take_profit=current_price + take_profit_distance if order_type == "BUY" else current_price - take_profit_distance,
                    setup_type=setup_type,
                    status="LIVE",  # Mark as live trade
                    reason=f"LIVE EXECUTION - {setup_type}"
                )

                self.save_trade(trade)
                self.log(f"✅ Trade executed successfully: {order_type} {symbol}")

            else:
                self.log(f"❌ Trade execution failed: {order_type} {symbol}")
                self.send_email_alert(
                    f"TRADE FAILED - {symbol} {order_type}",
                    f"❌ TRADE EXECUTION FAILED:\n"
                    f"Symbol: {symbol}\n"
                    f"Type: {order_type}\n"
                    f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"Please check MT5 connection and account status."
                )

        except Exception as e:
            self.log(f"❌ Error executing trade for {symbol}: {e}")

    # =========================================================================
    # ENHANCED SCANNING METHODS WITH BOTH INDICATORS
    # =========================================================================

    def scan_enhanced_setups(self):
        """Ultra-conservative scanning to avoid rate limits"""
        if not self.config.symbols:
            return

        # Only scan 1 symbol per cycle
        current_minute = datetime.now().minute
        symbol_index = current_minute % len(self.config.symbols)
        symbol = self.config.symbols[symbol_index]

        try:
            clean_symbol = symbol.split(":")[1] if ":" in symbol else symbol

            # Skip if already has active setups
            active_setup_count = (
                    (1 if clean_symbol in self.active_fvg_setups else 0) +
                    (1 if clean_symbol in self.active_ob_setups else 0) +
                    (1 if clean_symbol in self.active_rjb_setups else 0)
            )

            if active_setup_count >= 2:  # Even more conservative
                return

            # Scan for Super OB/FVG setups if enabled
            if self.config.use_super_ob_fvg:
                self.scan_super_ob_fvg_setups(clean_symbol)

            # Scan for Range Filter setups if enabled (less frequent)
            if self.config.use_range_filter and current_minute % 5 == 0:  # Only every 5 minutes
                self.scan_range_filter_setups(clean_symbol)

        except Exception as e:
            self.log(f"Error scanning enhanced setups for {symbol}: {e}")

    # When adding FVG setups, ensure we start at AWAITING_CANDIDATE and do NOT execute trades here.

    def scan_super_ob_fvg_setups(self, symbol):
        try:
            # FVG (unchanged from earlier patch): ...
            fvg_setups = self.strategy.detect_enhanced_fvg_setup(symbol)
            if fvg_setups:
                for fvg_setup in fvg_setups:
                    if not self.is_duplicate_setup(symbol, fvg_setup.direction, "FVG"):
                        self.record_setup(symbol, fvg_setup.direction, "FVG")
                        fvg_setup.status = "AWAITING_CANDIDATE"
                        fvg_setup.candidate_index = 1
                        fvg_setup.rf_window_start = None
                        fvg_setup.rf_window_deadline = None
                        self.active_fvg_setups[symbol] = fvg_setup
                        setup_type = "STRUCTURE_BREAKING" if getattr(fvg_setup, "status",
                                                                     "") == "STRUCTURE_BREAKING" else "REGULAR"
                        self.log(f"🎯 FVG {fvg_setup.direction} {setup_type} setup detected for {symbol}")

            # OB detection: initialize OB state for 25-candle workflow
            ob_setups = self.strategy.detect_super_ob_setup(symbol)
            if ob_setups:
                for setup in ob_setups:
                    if isinstance(setup, OBSetup):
                        if not self.is_duplicate_setup(symbol, setup.direction, "OB"):
                            self.record_setup(symbol, setup.direction, "OB")
                            # Initialize OB state
                            setup.status = "AWAITING_RETEST"
                            setup.candidate_index = 1
                            setup.rf_window_start = None
                            setup.rf_window_deadline = None
                            self.active_ob_setups[symbol] = setup
                            self.log(f"🎯 OB {setup.direction} setup detected for {symbol}")
                    elif isinstance(setup, RJBSetup):
                        if not self.is_duplicate_setup(symbol, setup.direction, "RJB"):
                            self.record_setup(symbol, setup.direction, "RJB")
                            self.active_rjb_setups[symbol] = setup
                            self.log(f"🎯 RJB {setup.direction} setup detected for {symbol}")
                    elif isinstance(setup, BOSSetup):
                        if not self.is_duplicate_setup(symbol, setup.direction, "BOS"):
                            self.record_setup(symbol, setup.direction, "BOS")
                            self.active_bos_setups[symbol] = setup
                            self.log(f"🎯 BOS {setup.direction} setup detected for {symbol}")
        except Exception as e:
            self.log(f"Error scanning super OB/FVG for {symbol}: {e}")

    def _get_ob_candidate_candle(self, setup: OBSetup):
        """
        Return the Nth closed 4H candle after the OB anchor, where N=candidate_index.
        """
        df4h = self.strategy.get_4h_data(setup.symbol, n_bars=60)
        if df4h is None or df4h.empty:
            return None, None

        after = df4h[df4h.index > setup.ob_candle_time]
        if len(after) >= setup.candidate_index:
            candidate = after.iloc[setup.candidate_index - 1]
            candidate_time = after.index[setup.candidate_index - 1]
            if setup.last_checked_4h_close is None or candidate_time > setup.last_checked_4h_close:
                return candidate, candidate_time
        return None, None

    def _ob_retest_condition(self, setup: OBSetup, candidate_candle) -> bool:
        """
        OB Down retest (bearish):
          - wick must rise above OB high (candidate.high > ob_candle_high)
          - some of the body must be above OB high by at least a small tolerance
        OB Up retest (bullish):
          - wick must dip below OB low (candidate.low < ob_candle_low)
          - some of the body must be below OB low by at least a small tolerance
        Tolerance = config.ob_min_body_overlap_pct % of reference price.
        """
        tol_pct = getattr(self.config, 'ob_min_body_overlap_pct', 0.05)
        # Use OB reference as price scale
        ref_price = max(1e-9, (setup.ob_candle_high + setup.ob_candle_low) / 2.0)
        tol_val = (tol_pct / 100.0) * ref_price

        body_top = max(candidate_candle['open'], candidate_candle['close'])
        body_bot = min(candidate_candle['open'], candidate_candle['close'])

        if setup.direction == "DOWN":
            wick_ok = candidate_candle['high'] > setup.ob_candle_high
            body_overlap = max(0.0, body_top - max(setup.ob_candle_high, body_bot))
            body_ok = body_overlap >= tol_val
            return wick_ok and body_ok
        else:  # UP
            wick_ok = candidate_candle['low'] < setup.ob_candle_low
            body_overlap = max(0.0, min(setup.ob_candle_low, body_top) - body_bot)
            # body_overlap below OB low: measure how much body is under ob_low
            # A simpler symmetric form:
            body_overlap = max(0.0, max(0.0, setup.ob_candle_low - body_bot) - max(0.0, setup.ob_candle_low - body_top))
            # But keep prior calculation if you prefer:
            body_ok = (min(body_top, setup.ob_candle_low) - body_bot) >= tol_val
            return wick_ok and body_ok


    # Patch: make the wick-only check honor a configurable tiny-body tolerance (percent of price).
    # Also reuse it in DOWN/UP mirroring.

    def _fvg_wick_condition(self, setup: FVGSetup, candidate_candle) -> bool:
        """
        Returns True if candidate satisfies the wick-only (or tiny-body) retest relative to the 3rd candle.
        DOWN:
          - wick must exceed above the 3rd candle's wick high (candidate.high > third_candle_high)
          - body must not close above third_candle_body_high + tolerance
        UP:
          - wick must dip below third_candle_low (candidate.low < third_candle_low)
          - body must not close below third_candle_body_low - tolerance
        Tolerance = config.fvg_tiny_body_tolerance_pct % of price (defaults 0.05%).
        """
        # Pull tolerance from config; default to 0.05% if not present
        tol_pct = getattr(self.config, 'fvg_tiny_body_tolerance_pct', 0.05)
        tol_val = (tol_pct / 100.0) * max(1e-9, setup.third_candle_high)  # scale vs price

        if setup.direction == "DOWN":
            wick_ok = candidate_candle['high'] > setup.third_candle_high
            body_ok = candidate_candle['close'] <= setup.third_candle_body_high + tol_val
            return wick_ok and body_ok
        else:  # UP
            wick_ok = candidate_candle['low'] < setup.third_candle_low
            body_ok = candidate_candle['close'] >= setup.third_candle_body_low - tol_val
            return wick_ok and body_ok

    def _get_fvg_candidate_candle(self, setup: FVGSetup):
        """
        Locate the Nth closed 4H candle after the third_candle_time, where N = candidate_index (1..5).
        Returns (candidate_candle_row, candidate_time) or (None, None) if not yet closed.
        """
        df4h = self.strategy.get_4h_data(setup.symbol, n_bars=50)
        if df4h is None or df4h.empty:
            return None, None

        # candles strictly after the 3rd candle
        after = df4h[df4h.index > setup.third_candle_time]
        if len(after) >= setup.candidate_index:
            candidate = after.iloc[setup.candidate_index - 1]
            candidate_time = after.index[setup.candidate_index - 1]
            # Ensure we only evaluate once
            if setup.last_checked_4h_close is None or candidate_time > setup.last_checked_4h_close:
                return candidate, candidate_time
        return None, None

    def scan_range_filter_setups(self, symbol):
        """Scan for Range Filter setups"""
        try:
            # Get range filter signal
            signal = self.strategy.get_range_filter_signal(symbol)

            if signal != "NO_SIGNAL":
                # Check if this is a new signal
                range_key = f"{symbol}_RANGE_{signal}"
                if not self.is_duplicate_setup(symbol, signal, "RANGE"):
                    self.record_setup(symbol, signal, "RANGE")
                    self.log(f"🎯 Range Filter {signal} signal for {symbol}")

                    # Execute immediately for range filter signals
                    if self.can_trade_symbol(symbol, "RANGE_FILTER"):
                        self.execute_trade(symbol, signal, "RANGE_FILTER")

        except Exception as e:
            self.log(f"Error scanning range filter for {symbol}: {e}")

    def monitor_enhanced_setups(self):
        """Monitor all enhanced setups"""
        self.monitor_fvg_setups()
        self.monitor_ob_setups()
        self.monitor_rjb_setups()
        self.monitor_bos_setups()

    def monitor_rjb_setups(self):
        """Monitor Rejection Block setups"""
        current_time = datetime.now()
        expired_setups = []

        for symbol, setup in list(self.active_rjb_setups.items()):
            try:
                # RJB setups are short-lived - monitor for 5M confirmation
                if (current_time - setup.detection_time).total_seconds() > 3600:  # 1 hour expiry
                    self.log(f"⏰ RJB {setup.direction} setup expired for {symbol}")
                    expired_setups.append(symbol)
                    continue

                # Check 5-minute confirmation
                signal = self.strategy.get_5min_signal(symbol)
                target_signal = "SELL" if setup.direction == "DOWN" else "BUY"

                if signal == target_signal:
                    self.log(f"✅ RJB {setup.direction} confirmed by 5M signal for {symbol}")
                    self.execute_trade(symbol, target_signal, f"RJB_{setup.direction}")
                    expired_setups.append(symbol)

            except Exception as e:
                self.log(f"Error monitoring RJB setup for {symbol}: {e}")

        # Clean up expired setups
        for symbol in expired_setups:
            if symbol in self.active_rjb_setups:
                del self.active_rjb_setups[symbol]

    def monitor_bos_setups(self):
        """Monitor Break of Structure setups"""
        current_time = datetime.now()
        expired_setups = []

        for symbol, setup in list(self.active_bos_setups.items()):
            try:
                # BOS setups are longer-lived - monitor for 4 hours
                if (current_time - setup.detection_time).total_seconds() > 4 * 3600:  # 4 hours expiry
                    self.log(f"⏰ BOS {setup.direction} setup expired for {symbol}")
                    expired_setups.append(symbol)
                    continue

                # Check 5-minute confirmation
                signal = self.strategy.get_5min_signal(symbol)
                target_signal = "SELL" if setup.direction == "DOWN" else "BUY"

                if signal == target_signal:
                    self.log(f"✅ BOS {setup.direction} confirmed by 5M signal for {symbol}")
                    self.execute_trade(symbol, target_signal, f"BOS_{setup.direction}")
                    expired_setups.append(symbol)

            except Exception as e:
                self.log(f"Error monitoring BOS setup for {symbol}: {e}")

        # Clean up expired setups
        for symbol in expired_setups:
            if symbol in self.active_bos_setups:
                del self.active_bos_setups[symbol]

    # =========================================================================
    # EXISTING METHODS (Keep all your existing monitoring methods)
    # =========================================================================

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

    # Patch: send an early alert when the wick-only condition is met and the 5m window starts,
    # and keep the confirmation alert when 5m signal matches within the 4-hour window.

    def monitor_fvg_setups(self):
        current_time = datetime.now()
        to_remove = []

        for symbol, setup in list(self.active_fvg_setups.items()):
            try:
                if setup.status == "AWAITING_CANDIDATE":
                    candidate, candidate_time = self._get_fvg_candidate_candle(setup)
                    if candidate is None:
                        continue

                    setup.last_checked_4h_close = candidate_time

                    if self._fvg_wick_condition(setup, candidate):
                        # Start 5m confirmation window (4 hours)
                        setup.status = "AWAITING_5M"
                        setup.rf_window_start = current_time
                        setup.rf_window_deadline = current_time + timedelta(hours=4)

                        # EARLY ALERT (before 5m confirmation)
                        self.send_email_alert(
                            f"FVG {setup.direction} Wick-only Detected - {symbol}",
                            f"🔔 FVG {setup.direction} wick-only condition met on {symbol}\n"
                            f"Config: {self.config.name}\n"
                            f"Third candle: {setup.third_candle_time}\n"
                            f"4H candidate time: {candidate_time}\n"
                            f"5m window started: {setup.rf_window_start} until {setup.rf_window_deadline}\n"
                            f"Next step: Watching 5m Range Filter for confirmation."
                        )
                        self.log(
                            f"📬 Early alert sent: FVG {setup.direction} {symbol} wick-only met; 5m window started.")
                    else:
                        setup.candidate_index += 1
                        if setup.candidate_index > setup.max_candidates:
                            setup.status = "EXPIRED"
                            self.log(f"⏰ FVG {setup.direction} on {symbol} expired (no valid wick-only in 4th–8th).")
                            to_remove.append(symbol)
                        else:
                            self.log(
                                f"⏭️ FVG {setup.direction} on {symbol}: moving to 4H candidate #{setup.candidate_index}.")

                elif setup.status == "AWAITING_5M":
                    if current_time >= setup.rf_window_deadline:
                        setup.status = "AWAITING_CANDIDATE"
                        setup.candidate_index += 1
                        setup.rf_window_start = None
                        setup.rf_window_deadline = None
                        if setup.candidate_index > setup.max_candidates:
                            setup.status = "EXPIRED"
                            self.log(
                                f"⏰ FVG {setup.direction} on {symbol} expired after 5m window; no more candidates.")
                            to_remove.append(symbol)
                        else:
                            self.log(
                                f"🔄 FVG {setup.direction} on {symbol}: 5m window ended. Waiting for next 4H candidate #{setup.candidate_index}.")
                        continue

                    signal = self.strategy.get_5min_signal(symbol)
                    target_signal = "SELL" if setup.direction == "DOWN" else "BUY"

                    if signal == target_signal:
                        setup.status = "CONFIRMED"
                        # CONFIRMATION ALERT
                        self.send_email_alert(
                            f"FVG {setup.direction} CONFIRMED (5m) - {symbol}",
                            f"✅ FVG {setup.direction} confirmed on 5m for {symbol}\n"
                            f"Config: {self.config.name}\n"
                            f"Third candle: {setup.third_candle_time}\n"
                            f"Confirmed at: {current_time}\n"
                            f"Action: ALERT ONLY (no execution)"
                        )
                        self.log(
                            f"✅ FVG {setup.direction} on {symbol}: 5m Range Filter confirmed ({target_signal}). Confirmation alert sent.")
                        to_remove.append(symbol)

                elif setup.status in ("CONFIRMED", "EXPIRED"):
                    to_remove.append(symbol)

            except Exception as e:
                self.log(f"Error monitoring FVG setup for {symbol}: {e}")

        for symbol in to_remove:
            self.active_fvg_setups.pop(symbol, None)

    # OB state machine with 25-candle candidate window, early alert on retest, 4-hour 5m confirmation.

    def monitor_ob_setups(self):
        current_time = datetime.now()
        to_remove = []

        for symbol, setup in list(self.active_ob_setups.items()):
            try:
                if setup.status == "AWAITING_RETEST":
                    candidate, candidate_time = self._get_ob_candidate_candle(setup)
                    if candidate is None:
                        continue

                    setup.last_checked_4h_close = candidate_time

                    if self._ob_retest_condition(setup, candidate):
                        # Start 5m confirmation window (4 hours)
                        setup.status = "AWAITING_5M"
                        setup.rf_window_start = current_time
                        setup.rf_window_deadline = current_time + timedelta(hours=4)

                        # EARLY ALERT (before 5m confirmation)
                        self.send_email_alert(
                            f"OB {setup.direction} Retest Detected - {symbol}",
                            f"🔔 OB {setup.direction} retest condition met on {symbol}\n"
                            f"Config: {self.config.name}\n"
                            f"OB candle time: {setup.ob_candle_time}\n"
                            f"4H candidate time: {candidate_time}\n"
                            f"5m window: {setup.rf_window_start} → {setup.rf_window_deadline}\n"
                            f"Next step: Watching 5m Range Filter for confirmation."
                        )
                        self.log(f"📬 Early alert sent: OB {setup.direction} {symbol} retest met; 5m window started.")
                    else:
                        setup.candidate_index += 1
                        if setup.candidate_index > setup.max_candidates:
                            setup.status = "EXPIRED"
                            self.log(f"⏰ OB {setup.direction} on {symbol} expired (25 candidates exhausted).")
                            to_remove.append(symbol)
                        else:
                            self.log(
                                f"⏭️ OB {setup.direction} on {symbol}: moving to 4H candidate #{setup.candidate_index}.")

                elif setup.status == "AWAITING_5M":
                    if current_time >= setup.rf_window_deadline:
                        # 5m window expired; go back to 4H and next candidate
                        setup.status = "AWAITING_RETEST"
                        setup.candidate_index += 1
                        setup.rf_window_start = None
                        setup.rf_window_deadline = None
                        if setup.candidate_index > setup.max_candidates:
                            setup.status = "EXPIRED"
                            self.log(f"⏰ OB {setup.direction} on {symbol} expired after 5m window; no more candidates.")
                            to_remove.append(symbol)
                        else:
                            self.log(
                                f"🔄 OB {setup.direction} on {symbol}: 5m window ended. Waiting for next 4H candidate #{setup.candidate_index}.")
                        continue

                    # Evaluate 5m signal
                    signal = self.strategy.get_5min_signal(symbol)
                    target_signal = "SELL" if setup.direction == "DOWN" else "BUY"

                    if signal == target_signal:
                        setup.status = "CONFIRMED"
                        # CONFIRMATION ALERT
                        self.send_email_alert(
                            f"OB {setup.direction} CONFIRMED (5m) - {symbol}",
                            f"✅ OB {setup.direction} confirmed on 5m for {symbol}\n"
                            f"Config: {self.config.name}\n"
                            f"OB candle time: {setup.ob_candle_time}\n"
                            f"Confirmed at: {current_time}\n"
                            f"Action: ALERT ONLY (no execution)"
                        )
                        self.log(
                            f"✅ OB {setup.direction} on {symbol}: 5m confirmed ({target_signal}). Confirmation alert sent.")
                        to_remove.append(symbol)

                elif setup.status in ("CONFIRMED", "EXPIRED"):
                    to_remove.append(symbol)

            except Exception as e:
                self.log(f"Error monitoring OB setup for {symbol}: {e}")

        for symbol in to_remove:
            self.active_ob_setups.pop(symbol, None)

    def run_strategy_cycle(self):
        """Enhanced strategy cycle with both indicators"""
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

            # Enhanced scanning with both indicators
            self.scan_enhanced_setups()

            # Monitor all active setups
            self.monitor_enhanced_setups()

        except Exception as e:
            self.log(f"Error in enhanced strategy cycle: {e}")

    def start_trading(self):
        """Start trading (change from stopped state)"""
        if not self.mt5_trader.connect():
            self.log("Failed to connect to MT5")
            return False

        self.running = True
        self.config.trading_active = True
        self.log(f"✅ Trading STARTED for config: {self.config.name}")
        self.log(f"📊 Using Super OB/FVG: {self.config.use_super_ob_fvg}")
        self.log(f"📊 Using Range Filter: {self.config.use_range_filter}")
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
        pass


# =============================================================================
# KEEP ALL REMAINING CLASSES THE SAME (MT5Trader, ParametersWindow, AdvancedTradingApp)
# =============================================================================

# [Keep all the remaining classes exactly as they were: MT5Trader, ParametersWindow, AdvancedTradingApp]
# The rest of your code remains unchanged...

# -----------------------
# MT5 Trader (Unchanged)
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
                self.log(f"❌ Symbol {symbol} not found")
                return False

            price_info = mt5.symbol_info_tick(symbol)
            if not price_info:
                self.log(f"❌ Cannot get price for {symbol}")
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
                logging.error(f"❌ Order failed: {result.retcode} - {result.comment}")
                return False

            logging.info(f"✅ Order placed successfully: {order_type} {symbol}")
            return True

        except Exception as e:
            logging.error(f"❌ Error placing order: {e}")
            return False

"""            symbol_info = self.get_symbol_info(symbol)
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
"""


# -----------------------
# Enhanced Parameters Window with New Settings
# -----------------------
class ParametersWindow(ctk.CTkToplevel):
    def __init__(self, parent, configs, users, workers, email_sender, main_app):
        super().__init__(parent)
        self.title("Trading Parameters & Configuration - tool5_v6")  # Add version
        self.geometry("1200x800")
        self.minsize(1000, 600)

        # Make window modal
        self.transient(parent)
        self.grab_set()

        self.configs = configs
        self.users = users
        self.workers = workers
        self.email_sender = email_sender
        self.main_app = main_app

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

        # Enhanced Indicators tab
        indicators_tab = ctk.CTkFrame(notebook, corner_radius=8)
        notebook.add(indicators_tab, text="📊 Enhanced Indicators")
        self.setup_indicators_tab(indicators_tab)

        # Risk Management tab
        risk_tab = ctk.CTkFrame(notebook, corner_radius=8)
        notebook.add(risk_tab, text="🎯 Risk Management")
        self.setup_risk_tab(risk_tab)

    def setup_indicators_tab(self, parent):
        """Setup simplified indicators configuration tab - ONLY TWO INDICATORS"""
        main_frame = ctk.CTkFrame(parent)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)
        main_frame.grid_columnconfigure(0, weight=1)

        # Title
        ctk.CTkLabel(main_frame, text="Trading Indicators Configuration",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(pady=10)

        # Info frame
        info_frame = ctk.CTkFrame(main_frame, fg_color="#2b2b2b")
        info_frame.pack(fill="x", padx=20, pady=10)

        info_text = """
    🎯 ACTIVE TRADING INDICATORS:

    • Super OrderBlock/FVG Tools: Advanced order block and fair value gap detection
    • Range Filter (5min): 5-minute timeframe confirmation signals

    Other indicators (RJB, BOS, Structure Breaking) have been removed
    to focus on the core strategy.
        """
        ctk.CTkLabel(info_frame, text=info_text, justify="left").pack(padx=10, pady=10)

        # Indicator settings frame - ONLY TWO INDICATORS
        settings_frame = ctk.CTkFrame(main_frame)
        settings_frame.pack(fill="x", padx=20, pady=10)

        # Super OB/FVG Settings
        ob_fvg_frame = ctk.CTkFrame(settings_frame)
        ob_fvg_frame.pack(fill="x", pady=10)

        self.use_super_ob_fvg = ctk.CTkCheckBox(ob_fvg_frame,
                                                text="Super OrderBlock/FVG Tools",
                                                font=ctk.CTkFont(weight="bold"))
        self.use_super_ob_fvg.pack(side="left", padx=10, pady=5)

        # Range Filter Settings
        range_frame = ctk.CTkFrame(settings_frame)
        range_frame.pack(fill="x", pady=10)

        self.use_range_filter = ctk.CTkCheckBox(range_frame,
                                                text="Range Filter (5min)",
                                                font=ctk.CTkFont(weight="bold"))
        self.use_range_filter.pack(side="left", padx=10, pady=5)

        # Load current settings
        self.load_indicator_settings()

        # Save button
        ctk.CTkButton(settings_frame, text="Save Indicator Settings",
                      command=self.save_indicator_settings,
                      fg_color="#2E8B57", hover_color="#3CB371").pack(pady=20)

    def load_indicator_settings(self):
        """Load current indicator settings - ONLY TWO INDICATORS"""
        if self.workers:
            first_worker = list(self.workers.values())[0]
            config = first_worker.config

            # Only set the two main indicators
            self.use_super_ob_fvg.select() if config.use_super_ob_fvg else self.use_super_ob_fvg.deselect()
            self.use_range_filter.select() if config.use_range_filter else self.use_range_filter.deselect()

    def save_indicator_settings(self):
        """Save indicator settings to all workers - ONLY TWO INDICATORS"""
        try:
            for worker in self.workers.values():
                worker.config.use_super_ob_fvg = self.use_super_ob_fvg.get()
                worker.config.use_range_filter = self.use_range_filter.get()

            messagebox.showinfo("Success", "Indicator settings updated for all configurations!")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to save indicator settings: {e}")


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
        """Setup risk management tab with fixed percentage SL/TP"""
        main_frame = ctk.CTkFrame(parent)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)
        main_frame.grid_columnconfigure(0, weight=1)

        # Title
        ctk.CTkLabel(main_frame, text="Fixed Risk Management Settings",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(pady=10)

        # Fixed Percentage Settings Frame
        fixed_frame = ctk.CTkFrame(main_frame)
        fixed_frame.pack(fill="x", padx=20, pady=10)

        # Stop Loss Percentage
        sl_frame = ctk.CTkFrame(fixed_frame)
        sl_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(sl_frame, text="Stop Loss (%):", font=ctk.CTkFont(weight="bold")).pack(side="left")
        self.sl_percentage = ctk.CTkEntry(sl_frame, placeholder_text="0.5")
        self.sl_percentage.insert(0, "0.5")
        self.sl_percentage.pack(side="right", fill="x", padx=10)

        # Take Profit Percentage
        tp_frame = ctk.CTkFrame(fixed_frame)
        tp_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(tp_frame, text="Take Profit (%):", font=ctk.CTkFont(weight="bold")).pack(side="left")
        self.tp_percentage = ctk.CTkEntry(tp_frame, placeholder_text="1.0")
        self.tp_percentage.insert(0, "1.0")
        self.tp_percentage.pack(side="right", fill="x", padx=10)

        # Risk per trade
        risk_frame = ctk.CTkFrame(fixed_frame)
        risk_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(risk_frame, text="Risk Per Trade (%):", font=ctk.CTkFont(weight="bold")).pack(side="left")
        self.risk_entry = ctk.CTkEntry(risk_frame, placeholder_text="0.5")
        self.risk_entry.insert(0, "0.5")
        self.risk_entry.pack(side="right", fill="x", padx=10)

        # Capital
        capital_frame = ctk.CTkFrame(fixed_frame)
        capital_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(capital_frame, text="Trading Capital ($):", font=ctk.CTkFont(weight="bold")).pack(side="left")
        self.capital_entry = ctk.CTkEntry(capital_frame, placeholder_text="1000")
        self.capital_entry.insert(0, "1000")
        self.capital_entry.pack(side="right", fill="x", padx=10)

        # Info frame
        info_frame = ctk.CTkFrame(main_frame, fg_color="#2b2b2b")
        info_frame.pack(fill="x", padx=20, pady=10)

        info_text = """
    🔒 FIXED PERCENTAGE RISK MANAGEMENT:

    • Stop Loss: 0.5% fixed from entry price
    • Take Profit: 1.0% fixed from entry price  
    • Risk/Reward Ratio: 1:2
    • No time-based calculations
    • Consistent across all trades
        """
        ctk.CTkLabel(info_frame, text=info_text, justify="left").pack(padx=10, pady=10)

        # Save risk settings
        ctk.CTkButton(main_frame, text="Save Fixed Risk Settings",
                      command=self.save_fixed_risk_settings,
                      fg_color="#2E8B57", hover_color="#3CB371").pack(pady=20)

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

    def save_fixed_risk_settings(self):
        """Save fixed percentage risk management settings"""
        try:
            capital = float(self.capital_entry.get() or "1000")
            risk_per_trade = float(self.risk_entry.get() or "0.5")
            sl_percentage = float(self.sl_percentage.get() or "0.5")
            tp_percentage = float(self.tp_percentage.get() or "1.0")

            # Validate inputs
            if sl_percentage <= 0 or tp_percentage <= 0 or risk_per_trade <= 0:
                messagebox.showerror("Error", "Percentages must be positive numbers")
                return

            # Update all workers with new fixed settings
            for worker_name, worker in self.workers.items():
                worker.config.capital = capital
                worker.config.risk_per_trade = risk_per_trade
                # Store fixed percentages in config for reference
                worker.config.sl_percentage = sl_percentage
                worker.config.tp_percentage = tp_percentage

            messagebox.showinfo("Success",
                                f"✅ Fixed Risk Settings Updated!\n"
                                f"• Capital: ${capital:.2f}\n"
                                f"• Risk per trade: {risk_per_trade}%\n"
                                f"• Stop Loss: {sl_percentage}%\n"
                                f"• Take Profit: {tp_percentage}%\n"
                                f"• Risk/Reward: 1:{tp_percentage / sl_percentage:.1f}")

        except ValueError as e:
            messagebox.showerror("Error", "Please enter valid numbers for all fields")

    def save_risk_settings(self):
        """Legacy method - redirect to fixed risk settings"""
        self.save_fixed_risk_settings()


# -----------------------
# Enhanced GUI Application
# -----------------------
class AdvancedTradingApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Advanced MT5 Trading Bot - tool5_v7 (SIMULATION MODE)")  # Updated version
        self.geometry("1400x900")
        self.minsize(1200, 800)

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

        # Move cleanup to AFTER UI initialization
        self.cleanup_old_configs()
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

        # Left panel - Enhanced Controls
        control_frame = ctk.CTkFrame(main_frame, width=350, corner_radius=10)
        control_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        control_frame.grid_propagate(False)

        # Right panel - Logs and Info
        info_frame = ctk.CTkFrame(main_frame, corner_radius=10)
        info_frame.grid(row=0, column=1, sticky="nsew")
        info_frame.grid_columnconfigure(0, weight=1)
        info_frame.grid_rowconfigure(1, weight=1)

        self.setup_enhanced_control_panel(control_frame)
        self.setup_info_panel(info_frame)

    def open_backtest_window(self):
        """Open backtest window"""
        BacktestWindow(self, self.configs, self.workers)

    def setup_enhanced_control_panel(self, parent):
        """Setup enhanced control panel with indicator status"""
        # Configure parent grid
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(3, weight=1)

        # Title
        title_label = ctk.CTkLabel(parent, text="Enhanced Trading Bot",
                                   font=ctk.CTkFont(size=20, weight="bold"))
        title_label.grid(row=0, column=0, pady=(20, 10), padx=20, sticky="ew")

        # In setup_enhanced_control_panel method, update the risk management section:
        strategy_info = """
        🤖 SIMULATION MODE ACTIVATED:

        🔹 TRADE EXECUTION:
        • 🚫 ACTUAL TRADING: DISABLED
        • 📧 EMAIL ALERTS: ENABLED  
        • 💾 HISTORY SAVING: ENABLED

        🔹 STRATEGIES:
        • Super OB/FVG Tools
        • Range Filter (5min)

        🔹 FIXED RISK MANAGEMENT:
        • Stop Loss: 0.5% fixed
        • Take Profit: 1.0% fixed
        • Risk/Reward: 1:2 ratio
        """
        info_frame = ctk.CTkFrame(parent, fg_color="#2b2b2b", corner_radius=8)
        info_frame.grid(row=1, column=0, sticky="ew", padx=15, pady=10)

        info_label = ctk.CTkLabel(info_frame, text=strategy_info, justify="left",
                                  font=ctk.CTkFont(size=11))
        info_label.pack(padx=10, pady=10)

        # Enhanced active setups display
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

        # Enhanced indicators button
        ctk.CTkButton(button_frame, text="⚙️ INDICATOR SETTINGS",
                      command=self.open_parameters,
                      height=35).pack(fill="x", pady=(10, 0))

    def create_menu_bar(self):
        """Create menu bar"""
        menu_bar = tk.Menu(self)
        self.config(menu=menu_bar)

        # Parameters menu
        params_menu = tk.Menu(menu_bar, tearoff=0)
        menu_bar.add_cascade(label="Parameters", menu=params_menu)
        params_menu.add_command(label="Open Parameters", command=self.open_parameters)

        # NEW: Backtest menu
        backtest_menu = tk.Menu(menu_bar, tearoff=0)
        menu_bar.add_cascade(label="Backtest", menu=backtest_menu)
        backtest_menu.add_command(label="Run Backtest", command=self.open_backtest_window)

    def cleanup_old_configs(self):
        """Remove old indicator fields from config file"""
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r') as f:
                    configs = json.load(f)

                # Clean each config
                cleaned_count = 0
                for config_name, config_data in configs.items():
                    old_fields = ['use_rjb', 'use_bos', 'use_structure_breaking']
                    for field in old_fields:
                        if field in config_data:
                            del config_data[field]
                            cleaned_count += 1

                # Save cleaned configs if changes were made
                if cleaned_count > 0:
                    save_json(CONFIG_FILE, configs)
                    # Use print instead of log_message during initialization
                    print(f"✅ Cleaned {cleaned_count} old indicator fields from config file")

        except Exception as e:
            # Use print during initialization instead of log_message
            print(f"Warning: Could not clean config file: {e}")

    def open_parameters(self):
        """Open parameters window"""
        ParametersWindow(self, self.configs, self.users, self.workers, self.email_sender, self)

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
                                                  bg="#1a1a1a", fg="#00ff00",
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

    def start_all_trading(self):
        """Start all trading workers"""
        for worker_name, worker in self.workers.items():
            if worker.start_trading():
                self.log_message(f"✅ STARTED: {worker_name}")
                self.log_message(f"   Super OB/FVG: {worker.config.use_super_ob_fvg}")
                self.log_message(f"   Range Filter: {worker.config.use_range_filter}")
                # Removed: worker.config.use_rjb and worker.config.use_bos (no such fields)

        self.status_label.configure(text="🟢 SYSTEM RUNNING", text_color="green")
        self.log_message("=== ENHANCED TRADING SYSTEM STARTED ===")

    def update_setups_display(self):
        """Update enhanced active setups display"""
        try:
            self.setups_text.configure(state="normal")
            self.setups_text.delete("1.0", "end")

            all_setups = []

            for worker_name, worker in self.workers.items():
                if hasattr(worker, 'active_fvg_setups'):
                    for symbol, setup in worker.active_fvg_setups.items():
                        setup_type = "STRUCTURE_BREAKING" if getattr(setup, "status", "") == "STRUCTURE_BREAKING" else "REGULAR"
                        all_setups.append(f"FVG {setup.direction} - {symbol} ({setup_type})")

                if hasattr(worker, 'active_ob_setups'):
                    for symbol, setup in worker.active_ob_setups.items():
                        # Show OB candidate progress (1..25)
                        all_setups.append(f"OB {setup.direction} - {symbol} (candidate {setup.candidate_index}/{setup.max_candidates})")

                if hasattr(worker, 'active_rjb_setups'):
                    for symbol, setup in worker.active_rjb_setups.items():
                        all_setups.append(f"RJB {setup.direction} - {symbol}")

                if hasattr(worker, 'active_bos_setups'):
                    for symbol, setup in worker.active_bos_setups.items():
                        all_setups.append(f"BOS {setup.direction} - {symbol}")

            if not all_setups:
                self.setups_text.insert("1.0", "No active setups")
            else:
                self.setups_text.insert("1.0", "\n".join(all_setups))

            self.setups_text.configure(state="disabled")
        except Exception as e:
            print(f"Error updating setups display: {e}")

    def _clean_config_data(self, config_data):
        """Remove old/unexpected fields from config data"""
        valid_fields = {
            'name', 'symbols', 'recipients', 'capital', 'risk_per_trade',
            'trading_active', 'email_notifications', 'account', 'password', 'server',
            'use_super_ob_fvg', 'use_range_filter', 'sl_percentage', 'tp_percentage',
            # Preserve new tolerances:
            'fvg_tiny_body_tolerance_pct', 'ob_min_body_overlap_pct'
        }

        cleaned = {}
        for key, value in config_data.items():
            if key in valid_fields:
                cleaned[key] = value

        # Ensure our two main indicators are set
        if 'use_super_ob_fvg' not in cleaned:
            cleaned['use_super_ob_fvg'] = True
        if 'use_range_filter' not in cleaned:
            cleaned['use_range_filter'] = True

        # Defaults for tolerances if missing
        if 'fvg_tiny_body_tolerance_pct' not in cleaned:
            cleaned['fvg_tiny_body_tolerance_pct'] = 0.05
        if 'ob_min_body_overlap_pct' not in cleaned:
            cleaned['ob_min_body_overlap_pct'] = 0.05

        return cleaned

    def stop_all_trading(self):
        """Stop all trading workers"""
        for worker_name, worker in self.workers.items():
            worker.stop_trading()
            self.log_message(f"⏸ STOPPED: {worker_name}")

        self.status_label.configure(text="🔴 SYSTEM STOPPED", text_color="red")
        self.log_message("=== TRADING SYSTEM STOPPED ===")

    def worker_loop(self, config_name):
        """Ultra-conservative worker execution loop"""
        worker = self.workers[config_name]
        cycle_count = 0

        while True:
            try:
                if worker.running and worker.config.trading_active:
                    worker.run_strategy_cycle()
                    self.update_setups_display()

                # Much longer sleep between cycles
                time.sleep(120)  # 2 minutes between cycles instead of 1

                # Cleanup every 6 cycles (12 minutes)
                cycle_count += 1
                if cycle_count >= 6:
                    worker.cleanup_old_trades()
                    cycle_count = 0

            except Exception as e:
                self.log_message(f"Error in worker {config_name}: {e}")
                time.sleep(60)  # Shorter sleep on error

    def start_existing_configs_stopped(self):
        """Start existing configurations in STOPPED state with cleaned configs"""
        for config_name, config_data in self.configs.items():
            try:
                # Clean the config data by removing old fields
                cleaned_config = self._clean_config_data(config_data)

                # Use the from_dict method to create TradingConfig
                config_obj = TradingConfig.from_dict(cleaned_config)

                # Ensure it starts stopped
                config_obj.trading_active = False

                worker = AdvancedTradeWorker(config_obj, self.email_sender, self.log_message)
                self.workers[config_name] = worker

                # Start worker thread but it won't trade until explicitly started
                threading.Thread(target=self.worker_loop, args=(config_name,), daemon=True).start()

            except Exception as e:
                self.log_message(f"Error starting config {config_name}: {e}")


    def on_closing(self):
        """Handle application closing"""
        self.stop_all_trading()
        self.destroy()


class BacktestWindow(ctk.CTkToplevel):
    def __init__(self, parent, configs, workers):
        super().__init__(parent)
        self.title("Backtest Simulator - tool5_v7 (HISTORICAL DATA)")
        self.geometry("900x700")
        self.minsize(800, 600)

        self.configs = configs
        self.workers = workers
        self.backtest_running = False
        self.strategy = AdvancedTradingStrategy(TvDatafeed())

        # Alerts-only backtest (mirror live alerts-only logic)
        self.alerts_only_backtest = True

        # The selected config for the run gets assigned in _execute_backtest
        self.active_config = None

        self.init_ui()

    def init_ui(self):
        # Main container with scrollbar
        main_container = ctk.CTkFrame(self)
        main_container.pack(fill="both", expand=True, padx=10, pady=10)

        # Create scrollable frame
        self.scrollable_frame = ctk.CTkScrollableFrame(main_container)
        self.scrollable_frame.pack(fill="both", expand=True)

        # Title
        title_label = ctk.CTkLabel(self.scrollable_frame,
                                   text="📊 Historical Data Backtest Simulator",
                                   font=ctk.CTkFont(size=22, weight="bold"))
        title_label.pack(pady=15)

        # Configuration selection
        config_frame = ctk.CTkFrame(self.scrollable_frame)
        config_frame.pack(fill="x", pady=10, padx=10)

        ctk.CTkLabel(config_frame, text="Select Configuration:",
                     font=ctk.CTkFont(weight="bold")).pack(pady=5)
        self.config_combo = ctk.CTkComboBox(config_frame,
                                            values=list(self.configs.keys()),
                                            width=400)
        self.config_combo.pack(pady=5)

        # Data selection method
        method_frame = ctk.CTkFrame(self.scrollable_frame)
        method_frame.pack(fill="x", pady=10, padx=10)

        ctk.CTkLabel(method_frame, text="Data Selection Method:",
                     font=ctk.CTkFont(weight="bold")).pack(pady=5)

        self.data_method = ctk.CTkSegmentedButton(method_frame,
                                                  values=["By Date Range", "By Number of Bars"],
                                                  command=self._on_method_change)
        self.data_method.pack(pady=5)
        self.data_method.set("By Date Range")

        # Date range selection (initially visible)
        self.date_frame = ctk.CTkFrame(self.scrollable_frame)
        self.date_frame.pack(fill="x", pady=10, padx=10)

        ctk.CTkLabel(self.date_frame, text="📅 Date Range Selection").pack(pady=5)

        # Start date
        start_frame = ctk.CTkFrame(self.date_frame)
        start_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(start_frame, text="Start Date (YYYY-MM-DD):").pack(side="left", padx=5)
        self.start_date = ctk.CTkEntry(start_frame, placeholder_text="2024-01-01")
        self.start_date.pack(side="right", fill="x", expand=True, padx=5)

        # End date
        end_frame = ctk.CTkFrame(self.date_frame)
        end_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(end_frame, text="End Date (YYYY-MM-DD):").pack(side="left", padx=5)
        self.end_date = ctk.CTkEntry(end_frame, placeholder_text="2024-10-10")
        self.end_date.pack(side="right", fill="x", expand=True, padx=5)

        # Bars selection (initially hidden)
        self.bars_frame = ctk.CTkFrame(self.scrollable_frame)
        self.bars_frame.pack(fill="x", pady=10, padx=10)
        self.bars_frame.pack_forget()  # Hide initially

        ctk.CTkLabel(self.bars_frame, text="📊 Bars Selection").pack(pady=5)

        # 4H Bars
        bars_4h_frame = ctk.CTkFrame(self.bars_frame)
        bars_4h_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(bars_4h_frame, text="Number of 4H Bars:").pack(side="left", padx=5)
        self.n_bars_4h = ctk.CTkEntry(bars_4h_frame, placeholder_text="500")
        self.n_bars_4h.insert(0, "500")
        self.n_bars_4h.pack(side="right", fill="x", expand=True, padx=5)

        # 5min Bars
        bars_5min_frame = ctk.CTkFrame(self.bars_frame)
        bars_5min_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(bars_5min_frame, text="Number of 5min Bars:").pack(side="left", padx=5)
        self.n_bars_5min = ctk.CTkEntry(bars_5min_frame, placeholder_text="2000")
        self.n_bars_5min.insert(0, "2000")
        self.n_bars_5min.pack(side="right", fill="x", expand=True, padx=5)

        # Info frame
        info_frame = ctk.CTkFrame(self.scrollable_frame, fg_color="#2b2b2b")
        info_frame.pack(fill="x", pady=10, padx=10)

        info_text = """
📈 HISTORICAL DATA BACKTESTING OPTIONS:

• By Date Range: Specify start and end dates for testing
• By Number of Bars: Specify exact number of 4H and 5min bars

📊 BAR CALCULATIONS:
• 4H Bars: 6 bars per day (24 hours ÷ 4 hours)
• 5min Bars: 288 bars per day (24 hours × 12 bars per hour)
• Example: 30 days = 180 fourH bars / 8,640 fiveMin bars
        """
        ctk.CTkLabel(info_frame, text=info_text, justify="left").pack(padx=10, pady=10)

        # Backtest results
        results_frame = ctk.CTkFrame(self.scrollable_frame)
        results_frame.pack(fill="both", expand=True, pady=10, padx=10)

        ctk.CTkLabel(results_frame, text="Backtest Results:").pack(pady=5)
        self.results_text = scrolledtext.ScrolledText(results_frame,
                                                      height=20,
                                                      bg="#1a1a1a",
                                                      fg="white",
                                                      font=("Consolas", 10),
                                                      wrap=tk.WORD)
        self.results_text.pack(fill="both", expand=True, padx=10, pady=10)
        self.results_text.config(state="disabled")

        # Control buttons
        btn_frame = ctk.CTkFrame(self.scrollable_frame)
        btn_frame.pack(fill="x", pady=10, padx=10)

        ctk.CTkButton(btn_frame, text="🚀 Run Backtest",
                      command=self.run_backtest,
                      fg_color="#2E8B57",
                      height=40).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="⏹️ Stop Backtest",
                      command=self.stop_backtest,
                      fg_color="#D35B58",
                      height=40).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="🧹 Clear Results",
                      command=self.clear_results,
                      height=40).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="💾 Export Results",
                      command=self.export_results,
                      height=40).pack(side="left", padx=5)

    def _on_method_change(self, value):
        """Toggle between date range and bars selection"""
        if value == "By Date Range":
            self.date_frame.pack(fill="x", pady=10, padx=10)
            self.bars_frame.pack_forget()
        else:
            self.bars_frame.pack(fill="x", pady=10, padx=10)
            self.date_frame.pack_forget()

    def _calculate_bars_from_dates(self, start_date, end_date):
        """Calculate number of bars based on date range"""
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")

            days = (end_dt - start_dt).days + 1  # Inclusive

            # Calculate bars
            bars_4h = days * 6  # 6 fourH bars per day
            bars_5min = days * 288  # 288 fiveMin bars per day

            return bars_4h, bars_5min
        except Exception:
            return 500, 2000  # Default fallback

    def run_backtest(self):
        if self.backtest_running:
            return

        config_name = self.config_combo.get()
        if not config_name:
            messagebox.showerror("Error", "Please select a configuration")
            return

        method = self.data_method.get()

        if method == "By Date Range":
            start_date = self.start_date.get().strip()
            end_date = self.end_date.get().strip()

            if not start_date:
                messagebox.showerror("Error", "Please enter a start date")
                return

            if not end_date:
                end_date = datetime.now().strftime("%Y-%m-%d")  # Default to today

            # Calculate bars from dates
            bars_4h, bars_5min = self._calculate_bars_from_dates(start_date, end_date)

        else:  # By Number of Bars
            try:
                bars_4h = int(self.n_bars_4h.get() or "500")
                bars_5min = int(self.n_bars_5min.get() or "2000")
                start_date = None
                end_date = None
            except ValueError:
                messagebox.showerror("Error", "Please enter valid numbers for bars")
                return

        self.backtest_running = True
        threading.Thread(target=self._execute_backtest,
                         args=(config_name, start_date, end_date, bars_4h, bars_5min),
                         daemon=True).start()

    def stop_backtest(self):
        self.backtest_running = False
        self._update_results("⏹️ Backtest stopped by user")

    def clear_results(self):
        self.results_text.config(state="normal")
        self.results_text.delete(1.0, tk.END)
        self.results_text.config(state="disabled")

    def export_results(self):
        try:
            filename = f"backtest_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(self.results_text.get(1.0, tk.END))
            messagebox.showinfo("Export Successful", f"Results exported to {filename}")
        except Exception as e:
            messagebox.showerror("Export Error", f"Failed to export: {e}")

    # =============== Helpers to mirror live logic ===============

    def _bt_fvg_wick_condition(self, setup, candidate, tol_pct):
        """
        setup = dict with third_candle_* and direction keys
        candidate = 4H candle row (Series)
        tol_pct = percent of price (e.g., 0.05 = 0.05%)
        """
        tol_val = (float(tol_pct) / 100.0) * max(1e-9, setup['third_candle_high'])
        if setup['direction'] == "DOWN":
            wick_ok = candidate['high'] > setup['third_candle_high']
            body_ok = candidate['close'] <= setup['third_candle_body_high'] + tol_val
            return wick_ok and body_ok
        else:
            wick_ok = candidate['low'] < setup['third_candle_low']
            body_ok = candidate['close'] >= setup['third_candle_body_low'] - tol_val
            return wick_ok and body_ok

    def _bt_ob_retest_condition(self, setup, candidate, ob_min_overlap_pct):
        """
        setup = dict with ob_* and direction
        candidate = 4H candle row (Series)
        ob_min_overlap_pct = percent of price (e.g., 0.05 = 0.05%)
        """
        ref_price = max(1e-9, (setup['ob_high'] + setup['ob_low']) / 2.0)
        tol_val = (float(ob_min_overlap_pct) / 100.0) * ref_price

        body_top = max(candidate['open'], candidate['close'])
        body_bot = min(candidate['open'], candidate['close'])

        if setup['direction'] == "DOWN":
            wick_ok = candidate['high'] > setup['ob_high']
            body_overlap = max(0.0, body_top - max(setup['ob_high'], body_bot))
            body_ok = body_overlap >= tol_val
            return wick_ok and body_ok
        else:
            wick_ok = candidate['low'] < setup['ob_low']
            # how much body is under ob_low
            body_ok = (min(body_top, setup['ob_low']) - body_bot) >= tol_val
            return wick_ok and body_ok

    def _bt_get_nth_4h_after(self, df_4h, anchor_time, n_index, last_checked):
        """
        Return (row, time) for the Nth fully closed 4H candle after anchor_time.
        n_index: 1-based (1=4th for FVG, 1=first after OB).
        """
        after = df_4h[df_4h.index > anchor_time]
        if len(after) >= n_index:
            row = after.iloc[n_index - 1]
            t = after.index[n_index - 1]
            if last_checked is None or t > last_checked:
                return row, t
        return None, None

    def _bt_get_5m_signal_at_time(self, symbol, current_time, df_5min):
        """
        Compute Range Filter signal at current_time from the last 24h of data.
        """
        lookback_start = current_time - timedelta(hours=24)
        recent = df_5min[(df_5min.index >= lookback_start) & (df_5min.index <= current_time)]
        if len(recent) < 100:
            return "NO_SIGNAL"
        rf = self.strategy.calculate_range_filter(recent)
        if rf.empty:
            return "NO_SIGNAL"
        last = rf.iloc[-1]
        if bool(last.get('longCond', False)):
            return "BUY"
        if bool(last.get('shortCond', False)):
            return "SELL"
        return "NO_SIGNAL"

    def _bt_detect_new_setups_at_4h_close(self, symbol, current_time, df_4h, state):
        """
        Detect new FVG/OB on the just-closed 4H candle and add to state.
        FVG (Pine): isFvgUp(0): low[0] > high[2]; isFvgDown(0): high[0] < low[2].
        OB (Pine): isObUp(1) and isObDown(1) equivalent implemented like in live strategy.
        """
        # Find the current fully closed 4H candle
        df4 = df_4h[df_4h.index <= current_time]
        if len(df4) < 3:
            return
        c0 = df4.iloc[-1]       # bar 0
        c1 = df4.iloc[-2]       # bar 1
        c2 = df4.iloc[-3]       # bar 2

        # FVG detection (anchor to c0 as "third candle")
        # Bullish: low[0] > high[2]
        if c0['low'] > c2['high']:
            setup = {
                'type': 'FVG',
                'direction': 'UP',
                'third_candle_time': c0.name,
                'third_candle_high': c0['high'],
                'third_candle_low': c0['low'],
                'third_candle_body_high': max(c0['open'], c0['close']),
                'third_candle_body_low': min(c0['open'], c0['close']),
                'status': 'AWAITING_CANDIDATE',
                'candidate_index': 1,   # 4th
                'max_candidates': 5,    # 4th..8th
                'rf_window_start': None,
                'rf_window_deadline': None,
                'last_checked_4h_close': None
            }
            state['fvg_setups'].append(setup)
            self._update_results(f"   🎯 FVG UP detected at 4H close {c0.name}")

        # Bearish: high[0] < low[2]
        elif c0['high'] < c2['low']:
            setup = {
                'type': 'FVG',
                'direction': 'DOWN',
                'third_candle_time': c0.name,
                'third_candle_high': c0['high'],
                'third_candle_low': c0['low'],
                'third_candle_body_high': max(c0['open'], c0['close']),
                'third_candle_body_low': min(c0['open'], c0['close']),
                'status': 'AWAITING_CANDIDATE',
                'candidate_index': 1,
                'max_candidates': 5,
                'rf_window_start': None,
                'rf_window_deadline': None,
                'last_checked_4h_close': None
            }
            state['fvg_setups'].append(setup)
            self._update_results(f"   🎯 FVG DOWN detected at 4H close {c0.name}")

        # OB detection (equivalent to live _is_ob_up/_is_ob_down)
        # OB Up: prev down, current up, and current close > previous high
        if (c1['close'] < c1['open']) and (c0['close'] > c0['open']) and (c0['close'] > c1['high']):
            ob = {
                'type': 'OB',
                'direction': 'UP',
                'ob_candle_time': c0.name,
                'ob_high': c0['high'],
                'ob_low': c0['low'],
                'ob_body_high': max(c0['open'], c0['close']),
                'ob_body_low': min(c0['open'], c0['close']),
                'status': 'AWAITING_RETEST',
                'candidate_index': 1,
                'max_candidates': 25,
                'rf_window_start': None,
                'rf_window_deadline': None,
                'last_checked_4h_close': None
            }
            state['ob_setups'].append(ob)
            self._update_results(f"   🎯 OB UP detected at 4H close {c0.name}")

        # OB Down: prev up, current down, and current close < previous low
        if (c1['close'] > c1['open']) and (c0['close'] < c0['open']) and (c0['close'] < c1['low']):
            ob = {
                'type': 'OB',
                'direction': 'DOWN',
                'ob_candle_time': c0.name,
                'ob_high': c0['high'],
                'ob_low': c0['low'],
                'ob_body_high': max(c0['open'], c0['close']),
                'ob_body_low': min(c0['open'], c0['close']),
                'status': 'AWAITING_RETEST',
                'candidate_index': 1,
                'max_candidates': 25,
                'rf_window_start': None,
                'rf_window_deadline': None,
                'last_checked_4h_close': None
            }
            state['ob_setups'].append(ob)
            self._update_results(f"   🎯 OB DOWN detected at 4H close {c0.name}")

    def _bt_update_fvg_state(self, symbol, current_time, df_4h, df_5min, state, alerts):
        tol_pct = float(self.active_config.get('fvg_tiny_body_tolerance_pct', 0.05))
        for setup in list(state['fvg_setups']):
            try:
                if setup['status'] == 'AWAITING_CANDIDATE':
                    cand_row, cand_time = self._bt_get_nth_4h_after(df_4h, setup['third_candle_time'],
                                                                    setup['candidate_index'],
                                                                    setup['last_checked_4h_close'])
                    if cand_row is None:
                        continue
                    setup['last_checked_4h_close'] = cand_time
                    if self._bt_fvg_wick_condition(setup, cand_row, tol_pct):
                        setup['status'] = 'AWAITING_5M'
                        setup['rf_window_start'] = current_time
                        setup['rf_window_deadline'] = current_time + timedelta(hours=4)
                        # Early alert
                        alerts.append({
                            'symbol': symbol,
                            'setup': 'FVG',
                            'direction': setup['direction'],
                            'event': 'EARLY',
                            'time': cand_time
                        })
                        self._update_results(f"   🔔 FVG {setup['direction']} wick-only detected at {cand_time} — 5m window started (4h)")
                    else:
                        setup['candidate_index'] += 1
                        if setup['candidate_index'] > setup['max_candidates']:
                            setup['status'] = 'EXPIRED'
                            self._update_results("   ⏰ FVG expired (no valid wick-only in 4th–8th)")

                elif setup['status'] == 'AWAITING_5M':
                    if current_time >= setup['rf_window_deadline']:
                        setup['status'] = 'AWAITING_CANDIDATE'
                        setup['candidate_index'] += 1
                        setup['rf_window_start'] = None
                        setup['rf_window_deadline'] = None
                        if setup['candidate_index'] > setup['max_candidates']:
                            setup['status'] = 'EXPIRED'
                            self._update_results("   ⏰ FVG expired after 5m window; no more candidates")
                        continue

                    sig = self._bt_get_5m_signal_at_time(symbol, current_time, df_5min)
                    target = "SELL" if setup['direction'] == "DOWN" else "BUY"
                    if sig == target:
                        setup['status'] = 'CONFIRMED'
                        alerts.append({
                            'symbol': symbol,
                            'setup': 'FVG',
                            'direction': setup['direction'],
                            'event': 'CONFIRM',
                            'time': current_time
                        })
                        self._update_results(f"   ✅ FVG {setup['direction']} confirmed by 5m ({target}) at {current_time}")

            except Exception as e:
                self._update_results(f"   ⚠️ FVG state error: {e}")

        # Cleanup finished ones
        state['fvg_setups'] = [s for s in state['fvg_setups'] if s['status'] not in ('CONFIRMED', 'EXPIRED')]

    def _bt_update_ob_state(self, symbol, current_time, df_4h, df_5min, state, alerts):
        ob_tol = float(self.active_config.get('ob_min_body_overlap_pct', 0.05))
        for setup in list(state['ob_setups']):
            try:
                if setup['status'] == 'AWAITING_RETEST':
                    cand_row, cand_time = self._bt_get_nth_4h_after(df_4h, setup['ob_candle_time'],
                                                                    setup['candidate_index'],
                                                                    setup['last_checked_4h_close'])
                    if cand_row is None:
                        continue
                    setup['last_checked_4h_close'] = cand_time
                    if self._bt_ob_retest_condition(setup, cand_row, ob_tol):
                        setup['status'] = 'AWAITING_5M'
                        setup['rf_window_start'] = current_time
                        setup['rf_window_deadline'] = current_time + timedelta(hours=4)
                        # Early alert
                        alerts.append({
                            'symbol': symbol,
                            'setup': 'OB',
                            'direction': setup['direction'],
                            'event': 'EARLY',
                            'time': cand_time
                        })
                        self._update_results(f"   🔔 OB {setup['direction']} retest detected at {cand_time} — 5m window started (4h)")
                    else:
                        setup['candidate_index'] += 1
                        if setup['candidate_index'] > setup['max_candidates']:
                            setup['status'] = 'EXPIRED'
                            self._update_results("   ⏰ OB expired (25 candidates exhausted)")

                elif setup['status'] == 'AWAITING_5M':
                    if current_time >= setup['rf_window_deadline']:
                        setup['status'] = 'AWAITING_RETEST'
                        setup['candidate_index'] += 1
                        setup['rf_window_start'] = None
                        setup['rf_window_deadline'] = None
                        if setup['candidate_index'] > setup['max_candidates']:
                            setup['status'] = 'EXPIRED'
                            self._update_results("   ⏰ OB expired after 5m window; no more candidates")
                        continue

                    sig = self._bt_get_5m_signal_at_time(symbol, current_time, df_5min)
                    target = "SELL" if setup['direction'] == "DOWN" else "BUY"
                    if sig == target:
                        setup['status'] = 'CONFIRMED'
                        alerts.append({
                            'symbol': symbol,
                            'setup': 'OB',
                            'direction': setup['direction'],
                            'event': 'CONFIRM',
                            'time': current_time
                        })
                        self._update_results(f"   ✅ OB {setup['direction']} confirmed by 5m ({target}) at {current_time}")

            except Exception as e:
                self._update_results(f"   ⚠️ OB state error: {e}")

        # Cleanup finished ones
        state['ob_setups'] = [s for s in state['ob_setups'] if s['status'] not in ('CONFIRMED', 'EXPIRED')]

    # =============== Backtest core ===============

    def _simulate_strategy_on_historical_data(self, symbol, start_date, end_date, bars_4h, bars_5min):
        """Simulate strategy mirroring live logic (alert-only)."""
        try:
            self._update_results(f"📥 Loading historical data for {symbol}...")

            df_4h = self._get_historical_data(symbol, Interval.in_4_hour, bars_4h)
            df_5min = self._get_historical_data(symbol, Interval.in_5_minute, bars_5min)

            if df_4h is None or df_5min is None or df_4h.empty or df_5min.empty:
                return {"error": f"No data for {symbol}"}

            if start_date and end_date:
                start_dt = pd.to_datetime(start_date)
                end_dt = pd.to_datetime(end_date) + timedelta(days=1)
                df_4h = df_4h[(df_4h.index >= start_dt) & (df_4h.index <= end_dt)]
                df_5min = df_5min[(df_5min.index >= start_dt) & (df_5min.index <= end_dt)]

            self._update_results(f"📊 Loaded {len(df_4h)} 4H bars and {len(df_5min)} 5min bars")
            self._update_results(f"📅 Data period: {df_4h.index[0]} to {df_4h.index[-1]}")

            df_4h = df_4h.sort_index()
            df_5min = df_5min.sort_index()

            # Initialize per-run config and state
            if self.active_config is None:
                self.active_config = {'fvg_tiny_body_tolerance_pct': 0.05, 'ob_min_body_overlap_pct': 0.05}

            state = {
                'fvg_setups': [],
                'ob_setups': []
            }

            alerts = []  # collect alert events (EARLY/CONFIRM)

            # Iterate 5m stream (like live) and drive 4H detection only on 4H close moments
            for current_5min_time in df_5min.index:
                if not self.backtest_running:
                    break

                # 4H detection only when the current 5m time aligns with 4H candle close schedule
                if self._is_4h_candle_close(current_5min_time):
                    self._bt_detect_new_setups_at_4h_close(symbol, current_5min_time, df_4h, state)

                # Update FVG and OB state machines each 5m
                self._bt_update_fvg_state(symbol, current_5min_time, df_4h, df_5min, state, alerts)
                self._bt_update_ob_state(symbol, current_5min_time, df_4h, df_5min, state, alerts)

            # Summarize results (alerts only)
            early_cnt = sum(1 for a in alerts if a['event'] == 'EARLY')
            confirm_cnt = sum(1 for a in alerts if a['event'] == 'CONFIRM')
            self._update_results(f"   🔔 Alerts: Early={early_cnt}, Confirmations={confirm_cnt}")

            # Provide a minimal "trades-like" list for the overall summary (no PnL)
            pseudo_trades = [{
                'symbol': a['symbol'],
                'type': ('BUY' if a.get('setup') in ('FVG', 'OB') and a.get('direction') == 'UP' else 'SELL'),
                'setup': a.get('setup'),
                'direction': a.get('direction'),
                'entry_time': a.get('time'),
                'entry_price': float('nan'),
                'exit_time': a.get('time'),
                'exit_price': float('nan'),
                'sl_price': float('nan'),
                'tp_price': float('nan'),
                'profit': 0.0,
                'outcome': a['event'],
                'price_change': 0.0
            } for a in alerts if a['event'] == 'CONFIRM']

            total_profit = 0.0
            return {
                'trades': pseudo_trades,
                'total_trades': len(pseudo_trades),
                'total_profit': total_profit,
                'final_equity': None
            }

        except Exception as e:
            self._update_results(f"❌ Error in {symbol} backtest: {str(e)}")
            import traceback
            self._update_results(f"❌ Traceback: {traceback.format_exc()}")
            return {"error": str(e)}

    # =============== Shared utils ===============

    def _is_4h_candle_close(self, current_time):
        """Check if current time aligns with 4H candle close"""
        # 4H candles close at :00 of every 4th hour (0, 4, 8, 12, 16, 20)
        hour = current_time.hour
        minute = current_time.minute
        return minute == 55 and hour % 4 == 3  # Check at 55th minute of the 3rd hour

    def _get_historical_data(self, symbol, interval, n_bars):
        """Get historical data from TradingView"""
        try:
            exchange = self.strategy.get_exchange(symbol)
            df = self.strategy.tv.get_hist(
                symbol=symbol,
                exchange=exchange,
                interval=interval,
                n_bars=n_bars
            )
            return df
        except Exception as e:
            self._update_results(f"❌ Error loading data for {symbol}: {e}")
            return None

    def _get_symbol_results(self, symbol):
        """Helper method to get symbol results - placeholder"""
        return None

    def _update_results(self, message):
        def update():
            self.results_text.config(state="normal")
            self.results_text.insert("end", message + "\n")
            self.results_text.see("end")
            self.results_text.config(state="disabled")
        self.after(0, update)

    # Deprecated (replaced by the alert-only state-machine simulation)
    def _process_new_price_data(self, symbol, current_time, current_data, df_4h, df_5min, trading_state, trades):
        """
        DEPRECATED in this class:
        The backtest mirrors live logic via _simulate_strategy_on_historical_data directly,
        using FVG/OB state machines and alert events only.
        """
        pass

    def _execute_backtest(self, config_name, start_date, end_date, bars_4h, bars_5min):
        try:
            self._update_results("🚀 Starting Historical Data Backtest...")
            self._update_results(f"Configuration: {config_name}")

            # Capture selected config to use tolerances
            self.active_config = self.configs.get(config_name, {}) if self.configs else {}

            if start_date and end_date:
                self._update_results(f"Date Range: {start_date} to {end_date}")
                self._update_results(f"Calculated Bars: {bars_4h} fourH, {bars_5min} fiveMin")
            else:
                self._update_results(f"Bars: {bars_4h} fourH, {bars_5min} fiveMin")

            self._update_results("=" * 60)

            config_data = self.configs[config_name]
            symbols = config_data['symbols']

            total_stats = {
                'trades': 0,            # here: confirmations
                'profit': 0.0,          # alerts-only; stays 0
                'wins': 0,
                'losses': 0,
                'symbols_tested': 0
            }

            # Simulate for each symbol
            for symbol in symbols:
                if not self.backtest_running:
                    break

                clean_symbol = symbol.split(":")[1] if ":" in symbol else symbol
                self._update_results(f"\n🔍 Backtesting {clean_symbol}...")

                res = self._simulate_strategy_on_historical_data(
                    clean_symbol, start_date, end_date, bars_4h, bars_5min
                )

                if res and 'trades' in res:
                    trades = res['trades']
                    total_stats['trades'] += len(trades)
                    total_stats['profit'] += res.get('total_profit', 0.0)
                    total_stats['wins'] += sum(1 for t in trades if t['profit'] > 0)
                    total_stats['losses'] += sum(1 for t in trades if t['profit'] < 0)
                    total_stats['symbols_tested'] += 1

                    self._update_results(f"✅ {clean_symbol}: {len(trades)} confirmations")
                else:
                    self._update_results(f"❌ {clean_symbol}: No confirmations or error in backtest")

            # Final summary
            self._update_results("\n" + "=" * 60)
            self._update_results("📊 BACKTEST SUMMARY")
            self._update_results("=" * 60)
            self._update_results(f"Symbols Tested: {total_stats['symbols_tested']}")
            self._update_results(f"Total Confirmations: {total_stats['trades']}")

            self._update_results("\n✅ Backtest completed!")

        except Exception as e:
            self._update_results(f"❌ Backtest error: {e}")
        finally:
            self.backtest_running = False

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