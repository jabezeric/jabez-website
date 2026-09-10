"""
Transit Packet — Flask backend.

Endpoints:
  GET  /                         -> map UI
  GET  /api/routes                -> list of routes in the loaded feed
  GET  /api/geometry?route_ids=a,b&bbox=w,s,e,n   -> GeoJSON shapes + stops for map preview
  POST /api/package                -> body {route_ids, bbox?, format: "kml"|"gtfs", name?}
                                       builds the file server-side, returns {token, size_bytes,
                                       filename, download_url}
  GET  /api/download/<token>       -> serves the built file (also what the QR code encodes)

Swap FEED_PATH to point at any real city's GTFS zip. The bundled sample is a tiny
fictional mountain-gateway shuttle feed so the app is runnable with zero setup.
"""
import io
import time
import uuid
from pathlib import Path

from flask import Flask, jsonify, request, send_file, render_template, abort

import gtfs_utils

BASE_DIR = Path(__file__).parent
FEED_PATH = BASE_DIR / "data" / "sample_gtfs.zip"

app = Flask(__name__)

_feed = None
_packages = {}  # token -> {"bytes": ..., "filename": ..., "mimetype": ..., "created": ts}
PACKAGE_TTL_SECONDS = 60 * 30


def get_feed():
    global _feed
    if _feed is None:
        _feed = gtfs_utils.load_gtfs(FEED_PATH.read_bytes())
    return _feed


def _prune_packages():
    now = time.time()
    stale = [k for k, v in _packages.items() if now - v["created"] > PACKAGE_TTL_SECONDS]
    for k in stale:
        _packages.pop(k, None)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/routes")
def api_routes():
    return jsonify(gtfs_utils.route_summary(get_feed()))


@app.route("/api/geometry")
def api_geometry():
    route_ids = [r for r in request.args.get("route_ids", "").split(",") if r]
    if not route_ids:
        return jsonify({"shapes": [], "stops": []})
    bbox_param = request.args.get("bbox")
    bbox = [float(x) for x in bbox_param.split(",")] if bbox_param else None
    geo = gtfs_utils.geometry_for_routes(get_feed(), route_ids, bbox)
    return jsonify(geo)


@app.route("/api/package", methods=["POST"])
def api_package():
    body = request.get_json(force=True) or {}
    route_ids = body.get("route_ids") or []
    bbox = body.get("bbox")
    fmt = body.get("format", "kml")
    name = body.get("name") or "Transit Packet"

    if not route_ids:
        return jsonify({"error": "route_ids is required"}), 400

    feed = get_feed()
    if fmt == "kml":
        data = gtfs_utils.build_kml(feed, route_ids, bbox, package_name=name)
        filename = f"{_slug(name)}.kml"
        mimetype = "application/vnd.google-earth.kml+xml"
    elif fmt == "gtfs":
        data = gtfs_utils.build_mini_gtfs(feed, route_ids)
        filename = f"{_slug(name)}-gtfs.zip"
        mimetype = "application/zip"
    else:
        return jsonify({"error": "format must be 'kml' or 'gtfs'"}), 400

    _prune_packages()
    token = uuid.uuid4().hex[:10]
    _packages[token] = {
        "bytes": data, "filename": filename, "mimetype": mimetype, "created": time.time(),
    }

    return jsonify({
        "token": token,
        "size_bytes": len(data),
        "filename": filename,
        "download_url": f"/api/download/{token}",
    })


@app.route("/api/download/<token>")
def api_download(token):
    pkg = _packages.get(token)
    if not pkg:
        abort(404, description="Package expired or not found. Rebuild it from the map.")
    return send_file(
        io.BytesIO(pkg["bytes"]),
        mimetype=pkg["mimetype"],
        as_attachment=True,
        download_name=pkg["filename"],
    )


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-") or "transit-packet"


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
