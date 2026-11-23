import tkinter as tk
from tkinter import messagebox, ttk
import swisseph as swe
from datetime import datetime, timedelta
import os
import math

# --- EPHEMERIS PATH SETUP ---
current_dir = os.path.dirname(os.path.abspath(__file__))
ephe_path = os.path.join(current_dir, 'ephe')
if not os.path.exists(ephe_path):
    os.makedirs(ephe_path)
swe.set_ephe_path(ephe_path)

# --- PLANET MAPPING ---
PLANETS = {
    "Sun": swe.SUN, "Moon": swe.MOON, "Mercury": swe.MERCURY, "Venus": swe.VENUS,
    "Mars": swe.MARS, "Jupiter": swe.JUPITER, "Saturn": swe.SATURN, "Uranus": swe.URANUS,
    "Neptune": swe.NEPTUNE, "Pluto": swe.PLUTO, "T.N. Node": swe.TRUE_NODE, "Ceres": swe.CERES,
    "Pallas": swe.PALLAS, "Juno": swe.JUNO, "Vesta": swe.VESTA, "Chiron": swe.CHIRON,
    "Cupido": swe.CUPIDO, "Hades": swe.HADES, "Zeus": swe.ZEUS, "Kronos": swe.KRONOS,
    "Apollon": swe.APOLLON, "Admetos": swe.ADMETOS, "Vulkanus": swe.VULKANUS,
    "Poseidon": swe.POSEIDON, "Transpluto": swe.FICT_OFFSET + 1
}

ZODIAC = ["Ari", "Tau", "Gem", "Cnc", "Leo", "Vir", "Lib", "Sco", "Sag", "Cap", "Aqu", "Pis"]
SIGN_NAMES = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra", "Scorpio", "Sagittarius", "Capricorn",
              "Aquarius", "Pisces"]

# --- GEOMETRIC ASPECTS ---
GEOMETRIC_ASPECTS = {
    "Conjunction (0°)": 0,
    "Semisextile (30°)": 30,
    "Semi-square (45°)": 45,
    "Sextile (60°)": 60,
    "Square (90°)": 90,
    "Trine (120°)": 120,
    "Sesquiquadrate (135°)": 135,
    "Quincunx (150°)": 150,
    "Opposition (180°)": 180
}

# --- FULL EVENT LIST ---
EVENT_ITEMS = []

# Generic sign ingress
EVENT_ITEMS.append(("Generic Sign Ingress", "INGRESS_GENERIC"))

# Per‑sign ingress
for i, sign in enumerate(SIGN_NAMES):
    EVENT_ITEMS.append((f"Planet enters {sign}", f"INGRESS_{i}"))

# Retrograde / Direct
EVENT_ITEMS.append(("Retrograde Station", "RETRO"))
EVENT_ITEMS.append(("Direct Station", "DIRECT"))
EVENT_ITEMS.append(("Going Retrograde", "RETRO"))
EVENT_ITEMS.append(("Going Direct", "DIRECT"))

# Lunar events
EVENT_ITEMS.append(("New Moon", "NEW_MOON"))
EVENT_ITEMS.append(("Full Moon", "FULL_MOON"))
EVENT_ITEMS.append(("Solar Eclipse", "SOLAR_ECLIPSE"))
EVENT_ITEMS.append(("Lunar Eclipse", "LUNAR_ECLIPSE"))

# Crossing specific degrees
EVENT_ITEMS.append(("Crossing 15° of any sign", "CROSS_15"))
EVENT_ITEMS.append(("Crossing 24° of any sign", "CROSS_24"))

# Latitude events
EVENT_ITEMS.append(("Crossing 0° Latitude", "LAT_ZERO"))
EVENT_ITEMS.append(("Max North Latitude", "LAT_MAX_NORTH"))
EVENT_ITEMS.append(("Max South Latitude", "LAT_MAX_SOUTH"))

# Distance events
EVENT_ITEMS.append(("Aphelion", "APHELION"))
EVENT_ITEMS.append(("Perihelion", "PERIHELION"))

