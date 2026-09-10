"""
Generates data/sample_gtfs.zip: a small, fictional GTFS feed for "Ridgeline Transit",
a gateway-town shuttle system serving trailheads with little to no cell coverage.
Run once: python data/make_sample_gtfs.py
"""
import csv
import io
import zipfile
from pathlib import Path

HERE = Path(__file__).parent

agency = [
    ["agency_id", "agency_name", "agency_url", "agency_timezone"],
    ["ridgeline", "Ridgeline Transit", "https://example.org/ridgeline", "America/Denver"],
]

routes = [
    ["route_id", "agency_id", "route_short_name", "route_long_name", "route_type", "route_color"],
    ["R1", "ridgeline", "1", "Village – Lakeshore Trailhead", "3", "3FA796"],
    ["R2", "ridgeline", "2", "Village – Ridge Overlook", "3", "E8A33D"],
    ["R3", "ridgeline", "3", "Depot – Canyon Rim Loop", "3", "C1502E"],
]

# stop_id, stop_name, stop_lat, stop_lon
stops = [
    ["stop_id", "stop_name", "stop_lat", "stop_lon"],
    ["S01", "Village Depot", "44.6180", "-110.5020"],
    ["S02", "Village Market", "44.6205", "-110.4988"],
    ["S03", "Aspen Junction", "44.6240", "-110.4930"],
    ["S04", "Meadow Loop", "44.6288", "-110.4870"],
    ["S05", "Lakeshore Trailhead", "44.6340", "-110.4790"],
    ["S06", "Sawtooth Vista", "44.6255", "-110.5090"],
    ["S07", "Ridge Switchback", "44.6300", "-110.5180"],
    ["S08", "Ridge Overlook", "44.6355", "-110.5260"],
    ["S09", "Canyon Rim East", "44.6120", "-110.4960"],
    ["S10", "Canyon Rim West", "44.6090", "-110.5120"],
    ["S11", "Old Mill Bridge", "44.6150", "-110.5210"],
]

# route_id, shape_id, points (lat, lon, sequence)
shapes_by_route = {
    "R1": ["S01", "S02", "S03", "S04", "S05"],
    "R2": ["S01", "S06", "S07", "S08"],
    "R3": ["S01", "S09", "S10", "S11", "S01"],
}

trips = [["route_id", "service_id", "trip_id", "trip_headsign", "shape_id"]]
stop_times = [["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"]]
shapes = [["shape_id", "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"]]

stop_lookup = {row[0]: (row[2], row[3]) for row in stops[1:]}

for route_id, stop_seq in shapes_by_route.items():
    shape_id = f"shp_{route_id}"
    trip_id = f"trip_{route_id}_1"
    trips.append([route_id, "WKDY", trip_id, stop_lookup and f"To {stop_seq[-1]}", shape_id])

    minute = 0
    for i, sid in enumerate(stop_seq):
        h, m = divmod(7 * 60 + minute, 60)
        t = f"{h:02d}:{m:02d}:00"
        stop_times.append([trip_id, t, t, sid, i + 1])
        minute += 6

    for i, sid in enumerate(stop_seq):
        lat, lon = stop_lookup[sid]
        shapes.append([shape_id, lat, lon, i + 1])

calendar = [
    ["service_id", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
     "start_date", "end_date"],
    ["WKDY", "1", "1", "1", "1", "1", "1", "1", "20260101", "20261231"],
]

files = {
    "agency.txt": agency,
    "routes.txt": routes,
    "stops.txt": stops,
    "trips.txt": trips,
    "stop_times.txt": stop_times,
    "shapes.txt": shapes,
    "calendar.txt": calendar,
}

out_path = HERE / "sample_gtfs.zip"
with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
    for name, rows in files.items():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerows(rows)
        zf.writestr(name, buf.getvalue())

print(f"Wrote {out_path} ({out_path.stat().st_size} bytes)")
