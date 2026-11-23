import os
import sys
import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageTk
import customtkinter as ctk
import math  # Added for sqrt function

# App metadata
AUTHOR = "TageYassir"
VERSION = "1.3"

# Make sure customtkinter default settings are set before creating widgets
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


def setup_icons(root, basename="icon_trading"):
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    ico_path = os.path.join(base_path, f"{basename}.ico")
    png_path = os.path.join(base_path, f"{basename}.png")

    try:
        if os.path.exists(ico_path):
            try:
                root.iconbitmap(ico_path)
            except Exception as e:
                print(f"iconbitmap failed: {e}")
            else:
                if os.name == "nt":
                    try:
                        from ctypes import windll
                        windll.shell32.SetCurrentProcessExplicitAppUserModelID('com.tagemouati.lotsizecalculator')
                    except Exception as e:
                        print(f"Failed to set AppUserModelID: {e}")
                return
        if os.path.exists(png_path):
            try:
                img = Image.open(png_path)
                photo = ImageTk.PhotoImage(img)
                root._icon_photo = photo
                root.iconphoto(False, photo)
                return
            except Exception as e:
                print(f"Pillow icon load failed: {e}")
        try:
            blank = tk.PhotoImage(width=16, height=16)
            root.iconphoto(False, blank)
            root._icon_photo = blank
        except Exception as e:
            print(f"Fallback iconphoto failed: {e}")
    except Exception as e:
        print(f"Impossible to load icon: {e}")


