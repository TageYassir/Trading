"""
Ultra Simple Wave Pattern Detector using tvDatafeed
Direct TradingView data + ML-ready format
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
from pathlib import Path
import json
import warnings
warnings.filterwarnings('ignore')

# TradingView data feed - NO API KEY NEEDED!
from tvDatafeed import TvDatafeed, Interval

# For pattern detection
import talib

# For ML
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, Dense, Dropout, BatchNormalization
from tensorflow.keras.optimizers import Adam


class SuperSimpleWaveDetector:
    """
    Super simple wave pattern detector using TradingView data
    """

    def __init__(self):
        # Initialize TradingView data feed
        print("🔗 Connecting to TradingView...")
        self.tv = TvDatafeed()
        print("✅ Connected to TradingView!")

        # Available symbols dictionary
        self.symbol_map = {
            'forex': ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD',
                     'EURGBP', 'EURJPY', 'GBPJPY', 'USDCHF', 'NZDUSD'],
            'crypto': ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'XRPUSDT', 'SOLUSDT',
                      'ADAUSDT', 'DOGEUSDT', 'DOTUSDT', 'MATICUSDT', 'AVAXUSDT'],
            'stocks': ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA',
                      'META', 'NVDA', 'NFLX', 'SPY', 'QQQ'],
            'indices': ['US30', 'NAS100', 'SPX500', 'UK100', 'DAX', 'NIKKEI'],
            'commodities': ['XAUUSD', 'XAGUSD', 'CL1!', 'NG1!']
        }

        # Timeframe mapping
        self.timeframe_map = {
            '1m': Interval.in_1_minute,
            '5m': Interval.in_5_minute,
            '15m': Interval.in_15_minute,
            '30m': Interval.in_30_minute,
            '1h': Interval.in_1_hour,
            '4h': Interval.in_4_hour,
            '1d': Interval.in_daily,
            '1w': Interval.in_weekly
        }

    def get_symbols_by_type(self, symbol_type: str = 'all') -> list:
        """Get list of symbols by type"""
        if symbol_type == 'all':
            all_symbols = []
            for symbols in self.symbol_map.values():
                all_symbols.extend(symbols)
            return all_symbols
        elif symbol_type in self.symbol_map:
            return self.symbol_map[symbol_type]
        else:
            return []

    def download_data(self, symbol: str, timeframe: str = '1h',
                     bars: int = 1000) -> pd.DataFrame:
        """
        Download data from TradingView
        """
        print(f"📥 Downloading {symbol} ({timeframe})...", end="")

        try:
            # Handle different exchanges
            if symbol in self.symbol_map['forex']:
                exchange = 'OANDA'  # For forex pairs
            elif symbol in self.symbol_map['crypto']:
                exchange = 'BINANCE'  # For crypto
            elif symbol.endswith('USDT'):
                exchange = 'BINANCE'
                symbol = symbol.replace('USDT', '')  # Remove USDT for Binance
            else:
                exchange = 'NASDAQ'  # Default for stocks

            # Map timeframe
            interval = self.timeframe_map.get(timeframe, Interval.in_1_hour)

            # Get data
            data = self.tv.get_hist(
                symbol=symbol,
                exchange=exchange,
                interval=interval,
                n_bars=bars
            )

            if data is None or data.empty:
                print(" ✗ No data returned")
                return pd.DataFrame()

            # Clean and rename columns
            data = data.rename(columns={
                'open': 'Open',
                'high': 'High',
                'low': 'Low',
                'close': 'Close',
                'volume': 'Volume'
            })

            # Ensure proper data types
            data = data[['Open', 'High', 'Low', 'Close', 'Volume']]
            data = data.astype(float)

            print(f" ✓ {len(data)} bars")
            return data

        except Exception as e:
            print(f" ✗ Error: {e}")
            return pd.DataFrame()

    def detect_wave_patterns_simple(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Simple wave pattern detection
        Returns: DataFrame with 'wave_label' column
        0 = No pattern, 1 = Up wave, 2 = Down wave, 3 = Sideways
        """
        if df.empty or len(df) < 50:
            return df

        df_copy = df.copy()

        # Calculate basic indicators
        df_copy['SMA_20'] = talib.SMA(df_copy['Close'], timeperiod=20)
        df_copy['SMA_50'] = talib.SMA(df_copy['Close'], timeperiod=50)
        df_copy['RSI'] = talib.RSI(df_copy['Close'], timeperiod=14)

        # Price change
        df_copy['Returns'] = df_copy['Close'].pct_change()
        df_copy['Trend'] = df_copy['Close'].rolling(10).mean() - df_copy['Close'].rolling(30).mean()

        # Initialize labels
        df_copy['wave_label'] = 0

        # Simple wave detection logic
        for i in range(20, len(df_copy)):
            recent_prices = df_copy['Close'].iloc[i-20:i]
            recent_high = recent_prices.max()
            recent_low = recent_prices.min()
            current_price = df_copy['Close'].iloc[i]

            # Check for up wave (higher highs and higher lows)
            if i > 40:
                prev_prices = df_copy['Close'].iloc[i-40:i-20]
                prev_high = prev_prices.max()
                prev_low = prev_prices.min()

                # Up wave condition
                if (recent_high > prev_high and recent_low > prev_low and
                    current_price > df_copy['SMA_20'].iloc[i] and
                    df_copy['RSI'].iloc[i] > 50):
                    df_copy.loc[df_copy.index[i], 'wave_label'] = 1

                # Down wave condition
                elif (recent_high < prev_high and recent_low < prev_low and
                      current_price < df_copy['SMA_20'].iloc[i] and
                      df_copy['RSI'].iloc[i] < 50):
                    df_copy.loc[df_copy.index[i], 'wave_label'] = 2

        # Detect sideways (consolidation)
        for i in range(20, len(df_copy)):
            recent_prices = df_copy['Close'].iloc[i-20:i]
            price_range = recent_prices.max() - recent_prices.min()
            avg_price = recent_prices.mean()

            # Sideways if range is small (< 2% of price)
            if price_range / avg_price < 0.02 and df_copy['wave_label'].iloc[i] == 0:
                df_copy.loc[df_copy.index[i], 'wave_label'] = 3

        return df_copy.dropna()

    def create_ml_dataset(self, df: pd.DataFrame, seq_length: int = 30) -> tuple:
        """
        Create ML-ready dataset from labeled data
        Returns: X (features), y (labels)
        """
        if 'wave_label' not in df.columns:
            print("❌ No wave labels found. Run detect_wave_patterns_simple first.")
            return None, None

        # Select features
        feature_cols = ['Open', 'High', 'Low', 'Close', 'Volume',
                       'Returns', 'SMA_20', 'SMA_50', 'RSI', 'Trend']

        # Keep only columns that exist
        available_cols = [col for col in feature_cols if col in df.columns]

        if len(available_cols) < 5:
            print("❌ Not enough features available")
            return None, None

        features = df[available_cols].values
        labels = df['wave_label'].values

        # Create sequences
        X, y = [], []

        for i in range(len(features) - seq_length):
            X.append(features[i:i+seq_length])
            y.append(labels[i+seq_length-1])

        X = np.array(X)
        y = np.array(y)

        print(f"📊 Created dataset: {X.shape} sequences, {len(np.unique(y))} classes")

        return X, y

    def train_simple_model(self, X: np.ndarray, y: np.ndarray, test_size: float = 0.2):
        """
        Train a simple LSTM model
        """
        if X is None or len(X) == 0:
            print("❌ No data to train on")
            return None

        print("\n🧠 Training LSTM model...")

        # Split data
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=42, stratify=y
        )

        print(f"Training samples: {X_train.shape}")
        print(f"Test samples: {X_test.shape}")

        # Scale features
        scaler = StandardScaler()
        X_train_reshaped = X_train.reshape(-1, X_train.shape[-1])
        X_test_reshaped = X_test.reshape(-1, X_test.shape[-1])

        X_train_scaled = scaler.fit_transform(X_train_reshaped)
        X_test_scaled = scaler.transform(X_test_reshaped)

        X_train_scaled = X_train_scaled.reshape(X_train.shape)
        X_test_scaled = X_test_scaled.reshape(X_test.shape)

        # Build simple LSTM model
        model = Sequential([
            LSTM(32, return_sequences=True, input_shape=(X_train.shape[1], X_train.shape[2])),
            Dropout(0.2),

            LSTM(16, return_sequences=False),
            Dropout(0.2),

            Dense(8, activation='relu'),
            Dense(4, activation='softmax')  # 4 classes: 0,1,2,3
        ])

        model.compile(
            optimizer=Adam(learning_rate=0.001),
            loss='sparse_categorical_crossentropy',
            metrics=['accuracy']
        )

        # Train
        history = model.fit(
            X_train_scaled, y_train,
            validation_data=(X_test_scaled, y_test),
            epochs=20,
            batch_size=32,
            verbose=1
        )

        # Evaluate
        print("\n📈 Model Evaluation:")
        loss, accuracy = model.evaluate(X_test_scaled, y_test, verbose=0)
        print(f"Test Accuracy: {accuracy:.2%}")
        print(f"Test Loss: {loss:.4f}")

        return model, history, scaler

    def predict_next_wave(self, model, scaler, df: pd.DataFrame, seq_length: int = 30):
        """
        Predict the next wave pattern
        """
        if len(df) < seq_length:
            print(f"❌ Need at least {seq_length} bars for prediction")
            return None

        # Prepare latest sequence
        feature_cols = ['Open', 'High', 'Low', 'Close', 'Volume',
                       'Returns', 'SMA_20', 'SMA_50', 'RSI', 'Trend']

        available_cols = [col for col in feature_cols if col in df.columns]
        latest_data = df[available_cols].iloc[-seq_length:].values

        # Scale
        latest_scaled = scaler.transform(latest_data.reshape(-1, len(available_cols)))
        latest_scaled = latest_scaled.reshape(1, seq_length, len(available_cols))

        # Predict
        prediction = model.predict(latest_scaled, verbose=0)
        predicted_class = np.argmax(prediction[0])

        # Class labels
        class_names = {
            0: 'No Pattern',
            1: 'Up Wave ↗️',
            2: 'Down Wave ↘️',
            3: 'Sideways ↔️'
        }

        result = {
            'predicted_class': int(predicted_class),
            'class_name': class_names.get(predicted_class, 'Unknown'),
            'probabilities': {
                class_names[i]: float(prediction[0][i]) for i in range(4)
            },
            'confidence': float(np.max(prediction[0]))
        }

        return result

    def plot_wave_patterns(self, df: pd.DataFrame):
        """
        Plot price with wave pattern labels
        """
        if 'wave_label' not in df.columns:
            print("❌ No wave labels to plot")
            return

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(15, 10),
                                       gridspec_kw={'height_ratios': [3, 1]})

        # Plot price
        ax1.plot(df.index, df['Close'], label='Price', color='blue', alpha=0.7)
        ax1.plot(df.index, df['SMA_20'], label='SMA 20', color='orange', alpha=0.7)
        ax1.plot(df.index, df['SMA_50'], label='SMA 50', color='green', alpha=0.7)

        # Highlight wave patterns
        up_waves = df[df['wave_label'] == 1]
        down_waves = df[df['wave_label'] == 2]
        sideways = df[df['wave_label'] == 3]

        ax1.scatter(up_waves.index, up_waves['Close'],
                   color='green', s=50, label='Up Wave', marker='^')
        ax1.scatter(down_waves.index, down_waves['Close'],
                   color='red', s=50, label='Down Wave', marker='v')
        ax1.scatter(sideways.index, sideways['Close'],
                   color='yellow', s=50, label='Sideways', marker='s')

        ax1.set_title('Price with Wave Patterns')
        ax1.set_ylabel('Price')
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        # Plot RSI
        ax2.plot(df.index, df['RSI'], color='purple', label='RSI')
        ax2.axhline(y=70, color='r', linestyle='--', alpha=0.5)
        ax2.axhline(y=30, color='g', linestyle='--', alpha=0.5)
        ax2.fill_between(df.index, 30, 70, alpha=0.1, color='gray')
        ax2.set_ylabel('RSI')
        ax2.set_ylim(0, 100)
        ax2.legend()
        ax2.grid(True, alpha=0.3)

        plt.tight_layout()
        plt.show()

        # Print statistics
        total = len(df)
        up_count = len(up_waves)
        down_count = len(down_waves)
        side_count = len(sideways)
        no_pattern = total - (up_count + down_count + side_count)

        print(f"\n📊 Pattern Statistics:")
        print(f"Total bars: {total}")
        print(f"Up waves: {up_count} ({up_count/total:.1%})")
        print(f"Down waves: {down_count} ({down_count/total:.1%})")
        print(f"Sideways: {side_count} ({side_count/total:.1%})")
        print(f"No pattern: {no_pattern} ({no_pattern/total:.1%})")


