import bz2
import json
import os
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import contourpy
import numpy as np
from PIL import Image


# Variabelen die als vector-contouren (GeoJSON) worden gerenderd i.p.v. raster-PNG.
# Uitbreidbaar: later bv. neerslagzones hier ook aan toevoegen.
CONTOUR_VARIABLES = {
    "pmsl": {
        "interval": 5,       # isobaar elke 5 hPa (standaard synoptische kaarten)
        "unit_divisor": 100,  # GRIB levert Pa, isobaren tonen we in hPa
    },
}


DWD_BASE = "https://opendata.dwd.de/weather/nwp/icon-d2/grib"

RUN = None  # Will be auto-detected

VARIABLES = [
    # Basis & Gevoel (Dagelijkse weer)
    "t_2m",           # Temperature 2m
    "td_2m",          # Dew point 2m
    "tmax_2m",        # Max temperature 2m
    "tmin_2m",        # Min temperature 2m
    "u_10m",          # U wind 10m
    "v_10m",          # V wind 10m
    "vmax_10m",       # Max wind gust 10m
    "pmsl",           # Pressure MSL (sea level)
    "ps",             # Surface pressure
    "ww",             # Weather code
    "vis",            # Visibility
    
    # Neerslag & Buienradar
    "tot_prec",       # Total precipitation
    "rain_gsp",       # Large-scale rain
    "snow_gsp",       # Large-scale snow
    "rain_con",       # Convective rain (showers)
    "snow_con",       # Convective snow
    "prg_gsp",        # Graupel intensity
    "prr_gsp",        # Rain intensity
    "prs_gsp",        # Snow intensity
    "dbz_cmax",       # Composite radar reflectivity (BUIENRADAR!)
    "dbz_850",        # Radar reflectivity 850 hPa
    "grau_gsp",       # Graupel/hail at surface
    "runoff_g",       # Ground runoff
    "runoff_s",       # Surface runoff
    
    # Bewolking & Wolkenopbouw
    "clct",           # Total cloud cover
    "clct_mod",       # Modified total cloud
    "clcl",           # Low cloud
    "clcm",           # Mid cloud
    "clch",           # High cloud
    "ceiling",        # Cloud base height
    "cldepth",        # Cloud depth
    "hbas_sc",        # Stratocumulus base
    "htop_sc",        # Stratocumulus top
    "htop_dc",        # Deep convection top
    
    # Onweer & Noodweer
    "cape_ml",        # CAPE mixed layer
    "cin_ml",         # Convective inhibition
    "lpi",            # Lightning potential index
    "lpi_max",        # Max LPI
    "uh_max",         # Max updraft helicity
    "uh_max_low",     # Updraft helicity low level
    "uh_max_med",     # Updraft helicity mid level
    "echotop",        # Echo top height
    
    # Luchtmassa & Vocht
    "relhum",         # Relative humidity (general)
    "relhum_2m",      # Relative humidity 2m
    "qv_s",           # Specific humidity surface
    "tqv",            # Total column water vapor
    "twater",         # Total integrated water
    "tqc",            # Column cloud water
    "tqg",            # Column graupel
    "tqi",            # Column ice
    "tqr",            # Column rain
    "tqs",            # Column snow
    
    # Specialistische extra's
    "hzerocl",        # 0°C isotherm height
    "snowc",          # Snow cover
    "snowlmt",        # Snow limit height
    "t_wml_lk",       # Lake water temp
    "z0",             # Roughness length
]

OUTPUT_DIR = Path("public/data/icon-d2")

# Nederland + stukje België/Duitsland/Noordzee
MIN_LON = 2.5
MAX_LON = 8.5
MIN_LAT = 50.5
MAX_LAT = 54.0


def download(url, destination):
    print(f"Downloading: {url}")

    urllib.request.urlretrieve(url, destination)

    print(f"Saved: {destination}")


def get_directory(url):
    with urllib.request.urlopen(url) as response:
        return response.read().decode("utf-8")


def get_latest_run():
    """
    Detect the latest available ICON-D2 run.
    DWD typically publishes runs at 00, 06, 12, 18 UTC.
    Returns the most recent one.
    """
    now = datetime.now(timezone.utc)
    
    # Try runs from most recent backwards
    for hours_back in range(24):
        test_time = now - timedelta(hours=hours_back)
        run_hour = test_time.hour
        
        # ICON-D2 runs at 00, 06, 12, 18
        if run_hour % 6 == 0:
            run_str = test_time.strftime("%Y%m%d%H")
            run_hh = run_str[-2:]  # Get HH part (00, 06, 12, 18)
            test_url = f"{DWD_BASE}/{run_hh}/t_2m/"
            
            try:
                html = get_directory(test_url)
                # Check if we got valid content
                if "icon-d2" in html:
                    print(f"Latest run found: {run_str}")
                    return run_hh
            except:
                continue
    
    raise RuntimeError("Could not find latest ICON-D2 run")


