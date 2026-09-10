"""
gtfs_utils.py
Load a GTFS feed (a .zip of the standard text files) with pandas, turn shapes/stops
into geopandas GeoDataFrames, filter by route selection and/or a drawn bounding box,
and export the result as either:
  - a styled KML (tracks + labeled stop placemarks), or
  - a minimized GTFS zip containing only the rows needed for the selection.

Everything here works off any real-world GTFS feed, not just the bundled sample.
"""
from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from xml.sax.saxutils import escape

import pandas as pd
import geopandas as gpd
from shapely.geometry import LineString, Point, box

REQUIRED_FILES = ["agency.txt", "routes.txt", "stops.txt", "trips.txt", "stop_times.txt"]
OPTIONAL_FILES = ["shapes.txt", "calendar.txt", "calendar_dates.txt"]


@dataclass
class GTFSFeed:
    tables: dict  # filename (without .txt) -> DataFrame
    source_bytes: bytes  # raw zip bytes, kept so we can re-slice untouched columns

    def __getattr__(self, name):
        if name in self.tables:
            return self.tables[name]
        raise AttributeError(name)


def load_gtfs(zip_bytes: bytes) -> GTFSFeed:
    """Parse a GTFS zip (bytes) into a GTFSFeed of pandas DataFrames."""
    tables = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = set(zf.namelist())
        for fname in REQUIRED_FILES + OPTIONAL_FILES:
            if fname in names:
                with zf.open(fname) as f:
                    df = pd.read_csv(f, dtype=str)
                    df.columns = [c.strip() for c in df.columns]
                    tables[fname.replace(".txt", "")] = df
        missing = [f for f in REQUIRED_FILES if f.replace(".txt", "") not in tables]
        if missing:
            raise ValueError(f"GTFS feed is missing required files: {missing}")
    return GTFSFeed(tables=tables, source_bytes=zip_bytes)


def route_summary(feed: GTFSFeed) -> list[dict]:
    routes = feed.tables["routes"]
    out = []
    for _, r in routes.iterrows():
        out.append({
            "route_id": r["route_id"],
            "short_name": r.get("route_short_name", "") or "",
            "long_name": r.get("route_long_name", "") or "",
            "color": (r.get("route_color") or "3FA796").strip() or "3FA796",
            "type": r.get("route_type", ""),
        })
    return out


def _shapes_gdf(feed: GTFSFeed, route_ids: list[str]) -> gpd.GeoDataFrame:
    """One LineString per route, built from shapes.txt (falls back to stop sequence)."""
    trips = feed.tables["trips"]
    trips = trips[trips["route_id"].isin(route_ids)]

    rows = []
    if "shapes" in feed.tables and "shape_id" in trips.columns:
        shapes = feed.tables["shapes"].copy()
        shapes["shape_pt_sequence"] = pd.to_numeric(shapes["shape_pt_sequence"])
        shapes["shape_pt_lat"] = pd.to_numeric(shapes["shape_pt_lat"])
        shapes["shape_pt_lon"] = pd.to_numeric(shapes["shape_pt_lon"])
        for route_id, route_trips in trips.groupby("route_id"):
            shape_id = route_trips["shape_id"].dropna().iloc[0] if route_trips["shape_id"].notna().any() else None
            if shape_id is None:
                continue
            pts = shapes[shapes["shape_id"] == shape_id].sort_values("shape_pt_sequence")
            if len(pts) < 2:
                continue
            line = LineString(list(zip(pts["shape_pt_lon"], pts["shape_pt_lat"])))
            rows.append({"route_id": route_id, "geometry": line})
    else:
        # fall back to stop_times order via stops.txt lat/lon
        stop_times = feed.tables["stop_times"]
        stops = feed.tables["stops"].set_index("stop_id")
        for route_id, route_trips in trips.groupby("route_id"):
            trip_id = route_trips["trip_id"].iloc[0]
            st = stop_times[stop_times["trip_id"] == trip_id].sort_values("stop_sequence")
            coords = [(float(stops.loc[sid, "stop_lon"]), float(stops.loc[sid, "stop_lat"]))
                      for sid in st["stop_id"] if sid in stops.index]
            if len(coords) >= 2:
                rows.append({"route_id": route_id, "geometry": LineString(coords)})

    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326") if rows else \
        gpd.GeoDataFrame(columns=["route_id", "geometry"], geometry="geometry", crs="EPSG:4326")


def _stops_gdf(feed: GTFSFeed, route_ids: list[str]) -> gpd.GeoDataFrame:
    """Stops actually served by the selected routes (via trips -> stop_times -> stops)."""
    trips = feed.tables["trips"]
    trip_ids = trips[trips["route_id"].isin(route_ids)]["trip_id"]
    stop_times = feed.tables["stop_times"]
    stop_ids = stop_times[stop_times["trip_id"].isin(trip_ids)]["stop_id"].unique()

    stops = feed.tables["stops"]
    sub = stops[stops["stop_id"].isin(stop_ids)].copy()
    sub["stop_lat"] = pd.to_numeric(sub["stop_lat"])
    sub["stop_lon"] = pd.to_numeric(sub["stop_lon"])
    geometry = [Point(lon, lat) for lon, lat in zip(sub["stop_lon"], sub["stop_lat"])]
    return gpd.GeoDataFrame(sub, geometry=geometry, crs="EPSG:4326")


