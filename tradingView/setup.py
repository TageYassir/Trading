# setup.py
import sys
from cx_Freeze import setup, Executable

APP_NAME = "TradingView Data Loader"
VERSION = "1.2"
DESCRIPTION = "Application conviviale pour charger et visualiser des données TradingView"
AUTHOR = "Yassir Tagemouati"
ICON_PATH = "TradingViewLoader/icon_trading.ico"  # Make sure this file exists in your project directory



build_exe_options = {
    "packages": [
        "os", "sys", "tkinter", "customtkinter", "matplotlib", "tvDatafeed",
        "pandas", "re", "urllib", "json", "datetime", "mplfinance"
    ],
    "includes": [
        "tkinter", "customtkinter", "matplotlib", "tvDatafeed",
        "pandas", "re", "urllib", "json", "datetime", "mplfinance"
    ],
    "include_files": [(ICON_PATH, "icon_trading.ico")],
    "excludes": ["tkinter.test"],
    "optimize": 2
}

base = None
if sys.platform == "win32":
    base = "Win32GUI"

executable = Executable(
    script="tool_v22.py",
    base=base,
    target_name="TradingViewDataLoader.exe",
    icon=ICON_PATH
)

setup(
    name=APP_NAME,
    version=VERSION,
    description=DESCRIPTION,
    author=AUTHOR,
    options={"build_exe": build_exe_options},
    executables=[executable]
)