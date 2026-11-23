import os
import sys
import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageTk
import customtkinter as ctk

# Make sure customtkinter default settings are set before creating widgets
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


def setup_icons(root, basename="icon_trading"):
    """
    Configure the window and taskbar icon.
    Looks for basename.ico first (preferred on Windows), then basename.png (via Pillow),
    otherwise uses a tiny blank PhotoImage as a fallback.
    Works when running normally and when bundled by PyInstaller (uses sys._MEIPASS).
    """
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    ico_path = os.path.join(base_path, f"{basename}.ico")
    png_path = os.path.join(base_path, f"{basename}.png")

    # Try .ico first (best for Windows)
    try:
        if os.path.exists(ico_path):
            try:
                root.iconbitmap(ico_path)
            except Exception as e:
                print(f"iconbitmap failed: {e}")  # Log error but continue
            else:
                if os.name == 'nt':
                    try:
                        from ctypes import windll
                        windll.shell32.SetCurrentProcessExplicitAppUserModelID('com.tagemouati.lotsizecalculator')
                    except Exception as e:
                        print(f"Failed to set AppUserModelID: {e}")
                return
        # Try PNG via Pillow
        if os.path.exists(png_path):
            try:
                img = Image.open(png_path)
                photo = ImageTk.PhotoImage(img)
                root._icon_photo = photo
                root.iconphoto(False, photo)
                return
            except Exception as e:
                print(f"Pillow icon load failed: {e}")
        # Last resort: tiny blank PhotoImage to avoid exceptions
        try:
            blank = tk.PhotoImage(width=16, height=16)
            root.iconphoto(False, blank)
            root._icon_photo = blank
        except Exception as e:
            print(f"Fallback iconphoto failed: {e}")
    except Exception as e:
        print(f"Impossible to load icon: {e}")


