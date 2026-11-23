import os
import urllib.request

# Create ephe folder if it doesn't exist
ephe_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ephe')
os.makedirs(ephe_path, exist_ok=True)

# Files to download
files = [
    'seas_18.se1',
    'sepl_18.se1',
    'semo_18.se1',
    'seplm18.se1',
    'semom18.se1'
]

base_url = 'https://www.astro.com/ftp/swisseph/ephe/'

for file in files:
    print(f"Downloading {file}...")
    try:
        urllib.request.urlretrieve(f"{base_url}{file}",
                                 os.path.join(ephe_path, file))
        print(f"✓ {file} downloaded successfully")
    except Exception as e:
        print(f"✗ Failed to download {file}: {e}")

print("\nVerifying files...")
missing = [f for f in files if not os.path.exists(os.path.join(ephe_path, f))]
if missing:
    print(f"Missing files: {missing}")
else:
    print("All files present! You can now run your script.")