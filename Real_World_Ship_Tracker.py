import asyncio
from playwright.async_api import async_playwright
import pandas as pd
import geopandas as gpd
import folium
from folium.plugins import MarkerCluster
import webbrowser
import os
import math
from folium import DivIcon
import branca.colormap as cm
from folium.features import DivIcon

# === Source ===
# https://www.marinetraffic.com/en/ais/home/centerx:-86.1/centery:32.0/zoom:5

# === CONFIGURE YOUR FILTERS HERE ===

FILTER_SHIP_TYPE_NAMES = []
FILTER_REGION_NAME = ["north_america","south_america",]
ZOOM = 4

# === SHIP TYPE CODES REFERENCE ===
# "0"  = "Unkown"
# "1"  = "Cargo"
# "2"  = "Tanker"
# "3"  = "Passenger"
# "4"  = "High Speed Craft"
# "5"  = "Fishing"
# "6"  = "Tug"
# "7"  = "Port Tender"
# "8"  = "Anti-pollution"
# "9"  = "Other"
# "10" = "Medical Transport"
# "11" = "Law Enforcement"

# Premade region options for FILTER_REGION_NAME:
# "worldwide"      - Entire globe (no filtering)
# "north_america"  - Most of North America
# "south_america"  - South America continent
# "europe"         - Europe continent
# "asia"           - Asia continent incl. Middle East & Russia eastward
# "africa"         - Africa continent
# "oceania"        - Australia, New Zealand & surrounding islands
# "antarctica"     - Antarctic continent & surrounding seas
# "middle_east"    - All of Middle East

# Ocean regions:
# "atlantic_ocean" - Atlantic Ocean region
# "pacific_ocean_1"- Western Pacific ocean
# "pacific_ocean_2"- Eastern Pacific ocean
# "indian_ocean"   - Indian Ocean region
# "arctic_ocean"   - Arctic Ocean region (high northern latitudes)
# "southern_ocean" - Southern Ocean region (around Antarctica)

# ================================

SHIP_TYPE_NAME_TO_CODE = {
    "unknown": "0",
    "cargo": "1",
    "tanker": "2",
    "passenger": "3",
    "high speed craft": "4",
    "fishing": "5",
    "tug": "6",
    "port tender": "7",
    "anti-pollution": "8",
    "other": "9",
    "medical transport": "10",
    "law enforcement": "11"
}

SHIP_TYPE_CODE_TO_NAME = {v: k.title() for k, v in SHIP_TYPE_NAME_TO_CODE.items()}

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
    "pacific_ocean_1": (-60.0, 72.0, 110.0, 180.0),  # Western Pacific
    "pacific_ocean_2": (-60.0, 72.0, -180.0, -85.0), # Eastern Pacific
    "indian_ocean": (-50.0, 30.0, 20.0, 110.0),
    "arctic_ocean": (66.0, 90.0, -180.0, 180.0),
    "southern_ocean": (-90.0, -60.0, -180.0, 180.0)
}

async def fetch_tile_data(z, x, y, page):
    url = f"https://www.marinetraffic.com/getData/get_data_json_4/z:{z}/X:{x}/Y:{y}/station:0"
    try:
        return await page.evaluate(
            f"""
            async () => {{
                const res = await fetch("{url}", {{
                    method: "GET",
                    headers: {{
                        "Referer": "https://www.marinetraffic.com/"
                    }}
                }});
                return await res.json();
            }}
            """
        )
    except Exception as e:
        print(f"Error fetching tile {z}/{x}/{y}: {e}")
        return None

async def fetch_all_tiles():
    z = ZOOM  # Zoom level
    tile_coords = [(z, x, y) for x in range(8) for y in range(8)]  # z=3 has 8x8 tiles

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
        )
        page = await context.new_page()

        await page.goto("https://www.marinetraffic.com/")  # Setup cookies/session

        tasks = [fetch_tile_data(z, x, y, page) for (z, x, y) in tile_coords]
        results = await asyncio.gather(*tasks)

        await browser.close()

        all_rows = []
        for result in results:
            if result and isinstance(result, dict):
                rows = result.get("data", {}).get("rows", [])
                all_rows.extend(rows)
        return all_rows


def apply_filters(df):
    # Ship type filtering
    if FILTER_SHIP_TYPE_NAMES:
        filter_names_lower = [name.lower() for name in FILTER_SHIP_TYPE_NAMES]
        filter_codes = [
            SHIP_TYPE_NAME_TO_CODE[name]
            for name in filter_names_lower
            if name in SHIP_TYPE_NAME_TO_CODE
        ]
        if not filter_codes:
            print("Warning: No matching ship type codes found. Skipping ship type filter.")
        else:
            df = df[df["SHIPTYPE"].isin(filter_codes)]

    # Region filtering
    if FILTER_REGION_NAME:
        df["LAT"] = pd.to_numeric(df["LAT"], errors="coerce")
        df["LON"] = pd.to_numeric(df["LON"], errors="coerce")
        region_filtered = pd.DataFrame()
        for region in FILTER_REGION_NAME:
            if region not in PREMADE_REGIONS:
                print(f"Warning: Region '{region}' not found. Skipping.")
                continue
            min_lat, max_lat, min_lon, max_lon = PREMADE_REGIONS[region]
            region_df = df[
                (df["LAT"] >= min_lat) & (df["LAT"] <= max_lat) &
                (df["LON"] >= min_lon) & (df["LON"] <= max_lon)
            ]
            region_filtered = pd.concat([region_filtered, region_df])
        df = region_filtered
    return df