def find_grib_files(html, variable):
    """
    Find GRIB files for a specific variable.
    """
    # Escape special regex chars in variable name
    var_pattern = variable.replace("_", r"[_-]")
    pattern = (
        r'href="([^"]+regular-lat-lon_single-level_[^"]+'
        + var_pattern +
        r'\.grib2\.bz2)"'
    )

    return re.findall(pattern, html)


def temperature_to_rgba_vectorized(values):
    """
    Vectorized temperature to RGBA (Kelvin -> RGB).
    10-20x faster than pixel-by-pixel approach.
    """
    celsius = values - 273.15
    
    n = len(values)
    colors = np.zeros((n, 4), dtype=np.uint8)
    
    # Color stops for temperature
    stops = [
        (-5, np.array([75, 29, 149])),
        (0, np.array([49, 95, 196])),
        (5, np.array([49, 166, 216])),
        (10, np.array([66, 201, 139])),
        (15, np.array([197, 217, 71])),
        (20, np.array([242, 188, 62])),
        (25, np.array([233, 109, 54])),
        (30, np.array([217, 54, 54])),
    ]
    
    # Interpolate between stops
    for i in range(len(stops) - 1):
        val_a, col_a = stops[i]
        val_b, col_b = stops[i + 1]
        
        mask = (celsius >= val_a) & (celsius <= val_b)
        if np.any(mask):
            fraction = (celsius[mask] - val_a) / (val_b - val_a)
            for c in range(3):
                colors[mask, c] = (col_a[c] + (col_b[c] - col_a[c]) * fraction).astype(np.uint8)
            colors[mask, 3] = 255
    
    # Values below min
    mask_low = celsius < stops[0][0]
    colors[mask_low, :3] = stops[0][1]
    colors[mask, 3] = 255
    
    # Values above max
    mask_high = celsius > stops[-1][0]
    colors[mask_high, :3] = stops[-1][1]
    colors[mask, 3] = 255
    
    return colors


def humidity_to_rgba_vectorized(values):
    """Vectorized humidity to RGBA (0-100%)."""
    humidity = np.clip(values, 0, 100)
    colors = np.zeros((len(values), 4), dtype=np.uint8)
    colors[:, 0] = (255 * (1 - humidity / 100)).astype(np.uint8)
    colors[:, 1] = (150 + 105 * (humidity / 100)).astype(np.uint8)
    colors[:, 2] = (196 - 50 * (humidity / 100)).astype(np.uint8)
    colors[:, 3] = 255
    return colors


def precipitation_to_rgba_vectorized(values):
    """Vectorized precipitation to RGBA (mm)."""
    n = len(values)
    colors = np.zeros((n, 4), dtype=np.uint8)
    
    stops = [
        (0, np.array([49, 95, 196])),      # No rain
        (1, np.array([49, 166, 216])),     # Light
        (5, np.array([66, 201, 139])),     # Moderate
        (10, np.array([242, 188, 62])),    # Heavy
        (20, np.array([217, 54, 54])),     # Very heavy
    ]
    
    for i in range(len(stops) - 1):
        val_a, col_a = stops[i]
        val_b, col_b = stops[i + 1]
        mask = (values > val_a) & (values <= val_b)
        if np.any(mask):
            fraction = (values[mask] - val_a) / (val_b - val_a)
            for c in range(3):
                colors[mask, c] = (col_a[c] + (col_b[c] - col_a[c]) * fraction).astype(np.uint8)
            colors[mask, 3] = 255
    
    mask_zero = values <= stops[0][0]
    colors[mask_zero, :3] = stops[0][1]
    colors[mask_zero, 3] = 0
    
    mask_high = values >= stops[-1][0]
    colors[mask_high, :3] = stops[-1][1]
    colors[mask, 3] = 255
    
    return colors


def wind_to_rgba_vectorized(values):
    """Vectorized wind speed to RGBA (m/s)."""
    n = len(values)
    colors = np.zeros((n, 4), dtype=np.uint8)
    
    stops = [
        (0, np.array([49, 95, 196])),      # Calm
        (5, np.array([66, 201, 139])),     # Light
        (10, np.array([242, 188, 62])),    # Moderate
        (15, np.array([217, 54, 54])),     # Strong
        (25, np.array([149, 29, 75])),     # Very strong
    ]
    
    for i in range(len(stops) - 1):
        val_a, col_a = stops[i]
        val_b, col_b = stops[i + 1]
        mask = (values > val_a) & (values <= val_b)
        if np.any(mask):
            fraction = (values[mask] - val_a) / (val_b - val_a)
            for c in range(3):
                colors[mask, c] = (col_a[c] + (col_b[c] - col_a[c]) * fraction).astype(np.uint8)
            colors[mask, 3] = 255
    
    mask_calm = values <= stops[0][0]
    colors[mask_calm, :3] = stops[0][1]
    colors[mask_calm, 3] = 50
    
    mask_strong = values >= stops[-1][0]
    colors[mask_strong, :3] = stops[-1][1]
    colors[mask_strong, 3] = 255
    
    return colors


