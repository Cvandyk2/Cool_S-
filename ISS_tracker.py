
import requests
import folium
import time
from datetime import datetime, timedelta
import webbrowser
import os

# =====================
# CONFIGURABLE SETTINGS
# =====================
TRACKING_HOURS = 6        # Number of hours to track ISS
INTERVAL_SECONDS = 10     # Interval between location checks (seconds)
ROLLING_HOURS = 1         # Number of hours to show on map (rolling window)
MAP_FILENAME = "ISS/iss_location.html"  # Output map filename (now inside ISS folder)
MAP_ZOOM = 5              # Default zoom level for the map (higher = more zoomed in)
AUTO_REFRESH_SECONDS = 20 # Interval (seconds) for browser auto-refresh


def get_iss_location():
    url = "http://api.open-notify.org/iss-now.json"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            position = data['iss_position']
            latitude = float(position['latitude'])
            longitude = float(position['longitude'])
            return latitude, longitude
        else:
            print(f"Failed to retrieve ISS location data: {response.status_code}")
            return None
    except Exception as e:
        print(f"Error fetching ISS location: {e}")
        return None

def main():
    total_duration = TRACKING_HOURS * 60 * 60
    rolling_window = ROLLING_HOURS * 60 * 60
    iterations = total_duration // INTERVAL_SECONDS

    locations = []
    timestamps = []
    print(f"Tracking ISS for {TRACKING_HOURS} hours, updating every {INTERVAL_SECONDS} seconds...")
    start_time = datetime.now()

    browser_opened = False
    for i in range(int(iterations)):
        loc = get_iss_location()
        now = datetime.now()
        if loc:
            locations.append(loc)
            timestamps.append(now)
            print(f"[{now.strftime('%H:%M:%S')}] ISS Location: Lat {loc[0]}, Lon {loc[1]}")
        else:
            print(f"[{now.strftime('%H:%M:%S')}] Skipped due to error.")

        # Filter locations to only last ROLLING_HOURS
        cutoff = datetime.now() - timedelta(seconds=rolling_window)
        filtered = [(lat, lon) for (lat, lon), ts in zip(locations, timestamps) if ts >= cutoff]
        if filtered:
            m = folium.Map(location=filtered[-1], zoom_start=MAP_ZOOM)
            # Add previous locations as gray markers
            for lat, lon in filtered[:-1]:
                folium.CircleMarker(
                    location=[lat, lon],
                    radius=3,
                    color='lightgray',
                    fill=True,
                    fill_color='lightgray',
                    fill_opacity=0.6,
                    popup=f"Lat: {lat}, Lon: {lon}"
                ).add_to(m)
            # Add current location as red marker
            folium.Marker(
                location=filtered[-1],
                popup="Current ISS Location",
                icon=folium.Icon(color="red", icon="rocket", prefix="fa")
            ).add_to(m)
            m.save(MAP_FILENAME)
            # Inject auto-refresh JavaScript
            try:
                with open(MAP_FILENAME, "r+") as f:
                    html = f.read()
                    refresh_script = f"<script>setTimeout(function(){{window.location.reload();}}, {AUTO_REFRESH_SECONDS * 1000});</script>"
                    if "window.location.reload" not in html:
                        html = html.replace("</head>", refresh_script + "\n</head>")
                        f.seek(0)
                        f.write(html)
                        f.truncate()
            except Exception as e:
                print(f"Failed to inject auto-refresh: {e}")
            print(f"Map has been saved as {MAP_FILENAME} with {len(filtered)} locations (last {ROLLING_HOURS} hours).")
            # Open browser on first update using absolute path
            if not browser_opened:
                abs_path = os.path.abspath(MAP_FILENAME)
                webbrowser.open(f"file://{abs_path}")
                browser_opened = True
        else:
            print(f"No locations in the last {ROLLING_HOURS} hours to display.")
        time.sleep(INTERVAL_SECONDS)

    if not locations:
        print("No locations tracked.")

if __name__ == "__main__":
    main()
