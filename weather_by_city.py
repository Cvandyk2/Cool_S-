import folium
import requests
import pandas as pd
from folium.plugins import MarkerCluster
import time
from metar import Metar

# =====================
# CONFIGURABLE SETTINGS
# =====================
FILTER_REGION_NAME = ["north_america"]  # e.g. ["europe"] or [] for worldwide
MAP_FILENAME = "Weather/weather_map.html"
AUTO_REFRESH_SECONDS = 120
MAP_ZOOM = 5
MAX_RUNTIME_HOURS = 12  # Failsafe to stop after N hours of continuous updates

# Premade region bounding boxes
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
}

# Global airport list (ICAO, lat, lon)
GLOBAL_AIRPORTS = [
    # North America
    {"name": "KJFK", "city": "New York", "lat": 40.6413, "lon": -73.7781},
    {"name": "KLAX", "city": "Los Angeles", "lat": 33.9416, "lon": -118.4085},
    {"name": "KORD", "city": "Chicago", "lat": 41.9742, "lon": -87.9073},
    {"name": "KATL", "city": "Atlanta", "lat": 33.6407, "lon": -84.4277},
    {"name": "KDFW", "city": "Dallas/Fort Worth", "lat": 32.8998, "lon": -97.0403},
    {"name": "KDEN", "city": "Denver", "lat": 39.8561, "lon": -104.6737},
    {"name": "KSFO", "city": "San Francisco", "lat": 37.6213, "lon": -122.3790},
    {"name": "KSEA", "city": "Seattle", "lat": 47.4502, "lon": -122.3088},
    {"name": "KMIA", "city": "Miami", "lat": 25.7959, "lon": -80.2870},
    {"name": "KBOS", "city": "Boston", "lat": 42.3656, "lon": -71.0096},
    {"name": "KPHX", "city": "Phoenix", "lat": 33.4342, "lon": -112.0116},
    {"name": "KIAH", "city": "Houston", "lat": 29.9902, "lon": -95.3368},
    {"name": "KLAS", "city": "Las Vegas", "lat": 36.0840, "lon": -115.1537},
    {"name": "KMCO", "city": "Orlando", "lat": 28.4312, "lon": -81.3081},
    {"name": "KEWR", "city": "Newark", "lat": 40.6895, "lon": -74.1745},
    {"name": "KMSP", "city": "Minneapolis", "lat": 44.8831, "lon": -93.2223},
    {"name": "KDTW", "city": "Detroit", "lat": 42.2162, "lon": -83.3554},
    {"name": "KPHL", "city": "Philadelphia", "lat": 39.8744, "lon": -75.2424},
    {"name": "KSLC", "city": "Salt Lake City", "lat": 40.7899, "lon": -111.9791},
    {"name": "KBWI", "city": "Baltimore", "lat": 39.1754, "lon": -76.6684},
    {"name": "KAUS", "city": "Austin", "lat": 30.1944, "lon": -97.6699},
    {"name": "KBIL", "city": "Billings", "lat": 45.8077, "lon": -108.5429},
    {"name": "KBNA", "city": "Nashville", "lat": 36.1260, "lon": -86.6812},
    {"name": "KBOI", "city": "Boise", "lat": 43.5644, "lon": -116.2228},
    {"name": "KSBN", "city": "South Bend", "lat": 41.7086, "lon": -86.3173},
    {"name": "KLNK", "city": "Lincoln", "lat": 40.8510, "lon": -96.7592},
    {"name": "KGPI", "city": "Kalispell", "lat": 48.3105, "lon": -114.2560},
    # Europe
    {"name": "EGLL", "city": "London", "lat": 51.4700, "lon": -0.4543},
    {"name": "LFPG", "city": "Paris", "lat": 49.0097, "lon": 2.5479},
    {"name": "EDDF", "city": "Frankfurt", "lat": 50.0379, "lon": 8.5622},
    {"name": "EHAM", "city": "Amsterdam", "lat": 52.3086, "lon": 4.7639},
    {"name": "LEMD", "city": "Madrid", "lat": 40.4936, "lon": -3.5668},
    {"name": "LIRF", "city": "Rome", "lat": 41.8003, "lon": 12.2389},
    {"name": "UUEE", "city": "Moscow", "lat": 55.9726, "lon": 37.4146},
    {"name": "LSZH", "city": "Zurich", "lat": 47.4647, "lon": 8.5492},
    {"name": "LFMN", "city": "Nice", "lat": 43.6653, "lon": 7.2150},
    {"name": "EBBR", "city": "Brussels", "lat": 50.9014, "lon": 4.4844},
    # Asia
    {"name": "RJTT", "city": "Tokyo", "lat": 35.5523, "lon": 139.7798},
    {"name": "ZBAA", "city": "Beijing", "lat": 40.0801, "lon": 116.5846},
    {"name": "VHHH", "city": "Hong Kong", "lat": 22.3080, "lon": 113.9185},
    {"name": "OMDB", "city": "Dubai", "lat": 25.2532, "lon": 55.3657},
    {"name": "VIDP", "city": "Delhi", "lat": 28.5562, "lon": 77.1000},
    {"name": "WSSS", "city": "Singapore", "lat": 1.3644, "lon": 103.9915},
    {"name": "RKSI", "city": "Seoul", "lat": 37.4602, "lon": 126.4407},
    {"name": "VTBS", "city": "Bangkok", "lat": 13.6900, "lon": 100.7501},
    {"name": "YSSY", "city": "Sydney", "lat": -33.9399, "lon": 151.1753},
    {"name": "NZAA", "city": "Auckland", "lat": -37.0082, "lon": 174.7850},
    # Africa
    {"name": "FAOR", "city": "Johannesburg", "lat": -26.1337, "lon": 28.2420},
    {"name": "DNMM", "city": "Lagos", "lat": 6.5774, "lon": 3.3212},
    {"name": "HECA", "city": "Cairo", "lat": 30.1114, "lon": 31.4000},
    {"name": "GMMN", "city": "Casablanca", "lat": 33.3675, "lon": -7.5897},
    {"name": "HKJK", "city": "Nairobi", "lat": -1.3192, "lon": 36.9278},
    # South America
    {"name": "SBGR", "city": "São Paulo", "lat": -23.4356, "lon": -46.4731},
    {"name": "SBBR", "city": "Brasília", "lat": -15.8711, "lon": -47.9186},
    {"name": "SCEL", "city": "Santiago", "lat": -33.3930, "lon": -70.7858},
    {"name": "SUMU", "city": "Montevideo", "lat": -34.8384, "lon": -56.0308},
    {"name": "SKBO", "city": "Bogotá", "lat": 4.7016, "lon": -74.1469},
    # Middle East
    {"name": "LLBG", "city": "Tel Aviv", "lat": 32.0114, "lon": 34.8867},
    {"name": "OIIE", "city": "Tehran", "lat": 35.4161, "lon": 51.1522},
    {"name": "OTHH", "city": "Doha", "lat": 25.2731, "lon": 51.6081},
    {"name": "OEJN", "city": "Jeddah", "lat": 21.4817, "lon": 39.5443},
]

