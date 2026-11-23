import cv2
import numpy as np
from pathlib import Path


# ---------------- Candle Extraction ---------------- #

def extract_candles(image_bgr):
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)

    # ---- Detect GREEN candles ----
    lower_green = np.array([35, 50, 50])
    upper_green = np.array([90, 255, 255])
    green_mask = cv2.inRange(hsv, lower_green, upper_green)

    # ---- Detect RED candles (two ranges in HSV) ----
    lower_red1 = np.array([0, 50, 50])
    upper_red1 = np.array([10, 255, 255])
    lower_red2 = np.array([170, 50, 50])
    upper_red2 = np.array([180, 255, 255])

    red_mask1 = cv2.inRange(hsv, lower_red1, upper_red1)
    red_mask2 = cv2.inRange(hsv, lower_red2, upper_red2)
    red_mask = cv2.bitwise_or(red_mask1, red_mask2)

    # ---- Combine candle colors ----
    color_mask = cv2.bitwise_or(green_mask, red_mask)

    # ---- Clean up mask ----
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 5))
    color_mask = cv2.morphologyEx(color_mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    color_mask = cv2.morphologyEx(color_mask, cv2.MORPH_OPEN, kernel, iterations=1)

    # ---- Remove small noise ----
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        color_mask, connectivity=8
    )

    final_mask = np.zeros_like(color_mask)

    for i in range(1, num_labels):
        area = stats[i, cv2.CC_STAT_AREA]
        height = stats[i, cv2.CC_STAT_HEIGHT]

        # Candle heuristic
        if area > 100 and height > 8:
            final_mask[labels == i] = 255

    # ---- Apply mask (KEEP COLORS) ----
    candle_only = cv2.bitwise_and(image_bgr, image_bgr, mask=final_mask)

    return candle_only


# ---------------- Batch Pipeline ---------------- #

def process_directory(input_dir, output_dir):
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    images = list(input_dir.glob("*.png")) + \
             list(input_dir.glob("*.jpg")) + \
             list(input_dir.glob("*.jpeg"))

    print(f"Processing {len(images)} images...")

    for img_path in images:
        image = cv2.imread(str(img_path))
        if image is None:
            print(f"Skipping {img_path.name}")
            continue

        candle_img = extract_candles(image)

        out_path = output_dir / f"{img_path.stem}.png"
        cv2.imwrite(str(out_path), candle_img)

    print("Done ✅")


# ---------------- Run ---------------- #

if __name__ == "__main__":
    INPUT_DIR = "input_charts"
    OUTPUT_DIR = "output_candles"

    process_directory(INPUT_DIR, OUTPUT_DIR)