def cloud_to_rgba_vectorized(values):
    """Vectorized cloud cover to RGBA (0-100%)."""
    cloud_pct = np.clip(values, 0, 100)
    colors = np.zeros((len(values), 4), dtype=np.uint8)
    opacity = (255 * cloud_pct / 100).astype(np.uint8)
    gray = ((200 * cloud_pct / 100) + 55).astype(np.uint8)
    
    colors[:, 0] = gray
    colors[:, 1] = gray
    colors[:, 2] = gray
    colors[:, 3] = opacity
    
    return colors


def windgust_to_rgba_vectorized(values):
    """Vectorized wind gust to RGBA (0-40 m/s). Red scale for severe winds."""
    stops = [
        (0, np.array([31, 178, 227])),      # Light: cyan
        (5, np.array([49, 201, 84])),       # Moderate: green
        (10, np.array([255, 193, 7])),      # Strong: yellow
        (15, np.array([255, 112, 67])),     # Very strong: orange
        (25, np.array([229, 57, 53])),      # Severe: red
        (40, np.array([136, 14, 79])),      # Extreme: dark red
    ]
    
    colors = np.zeros((len(values), 4), dtype=np.uint8)
    
    for i in range(len(stops) - 1):
        val_a, col_a = stops[i]
        val_b, col_b = stops[i + 1]
        mask = (values > val_a) & (values <= val_b)
        if np.any(mask):
            fraction = (values[mask] - val_a) / (val_b - val_a)
            for c in range(3):
                colors[mask, c] = (col_a[c] + (col_b[c] - col_a[c]) * fraction).astype(np.uint8)
            colors[mask, 3] = 255
    
    mask_calm = values <= stops[0][0]
    colors[mask_calm, :3] = stops[0][1]
    colors[mask_calm, 3] = 50
    
    mask_strong = values >= stops[-1][0]
    colors[mask_strong, :3] = stops[-1][1]
    colors[mask_strong, 3] = 255
    
    return colors


def hail_to_rgba_vectorized(values):
    """Vectorized hail probability to RGBA (0-100%). Purple scale."""
    hail_pct = np.clip(values, 0, 100)
    colors = np.zeros((len(values), 4), dtype=np.uint8)
    
    # 0% = semi-transparent, higher = fully opaque purple
    opacity = (50 + (205 * hail_pct / 100)).astype(np.uint8)
    
    # Interpolate from blue to purple to red
    r = (hail_pct * 2).astype(np.uint8)
    g = np.zeros_like(hail_pct, dtype=np.uint8)
    b = np.clip(255 - hail_pct, 0, 255).astype(np.uint8)
    
    colors[:, 0] = r
    colors[:, 1] = g
    colors[:, 2] = b
    colors[:, 3] = opacity
    
    return colors


def snow_to_rgba_vectorized(values):
    """Vectorized snow depth/fall to RGBA (0-30 cm). Blue-white scale."""
    snow_cm = np.clip(values, 0, 30)
    colors = np.zeros((len(values), 4), dtype=np.uint8)
    
    # 0 = semi-transparent, higher = fully opaque white
    opacity = (50 + (205 * snow_cm / 30)).astype(np.uint8)
    
    # Blue (0cm) to white (30cm)
    r = np.clip((snow_cm / 30 * 100).astype(np.uint8), 100, 255)
    g = np.clip((snow_cm / 30 * 120).astype(np.uint8), 150, 255)
    b = np.clip(200 + (snow_cm / 30 * 55).astype(np.uint8), 200, 255)
    
    colors[:, 0] = r
    colors[:, 1] = g
    colors[:, 2] = b
    colors[:, 3] = opacity
    
    return colors


def pressure_to_rgba_vectorized(values):
    """Vectorized surface pressure to RGBA (970-1050 hPa). Green=high pressure, Red=low."""
    p = np.clip(values, 970, 1050)
    colors = np.zeros((len(values), 4), dtype=np.uint8)
    
    # Normalize 970-1050 to 0-1
    norm = (p - 970) / 80
    
    # Green (high, 1050) to Red (low, 970)
    r = (norm * 255).astype(np.uint8)
    g = ((1 - norm) * 100 + 150).astype(np.uint8)
    b = ((1 - norm) * 100 + 50).astype(np.uint8)
    
    colors[:, 0] = r
    colors[:, 1] = g
    colors[:, 2] = b
    colors[:, 3] = 255
    
    return colors