# --- NEW EVENTS (requested) ---
EVENT_ITEMS.append(("Planets in Conjunction", "CONJUNCTION"))
EVENT_ITEMS.append(("Planets in Parallel", "PARALLEL"))
EVENT_ITEMS.append(("Planets in Contraparallel", "CONTRAPARALLEL"))
EVENT_ITEMS.append(("Latitude Conjunction", "LAT_CONJUNCTION"))
EVENT_ITEMS.append(("Latitude Angle Between", "LAT_ANGLE"))
EVENT_ITEMS.append(("Planet at Fixed Degree", "FIXED_DEGREE"))

# Mystery events
EVENT_ITEMS.append(("Nature's Reversal Dates", "REVERSAL"))
EVENT_ITEMS.append(("Moon Void of Course", "VOID_MOON"))

# Remove duplicates by converting to dict
unique_events = {}
for name, key in EVENT_ITEMS:
    unique_events[name] = key
EVENT_NAMES = list(unique_events.keys())
EVENT_KEYS = list(unique_events.values())


# --- FORMATTING & REFINERS ---
def format_zet_degree(longitude):
    sign_idx = int(longitude // 30)
    rem = longitude % 30
    deg = int(rem)
    mins = int((rem - deg) * 60)
    secs = int((((rem - deg) * 60) - mins) * 60)
    return f"{deg}°{mins:02d}'{secs:02d}\"{ZODIAC[sign_idx]}"


def format_zet_datetime(dt):
    return f"{dt.strftime('%d.%m.%Y')}  {dt.hour}:{dt.minute:02d}:{dt.second:02d}"


def get_exact_dt_string(jd):
    """Converts a highly precise Julian Day into the exact ZET 9 Date/Time string."""
    y, m, d, h_float = swe.revjul(jd, swe.GREG_CAL)
    hour = int(h_float)
    minute = int((h_float - hour) * 60)
    second = int((((h_float - hour) * 60) - minute) * 60)
    return f"{d:02d}.{m:02d}.{y}  {hour}:{minute:02d}:{second:02d}"


def get_planet_data(jd, p_id):
    flags = swe.FLG_MOSEPH | swe.FLG_SPEED
    try:
        calc, _ = swe.calc_ut(jd, p_id, flags)
        return calc[0], calc[1], calc[2], calc[3]
    except swe.Error:
        return 0.0, 0.0, 1.0, 1.0


def get_declination(jd, lon, lat):
    xeq = swe.cotrans((lon, lat, 1.0), 0.0)
    return xeq[1]


# --- MINUTE REFINERS (For ZET 9 Precision) ---
def refine_aspect(jd_start, p1_id, p2_id, target_angle):
    """Scans the 24h window minute-by-minute to find the exact time of perfection."""
    min_error = 999.0
    best_jd = jd_start
    for m in range(1440):
        test_jd = jd_start + (m / 1440.0)
        l1, _, _, _ = get_planet_data(test_jd, p1_id)
        l2, _, _, _ = get_planet_data(test_jd, p2_id)
        diff = abs(l1 - l2)
        if diff > 180: diff = 360 - diff
        error = abs(diff - target_angle)
        if error < min_error:
            min_error = error
            best_jd = test_jd
    return best_jd


def refine_ingress(jd_start, p_id):
    """Finds exact minute a planet changes signs."""
    lon_start, _, _, _ = get_planet_data(jd_start, p_id)
    start_sign = int(lon_start // 30)
    for m in range(1440):
        test_jd = jd_start + (m / 1440.0)
        l, _, _, _ = get_planet_data(test_jd, p_id)
        if int(l // 30) != start_sign:
            return test_jd
    return jd_start + 0.5


def refine_station(jd_start, p_id):
    """Finds the exact minute a planet's speed hits 0.0 (Retrograde/Direct)."""
    min_speed = 999.0
    best_jd = jd_start
    for m in range(1440):
        test_jd = jd_start + (m / 1440.0)
        _, _, _, speed = get_planet_data(test_jd, p_id)
        if abs(speed) < min_speed:
            min_speed = abs(speed)
            best_jd = test_jd
    return best_jd


# --- SCANNER ---
def scan_events(start_dt, end_dt, selected_planets, selected_event_keys, aspect_angle=None, target_degree=15):
    results = []
    current_dt = start_dt
    total_days = (end_dt - start_dt).days + 1

    prev2_data = {}
    prev1_data = {}
    today_data = {}
    ORB = 1.0

    for day in range(total_days):
        jd = swe.julday(current_dt.year, current_dt.month, current_dt.day,
                        current_dt.hour + current_dt.minute / 60.0 + current_dt.second / 3600.0)

        today_data = {}
        for planet in selected_planets:
            p_id = PLANETS[planet]
            lon, lat, dist, speed = get_planet_data(jd, p_id)
            decl = get_declination(jd, lon, lat)
            today_data[planet] = (lon, lat, dist, speed, decl)

        dt_str = format_zet_datetime(current_dt)

        # 1. Generic Sign Ingress
        if "INGRESS_GENERIC" in selected_event_keys and day > 0:
            for planet in selected_planets:
                if int(prev1_data[planet][0] // 30) != int(today_data[planet][0] // 30):
                    exact_jd = refine_ingress(jd - 1, PLANETS[planet])
                    exact_lon, _, _, _ = get_planet_data(exact_jd, PLANETS[planet])
                    results.append(f"{get_exact_dt_string(exact_jd)}  {format_zet_degree(exact_lon)} <<< {planet}")

        # 2. Per-sign Ingress
        selected_ingress_signs = [i for i in range(12) if f"INGRESS_{i}" in selected_event_keys]
        if selected_ingress_signs and day > 0:
            for planet in selected_planets:
                curr_sign = int(today_data[planet][0] // 30)
                if int(prev1_data[planet][0] // 30) != curr_sign and curr_sign in selected_ingress_signs:
                    exact_jd = refine_ingress(jd - 1, PLANETS[planet])
                    exact_lon, _, _, _ = get_planet_data(exact_jd, PLANETS[planet])
                    results.append(
                        f"{get_exact_dt_string(exact_jd)}  {format_zet_degree(exact_lon)} <<< {planet} enters {SIGN_NAMES[curr_sign]}")

        # 3. Retrograde / Direct stations
        if ("RETRO" in selected_event_keys or "DIRECT" in selected_event_keys) and day > 0:
            for planet in selected_planets:
                if prev1_data[planet][3] > 0 and today_data[planet][3] <= 0 and "RETRO" in selected_event_keys:
                    exact_jd = refine_station(jd - 1, PLANETS[planet])
                    exact_lon, _, _, _ = get_planet_data(exact_jd, PLANETS[planet])
                    results.append(
                        f"{get_exact_dt_string(exact_jd)}  {format_zet_degree(exact_lon)} <<< {planet} Retrograde Station")
                elif prev1_data[planet][3] < 0 and today_data[planet][3] >= 0 and "DIRECT" in selected_event_keys:
                    exact_jd = refine_station(jd - 1, PLANETS[planet])
                    exact_lon, _, _, _ = get_planet_data(exact_jd, PLANETS[planet])
                    results.append(
                        f"{get_exact_dt_string(exact_jd)}  {format_zet_degree(exact_lon)} <<< {planet} Direct Station")

        # 4 & 5. NEW MOON, FULL MOON, AND ECLIPSES (ZET 9 Precision)
        if any(k in selected_event_keys for k in ["NEW_MOON", "FULL_MOON", "SOLAR_ECLIPSE", "LUNAR_ECLIPSE"]):
            if day > 0:
                s_lon, _, _, _ = get_planet_data(jd, swe.SUN)
                m_lon, _, _, _ = get_planet_data(jd, swe.MOON)
                p_s_lon, _, _, _ = get_planet_data(jd - 1, swe.SUN)
                p_m_lon, _, _, _ = get_planet_data(jd - 1, swe.MOON)

                rel_lon = (m_lon - s_lon) % 360
                p_rel_lon = (p_m_lon - p_s_lon) % 360

                is_new_moon = (p_rel_lon > 340 and rel_lon < 20)
                is_full_moon = (p_rel_lon < 180 and rel_lon >= 180)

                if is_new_moon:
                    exact_jd = refine_aspect(jd - 1, swe.SUN, swe.MOON, 0)
                    exact_dt = get_exact_dt_string(exact_jd)
                    exact_s_lon, _, _, _ = get_planet_data(exact_jd, swe.SUN)
                    deg_str = format_zet_degree(exact_s_lon)

                    if "NEW_MOON" in selected_event_keys:
                        results.append(f"{exact_dt}  {deg_str} <<< Sun New Moon")

                    if "SOLAR_ECLIPSE" in selected_event_keys:
                        n_lon, _, _, _ = get_planet_data(exact_jd, swe.TRUE_NODE)
                        dist_node = min(abs(exact_s_lon - n_lon), 360 - abs(exact_s_lon - n_lon))
                        dist_node = min(dist_node, abs(180 - dist_node))
                        if dist_node <= 18.5:
                            results.append(f"{exact_dt}  {deg_str} <<< Sun Solar Eclipse")

                if is_full_moon:
                    exact_jd = refine_aspect(jd - 1, swe.SUN, swe.MOON, 180)
                    exact_dt = get_exact_dt_string(exact_jd)
                    exact_m_lon, _, _, _ = get_planet_data(exact_jd, swe.MOON)
                    deg_str = format_zet_degree(exact_m_lon)

                    if "FULL_MOON" in selected_event_keys:
                        results.append(f"{exact_dt}  {deg_str} <<< Moon Full Moon")

                    if "LUNAR_ECLIPSE" in selected_event_keys:
                        n_lon, _, _, _ = get_planet_data(exact_jd, swe.TRUE_NODE)
                        dist_node = min(abs(exact_m_lon - n_lon), 360 - abs(exact_m_lon - n_lon))
                        dist_node = min(dist_node, abs(180 - dist_node))
                        if dist_node <= 12.2:
                            results.append(f"{exact_dt}  {deg_str} <<< Moon Lunar Eclipse")

        # 6. Crossing 15° or 24° of any sign
        if "CROSS_15" in selected_event_keys or "CROSS_24" in selected_event_keys:
            for planet in selected_planets:
                if day > 0:
                    pf, cf, spd = prev1_data[planet][0] % 30, today_data[planet][0] % 30, today_data[planet][3]
                    for deg, key in [(15, "CROSS_15"), (24, "CROSS_24")]:
                        if key in selected_event_keys:
                            if (spd > 0 and pf < deg <= cf) or (spd < 0 and pf > deg >= cf):
                                results.append(
                                    f"{dt_str}  {format_zet_degree(today_data[planet][0])} <<< {planet} Crossing {deg}°")

        # 7. Crossing 0° Latitude
        if "LAT_ZERO" in selected_event_keys and day > 0:
            for planet in selected_planets:
                if prev1_data[planet][1] * today_data[planet][1] <= 0 and abs(prev1_data[planet][1]) > 0.001:
                    results.append(f"{dt_str}  {format_zet_degree(today_data[planet][0])} <<< {planet} Crossing 0° Lat")

        # 8. Max North / South Latitude
        if ("LAT_MAX_NORTH" in selected_event_keys or "LAT_MAX_SOUTH" in selected_event_keys) and day >= 2:
            for planet in selected_planets:
                l0, l1, l2 = prev2_data[planet][1], prev1_data[planet][1], today_data[planet][1]
                if "LAT_MAX_NORTH" in selected_event_keys and l1 > l0 and l1 > l2:
                    results.append(
                        f"{dt_str}  {format_zet_degree(prev1_data[planet][0])} <<< {planet} Max North Latitude")
                if "LAT_MAX_SOUTH" in selected_event_keys and l1 < l0 and l1 < l2:
                    results.append(
                        f"{dt_str}  {format_zet_degree(prev1_data[planet][0])} <<< {planet} Max South Latitude")

        # 9. Aphelion / Perihelion
        if ("APHELION" in selected_event_keys or "PERIHELION" in selected_event_keys) and day >= 2:
            for planet in selected_planets:
                d0, d1, d2 = prev2_data[planet][2], prev1_data[planet][2], today_data[planet][2]
                if "APHELION" in selected_event_keys and d1 > d0 and d1 > d2:
                    results.append(f"{dt_str}  {format_zet_degree(prev1_data[planet][0])} <<< {planet} Aphelion")
                if "PERIHELION" in selected_event_keys and d1 < d0 and d1 < d2:
                    results.append(f"{dt_str}  {format_zet_degree(prev1_data[planet][0])} <<< {planet} Perihelion")

        # 10. Planets in Conjunction
        if "CONJUNCTION" in selected_event_keys and len(selected_planets) >= 2:
            for i, p1 in enumerate(selected_planets):
                for p2 in selected_planets[i + 1:]:
                    diff = abs(today_data[p1][0] - today_data[p2][0])
                    if diff > 180: diff = 360 - diff
                    if day > 0:
                        pd = abs(prev1_data[p1][0] - prev1_data[p2][0])
                        if pd > 180: pd = 360 - pd
                        if (pd <= ORB and diff >= ORB) or (pd >= ORB and diff <= ORB):
                            exact_jd = refine_aspect(jd - 1, PLANETS[p1], PLANETS[p2], 0)
                            exact_lon, _, _, _ = get_planet_data(exact_jd, PLANETS[p2])
                            results.append(
                                f"{get_exact_dt_string(exact_jd)}  {format_zet_degree(exact_lon)} <<< {p1} Conjunction {p2}")

        # 11. Planets in Parallel
        if "PARALLEL" in selected_event_keys and len(selected_planets) >= 2:
            for i, p1 in enumerate(selected_planets):
                for p2 in selected_planets[i + 1:]:
                    diff, pd = abs(today_data[p1][4] - today_data[p2][4]), abs(prev1_data[p1][4] - prev1_data[p2][4])
                    if day > 0 and ((pd <= ORB and diff >= ORB) or (pd >= ORB and diff <= ORB)):
                        results.append(
                            f"{dt_str}  {format_zet_degree(today_data[p1][0])} <<< {p1} Parallel {p2} (decl {today_data[p1][4]:.2f}°, {today_data[p2][4]:.2f}°)")

        # 12. Planets in Contraparallel
        if "CONTRAPARALLEL" in selected_event_keys and len(selected_planets) >= 2:
            for i, p1 in enumerate(selected_planets):
                for p2 in selected_planets[i + 1:]:
                    diff, pd = abs(abs(today_data[p1][4]) - abs(today_data[p2][4])), abs(
                        abs(prev1_data[p1][4]) - abs(prev1_data[p2][4]))
                    if day > 0 and ((pd <= ORB and diff >= ORB) or (pd >= ORB and diff <= ORB)):
                        results.append(
                            f"{dt_str}  {format_zet_degree(today_data[p1][0])} <<< {p1} Contraparallel {p2} (decl {today_data[p1][4]:.2f}°, {today_data[p2][4]:.2f}°)")

        # 13. Latitude Conjunction
        if "LAT_CONJUNCTION" in selected_event_keys and len(selected_planets) >= 2:
            for i, p1 in enumerate(selected_planets):
                for p2 in selected_planets[i + 1:]:
                    diff, pd = abs(today_data[p1][1] - today_data[p2][1]), abs(prev1_data[p1][1] - prev1_data[p2][1])
                    if day > 0 and ((pd <= ORB and diff >= ORB) or (pd >= ORB and diff <= ORB)):
                        results.append(
                            f"{dt_str}  {format_zet_degree(today_data[p1][0])} <<< {p1} Latitude Conjunction {p2}")

        # 14. Latitude Angle Between
        if "LAT_ANGLE" in selected_event_keys and len(selected_planets) >= 2:
            target = float(target_degree)
            for i, p1 in enumerate(selected_planets):
                for p2 in selected_planets[i + 1:]:
                    diff, pd = abs(today_data[p1][1] - today_data[p2][1]), abs(prev1_data[p1][1] - prev1_data[p2][1])
                    if day > 0 and ((pd <= target and diff >= target) or (pd >= target and diff <= target)):
                        results.append(
                            f"{dt_str}  {format_zet_degree(today_data[p1][0])} <<< {p1} Latitude {target}° {p2}")

        # 15. Planet at Fixed Degree
        if "FIXED_DEGREE" in selected_event_keys:
            fixed = float(target_degree) % 30
            for planet in selected_planets:
                if day > 0:
                    pf, cf, spd = prev1_data[planet][0] % 30, today_data[planet][0] % 30, today_data[planet][3]
                    if (spd > 0 and pf < fixed <= cf) or (spd < 0 and pf > fixed >= cf):
                        results.append(f"{dt_str}  {format_zet_degree(today_data[planet][0])} <<< {planet} at {fixed}°")

        # 16 & 17. Geometric Aspects (ZET 9 Precision)
        if aspect_angle is not None and len(selected_planets) >= 2:
            b_lon = today_data[selected_planets[0]][0]
            for target in selected_planets[1:]:
                t_lon = today_data[target][0]
                diff = abs(b_lon - t_lon)
                if diff > 180: diff = 360 - diff
                if day > 0:
                    pd = abs(prev1_data[selected_planets[0]][0] - prev1_data[target][0])
                    if pd > 180: pd = 360 - pd
                    if (pd <= aspect_angle and diff >= aspect_angle) or (pd >= aspect_angle and diff <= aspect_angle):
                        exact_jd = refine_aspect(jd - 1, PLANETS[selected_planets[0]], PLANETS[target], aspect_angle)
                        exact_lon, _, _, _ = get_planet_data(exact_jd, PLANETS[target])
                        aspect_name = [k for k, v in GEOMETRIC_ASPECTS.items() if v == aspect_angle][0]
                        results.append(
                            f"{get_exact_dt_string(exact_jd)}  {format_zet_degree(exact_lon)} <<< {target} {aspect_name} {selected_planets[0]}")

        prev2_data, prev1_data = prev1_data.copy(), today_data.copy()
        current_dt += timedelta(days=1)

    return results

# --- GUI APPLICATION ---
class App(tk.Tk):
    def __init__(self):
        super().__init__()

        # --- REFINED THEME CONFIGURATION ---
        self.bg_color = "#0b0e14"  # Deep Space Black/Blue background
        self.frame_bg = "#151a22"  # Slightly lighter for active panels
        self.text_color = "#a1aab8"  # Soft grey for reading comfort
        self.header_color = "#e2e8f0"  # Crisp bright text for headers
        self.accent_color = "#2962ff"  # Vibrant blue accent (Trading style)
        self.accent_hover = "#1e4eb8"  # Darker blue on hover

        self.title("Galactic Aspect Engine | ZET 9 Pro")
        self.geometry("1100x850")
        self.minsize(900, 700)  # Prevents the UI from being crushed too small
        self.configure(bg=self.bg_color)

        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure("TCombobox", fieldbackground=self.frame_bg, background=self.frame_bg, foreground="white")
        style.configure("Vertical.TScrollbar", background=self.frame_bg, troughcolor=self.bg_color,
                        bordercolor=self.bg_color, arrowcolor=self.text_color)

        self.selected_planets = {p: tk.IntVar(value=1) for p in PLANETS}
        self.selected_events = {name: tk.IntVar(value=0) for name in EVENT_NAMES}
        self.aspect_angle = tk.StringVar(value="None")
        self.target_degree = tk.StringVar(value="15")
        self.start_date = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
        self.end_date = tk.StringVar(value=(datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"))

        self._build_ui()

    def _build_ui(self):
        header = tk.Label(self, text="GALACTIC ASPECT ENGINE", font=("Segoe UI", 22, "bold"),
                          bg=self.bg_color, fg=self.header_color)
        header.pack(pady=(25, 15))

        # Main wrapper padding - flexible
        main_container = tk.Frame(self, bg=self.bg_color)
        main_container.pack(fill=tk.BOTH, expand=True, padx=30, pady=(0, 25))

        # --- 1. DATE SELECTION FRAME ---
        date_frame = tk.LabelFrame(main_container, text=" Observation Window ", font=("Segoe UI", 11, "bold"),
                                   bg=self.frame_bg, fg=self.accent_color, bd=1, labelanchor='nw')
        date_frame.pack(fill=tk.X, pady=(0, 20), ipady=15, ipadx=10)

        tk.Label(date_frame, text="Start Date (YYYY-MM-DD):", font=("Segoe UI", 10), bg=self.frame_bg,
                 fg=self.text_color).pack(side=tk.LEFT, padx=(15, 5))
        start_entry = tk.Entry(date_frame, textvariable=self.start_date, width=15, bg="#0b0e14", fg="white",
                               insertbackground="white", bd=0, font=("Consolas", 12))
        start_entry.pack(side=tk.LEFT, padx=5, ipady=4)

        tk.Label(date_frame, text="End Date (YYYY-MM-DD):", font=("Segoe UI", 10), bg=self.frame_bg,
                 fg=self.text_color).pack(side=tk.LEFT, padx=(40, 5))
        end_entry = tk.Entry(date_frame, textvariable=self.end_date, width=15, bg="#0b0e14", fg="white",
                             insertbackground="white", bd=0, font=("Consolas", 12))
        end_entry.pack(side=tk.LEFT, padx=5, ipady=4)

        # --- 2. MIDDLE TWO-COLUMN LAYOUT (Flexible) ---
        mid_container = tk.Frame(main_container, bg=self.bg_color)
        mid_container.pack(fill=tk.BOTH, expand=True)

        # Left Column: Planets (Expands)
        planet_frame = tk.LabelFrame(mid_container, text=" Celestial Bodies ", font=("Segoe UI", 11, "bold"),
                                     bg=self.frame_bg, fg=self.accent_color, bd=1)
        planet_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        planet_inner = tk.Frame(planet_frame, bg=self.frame_bg)
        planet_inner.pack(padx=15, pady=15, fill=tk.BOTH, expand=True)

        # Make planet grid columns expandable
        for i in range(3):
            planet_inner.columnconfigure(i, weight=1)

        col, row = 0, 0
        for planet in PLANETS:
            cb = tk.Checkbutton(planet_inner, text=planet, variable=self.selected_planets[planet],
                                font=("Segoe UI", 10), bg=self.frame_bg, fg=self.header_color,
                                selectcolor=self.bg_color, activebackground=self.frame_bg, activeforeground="white")
            cb.grid(row=row, column=col, sticky='w', padx=5, pady=4)
            col += 1
            if col > 2:
                col = 0
                row += 1

        # Right Column: Events (Expands)
        event_frame = tk.LabelFrame(mid_container, text=" Event Triggers ", font=("Segoe UI", 11, "bold"),
                                    bg=self.frame_bg, fg=self.accent_color, bd=1)
        event_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(10, 0))

        event_canvas = tk.Canvas(event_frame, bg=self.frame_bg, highlightthickness=0)
        event_scrollbar = ttk.Scrollbar(event_frame, orient="vertical", command=event_canvas.yview)
        event_scrollable_frame = tk.Frame(event_canvas, bg=self.frame_bg)

        event_scrollable_frame.bind("<Configure>",
                                    lambda e: event_canvas.configure(scrollregion=event_canvas.bbox("all")))
        event_canvas.create_window((0, 0), window=event_scrollable_frame, anchor="nw")
        event_canvas.configure(yscrollcommand=event_scrollbar.set)

        event_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 0), pady=10)
        event_scrollbar.pack(side=tk.RIGHT, fill=tk.Y, pady=10)

        col, row = 0, 0
        for name in EVENT_NAMES:
            cb = tk.Checkbutton(event_scrollable_frame, text=name, variable=self.selected_events[name],
                                font=("Segoe UI", 10), bg=self.frame_bg, fg=self.header_color, wraplength=180,
                                justify="left",
                                selectcolor=self.bg_color, activebackground=self.frame_bg, activeforeground="white")
            cb.grid(row=row, column=col, sticky='nw', padx=10, pady=5)
            row += 1
            if row > 12:
                row = 0
                col += 1

        # --- 3. BOTTOM PARAMETERS & BUTTON FRAME ---
        bottom_frame = tk.LabelFrame(main_container, text=" Parameters & Export ", font=("Segoe UI", 11, "bold"),
                                     bg=self.frame_bg, fg=self.accent_color, bd=1)
        bottom_frame.pack(fill=tk.X, pady=(20, 0), ipady=15, ipadx=10)

        tk.Label(bottom_frame, text="Geometric Aspect:", font=("Segoe UI", 10), bg=self.frame_bg,
                 fg=self.text_color).pack(side=tk.LEFT, padx=(15, 5))
        values = ["None"] + list(GEOMETRIC_ASPECTS.keys())
        self.aspect_menu = ttk.Combobox(bottom_frame, textvariable=self.aspect_angle, values=values, state="readonly",
                                        width=22, font=("Segoe UI", 10))
        self.aspect_menu.pack(side=tk.LEFT, padx=5)

        tk.Label(bottom_frame, text="Target Degree:", font=("Segoe UI", 10), bg=self.frame_bg, fg=self.text_color).pack(
            side=tk.LEFT, padx=(30, 5))
        deg_entry = tk.Entry(bottom_frame, textvariable=self.target_degree, width=8, bg="#0b0e14", fg="white",
                             insertbackground="white", bd=0, font=("Consolas", 12))
        deg_entry.pack(side=tk.LEFT, padx=5, ipady=4)

        self.btn_run = tk.Button(bottom_frame, text="GENERATE & SAVE CSV", command=self.run_scanner,
                                 bg=self.accent_color, fg="white", font=("Segoe UI", 11, "bold"),
                                 bd=0, activebackground=self.accent_hover, activeforeground="white",
                                 padx=25, pady=10, cursor="hand2")
        self.btn_run.pack(side=tk.RIGHT, padx=20)

        self.btn_run.bind("<Enter>", lambda e: e.widget.config(bg=self.accent_hover))
        self.btn_run.bind("<Leave>", lambda e: e.widget.config(bg=self.accent_color))

    def run_scanner(self):
        active_planets = [p for p, var in self.selected_planets.items() if var.get() == 1]
        if not active_planets:
            messagebox.showwarning("Error", "Please select at least one planet.")
            return

        active_event_keys = [unique_events[name] for name in EVENT_NAMES if self.selected_events[name].get() == 1]
        if not active_event_keys and self.aspect_angle.get() == "None":
            messagebox.showwarning("Error", "Please select at least one event or a geometric aspect.")
            return

        try:
            start = datetime.strptime(self.start_date.get(), "%Y-%m-%d")
            end = datetime.strptime(self.end_date.get(), "%Y-%m-%d")
            if start > end:
                messagebox.showerror("Error", "Start date must be before end date.")
                return
        except ValueError:
            messagebox.showerror("Error", "Invalid date format. Use YYYY-MM-DD.")
            return

        angle = None
        if self.aspect_angle.get() in GEOMETRIC_ASPECTS:
            angle = GEOMETRIC_ASPECTS[self.aspect_angle.get()]

        try:
            tdeg = float(self.target_degree.get()) if self.target_degree.get().strip() else 15.0
        except ValueError:
            tdeg = 15.0

        # Run logic
        results = scan_events(start, end, active_planets, active_event_keys, angle, tdeg)

        # --- UPDATED SAVE LOGIC ---
        export_dir = os.path.join(current_dir, "ZET9_Exports")
        if not os.path.exists(export_dir):
            os.makedirs(export_dir)

        timestamp = datetime.now().strftime("%H%M%S")
        file_name = f"Aspects_{start.strftime('%Y%m%d')}_{timestamp}.csv"
        filepath = os.path.join(export_dir, file_name)

        # Writing with exact alignment requested
        with open(filepath, "w", encoding="utf-8") as f:
            for line in results:
                # 'line' is already formatted as "DD.MM.YYYY HH:MM:SS  DEGREE <<< PLANET"
                f.write(f"{line}\n")

        messagebox.showinfo("Success", f"Found {len(results)} events.\n\nFile: {file_name}")


if __name__ == "__main__":
    app = App()
    app.mainloop()