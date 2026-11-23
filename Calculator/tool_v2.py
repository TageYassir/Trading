import os
import sys
import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageTk
import customtkinter as ctk

# App metadata
AUTHOR = "TageYassir"
VERSION = "1.2"

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
        self.root.title("Forex Lot Size Calculator (extended)")

        fixed_width = 640
        fixed_height = 720
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

        self._populate_ui(self.container)

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

    def _populate_ui(self, parent):
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
        pair_options = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "NZDUSD", "EURGBP", "EURJPY", "GBPJPY", "Other"]
        self.pair_var = tk.StringVar(value="EURUSD")
        self.pair_option = ctk.CTkOptionMenu(form, values=pair_options, command=self._pair_selected, variable=self.pair_var)
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
        self.entry_price = self._create_entry_row(form, 7, "Entry Price (optional for pips):", "", label_font, entry_font)

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
        self.pip_value = self._create_entry_row(form, 12, "Pip Value (per lot in acct currency, optional):", "", label_font, entry_font)

        # Buttons
        btn_frame = ctk.CTkFrame(parent, corner_radius=8, fg_color="transparent")
        btn_frame.grid(row=4, column=0, padx=16, pady=(6, 12), sticky="ew")
        btn_frame.grid_columnconfigure((0, 1), weight=1)
        calc_btn = ctk.CTkButton(btn_frame, text="Calculate", command=self.calculate_lot_size, height=40, corner_radius=10)
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

        footer = ctk.CTkLabel(parent, text=f"By {AUTHOR} | v{VERSION}", font=ctk.CTkFont(size=10), text_color="gray50")
        footer.grid(row=6, column=0, padx=16, pady=(4, 18), sticky="e")

    # UI helpers
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
        # change placeholder text
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
        """
        Returns mapping USD -> currency (units per 1 USD), e.g. {"EUR": 0.92, "JPY": 150.0}
        If request fails or requests not installed, returns None.
        """
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
        # typical pip: 0.01 for JPY pairs, else 0.0001
        return 0.01 if "JPY" in pair else 0.0001

    def _estimate_pip_value_per_lot_in_account(self, pair, lot_contract, account_currency, live_rates):
        """
        Compute value of 1 pip for one lot_contract (e.g., 100000) expressed in account currency.
        Logic:
          pip_in_quote = pip_size * lot_contract  (value expressed in quote currency)
          Convert quote -> account currency using live_rates if available:
            1 unit quote = (1 / rate_quote_per_usd) USD
            1 USD = rate_account_per_usd account_currency
            => 1 quote = (1 / rate_quote_per_usd) * rate_account_per_usd account_currency
          So pip_value_account = pip_in_quote * rate_account_per_usd / rate_quote_per_usd
          If live_rates missing, fall back to heuristics:
            - If quote == account_currency -> take pip_in_quote
            - If quote is USD and account is not USD -> convert with fallback 1 USD = 1 account_currency
            - Fallback: return approximate defaults (10 for non-JPY pairs per 100k, ~8-9 for JPY /100k)
        """
        base = pair[:3]
        quote = pair[3:]
        pip_size = self._pip_size(pair)
        pip_in_quote = pip_size * lot_contract

        # If no live rates, handle common quick cases and fallback defaults
        if not live_rates:
            if quote == account_currency:
                return pip_in_quote
            # if quote is USD and account is USD, pip_in_quote already in account
            if quote == "USD" and account_currency == "USD":
                return pip_in_quote
            # heuristic defaults
            if "JPY" in quote:
                fallback_rate = 120.0  # USDJPY typical fallback
                # convert pip_in_quote (JPY) to account currency via USD assumption
                if account_currency == "USD":
                    return pip_in_quote / fallback_rate
                else:
                    # assume account currency roughly similar to USD for fallback
                    return pip_in_quote / fallback_rate
            else:
                # Most common pairs with USD as quote (EURUSD etc): pip_in_quote is in USD when quote==USD
                # For non-USD quote fallback assume ~10 USD per pip for standard 100k
                if lot_contract == 100000:
                    return 10.0
                # scale linearly for mini/micro
                return 10.0 * (lot_contract / 100000.0)

        # Use live rates to convert
        # rates map USD -> other (units per USD)
        rates = live_rates
        # if quote not in rates or account_currency not in rates, fallback to heuristics above
        if quote not in rates or account_currency not in rates:
            # fallback
            return self._estimate_pip_value_per_lot_in_account(pair, lot_contract, account_currency, None)

        rate_quote_per_usd = rates[quote]  # e.g. for USD->JPY, 1 USD = rate JPY
        rate_account_per_usd = rates.get(account_currency, 1.0)

        # pip_in_quote (in quote) -> account currency:
        # 1 quote = (1 / rate_quote_per_usd) USD -> * rate_account_per_usd -> account currency
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
            # Risk in account currency
            risk_amount = acc_size * (risk_pct / 100.0)

            # Determine pip size (0.0001 or 0.01)
            pip_size_unit = self._pip_size(pair)

            # If SL given as price, calculate SL pips distance
            sl_pips_distance = None
            if sl_mode == "pips":
                sl_pips_distance = abs(sl_val)
            else:
                # price mode
                if entry_price is None:
                    messagebox.showerror("Input Error", "Entry price is required when SL is a price level.")
                    return
                sl_pips_distance = abs(entry_price - sl_val) / pip_size_unit

            # TP pips distance (if provided)
            tp_pips_distance = None
            if tp_val is not None and str(tp_val).strip() != "":
                if tp_mode == "pips":
                    tp_pips_distance = abs(tp_val)
                else:
                    if entry_price is None:
                        tp_pips_distance = None
                    else:
                        tp_pips_distance = abs(entry_price - tp_val) / pip_size_unit

            # Live rates (optional)
            live_rates = self._get_live_rates()

            # Compute pip value per lot in account currency unless user overrides
            if pip_override is not None:
                pip_value_per_lot = pip_override
            else:
                pip_value_per_lot = self._estimate_pip_value_per_lot_in_account(pair, lot_contract, account_currency, live_rates)

            # Prevent zero division
            if sl_pips_distance == 0 or pip_value_per_lot == 0:
                messagebox.showerror("Calculation Error", "Stop Loss distance or pip value is zero, aborting.")
                return

            # Lot size (in standard lots of the chosen contract size):
            # risk_amount (in account currency) / (sl_pips_distance * pip_value_per_lot)
            # This yields number of "lots" where one lot = lot_contract base units
            lots = risk_amount / (sl_pips_distance * pip_value_per_lot)

            # Position size in units (base currency units) = lots * lot_contract
            position_units = lots * lot_contract

            # Risk:Reward ratio if TP provided
            rr = None
            if tp_pips_distance:
                if tp_pips_distance == 0:
                    rr = None
                else:
                    rr = tp_pips_distance / sl_pips_distance

            # Update UI results
            self.lot_size_result.configure(text=f"{lots:.4f}")
            self.risk_amount_result.configure(text=f"{account_currency} {risk_amount:,.2f}")
            self.position_size_result.configure(text=f"{position_units:,.0f} units")
            self.pip_value_result.configure(text=f"{account_currency} {pip_value_per_lot:.4f} per lot")
            self.sl_pips_result.configure(text=f"{sl_pips_distance:.2f} pips")
            self.tp_pips_result.configure(text=f"{tp_pips_distance:.2f} pips" if tp_pips_distance else "—")
            self.rr_result.configure(text=f"{rr:.2f}" if rr else "—")

            # If calculated lots is huge warn
            if lots > 100:
                messagebox.showwarning("Large Lot Size", f"Calculated lot size ({lots:.2f}) is very large. Check inputs.")

            # Scroll to results
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