def cape_to_rgba_vectorized(values):
    """Vectorized CAPE to RGBA (0-4000 J/kg). Red scale for instability."""
    stops = [
        (0, np.array([74, 144, 226])),      # Stable: blue
        (500, np.array([76, 175, 80])),     # Low: green
        (1000, np.array([255, 193, 7])),    # Moderate: yellow
        (2000, np.array([255, 87, 34])),    # High: orange
        (3500, np.array([229, 57, 53])),    # Very high: red
        (4000, np.array([98, 0, 0])),       # Extreme: dark red
    ]
    
    colors = np.zeros((len(values), 4), dtype=np.uint8)
    
    for i in range(len(stops) - 1):
        val_a, col_a = stops[i]
        val_b, col_b = stops[i + 1]
        mask = (values > val_a) & (values <= val_b)
        if np.any(mask):
            fraction = (values[mask] - val_a) / (val_b - val_a)
            for c in range(3):
                colors[mask, c] = (col_a[c] + (col_b[c] - col_a[c]) * fraction).astype(np.uint8)
            colors[mask, 3] = 255
    
    mask_stable = values <= stops[0][0]
    colors[mask_stable, :3] = stops[0][1]
    colors[mask_stable, 3] = 120
    
    mask_extreme = values >= stops[-1][0]
    colors[mask_extreme, :3] = stops[-1][1]
    colors[mask_extreme, 3] = 255
    
    return colors


def lifted_index_to_rgba_vectorized(values):
    """Vectorized lifted index to RGBA. Red = unstable (low/negative values), Blue = stable."""
    li = np.clip(values, -10, 10)
    colors = np.zeros((len(values), 4), dtype=np.uint8)
    
    # Normalize -10 to 10, so 0 = red (unstable), 10 = blue (stable)
    norm = (li + 10) / 20
    
    # Red (unstable, negative) to Blue (stable, positive)
    r = ((1 - norm) * 255).astype(np.uint8)
    g = 0
    b = (norm * 255).astype(np.uint8)
    
    colors[:, 0] = r
    colors[:, 1] = g
    colors[:, 2] = b
    colors[:, 3] = 255
    
    return colors


def radar_reflectivity_to_rgba_vectorized(values):
    """Vectorized DBZ (radar reflectivity) to RGBA (-10 to 60 dBZ). Classic radar colors."""
    dbz = np.clip(values, -10, 60)
    colors = np.zeros((len(values), 4), dtype=np.uint8)
    
    stops = [
        (-10, np.array([0, 0, 0])),         # No echo: black/transparent
        (5, np.array([102, 204, 255])),     # Weak: light blue
        (15, np.array([0, 255, 0])),        # Light: green
        (25, np.array([255, 255, 0])),      # Moderate: yellow
        (35, np.array([255, 165, 0])),      # Strong: orange
        (45, np.array([255, 0, 0])),        # Very strong: red
        (60, np.array([139, 0, 139])),      # Extreme: magenta
    ]
    
    for i in range(len(stops) - 1):
        val_a, col_a = stops[i]
        val_b, col_b = stops[i + 1]
        mask = (dbz > val_a) & (dbz <= val_b)
        if np.any(mask):
            fraction = (dbz[mask] - val_a) / (val_b - val_a)
            for c in range(3):
                colors[mask, c] = (col_a[c] + (col_b[c] - col_a[c]) * fraction).astype(np.uint8)
            colors[mask, 3] = 255
    
    mask_none = dbz <= stops[0][0]
    colors[mask_none, 3] = 0
    
    mask_extreme = dbz >= stops[-1][0]
    colors[mask_extreme, :3] = stops[-1][1]
    colors[mask_extreme, 3] = 255
    
    return colors


def lpi_to_rgba_vectorized(values):
    """Vectorized Lightning Potential Index (0-150). Yellow->Red scale for lightning risk."""
    lpi = np.clip(values, 0, 150)
    colors = np.zeros((len(values), 4), dtype=np.uint8)
    
    # 0 = yellow, 75 = orange, 150 = red
    r = np.clip(150 + (lpi * 0.7), 0, 255).astype(np.uint8)
    g = np.clip(200 - (lpi * 1.5), 0, 255).astype(np.uint8)
    b = np.clip(50 - (lpi * 0.3), 0, 255).astype(np.uint8)
    
    colors[:, 0] = r
    colors[:, 1] = g
    colors[:, 2] = b
    colors[:, 3] = 255
    
    return colors


def updraft_helicity_to_rgba_vectorized(values):
    """Vectorized UH (0-300 m²/s²). Red scale for rotation/supercells."""
    uh = np.clip(values, 0, 300)
    colors = np.zeros((len(values), 4), dtype=np.uint8)
    
    # 0 = blue, 100 = green, 200 = orange, 300 = red
    stops = [
        (0, np.array([50, 100, 255])),      # Weak: blue
        (75, np.array([100, 200, 100])),    # Light: green
        (150, np.array([255, 165, 0])),     # Moderate: orange
        (250, np.array([255, 0, 0])),       # Strong: red
        (300, np.array([139, 0, 0])),       # Extreme: dark red
    ]
    
    for i in range(len(stops) - 1):
        val_a, col_a = stops[i]
        val_b, col_b = stops[i + 1]
        mask = (uh > val_a) & (uh <= val_b)
        if np.any(mask):
            fraction = (uh[mask] - val_a) / (val_b - val_a)
            for c in range(3):
                colors[mask, c] = (col_a[c] + (col_b[c] - col_a[c]) * fraction).astype(np.uint8)
            colors[mask, 3] = 255
    
    mask_extreme = uh >= stops[-1][0]
    colors[mask_extreme, :3] = stops[-1][1]
    colors[mask_extreme, 3] = 255
    
    return colors