def c_to_f(c):
    try:
        return round((c * 9/5) + 32, 1)
    except:
        return "N/A"

def kt_to_mph(kt):
    try:
        return round(kt * 1.15078, 1)
    except:
        return "N/A"

def km_to_mi(km):
    try:
        return round(km * 0.621371, 1)
    except:
        return "N/A"

def fetch_metar_noaa(airports):
    records = []
    for airport in airports:
        url = f"https://tgftp.nws.noaa.gov/data/observations/metar/stations/{airport['name']}.TXT"
        try:
            resp = requests.get(url)
            print(f"\n{airport['name']} NOAA response:")
            print(resp.text)
            lines = resp.text.splitlines()
            raw = lines[-1] if len(lines) > 1 else "N/A"
            # Use python-metar for robust parsing
            try:
                if raw != "N/A":
                    report = Metar.Metar(raw)
                    temp_c = report.temp.value() if report.temp else None
                    temp_f = c_to_f(temp_c) if temp_c is not None else "N/A"
                    wind_kt = report.wind_speed.value() if report.wind_speed else None
                    wind_mph = kt_to_mph(wind_kt) if wind_kt is not None else "N/A"
                    wind_dir = report.wind_dir.value() if report.wind_dir else "N/A"
                    wind = f"{wind_mph} mph @ {wind_dir}°" if wind_mph != "N/A" and wind_dir != "N/A" else "N/A"
                    vis_km = report.vis.value() if report.vis else None
                    vis_mi = km_to_mi(vis_km) if vis_km is not None else "N/A"
                    wx = ", ".join([w for w in report.weather]) if report.weather else "N/A"
                    precip = None
                    if hasattr(report, 'precip') and report.precip:
                        precip = ", ".join([str(p) for p in report.precip])
                    else:
                        precip = "N/A"
                else:
                    temp_f = wind = vis_mi = wx = precip = "N/A"
            except Exception as e:
                temp_f = wind = vis_mi = wx = precip = "N/A"
            records.append({
                "name": airport["name"],
                "city": airport["city"],
                "lat": airport["lat"],
                "lon": airport["lon"],
                "raw": raw,
                "temperature": temp_f,
                "wind": wind,
                "visibility": vis_mi,
                "wx": wx,
                "precip": precip,
            })
        except Exception as e:
            records.append({
                "name": airport["name"],
                "city": airport["city"],
                "lat": airport["lat"],
                "lon": airport["lon"],
                "raw": "N/A",
                "temperature": "N/A",
                "wind": "N/A",
                "visibility": "N/A",
                "wx": "N/A",
                "precip": "N/A",
            })
        time.sleep(0.2)  # Faster, but still cautious for rate limits
    return pd.DataFrame(records)

