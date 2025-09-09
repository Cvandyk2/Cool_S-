# Planes.py
import time
import folium
import pandas as pd
from opensky_api import OpenSkyApi
from folium.plugins import MarkerCluster


# Optional: add USERNAME, PASSWORD for higher limits
USERNAME = None
PASSWORD = None

# ===== Credit ====
# https://github.com/openskynetwork/opensky-api/blob/master/python/test_opensky_api.py
# =================

# ==== info ====
#       category: 0 = No information at all, 1 = No ADS-B Emitter Category Information,
#      2 = Light (< 15500 lbs), 3 = Small (15500 to 75000 lbs), 4 = Large (75000 to 300000 lbs),
#      5 = High Vortex Large (aircraft such as B-757), 6 = Heavy (> 300000 lbs),
#      7 = High Performance (> 5g acceleration and 400 kts), 8 = Rotorcraft, 9 = Glider / sailplane,
#      10 = Lighter-than-air, 11 = Parachutist / Skydiver, 12 = Ultralight / hang-glider / paraglider,
#      13 = Reserved, 14 = Unmanned Aerial Vehicle, 15 = Space / Trans-atmospheric vehicle,
#      16 = Surface Vehicle – Emergency Vehicle, 17 = Surface Vehicle – Service Vehicle,
#      18 = Point Obstacle (includes tethered balloons), 19 = Cluster Obstacle, 20 = Line Obstacle.
# =====================

# =====================
# CONFIGURABLE SETTINGS
# =====================
FILTER_REGION_NAME = ["north_america"]  # e.g. ['europe'] or [] for worldwide
MAP_FILENAME = "Planes/planes_map.html"
AUTO_REFRESH_SECONDS = 120
MAP_ZOOM = 5
UNITS = "us"  # Change to "metric" for metric units or keep as "us" for the right ones

# Premade region options
PREMADE_REGIONS = {
    "worldwide": (-90.0, 90.0, -180.0, 180.0),
    "north_america": (15.0, 72.0, -170.0, -50.0),
    "south_america": (-60.0, 15.0, -90.0, -30.0),
    "europe": (35.0, 72.0, -25.0, 70.0),
    "asia": (5.0, 80.0, 45.0, 180.0),
    "africa": (-35.0, 37.0, -20.0, 55.0),
    "oceania": (-50.0, 10.0, 110.0, 180.0),
    "antarctica": (-90.0, -60.0, -180.0, 180.0),
    "middle_east": (12.0, 40.0, 35.0, 60.0),
    "atlantic_ocean": (-60.0, 72.0, -85.0, 20.0),
    "pacific_ocean_1": (-60.0, 72.0, 110.0, 180.0),
    "pacific_ocean_2": (-60.0, 72.0, -180.0, -85.0),
    "indian_ocean": (-50.0, 30.0, 20.0, 110.0),
    "arctic_ocean": (66.0, 90.0, -180.0, 180.0),
    "southern_ocean": (-90.0, -60.0, -180.0, 180.0)
}

def fetch_live_planes(region_names=None):
    """Fetch live aircraft states from OpenSky API (optionally bounding box)."""
    api = OpenSkyApi(USERNAME, PASSWORD) if USERNAME and PASSWORD else OpenSkyApi()
    dfs = []
    # If no region specified, use worldwide
    if not region_names:
        region_names = ["worldwide"]
    for region in region_names:
        bbox = PREMADE_REGIONS.get(region, PREMADE_REGIONS["worldwide"])
        states = api.get_states(bbox=bbox)
        records = []
        if states and states.states:
            for s in states.states:
                records.append({
                    "icao24": s.icao24,
                    "callsign": s.callsign,
                    "origin_country": s.origin_country,
                    "longitude": s.longitude,
                    "latitude": s.latitude,
                    "baro_altitude": s.baro_altitude,
                    "geo_altitude": getattr(s, 'geo_altitude', None),
                    "velocity": s.velocity,
                    "vertical_rate": getattr(s, 'vertical_rate', None),
                    "heading": getattr(s, 'true_track', None),
                    "on_ground": getattr(s, 'on_ground', None),
                    "spi": getattr(s, 'spi', None),
                    "position_source": getattr(s, 'position_source', None),
                    "category": getattr(s, 'category', None),
                    "time_position": getattr(s, 'time_position', None),
                    "last_contact": getattr(s, 'last_contact', None),
                    "squawk": s.squawk
                })
        dfs.append(pd.DataFrame(records))
    if dfs:
        return pd.concat(dfs, ignore_index=True)
    return pd.DataFrame()