# ============================================================================
# SUPER SIMPLE INTERFACE
# ============================================================================

def run_quick_wave_detection():
    """
    One-click wave detection - SUPER SIMPLE!
    """
    print("""
    ╔══════════════════════════════════════════════╗
    ║      SUPER SIMPLE WAVE DETECTOR             ║
    ║      Using TradingView Data                 ║
    ╚══════════════════════════════════════════════╝
    """)

    # Create detector
    detector = SuperSimpleWaveDetector()

    # Step 1: Select symbol
    print("\n" + "="*50)
    print("STEP 1: Select Symbol")
    print("="*50)

    print("\nAvailable symbol types:")
    print("1. Forex (EURUSD, GBPUSD, etc.)")
    print("2. Crypto (BTCUSDT, ETHUSDT, etc.)")
    print("3. Stocks (AAPL, TSLA, etc.)")
    print("4. Indices (US30, SPX500, etc.)")
    print("5. Commodities (XAUUSD, XAGUSD)")

    type_choice = input("\nSelect type (1-5): ").strip()

    type_map = {'1': 'forex', '2': 'crypto', '3': 'stocks', '4': 'indices', '5': 'commodities'}
    symbol_type = type_map.get(type_choice, 'forex')

    symbols = detector.get_symbols_by_type(symbol_type)
    print(f"\nAvailable {symbol_type} symbols:")
    for i, sym in enumerate(symbols[:15], 1):
        print(f"{i:2}. {sym}", end='  ')
        if i % 5 == 0:
            print()

    symbol_idx = input(f"\nSelect symbol (1-{min(15, len(symbols))}) or type custom: ").strip()

    if symbol_idx.isdigit() and 1 <= int(symbol_idx) <= len(symbols):
        symbol = symbols[int(symbol_idx) - 1]
    else:
        symbol = symbol_idx.upper()

    # Step 2: Select timeframe
    print("\n" + "="*50)
    print("STEP 2: Select Timeframe")
    print("="*50)

    timeframes = list(detector.timeframe_map.keys())
    print("\nAvailable timeframes:")
    for i, tf in enumerate(timeframes, 1):
        print(f"{i}. {tf}")

    tf_idx = input(f"\nSelect timeframe (1-{len(timeframes)}): ").strip()

    if tf_idx.isdigit() and 1 <= int(tf_idx) <= len(timeframes):
        timeframe = timeframes[int(tf_idx) - 1]
    else:
        timeframe = '1h'

    # Step 3: Get data
    print("\n" + "="*50)
    print("STEP 3: Download Data")
    print("="*50)

    bars = input("\nHow many bars to download? (default 1000): ").strip()
    bars = int(bars) if bars.isdigit() else 1000

    data = detector.download_data(symbol, timeframe, bars)

    if data.empty:
        print(f"\n❌ Could not download data for {symbol}")
        return

    # Step 4: Detect wave patterns
    print("\n" + "="*50)
    print("STEP 4: Detect Wave Patterns")
    print("="*50)

    print("\n🔍 Detecting wave patterns...")
    data_with_waves = detector.detect_wave_patterns_simple(data)

    # Step 5: Show results
    print("\n" + "="*50)
    print("STEP 5: Results")
    print("="*50)

    # Plot
    detector.plot_wave_patterns(data_with_waves)

    # Step 6: Ask about ML
    print("\n" + "="*50)
    print("STEP 6: Machine Learning")
    print("="*50)

    ml_choice = input("\nDo you want to train an ML model? (y/n): ").strip().lower()

    if ml_choice == 'y':
        print("\n🧠 Creating ML dataset...")
        X, y = detector.create_ml_dataset(data_with_waves)

        if X is not None and len(X) > 0:
            print("\nTraining model (this may take a minute)...")
            model, history, scaler = detector.train_simple_model(X, y)

            # Predict next wave
            print("\n" + "="*50)
            print("PREDICT NEXT WAVE")
            print("="*50)

            prediction = detector.predict_next_wave(model, scaler, data_with_waves)

            if prediction:
                print(f"\n🎯 Next Wave Prediction for {symbol}:")
                print(f"   Pattern: {prediction['class_name']}")
                print(f"   Confidence: {prediction['confidence']:.1%}")
                print(f"\nProbabilities:")
                for pattern, prob in prediction['probabilities'].items():
                    print(f"   {pattern}: {prob:.1%}")

    # Save data option
    save_choice = input("\nSave data to CSV? (y/n): ").strip().lower()
    if save_choice == 'y':
        filename = f"{symbol}_{timeframe}_{datetime.now().strftime('%Y%m%d')}.csv"
        data_with_waves.to_csv(filename)
        print(f"✅ Data saved to {filename}")


