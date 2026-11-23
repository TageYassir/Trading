# try_two_accounts.py
import time
import MetaTrader5 as mt5
import os

# Optional: set path to your terminal executable if you have multiple MT5 installs.
# If you leave it as None the API will try to connect to a running terminal.
terminal_path = None  # e.g. r"C:\Program Files\MetaTrader 5\terminal64.exe"

# Your two accounts (as you provided)
account_a = {
    "login": 5049720938,
    "password": "8tSqF!Bx",
    "server": "MetaQuotes-Demo",
}

account_b = {
    "login": 1062688336,
    "password": "FpL-lq4v",
    "server": "MetaQuotes-Demo",
}

def init_mt5(path=None):
    try:
        mt5.shutdown()
    except Exception:
        pass
    if path:
        ok = mt5.initialize(path=path)
    else:
        ok = mt5.initialize()
    print("initialize ->", ok, "last_error:", mt5.last_error())
    return ok

def try_login(acc):
    try:
        res = mt5.login(int(acc["login"]), acc["password"], acc.get("server", ""))
    except Exception as e:
        print("mt5.login raised exception:", e)
        return False, mt5.last_error()
    le = mt5.last_error()
    return bool(res), le

def show_account_info():
    try:
        info = mt5.account_info()
        print("account_info:", info)
    except Exception as e:
        print("account_info() error:", e)

def test_account(acc, path=None):
    print("\n=== Testing account:", acc["login"], "===\n")
    ok = init_mt5(path)
    if not ok:
        print("initialize failed; try starting MT5 GUI and/or set terminal_path to the terminal exe.")
        return
    logged, last_err = try_login(acc)
    print("login result:", logged, "last_error:", last_err)
    if logged:
        show_account_info()
        # fetch positions as a quick check
        try:
            pos = mt5.positions_get()
            print("positions:", pos)
        except Exception as e:
            print("positions_get() error:", e)
    else:
        print("Programmatic login failed for account", acc["login"])
        print("Suggestion: Open MT5 desktop terminal, log in to that account manually (use trading password), close any modal dialogs, then run:")
        print("  mt5.shutdown(); mt5.initialize(); print(mt5.account_info()); print(mt5.positions_get())")
    # leave mt5 initialized so caller can shutdown or reuse
    mt5.shutdown()
    time.sleep(0.5)

if __name__ == "__main__":
    if not hasattr(mt5, "__version__"):
        print("MetaTrader5 module not available. Install with: python -m pip install MetaTrader5")
        raise SystemExit(1)

    print("MT5 module version:", mt5.__version__)
    # First account
    test_account(account_a, terminal_path)
    # Second account
    test_account(account_b, terminal_path)
    print("\nDone. Remember to remove/rotate credentials if needed.")