def visibility_to_rgba_vectorized(values):
    """Vectorized visibility (0-20 km). Blue for poor, green for good visibility."""
    vis_km = np.clip(values / 1000, 0, 20)  # Convert m to km
    colors = np.zeros((len(values), 4), dtype=np.uint8)
    
    # 0 km = red (fog), 10 km = yellow, 20 km = green
    r = np.clip(255 - (vis_km * 12), 0, 255).astype(np.uint8)
    g = np.clip(100 + (vis_km * 7), 0, 255).astype(np.uint8)
    b = np.clip(100 - (vis_km * 5), 0, 255).astype(np.uint8)
    
    colors[:, 0] = r
    colors[:, 1] = g
    colors[:, 2] = b
    colors[:, 3] = 255
    
    return colors


def height_to_rgba_vectorized(values):
    """Vectorized height/altitude (0-5000m). Purple to blue scale."""
    h = np.clip(values, 0, 5000)
    colors = np.zeros((len(values), 4), dtype=np.uint8)
    
    # 0m = purple, 2500m = blue, 5000m = cyan
    norm = h / 5000
    r = np.clip(200 * (1 - norm), 0, 255).astype(np.uint8)
    g = np.clip(100 + norm * 155, 0, 255).astype(np.uint8)
    b = 255
    
    colors[:, 0] = r
    colors[:, 1] = g
    colors[:, 2] = b
    colors[:, 3] = 255
    
    return colors


def column_water_to_rgba_vectorized(values):
    """Vectorized column water (0-80 kg/m²). Blue for dry, green for wet."""
    water = np.clip(values, 0, 80)
    colors = np.zeros((len(values), 4), dtype=np.uint8)
    
    # 0 = blue (dry), 40 = green, 80 = brown (very wet)
    r = np.clip(water * 2, 0, 255).astype(np.uint8)
    g = np.clip(100 + water * 1.5, 0, 255).astype(np.uint8)
    b = np.clip(255 - water * 2, 0, 255).astype(np.uint8)
    
    colors[:, 0] = r
    colors[:, 1] = g
    colors[:, 2] = b
    colors[:, 3] = 255
    
    return colors


def weather_code_to_rgba_vectorized(values):
    """Vectorized weather code (ww). Show actual weather condition colors."""
    ww = values.astype(int)
    colors = np.zeros((len(values), 4), dtype=np.uint8)
    
    # Simplified WMO weather codes
    # 0 = clear, 1-2 = cloudy, 3-4 = fog, 5-8 = drizzle, 9-22 = rain, 23-29 = snow/sleet, 30-39 = thunderstorm
    for i, code in enumerate(ww):
        if code == 0:
            colors[i] = [255, 255, 200, 100]  # Clear: light yellow
        elif code <= 2:
            colors[i] = [200, 200, 200, 150]  # Cloudy: gray
        elif code <= 4:
            colors[i] = [180, 180, 150, 200]  # Fog: brown-gray
        elif code <= 8:
            colors[i] = [100, 150, 200, 220]  # Drizzle: light blue
        elif code <= 22:
            colors[i] = [50, 100, 200, 255]   # Rain: blue
        elif code <= 29:
            colors[i] = [200, 200, 255, 255]  # Snow: white-blue
        else:
            colors[i] = [255, 0, 200, 255]    # Thunderstorm: magenta
    
    return colors


