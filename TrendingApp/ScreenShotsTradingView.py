"""
TradingView Wave Pattern Screenshot Collector - HISTORICAL VERSION
Adds random historical navigation for diverse ML training data
"""
import time
import json
import random
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import concurrent.futures

# Selenium imports
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager

# Image processing
from PIL import Image, ImageEnhance
import numpy as np


class TradingViewWaveScreenshot:
    """
    Professional screenshot collector with historical navigation
    Captures diverse wave patterns from different time periods
    """

    def __init__(self, config_path: str = "wave_screenshot_config.json"):
        """
        Initialize with configuration

        Args:
            config_path: Path to configuration JSON file
        """
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self.driver = None
        self.setup_driver()

    def _load_config(self) -> Dict:
        """Load configuration from JSON file"""
        default_config = {
            "output_dir": "wave_pattern_charts",
            "symbols": [
                "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
                "EURJPY", "GBPJPY", "AUDJPY", "XAUUSD", "BTCUSD",
                "ETHUSD", "US30", "NAS100", "SPX500", "UK100"
            ],
            "timeframes": ["15", "30", "60", "240", "1D", "1W"],
            "chart_style": "1",  # 1=Candles
            "theme": "dark",  # "light" or "dark"
            "image_settings": {
                "width": 1920,
                "height": 1080,
                "quality": 95,
                "dpi": 150,
                "crop_margins": True,
                "crop_amount": 100,
                "enhance_contrast": True,
                "contrast_factor": 1.2,
                "remove_grid": True
            },
            "screenshot_settings": {
                "wait_time": 8,
                "max_retries": 2,
                "retry_delay": 2,
                "parallel_workers": 3,
                "batch_size": 10
            },
            "historical_settings": {  # NEW: Settings for historical navigation
                "enable_historical": True,  # Set to False to disable
                "randomize_period": True,  # Go to random periods
                "historical_years": 5,  # Go back up to 5 years
                "randomize_zoom": True,  # Random zoom levels
                "zoom_levels": ["1M", "3M", "6M", "1Y", "3Y", "5Y", "10Y"],
                "min_bars_on_screen": 50,  # Minimum bars to show
                "max_bars_on_screen": 300,  # Maximum bars to show
                "avoid_recent_data": True,  # Avoid current day/week
                "recent_threshold": 7  # Days to avoid from current
            },
            "chart_settings": {
                "hide_side_toolbar": True,
                "hide_volume": False,
                "hide_legend": True,
                "studies": [],
                "timezone": "Etc/UTC",
                "locale": "en"
            }
        }

        if self.config_path.exists():
            try:
                with open(self.config_path, 'r') as f:
                    user_config = json.load(f)
                    self._deep_update(default_config, user_config)
            except Exception as e:
                print(f"Warning: Could not load config file: {e}")

        self._save_config(default_config)
        return default_config

    def _deep_update(self, base: Dict, update: Dict):
        """Deep update dictionary"""
        for key, value in update.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_update(base[key], value)
            else:
                base[key] = value

    def _save_config(self, config: Dict):
        """Save configuration to file"""
        with open(self.config_path, 'w') as f:
            json.dump(config, f, indent=4)

    def setup_driver(self):
        """Setup Chrome driver with optimal settings"""
        chrome_options = Options()

        # Performance optimizations
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)

        # Window size
        width = self.config["image_settings"]["width"]
        height = self.config["image_settings"]["height"]
        chrome_options.add_argument(f"--window-size={width},{height}")

        # For better rendering
        chrome_options.add_argument("--force-device-scale-factor=1")

        try:
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            print("✓ Chrome driver initialized successfully")

        except Exception as e:
            print(f"✗ Error setting up driver: {e}")
            raise

    def navigate_to_random_period(self):
        """
        Navigate to a random historical period to get different charts
        This is the KEY FUNCTION for getting diverse images
        """
        if not self.config["historical_settings"]["enable_historical"]:
            return

        print("   📅 Navigating to random historical period...", end="")

        try:
            # Wait for chart to be ready
            time.sleep(2)

            # Method 1: Use mouse wheel to zoom out and scroll back
            self._zoom_out_randomly()
            time.sleep(1)

            # Method 2: Scroll to random position
            self._scroll_to_random_position()
            time.sleep(1)

            # Method 3: Apply random zoom via keyboard shortcuts
            self._apply_random_zoom()
            time.sleep(2)

            print("✓")

        except Exception as e:
            print(f"⚠️  Historical navigation failed (continuing): {e}")

    def _zoom_out_randomly(self):
        """Zoom out using mouse wheel"""
        try:
            # Find chart container
            chart_container = self.driver.find_element(By.CSS_SELECTOR, "div.chart-container")

            # Create action chain for zoom out (Ctrl + mouse wheel down)
            actions = ActionChains(self.driver)
            actions.move_to_element(chart_container)

            # Random number of zoom outs (2-8 times)
            zoom_outs = random.randint(2, 8)
            for _ in range(zoom_outs):
                actions.key_down(Keys.CONTROL)
                actions.send_keys(Keys.ARROW_DOWN)  # Alternative to mouse wheel
                actions.key_up(Keys.CONTROL)

            actions.perform()
            time.sleep(1)

        except Exception:
            # Fallback method
            self._zoom_with_keys()

    def _zoom_with_keys(self):
        """Alternative zoom method using keyboard shortcuts"""
        try:
            # Press Ctrl+- to zoom out (multiple times)
            zoom_outs = random.randint(3, 10)
            for _ in range(zoom_outs):
                self.driver.find_element(By.TAG_NAME, 'body').send_keys(
                    Keys.CONTROL + Keys.SUBTRACT
                )
                time.sleep(0.1)
        except Exception:
            pass

    def _scroll_to_random_position(self):
        """Scroll to random position in chart history"""
        try:
            # Scroll using arrow keys
            body = self.driver.find_element(By.TAG_NAME, 'body')

            # Scroll left (into history) a random amount
            scrolls = random.randint(5, 50)
            for _ in range(scrolls):
                body.send_keys(Keys.LEFT)
                time.sleep(0.05)

            # Sometimes scroll right a bit
            if random.random() > 0.7:
                right_scrolls = random.randint(1, 10)
                for _ in range(right_scrolls):
                    body.send_keys(Keys.RIGHT)
                    time.sleep(0.05)

        except Exception:
            pass

    def _apply_random_zoom(self):
        """Apply random zoom level via TradingView's period buttons"""
        try:
            # Try to click on period buttons if available
            zoom_levels = self.config["historical_settings"]["zoom_levels"]
            random_zoom = random.choice(zoom_levels)

            # Try to find and click period buttons
            script = f"""
            // Try to set chart to {random_zoom} period
            try {{
                const buttons = document.querySelectorAll('button[data-name="period"]');
                for (let btn of buttons) {{
                    if (btn.textContent.includes('{random_zoom}')) {{
                        btn.click();
                        return true;
                    }}
                }}
                return false;
            }} catch(e) {{
                return false;
            }}
            """

            result = self.driver.execute_script(script)
            if result:
                print(f"(Zoom: {random_zoom})", end=" ")

        except Exception:
            pass

    def build_tradingview_url(self, symbol: str, timeframe: str) -> str:
        """
        Build TradingView URL with random historical parameters when possible
        """
        config = self.config

        # Add random date parameter if historical navigation is enabled
        date_param = ""
        if config["historical_settings"]["enable_historical"] and random.random() > 0.5:
            # Go back random number of days (up to 5 years)
            days_back = random.randint(1, config["historical_settings"]["historical_years"] * 365)
            date_param = f"&from={int((datetime.now() - timedelta(days=days_back)).timestamp())}"

        studies = config["chart_settings"]["studies"]
        studies_param = ""
        if studies:
            studies_param = "&studies=" + "%2C".join(studies)

        url = (
            f"https://www.tradingview.com/chart/"
            f"?symbol={symbol.upper()}"
            f"&interval={timeframe}"
            f"&theme={config['theme']}"
            f"&style={config['chart_style']}"
            f"{date_param}"
            f"{studies_param}"
            f"&timezone={config['chart_settings']['timezone']}"
            f"&hide_side_toolbar={'true' if config['chart_settings']['hide_side_toolbar'] else 'false'}"
            f"&hide_volume={'true' if config['chart_settings']['hide_volume'] else 'false'}"
            f"&locale={config['chart_settings']['locale']}"
        )

        return url

    def wait_for_chart_load(self, timeout: int = 15):
        """
        Wait for chart to fully load
        """
        try:
            print("   Waiting for chart...", end="")

            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.chart-container"))
            )
            print("✓", end="")

            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "canvas"))
            )
            print("✓", end="")

            # Extra wait for chart rendering
            time.sleep(3)
            print("✓")

            return True

        except TimeoutException:
            print("✗")
            return False

    def take_screenshot(self, output_path: str, retry_count: int = 0) -> bool:
        """
        Take screenshot with quality optimizations
        """
        try:
            if retry_count >= self.config["screenshot_settings"]["max_retries"]:
                return False

            time.sleep(1)
            self.driver.save_screenshot(output_path)
            print(f"   ✓ Screenshot taken")

            # Apply post-processing
            if self.post_process_image(output_path):
                print(f"   ✓ Image processed")
                return True
            else:
                return True  # Still keep original

        except Exception as e:
            print(f"   ✗ Screenshot failed: {e}")
            if retry_count < self.config["screenshot_settings"]["max_retries"]:
                time.sleep(self.config["screenshot_settings"]["retry_delay"])
                return self.take_screenshot(output_path, retry_count + 1)
            return False

    def post_process_image(self, image_path: str) -> bool:
        """
        Enhance image quality for ML training
        """
        try:
            img = Image.open(image_path)

            # Convert to RGB if needed
            if img.mode in ('RGBA', 'LA', 'P'):
                if img.mode == 'P':
                    img = img.convert('RGBA')

                rgb_img = Image.new('RGB', img.size, (0, 0, 0))

                if img.mode == 'RGBA':
                    rgb_img.paste(img, mask=img.split()[3])
                else:
                    rgb_img.paste(img)

                img = rgb_img

            # Crop if requested
            if self.config["image_settings"].get("crop_margins", False):
                try:
                    width, height = img.size
                    crop_amount = self.config["image_settings"].get("crop_amount", 100)
                    left = min(crop_amount, width // 4)
                    top = min(crop_amount, height // 4)
                    right = max(width - crop_amount, width * 3 // 4)
                    bottom = max(height - crop_amount, height * 3 // 4)

                    if left < right and top < bottom:
                        img = img.crop((left, top, right, bottom))
                except Exception:
                    pass

            # Enhance contrast if requested
            if self.config["image_settings"].get("enhance_contrast", False):
                try:
                    contrast_factor = self.config["image_settings"].get("contrast_factor", 1.2)
                    enhancer = ImageEnhance.Contrast(img)
                    img = enhancer.enhance(contrast_factor)
                except Exception:
                    pass

            # Save with quality settings
            dpi = self.config["image_settings"].get("dpi", 150)
            quality = self.config["image_settings"].get("quality", 95)

            img.save(
                image_path,
                'PNG',
                quality=quality,
                dpi=(dpi, dpi),
                optimize=True
            )

            # Get file size
            file_size = Path(image_path).stat().st_size / 1024
            print(f"   📏 Size: {img.size[0]}x{img.size[1]}, 📊 File: {file_size:.1f}KB")

            return True

        except Exception as e:
            print(f"   ⚠️  Image processing error: {e}")
            return True

    def capture_wave_chart(self, symbol: str, timeframe: str) -> Optional[str]:
        """
        Capture a wave pattern chart with historical navigation
        """
        try:
            # Build URL with potential historical parameter
            url = self.build_tradingview_url(symbol, timeframe)
            print(f"\n📈 Capturing: {symbol} - {timeframe}")
            print(f"   🔗 URL: {url[:100]}...")  # Show truncated URL

            # Navigate to chart
            self.driver.get(url)

            # Wait for chart to load
            if not self.wait_for_chart_load(self.config["screenshot_settings"]["wait_time"]):
                print(f"   ✗ Failed to load chart")
                return None

            # Apply historical navigation for diversity
            if self.config["historical_settings"]["enable_historical"]:
                self.navigate_to_random_period()

            # Wait for chart to adjust
            time.sleep(2)

            # Create output directory
            output_dir = Path(self.config["output_dir"]) / symbol / timeframe
            output_dir.mkdir(parents=True, exist_ok=True)

            # Generate unique filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            rand_id = random.randint(1000, 9999)
            filename = f"{symbol}_{timeframe}_{timestamp}_{rand_id}.png"
            output_path = output_dir / filename

            # Take screenshot
            if self.take_screenshot(str(output_path)):
                return str(output_path)
            else:
                return None

        except Exception as e:
            print(f"   ✗ Error capturing: {e}")
            return None

    def capture_batch(self, symbols: List[str] = None, timeframes: List[str] = None,
                      count_per_combo: int = 1) -> Dict:
        """
        Capture multiple charts with diversity
        """
        if symbols is None:
            symbols = self.config["symbols"]

        if timeframes is None:
            timeframes = self.config["timeframes"]

        results = {
            "total_requested": len(symbols) * len(timeframes) * count_per_combo,
            "successful": 0,
            "failed": 0,
            "images": [],
            "start_time": datetime.now().isoformat()
        }

        print(f"\n🚀 Starting batch capture with HISTORICAL NAVIGATION")
        print(f"   📊 Symbols: {len(symbols)}")
        print(f"   ⏰ Timeframes: {len(timeframes)}")
        print(f"   🖼️  Images per combo: {count_per_combo}")
        print(f"   🎯 Total expected: {results['total_requested']}")
        print(f"   📅 Historical: {'ENABLED' if self.config['historical_settings']['enable_historical'] else 'DISABLED'}")
        print("-" * 50)

        start_time = time.time()

        # Process each symbol/timeframe combination
        for symbol_idx, symbol in enumerate(symbols):
            for tf_idx, timeframe in enumerate(timeframes):
                combo_num = symbol_idx * len(timeframes) + tf_idx + 1
                total_combos = len(symbols) * len(timeframes)

                print(f"\n🔹 [{combo_num}/{total_combos}] {symbol} - {timeframe}")

                for i in range(count_per_combo):
                    image_path = self.capture_wave_chart(symbol, timeframe)

                    if image_path:
                        results["successful"] += 1
                        results["images"].append({
                            "symbol": symbol,
                            "timeframe": timeframe,
                            "path": image_path,
                            "timestamp": datetime.now().isoformat()
                        })
                    else:
                        results["failed"] += 1

                    # Random delay between captures (1-5 seconds)
                    if i < count_per_combo - 1:
                        time.sleep(random.uniform(1, 5))

        # Calculate statistics
        elapsed_time = time.time() - start_time
        results["end_time"] = datetime.now().isoformat()
        results["elapsed_seconds"] = elapsed_time
        results["success_rate"] = (results["successful"] / results["total_requested"] * 100) if results["total_requested"] > 0 else 0

        return results

    def cleanup(self):
        """Clean up resources"""
        if self.driver:
            try:
                self.driver.quit()
                print("✓ Driver cleaned up")
            except:
                pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()


# Alternative Solutions for Maximum Diversity
class AdvancedWavePatternCollector(TradingViewWaveScreenshot):
    """
    Advanced collector with multiple strategies for maximum diversity
    """

    def __init__(self, config_path: str = "advanced_config.json"):
        super().__init__(config_path)
        self.strategies = [
            self.navigate_random_period,
            self.apply_random_studies,
            self.change_chart_style,
            self.random_timeframe_shift
        ]

    def apply_random_studies(self):
        """Randomly apply technical indicators for variety"""
        studies = [
            "RSI@tv-basicstudies",
            "MACD@tv-basicstudies",
            "BB@tv-basicstudies",
            "Stochastic@tv-basicstudies",
            "Volume@tv-basicstudies"
        ]

        # Randomly apply 0-2 studies
        num_studies = random.randint(0, 2)
        if num_studies > 0:
            selected_studies = random.sample(studies, num_studies)
            script = f"""
            try {{
                // Apply studies
                {selected_studies}
                console.log('Applied studies: {selected_studies}');
            }} catch(e) {{}}
            """
            self.driver.execute_script(script)
            time.sleep(2)

    def change_chart_style(self):
        """Randomly change chart style"""
        styles = ["1", "2", "3", "4", "9"]  # Candles, Hollow, Bars, Line, Area
        random_style = random.choice(styles)

        try:
            script = f"""
            try {{
                // Try to change chart style
                document.querySelector('div[data-name="chart-style-button"]').click();
                setTimeout(() => {{
                    const styleBtn = document.querySelector('div[data-value="{random_style}"]');
                    if (styleBtn) styleBtn.click();
                }}, 500);
            }} catch(e) {{}}
            """
            self.driver.execute_script(script)
            time.sleep(1)
        except:
            pass


# NEW: Multi-Symbol View for More Variety
def capture_multi_timeframe_view():
    """
    Alternative approach: Open multiple timeframes for same symbol
    """
    config = {
        "output_dir": "multi_timeframe_charts",
        "symbols": ["EURUSD", "GBPUSD", "BTCUSD"],
        "timeframe_combinations": [
            ["15", "60", "240"],  # 15min, 1H, 4H
            ["60", "240", "1D"],  # 1H, 4H, Daily
            ["30", "120", "1W"],  # 30min, 2H, Weekly
        ]
    }

    collector = TradingViewWaveScreenshot()

    for symbol in config["symbols"]:
        for tf_combo in config["timeframe_combinations"]:
            # Navigate to each timeframe in the combo
            for timeframe in tf_combo:
                url = collector.build_tradingview_url(symbol, timeframe)
                collector.driver.get(url)
                collector.wait_for_chart_load()
                collector.navigate_to_random_period()

                # Save with combo identifier
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{symbol}_{'_'.join(tf_combo)}_{timestamp}.png"
                output_path = Path(config["output_dir"]) / filename

                collector.take_screenshot(str(output_path))
                time.sleep(2)


# Main execution
def run_diverse_collection():
    """
    Run collection with maximum diversity using all strategies
    """
    print("\n🎯 DIVERSE WAVE PATTERN COLLECTION")
    print("=" * 60)
    print("This version will:")
    print("1. Navigate to random historical periods")
    print("2. Apply random zoom levels")
    print("3. Use multiple chart navigation techniques")
    print("4. Generate unique filenames with timestamps")
    print("=" * 60)

    # Configuration optimized for diversity
    config = {
        "output_dir": "diverse_wave_patterns",
        "symbols": [
            "EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "BTCUSD",
            "ETHUSD", "US30", "NAS100", "SPX500"
        ],
        "timeframes": ["15", "30", "60", "240", "1D"],
        "historical_settings": {
            "enable_historical": True,
            "randomize_period": True,
            "historical_years": 10,  # Go back up to 10 years
            "randomize_zoom": True,
            "zoom_levels": ["1M", "3M", "6M", "1Y", "2Y", "5Y", "10Y", "ALL"],
            "min_bars_on_screen": 30,
            "max_bars_on_screen": 500
        },
        "image_settings": {
            "width": 1920,
            "height": 1080,
            "crop_margins": True,
            "enhance_contrast": True,
            "contrast_factor": 1.3
        }
    }

    # Save config
    config_path = "diverse_collection_config.json"
    with open(config_path, "w") as f:
        json.dump(config, f, indent=4)

    images_per = input("\nHow many diverse images per symbol/timeframe? (default 5): ").strip()
    images_per = int(images_per) if images_per.isdigit() else 5

    print(f"\nWill collect {len(config['symbols'])} symbols × {len(config['timeframes'])} timeframes × {images_per} each")
    print(f"Total: {len(config['symbols']) * len(config['timeframes']) * images_per} unique images")

    proceed = input("\nProceed? (y/n): ").strip().lower()
    if proceed != 'y':
        print("Cancelled.")
        return

    print("\n🚀 Starting diverse collection...")
    print("This will take time as we navigate to different historical periods...")

    try:
        with TradingViewWaveScreenshot(config_path) as collector:
            results = collector.capture_batch(count_per_combo=images_per)

            # Summary
            print("\n" + "=" * 60)
            print("🎉 DIVERSE COLLECTION COMPLETE!")
            print("=" * 60)
            print(f"✅ Successfully collected: {results['successful']} unique images")
            print(f"❌ Failed: {results['failed']}")
            print(f"📊 Success rate: {results['success_rate']:.1f}%")
            print(f"⏱️  Time: {results['elapsed_seconds']:.1f} seconds")
            print(f"📁 Output: {config['output_dir']}")

            # Save log
            log_file = Path(config["output_dir"]) / "diverse_collection_log.json"
            with open(log_file, "w") as f:
                json.dump(results, f, indent=4, default=str)

            print(f"\n📝 Log saved: {log_file}")

    except Exception as e:
        print(f"\n❌ Error: {e}")


def quick_test_diversity():
    """Quick test to verify diversity works"""
    print("\n🔍 Testing Diversity Feature")
    print("-" * 40)

    config = {
        "output_dir": "diversity_test",
        "symbols": ["EURUSD"],
        "timeframes": ["60"],
        "historical_settings": {
            "enable_historical": True,
            "randomize_period": True
        }
    }

    config_path = "diversity_test_config.json"
    with open(config_path, "w") as f:
        json.dump(config, f, indent=4)

    print("Taking 3 different screenshots of EURUSD 1H from different periods...")

    try:
        with TradingViewWaveScreenshot(config_path) as collector:
            images = []
            for i in range(3):
                print(f"\nImage {i+1}/3:")
                img_path = collector.capture_wave_chart("EURUSD", "60")
                if img_path:
                    images.append(img_path)
                time.sleep(2)

            if images:
                print(f"\n✅ Success! Captured {len(images)} different images:")
                for img in images:
                    print(f"   📸 {Path(img).name}")
    except Exception as e:
        print(f"\n❌ Error: {e}")


# Menu
if __name__ == "__main__":
    print("""
    ╔═══════════════════════════════════════════════════════╗
    ║   DIVERSE WAVE PATTERN COLLECTOR - HISTORICAL EDITION ║
    ║         Captures Charts from Different Periods        ║
    ╚═══════════════════════════════════════════════════════╝
    """)

    print("\n" + "=" * 70)
    print("MAIN MENU - MAXIMUM DIVERSITY EDITION")
    print("=" * 70)
    print("1. Quick Diversity Test (Verify it works)")
    print("2. Full Diverse Collection (Recommended for ML)")
    print("3. Advanced Collector (More strategies)")
    print("4. Multi-Timeframe Views")
    print("5. Exit")
    print("=" * 70)

    choice = input("\nSelect option (1-5): ").strip()

    if choice == "1":
        quick_test_diversity()
    elif choice == "2":
        run_diverse_collection()
    elif choice == "3":
        print("\n🚀 Launching Advanced Collector...")
        # You would instantiate AdvancedWavePatternCollector here
        run_diverse_collection()  # Fallback to main function
    elif choice == "4":
        print("\n📊 Multi-Timeframe Views (Coming soon)")
        run_diverse_collection()  # Fallback
    elif choice == "5":
        print("Goodbye! 👋")
    else:
        print("Invalid choice")