def make_map(df, filename=MAP_FILENAME, auto_refresh_seconds=AUTO_REFRESH_SECONDS, zoom_start=MAP_ZOOM, open_browser=False):
    center_lat = df["lat"].mean()
    center_lon = df["lon"].mean()
    m = folium.Map(location=[center_lat, center_lon], zoom_start=zoom_start)
    marker_cluster = MarkerCluster().add_to(m)

    for _, row in df.iterrows():
        # Check for precipitation in weather codes or precip field
        precip_keywords = ["RA", "SN", "DZ", "SG", "PL", "GR", "GS", "IC"]
        wx_precip = any(code in str(row.get('wx', "")) for code in precip_keywords)
        has_precip = (row.get('precip') and row['precip'] != "N/A" and row['precip'].strip() != "") or wx_precip
        if has_precip:
            icon_name = "cloud-showers-heavy"  # stormy cloud (FontAwesome)
            icon_color = "darkpurple"
        else:
            icon_name = "cloud"
            icon_color = "blue"
        popup_text = f"""
        <div style='font-family: Arial, sans-serif; font-size: 13px; min-width: 200px;'>
            <table style='width:100%; border-collapse:collapse;'>
                <tr><th colspan='2' style='background:#4FC3F7; color:#fff; padding:4px; border-radius:4px 4px 0 0;'>{row['name']} - {row['city']}</th></tr>
                <tr><td><b>Temperature</b></td><td>{row['temperature']} °F</td></tr>
                <tr><td><b>Wind</b></td><td>{row['wind']}</td></tr>
                <tr><td><b>Visibility</b></td><td>{row['visibility']} mi</td></tr>
                <tr><td><b>Weather</b></td><td>{row['wx']}</td></tr>
                <tr><td><b>Precipitation</b></td><td>{row['precip']}</td></tr>
                <tr><td colspan='2'><small>Raw METAR: {row['raw']}</small></td></tr>
            </table>
        </div>
        """
        folium.Marker(
            location=[row["lat"], row["lon"]],
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
    if open_browser:
        import os, webbrowser
        full_path = os.path.abspath(filename)
        webbrowser.open(f"file://{full_path}")
    return filename

def get_airports_by_region(region_names):
    airports = []
    if not region_names:
        region_names = ["worldwide"]
    for region in region_names:
        bbox = PREMADE_REGIONS.get(region, PREMADE_REGIONS["worldwide"])
        min_lat, max_lat, min_lon, max_lon = bbox
        region_airports = [a for a in GLOBAL_AIRPORTS if min_lat <= a["lat"] <= max_lat and min_lon <= a["lon"] <= max_lon]
        airports.extend(region_airports)
    return airports

if __name__ == "__main__":
    import time as _time
    opened = False
    start = _time.monotonic()
    max_seconds = MAX_RUNTIME_HOURS * 3600 if MAX_RUNTIME_HOURS and MAX_RUNTIME_HOURS > 0 else None
    try:
        while True:
            print(f"🌎 Fetching NOAA METAR weather data for: {FILTER_REGION_NAME}")
            airports = get_airports_by_region(FILTER_REGION_NAME)
            df = fetch_metar_noaa(airports)
            print(df.head())
            make_map(df, open_browser=not opened)
            opened = True

            if max_seconds is not None and (_time.monotonic() - start) >= max_seconds:
                print(f"Max runtime reached ({MAX_RUNTIME_HOURS}h). Exiting.")
                break

            _time.sleep(AUTO_REFRESH_SECONDS)
    except KeyboardInterrupt:
        print("Stopped by user.")
