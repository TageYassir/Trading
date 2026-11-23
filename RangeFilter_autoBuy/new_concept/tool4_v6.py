import os
import time
import threading
from datetime import datetime, timedelta
from collections import deque
import pandas as pd
import MetaTrader5 as mt5
from tvDatafeed import TvDatafeed, Interval

# --------------------------
# Configuration / Trade Model
# --------------------------
class TradingConfig:
    def __init__(self):
        self.symbols = ["EURUSD", "GBPUSD", "USDJPY"]  # example
        self.strength_threshold = 0.5
        self.min_bars_hold = 3
        self.max_daily_loss_pct = 5.0
        self.volatility_lookback = 20
        self.risk_reward_ratio = 2.0
        self.capital = 10000
        self.buy_mode = True
        self.sell_mode = True
        self.trading_active = False
        self.account = None
        self.password = None
        self.server = None
        self.regime_window = 5
        self.max_recent_loss = 50  # max loss in recent trades to skip signal

class Trade:
    def __init__(self, symbol, trade_type, entry_time, entry_price, volume=0.01, status="OPEN", stop_loss=None, take_profit=None, profit=0.0, exit_time=None, exit_price=None, reason=None):
        self.symbol = symbol
        self.trade_type = trade_type
        self.entry_time = entry_time
        self.entry_price = entry_price
        self.volume = volume
        self.status = status
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.profit = profit
        self.exit_time = exit_time
        self.exit_price = exit_price
        self.reason = reason

TRADES_FILE = "trades_history.csv"

# --------------------------
# Strategy (placeholder)
# --------------------------
class AdaptiveRangeFilterStrategy:
    def __init__(self, log_callback):
        self.log_callback = log_callback
        self.performance_history = []

    def log(self, message):
        self.log_callback(message)

    def get_adaptive_signal(self, df, symbol, config):
        # Example placeholder: simple moving average crossover
        if len(df) < 10:
            return "NO_SIGNAL", 0.0
        short_ma = df['close'].rolling(5).mean().iloc[-1]
        long_ma = df['close'].rolling(10).mean().iloc[-1]
        strength = abs(short_ma - long_ma) / long_ma
        if short_ma > long_ma:
            return "BUY", strength
        elif short_ma < long_ma:
            return "SELL", strength
        return "NO_SIGNAL", 0.0

    def update_performance(self, profit):
        self.performance_history.append(profit)

# --------------------------
# MT5 Wrapper
# --------------------------
class EnhancedMT5Trader:
    def __init__(self):
        self.daily_pnl = 0.0

    def connect(self, account=None, password=None, server=None):
        return mt5.initialize(login=account, password=password, server=server)

    def disconnect(self):
        mt5.shutdown()

    def get_open_positions(self):
        return mt5.positions_get() or []

    def get_symbol_info(self, symbol):
        return mt5.symbol_info(symbol)

    def place_order_simple(self, symbol, order_type, volume):
        try:
            tick = mt5.symbol_info_tick(symbol)
            price = tick.ask if order_type == "BUY" else tick.bid
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": volume,
                "type": mt5.ORDER_TYPE_BUY if order_type=="BUY" else mt5.ORDER_TYPE_SELL,
                "price": price,
                "deviation": 10,
                "magic": 123456,
                "comment": "adaptive bot",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            result = mt5.order_send(request)
            return result.retcode == mt5.TRADE_RETCODE_DONE
        except:
            return False

    def place_order(self, symbol, order_type, volume, sl_distance, tp_distance):
        try:
            tick = mt5.symbol_info_tick(symbol)
            price = tick.ask if order_type=="BUY" else tick.bid
            sl = price - sl_distance if order_type=="BUY" else price + sl_distance
            tp = price + tp_distance if order_type=="BUY" else price - tp_distance
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": volume,
                "type": mt5.ORDER_TYPE_BUY if order_type=="BUY" else mt5.ORDER_TYPE_SELL,
                "price": price,
                "sl": sl,
                "tp": tp,
                "deviation": 10,
                "magic": 123456,
                "comment": "adaptive bot",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            result = mt5.order_send(request)
            return result.retcode == mt5.TRADE_RETCODE_DONE
        except:
            return False

    def close_all_positions(self, symbol):
        positions = [p for p in self.get_open_positions() if p.symbol==symbol]
        success = True
        for p in positions:
            order_type = mt5.ORDER_TYPE_SELL if p.type==mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
            if not self.place_order_simple(symbol, "SELL" if p.type==mt5.ORDER_TYPE_BUY else "BUY", p.volume):
                success = False
        return success

    def get_daily_loss_pct(self, capital):
        return max(0, -self.daily_pnl / capital * 100)

