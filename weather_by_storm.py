import os
import csv
import folium
import requests
from datetime import datetime, timezone
from math import cos, radians, sqrt, pi
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# =====================
# CONFIGURABLE SETTINGS
# =====================
# Place outputs in repo root /WWeather regardless of current working dir
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, os.pardir))
OUTPUT_DIR = os.path.join(_ROOT, "Weather")
MAP_FILENAME = os.path.join(OUTPUT_DIR, "weather_events_map.html")
MAP_ZOOM = 3
RADAR_OPACITY = 0.7  # 0..1
STORM_RADIUS_KM = 200  # approximate impact radius for tropical cyclones
REFRESH_SECONDS = 120
MAX_RUNTIME_HOURS = 12  # Failsafe to stop after N hours

# Timeouts and concurrency
TIMEOUT = 12
MAX_WORKERS = 6

# Shared session with gentle retries and larger pool
SESSION = requests.Session()
retry_strategy = Retry(
    total=2,
    backoff_factor=0.5,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"],
)
adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=20, pool_maxsize=20)
SESSION.mount("https://", adapter)
SESSION.mount("http://", adapter)
SESSION.headers.update({
    # Include a contact per NWS API guidance to reduce rejected requests
    "User-Agent": "weather-map/1.0 (contact: noreply@example.com)",
    "Accept": "application/geo+json"
})


def fetch_json(url, timeout=TIMEOUT):
    r = SESSION.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()

def fetch_text(url, timeout=TIMEOUT):
    r = SESSION.get(url, timeout=timeout)
    r.raise_for_status()
    return r.text

def to_float(v):
    try:
        return float(v)
    except Exception:
        return None

def parse_lat(v):
    if v is None: return None
    if isinstance(v, (int, float)): return float(v)
    s = str(v).strip().upper()
    if s.endswith("N"): return to_float(s[:-1])
    if s.endswith("S"):
        val = to_float(s[:-1])
        return -val if val is not None else None
    return to_float(s)

def parse_lon(v):
    if v is None: return None
    if isinstance(v, (int, float)): return float(v)
    s = str(v).strip().upper()
    if s.endswith("E"): return to_float(s[:-1])
    if s.endswith("W"):
        val = to_float(s[:-1])
        return -val if val is not None else None
    return to_float(s)

# Region filters removed (always worldwide)

# Generic lon/lat iterator for GeoJSON coords
def iter_lonlat(coords):
    if isinstance(coords, (list, tuple)):
        if len(coords) >= 2 and all(isinstance(x, (int, float)) for x in coords[:2]):
            yield coords
        else:
            for c in coords:
                yield from iter_lonlat(c)

# Compute bounds (min_lat, max_lat, min_lon, max_lon) for a GeoJSON geometry
def geom_bounds(geom):
    if not isinstance(geom, dict): return None
    coords = list(iter_lonlat(geom.get("coordinates", [])))
    if not coords: return None
    lons = [to_float(c[0]) for c in coords if c and to_float(c[0]) is not None]
    lats = [to_float(c[1]) for c in coords if c and to_float(c[1]) is not None]
    if not lons or not lats: return None
    return (min(lats), max(lats), min(lons), max(lons))

# Draw a soft-edged filled area by stacking concentric geodesic circles
def add_faded_circle(layer, lat, lon, radius_m, color, steps=4, max_opacity=0.35):
    """Add concentric circles with decreasing opacity so the edge fades out.
    - steps: number of rings (>=2)
    - max_opacity: opacity at center ring; outer ring approaches 0
    """
    try:
        steps = max(2, int(steps))
        for i in range(steps):
            # Fraction of total radius (smaller first to larger last)
            f = (i + 1) / steps
            # Quadratic falloff for smoother fade to edge
            opacity = max(0.0, max_opacity * (1.0 - (f ** 2)))
            if opacity <= 0.01 and i < steps - 1:
                continue
            folium.Circle(
                location=[lat, lon],
                radius=radius_m * f,
                color=color,
                weight=0,
                fill=True,
                fill_color=color,
                fill_opacity=opacity,
            ).add_to(layer)
    except Exception:
        # Fallback to single circle if anything goes wrong
        folium.Circle(
            location=[lat, lon],
            radius=radius_m,
            color=color,
            weight=0,
            fill=True,
            fill_color=color,
            fill_opacity=max_opacity,
        ).add_to(layer)