def save_ships_table(df, filename="ships_table.csv"):
    df = df.copy()

    # Make sure SHIPNAME exists, fill missing with "Unknown"
    if "SHIPNAME" not in df.columns:
        df["SHIPNAME"] = "Unknown"
    else:
        df["SHIPNAME"] = df["SHIPNAME"].fillna("Unknown")

    # Put SHIPNAME first, then other columns sorted alphabetically (excluding SHIPNAME)
    cols = df.columns.tolist()
    cols.remove("SHIPNAME")
    cols_sorted = ["SHIPNAME"] + sorted(cols)

    # Reorder df
    df = df[cols_sorted]

    # Save to CSV
    df.to_csv(filename, index=False)
    print(f"Saved ships data table to {filename}")

def plot_ships_folium(df):
    if df.empty:
        print("No ships to plot. Skipping map rendering.")
        return

    df = df.copy()
    df["LAT"] = pd.to_numeric(df["LAT"], errors="coerce")
    df["LON"] = pd.to_numeric(df["LON"], errors="coerce")
    df = df.dropna(subset=["LAT", "LON", "SHIPTYPE"])

    # Map ship type code to readable names
    df["SHIPTYPE_NAME"] = df["SHIPTYPE"].map(SHIP_TYPE_CODE_TO_NAME).fillna("Unknown")

    # Create folium map centered on mean coords
    center_lat = df["LAT"].mean()
    center_lon = df["LON"].mean()
    m = folium.Map(location=[center_lat, center_lon], zoom_start=4, tiles="OpenStreetMap")

    # Create color palette for ship types
    ship_types = df["SHIPTYPE_NAME"].unique()
    palette = cm.linear.Set1_09.scale(0, len(ship_types) - 1)
    color_dict = {stype: palette(i) for i, stype in enumerate(ship_types)}

    # Add marker cluster
    marker_cluster = MarkerCluster().add_to(m)

    for _, row in df.iterrows():
        lat, lon = row["LAT"], row["LON"]
        ship_name = row.get("SHIPNAME", "Unknown")
        ship_type_name = row.get("SHIPTYPE_NAME", "Unknown")
        destination = row.get("DESTINATION", "Unknown")
        heading = row.get("HEADING")

        popup_html = f"""
            <b>{ship_name}</b><br>
            Type: {ship_type_name}<br>
            Destination: {destination}
        """

        # Get boat color from ship type
        boat_color = color_dict.get(ship_type_name, "blue")  # fallback blue if unknown

        # Prepare arrow rotation CSS if heading is valid
        arrow_style = ""
        try:
            h = float(heading)
            if not math.isnan(h):
                arrow_style = f"transform: rotate({h}deg);"
        except (ValueError, TypeError):
            arrow_style = ""

        # Compose combined icon HTML: colored boat + black arrow
        icon_html = f"""
        <div style="position: relative; width: 32px; height: 32px;">
            <!-- Boat icon with ship type color -->
            <i class="fas fa-ship" style="font-size: 24px; color: {boat_color}; position: absolute; top: 4px; left: 4px;"></i>
            <!-- Black arrow icon, rotated and positioned -->
            {'<i class="fa fa-arrow-up" style="color: black; font-size: 12px; position: absolute; top: 0; left: 12px; ' + arrow_style + '"></i>' if arrow_style else ''}
        </div>
        """

        icon = DivIcon(
            html=icon_html,
            icon_size=(32, 32),
            icon_anchor=(16, 16),  # center anchor so it points correctly
            popup_anchor=(0, -16)
        )

        folium.Marker(
            location=(lat, lon),
            popup=popup_html,
            icon=icon,
        ).add_to(marker_cluster)

    # Add legend
    legend_html = '<div style="position: fixed; bottom: 50px; left: 50px; width: 150px; background-color: white; border:2px solid grey; z-index:9999; font-size:14px;">'
    legend_html += '<b>Ship Types</b><br>'
    for stype, color in color_dict.items():
        legend_html += f'<i style="background:{color};width:15px;height:15px;float:left;margin-right:5px;"></i>{stype}<br>'
    legend_html += '</div>'
    m.get_root().html.add_child(folium.Element(legend_html))

    map_filename = "ships_map.html"
    m.save(map_filename)
    print(f"Interactive map saved to {map_filename}")

    full_path = os.path.abspath(map_filename)
    webbrowser.open(f"file://{full_path}")

if __name__ == "__main__":
    ships = asyncio.run(fetch_all_tiles())
    df = pd.DataFrame(ships).drop_duplicates(subset=["SHIP_ID"])

    # print("Unique SHIPTYPE codes in dataset:", df["SHIPTYPE"].dropna().unique())
    print(f"Total boats fetched: {len(df)}")

    df_filtered = apply_filters(df)

    print(f"Boats after filtering: {len(df_filtered)}")
    print(df_filtered.head())

    df_filtered.to_csv("filtered_ships_data.csv", index=False)
    print("Saved filtered_ships_data.csv with filtered boats.")

    save_ships_table(df_filtered, filename="ships_table.csv")
    plot_ships_folium(df_filtered)