def get_value_to_rgba(variable):
    """
    Return the appropriate vectorized color mapping function for a variable.
    """
    mappings = {
        # Basis & Gevoel
        "t_2m": temperature_to_rgba_vectorized,
        "td_2m": temperature_to_rgba_vectorized,
        "tmax_2m": temperature_to_rgba_vectorized,
        "tmin_2m": temperature_to_rgba_vectorized,
        "u_10m": wind_to_rgba_vectorized,
        "v_10m": wind_to_rgba_vectorized,
        "vmax_10m": windgust_to_rgba_vectorized,
        "pmsl": pressure_to_rgba_vectorized,
        "ps": pressure_to_rgba_vectorized,
        "ww": weather_code_to_rgba_vectorized,
        "vis": visibility_to_rgba_vectorized,
        
        # Neerslag & Buienradar
        "tot_prec": precipitation_to_rgba_vectorized,
        "rain_gsp": precipitation_to_rgba_vectorized,
        "snow_gsp": precipitation_to_rgba_vectorized,
        "rain_con": precipitation_to_rgba_vectorized,
        "snow_con": precipitation_to_rgba_vectorized,
        "prg_gsp": precipitation_to_rgba_vectorized,
        "prr_gsp": precipitation_to_rgba_vectorized,
        "prs_gsp": precipitation_to_rgba_vectorized,
        "dbz_cmax": radar_reflectivity_to_rgba_vectorized,
        "dbz_850": radar_reflectivity_to_rgba_vectorized,
        "grau_gsp": precipitation_to_rgba_vectorized,
        "runoff_g": precipitation_to_rgba_vectorized,
        "runoff_s": precipitation_to_rgba_vectorized,
        
        # Bewolking & Wolkenopbouw
        "clct": cloud_to_rgba_vectorized,
        "clct_mod": cloud_to_rgba_vectorized,
        "clcl": cloud_to_rgba_vectorized,
        "clcm": cloud_to_rgba_vectorized,
        "clch": cloud_to_rgba_vectorized,
        "ceiling": height_to_rgba_vectorized,
        "cldepth": height_to_rgba_vectorized,
        "hbas_sc": height_to_rgba_vectorized,
        "htop_sc": height_to_rgba_vectorized,
        "htop_dc": height_to_rgba_vectorized,
        
        # Onweer & Noodweer
        "cape_ml": cape_to_rgba_vectorized,
        "cin_ml": height_to_rgba_vectorized,
        "lpi": lpi_to_rgba_vectorized,
        "lpi_max": lpi_to_rgba_vectorized,
        "uh_max": updraft_helicity_to_rgba_vectorized,
        "uh_max_low": updraft_helicity_to_rgba_vectorized,
        "uh_max_med": updraft_helicity_to_rgba_vectorized,
        "echotop": height_to_rgba_vectorized,
        
        # Luchtmassa & Vocht
        "relhum": humidity_to_rgba_vectorized,
        "relhum_2m": humidity_to_rgba_vectorized,
        "qv_s": column_water_to_rgba_vectorized,
        "tqv": column_water_to_rgba_vectorized,
        "twater": column_water_to_rgba_vectorized,
        "tqc": column_water_to_rgba_vectorized,
        "tqg": column_water_to_rgba_vectorized,
        "tqi": column_water_to_rgba_vectorized,
        "tqr": column_water_to_rgba_vectorized,
        "tqs": column_water_to_rgba_vectorized,
        
        # Specialistische extra's
        "hzerocl": height_to_rgba_vectorized,
        "snowc": humidity_to_rgba_vectorized,
        "snowlmt": height_to_rgba_vectorized,
        "t_wml_lk": temperature_to_rgba_vectorized,
        "z0": height_to_rgba_vectorized,
    }
    
    return mappings.get(variable, temperature_to_rgba_vectorized)


def read_grib_with_cfgrib(path):
    """
    Parse GRIB2 file using cfgrib library with NumPy vectorization.
    
    Returns numpy arrays (lats, lons, values) for points in our region.
    """
    
    try:
        # Open GRIB file with cfgrib and xarray
        import xarray as xr
        ds = xr.open_dataset(str(path), engine='cfgrib')
        
        # Find the data variable (first non-coordinate variable)
        data_var = None
        for var_name in ds.data_vars:
            if var_name not in ['latitude', 'longitude']:
                data_var = var_name
                break
        
        if data_var is None:
            raise ValueError("Could not find data variable in GRIB file")
            
        print(f"Using variable: {data_var}")
        
        # Get lat/lon coordinates and data
        lats = ds.coords['latitude'].values
        lons = ds.coords['longitude'].values
        data = ds[data_var]
        
        # Handle multi-dimensional data (e.g., time dimension)
        # If there are extra dimensions, take the first timestep
        if len(data.shape) > 2:
            print(f"Data has {len(data.shape)} dimensions, shape: {data.shape}")
            # Take first time step if data has time dimension
            values = data.values[0]
        else:
            values = data.values
        
        print(f"Grid shape: {values.shape}, lat shape: {lats.shape}, lon shape: {lons.shape}")
        
        # Ensure lat/lon grids match data shape
        if lats.shape[0] != values.shape[0] or lons.shape[0] != values.shape[1]:
            print(f"Warning: Shape mismatch. Regridding...")
            # Create meshgrid matching the actual data shape
            lon_grid, lat_grid = np.meshgrid(lons, lats)
        else:
            lon_grid, lat_grid = np.meshgrid(lons, lats)
        
        # Flatten all arrays
        lat_flat = lat_grid.flatten()
        lon_flat = lon_grid.flatten()
        val_flat = values.flatten()
        
        # Ensure all have same length
        min_len = min(len(lat_flat), len(lon_flat), len(val_flat))
        lat_flat = lat_flat[:min_len]
        lon_flat = lon_flat[:min_len]
        val_flat = val_flat[:min_len]
        
        # Vectorized filtering: create mask for region + valid values
        mask = (
            (lat_flat >= MIN_LAT) & (lat_flat <= MAX_LAT) &
            (lon_flat >= MIN_LON) & (lon_flat <= MAX_LON) &
            ~np.isnan(val_flat)
        )
        
        lats_filtered = lat_flat[mask]
        lons_filtered = lon_flat[mask]
        vals_filtered = val_flat[mask]
        
        print(f"Found {len(lats_filtered)} points in region")
        ds.close()
        
        return lats_filtered, lons_filtered, vals_filtered
        
    except Exception as e:
        print(f"Error reading GRIB with cfgrib: {e}")
        raise


