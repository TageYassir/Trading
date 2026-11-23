# setup.py for cx_Freeze - builds a single-folder GUI exe for the lot-size calculator app
# Adjust MAIN_SCRIPT and ICON_PATH if your filenames differ.

import sys
from cx_Freeze import setup, Executable

# ---- Edit these to match your project ----
APP_NAME = "Lot Size Calculator"
VERSION = "1.0"
DESCRIPTION = "Forex Lot Size Calculator"
AUTHOR = "Yassir Tagemouati"
# Preferred icon: app_icon.ico (place in the same folder). If you have a PNG, cx_Freeze will include it but Windows prefers .ico.
ICON_PATH = "app_icon.ico"
MAIN_SCRIPT = "tool_v2.py"  # <- change to your main script (e.g., tool_v1.py)
TARGET_NAME = "LotSizeCalculator.exe"
# -----------------------------------------

# Include packages used by your script. Add any other modules you import.
build_exe_options = {
    "packages": [
        "os",
        "sys",
        "tkinter",
        "customtkinter",
        "PIL",          # pillow (if using PNG icons)
        "pandas",       # if your app uses pandas
        # add other heavy dependencies here if required, e.g. "tvDatafeed"
    ],
    "includes": [
        "tkinter",
        "customtkinter",
        "PIL",
        # list other modules that cx_Freeze may not auto-detect
    ],
    "excludes": [
        "tkinter.test",
        # add modules to exclude if you run into packaging conflicts
    ],
    "include_files": [
        # Include icon so it is bundled with the exe
        (ICON_PATH, ICON_PATH),
        # Add any additional resource files here, e.g. ("data/config.json", "config.json")
    ],
    "optimize": 2,
}

# On Windows, use Win32GUI to avoid a console window
base = None
if sys.platform == "win32":
    base = "Win32GUI"

executable = Executable(
    script=MAIN_SCRIPT,
    base=base,
    target_name=TARGET_NAME,
    icon=ICON_PATH if ICON_PATH else None
)

setup(
    name=APP_NAME,
    version=VERSION,
    description=DESCRIPTION,
    author=AUTHOR,
    options={"build_exe": build_exe_options},
    executables=[executable]
)