def build_map(auto_refresh: bool = False):
    # Map (worldwide view)
    center = [20.0, 0.0]
    m = folium.Map(location=center, zoom_start=MAP_ZOOM, tiles="CartoDB positron")

    # Layers
    layer_radar = folium.FeatureGroup(name="Radar (RainViewer)", overlay=True, control=True, show=True)
    layer_nws = folium.FeatureGroup(name="US Alerts (NWS polygons)", overlay=True, control=True, show=True)
    layer_quakes_area = folium.FeatureGroup(name="Earthquakes (approx. felt area)", overlay=True, control=True, show=True)
    layer_fires_area = folium.FeatureGroup(name="Wildfires (FIRMS, approx. footprint)", overlay=True, control=True, show=True)
    layer_tc_areas = folium.FeatureGroup(name="Tropical Cyclone Areas (NHC approx.)", overlay=True, control=True, show=True)
    layer_volcano = folium.FeatureGroup(name="Volcanoes (EONET)", overlay=True, control=True, show=True)
    layer_spc_lsr = folium.FeatureGroup(name="Severe Reports (SPC 24h)", overlay=True, control=True, show=True)

    counts = {"radar": 0, "nws": 0, "earthquakes": 0, "fires": 0, "storms": 0}
    radar_time_str = None

    # 1) Radar mosaic (RainViewer)
    try:
        maps = fetch_json("https://api.rainviewer.com/public/weather-maps.json")
        host = maps.get("host", "https://tilecache.rainviewer.com")
        frames = (maps.get("radar", {}).get("past", []) or []) + (maps.get("radar", {}).get("nowcast", []) or [])
        frame = frames[-1] if frames else None
        if frame and frame.get("path"):
            tile_url = f"{host}{frame['path']}/256/{{z}}/{{x}}/{{y}}/2/1_1.png?color=3&smooth=1&noclutter=1"
            folium.TileLayer(
                tiles=tile_url,
                name="Radar (RainViewer latest)",
                attr="RainViewer",
                overlay=True,
                control=True,
                opacity=RADAR_OPACITY,
            ).add_to(layer_radar)
            counts["radar"] = 1
            ts = frame.get("time")
            if ts:
                radar_time_str = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except Exception as e:
        print(f"RainViewer error: {e}")
    layer_radar.add_to(m)

    # 2) Volcanoes (from EONET only for volcano category)
    try:
        eonet_url = "https://eonet.gsfc.nasa.gov/api/v3/events?status=open&category=volcanoes&limit=200"
        eonet = fetch_json(eonet_url)
        vcount = 0
        for ev in eonet.get("events", []):
            title = ev.get("title") or "Volcano Activity"
            for geo in ev.get("geometry", []):
                coords = geo.get("coordinates")
                if not coords or len(coords) < 2:
                    continue
                lon, lat = to_float(coords[0]), to_float(coords[1])
                # No region filtering; show worldwide
                # Small faded circle to indicate activity
                add_faded_circle(
                    layer_volcano,
                    lat,
                    lon,
                    radius_m=20000.0,
                    color="#B87333",  # copper-like for volcano
                    steps=4,
                    max_opacity=0.25,
                )
                folium.CircleMarker(
                    location=[lat, lon], radius=3, color="#B87333", fill=True, fill_opacity=0.9,
                    tooltip=title
                ).add_to(layer_volcano)
                vcount += 1
        # counts not tracked separately earlier; optional
    except Exception as e:
        print(f"EONET Volcano error: {e}")
    layer_volcano.add_to(m)

    # 3) NWS US alert polygons (include tsunami-related alerts)
    try:
        # Some query params yield 400 on /alerts/active; try simpler variants first
        nws_data = None
        nws_try_urls = [
            "https://api.weather.gov/alerts/active"
        ]
        for url in nws_try_urls:
            try:
                resp = SESSION.get(url, timeout=20)
                if resp.status_code == 200:
                    nws_data = resp.json()
                    break
                else:
                    # Log brief error body to help debugging
                    body = resp.text[:200].replace("\n", " ")
                    print(f"NWS attempt {url} -> {resp.status_code}: {body}")
            except Exception as e_inner:
                print(f"NWS request failed for {url}: {e_inner}")

        if not nws_data:
            raise Exception("All NWS attempts failed")

        feats = nws_data.get("features", [])
        include_events = {
            "Tornado Warning": "#D50000",            # vivid red
            "Tornado Watch": "#FF6D00",              # orange
            "Severe Thunderstorm Warning": "#FFC107", # amber
            "Severe Thunderstorm Watch": "#FFE082",   # light amber
            "Flash Flood Warning": "#2E7D32",        # deep green
            "Flood Warning": "#66BB6A",              # green
            "Hurricane Warning": "#6A1B9A",          # deep purple
            "Hurricane Watch": "#9C27B0",            # purple
            "Tropical Storm Warning": "#0077BE",     # cyclone blue
            "Winter Storm Warning": "#1565C0",       # strong blue
            "Blizzard Warning": "#90CAF9",           # light blue
            "Red Flag Warning": "#C62828",           # wildfire red
            "Excessive Heat Warning": "#E53935",     # hot red
            "High Wind Warning": "#9E9D24",          # olive
            "Special Marine Warning": "#006D77",     # teal
            "Tsunami Warning": "#004C8C",           # dark ocean blue
            "Tsunami Advisory": "#1976D2",          # medium ocean blue
            "Tsunami Watch": "#64B5F6",             # light ocean blue
        }
        nws_count = 0
        for f in feats:
            props = f.get("properties", {})
            event = props.get("event")
            geom = f.get("geometry")
            if not geom or event not in include_events:
                continue
            bounds = geom_bounds(geom)
            if bounds is None:
                continue
            color = include_events[event]
            def style_fn(_):
                return {"color": color, "fillColor": color, "weight": 2, "fillOpacity": 0.25}
            tooltip = f"{event}: {props.get('headline') or props.get('areaDesc') or ''}"
            folium.GeoJson(f, name=event, style_function=style_fn, tooltip=tooltip).add_to(layer_nws)
            nws_count += 1
        counts["nws"] = nws_count
    except Exception as e:
        print(f"NWS error: {e}")
    layer_nws.add_to(m)

    # 4) Severe Weather Reports (SPC LSR: tornado/wind/hail) — last 24h
    try:
        import datetime as _dt

        def fetch_spc_csv(url):
            try:
                txt = fetch_text(url)
                return list(csv.reader(txt.splitlines()))
            except Exception:
                return []

        # Three feeds for today; also attempt yesterday to cover UTC day changes
        now_utc = _dt.datetime.now(_dt.timezone.utc)
        today = now_utc.strftime("%y%m%d")
        yday = (now_utc - _dt.timedelta(days=1)).strftime("%y%m%d")
        feeds = {
            "tornado": [
                f"https://www.spc.noaa.gov/climo/reports/today_torn.csv",
                f"https://www.spc.noaa.gov/climo/reports/{yday}_rpts_torn.csv",
            ],
            "wind": [
                f"https://www.spc.noaa.gov/climo/reports/today_wind.csv",
                f"https://www.spc.noaa.gov/climo/reports/{yday}_rpts_wind.csv",
            ],
            "hail": [
                f"https://www.spc.noaa.gov/climo/reports/today_hail.csv",
                f"https://www.spc.noaa.gov/climo/reports/{yday}_rpts_hail.csv",
            ],
        }
        colors = {"tornado": "#D50000", "wind": "#FFB300", "hail": "#00ACC1"}
        radii = {"tornado": 8000.0, "wind": 6000.0, "hail": 5000.0}
        lsr_count = 0
        for kind, urls in feeds.items():
            rows = []
            for u in urls:
                rows.extend(fetch_spc_csv(u))
            # First row is header; expected columns include Lat,Lon near the end
            for row in rows[1:]:
                if len(row) < 8:
                    continue
                try:
                    lat = to_float(row[-2])
                    lon = to_float(row[-1])
                except Exception:
                    continue
                if lat is None or lon is None:
                    continue
                # No region filtering; show worldwide
                add_faded_circle(
                    layer_spc_lsr,
                    lat,
                    lon,
                    radius_m=radii[kind],
                    color=colors[kind],
                    steps=3,
                    max_opacity=0.25,
                )
                lsr_count += 1
        counts["spc_lsr"] = lsr_count
    except Exception as e:
        print(f"SPC LSR error: {e}")
    layer_spc_lsr.add_to(m)

    # 5) Earthquakes affected areas (USGS) — circles sized by approximate felt area
    try:
        eq_urls = [
            "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson",
            "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson",
        ]
        n_quakes = 0
        results = []
        try:
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
                futs = {ex.submit(fetch_json, url): url for url in eq_urls}
                for f in as_completed(futs):
                    try:
                        results.append(f.result())
                    except Exception as _e:
                        print(f"USGS fetch error: {_e}")
        except Exception as _e:
            print(f"USGS parallel error: {_e}")

        for eq in results:
            for feature in (eq or {}).get("features", []):
                coords = (feature.get("geometry") or {}).get("coordinates") or []
                if len(coords) < 2:
                    continue
                lat, lon = to_float(coords[1]), to_float(coords[0])
                # No region filtering; show worldwide
                mag = feature.get("properties", {}).get("mag")
                if mag is None:
                    continue
                try:
                    M = float(mag)
                except Exception:
                    continue
                # Approximate felt area A (km^2): log10 A ≈ 1.02 M - 1.83 (Johnston 1996)
                # radius_km = sqrt(A / pi)
                A = 10 ** (1.02 * M - 1.83)
                radius_km = (A / pi) ** 0.5
                # Depth attenuation: reduce area for deeper quakes
                depth_km = to_float(coords[2]) if len(coords) >= 3 else None
                if depth_km is not None:
                    if depth_km > 300:
                        radius_km *= 0.5
                    elif depth_km > 70:
                        radius_km *= 0.7
                # Clamp to reasonable range
                radius_km = max(2.0, min(300.0, radius_km))

                add_faded_circle(
                    layer_quakes_area,
                    lat,
                    lon,
                    radius_km * 1000.0,
                    color="#7B1FA2",
                    steps=5,
                    max_opacity=0.30,
                )
                n_quakes += 1
        counts["earthquakes"] = n_quakes
    except Exception as e:
        print(f"USGS error: {e}")
    layer_quakes_area.add_to(m)

    # 6) Wildfires (NASA FIRMS MODIS 24h) — red circles with real-world footprint
    try:
        fires_url = "https://firms.modaps.eosdis.nasa.gov/data/active_fire/c6.1/csv/MODIS_C6_1_Global_24h.csv"
        text = fetch_text(fires_url)
        reader = csv.DictReader(text.splitlines())
        n = 0
        for row in reader:
            lat = to_float(row.get("latitude"))
            lon = to_float(row.get("longitude"))
            # No region filtering; show worldwide

            # Approximate sensor footprint radius in meters using scan/track in degrees if available
            scan_deg = to_float(row.get("scan"))
            track_deg = to_float(row.get("track"))
            if scan_deg is not None and track_deg is not None and lat is not None:
                # Convert degrees to meters (lon scales with cos(lat))
                width_m = scan_deg * 111320.0 * max(0.0, cos(radians(lat)))
                height_m = track_deg * 111320.0
                # Area-equivalent circle radius
                radius_m = sqrt(max(1.0, width_m * height_m) / pi)
                # Keep radii within a reasonable range
                radius_m = max(150.0, min(2000.0, radius_m))
            else:
                # MODIS nominal ~1km pixels -> ~564m radius area-equivalent; use 500m for clarity
                radius_m = 500.0

            add_faded_circle(
                layer_fires_area,
                lat,
                lon,
                radius_m,
                color="#E02D2D",
                steps=4,
                max_opacity=0.35,
            )
            n += 1
        counts["fires"] = n
    except Exception as e:
        print(f"FIRMS error: {e}")
    layer_fires_area.add_to(m)

    # 7) Tropical cyclones as area circles (dynamic when possible)
    try:
        storm_url = "https://www.nhc.noaa.gov/CurrentStorms.json"
        data = fetch_json(storm_url)
        storms = data.get("currentStorms") or data.get("activeStorms") or []
        for s in storms:
            lat = parse_lat(s.get("lat"))
            lon = parse_lon(s.get("lon"))
            if lat is None or lon is None:
                continue
            # No region filtering; show worldwide
            name = s.get("name") or s.get("stormName") or "Storm"
            # Estimate radius dynamically from available metadata
            def estimate_tc_radius_km(storm):
                # Try wind speed in knots
                wind = to_float(storm.get("wind") or storm.get("maxWind") or storm.get("intensity") or storm.get("sustainedWind"))
                if wind is not None:
                    kts = max(0.0, float(wind))
                    if kts < 34: return 100.0
                    if kts < 50: return 150.0
                    if kts < 64: return 200.0
                    if kts < 83: return 250.0  # Cat 1
                    if kts < 96: return 300.0  # Cat 2
                    if kts < 113: return 350.0 # Cat 3
                    if kts < 137: return 420.0 # Cat 4
                    return 500.0               # Cat 5
                # Try Saffir-Simpson category if present
                sshs = s.get("sshs")
                try:
                    if sshs is not None:
                        c = int(sshs)
                        return {0: 250.0, 1: 250.0, 2: 300.0, 3: 350.0, 4: 420.0, 5: 500.0}.get(c, 200.0)
                except Exception:
                    pass
                # Try status/class
                status = (str(storm.get("type") or storm.get("stormType") or storm.get("class") or storm.get("status") or "")).upper()
                if "TD" in status: return 120.0
                if "TS" in status: return 200.0
                if "HU" in status or "HURRICANE" in status: return 320.0
                # Fallback
                return float(STORM_RADIUS_KM)

            radius_km = estimate_tc_radius_km(s)
            # Clamp
            radius_km = max(60.0, min(600.0, radius_km))

            add_faded_circle(
                layer_tc_areas,
                lat,
                lon,
                radius_km * 1000.0,
                color="#0077BE",
                steps=5,
                max_opacity=0.25,
            )
            counts["storms"] += 1
    except Exception as e:
        print(f"NHC error: {e}")
    layer_tc_areas.add_to(m)

    # Controls
    folium.LayerControl(collapsed=True).add_to(m)

    # Inject legend/key into the Layers control so there's only one box
    try:
        # Build HTML that will be inserted inside the layers control
        def _swatch(color, label):
            return (
                f'<div style="display:flex;align-items:center;margin:3px 0;">'
                f'<span style="display:inline-block;width:14px;height:14px;background:{color};opacity:0.9;'
                f'border-radius:50%;margin-right:8px;border:1px solid rgba(0,0,0,0.25);"></span>'
                f'<span>{label}</span>'
                f'</div>'
            )

        legend_items = [
            ("#E02D2D", "Wildfire area (FIRMS)"),
            ("#7B1FA2", "Earthquake felt area (USGS approx.)"),
            ("#0077BE", "Tropical cyclone area (approx.)"),
            ("#B87333", "Volcano activity (EONET)"),
            ("#D50000", "SPC Tornado report (~8 km)"),
            ("#FFB300", "SPC Wind report (~6 km)"),
            ("#00ACC1", "SPC Hail report (~5 km)"),
        ]
        nws_legend_map = {
            "Tornado Warning": "#ff0000",
            "Tornado Watch": "#ff7f00",
            "Severe Thunderstorm Warning": "#ffa500",
            "Severe Thunderstorm Watch": "#ffd37f",
            "Flash Flood Warning": "#00aa00",
            "Flood Warning": "#008000",
            "Hurricane Warning": "#800080",
            "Hurricane Watch": "#b266ff",
            "Tropical Storm Warning": "#4b0082",
            "Winter Storm Warning": "#1e90ff",
            "Blizzard Warning": "#87cefa",
            "Red Flag Warning": "#b22222",
            "Excessive Heat Warning": "#e31a1c",
            "High Wind Warning": "#9e9e00",
            "Special Marine Warning": "#006d77",
            "Tsunami Warning": "#0065bd",
            "Tsunami Advisory": "#5aa7ff",
            "Tsunami Watch": "#89c3ff",
        }

        parts = []
        parts.append('<div style="border-top:1px solid #ddd;margin:6px 0;"></div>')
        parts.append('<div style="font-weight:600; margin:6px 0 4px;">Map Key</div>')
        if radar_time_str:
            parts.append(f'<div style="color:#555; margin-bottom:6px;">Radar: {radar_time_str}</div>')
        for color, label in legend_items:
            parts.append(_swatch(color, label))
        parts.append('<div style="margin:8px 0 4px; font-weight:600;">US Alerts (NWS polygons)</div>')
        parts.append('<div style="max-height: 120px; overflow: auto; padding-right: 4px; border-left: 3px solid #eee; padding-left:8px;">')
        for label, color in nws_legend_map.items():
            parts.append(_swatch(color, label))
        parts.append('</div>')
        legend_inner_html = "".join(parts)

        script = f"""
<script>
(function() {{
  function addLegendToLayerControl() {{
    var ctl = document.querySelector('.leaflet-control-layers');
    if (!ctl) return;
    var list = ctl.querySelector('.leaflet-control-layers-list') || ctl;
    var container = document.createElement('div');
    container.className = 'legend-section';
    container.style.marginTop = '4px';
    container.innerHTML = `{legend_inner_html}`;
    list.appendChild(container);
  }}
  if (document.readyState === 'complete') {{ setTimeout(addLegendToLayerControl, 0); }}
  else {{ window.addEventListener('load', addLegendToLayerControl); }}
}})();
</script>
"""
        m.get_root().html.add_child(folium.Element(script))
    except Exception as e:
        print(f"Combined legend injection error: {e}")

    # Optional: embed auto-refresh on the map page
    if auto_refresh:
        try:
            m.get_root().html.add_child(
                folium.Element(
                    f"<script>setTimeout(function(){{location.reload();}},{REFRESH_SECONDS*1000});</script>"
                )
            )
        except Exception as e:
            print(f"Auto-refresh injection error: {e}")

    return m

