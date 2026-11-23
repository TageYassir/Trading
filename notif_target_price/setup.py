# setup.py
import sys
from cx_Freeze import setup, Executable

APP_NAME = "Target Price Email Notifier"
VERSION = "1.0"
DESCRIPTION = "Trading notifier app using TradingView data with email alerts"
AUTHOR = "Yassir Tagemouati"
ICON_PATH = "icon_notif.ico"  # Make sure this file exists in your project directory

build_exe_options = {
    "packages": [
        "os", "sys", "tkinter", "pandas", "tvDatafeed",
        "re", "urllib", "json", "smtplib", "email", "threading", "time"
    ],
    "includes": [
        "tkinter", "pandas", "tvDatafeed", "re", "urllib", "json", "smtplib", "email", "threading", "time"
    ],
    "include_files": [(ICON_PATH, "icon_notif.ico")],
    "excludes": ["tkinter.test"],
    "optimize": 2
}

base = None
if sys.platform == "win32":
    base = "Win32GUI"  # This prevents a console window from appearing

executable = Executable(
    script="tool_v1.py",  # Replace with your main Python script filename
    base=base,
    target_name="NotifTargetPrice.exe",
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