def run_batch_processing():
    """
    Process multiple symbols at once
    """
    print("\n🔄 BATCH PROCESSING MODE")
    print("-" * 40)

    detector = SuperSimpleWaveDetector()

    # Get symbol type
    print("\nSymbol types:")
    print("1. Forex")
    print("2. Crypto")
    print("3. Stocks")
    print("4. All (mix)")

    choice = input("\nSelect type: ").strip()

    if choice == '1':
        symbols = detector.symbol_map['forex'][:5]
    elif choice == '2':
        symbols = detector.symbol_map['crypto'][:5]
    elif choice == '3':
        symbols = detector.symbol_map['stocks'][:5]
    else:
        symbols = []
        for sym_list in detector.symbol_map.values():
            symbols.extend(sym_list[:2])

    timeframe = input("\nTimeframe (default 4h): ").strip() or '4h'
    bars = input("Bars per symbol (default 500): ").strip()
    bars = int(bars) if bars.isdigit() else 500

    print(f"\nProcessing {len(symbols)} symbols...")
    print("-" * 40)

    all_predictions = []

    for symbol in symbols:
        print(f"\n📊 Processing {symbol}...")

        try:
            # Get data
            data = detector.download_data(symbol, timeframe, bars)
            if data.empty:
                continue

            # Detect waves
            data_with_waves = detector.detect_wave_patterns_simple(data)

            # Create ML dataset
            X, y = detector.create_ml_dataset(data_with_waves)

            if X is not None and len(X) > 0:
                # Train quick model
                model, history, scaler = detector.train_simple_model(X, y)

                # Predict
                prediction = detector.predict_next_wave(model, scaler, data_with_waves)

                if prediction:
                    all_predictions.append({
                        'symbol': symbol,
                        'prediction': prediction['class_name'],
                        'confidence': prediction['confidence']
                    })

                    print(f"   Prediction: {prediction['class_name']} ({prediction['confidence']:.1%})")

        except Exception as e:
            print(f"   Error: {e}")
            continue

    # Show summary
    if all_predictions:
        print("\n" + "="*50)
        print("BATCH RESULTS SUMMARY")
        print("="*50)

        for pred in all_predictions:
            print(f"{pred['symbol']:10} → {pred['prediction']:15} ({pred['confidence']:.1%})")