def read_grib_grid_with_cfgrib(path):
    """
    Parse GRIB2 file als een regulier 2D-grid (i.p.v. platgeslagen puntenlijst).
    Nodig voor contour-generatie: marching squares werkt op een grid, niet op
    losse (lat, lon, waarde) punten.

    Returns:
        lats_axis: 1D array, oplopend, alleen de rijen binnen de regio
        lons_axis: 1D array, oplopend, alleen de kolommen binnen de regio
        values_grid: 2D array, shape (len(lats_axis), len(lons_axis))
    """
    import xarray as xr

    ds = xr.open_dataset(str(path), engine="cfgrib")

    data_var = None
    for var_name in ds.data_vars:
        if var_name not in ["latitude", "longitude"]:
            data_var = var_name
            break

    if data_var is None:
        raise ValueError("Could not find data variable in GRIB file")

    lats_axis = ds.coords["latitude"].values
    lons_axis = ds.coords["longitude"].values
    data = ds[data_var]

    values_grid = data.values[0] if len(data.shape) > 2 else data.values

    # ICON-D2 lat-as loopt vaak aflopend (noord -> zuid); contourpy en Leaflet
    # verwachten oplopende assen, dus indien nodig omdraaien.
    if lats_axis[0] > lats_axis[-1]:
        lats_axis = lats_axis[::-1]
        values_grid = values_grid[::-1, :]

    # Clip naar de regio via index-slicing (behoudt de 2D grid-structuur,
    # in tegenstelling tot de boolean mask die read_grib_with_cfgrib gebruikt).
    lat_mask = (lats_axis >= MIN_LAT) & (lats_axis <= MAX_LAT)
    lon_mask = (lons_axis >= MIN_LON) & (lons_axis <= MAX_LON)

    lats_axis = lats_axis[lat_mask]
    lons_axis = lons_axis[lon_mask]
    values_grid = values_grid[np.ix_(lat_mask, lon_mask)]

    ds.close()

    return lats_axis, lons_axis, values_grid


def generate_contour_geojson(lats_axis, lons_axis, values_grid, output_file, interval, unit_divisor=1):
    """
    Genereert isolijnen (bv. isobaren) als GeoJSON LineStrings uit een 2D-grid,
    via marching squares (contourpy - dezelfde engine als matplotlib.contour()).

    Elke lijn krijgt een "level"-property zodat de frontend kan stylen
    (bv. elke 4e isobaar dikker, of een waarde-label tonen).
    """
    values = values_grid / unit_divisor

    vmin = np.floor(np.nanmin(values) / interval) * interval
    vmax = np.ceil(np.nanmax(values) / interval) * interval
    levels = np.arange(vmin, vmax + interval, interval)

    cg = contourpy.contour_generator(x=lons_axis, y=lats_axis, z=values)

    features = []
    for level in levels:
        lines = cg.lines(float(level))
        for line in lines:
            if len(line) < 2:
                continue
            coords = [[round(float(x), 4), round(float(y), 4)] for x, y in line]
            features.append(
                {
                    "type": "Feature",
                    "properties": {"level": round(float(level), 1)},
                    "geometry": {"type": "LineString", "coordinates": coords},
                }
            )

    geojson = {"type": "FeatureCollection", "features": features}

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(geojson, f)

    return len(features)


def create_overlay(lats, lons, values, output_file, value_to_rgba):
    """
    Creates a transparent PNG with vectorized NumPy operations.
    Much faster than pixel-by-pixel approach.
    """

    # Regular ICON-D2 grid is roughly 2 km.
    # Create high-res 1200x1000 visual raster.
    width = 1200
    height = 1000

    # Vectorized: convert geographic coords to pixel coords
    x = ((lons - MIN_LON) / (MAX_LON - MIN_LON) * (width - 1)).astype(int)
    y = ((1 - (lats - MIN_LAT) / (MAX_LAT - MIN_LAT)) * (height - 1)).astype(int)
    
    # Filter to valid pixel ranges
    valid_mask = (x >= 0) & (x < width) & (y >= 0) & (y < height)
    x_valid = x[valid_mask]
    y_valid = y[valid_mask]
    values_valid = values[valid_mask]
    
    # Get RGBA colors for all values at once (vectorized)
    colors = value_to_rgba(values_valid)
    
    # Create RGBA image array and fill with computed colors
    img_array = np.zeros((height, width, 4), dtype=np.uint8)
    img_array[y_valid, x_valid] = colors
    
    # Convert numpy array to PIL Image
    image = Image.fromarray(img_array, mode='RGBA')

    # Enlarge for better display (2400x2000).
    enlarged = image.resize(
        (width * 2, height * 2),
        Image.Resampling.BILINEAR,
    )

    enlarged.save(
        output_file,
        optimize=True,
    )


