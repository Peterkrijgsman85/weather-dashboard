import bz2
import json
import os
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from PIL import Image


DWD_BASE = "https://opendata.dwd.de/weather/nwp/icon-d2/grib"

RUN = None  # Will be auto-detected

VARIABLES = [
    "t_2m",       # Temperature 2m
    "td_2m",      # Dew point 2m
    "rh_2m",      # Relative humidity 2m
    "u_10m",      # U wind 10m
    "v_10m",      # V wind 10m
    "tot_prec",   # Total precipitation
    "clct",       # Total cloud cover
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
            test_url = f"{DWD_BASE}/{run_str:[-2:]}/t_2m/"
            
            try:
                html = get_directory(test_url)
                # Check if we got valid content
                if "icon-d2" in html:
                    print(f"Latest run found: {run_str}")
                    return run_str[-2:]  # Return just the HH part (00, 06, 12, 18)
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
            colors[mask, 3] = 210
    
    # Values below min
    mask_low = celsius < stops[0][0]
    colors[mask_low, :3] = stops[0][1]
    colors[mask_low, 3] = 210
    
    # Values above max
    mask_high = celsius > stops[-1][0]
    colors[mask_high, :3] = stops[-1][1]
    colors[mask_high, 3] = 210
    
    return colors


def humidity_to_rgba_vectorized(values):
    """Vectorized humidity to RGBA (0-100%)."""
    humidity = np.clip(values, 0, 100)
    colors = np.zeros((len(values), 4), dtype=np.uint8)
    colors[:, 0] = (255 * (1 - humidity / 100)).astype(np.uint8)
    colors[:, 1] = (150 + 105 * (humidity / 100)).astype(np.uint8)
    colors[:, 2] = (196 - 50 * (humidity / 100)).astype(np.uint8)
    colors[:, 3] = 210
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
            colors[mask, 3] = 210
    
    mask_zero = values <= stops[0][0]
    colors[mask_zero, :3] = stops[0][1]
    colors[mask_zero, 3] = 0
    
    mask_high = values >= stops[-1][0]
    colors[mask_high, :3] = stops[-1][1]
    colors[mask_high, 3] = 210
    
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
            colors[mask, 3] = 210
    
    mask_calm = values <= stops[0][0]
    colors[mask_calm, :3] = stops[0][1]
    colors[mask_calm, 3] = 0
    
    mask_strong = values >= stops[-1][0]
    colors[mask_strong, :3] = stops[-1][1]
    colors[mask_strong, 3] = 210
    
    return colors


def cloud_to_rgba_vectorized(values):
    """Vectorized cloud cover to RGBA (0-100%)."""
    cloud_pct = np.clip(values, 0, 100)
    colors = np.zeros((len(values), 4), dtype=np.uint8)
    opacity = (210 * cloud_pct / 100).astype(np.uint8)
    gray = ((200 * cloud_pct / 100) + 55).astype(np.uint8)
    
    colors[:, 0] = gray
    colors[:, 1] = gray
    colors[:, 2] = gray
    colors[:, 3] = opacity
    
    return colors


def get_value_to_rgba(variable):
    """
    Return the appropriate vectorized color mapping function for a variable.
    """
    mappings = {
        "t_2m": temperature_to_rgba_vectorized,
        "td_2m": temperature_to_rgba_vectorized,
        "rh_2m": humidity_to_rgba_vectorized,
        "u_10m": wind_to_rgba_vectorized,
        "v_10m": wind_to_rgba_vectorized,
        "tot_prec": precipitation_to_rgba_vectorized,
        "clct": cloud_to_rgba_vectorized,
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
        values = ds[data_var].values
        
        # Vectorized: create meshgrid and flatten
        lon_grid, lat_grid = np.meshgrid(lons, lats)
        lat_flat = lat_grid.flatten()
        lon_flat = lon_grid.flatten()
        val_flat = values.flatten()
        
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


def create_overlay(lats, lons, values, output_file, value_to_rgba):
    """
    Creates a transparent PNG with vectorized NumPy operations.
    Much faster than pixel-by-pixel approach.
    """

    # Regular ICON-D2 grid is roughly 2 km.
    # For MVP we create a 600x500 visual raster.
    width = 600
    height = 500

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

    # Slight enlargement of individual grid cells.
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

        # Limit to 24 frames (24 hour forecast)
        files = files[:24]

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
        value_to_rgba = get_value_to_rgba(variable)

        for index, filename in enumerate(files):

            local_bz2 = (
                var_dir
                / f"source-{index:03d}.grib2.bz2"
            )

            local_grib = (
                var_dir
                / f"source-{index:03d}.grib2"
            )

            output_png = (
                var_dir
                / f"{index:03d}.png"
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

            frames.append(
                {
                    "forecastHour": forecast_hour,
                    "validTime": valid_time.isoformat(),
                    "image": f"/data/icon-d2/{variable}/{index:03d}.png",
                }
            )

            local_bz2.unlink(
                missing_ok=True
            )

            local_grib.unlink(
                missing_ok=True
            )

        all_variables_data[variable] = {
            "frames": frames,
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
