import bz2
import json
import os
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import cfgrib
import numpy as np
from PIL import Image


DWD_BASE = "https://opendata.dwd.de/weather/nwp/icon-d2/grib"

RUN = "00"

VARIABLE = "t_2m"

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


def find_grib_files(html):
    pattern = (
        r'href="([^"]+regular-lat-lon_single-level_[^"]+'
        r'_t_2m\.grib2\.bz2)"'
    )

    return re.findall(pattern, html)


def temperature_to_rgba(value):
    """
    Temperature in Kelvin.

    Simple first-pass colour scale.
    """

    if value is None:
        return (0, 0, 0, 0)

    celsius = value - 273.15

    stops = [
        (-5, (75, 29, 149)),
        (0, (49, 95, 196)),
        (5, (49, 166, 216)),
        (10, (66, 201, 139)),
        (15, (197, 217, 71)),
        (20, (242, 188, 62)),
        (25, (233, 109, 54)),
        (30, (217, 54, 54)),
    ]

    if celsius <= stops[0][0]:
        return (*stops[0][1], 210)

    if celsius >= stops[-1][0]:
        return (*stops[-1][1], 210)

    for index in range(len(stops) - 1):
        value_a, color_a = stops[index]
        value_b, color_b = stops[index + 1]

        if value_a <= celsius <= value_b:
            fraction = (
                (celsius - value_a)
                / (value_b - value_a)
            )

            color = tuple(
                round(
                    color_a[channel]
                    + (
                        color_b[channel]
                        - color_a[channel]
                    )
                    * fraction
                )
                for channel in range(3)
            )

            return (*color, 210)

    return (0, 0, 0, 0)


def read_grib_with_cfgrib(path):
    """
    Parse GRIB2 file using cfgrib library.
    
    Returns list of (lat, lon, value) tuples for points in our region.
    """
    
    try:
        # Open GRIB file with cfgrib
        ds = cfgrib.open_file(str(path))
        
        # Get temperature data (t, t2m or similar - depends on GRIB structure)
        # Common names: 't', 't2m', 'temperature', etc.
        temp_var = None
        for var_name in ds.data_vars:
            if 't' in var_name.lower() and '2m' in var_name.lower():
                temp_var = var_name
                break
        
        if temp_var is None:
            # Fallback: just take first variable
            temp_var = list(ds.data_vars)[0]
            print(f"Note: using variable '{temp_var}' (not t2m)")
        
        # Get lat/lon coordinates and temperature data
        lats = ds.coords['latitude'].values
        lons = ds.coords['longitude'].values
        temps = ds[temp_var].values
        
        # Create meshgrid of coordinates
        lon_grid, lat_grid = np.meshgrid(lons, lats)
        
        points = []
        
        # Iterate through all grid points
        for i in range(len(lats)):
            for j in range(len(lons)):
                lat = lat_grid[i, j]
                lon = lon_grid[i, j]
                value = temps[i, j]
                
                # Filter to our region
                if (MIN_LAT <= lat <= MAX_LAT and 
                    MIN_LON <= lon <= MAX_LON):
                    # Skip NaN values
                    if not np.isnan(value):
                        points.append((lat, lon, float(value)))
        
        print(f"Found {len(points)} points in region")
        return points
        
    except Exception as e:
        print(f"Error reading GRIB with cfgrib: {e}")
        raise


def create_overlay(points, output_file):
    """
    First MVP renderer.

    Creates a transparent PNG covering our geographic
    bounding box.

    This is deliberately simple. Later we can replace
    this with proper raster tiles/WebGL data.
    """

    # Regular ICON-D2 grid is roughly 2 km.
    # For MVP we create a 600x500 visual raster.
    width = 600
    height = 500

    image = Image.new(
        "RGBA",
        (width, height),
        (0, 0, 0, 0),
    )

    pixels = image.load()

    for lat, lon, value in points:

        x = int(
            (
                (lon - MIN_LON)
                / (MAX_LON - MIN_LON)
            )
            * (width - 1)
        )

        y = int(
            (
                1
                - (
                    (lat - MIN_LAT)
                    / (MAX_LAT - MIN_LAT)
                )
            )
            * (height - 1)
        )

        if (
            0 <= x < width
            and 0 <= y < height
        ):
            pixels[x, y] = temperature_to_rgba(
                value
            )

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

    directory_url = (
        f"{DWD_BASE}/{RUN}/{VARIABLE}/"
    )

    html = get_directory(
        directory_url
    )

    files = find_grib_files(html)

    if not files:
        raise RuntimeError(
            "Geen regular-lat-lon ICON-D2 bestanden gevonden."
        )

    # Sort by filename / forecast time.
    files.sort()

    # Limit first MVP to 24 frames.
    files = files[:24]

    frames = []

    for index, filename in enumerate(files):

        local_bz2 = (
            OUTPUT_DIR
            / f"source-{index:03d}.grib2.bz2"
        )

        local_grib = (
            OUTPUT_DIR
            / f"source-{index:03d}.grib2"
        )

        output_png = (
            OUTPUT_DIR
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

        print("Reading GRIB...")

        points = read_grib_with_cfgrib(
            local_grib
        )

        print(
            f"Points in NL area: {len(points)}"
        )

        create_overlay(
            points,
            output_png,
        )

        # Forecast hour is encoded in filename:
        #
        # ..._000_2d_t_2m.grib2.bz2
        #
        match = re.search(
            r"_(\d{3})_2d_t_2m\.grib2",
            filename,
        )

        if match:
            forecast_hour = int(
                match.group(1)
            )
        else:
            forecast_hour = index

        frames.append(
            {
                "forecastHour": forecast_hour,
                "image": f"/data/icon-d2/{index:03d}.png",
            }
        )

        local_bz2.unlink(
            missing_ok=True
        )

        local_grib.unlink(
            missing_ok=True
        )

    manifest = {
        "model": "ICON-D2",
        "provider": "DWD",
        "run": RUN,
        "variable": VARIABLE,
        "resolution": "2.2 km",
        "bounds": [
            [MIN_LAT, MIN_LON],
            [MAX_LAT, MAX_LON],
        ],
        "frames": frames,
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

    print("Manifest generated.")


if __name__ == "__main__":
    main()
