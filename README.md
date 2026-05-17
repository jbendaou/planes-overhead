# Planes Overhead

A tiny Flask web app that shows the closest aircraft flying near you in a
4-quadrant dashboard:

```
┌──────────────────────┬──────────────────────┐
│   Airline logo       │   Airline name       │
├──────────────────────┼──────────────────────┤
│   From → To          │   Altitude / Speed   │
│                      │   Time to land       │
└──────────────────────┴──────────────────────┘
```

## Run it

```bash
cd planes-overhead
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open <http://127.0.0.1:5000>. Allow location access when the browser asks.
The dashboard polls every 12 seconds.

## How it works

| Quadrant      | Source                                                    |
| ------------- | --------------------------------------------------------- |
| Logo          | AirHex public logo CDN (by airline IATA code)             |
| Carrier name  | adsbdb (callsign → airline)                               |
| From → To     | adsbdb (callsign → origin/destination airports)           |
| Altitude/Speed| OpenSky Network live state vectors                        |
| Time to land  | Computed: distance to destination ÷ current ground speed |

All three services are free and require no API key, but they're rate-limited
for anonymous use — if you see "OpenSky is rate-limiting…" in the status bar,
wait a minute.

## Notes

- Browser geolocation needs HTTPS, **except** on `localhost`/`127.0.0.1`, which
  is why we bind there.
- Route data (origin/destination) is only available for flights adsbdb has
  seen before. General aviation, military, and brand-new routes will show
  "Route unavailable" — telemetry will still work.
- "Time to land" is a straight-line estimate; real ETAs depend on approach
  patterns and ATC.
