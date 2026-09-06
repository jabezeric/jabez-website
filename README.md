# Chaos Transit — NYC Disruption & Reroute Planner

## The angle
Not another "type A, type B, get a route" map. This tracks live service
disruptions and **automatically recalculates and re-draws your route the
moment a line you're using goes down** — with a running chaos log, like a
real transit ops console. That live "watch it reroute in front of you"
moment is the demo beat for judges.

## What's actually running (open `chaos-transit.html` in any browser, no install)
- A real graph of ~18 NYC stations and 5 lines (1·2·3, A·C·E, 4·5·6,
  N·Q·R·W, L), with real transfer hubs (Union Sq, Times Sq, Fulton St, etc.)
- A genuine Dijkstra shortest-path router running client-side — not a
  mock. Change origin/destination and it computes a fresh route.
- A disruption simulator standing in for a live GTFS-RT alerts feed: it
  randomly (or on a button click) takes a line down with a real-sounding
  reason, and if your current route uses that line, the app **recomputes
  a different path live** and shows both the old (faded) and new (solid)
  route on the map, plus the time delta.
- A scrolling alert ticker acting as the chaos log / audit trail.

## Upgrading this to a "real" backend post-hackathon
This prototype's routing logic is intentionally swappable:
1. **Static GTFS** — pull the MTA's free GTFS feed (stops.txt, routes.txt,
   stop_times.txt) to replace the hand-placed `STATIONS`/`EDGES` with the
   real network and real scheduled travel times.
2. **GTFS-RT alerts** — the MTA publishes a free real-time
   Service Alerts feed (protobuf). Poll it server-side (CORS usually
   blocks browser-side polling of transit agency feeds) and forward
   affected route IDs to the frontend in place of `triggerDisruption()`.
3. **Routing engine** — once the network is the full graph, hand routing
   to OpenTripPlanner or Valhalla instead of the in-browser Dijkstra; keep
   the same "old path vs. new path" diff UI, since that's the part judges
   respond to.
4. Everything else (the schematic map renderer, the ticker, the reroute
   diff logic) can stay as-is — only the data source and routing call
   change.

## Why NYC
Excellent free open data (GTFS + GTFS-RT), real subway line-color
conventions people instantly recognize, and enough transfer hubs to make
"the disrupted line forced a genuinely different route" visually obvious
— which is the whole pitch.
