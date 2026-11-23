import MetaTrader5 as mt5

# Initialize MT5
if not mt5.initialize():
    print("Failed to initialize MT5, error code:", mt5.last_error())
    exit()

# Login to MT5
account = 5049720938
password = "8tSqF!Bx"
server = "MetaQuotes-Demo"
if not mt5.login(account, password, server):
    print("Failed to login, error code:", mt5.last_error())
    mt5.shutdown()
    exit()

# Define the symbol
symbol = "ETH"

# Check if the symbol is available
si = mt5.symbol_info(symbol)
if si is None:
    print(f"Symbol {symbol} not found, cannot proceed")
    mt5.shutdown()
    exit()

# Ensure the symbol is selected
if not mt5.symbol_select(symbol, True):
    print(f"Failed to select symbol {symbol}")
    mt5.shutdown()
    exit()

# Print symbol information
print(f"Symbol: {symbol}")
print(f"Volume min: {si.volume_min}, step: {si.volume_step}")

# Calculate the volume
vol_step = si.volume_step
min_vol = si.volume_min
volume = max(min_vol, round(0.1 / vol_step) * vol_step)
print(f"Volume: {volume}")

# Get the latest tick data
tick = mt5.symbol_info_tick(symbol)
if tick is None:
    print(f"Failed to get tick data for {symbol}")
    mt5.shutdown()
    exit()

print(f"Bid: {tick.bid}, Ask: {tick.ask}")

# Create a trade request
request = {
    "action": mt5.TRADE_ACTION_DEAL,
    "symbol": symbol,
    "volume": volume,
    "type": mt5.ORDER_TYPE_BUY,
    "price": tick.ask,
    "deviation": 20,
    "type_filling": mt5.ORDER_FILLING_FOK,
    "type_time": mt5.ORDER_TIME_GTC,
}

# Send the trade request
result = mt5.order_send(request)
if result is None:
    print("Failed to send order, error code:", mt5.last_error())
else:
    print(f"Retcode: {result.retcode}, Comment: {result.comment}")

    # Handle specific retcodes
    if result.retcode == 10009:
        print("SUCCESS - Trade executed!")
    elif result.retcode == 10018:
        print("Market is closed right now")
    elif result.retcode == 10030:
        print("Try ORDER_FILLING_IOC instead")

# Shutdown MT5
mt5.shutdown()
