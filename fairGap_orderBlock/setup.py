# setup_minimal.py
import sys
from cx_Freeze import setup, Executable
import os

# Application information
APP_NAME = "Advanced MT5 Trading Bot"
VERSION = "1.0"
DESCRIPTION = "Advanced trading bot with Super OB/FVG and Range Filter strategies"
AUTHOR = "Yassir Tagemouati"

# Minimal build options - let cx_Freeze auto-detect dependencies
build_exe_options = {
    "packages": ["pandas", "numpy", "tvDatafeed", "MetaTrader5", "customtkinter"],
    "excludes": ["tkinter.test", "unittest", "pytest", "test"],
    "optimize": 2,
    "include_msvcr": True,
}

# Add files that exist
include_files = []
for file in ["trading_config_tool5_v7.json", "users_config_tool5_v7.json",
             "trade_history_tool5_v7.csv", "icon_trading.ico", "icon_notif.ico"]:
    if os.path.exists(file):
        include_files.append(file)

if include_files:
    build_exe_options["include_files"] = include_files

base = None
if sys.platform == "win32":
    base = "Win32GUI"

executable = Executable(
    script="tool5_v7.py",
    base=base,
    target_name="AdvancedTradingBot.exe"
)

setup(
    name=APP_NAME,
    version=VERSION,
    description=DESCRIPTION,
    author=AUTHOR,
    options={"build_exe": build_exe_options},
    executables=[executable]
)