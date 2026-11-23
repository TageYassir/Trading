import tkinter as tk
from tkinter import filedialog, messagebox
import csv
import os
from datetime import datetime


def format_for_galactic_trader(input_filepath):
    # Dynamically create the output filepath
    base_name, extension = os.path.splitext(input_filepath)
    output_filepath = f"{base_name}_galactic{extension}"

    formatted_data = []

    try:
        with open(input_filepath, mode='r', encoding='utf-8-sig') as infile:
            # 1. AUTO-DETECT DELIMITER: Check if the file uses semicolons or commas
            first_line = infile.readline()
            file_delimiter = ';' if ';' in first_line else ','
            infile.seek(0)  # Reset back to the top of the file

            reader = csv.reader(infile, delimiter=file_delimiter)

            # Skip the header row
            next(reader, None)

            for row in reader:
                # Catch empty rows
                if len(row) < 5:
                    continue

                # 2. AUTO-DETECT TIME COLUMN: MetaTrader often adds a Time column (e.g., 15:00).
                # If we see a colon in column 2, we shift all our price targets over by 1.
                offset = 1 if ':' in row[1] else 0

                try:
                    raw_date = row[0].strip()
                    open_price = row[1 + offset]
                    high_price = row[2 + offset]
                    low_price = row[3 + offset]
                    close_price = row[4 + offset]

                    # Some files lack volume, so we protect against that error
                    volume = row[5 + offset] if len(row) > (5 + offset) else "0"
                    open_interest = "0"  # Galactic Trader expects this
                except IndexError:
                    continue  # Skip incomplete rows

                # 3. FIX METATRADER DATES: Replace dots and slashes with standard dashes
                raw_date = raw_date.replace('.', '-').replace('/', '-')

                # If time is attached directly to the date (e.g., 2026-02-20 15:00), chop the time off
                raw_date = raw_date.split(' ')[0]

                # Parse the date perfectly to YYYYMMDD
                try:
                    # Try YYYY-MM-DD first
                    try:
                        dt = datetime.strptime(raw_date, '%Y-%m-%d')
                    except ValueError:
                        # Fallback to DD-MM-YYYY if formatted differently
                        try:
                            dt = datetime.strptime(raw_date, '%d-%m-%Y')
                        except ValueError:
                            # Fallback if it is already YYYYMMDD
                            dt = datetime.strptime(raw_date, '%Y%m%d')

                    clean_date = dt.strftime('%Y%m%d')
                except ValueError:
                    continue  # Skip rows where the date is completely unreadable

                # Arrange in exact CSI/Galactic Trader order
                formatted_data.append(
                    [clean_date, open_price, high_price, low_price, close_price, volume, open_interest])

        # FAIL-SAFE: If the file is still empty, tell the user exactly why!
        if len(formatted_data) == 0:
            return False, "Could not read the data. All rows were skipped.\nPlease check if the CSV contains standard Open, High, Low, Close data."

        # Write the clean data to the dynamic new file WITHOUT headers
        with open(output_filepath, mode='w', newline='') as outfile:
            writer = csv.writer(outfile)
            writer.writerows(formatted_data)

        return True, output_filepath

    except Exception as e:
        return False, str(e)


# --- GUI FUNCTIONS ---
def browse_file():
    filepath = filedialog.askopenfilename(
        title="Select MetaTrader CSV",
        filetypes=(("CSV Files", "*.csv"), ("All Files", "*.*"))
    )
    if filepath:
        file_path_var.set(filepath)


def run_conversion():
    input_filepath = file_path_var.get()

    if not input_filepath:
        messagebox.showwarning("Missing File", "Please browse and select a CSV file first.")
        return

    # Run the background logic
    success, result = format_for_galactic_trader(input_filepath)

    if success:
        messagebox.showinfo("Success!", f"Data formatted perfectly for Galactic Trader!\n\nSaved to:\n{result}")
        file_path_var.set("")
    else:
        messagebox.showerror("Error", f"Something went wrong:\n{result}")


# --- BUILD THE TKINTER WINDOW ---
root = tk.Tk()
root.title("Galactic Trader Data Converter")
root.geometry("500x200")
root.resizable(False, False)
root.eval('tk::PlaceWindow . center')

file_path_var = tk.StringVar()

instruction_label = tk.Label(root, text="Select your raw CSV to format it for Galactic Trader:", font=("Arial", 10))
instruction_label.pack(pady=(20, 5))

file_frame = tk.Frame(root)
file_frame.pack(pady=5, padx=20, fill="x")

file_entry = tk.Entry(file_frame, textvariable=file_path_var, font=("Arial", 10), state="readonly")
file_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

browse_button = tk.Button(file_frame, text="Browse", command=browse_file, width=10)
browse_button.pack(side="right")

convert_button = tk.Button(root, text="Convert to Galactic Format", command=run_conversion, font=("Arial", 10, "bold"),
                           bg="#4CAF50", fg="black", pady=5)
convert_button.pack(pady=20)

root.mainloop()