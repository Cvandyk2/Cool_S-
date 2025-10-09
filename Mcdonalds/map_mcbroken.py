
import csv

# =====================
# Adjustable Variables
# =====================
REFRESH_RATE = 300  # seconds; set to 0 for no refresh, e.g. 300 for 5 min
STATUS_FILTER = None  # 'working' or 'broken' or None
CITY = None  # e.g. 'Chicago' or None

import json
import folium
from folium.plugins import MarkerCluster
import os
import datetime
import time

# Example marker format (replace with actual data if available)
# [
#   {"lat": 40.7128, "lng": -74.0060, "status": "working", "address": "New York, NY"},
#   {"lat": 34.0522, "lng": -118.2437, "status": "broken", "address": "Los Angeles, CA"}
# ]

def geojson_to_csv(json_path, csv_path):
    with open(json_path, "r") as f:
        geojson = json.load(f)
    header = ["lat", "lng", "status", "country", "state", "city", "street", "last_checked"]
    with open(csv_path, "w", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(header)
        for feature in geojson.get("features", []):
            coords = feature["geometry"]["coordinates"]
            props = feature["properties"]
            lat = float(coords[1])
            lng = float(coords[0])
            status = "working" if not props.get("is_broken") else "broken"
            country = props.get("country", "")
            state = props.get("state", "")
            city = props.get("city", "")
            street = props.get("street", "")
            last_checked = props.get("last_checked", "")
            writer.writerow([lat, lng, status, country, state, city, street, last_checked])

def load_markers_from_csv(csv_path):
    markers = []
    with open(csv_path, "r") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            markers.append(row)
    return markers

def fetch_mcbroken_markers(json_path):
    import requests
    url = "https://mcbroken.com/markers.json"
    response = requests.get(url)
    response.raise_for_status()
    data = response.json()
    with open(json_path, "w") as f:
        json.dump(data, f)
    return data

def create_map(markers, output_path, status_filter=None, city=None):
    # Center map on North America, zoomed out to show the world
    map_center = [40, -100]
    zoom = 3
    if city:
        city_marker = next((m for m in markers if city.lower() in m.get("city", "").lower()), None)
        if city_marker:
            map_center = [float(city_marker["lat"]), float(city_marker["lng"])]
            zoom = 10
    m = folium.Map(location=map_center, zoom_start=zoom)
    # Filter markers by status if requested
    if status_filter:
        markers = [m for m in markers if m.get("status") == status_filter]
    marker_cluster = MarkerCluster().add_to(m)
    ice_cream_icon = '🍦'
    for marker in markers:
        lat = float(marker["lat"])
        lng = float(marker["lng"])
        status = marker["status"]
        color = "green" if status == "working" else "red"
        # Build popup with all available data
        popup_html = "<b>Store Details:</b><br>"
        for key, value in marker.items():
            popup_html += f"<b>{key}:</b> {value}<br>"
        folium.Marker(
            location=[lat, lng],
            popup=popup_html,
            icon=folium.Icon(color=color, icon="info-sign"),
        ).add_to(marker_cluster)
    legend_html = '''
     <div style="position: fixed; 
     bottom: 50px; left: 50px; width: 260px; height: 120px; 
     background-color: white; z-index:9999; font-size:16px; border:2px solid grey; border-radius:8px; padding: 10px;">
     <b>Ice Cream Machine Status</b><br>
     <span style="color:green;font-size:22px;">✅</span> Working<br>
     <span style="color:red;font-size:22px;">❌</span> Broken<br>
     <br><b>Options:</b><br>
     <span style="font-size:14px;">Filter by status, search city, see last updated.</span>
     </div>
     '''
    m.get_root().html.add_child(folium.Element(legend_html))
    last_updated = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    updated_html = f'''<div style="position: fixed; bottom: 10px; left: 50px; background: white; z-index:9999; font-size:13px; border:1px solid grey; border-radius:6px; padding: 5px;">Last updated: {last_updated}</div>'''
    m.get_root().html.add_child(folium.Element(updated_html))
    m.save(output_path)
    print(f"Map saved to {output_path}")
    import webbrowser
    webbrowser.open(f"file://{os.path.abspath(output_path)}")

if __name__ == "__main__":
    json_path = os.path.join(os.path.dirname(__file__), "mcbroken_markers.json")
    csv_path = os.path.join(os.path.dirname(__file__), "mcbroken_markers.csv")
    output_path = os.path.join(os.path.dirname(__file__), "mcbroken_map.html")
    while True:
        # Convert GeoJSON to CSV for efficient storage
        geojson_to_csv(json_path, csv_path)
        markers = load_markers_from_csv(csv_path)
        create_map(markers, output_path, status_filter=STATUS_FILTER, city=CITY)
        if REFRESH_RATE <= 0:
            break
        print(f"Waiting {REFRESH_RATE} seconds before refreshing...")
        time.sleep(REFRESH_RATE)
