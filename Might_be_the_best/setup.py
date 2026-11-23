# setup_minimal_backtest.py
import sys
from cx_Freeze import setup, Executable
import os

# Application information
APP_NAME = "Institutional Backtesting Platform"
VERSION = "1.0.0"
DESCRIPTION = "Professional Trading Strategy Backtesting"

# Minimal build options - let cx_Freeze auto-detect
build_exe_options = {
    "packages": ["os", "sys", "tkinter", "asyncio", "threading"],
    "excludes": ["tkinter.test", "unittest", "pytest"],
    "optimize": 2,
    "include_msvcr": True,
}

base = None
if sys.platform == "win32":
    base = "Win32GUI"

executable = Executable(
    script="extra_v4.py",  # Your main app file
    base=base,
    target_name="InstitutionalBacktest.exe"
)

setup(
    name=APP_NAME,
    version=VERSION,
    description=DESCRIPTION,
    author="Institutional Quant Team",
    options={"build_exe": build_exe_options},
    executables=[executable]
)