import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import customtkinter as ctk
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from tvDatafeed import TvDatafeed, Interval
import asyncio
import threading
import concurrent.futures
from datetime import datetime, timedelta
import warnings
import traceback
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any
import json
import logging
import redis
from functools import lru_cache
import pickle
import hashlib
from scipy.optimize import minimize
from scipy.stats import norm
import os

warnings.filterwarnings('ignore')

# Set appearance
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


# =============================================================================
# ENHANCED TVDATAFEED INTEGRATION
# =============================================================================

class ProfessionalTVDataFeed:
    """Professional data feed using TVDataFeed with bar-based collection"""

    def __init__(self, username=None, password=None):
        try:
            self.tv = TvDatafeed(username=username, password=password)
            self.connected = True
        except Exception as e:
            logging.warning(f"TVDataFeed initialization failed: {e}")
            self.tv = TvDatafeed()
            self.connected = True

        self.cache = DataCache()

        # TradingView timeframe mapping
        self.timeframe_map = {
            '1mn': Interval.in_1_minute,
            '3mn': Interval.in_3_minute,
            '5mn': Interval.in_5_minute,
            '15mn': Interval.in_15_minute,
            '30mn': Interval.in_30_minute,
            '45mn': Interval.in_45_minute,
            '1h': Interval.in_1_hour,
            '2h': Interval.in_2_hour,
            '3h': Interval.in_3_hour,
            '4h': Interval.in_4_hour,
            '1d': Interval.in_daily,
            '1W': Interval.in_weekly,
            '1M': Interval.in_monthly
        }

        # Symbol exchange mapping
        self.symbol_exchange_map = {
            'EURUSD': 'FX_IDC',
            'GBPUSD': 'FX_IDC',
            'USDJPY': 'FX_IDC',
            'XAUUSD': 'FX_IDC',
            'XAGUSD': 'FX_IDC',
            'BTCUSD': 'BINANCE',
            'ETHUSD': 'BINANCE',
            'AAPL': 'NASDAQ',
            'TSLA': 'NASDAQ',
            'SPY': 'AMEX',
            'QQQ': 'NASDAQ',
            'ES1!': 'CME_MINI',  # S&P Futures
            'NQ1!': 'CME_MINI',  # Nasdaq Futures
            'CL1!': 'NYMEX',  # Oil Futures
            'GC1!': 'COMEX',  # Gold Futures
        }

    def get_exchange(self, symbol: str) -> str:
        """Get exchange for symbol"""
        # Remove $ prefix if present
        clean_symbol = symbol.replace('$', '')
        return self.symbol_exchange_map.get(clean_symbol, 'FX_IDC')

    async def get_data_by_bars(self, symbol: str, timeframe: str, n_bars: int) -> pd.DataFrame:
        """Get data by number of bars (not dates)"""

        cache_key = f"{symbol}_{timeframe}_{n_bars}"
        cached_data = self.cache.get(cache_key)
        if cached_data is not None:
            return cached_data

        try:
            # Get exchange
            exchange = self.get_exchange(symbol)

            # Get TV interval
            tv_interval = self.timeframe_map.get(timeframe, Interval.in_1_hour)

            # Fetch data
            df = self.tv.get_hist(
                symbol=symbol,
                exchange=exchange,
                interval=tv_interval,
                n_bars=n_bars
            )

            if df is None or df.empty:
                raise ValueError(f"No data returned for {symbol} on {exchange}")

            # Enhance dataframe
            df = self._enhance_dataframe(df)

            # Cache the result
            self.cache.set(cache_key, df)

            return df

        except Exception as e:
            logging.error(f"Error fetching data for {symbol}: {e}")
            raise

    def get_multiple_timeframes(self, symbol: str, timeframe_bars: Dict[str, int]) -> Dict[str, pd.DataFrame]:
        """Get data for multiple timeframes simultaneously"""
        results = {}

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_tf = {
                executor.submit(self.get_data_by_bars, symbol, tf, n_bars): tf
                for tf, n_bars in timeframe_bars.items()
            }

            for future in concurrent.futures.as_completed(future_to_tf):
                tf = future_to_tf[future]
                try:
                    results[tf] = future.result()
                except Exception as e:
                    logging.error(f"Error fetching {tf} data: {e}")
                    results[tf] = None

        return results

    def _enhance_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add professional features to dataframe"""
        df = df.copy()

        # Ensure proper column names
        if 'datetime' in df.columns:
            df.set_index('datetime', inplace=True)

        # Calculate returns and volatility
        df['returns'] = df['close'].pct_change()
        df['log_returns'] = np.log(df['close'] / df['close'].shift(1))

        # Volume-based features
        if 'volume' in df.columns:
            df['volume_sma'] = df['volume'].rolling(20).mean()
            df['volume_ratio'] = df['volume'] / df['volume_sma']

        # Price-based features
        df['hl_range'] = (df['high'] - df['low']) / df['close']
        df['oc_range'] = abs(df['open'] - df['close']) / df['close']

        # Add technical indicators
        df = self._add_technical_indicators(df)

        return df

    def _add_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add comprehensive technical indicators"""
        # Moving averages
        for period in [5, 10, 20, 50, 100]:
            df[f'sma_{period}'] = df['close'].rolling(period).mean()
            df[f'ema_{period}'] = df['close'].ewm(span=period).mean()

        # Volatility
        df['volatility'] = df['returns'].rolling(20).std()
        df['atr'] = self._calculate_atr(df)

        # RSI
        df['rsi'] = self._calculate_rsi(df)

        # MACD
        df['macd'], df['macd_signal'], df['macd_hist'] = self._calculate_macd(df)

        return df

    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calculate Average True Range"""
        high = df['high']
        low = df['low']
        close = df['close']

        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())

        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return true_range.rolling(period).mean()

    def _calculate_rsi(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calculate RSI"""
        close = df['close']
        delta = close.diff()

        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def _calculate_macd(self, df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9):
        """Calculate MACD"""
        close = df['close']

        ema_fast = close.ewm(span=fast).mean()
        ema_slow = close.ewm(span=slow).mean()

        macd = ema_fast - ema_slow
        macd_signal = macd.ewm(span=signal).mean()
        macd_hist = macd - macd_signal

        return macd, macd_signal, macd_hist