class LotSizeCalculator:
    ICON_BASENAME = "app_icon"  # Corrected to match setup_icons default

    def __init__(self):
        self.root = ctk.CTk()
        self.root.title("Forex Lot Size Calculator")

        fixed_width = 520
        fixed_height = 640
        self.root.geometry(f"{fixed_width}x{fixed_height}")
        self.root.resizable(False, False)
        self.root.minsize(fixed_width, fixed_height)
        self.root.maxsize(fixed_width, fixed_height)

        setup_icons(self.root, basename=self.ICON_BASENAME)
        self._build_scrollable_ui()
        self.root.bind("<Return>", lambda event: self.calculate_lot_size())

    def _build_scrollable_ui(self):
        outer = ctk.CTkFrame(self.root, corner_radius=0)
        outer.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(outer, borderwidth=0, highlightthickness=0, bg="#2b2b2b")  # Match dark theme
        self.canvas.pack(side="left", fill="both", expand=True)

        scrollbar = ctk.CTkScrollbar(outer, orientation="vertical", command=self.canvas.yview)
        scrollbar.pack(side="right", fill="y")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.container = ctk.CTkFrame(self.canvas, corner_radius=15, fg_color="#2b2b2b")
        self._container_window = self.canvas.create_window((0, 0), window=self.container, anchor="nw")

        self.container.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self._bind_mousewheel_events()
        self._populate_ui(self.container)

    def _on_canvas_configure(self, event):
        try:
            self.canvas.itemconfig(self._container_window, width=event.width)
        except Exception:
            pass

    def _bind_mousewheel_events(self):
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel_windows)
        self.canvas.bind_all("<Button-4>", self._on_mousewheel_linux)
        self.canvas.bind_all("<Button-5>", self._on_mousewheel_linux)

    def _on_mousewheel_windows(self, event):
        try:
            delta = int(-1 * (event.delta / 120))
            self.canvas.yview_scroll(delta, "units")
        except Exception:
            pass

    def _on_mousewheel_linux(self, event):
        if event.num == 4:
            self.canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self.canvas.yview_scroll(1, "units")

    def _populate_ui(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, minsize=12)

        title_frame = ctk.CTkFrame(parent, corner_radius=10)
        title_frame.grid(row=1, column=0, padx=18, pady=(8, 12), sticky="ew")
        title_frame.grid_columnconfigure(0, weight=1)

        title_label = ctk.CTkLabel(title_frame, text="Forex Lot Size Calculator",
                                   font=ctk.CTkFont(size=20, weight="bold"))
        title_label.grid(row=0, column=0, padx=12, pady=(12, 4), sticky="w")
        subtitle = ctk.CTkLabel(title_frame, text="Quick, accurate lot size & position calculations",
                                font=ctk.CTkFont(size=11))
        subtitle.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="w")

        form_frame = ctk.CTkFrame(parent, corner_radius=8, fg_color="#232629")
        form_frame.grid(row=2, column=0, padx=18, pady=(0, 12), sticky="ew")
        form_frame.grid_columnconfigure(1, weight=1)

        label_font = ctk.CTkFont(size=12, weight="bold")
        entry_font = ctk.CTkFont(size=12)

        self.account_size = self._create_entry_row(form_frame, 0, "Account Size ($):", "1000", label_font, entry_font)
        self.risk_percentage = self._create_entry_row(form_frame, 1, "Risk (%):", "2", label_font, entry_font)
        self.sl_pips = self._create_entry_row(form_frame, 2, "Stop Loss (pips):", "20", label_font, entry_font)
        self.pip_value = self._create_entry_row(form_frame, 5, "Pip Value ($ per lot, optional):", "10", label_font,
                                                entry_font)

        # Currency Pair (special case with OptionMenu)
        lbl_pair = ctk.CTkLabel(form_frame, text="Currency Pair:", font=label_font)
        lbl_pair.grid(row=3, column=0, padx=(12, 8), pady=8, sticky="w")
        pair_options = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "NZDUSD", "EURGBP", "EURJPY", "GBPJPY",
                        "Other"]
        self.pair_var = tk.StringVar(value="EURUSD")
        self.pair_option = ctk.CTkOptionMenu(form_frame, values=pair_options, command=self._pair_selected,
                                             variable=self.pair_var)
        self.pair_option.grid(row=3, column=1, padx=(0, 12), pady=8, sticky="ew")
        self.pair_entry = ctk.CTkEntry(form_frame, font=entry_font, height=34, corner_radius=8)
        self.pair_entry.grid(row=4, column=1, padx=(0, 12), pady=(0, 8), sticky="ew")
        self.pair_entry.grid_remove()
        self.pair_entry.insert(0, "EURUSD")

        btn_frame = ctk.CTkFrame(parent, corner_radius=8, fg_color="transparent")
        btn_frame.grid(row=3, column=0, padx=18, pady=(6, 12), sticky="ew")
        btn_frame.grid_columnconfigure((0, 1), weight=1)
        calculate_btn = ctk.CTkButton(btn_frame, text="Calculate", command=self.calculate_lot_size, height=40,
                                      corner_radius=10)
        calculate_btn.grid(row=0, column=0, padx=(0, 8), pady=10, sticky="ew")
        clear_btn = ctk.CTkButton(btn_frame, text="Clear", command=self.clear_all, height=40, corner_radius=10,
                                  fg_color="#444444", hover_color="#555555")
        clear_btn.grid(row=0, column=1, padx=(8, 0), pady=10, sticky="ew")

        results_frame = ctk.CTkFrame(parent, corner_radius=8)
        results_frame.grid(row=4, column=0, padx=18, pady=(6, 18), sticky="ew")
        results_frame.grid_columnconfigure(1, weight=1)
        results_title = ctk.CTkLabel(results_frame, text="Calculation Results",
                                     font=ctk.CTkFont(size=14, weight="bold"))
        results_title.grid(row=0, column=0, columnspan=2, padx=12, pady=(12, 6), sticky="w")
        self.lot_size_result = self._add_result_row(results_frame, "Lot Size:", 1)
        self.risk_amount_result = self._add_result_row(results_frame, "Risk Amount ($):", 2)
        self.position_size_result = self._add_result_row(results_frame, "Position Size:", 3)
        self.pip_value_result = self._add_result_row(results_frame, "Pip Value ($):", 4)

        footer = ctk.CTkLabel(parent, text=f"By {AUTHOR} | v{VERSION}", font=ctk.CTkFont(size=10), text_color="gray50")
        footer.grid(row=5, column=0, padx=18, pady=(4, 18), sticky="e")

    def _create_entry_row(self, parent, row, label_text, default_value, label_font, entry_font):
        label = ctk.CTkLabel(parent, text=label_text, font=label_font)
        label.grid(row=row, column=0, padx=(12, 8), pady=8, sticky="w")
        entry = ctk.CTkEntry(parent, font=entry_font, height=36, corner_radius=8)
        entry.grid(row=row, column=1, padx=(0, 12), pady=8, sticky="ew")
        entry.insert(0, default_value)
        return entry

    def _pair_selected(self, value):
        if value == "Other":
            self.pair_entry.grid()
            self.pair_entry.focus_set()
        else:
            self.pair_entry.grid_remove()
            self.pair_entry.delete(0, "end")
            self.pair_entry.insert(0, value)

    def _add_result_row(self, parent, text, row):
        label = ctk.CTkLabel(parent, text=text, font=ctk.CTkFont(size=12, weight="bold"))
        label.grid(row=row, column=0, padx=(12, 6), pady=6, sticky="w")
        value = ctk.CTkLabel(parent, text="0.00", font=ctk.CTkFont(size=12), text_color="light blue")
        value.grid(row=row, column=1, padx=(12, 6), pady=6, sticky="e")
        return value

    def validate_inputs(self):
        try:
            account_size = float(self.account_size.get())
            risk_percentage = float(self.risk_percentage.get())
            sl_pips = float(self.sl_pips.get())
            pair = (self.pair_entry.get() if self.pair_var.get() == "Other" else self.pair_var.get()).strip().upper()

            pip_value_str = self.pip_value.get().strip()
            pip_value = float(pip_value_str) if pip_value_str else None

            if account_size <= 0: raise ValueError("Account size must be positive.")
            if not (0 < risk_percentage <= 100): raise ValueError("Risk percentage must be between 0 and 100.")
            if sl_pips <= 0: raise ValueError("Stop loss (pips) must be positive.")
            if not pair: raise ValueError("Currency pair is required.")
            if pip_value is not None and pip_value <= 0: raise ValueError("Pip value must be positive if specified.")

            return account_size, risk_percentage, sl_pips, pair, pip_value

        except ValueError as e:
            messagebox.showerror("Input Error", str(e))
            return None

    def calculate_lot_size(self):
        validated_data = self.validate_inputs()
        if not validated_data:
            return

        account_size, risk_percentage, sl_pips, pair, user_pip_value = validated_data

        try:
            risk_amount = account_size * (risk_percentage / 100)

            final_pip_value = user_pip_value
            if final_pip_value is None:
                pip_values = {'EURUSD': 10, 'GBPUSD': 10, 'USDJPY': 9, 'USDCHF': 10, 'AUDUSD': 10, 'USDCAD': 10,
                              'NZDUSD': 10, 'EURGBP': 10, 'EURJPY': 9, 'GBPJPY': 9}
                final_pip_value = pip_values.get(pair, 10)

            # Explicitly prevent division by zero
            if sl_pips * final_pip_value == 0:
                messagebox.showerror("Calculation Error",
                                     "Cannot calculate lot size. The product of Stop Loss and Pip Value cannot be zero.")
                return

            lot_size = risk_amount / (sl_pips * final_pip_value)

            if lot_size > 100:
                messagebox.showwarning("Large Lot Size",
                                       f"Calculated lot size ({lot_size:.2f}) is very large. Please double-check your inputs.")

            position_size = lot_size * 100000

            self.lot_size_result.configure(text=f"{lot_size:.4f}")
            self.risk_amount_result.configure(text=f"${risk_amount:.2f}")
            self.position_size_result.configure(text=f"{position_size:,.0f} units")
            self.pip_value_result.configure(text=f"${final_pip_value:.2f}")

            self._scroll_to_widget(self.lot_size_result)
        except Exception as e:
            messagebox.showerror("Calculation Error", f"An unexpected error occurred:\n{str(e)}")

    def _scroll_to_widget(self, widget):
        try:
            widget.update_idletasks()
            widget_y = widget.winfo_rooty() - self.canvas.winfo_rooty()
            canvas_h = self.canvas.winfo_height()
            if widget_y > canvas_h - 60: self.canvas.yview_scroll(1, "pages")
        except Exception:
            pass

    def clear_all(self):
        self.account_size.delete(0, 'end');
        self.account_size.insert(0, "1000")
        self.risk_percentage.delete(0, 'end');
        self.risk_percentage.insert(0, "2")
        self.sl_pips.delete(0, 'end');
        self.sl_pips.insert(0, "20")
        self.pip_value.delete(0, 'end');
        self.pip_value.insert(0, "10")
        self.pair_var.set("EURUSD");
        self.pair_entry.delete(0, 'end');
        self.pair_entry.insert(0, "EURUSD");
        self.pair_entry.grid_remove()

        self.lot_size_result.configure(text="0.00")
        self.risk_amount_result.configure(text="$0.00")
        self.position_size_result.configure(text="0 units")
        self.pip_value_result.configure(text="$0.00")

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    AUTHOR = "TageYassir"
    VERSION = "1.1"
    app = LotSizeCalculator()
    app.run()