class LotSizeCalculator:
    ICON_BASENAME = "app_icon"

    def __init__(self):
        self.root = ctk.CTk()
        self.root.title(f"Trading Calculator Suite v{VERSION}")

        # Variables for page management
        self.current_page = None
        self.pages = {}

        fixed_width = 640
        fixed_height = 720
        self.root.geometry(f"{fixed_width}x{fixed_height}")
        self.root.resizable(False, False)
        self.root.minsize(fixed_width, fixed_height)
        self.root.maxsize(fixed_width, fixed_height)

        setup_icons(self.root, basename=self.ICON_BASENAME)

        # Create main structure with menu
        self._create_menu_bar()
        self._create_main_container()

        # Initialize both calculator pages
        self._create_lot_calculator_page()
        self._create_angle_calculator_page()

        # Show lot calculator by default
        self.show_page("lot_calculator")

        self.root.bind("<Return>", lambda event: self._handle_enter_key())

    def _create_menu_bar(self):
        """Create the top menu bar"""
        self.menu_frame = ctk.CTkFrame(self.root, height=40, corner_radius=0, fg_color="#1a1a1a")
        self.menu_frame.pack(fill="x", side="top", padx=0, pady=0)
        self.menu_frame.pack_propagate(False)

        # Menu buttons
        self.lot_calc_btn = ctk.CTkButton(
            self.menu_frame,
            text="Lot Size Calculator",
            command=lambda: self.show_page("lot_calculator"),
            width=180,
            height=30,
            corner_radius=5,
            fg_color="#2b2b2b",
            hover_color="#3a3a3a"
        )
        self.lot_calc_btn.pack(side="left", padx=(10, 5), pady=5)

        self.angle_calc_btn = ctk.CTkButton(
            self.menu_frame,
            text="Angle Calculator",
            command=lambda: self.show_page("angle_calculator"),
            width=180,
            height=30,
            corner_radius=5,
            fg_color="#2b2b2b",
            hover_color="#3a3a3a"
        )
        self.angle_calc_btn.pack(side="left", padx=5, pady=5)

        # Separator
        separator = ctk.CTkFrame(self.menu_frame, width=1, height=20, fg_color="#444444")
        separator.pack(side="left", padx=10, pady=0)

        # Version label
        version_label = ctk.CTkLabel(
            self.menu_frame,
            text=f"v{VERSION} by {AUTHOR}",
            font=ctk.CTkFont(size=10),
            text_color="gray60"
        )
        version_label.pack(side="right", padx=10, pady=5)

    def _create_main_container(self):
        """Create main container for pages"""
        self.main_container = ctk.CTkFrame(self.root, corner_radius=0)
        self.main_container.pack(fill="both", expand=True, padx=0, pady=0)

    def show_page(self, page_name):
        """Switch between calculator pages"""
        # Hide current page
        if self.current_page:
            self.pages[self.current_page].pack_forget()

        # Update button colors
        self.lot_calc_btn.configure(fg_color="#2b2b2b")
        self.angle_calc_btn.configure(fg_color="#2b2b2b")

        # Show selected page and update button color
        if page_name == "lot_calculator":
            self.pages[page_name].pack(fill="both", expand=True)
            self.lot_calc_btn.configure(fg_color="#1f538d")
            self.root.title(f"Lot Size Calculator - Trading Calculator Suite v{VERSION}")
        elif page_name == "angle_calculator":
            self.pages[page_name].pack(fill="both", expand=True)
            self.angle_calc_btn.configure(fg_color="#1f538d")
            self.root.title(f"Angle Calculator - Trading Calculator Suite v{VERSION}")

        self.current_page = page_name

    def _handle_enter_key(self):
        """Handle Enter key based on current page"""
        if self.current_page == "lot_calculator":
            self.calculate_lot_size()
        elif self.current_page == "angle_calculator":
            self.calculate_angle()

    def _create_lot_calculator_page(self):
        """Create the lot size calculator page"""
        self.pages["lot_calculator"] = ctk.CTkFrame(self.main_container, corner_radius=0)
        self._build_scrollable_ui(self.pages["lot_calculator"])

    def _build_scrollable_ui(self, parent):
        outer = ctk.CTkFrame(parent, corner_radius=0)
        outer.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(outer, borderwidth=0, highlightthickness=0, bg="#2b2b2b")
        self.canvas.pack(side="left", fill="both", expand=True)

        scrollbar = ctk.CTkScrollbar(outer, orientation="vertical", command=self.canvas.yview)
        scrollbar.pack(side="right", fill="y")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.container = ctk.CTkFrame(self.canvas, corner_radius=12, fg_color="#2b2b2b")
        self._container_window = self.canvas.create_window((0, 0), window=self.container, anchor="nw")

        self.container.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel_windows)
        self.canvas.bind_all("<Button-4>", self._on_mousewheel_linux)
        self.canvas.bind_all("<Button-5>", self._on_mousewheel_linux)

        self._populate_lot_ui(self.container)

    def _create_angle_calculator_page(self):
        """Create the angle calculator page"""
        self.pages["angle_calculator"] = ctk.CTkFrame(self.main_container, corner_radius=0)
        self._build_angle_ui(self.pages["angle_calculator"])

    def _build_angle_ui(self, parent):
        """Build the angle calculator interface"""
        outer = ctk.CTkFrame(parent, corner_radius=0)
        outer.pack(fill="both", expand=True)

        canvas = tk.Canvas(outer, borderwidth=0, highlightthickness=0, bg="#2b2b2b")
        canvas.pack(side="left", fill="both", expand=True)

        scrollbar = ctk.CTkScrollbar(outer, orientation="vertical", command=canvas.yview)
        scrollbar.pack(side="right", fill="y")
        canvas.configure(yscrollcommand=scrollbar.set)

        container = ctk.CTkFrame(canvas, corner_radius=12, fg_color="#2b2b2b")
        container_window = canvas.create_window((0, 0), window=container, anchor="nw")

        container.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(container_window, width=e.width))

        # Title
        title = ctk.CTkLabel(container, text="Angle Calculator for Trading",
                             font=ctk.CTkFont(size=18, weight="bold"))
        title.grid(row=0, column=0, columnspan=2, padx=16, pady=(20, 8), sticky="w")

        subtitle = ctk.CTkLabel(container,
                                text="Calculate angles and projections for trading analysis\nFormulas: t = (√x - √y) / 0.005555, t1 = t / 180, f = (√x - t1)² / z",
                                font=ctk.CTkFont(size=11))
        subtitle.grid(row=1, column=0, columnspan=2, padx=16, pady=(0, 20), sticky="w")

        # Input Form Frame
        form = ctk.CTkFrame(container, corner_radius=8, fg_color="#232629")
        form.grid(row=2, column=0, columnspan=2, padx=16, pady=(0, 12), sticky="ew")
        form.grid_columnconfigure(1, weight=1)

        label_font = ctk.CTkFont(size=12, weight="bold")
        entry_font = ctk.CTkFont(size=12)

        # Create input fields with tooltips - REMOVE DEFAULT VALUES
        self.x_price = self._create_entry_with_label(form, 0, "Price High/Low (x):", "",
                                                     "The price level (high or low) for calculation",
                                                     label_font, entry_font)

        self.y_price = self._create_entry_with_label(form, 1, "Inverse Price (y):", "",
                                                     "The inverse price level for calculation",
                                                     label_font, entry_font)

        self.z_translation = self._create_entry_with_label(form, 2, "Translation (z):", "",
                                                           "Translation factor for final calculation",
                                                           label_font, entry_font)

        self.t_angle_override = self._create_entry_with_label(form, 3, "Angle Override (t, optional):", "",
                                                              "Optional: Provide your own t value (intermediate angle) instead of calculating it",
                                                              label_font, entry_font)

        # Buttons Frame
        btn_frame = ctk.CTkFrame(container, corner_radius=8, fg_color="transparent")
        btn_frame.grid(row=3, column=0, columnspan=2, padx=16, pady=(12, 20), sticky="ew")
        btn_frame.grid_columnconfigure((0, 1), weight=1)

        calc_btn = ctk.CTkButton(btn_frame, text="Calculate", command=self.calculate_angle,
                                 height=40, corner_radius=10)
        calc_btn.grid(row=0, column=0, padx=(0, 8), pady=10, sticky="ew")

        clear_btn = ctk.CTkButton(btn_frame, text="Clear", command=self.clear_angle_inputs,
                                  height=40, corner_radius=10, fg_color="#444444", hover_color="#555555")
        clear_btn.grid(row=0, column=1, padx=(8, 0), pady=10, sticky="ew")

        # Results Frame
        results = ctk.CTkFrame(container, corner_radius=8)
        results.grid(row=4, column=0, columnspan=2, padx=16, pady=(0, 20), sticky="ew")
        results.grid_columnconfigure(1, weight=1)

        results_title = ctk.CTkLabel(results, text="Calculation Results",
                                     font=ctk.CTkFont(size=14, weight="bold"))
        results_title.grid(row=0, column=0, columnspan=2, padx=12, pady=(12, 8), sticky="w")

        # Result labels
        self.t_result_label = self._add_angle_result_row(results, "Calculated Angle (t):", 1)
        self.f_result_label = self._add_angle_result_row(results, "Final Result (f):", 2)
        self.sqrt_x_label = self._add_angle_result_row(results, "√x:", 3)
        self.sqrt_y_label = self._add_angle_result_row(results, "√y:", 4)
        self.t_used_label = self._add_angle_result_row(results, "Angle Used in Calculation:", 5)

        # Formula Display
        formula_frame = ctk.CTkFrame(container, corner_radius=8, fg_color="#1e1e2e")
        formula_frame.grid(row=5, column=0, columnspan=2, padx=16, pady=(0, 30), sticky="ew")

        formula_text = """Formulas:
        1. t = (√x - √y) / 0.005555
        2. t1 = t / 180
        3. f = (√x - t1)² / z

        Where:
        • x = Price high/low
        • y = Inverse price
        • z = Translation factor
        • t = Intermediate angle calculation
        • t1 = Final angle used in f calculation (can be overridden)
        • f = Final projection value"""

        formula_label = ctk.CTkLabel(formula_frame, text=formula_text,
                                     font=ctk.CTkFont(size=11, family="Courier"),
                                     justify="left")
        formula_label.pack(padx=12, pady=12, fill="both")

    def _create_entry_with_label(self, parent, row, label_text, default_value, tooltip, label_font, entry_font):
        """Helper to create labeled entry with tooltip"""
        label = ctk.CTkLabel(parent, text=label_text, font=label_font)
        label.grid(row=row, column=0, padx=(12, 8), pady=12, sticky="w")

        entry = ctk.CTkEntry(parent, font=entry_font, height=36, corner_radius=8)
        entry.grid(row=row, column=1, padx=(0, 12), pady=12, sticky="ew")

        if default_value:
            entry.insert(0, default_value)

        # Simple tooltip implementation
        entry.bind("<Enter>", lambda e: self._show_tooltip(tooltip))
        entry.bind("<Leave>", lambda e: self._hide_tooltip())

        return entry

    def _add_angle_result_row(self, parent, text, row):
        """Helper to add result rows for angle calculator"""
        label = ctk.CTkLabel(parent, text=text, font=ctk.CTkFont(size=12, weight="bold"))
        label.grid(row=row, column=0, padx=(12, 8), pady=8, sticky="w")

        value = ctk.CTkLabel(parent, text="—", font=ctk.CTkFont(size=12), text_color="light blue")
        value.grid(row=row, column=1, padx=(0, 12), pady=8, sticky="e")

        return value

    def _show_tooltip(self, text):
        """Simple tooltip display"""
        # This is a basic implementation. For a better tooltip, you might want to use a custom tooltip class
        pass

    def _hide_tooltip(self):
        """Hide tooltip"""
        pass

    def calculate_angle(self):
        """Calculate angle using the provided formulas"""
        try:
            # Get inputs
            x_str = self.x_price.get().strip()
            y_str = self.y_price.get().strip()
            z_str = self.z_translation.get().strip()

            # Check if inputs are empty
            if not x_str or not y_str or not z_str:
                messagebox.showerror("Input Error", "Please fill in all required fields (x, y, z).")
                return

            x = float(x_str)
            y = float(y_str)
            z = float(z_str)

            # Check for negative values in sqrt operations
            if x < 0 or y < 0:
                messagebox.showerror("Input Error", "Price values cannot be negative for square root operations.")
                return

            # Calculate square roots
            sqrt_x = math.sqrt(x)
            sqrt_y = math.sqrt(y)

            # Check if user provided angle override
            t_override_str = self.t_angle_override.get().strip()
            if t_override_str:
                # User provides t (not t1), so we need to calculate t1 from t
                t = float(t_override_str)
                t1 = t / 180
                t_source = "User Override"
            else:
                # Calculate t using formula: t = (sqrt(x) - sqrt(y)) / 0.005555
                t = (sqrt_x - sqrt_y) / 0.005555
                t1 = t / 180
                t_source = "Calculated"

            # Calculate f using formula: f = (sqrt(x) - t1)² / z
            f = (sqrt_x - t1) ** 2 / z

            # Update results
            self.t_result_label.configure(text=f"{t:.6f}")
            self.f_result_label.configure(text=f"{f:.6f}")
            self.sqrt_x_label.configure(text=f"{sqrt_x:.6f}")
            self.sqrt_y_label.configure(text=f"{sqrt_y:.6f}")

            # Show intermediate calculation
            self.t_used_label.configure(text=f"{t1:.6f} (t = {t:.6f} / 180, {t_source})")

        except ValueError as e:
            messagebox.showerror("Input Error", f"Invalid input values. Please check your numbers.\nError: {e}")
        except ZeroDivisionError:
            messagebox.showerror("Calculation Error", "Translation (z) cannot be zero.")
        except Exception as e:
            messagebox.showerror("Calculation Error", f"An unexpected error occurred:\n{e}")

    def clear_angle_inputs(self):
        """Clear all angle calculator inputs"""
        self.x_price.delete(0, "end")
        self.y_price.delete(0, "end")
        self.z_translation.delete(0, "end")
        self.t_angle_override.delete(0, "end")

        # Clear results
        self.t_result_label.configure(text="—")
        self.f_result_label.configure(text="—")
        self.sqrt_x_label.configure(text="—")
        self.sqrt_y_label.configure(text="—")
        self.t_used_label.configure(text="—")

    # Lot Calculator UI helpers (rest of your existing methods remain the same)
    def _on_canvas_configure(self, event):
        try:
            self.canvas.itemconfig(self._container_window, width=event.width)
        except Exception:
            pass

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

    def _populate_lot_ui(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, minsize=8)

        title = ctk.CTkLabel(parent, text="Forex Lot Size Calculator — Extended",
                             font=ctk.CTkFont(size=18, weight="bold"))
        title.grid(row=1, column=0, padx=16, pady=(12, 4), sticky="w")

        subtitle = ctk.CTkLabel(parent, text="Supports SL/TP as pips or as price levels, account currency, lot types.",
                                font=ctk.CTkFont(size=11))
        subtitle.grid(row=2, column=0, padx=16, pady=(0, 12), sticky="w")

        form = ctk.CTkFrame(parent, corner_radius=8, fg_color="#232629")
        form.grid(row=3, column=0, padx=16, pady=(0, 12), sticky="ew")
        form.grid_columnconfigure(1, weight=1)

        label_font = ctk.CTkFont(size=12, weight="bold")
        entry_font = ctk.CTkFont(size=12)

        # Basic account/trade settings
        self.account_size = self._create_entry_row(form, 0, "Account Size:", "1000", label_font, entry_font)
        currency_options = ["USD", "EUR", "JPY", "GBP", "AUD", "CAD", "CHF", "NZD"]
        self.account_currency_var = tk.StringVar(value="USD")
        lbl_acc_cur = ctk.CTkLabel(form, text="Account Currency:", font=label_font)
        lbl_acc_cur.grid(row=1, column=0, padx=(12, 8), pady=8, sticky="w")
        self.account_currency_opt = ctk.CTkOptionMenu(form, values=currency_options,
                                                      variable=self.account_currency_var)
        self.account_currency_opt.grid(row=1, column=1, padx=(0, 12), pady=8, sticky="ew")

        self.risk_percentage = self._create_entry_row(form, 2, "Risk (%):", "2", label_font, entry_font)

        # Pair and trade direction
        lbl_pair = ctk.CTkLabel(form, text="Currency Pair:", font=label_font)
        lbl_pair.grid(row=3, column=0, padx=(12, 8), pady=8, sticky="w")
        pair_options = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "NZDUSD", "EURGBP", "EURJPY", "GBPJPY",
                        "Other"]
        self.pair_var = tk.StringVar(value="EURUSD")
        self.pair_option = ctk.CTkOptionMenu(form, values=pair_options, command=self._pair_selected,
                                             variable=self.pair_var)
        self.pair_option.grid(row=3, column=1, padx=(0, 12), pady=8, sticky="ew")

        self.pair_entry = ctk.CTkEntry(form, font=entry_font, height=34, corner_radius=8)
        self.pair_entry.grid(row=4, column=1, padx=(0, 12), pady=(0, 8), sticky="ew")
        if self.pair_var.get() != "Other":
            self.pair_entry.grid_remove()
        self.pair_entry.insert(0, "EURUSD")

        lbl_dir = ctk.CTkLabel(form, text="Direction:", font=label_font)
        lbl_dir.grid(row=5, column=0, padx=(12, 8), pady=8, sticky="w")
        self.direction_var = tk.StringVar(value="Buy")
        self.direction_opt = ctk.CTkOptionMenu(form, values=["Buy", "Sell"], variable=self.direction_var)
        self.direction_opt.grid(row=5, column=1, padx=(0, 12), pady=8, sticky="ew")

        # Lot contract size
        lbl_lot = ctk.CTkLabel(form, text="Lot Type:", font=label_font)
        lbl_lot.grid(row=6, column=0, padx=(12, 8), pady=8, sticky="w")
        self.lot_type_var = tk.StringVar(value="Standard (100k)")
        self.lot_type_opt = ctk.CTkOptionMenu(form,
                                              values=["Standard (100k)", "Mini (10k)", "Micro (1k)"],
                                              variable=self.lot_type_var)
        self.lot_type_opt.grid(row=6, column=1, padx=(0, 12), pady=8, sticky="ew")

        # Entry price (required when SL/TP are price levels)
        self.entry_price = self._create_entry_row(form, 7, "Entry Price (optional for pips):", "", label_font,
                                                  entry_font)

        # Stop Loss: mode + value (either pips or price)
        lbl_sl_mode = ctk.CTkLabel(form, text="Stop Loss Mode:", font=label_font)
        lbl_sl_mode.grid(row=8, column=0, padx=(12, 8), pady=8, sticky="w")
        self.sl_mode_var = tk.StringVar(value="pips")
        self.sl_mode_opt = ctk.CTkOptionMenu(form, values=["pips", "price"], variable=self.sl_mode_var,
                                             command=lambda v: self._toggle_sl_entry())
        self.sl_mode_opt.grid(row=8, column=1, padx=(0, 12), pady=8, sticky="ew")

        self.sl_value = ctk.CTkEntry(form, font=entry_font, height=36, corner_radius=8)
        self.sl_value.grid(row=9, column=1, padx=(0, 12), pady=(0, 8), sticky="ew")
        self.sl_value.insert(0, "20")

        # Take Profit: mode + value (optional)
        lbl_tp_mode = ctk.CTkLabel(form, text="Take Profit Mode:", font=label_font)
        lbl_tp_mode.grid(row=10, column=0, padx=(12, 8), pady=8, sticky="w")
        self.tp_mode_var = tk.StringVar(value="pips")
        self.tp_mode_opt = ctk.CTkOptionMenu(form, values=["pips", "price"], variable=self.tp_mode_var,
                                             command=lambda v: self._toggle_tp_entry())
        self.tp_mode_opt.grid(row=10, column=1, padx=(0, 12), pady=8, sticky="ew")

        self.tp_value = ctk.CTkEntry(form, font=entry_font, height=36, corner_radius=8)
        self.tp_value.grid(row=11, column=1, padx=(0, 12), pady=(0, 8), sticky="ew")
        self.tp_value.insert(0, "40")

        # Optional: pip value override
        self.pip_value = self._create_entry_row(form, 12, "Pip Value (per lot in acct currency, optional):", "",
                                                label_font, entry_font)

        # Buttons
        btn_frame = ctk.CTkFrame(parent, corner_radius=8, fg_color="transparent")
        btn_frame.grid(row=4, column=0, padx=16, pady=(6, 12), sticky="ew")
        btn_frame.grid_columnconfigure((0, 1), weight=1)
        calc_btn = ctk.CTkButton(btn_frame, text="Calculate", command=self.calculate_lot_size, height=40,
                                 corner_radius=10)
        calc_btn.grid(row=0, column=0, padx=(0, 8), pady=10, sticky="ew")
        clear_btn = ctk.CTkButton(btn_frame, text="Clear", command=self.clear_all, height=40, corner_radius=10,
                                  fg_color="#444444", hover_color="#555555")
        clear_btn.grid(row=0, column=1, padx=(8, 0), pady=10, sticky="ew")

        # Results
        results = ctk.CTkFrame(parent, corner_radius=8)
        results.grid(row=5, column=0, padx=16, pady=(6, 12), sticky="ew")
        results.grid_columnconfigure(1, weight=1)
        results_title = ctk.CTkLabel(results, text="Results", font=ctk.CTkFont(size=14, weight="bold"))
        results_title.grid(row=0, column=0, columnspan=2, padx=12, pady=(8, 6), sticky="w")

        self.lot_size_result = self._add_result_row(results, "Lot Size", 1)
        self.risk_amount_result = self._add_result_row(results, "Risk Amount", 2)
        self.position_size_result = self._add_result_row(results, "Position Size (units)", 3)
        self.pip_value_result = self._add_result_row(results, "Pip Value (per lot)", 4)
        self.sl_pips_result = self._add_result_row(results, "SL (pips)", 5)
        self.tp_pips_result = self._add_result_row(results, "TP (pips)", 6)
        self.rr_result = self._add_result_row(results, "Risk:Reward", 7)

    def _create_entry_row(self, parent, row, label_text, default_value, label_font, entry_font):
        label = ctk.CTkLabel(parent, text=label_text, font=label_font)
        label.grid(row=row * 1 + 0, column=0, padx=(12, 8), pady=8, sticky="w")
        entry = ctk.CTkEntry(parent, font=entry_font, height=36, corner_radius=8)
        entry.grid(row=row * 1 + 0, column=1, padx=(0, 12), pady=8, sticky="ew")
        entry.insert(0, default_value)
        return entry

    def _add_result_row(self, parent, text, row):
        label = ctk.CTkLabel(parent, text=text + ":", font=ctk.CTkFont(size=12, weight="bold"))
        label.grid(row=row, column=0, padx=(12, 6), pady=6, sticky="w")
        value = ctk.CTkLabel(parent, text="—", font=ctk.CTkFont(size=12), text_color="light blue")
        value.grid(row=row, column=1, padx=(12, 6), pady=6, sticky="e")
        return value

    def _pair_selected(self, value):
        if value == "Other":
            self.pair_entry.grid()
            self.pair_entry.focus_set()
        else:
            self.pair_entry.grid_remove()
            self.pair_entry.delete(0, "end")
            self.pair_entry.insert(0, value)

    def _toggle_sl_entry(self):
        mode = self.sl_mode_var.get()
        if mode == "pips":
            if not self.sl_value.get().strip():
                self.sl_value.insert(0, "20")
        else:
            if not self.sl_value.get().strip():
                self.sl_value.insert(0, "")

    def _toggle_tp_entry(self):
        mode = self.tp_mode_var.get()
        if mode == "pips":
            if not self.tp_value.get().strip():
                self.tp_value.insert(0, "40")
        else:
            if not self.tp_value.get().strip():
                self.tp_value.insert(0, "")

    # Data / calculations
    def validate_inputs(self):
        try:
            account_size = float(self.account_size.get())
            if account_size <= 0:
                raise ValueError("Account size must be positive.")

            risk_percentage = float(self.risk_percentage.get())
            if not (0 < risk_percentage <= 100):
                raise ValueError("Risk percentage must be between 0 and 100.")

            pair_raw = (self.pair_entry.get() if self.pair_var.get() == "Other" else self.pair_var.get())
            pair = pair_raw.strip().upper().replace("/", "").replace(" ", "")
            if len(pair) != 6:
                raise ValueError("Currency pair must be like EURUSD or USDJPY (6 letters).")

            direction = self.direction_var.get()
            lot_type = self.lot_type_var.get()
            lot_contract = 100000
            if "Mini" in lot_type:
                lot_contract = 10000
            elif "Micro" in lot_type:
                lot_contract = 1000

            entry_price_str = self.entry_price.get().strip()
            entry_price = float(entry_price_str) if entry_price_str else None

            sl_mode = self.sl_mode_var.get()
            sl_raw = self.sl_value.get().strip()
            if not sl_raw:
                raise ValueError("Stop Loss value is required (pips or price).")
            sl_val = float(sl_raw)

            tp_mode = self.tp_mode_var.get()
            tp_raw = self.tp_value.get().strip()
            tp_val = None
            if tp_raw:
                tp_val = float(tp_raw)

            # If SL/TP are given as prices ensure entry provided
            if sl_mode == "price" and entry_price is None:
                raise ValueError("Entry price is required when Stop Loss is a price level.")
            if tp_mode == "price" and entry_price is None and tp_val is not None:
                raise ValueError("Entry price is required when Take Profit is a price level.")

            # pip value override
            pip_value_override = None
            pv = self.pip_value.get().strip()
            if pv:
                pip_value_override = float(pv)
                if pip_value_override <= 0:
                    raise ValueError("Pip value override must be positive.")

            account_currency = self.account_currency_var.get().upper()

            return {
                "account_size": account_size,
                "risk_percentage": risk_percentage,
                "pair": pair,
                "direction": direction,
                "lot_contract": lot_contract,
                "entry_price": entry_price,
                "sl_mode": sl_mode,
                "sl_val": sl_val,
                "tp_mode": tp_mode,
                "tp_val": tp_val,
                "pip_value_override": pip_value_override,
                "account_currency": account_currency,
            }

        except ValueError as e:
            messagebox.showerror("Input Error", str(e))
            return None
        except Exception as e:
            messagebox.showerror("Input Error", f"Invalid input: {e}")
            return None

    def _get_live_rates(self):
        try:
            import requests
            resp = requests.get("https://api.exchangerate.host/latest?base=USD", timeout=4)
            if resp.status_code == 200:
                data = resp.json()
                rates = data.get("rates")
                if isinstance(rates, dict):
                    return rates
        except Exception:
            pass
        return None

    def _pip_size(self, pair):
        return 0.01 if "JPY" in pair else 0.0001

    def _estimate_pip_value_per_lot_in_account(self, pair, lot_contract, account_currency, live_rates):
        base = pair[:3]
        quote = pair[3:]
        pip_size = self._pip_size(pair)
        pip_in_quote = pip_size * lot_contract

        if not live_rates:
            if quote == account_currency:
                return pip_in_quote
            if quote == "USD" and account_currency == "USD":
                return pip_in_quote
            if "JPY" in quote:
                fallback_rate = 120.0
                if account_currency == "USD":
                    return pip_in_quote / fallback_rate
                else:
                    return pip_in_quote / fallback_rate
            else:
                if lot_contract == 100000:
                    return 10.0
                return 10.0 * (lot_contract / 100000.0)

        rates = live_rates
        if quote not in rates or account_currency not in rates:
            return self._estimate_pip_value_per_lot_in_account(pair, lot_contract, account_currency, None)

        rate_quote_per_usd = rates[quote]
        rate_account_per_usd = rates.get(account_currency, 1.0)

        conversion_factor = rate_account_per_usd / rate_quote_per_usd
        pip_value_account = pip_in_quote * conversion_factor
        return pip_value_account

    def calculate_lot_size(self):
        validated = self.validate_inputs()
        if not validated:
            return

        acc = validated
        acc_size = acc["account_size"]
        risk_pct = acc["risk_percentage"]
        pair = acc["pair"]
        direction = acc["direction"]
        lot_contract = acc["lot_contract"]
        entry_price = acc["entry_price"]
        sl_mode = acc["sl_mode"]
        sl_val = acc["sl_val"]
        tp_mode = acc["tp_mode"]
        tp_val = acc["tp_val"]
        pip_override = acc["pip_value_override"]
        account_currency = acc["account_currency"]

        try:
            risk_amount = acc_size * (risk_pct / 100.0)
            pip_size_unit = self._pip_size(pair)

            sl_pips_distance = None
            if sl_mode == "pips":
                sl_pips_distance = abs(sl_val)
            else:
                if entry_price is None:
                    messagebox.showerror("Input Error", "Entry price is required when SL is a price level.")
                    return
                sl_pips_distance = abs(entry_price - sl_val) / pip_size_unit

            tp_pips_distance = None
            if tp_val is not None and str(tp_val).strip() != "":
                if tp_mode == "pips":
                    tp_pips_distance = abs(tp_val)
                else:
                    if entry_price is None:
                        tp_pips_distance = None
                    else:
                        tp_pips_distance = abs(entry_price - tp_val) / pip_size_unit

            live_rates = self._get_live_rates()

            if pip_override is not None:
                pip_value_per_lot = pip_override
            else:
                pip_value_per_lot = self._estimate_pip_value_per_lot_in_account(pair, lot_contract, account_currency,
                                                                                live_rates)

            if sl_pips_distance == 0 or pip_value_per_lot == 0:
                messagebox.showerror("Calculation Error", "Stop Loss distance or pip value is zero, aborting.")
                return

            lots = risk_amount / (sl_pips_distance * pip_value_per_lot)
            position_units = lots * lot_contract

            rr = None
            if tp_pips_distance:
                if tp_pips_distance == 0:
                    rr = None
                else:
                    rr = tp_pips_distance / sl_pips_distance

            self.lot_size_result.configure(text=f"{lots:.4f}")
            self.risk_amount_result.configure(text=f"{account_currency} {risk_amount:,.2f}")
            self.position_size_result.configure(text=f"{position_units:,.0f} units")
            self.pip_value_result.configure(text=f"{account_currency} {pip_value_per_lot:.4f} per lot")
            self.sl_pips_result.configure(text=f"{sl_pips_distance:.2f} pips")
            self.tp_pips_result.configure(text=f"{tp_pips_distance:.2f} pips" if tp_pips_distance else "—")
            self.rr_result.configure(text=f"{rr:.2f}" if rr else "—")

            if lots > 100:
                messagebox.showwarning("Large Lot Size",
                                       f"Calculated lot size ({lots:.2f}) is very large. Check inputs.")

            self._scroll_to_widget(self.lot_size_result)

        except Exception as e:
            messagebox.showerror("Calculation Error", f"An unexpected error occurred:\n{e}")

    def _scroll_to_widget(self, widget):
        try:
            widget.update_idletasks()
            widget_y = widget.winfo_rooty() - self.canvas.winfo_rooty()
            canvas_h = self.canvas.winfo_height()
            if widget_y > canvas_h - 60:
                self.canvas.yview_scroll(1, "pages")
        except Exception:
            pass

    def clear_all(self):
        self.account_size.delete(0, "end")
        self.account_size.insert(0, "1000")
        self.account_currency_var.set("USD")
        self.risk_percentage.delete(0, "end")
        self.risk_percentage.insert(0, "2")
        self.pair_var.set("EURUSD")
        self.pair_entry.delete(0, "end")
        self.pair_entry.insert(0, "EURUSD")
        self.pair_entry.grid_remove()
        self.direction_var.set("Buy")
        self.lot_type_var.set("Standard (100k)")
        self.entry_price.delete(0, "end")
        self.sl_mode_var.set("pips")
        self.sl_value.delete(0, "end")
        self.sl_value.insert(0, "20")
        self.tp_mode_var.set("pips")
        self.tp_value.delete(0, "end")
        self.tp_value.insert(0, "40")
        self.pip_value.delete(0, "end")

        self.lot_size_result.configure(text="—")
        self.risk_amount_result.configure(text="—")
        self.position_size_result.configure(text="—")
        self.pip_value_result.configure(text="—")
        self.sl_pips_result.configure(text="—")
        self.tp_pips_result.configure(text="—")
        self.rr_result.configure(text="—")

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = LotSizeCalculator()
    app.run()