class DataCache:
    """Enhanced caching system"""

    def __init__(self):
        try:
            self.redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=False)
            self.redis_available = True
        except:
            self.redis_available = False
            logging.warning("Redis not available, using memory cache only")

        self.memory_cache = {}
        self.cache_hits = 0
        self.cache_misses = 0

    def get(self, key: str) -> Optional[pd.DataFrame]:
        """Get data from cache"""
        # Try memory cache first
        if key in self.memory_cache:
            self.cache_hits += 1
            return self.memory_cache[key]

        # Try Redis if available
        if self.redis_available:
            try:
                cached_data = self.redis_client.get(key)
                if cached_data:
                    self.cache_hits += 1
                    data = pickle.loads(cached_data)
                    self.memory_cache[key] = data
                    return data
            except Exception as e:
                logging.warning(f"Redis get error: {e}")

        self.cache_misses += 1
        return None

    def set(self, key: str, data: pd.DataFrame, expire: int = 3600):
        """Set data in cache"""
        # Memory cache
        self.memory_cache[key] = data

        # Redis cache
        if self.redis_available:
            try:
                serialized_data = pickle.dumps(data)
                self.redis_client.setex(key, expire, serialized_data)
            except Exception as e:
                logging.warning(f"Redis set error: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        total = self.cache_hits + self.cache_misses
        hit_rate = self.cache_hits / total if total > 0 else 0
        return {
            'hits': self.cache_hits,
            'misses': self.cache_misses,
            'hit_rate': hit_rate,
            'memory_items': len(self.memory_cache)
        }


# =============================================================================
# ENHANCED BACKTESTING ENGINE WITH BAR-BASED DATA
# =============================================================================

class BarBasedBacktestEngine:
    """Backtesting engine that works with bar counts instead of dates"""

    def __init__(self, initial_capital: float = 100000):
        self.initial_capital = initial_capital
        self.data_feed = ProfessionalTVDataFeed()

        # Strategy implementations
        self.strategies = {
            'Bollinger Mean Reversion': self.bollinger_mean_reversion,
            'RSI Mean Reversion': self.rsi_mean_reversion,
            'MACD Trend': self.macd_trend,
            'Moving Average Crossover': self.moving_average_crossover,
            'Channel Breakout': self.channel_breakout,
            'Volatility Breakout': self.volatility_breakout,
        }

    async def run_backtest(self, symbol: str, strategy_name: str, timeframe: str,
                           n_bars: int, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Run backtest using bar-based data"""

        try:
            # Get data by bars
            df = await self.data_feed.get_data_by_bars(symbol, timeframe, n_bars)

            if df is None or df.empty:
                return {'error': f'No data retrieved for {symbol} {timeframe}'}

            # Apply strategy
            strategy_func = self.strategies.get(strategy_name)
            if not strategy_func:
                return {'error': f'Strategy {strategy_name} not found'}

            df = strategy_func(df, **parameters)

            # Run simulation
            results = self.simulate_trading(df, parameters)

            return results

        except Exception as e:
            return {'error': f'Backtest failed: {str(e)}'}

    def simulate_trading(self, df: pd.DataFrame, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Simulate trading with the strategy"""
        capital = self.initial_capital
        position = None
        trades = []
        equity_curve = [capital]

        risk_per_trade = parameters.get('risk_per_trade', 0.02)
        stop_loss_multiplier = parameters.get('stop_loss_multiplier', 2.0)
        risk_reward_ratio = parameters.get('risk_reward_ratio', 2.0)

        for i in range(1, len(df)):
            current_data = df.iloc[i]
            signal = current_data.get('signal', 0)

            # Enter trade
            if position is None and signal != 0:
                entry_price = current_data['close']
                direction = 'long' if signal > 0 else 'short'

                # Calculate position size
                atr = current_data.get('atr', entry_price * 0.01)
                stop_loss = self.calculate_stop_loss(entry_price, atr, direction, stop_loss_multiplier)
                position_size = self.calculate_position_size(capital, entry_price, stop_loss, risk_per_trade)

                position = {
                    'entry_price': entry_price,
                    'entry_time': df.index[i],
                    'direction': direction,
                    'size': position_size,
                    'stop_loss': stop_loss,
                    'take_profit': self.calculate_take_profit(entry_price, stop_loss, direction, risk_reward_ratio)
                }

            # Manage position
            elif position is not None:
                current_price = current_data['close']
                exit_price, exit_reason = self.check_exit_conditions(position, current_price, current_data)

                if exit_price is not None:
                    pnl = self.calculate_pnl(position, exit_price)
                    capital += pnl

                    trades.append({
                        'entry_time': position['entry_time'],
                        'exit_time': df.index[i],
                        'entry_price': position['entry_price'],
                        'exit_price': exit_price,
                        'direction': position['direction'],
                        'size': position['size'],
                        'pnl': pnl,
                        'return_pct': pnl / (position['entry_price'] * position['size']),
                        'exit_reason': exit_reason
                    })

                    position = None

            equity_curve.append(capital)

        # Calculate performance metrics
        metrics = self.calculate_performance_metrics(trades, equity_curve)

        return {
            'trades': trades,
            'equity_curve': equity_curve,
            'metrics': metrics,
            'final_capital': capital,
            'data_points': len(df)
        }

    def calculate_stop_loss(self, entry_price: float, atr: float, direction: str, multiplier: float) -> float:
        """Calculate stop loss price"""
        if direction == 'long':
            return entry_price - (atr * multiplier)
        else:
            return entry_price + (atr * multiplier)

    def calculate_take_profit(self, entry_price: float, stop_loss: float, direction: str, ratio: float) -> float:
        """Calculate take profit price"""
        risk = abs(entry_price - stop_loss)
        if direction == 'long':
            return entry_price + (risk * ratio)
        else:
            return entry_price - (risk * ratio)

    def calculate_position_size(self, capital: float, entry_price: float, stop_loss: float,
                                risk_per_trade: float) -> float:
        """Calculate position size based on risk"""
        risk_amount = capital * risk_per_trade
        risk_per_share = abs(entry_price - stop_loss)

        if risk_per_share == 0:
            return 0

        position_size = risk_amount / risk_per_share
        max_position_value = capital * 0.1  # Max 10% of capital

        return min(position_size, max_position_value / entry_price)

    def check_exit_conditions(self, position: Dict, current_price: float, current_data: pd.DataFrame) -> Tuple[
        Optional[float], str]:
        """Check if position should be exited"""
        direction = position['direction']

        # Stop loss hit
        if (direction == 'long' and current_price <= position['stop_loss']) or \
                (direction == 'short' and current_price >= position['stop_loss']):
            return position['stop_loss'], 'stop_loss'

        # Take profit hit
        if (direction == 'long' and current_price >= position['take_profit']) or \
                (direction == 'short' and current_price <= position['take_profit']):
            return position['take_profit'], 'take_profit'

        return None, ''

    def calculate_pnl(self, position: Dict, exit_price: float) -> float:
        """Calculate P&L for position"""
        if position['direction'] == 'long':
            return (exit_price - position['entry_price']) * position['size']
        else:
            return (position['entry_price'] - exit_price) * position['size']

    def calculate_performance_metrics(self, trades: List[Dict], equity_curve: List[float]) -> Dict[str, float]:
        """Calculate performance metrics"""
        if not trades:
            return {}

        total_trades = len(trades)
        winning_trades = [t for t in trades if t['pnl'] > 0]
        losing_trades = [t for t in trades if t['pnl'] < 0]

        win_rate = len(winning_trades) / total_trades
        total_pnl = sum(t['pnl'] for t in trades)

        # Sharpe ratio (simplified)
        returns = [t['return_pct'] for t in trades]
        if returns and np.std(returns) > 0:
            sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252)
        else:
            sharpe = 0

        # Drawdown
        equity_array = np.array(equity_curve)
        rolling_max = np.maximum.accumulate(equity_array)
        drawdowns = (rolling_max - equity_array) / rolling_max
        max_drawdown = np.max(drawdowns) if len(drawdowns) > 0 else 0

        return {
            'total_trades': total_trades,
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'sharpe_ratio': sharpe,
            'max_drawdown': max_drawdown,
            'avg_win': np.mean([t['pnl'] for t in winning_trades]) if winning_trades else 0,
            'avg_loss': np.mean([t['pnl'] for t in losing_trades]) if losing_trades else 0,
        }

    # Strategy implementations
    def bollinger_mean_reversion(self, df: pd.DataFrame, period: int = 20, std: int = 2) -> pd.DataFrame:
        """Bollinger Band Mean Reversion"""
        df = df.copy()
        df['sma'] = df['close'].rolling(period).mean()
        df['std'] = df['close'].rolling(period).std()
        df['upper_band'] = df['sma'] + (df['std'] * std)
        df['lower_band'] = df['sma'] - (df['std'] * std)
        df['bb_position'] = (df['close'] - df['sma']) / (df['std'] * std)

        df['signal'] = 0
        df.loc[df['bb_position'] < -2, 'signal'] = 1  # Buy signal (oversold)
        df.loc[df['bb_position'] > 2, 'signal'] = -1  # Sell signal (overbought)

        return df

    def rsi_mean_reversion(self, df: pd.DataFrame, rsi_period: int = 14, oversold: int = 30,
                           overbought: int = 70) -> pd.DataFrame:
        """RSI Mean Reversion"""
        df = df.copy()
        df['rsi'] = self._calculate_rsi(df, rsi_period)

        df['signal'] = 0
        df.loc[df['rsi'] < oversold, 'signal'] = 1  # Buy signal
        df.loc[df['rsi'] > overbought, 'signal'] = -1  # Sell signal

        return df

    def macd_trend(self, df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
        """MACD Trend Following"""
        df = df.copy()
        df['macd'], df['macd_signal'], df['macd_hist'] = self._calculate_macd(df, fast, slow, signal)

        df['signal'] = 0
        df.loc[df['macd'] > df['macd_signal'], 'signal'] = 1  # Buy signal
        df.loc[df['macd'] < df['macd_signal'], 'signal'] = -1  # Sell signal

        return df

    def moving_average_crossover(self, df: pd.DataFrame, fast: int = 20, slow: int = 50) -> pd.DataFrame:
        """Moving Average Crossover"""
        df = df.copy()
        df['sma_fast'] = df['close'].rolling(fast).mean()
        df['sma_slow'] = df['close'].rolling(slow).mean()

        df['signal'] = 0
        df.loc[df['sma_fast'] > df['sma_slow'], 'signal'] = 1  # Buy signal
        df.loc[df['sma_fast'] < df['sma_slow'], 'signal'] = -1  # Sell signal

        return df

    def channel_breakout(self, df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
        """Channel Breakout"""
        df = df.copy()
        df['channel_high'] = df['high'].rolling(period).max()
        df['channel_low'] = df['low'].rolling(period).min()

        df['signal'] = 0
        df.loc[df['close'] > df['channel_high'].shift(1), 'signal'] = 1  # Buy signal
        df.loc[df['close'] < df['channel_low'].shift(1), 'signal'] = -1  # Sell signal

        return df

    def volatility_breakout(self, df: pd.DataFrame, atr_period: int = 14, multiplier: float = 2.0) -> pd.DataFrame:
        """Volatility Breakout"""
        df = df.copy()
        df['atr'] = self._calculate_atr(df, atr_period)
        df['volatility_high'] = df['close'] + (df['atr'] * multiplier)
        df['volatility_low'] = df['close'] - (df['atr'] * multiplier)

        df['signal'] = 0
        df.loc[df['close'] > df['volatility_high'].shift(1), 'signal'] = 1  # Buy signal
        df.loc[df['close'] < df['volatility_low'].shift(1), 'signal'] = -1  # Sell signal

        return df

    def _calculate_rsi(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calculate RSI"""
        close = df['close']
        delta = close.diff()

        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

        rs = gain / loss
        return 100 - (100 / (1 + rs))

    def _calculate_macd(self, df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9):
        """Calculate MACD"""
        close = df['close']

        ema_fast = close.ewm(span=fast).mean()
        ema_slow = close.ewm(span=slow).mean()

        macd = ema_fast - ema_slow
        macd_signal = macd.ewm(span=signal).mean()
        macd_hist = macd - macd_signal

        return macd, macd_signal, macd_hist

    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calculate ATR"""
        high = df['high']
        low = df['low']
        close = df['close']

        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())

        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return true_range.rolling(period).mean()


# =============================================================================
# ENHANCED UI WITH BAR-BASED INPUTS
# =============================================================================

class BarBasedBacktestApp(ctk.CTk):
    """Enhanced app with bar-based data collection and TradingView timeframes"""

    def __init__(self):
        super().__init__()

        self.title("📊 BAR-BASED BACKTESTING PLATFORM")
        self.geometry("1400x900")
        self.minsize(1200, 800)

        self.backtest_engine = BarBasedBacktestEngine()
        self.current_results = None

        self.init_ui()

    def init_ui(self):
        """Initialize user interface"""
        main_container = ctk.CTkFrame(self)
        main_container.pack(fill="both", expand=True, padx=10, pady=10)

        # Header
        header_frame = ctk.CTkFrame(main_container, fg_color="#2b2b2b")
        header_frame.pack(fill="x", pady=10)

        ctk.CTkLabel(header_frame,
                     text="📊 BAR-BASED BACKTESTING PLATFORM",
                     font=ctk.CTkFont(size=20, weight="bold"),
                     text_color="white").pack(pady=15)

        ctk.CTkLabel(header_frame,
                     text="TVDataFeed Integration • Bar-Based Data • Multi-Timeframe",
                     font=ctk.CTkFont(size=14),
                     text_color="lightblue").pack(pady=5)

        # Configuration frame
        config_frame = ctk.CTkFrame(main_container)
        config_frame.pack(fill="x", pady=10, padx=10)

        # Symbol input
        symbol_frame = ctk.CTkFrame(config_frame)
        symbol_frame.pack(fill="x", pady=5, padx=10)

        ctk.CTkLabel(symbol_frame, text="Symbol:", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, padx=5,
                                                                                         pady=5)
        self.symbol_entry = ctk.CTkEntry(symbol_frame, width=120, placeholder_text="EURUSD")
        self.symbol_entry.grid(row=0, column=1, padx=5, pady=5)
        self.symbol_entry.insert(0, "EURUSD")

        # Timeframe selection
        ctk.CTkLabel(symbol_frame, text="Timeframe:", font=ctk.CTkFont(weight="bold")).grid(row=0, column=2, padx=5,
                                                                                            pady=5)
        self.timeframe_combo = ctk.CTkComboBox(symbol_frame,
                                               values=['1mn', '3mn', '5mn', '15mn', '30mn', '45mn',
                                                       '1h', '2h', '3h', '4h', '1d', '1W', '1M'],
                                               width=80)
        self.timeframe_combo.grid(row=0, column=3, padx=5, pady=5)
        self.timeframe_combo.set("4h")

        # Bars input
        ctk.CTkLabel(symbol_frame, text="Number of Bars:", font=ctk.CTkFont(weight="bold")).grid(row=0, column=4,
                                                                                                 padx=5, pady=5)
        self.n_bars_entry = ctk.CTkEntry(symbol_frame, width=100, placeholder_text="1000")
        self.n_bars_entry.grid(row=0, column=5, padx=5, pady=5)
        self.n_bars_entry.insert(0, "1000")

        # Strategy selection
        strategy_frame = ctk.CTkFrame(config_frame)
        strategy_frame.pack(fill="x", pady=5, padx=10)

        ctk.CTkLabel(strategy_frame, text="Strategy:", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, padx=5,
                                                                                             pady=5)
        self.strategy_combo = ctk.CTkComboBox(strategy_frame,
                                              values=list(self.backtest_engine.strategies.keys()),
                                              width=200)
        self.strategy_combo.grid(row=0, column=1, padx=5, pady=5)
        self.strategy_combo.set("Bollinger Mean Reversion")

        # Risk parameters
        risk_frame = ctk.CTkFrame(config_frame)
        risk_frame.pack(fill="x", pady=5, padx=10)

        ctk.CTkLabel(risk_frame, text="Risk per Trade (%):", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0,
                                                                                                   padx=5, pady=5)
        self.risk_per_trade = ctk.CTkEntry(risk_frame, width=80)
        self.risk_per_trade.grid(row=0, column=1, padx=5, pady=5)
        self.risk_per_trade.insert(0, "2")

        ctk.CTkLabel(risk_frame, text="Stop Loss Multiplier:", font=ctk.CTkFont(weight="bold")).grid(row=0, column=2,
                                                                                                     padx=5, pady=5)
        self.stop_loss_multiplier = ctk.CTkEntry(risk_frame, width=80)
        self.stop_loss_multiplier.grid(row=0, column=3, padx=5, pady=5)
        self.stop_loss_multiplier.insert(0, "2")

        ctk.CTkLabel(risk_frame, text="Risk/Reward Ratio:", font=ctk.CTkFont(weight="bold")).grid(row=0, column=4,
                                                                                                  padx=5, pady=5)
        self.risk_reward_ratio = ctk.CTkEntry(risk_frame, width=80)
        self.risk_reward_ratio.grid(row=0, column=5, padx=5, pady=5)
        self.risk_reward_ratio.insert(0, "2")

        # Control buttons
        button_frame = ctk.CTkFrame(main_container)
        button_frame.pack(fill="x", pady=10, padx=10)

        ctk.CTkButton(button_frame, text="🚀 RUN BACKTEST",
                      command=self.run_backtest,
                      fg_color="#2E8B57",
                      height=40,
                      font=ctk.CTkFont(weight="bold")).pack(side="left", padx=5)

        ctk.CTkButton(button_frame, text="🔄 MULTI-TIMEFRAME ANALYSIS",
                      command=self.run_multi_timeframe,
                      fg_color="#1E90FF",
                      height=40,
                      font=ctk.CTkFont(weight="bold")).pack(side="left", padx=5)

        ctk.CTkButton(button_frame, text="🧹 CLEAR RESULTS",
                      command=self.clear_results,
                      height=40).pack(side="left", padx=5)

        # Results display
        results_frame = ctk.CTkFrame(main_container)
        results_frame.pack(fill="both", expand=True, pady=10, padx=10)

        # Create notebook for results
        self.results_notebook = ctk.CTkTabview(results_frame)
        self.results_notebook.pack(fill="both", expand=True)

        # Add tabs
        self.results_notebook.add("Backtest Results")
        self.results_notebook.add("Performance Charts")
        self.results_notebook.add("Trade Analysis")

        # Backtest results tab
        results_tab = self.results_notebook.tab("Backtest Results")
        self.results_text = scrolledtext.ScrolledText(results_tab,
                                                      height=20,
                                                      bg="#1a1a1a",
                                                      fg="white",
                                                      font=("Consolas", 10))
        self.results_text.pack(fill="both", expand=True, padx=10, pady=10)
        self.results_text.config(state="disabled")

        # Performance charts tab
        charts_tab = self.results_notebook.tab("Performance Charts")
        self.fig, (self.ax1, self.ax2) = plt.subplots(2, 1, figsize=(10, 8))
        self.canvas = FigureCanvasTkAgg(self.fig, charts_tab)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        # Trade analysis tab
        analysis_tab = self.results_notebook.tab("Trade Analysis")
        self.analysis_text = scrolledtext.ScrolledText(analysis_tab,
                                                       height=20,
                                                       bg="#1a1a1a",
                                                       fg="white",
                                                       font=("Consolas", 10))
        self.analysis_text.pack(fill="both", expand=True, padx=10, pady=10)
        self.analysis_text.config(state="disabled")

        # Status bar
        self.setup_status_bar(main_container)

    def setup_status_bar(self, parent):
        """Setup status bar"""
        status_frame = ctk.CTkFrame(parent, height=30)
        status_frame.pack(fill="x", side="bottom")
        status_frame.pack_propagate(False)

        self.status_label = ctk.CTkLabel(status_frame, text="Ready")
        self.status_label.pack(side="left", padx=10)

        cache_stats = self.backtest_engine.data_feed.cache.get_stats()
        self.cache_label = ctk.CTkLabel(status_frame, text=f"Cache: {cache_stats['hit_rate']:.1%}")
        self.cache_label.pack(side="right", padx=10)

    def run_backtest(self):
        """Run single backtest"""
        try:
            symbol = self.symbol_entry.get().strip().upper()
            timeframe = self.timeframe_combo.get()
            n_bars = int(self.n_bars_entry.get())
            strategy = self.strategy_combo.get()

            risk_per_trade = float(self.risk_per_trade.get()) / 100
            stop_loss_multiplier = float(self.stop_loss_multiplier.get())
            risk_reward_ratio = float(self.risk_reward_ratio.get())

            parameters = {
                'risk_per_trade': risk_per_trade,
                'stop_loss_multiplier': stop_loss_multiplier,
                'risk_reward_ratio': risk_reward_ratio
            }

            # Add strategy-specific parameters
            if 'Bollinger' in strategy:
                parameters.update({'period': 20, 'std': 2})
            elif 'RSI' in strategy:
                parameters.update({'rsi_period': 14, 'oversold': 30, 'overbought': 70})
            elif 'MACD' in strategy:
                parameters.update({'fast': 12, 'slow': 26, 'signal': 9})
            elif 'Moving Average' in strategy:
                parameters.update({'fast': 20, 'slow': 50})
            elif 'Channel' in strategy:
                parameters.update({'period': 20})
            elif 'Volatility' in strategy:
                parameters.update({'atr_period': 14, 'multiplier': 2.0})

            self.status_label.configure(text="🔄 Running backtest...")

            # Run in thread to avoid blocking UI
            threading.Thread(target=self._execute_backtest,
                             args=(symbol, strategy, timeframe, n_bars, parameters),
                             daemon=True).start()

        except Exception as e:
            messagebox.showerror("Error", f"Failed to start backtest: {str(e)}")
            self.status_label.configure(text="Error starting backtest")

    def _execute_backtest(self, symbol: str, strategy: str, timeframe: str,
                          n_bars: int, parameters: Dict[str, Any]):
        """Execute backtest in background thread"""
        try:
            # Create new event loop for async operations
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # Run async backtest
            result = loop.run_until_complete(
                self.backtest_engine.run_backtest(symbol, strategy, timeframe, n_bars, parameters)
            )

            # Update UI in main thread
            self.after(0, lambda: self._display_backtest_results(result, symbol, strategy, timeframe))

        except Exception as e:
            self.after(0, lambda: self._display_error(f"Backtest failed: {str(e)}"))
        finally:
            loop.close()

    def _display_backtest_results(self, result: Dict[str, Any], symbol: str, strategy: str, timeframe: str):
        """Display backtest results in UI"""
        if 'error' in result:
            self._display_error(result['error'])
            return

        metrics = result['metrics']
        trades = result['trades']

        # Update results text
        results_text = f"📊 BACKTEST RESULTS - {symbol} {timeframe} - {strategy}\n"
        results_text += "=" * 60 + "\n\n"
        results_text += f"Total Trades: {metrics['total_trades']}\n"
        results_text += f"Win Rate: {metrics['win_rate']:.1%}\n"
        results_text += f"Total PnL: ${metrics['total_pnl']:.2f}\n"
        results_text += f"Sharpe Ratio: {metrics['sharpe_ratio']:.3f}\n"
        results_text += f"Max Drawdown: {metrics['max_drawdown']:.1%}\n"
        results_text += f"Average Win: ${metrics['avg_win']:.2f}\n"
        results_text += f"Average Loss: ${metrics['avg_loss']:.2f}\n"
        results_text += f"Data Points: {result['data_points']}\n"

        self.results_text.config(state="normal")
        self.results_text.delete(1.0, tk.END)
        self.results_text.insert(1.0, results_text)
        self.results_text.config(state="disabled")

        # Update charts
        self._update_charts(result)

        # Update trade analysis
        self._update_trade_analysis(trades)

        self.status_label.configure(text="✅ Backtest completed")
        self.current_results = result

    def _display_error(self, error_message: str):
        """Display error message"""
        self.results_text.config(state="normal")
        self.results_text.delete(1.0, tk.END)
        self.results_text.insert(1.0, f"❌ ERROR: {error_message}")
        self.results_text.config(state="disabled")
        self.status_label.configure(text="❌ Backtest failed")

    def _update_charts(self, result: Dict[str, Any]):
        """Update performance charts"""
        # Clear previous charts
        self.ax1.clear()
        self.ax2.clear()

        # Equity curve
        equity_curve = result['equity_curve']
        self.ax1.plot(equity_curve, label='Portfolio Equity', color='green', linewidth=2)
        self.ax1.set_title('Equity Curve', fontsize=14, fontweight='bold')
        self.ax1.set_ylabel('Capital ($)', fontweight='bold')
        self.ax1.legend()
        self.ax1.grid(True, alpha=0.3)

        # Drawdown chart
        equity_array = np.array(equity_curve)
        rolling_max = np.maximum.accumulate(equity_array)
        drawdown = (rolling_max - equity_array) / rolling_max

        self.ax2.fill_between(range(len(drawdown)), drawdown * 100, 0,
                              color='red', alpha=0.3, label='Drawdown')
        self.ax2.plot(drawdown * 100, color='red', linewidth=1)
        self.ax2.set_title('Portfolio Drawdown (%)', fontsize=14, fontweight='bold')
        self.ax2.set_ylabel('Drawdown %', fontweight='bold')
        self.ax2.set_xlabel('Time Periods', fontweight='bold')
        self.ax2.legend()
        self.ax2.grid(True, alpha=0.3)

        self.canvas.draw()

    def _update_trade_analysis(self, trades: List[Dict]):
        """Update trade analysis tab"""
        if not trades:
            analysis_text = "No trades executed during backtest period."
        else:
            analysis_text = "📋 TRADE ANALYSIS\n"
            analysis_text += "=" * 40 + "\n\n"

            # Recent trades
            analysis_text += "Recent Trades:\n"
            for i, trade in enumerate(trades[-10:]):  # Show last 10 trades
                analysis_text += (
                    f"{i + 1:2d}. {trade['entry_time'].strftime('%m-%d %H:%M')} | "
                    f"{trade['direction'].upper():4} | "
                    f"Entry: ${trade['entry_price']:7.2f} | "
                    f"Exit: ${trade['exit_price']:7.2f} | "
                    f"PnL: ${trade['pnl']:7.2f} | "
                    f"{trade['exit_reason']:12}\n"
                )

            # Trade statistics
            winning_trades = [t for t in trades if t['pnl'] > 0]
            losing_trades = [t for t in trades if t['pnl'] < 0]

            analysis_text += f"\nTrade Statistics:\n"
            analysis_text += f"Total Trades: {len(trades)}\n"
            analysis_text += f"Winning Trades: {len(winning_trades)}\n"
            analysis_text += f"Losing Trades: {len(losing_trades)}\n"
            analysis_text += f"Win Rate: {len(winning_trades) / len(trades):.1%}\n"

            if winning_trades:
                analysis_text += f"Average Win: ${np.mean([t['pnl'] for t in winning_trades]):.2f}\n"
            if losing_trades:
                analysis_text += f"Average Loss: ${np.mean([t['pnl'] for t in losing_trades]):.2f}\n"

        self.analysis_text.config(state="normal")
        self.analysis_text.delete(1.0, tk.END)
        self.analysis_text.insert(1.0, analysis_text)
        self.analysis_text.config(state="disabled")

    def run_multi_timeframe(self):
        """Run analysis on multiple timeframes"""
        try:
            symbol = self.symbol_entry.get().strip().upper()
            strategy = self.strategy_combo.get()

            # Define timeframes to analyze
            timeframes = ['15mn', '1h', '4h', '1d']
            bars_per_tf = {
                '15mn': 2000,  # ~1 month of 15min bars
                '1h': 1000,  # ~2 months of 1h bars
                '4h': 500,  # ~3 months of 4h bars
                '1d': 250  # ~1 year of daily bars
            }

            self.status_label.configure(text="🔄 Running multi-timeframe analysis...")

            threading.Thread(target=self._execute_multi_timeframe,
                             args=(symbol, strategy, timeframes, bars_per_tf),
                             daemon=True).start()

        except Exception as e:
            messagebox.showerror("Error", f"Multi-timeframe analysis failed: {str(e)}")

    def _execute_multi_timeframe(self, symbol: str, strategy: str,
                                 timeframes: List[str], bars_per_tf: Dict[str, int]):
        """Execute multi-timeframe analysis in background"""
        try:
            results = {}

            for timeframe in timeframes:
                n_bars = bars_per_tf[timeframe]
                parameters = self._get_strategy_parameters(strategy)

                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                result = loop.run_until_complete(
                    self.backtest_engine.run_backtest(symbol, strategy, timeframe, n_bars, parameters)
                )

                results[timeframe] = result
                loop.close()

            self.after(0, lambda: self._display_multi_timeframe_results(results, symbol, strategy))

        except Exception as e:
            self.after(0, lambda: self._display_error(f"Multi-timeframe analysis failed: {str(e)}"))

    def _display_multi_timeframe_results(self, results: Dict[str, Any], symbol: str, strategy: str):
        """Display multi-timeframe results"""
        results_text = f"📊 MULTI-TIMEFRAME ANALYSIS - {symbol} - {strategy}\n"
        results_text += "=" * 60 + "\n\n"

        for timeframe, result in results.items():
            if 'error' in result:
                results_text += f"{timeframe:4} | ERROR: {result['error']}\n"
            else:
                metrics = result['metrics']
                results_text += (
                    f"{timeframe:4} | "
                    f"Trades: {metrics['total_trades']:3} | "
                    f"Win: {metrics['win_rate']:5.1%} | "
                    f"PnL: ${metrics['total_pnl']:7.2f} | "
                    f"Sharpe: {metrics['sharpe_ratio']:5.2f} | "
                    f"DD: {metrics['max_drawdown']:5.1%}\n"
                )

        self.results_text.config(state="normal")
        self.results_text.delete(1.0, tk.END)
        self.results_text.insert(1.0, results_text)
        self.results_text.config(state="disabled")

        self.status_label.configure(text="✅ Multi-timeframe analysis completed")

    def _get_strategy_parameters(self, strategy: str) -> Dict[str, Any]:
        """Get default parameters for strategy"""
        base_params = {
            'risk_per_trade': 0.02,
            'stop_loss_multiplier': 2.0,
            'risk_reward_ratio': 2.0
        }

        if 'Bollinger' in strategy:
            base_params.update({'period': 20, 'std': 2})
        elif 'RSI' in strategy:
            base_params.update({'rsi_period': 14, 'oversold': 30, 'overbought': 70})
        elif 'MACD' in strategy:
            base_params.update({'fast': 12, 'slow': 26, 'signal': 9})
        elif 'Moving Average' in strategy:
            base_params.update({'fast': 20, 'slow': 50})
        elif 'Channel' in strategy:
            base_params.update({'period': 20})
        elif 'Volatility' in strategy:
            base_params.update({'atr_period': 14, 'multiplier': 2.0})

        return base_params

    def clear_results(self):
        """Clear all results"""
        self.results_text.config(state="normal")
        self.results_text.delete(1.0, tk.END)
        self.results_text.config(state="disabled")

        self.analysis_text.config(state="normal")
        self.analysis_text.delete(1.0, tk.END)
        self.analysis_text.config(state="disabled")

        # Clear charts
        self.ax1.clear()
        self.ax2.clear()
        self.canvas.draw()

        self.status_label.configure(text="Ready")
        self.current_results = None


# =============================================================================
# APPLICATION LAUNCH
# =============================================================================

if __name__ == "__main__":
    print("🚀 LAUNCHING BAR-BASED BACKTESTING PLATFORM...")
    print("📊 INITIALIZING TVDATAFEED...")
    print("⚡ SETTING UP BAR-BASED DATA COLLECTION...")
    print("🔄 CONFIGURING MULTI-TIMEFRAME ANALYSIS...")

    try:
        app = BarBasedBacktestApp()
        app.mainloop()
    except Exception as e:
        print(f"❌ Application failed to start: {e}")
        traceback.print_exc()