def real_time_monitoring():
    """
    Simple real-time wave monitoring
    """
    print("\n⏰ REAL-TIME WAVE MONITOR")
    print("-" * 40)

    detector = SuperSimpleWaveDetector()

    symbol = input("Symbol to monitor (e.g., BTCUSDT): ").strip() or "BTCUSDT"
    timeframe = input("Timeframe (e.g., 15m): ").strip() or "15m"

    print(f"\nMonitoring {symbol} on {timeframe} timeframe...")
    print("Press Ctrl+C to stop")
    print("-" * 40)

    try:
        while True:
            # Get latest data
            data = detector.download_data(symbol, timeframe, bars=200)

            if not data.empty:
                # Detect waves
                data_with_waves = detector.detect_wave_patterns_simple(data)

                # Get latest wave
                latest_wave = data_with_waves['wave_label'].iloc[-1]

                wave_names = {
                    0: 'No Pattern',
                    1: 'Up Wave ↗️',
                    2: 'Down Wave ↘️',
                    3: 'Sideways ↔️'
                }

                current_time = datetime.now().strftime("%H:%M:%S")
                print(f"[{current_time}] {symbol}: {wave_names.get(latest_wave, 'Unknown')} "
                      f"| Price: {data['Close'].iloc[-1]:.2f}")

            # Wait before next update
            import time
            time.sleep(60)  # Update every minute

    except KeyboardInterrupt:
        print("\n\n👋 Monitoring stopped")