# --------------------------
# Adaptive Trading Engine
# --------------------------
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

    def log(self, message):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_message = f"[{timestamp}] {message}"
        self.log_callback(log_message)
        print(log_message)

    def load_trade_history(self):
        try:
            if os.path.exists(TRADES_FILE):
                df = pd.read_csv(TRADES_FILE)
                for _, trade in df.iterrows():
                    if trade['status'] == 'CLOSED':
                        self.strategy.update_performance(trade['profit'])
                self.log(f"Loaded {len(df)} historical trades")
        except Exception as e:
            self.log(f"Error loading trade history: {e}")

    def initialize_signal_history(self):
        for symbol in self.config.symbols:
            self.signal_history[symbol] = deque(maxlen=10)

    def save_trade(self, trade: Trade):
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
        if symbol in self.open_trades:
            trade = self.open_trades[symbol]
            trade.exit_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            trade.exit_price = exit_price
            trade.status = "CLOSED"
            trade.reason = reason

            if trade.trade_type == "BUY":
                trade.profit = (exit_price - trade.entry_price) * trade.volume * 100000
            else:
                trade.profit = (trade.entry_price - exit_price) * trade.volume * 100000

            self.strategy.update_performance(trade.profit)
            self.save_trade(trade)
            del self.open_trades[symbol]
            self.log(f"Trade closed: {symbol} {trade.trade_type} Profit: ${trade.profit:.2f} Reason: {reason}")

    def get_symbol_data(self, symbol, retry_count=3):
        for attempt in range(retry_count):
            try:
                for exchange in ["OANDA", "FX_IDC", "FXCM"]:
                    try:
                        df = self.tv.get_hist(symbol=symbol, exchange=exchange,
                                              interval=Interval.in_5_minute, n_bars=100)
                        if df is not None and not df.empty and len(df) > 20:
                            if df['close'].isna().sum() == 0 and df['close'].iloc[-1] > 0:
                                return df
                    except:
                        continue
                if attempt < retry_count - 1:
                    time.sleep(2)
            except Exception as e:
                self.log(f"Attempt {attempt + 1} failed for {symbol}: {e}")
                if attempt < retry_count - 1:
                    time.sleep(2)
        self.log(f"❌ Failed to get data for {symbol}")
        return None

    # --------------------------
    # Signal & Entry Logic
    # --------------------------
    def get_current_signal(self, symbol):
        df = self.get_symbol_data(symbol)
        if df is None or df.empty:
            return "NO_SIGNAL", 0.0

        signal, raw_strength = self.strategy.get_adaptive_signal(df, symbol, self.config)
        vol = df['close'].pct_change().rolling(self.config.volatility_lookback).std().iloc[-1]
        strength = raw_strength / (vol + 1e-6)
        strength = min(strength, 1.0)
        self.signal_history[symbol].append((signal, strength, datetime.now()))
        return signal, strength

    def performance_filter(self, symbol):
        last_n_profits = [t.profit for t in self.trade_history if t.symbol==symbol][-self.config.regime_window:]
        if len(last_n_profits) >= self.config.regime_window:
            avg_perf = sum(last_n_profits)/len(last_n_profits)
            if avg_perf < -self.config.max_recent_loss:
                return False, "Recent trades losing → market regime unfavorable"
        return True, "OK"

    def should_enter_trade(self, symbol, signal, strength):
        if symbol in self.last_trade_time:
            if datetime.now() - self.last_trade_time[symbol] < self.cooldown_period:
                return False, "In cooldown period"

        daily_loss_pct = self.mt5_trader.get_daily_loss_pct(self.config.capital)
        if daily_loss_pct >= self.config.max_daily_loss_pct:
            return False, f"Daily loss limit reached: {daily_loss_pct:.1f}%"

        recent_signals = list(self.signal_history[symbol])
        if len(recent_signals) >= self.config.min_bars_hold:
            recent_types = [s[0] for s in recent_signals[-self.config.min_bars_hold:]]
            if recent_types.count(signal) < self.config.min_bars_hold // 2 + 1:
                return False, f"Signal not confirmed over last {self.config.min_bars_hold} bars"

        vol = self.tv.get_hist(symbol, Interval.in_5_minute, n_bars=self.config.volatility_lookback)['close'].pct_change().std()
        adaptive_threshold = self.config.strength_threshold * (1 + vol*5)
        if strength < adaptive_threshold:
            return False, f"Signal below adaptive threshold {adaptive_threshold:.2f}"

        perf_ok, perf_reason = self.performance_filter(symbol)
        if not perf_ok:
            return False, perf_reason

        return True, "OK"

    def calculate_adaptive_stop_loss_take_profit(self, symbol, price, order_type, strength):
        df = self.get_symbol_data(symbol)
        vol = df['close'].pct_change().rolling(self.config.volatility_lookback).std().iloc[-1]
        sl_distance = max(price * 0.001, vol * price * 2)
        tp_distance = sl_distance * self.config.risk_reward_ratio
        return sl_distance, tp_distance

    # --------------------------
    # Trading Execution
    # --------------------------
    def execute_adaptive_action(self, symbol, signal, strength):
        try:
            ok, reason = self.should_enter_trade(symbol, signal, strength)
            if not ok:
                self.log(f"⏸️ Skipping {symbol} due to: {reason}")
                return

            positions = self.mt5_trader.get_open_positions()
            current_positions = [p for p in positions if p.symbol == symbol]

            if signal=="BUY" and self.config.buy_mode:
                existing_buy = any(p.type==mt5.ORDER_TYPE_BUY for p in current_positions)
                if existing_buy: return
                sell_positions = [p for p in current_positions if p.type==mt5.ORDER_TYPE_SELL]
                if sell_positions:
                    self.mt5_trader.close_all_positions(symbol)
                self.open_adaptive_trade(symbol, "BUY", strength)

            elif signal=="SELL" and self.config.sell_mode:
                existing_sell = any(p.type==mt5.ORDER_TYPE_SELL for p in current_positions)
                if existing_sell: return
                buy_positions = [p for p in current_positions if p.type==mt5.ORDER_TYPE_BUY]
                if buy_positions:
                    self.mt5_trader.close_all_positions(symbol)
                self.open_adaptive_trade(symbol, "SELL", strength)

        except Exception as e:
            self.log(f"Error executing adaptive action for {symbol}: {e}")

    def open_adaptive_trade(self, symbol, order_type, strength):
        try:
            tick = mt5.symbol_info_tick(symbol)
            if not tick: return
            current_price = tick.ask if order_type=="BUY" else tick.bid
            volume = 0.01

            sl_distance, tp_distance = self.calculate_adaptive_stop_loss_take_profit(symbol, current_price, order_type, strength)
            result = self.mt5_trader.place_order(symbol, order_type, volume, sl_distance, tp_distance)

            if result:
                trade = Trade(
                    symbol=symbol,
                    trade_type=order_type,
                    entry_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    entry_price=current_price,
                    volume=volume,
                    stop_loss=current_price - sl_distance if order_type=="BUY" else current_price + sl_distance,
                    take_profit=current_price + tp_distance if order_type=="BUY" else current_price - tp_distance
                )
                self.open_trades[symbol] = trade
                self.last_trade_time[symbol] = datetime.now()
                self.log(f"✅ Opened {order_type} for {symbol} at {current_price:.5f}")

        except Exception as e:
            self.log(f"❌ Error opening trade for {symbol}: {e}")

    def check_for_closed_positions(self):
        try:
            positions = self.mt5_trader.get_open_positions()
            current_symbols = {p.symbol for p in positions}
            for symbol in list(self.open_trades.keys()):
                if symbol not in current_symbols:
                    tick = mt5.symbol_info_tick(symbol)
                    exit_price = tick.bid if self.open_trades[symbol].trade_type=="BUY" else tick.ask
                    self.update_closed_trade(symbol, exit_price, "Auto Close (SL/TP)")
        except Exception as e:
            self.log(f"Error checking for closed positions: {e}")

    # --------------------------
    # Trading Loop
    # --------------------------
    def start_trading(self):
        if not self.mt5_trader.connect(account=self.config.account, password=self.config.password, server=self.config.server):
            self.log("Failed to connect to MT5")
            return False
        self.running = True
        self.log("🟢 Adaptive Trading Engine Started")
        return True

    def stop_trading(self):
        self.running = False
        self.mt5_trader.disconnect()
        self.log("🔴 Trading Engine Stopped")

    def execute_trading_cycle(self):
        if not self.config.trading_active: return
        try:
            self.check_for_closed_positions()
            for symbol in self.config.symbols:
                signal, strength = self.get_current_signal(symbol)
                if signal != "NO_SIGNAL":
                    self.log(f"📈 {symbol}: {signal} (Strength: {strength:.2f})")
                    self.execute_adaptive_action(symbol, signal, strength)
        except Exception as e:
            self.log(f"Error in trading cycle: {e}")

# --------------------------
# UI / App Placeholder
# --------------------------
class TradingApp:
    def __init__(self):
        self.config = TradingConfig()
    def log_message(self, msg):
        print(msg)

# --------------------------
# Main
# --------------------------
if __name__ == "__main__":
    app = TradingApp()
    engine = AdaptiveTradingEngine(app.config, app.log_message)
    if engine.start_trading():
        while True:
            engine.execute_trading_cycle()
            time.sleep(60)  # run cycle every 1 minute






# only generated logic not working !!!!!!!!!!!!!!!!!!!!!!!