def build_quick_map(auto_refresh: bool = False):
    """Fast-start map with only base and radar layer to reduce initial load time."""
    center = [20.0, 0.0]
    m = folium.Map(location=center, zoom_start=MAP_ZOOM, tiles="CartoDB positron")
    layer_radar = folium.FeatureGroup(name="Radar (RainViewer)", overlay=True, control=True, show=True)
    radar_time_str = None
    try:
        maps = fetch_json("https://api.rainviewer.com/public/weather-maps.json")
        host = maps.get("host", "https://tilecache.rainviewer.com")
        frames = (maps.get("radar", {}).get("past", []) or []) + (maps.get("radar", {}).get("nowcast", []) or [])
        frame = frames[-1] if frames else None
        if frame and frame.get("path"):
            tile_url = f"{host}{frame['path']}/256/{{z}}/{{x}}/{{y}}/2/1_1.png?color=3&smooth=1&noclutter=1"
            folium.TileLayer(
                tiles=tile_url,
                name="Radar (RainViewer latest)",
                attr="RainViewer",
                overlay=True,
                control=True,
                opacity=RADAR_OPACITY,
            ).add_to(layer_radar)
            ts = frame.get("time")
            if ts:
                radar_time_str = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except Exception as e:
        print(f"RainViewer (quick) error: {e}")
    layer_radar.add_to(m)

    folium.LayerControl(collapsed=True).add_to(m)

    if auto_refresh:
        try:
            m.get_root().html.add_child(
                folium.Element(
                    f"<script>setTimeout(function(){{location.reload();}},{REFRESH_SECONDS*1000});</script>"
                )
            )
        except Exception as e:
            print(f"Auto-refresh (quick) injection error: {e}")
    return m