# ============================================================================
# ONE-CLICK EXAMPLE
# ============================================================================

def one_click_example():
    """
    Run everything with one click - perfect for testing!
    """
    print("\n🚀 ONE-CLICK WAVE DETECTION EXAMPLE")
    print("="*60)

    detector = SuperSimpleWaveDetector()

    # Use EURUSD as example
    symbol = "EURUSD"
    timeframe = "4h"

    print(f"\n1. Downloading {symbol} {timeframe} data...")
    data = detector.download_data(symbol, timeframe, 1000)

    if data.empty:
        print("❌ Failed to get data. Trying BTCUSDT instead...")
        symbol = "BTCUSDT"
        data = detector.download_data(symbol, timeframe, 1000)

    print(f"\n2. Detecting wave patterns in {symbol}...")
    data_with_waves = detector.detect_wave_patterns_simple(data)

    print(f"\n3. Plotting results...")
    detector.plot_wave_patterns(data_with_waves)

    print(f"\n4. Creating ML dataset...")
    X, y = detector.create_ml_dataset(data_with_waves)

    if X is not None and len(X) > 0:
        print(f"\n5. Training model...")
        model, history, scaler = detector.train_simple_model(X, y)

        print(f"\n6. Predicting next wave...")
        prediction = detector.predict_next_wave(model, scaler, data_with_waves)

        if prediction:
            print(f"\n🎯 FINAL PREDICTION:")
            print(f"   Next pattern for {symbol}: {prediction['class_name']}")
            print(f"   Confidence: {prediction['confidence']:.1%}")

    print(f"\n✅ Example complete! You can now:")
    print(f"   1. Try your own symbols")
    print(f"   2. Adjust parameters")
    print(f"   3. Save the model for future use")