def main():

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    # Auto-detect latest run if not set
    global RUN
    if RUN is None:
        RUN = get_latest_run()
    
    print(f"Processing ICON-D2 run: {RUN}")

    all_variables_data = {}

    # Process each variable
    for variable in VARIABLES:
        print(f"\n=== Processing {variable} ===")
        
        directory_url = (
            f"{DWD_BASE}/{RUN}/{variable}/"
        )

        try:
            html = get_directory(
                directory_url
            )
        except Exception as e:
            print(f"Could not fetch directory for {variable}: {e}")
            continue

        files = find_grib_files(html, variable)

        if not files:
            print(f"No files found for {variable}")
            continue

        # Sort by filename / forecast time.
        files.sort()

        # Limit to 42 frames (42 hour forecast - maximum ICON-D2 provides)
        files = files[:42]

        # Determine the model run time from the filename
        if files:
            match = re.search(r"_(\d{10})_", files[0])
            if match:
                run_str = match.group(1)  # YYYYMMDDHH
                run_datetime = datetime.strptime(run_str, "%Y%m%d%H").replace(tzinfo=timezone.utc)
            else:
                run_datetime = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            run_datetime = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        # Create variable-specific directory
        var_dir = OUTPUT_DIR / variable
        var_dir.mkdir(parents=True, exist_ok=True)

        frames = []
        is_contour_variable = variable in CONTOUR_VARIABLES
        value_to_rgba = None if is_contour_variable else get_value_to_rgba(variable)

        for index, filename in enumerate(files):

            local_bz2 = (
                var_dir
                / f"source-{index:03d}.grib2.bz2"
            )

            local_grib = (
                var_dir
                / f"source-{index:03d}.grib2"
            )

            url = (
                f"{directory_url}{filename}"
            )

            download(
                url,
                local_bz2,
            )

            print("Decompressing...")

            with bz2.open(
                local_bz2,
                "rb",
            ) as source:

                with open(
                    local_grib,
                    "wb",
                ) as destination:

                    destination.write(
                        source.read()
                    )

            print(f"Reading GRIB... ({variable})")

            if is_contour_variable:
                contour_settings = CONTOUR_VARIABLES[variable]
                output_geojson = var_dir / f"{index:03d}.geojson"

                lats_axis, lons_axis, values_grid = read_grib_grid_with_cfgrib(
                    local_grib
                )

                n_lines = generate_contour_geojson(
                    lats_axis,
                    lons_axis,
                    values_grid,
                    output_geojson,
                    interval=contour_settings["interval"],
                    unit_divisor=contour_settings["unit_divisor"],
                )

                print(f"Generated {n_lines} contour lines")

                frame_entry = {
                    "geojson": f"/data/icon-d2/{variable}/{index:03d}.geojson",
                    "renderType": "contour",
                }
            else:
                output_png = var_dir / f"{index:03d}.png"

                lats, lons, values = read_grib_with_cfgrib(
                    local_grib
                )

                create_overlay(
                    lats,
                    lons,
                    values,
                    output_png,
                    value_to_rgba,
                )

                frame_entry = {
                    "image": f"/data/icon-d2/{variable}/{index:03d}.png",
                    "renderType": "raster",
                }

            # Forecast hour is encoded in filename
            match = re.search(
                r"_(\d{3})_",
                filename,
            )

            if match:
                forecast_hour = int(
                    match.group(1)
                )
            else:
                forecast_hour = index

            # Calculate valid time: run time + forecast hours
            valid_time = run_datetime + timedelta(hours=forecast_hour)

            frame_entry.update(
                {
                    "forecastHour": forecast_hour,
                    "validTime": valid_time.isoformat(),
                }
            )

            frames.append(frame_entry)

            local_bz2.unlink(
                missing_ok=True
            )

            local_grib.unlink(
                missing_ok=True
            )

        all_variables_data[variable] = {
            "frames": frames,
            "renderType": "contour" if is_contour_variable else "raster",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
        }

    # Create main manifest with all variables
    manifest = {
        "model": "ICON-D2",
        "provider": "DWD",
        "run": RUN,
        "resolution": "2.2 km",
        "bounds": [
            [MIN_LAT, MIN_LON],
            [MAX_LAT, MAX_LON],
        ],
        "variables": all_variables_data,
        "generatedAt": datetime.now(
            timezone.utc
        ).isoformat(),
    }

    with open(
        OUTPUT_DIR / "manifest.json",
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            manifest,
            file,
            indent=2,
        )

    print("\nManifest generated.")
    print(f"Total variables processed: {len(all_variables_data)}")


if __name__ == "__main__":
    main()