def write_timeline(*args, **kwargs):
    return None


def main():
    # Ensure output directories exist
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    opened = False
    import time as _time
    start = _time.monotonic()
    max_seconds = MAX_RUNTIME_HOURS * 3600 if MAX_RUNTIME_HOURS and MAX_RUNTIME_HOURS > 0 else None
    try:
        while True:
            # Fast-start: generate a quick radar-only map first
            try:
                mq = build_quick_map(auto_refresh=True)
                mq.save(MAP_FILENAME)
                if not opened:
                    try:
                        import webbrowser
                        webbrowser.open(f"file://{os.path.abspath(MAP_FILENAME)}")
                    except Exception:
                        pass
                    opened = True
                print(f"Updated (quick): {MAP_FILENAME}")
            except Exception as e:
                print(f"Quick map error: {e}")

            # Then build the full map with all overlays
            m = build_map(auto_refresh=True)
            # Save snapshot and latest
            try:
                m.save(MAP_FILENAME)
                print(f"Updated (full): {MAP_FILENAME}")
            except Exception as e:
                print(f"Save error: {e}")

            # Wait for next refresh
            if max_seconds is not None and (_time.monotonic() - start) >= max_seconds:
                print(f"Max runtime reached ({MAX_RUNTIME_HOURS}h). Exiting.")
                break
            _time.sleep(REFRESH_SECONDS)
    except KeyboardInterrupt:
        print("Stopped auto-refresh loop.")

if __name__ == "__main__":
    main()