# ============================================================================
# MAIN MENU
# ============================================================================

if __name__ == "__main__":
    print("""
    ╔══════════════════════════════════════════════════╗
    ║      TRADINGVIEW WAVE PATTERN DETECTOR          ║
    ║         Simple • Fast • ML-Ready                ║
    ╚══════════════════════════════════════════════════╝
    """)

    print("📦 Requirements: pip install tvDatafeed pandas numpy matplotlib scikit-learn tensorflow")
    print("="*70)

    print("\nMAIN MENU:")
    print("1. Quick Wave Detection (Recommended)")
    print("2. Batch Process Multiple Symbols")
    print("3. Real-time Wave Monitoring")
    print("4. One-Click Example (Try First!)")
    print("5. Custom Analysis")
    print("6. Exit")
    print("="*70)

    choice = input("\nSelect (1-6): ").strip()

    if choice == "1":
        run_quick_wave_detection()
    elif choice == "2":
        run_batch_processing()
    elif choice == "3":
        real_time_monitoring()
    elif choice == "4":
        one_click_example()
    elif choice == "5":
        # Advanced custom mode
        detector = SuperSimpleWaveDetector()
        symbol = input("\nEnter symbol: ").strip()
        timeframe = input("Timeframe: ").strip()
        bars = input("Number of bars: ").strip()

        data = detector.download_data(symbol, timeframe, int(bars) if bars.isdigit() else 500)
        if not data.empty:
            data_with_waves = detector.detect_wave_patterns_simple(data)
            detector.plot_wave_patterns(data_with_waves)
    elif choice == "6":
        print("👋 Goodbye!")
    else:
        print("Invalid choice. Running one-click example...")
        one_click_example()