def make_map(df, filename=MAP_FILENAME, auto_refresh_seconds=AUTO_REFRESH_SECONDS, zoom_start=MAP_ZOOM, units=UNITS):
    """Generate an interactive map with plane markers and auto-refresh."""
    if df.empty:
        print("No planes found.")
        return None

    # Center map around mean lat/lon
    center_lat = df["latitude"].mean()
    center_lon = df["longitude"].mean()

    m = folium.Map(location=[center_lat, center_lon], zoom_start=zoom_start)
    marker_cluster = MarkerCluster().add_to(m)

    for _, row in df.iterrows():
        velocity_mps = row['velocity']
        baro_altitude_m = row['baro_altitude']
        geo_altitude_m = row.get('geo_altitude', None)
        vertical_rate_mps = row.get('vertical_rate', None)

        if units == "us":
            velocity = velocity_mps * 2.23694 if velocity_mps is not None else 'N/A'
            velocity_str = f"{velocity:.1f} mph" if velocity_mps is not None else 'N/A'
            baro_altitude = baro_altitude_m * 3.28084 if baro_altitude_m is not None else 'N/A'
            baro_altitude_str = f"{baro_altitude:.0f} ft" if baro_altitude_m is not None else 'N/A'
            geo_altitude = geo_altitude_m * 3.28084 if geo_altitude_m is not None else 'N/A'
            geo_altitude_str = f"{geo_altitude:.0f} ft" if geo_altitude_m is not None else 'N/A'
            vertical_rate = vertical_rate_mps * 196.850 if vertical_rate_mps is not None else 'N/A'
            vertical_rate_str = f"{vertical_rate:.0f} ft/min" if vertical_rate_mps is not None else 'N/A'
        else:
            velocity = velocity_mps if velocity_mps is not None else 'N/A'
            velocity_str = f"{velocity:.1f} m/s" if velocity_mps is not None else 'N/A'
            baro_altitude = baro_altitude_m if baro_altitude_m is not None else 'N/A'
            baro_altitude_str = f"{baro_altitude:.0f} m" if baro_altitude_m is not None else 'N/A'
            geo_altitude = geo_altitude_m if geo_altitude_m is not None else 'N/A'
            geo_altitude_str = f"{geo_altitude:.0f} m" if geo_altitude_m is not None else 'N/A'
            vertical_rate = vertical_rate_mps if vertical_rate_mps is not None else 'N/A'
            vertical_rate_str = f"{vertical_rate:.0f} m/min" if vertical_rate_mps is not None else 'N/A'

        squawk = row.get('squawk', 'N/A')
        squawk_explanation = ""
        if squawk and squawk != 'N/A':
            squawk_explanations = {
                "7500": "Hijacking (emergency)",
                "7600": "Radio failure (emergency)",
                "7700": "General emergency",
            }
            if str(squawk) in squawk_explanations:
                squawk_explanation = f"<span style='color:#d32f2f;'><b>({squawk_explanations[str(squawk)]})</b></span>"
        popup_text = f"""
        <div style='font-family: Arial, sans-serif; font-size: 13px; min-width: 220px;'>
            <table style='width:100%; border-collapse:collapse;'>
                <tr><th colspan='2' style='background:#4FC3F7; color:#fff; padding:4px; border-radius:4px 4px 0 0;'>✈️ {row['callsign'] or 'Unknown'} ({row['origin_country']})</th></tr>
                <tr><td><b>Altitude</b></td><td>{baro_altitude_str}</td></tr>
                <tr><td><b>Geo Altitude</b></td><td>{geo_altitude_str}</td></tr>
                <tr><td><b>Velocity</b></td><td>{velocity_str}</td></tr>
                <tr><td><b>Vertical Rate</b></td><td>{vertical_rate_str}</td></tr>
                <tr><td><b>Heading</b></td><td>{row['heading']}°</td></tr>
                <tr><td><b>On Ground</b></td><td>{row.get('on_ground', 'N/A')}</td></tr>
                <tr><td><b>SPI</b></td><td>{row.get('spi', 'N/A')}</td></tr>
                <tr><td><b>Position Source</b></td><td>{row.get('position_source', 'N/A')}</td></tr>
                <tr><td><b>Category</b></td><td>{row.get('category', 'N/A')}</td></tr>
                <tr><td><b>Squawk</b></td><td>{squawk} {squawk_explanation}</td></tr>
                <tr><td><b>Time Position</b></td><td>{row.get('time_position', 'N/A')}</td></tr>
                <tr><td><b>Last Contact</b></td><td>{row.get('last_contact', 'N/A')}</td></tr>
            </table>
        </div>
        """

        # Emergency squawk codes (verified):
        emergency_squawks = {"7500", "7600", "7700"}
        is_emergency = str(squawk) in emergency_squawks
        icon_color = "red" if is_emergency else ("green" if row.get('on_ground', False) else "#4FC3F7")

        # Icon selection based on category
        # OpenSky category codes: 1=light, 2=small, 3=large, 4=high perf, 5=heavy, 6=rotorcraft, 7=glider, 8=balloon, 9=unknown
        category = row.get('category', None)
        if category == 4:
            icon_name = "fighter-jet"
        elif category == 6:
            icon_name = "helicopter"
        else:
            icon_name = "plane"

        # Use base circle as background for airborne planes
        if not row.get('on_ground', False) and row.get('heading') is not None:
            try:
                heading = float(row.get('heading'))
                plane_style = f"transform: rotate({heading}deg);"
            except (ValueError, TypeError):
                plane_style = ""
            icon_html = f"""
            <div style='position: relative; width: 32px; height: 32px;'>
                <span style='display: block; width: 32px; height: 32px; border-radius: 50%; background: #e0e0e0; position: absolute; top: 0; left: 0;'></span>
                <i class='fa fa-{icon_name}' style='font-size: 20px; color: {icon_color}; position: absolute; top: 6px; left: 6px; {plane_style}'></i>
            </div>
            """
            from folium.features import DivIcon
            icon = DivIcon(html=icon_html, icon_size=(32, 32), icon_anchor=(16, 16), popup_anchor=(0, -16))
            folium.Marker(
                location=[row["latitude"], row["longitude"]],
                popup=popup_text,
                icon=icon
            ).add_to(marker_cluster)
        else:
            folium.Marker(
                location=[row["latitude"], row["longitude"]],
                popup=popup_text,
                icon=folium.Icon(color=icon_color, icon=icon_name, prefix="fa")
            ).add_to(marker_cluster)

    folium.LayerControl().add_to(m)
    m.save(filename)
    # Inject auto-refresh JavaScript
    try:
        with open(filename, "r+") as f:
            html = f.read()
            refresh_script = f"<script>setTimeout(function(){{window.location.reload();}}, {auto_refresh_seconds * 1000});</script>"
            if "window.location.reload" not in html:
                html = html.replace("</head>", refresh_script + "\n</head>")
                f.seek(0)
                f.write(html)
                f.truncate()
    except Exception as e:
        print(f"Failed to inject auto-refresh: {e}")
    print(f"✅ Map saved: {filename}")
    # Open map in browser
    import os, webbrowser
    full_path = os.path.abspath(filename)
    webbrowser.open(f"file://{full_path}")
    return filename

if __name__ == "__main__":
    # Use region filter if specified, otherwise worldwide
    region_names = FILTER_REGION_NAME if FILTER_REGION_NAME else ["worldwide"]
    print(f"📡 Fetching live plane data for: {region_names}")
    df = fetch_live_planes(region_names=region_names)
    print(df.head())

    # Build map in Planes folder with auto-refresh and unit toggle
    make_map(df, units=UNITS)