def geometry_for_routes(feed: GTFSFeed, route_ids: list[str], bbox: list[float] | None = None) -> dict:
    """
    Returns GeoJSON-ready dict: {"shapes": [...], "stops": [...]}
    bbox, if given, is [west, south, east, north] and further restricts stops/shapes.
    """
    shapes_gdf = _shapes_gdf(feed, route_ids)
    stops_gdf = _stops_gdf(feed, route_ids)

    if bbox:
        clip_box = box(*bbox)  # box() takes (minx, miny, maxx, maxy) == (west, south, east, north)
        if not shapes_gdf.empty:
            shapes_gdf = shapes_gdf[shapes_gdf.intersects(clip_box)].copy()
            shapes_gdf["geometry"] = shapes_gdf.intersection(clip_box)
            shapes_gdf = shapes_gdf[~shapes_gdf.geometry.is_empty]
            # a box can slice one route into several disjoint segments (MultiLineString);
            # explode so each segment becomes its own LineString feature
            if not shapes_gdf.empty:
                shapes_gdf = shapes_gdf.explode(index_parts=False).reset_index(drop=True)
                shapes_gdf = shapes_gdf[shapes_gdf.geometry.geom_type == "LineString"]
        if not stops_gdf.empty:
            stops_gdf = stops_gdf[stops_gdf.intersects(clip_box)]

    routes_by_id = {r["route_id"]: r for r in route_summary(feed)}

    shape_features = []
    for _, row in shapes_gdf.iterrows():
        r = routes_by_id.get(row["route_id"], {})
        shape_features.append({
            "type": "Feature",
            "properties": {"route_id": row["route_id"], "color": r.get("color", "3FA796"),
                            "name": r.get("short_name") or r.get("long_name")},
            "geometry": row["geometry"].__geo_interface__,
        })

    stop_features = []
    for _, row in stops_gdf.iterrows():
        stop_features.append({
            "type": "Feature",
            "properties": {"stop_id": row["stop_id"], "name": row.get("stop_name", row["stop_id"])},
            "geometry": row["geometry"].__geo_interface__,
        })

    return {"shapes": shape_features, "stops": stop_features}


def build_kml(feed: GTFSFeed, route_ids: list[str], bbox: list[float] | None = None,
              package_name: str = "Transit Packet") -> bytes:
    """Styled KML: one colored <Placemark><LineString> per route, one pin per stop."""
    geo = geometry_for_routes(feed, route_ids, bbox)
    routes_by_id = {r["route_id"]: r for r in route_summary(feed)}

    style_blocks = []
    seen_colors = set()
    for route_id in route_ids:
        color_hex = routes_by_id.get(route_id, {}).get("color", "3FA796")
        if color_hex in seen_colors:
            continue
        seen_colors.add(color_hex)
        kml_color = "ff" + color_hex[4:6] + color_hex[2:4] + color_hex[0:2]  # KML is aabbggrr
        style_blocks.append(f"""
    <Style id="line_{color_hex}">
      <LineStyle><color>{kml_color}</color><width>4</width></LineStyle>
    </Style>""")

    placemarks = []
    for f in geo["shapes"]:
        coords = " ".join(f"{lon},{lat},0" for lon, lat in f["geometry"]["coordinates"])
        name = escape(str(f["properties"]["name"] or f["properties"]["route_id"]))
        color_hex = f["properties"]["color"]
        placemarks.append(f"""
    <Placemark>
      <name>{name}</name>
      <styleUrl>#line_{color_hex}</styleUrl>
      <LineString><tessellate>1</tessellate><coordinates>{coords}</coordinates></LineString>
    </Placemark>""")

    for f in geo["stops"]:
        lon, lat = f["geometry"]["coordinates"]
        name = escape(str(f["properties"]["name"]))
        placemarks.append(f"""
    <Placemark>
      <name>{name}</name>
      <Point><coordinates>{lon},{lat},0</coordinates></Point>
    </Placemark>""")

    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>{escape(package_name)}</name>
    <Style id="stop_default">
      <IconStyle><scale>0.9</scale></IconStyle>
    </Style>{"".join(style_blocks)}{"".join(placemarks)}
  </Document>
</kml>"""
    return kml.encode("utf-8")


def build_mini_gtfs(feed: GTFSFeed, route_ids: list[str]) -> bytes:
    """A GTFS-compliant zip trimmed to only the rows relevant to the selected routes."""
    t = feed.tables
    routes = t["routes"][t["routes"]["route_id"].isin(route_ids)]
    trips = t["trips"][t["trips"]["route_id"].isin(route_ids)]
    trip_ids = trips["trip_id"]
    stop_times = t["stop_times"][t["stop_times"]["trip_id"].isin(trip_ids)]
    stop_ids = stop_times["stop_id"].unique()
    stops = t["stops"][t["stops"]["stop_id"].isin(stop_ids)]

    out_tables = {
        "routes.txt": routes,
        "trips.txt": trips,
        "stop_times.txt": stop_times,
        "stops.txt": stops,
    }
    if "agency" in t:
        out_tables["agency.txt"] = t["agency"]
    if "shapes" in t and "shape_id" in trips.columns:
        shape_ids = trips["shape_id"].dropna().unique()
        out_tables["shapes.txt"] = t["shapes"][t["shapes"]["shape_id"].isin(shape_ids)]
    if "calendar" in t:
        service_ids = trips["service_id"].unique() if "service_id" in trips.columns else []
        out_tables["calendar.txt"] = t["calendar"][t["calendar"]["service_id"].isin(service_ids)]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname, df in out_tables.items():
            zf.writestr(fname, df.to_csv(index=False))
    return buf.getvalue()
