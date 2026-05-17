"""
Planes Overhead — single-file Flask app.
LED matrix board showing the closest aircraft flying near you.

Run:
    python3 -m pip install flask requests
    python3 app.py
Open http://127.0.0.1:5000
"""

import math
import os
import requests
from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)

OPENSKY_URL = "https://opensky-network.org/api/states/all"
ADSBDB_CALLSIGN_URL = "https://api.adsbdb.com/v0/callsign/{callsign}"
ADSBDB_AIRCRAFT_URL = "https://api.adsbdb.com/v0/aircraft/{icao24}"

DEFAULT_RADIUS_KM = 75
MIN_RADIUS_KM = 5
MAX_RADIUS_KM = 400
EARTH_RADIUS_KM = 6371
KM_PER_DEG_LAT = 111.0
HTTP_TIMEOUT = 25
OPENSKY_AUTH = (os.environ["OPENSKY_USER"], os.environ["OPENSKY_PASS"]) if os.environ.get("OPENSKY_USER") else None


def haversine_km(lat1, lon1, lat2, lon2):
    to_rad = math.radians
    d_lat = to_rad(lat2 - lat1)
    d_lon = to_rad(lon2 - lon1)
    a = (math.sin(d_lat / 2) ** 2
         + math.cos(to_rad(lat1)) * math.cos(to_rad(lat2)) * math.sin(d_lon / 2) ** 2)
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def bounding_box(lat, lon, radius_km):
    d_lat = radius_km / KM_PER_DEG_LAT
    d_lon = radius_km / (KM_PER_DEG_LAT * max(math.cos(math.radians(lat)), 0.01))
    return lat - d_lat, lon - d_lon, lat + d_lat, lon + d_lon


def fetch_nearby_states(lat, lon, radius_km):
    lamin, lomin, lamax, lomax = bounding_box(lat, lon, radius_km)
    r = requests.get(
        OPENSKY_URL,
        params={"lamin": lamin, "lomin": lomin, "lamax": lamax, "lomax": lomax},
        timeout=HTTP_TIMEOUT,
        auth=OPENSKY_AUTH,
    )
    r.raise_for_status()
    return r.json().get("states") or []


def fetch_route(callsign):
    if not callsign:
        return None
    try:
        r = requests.get(ADSBDB_CALLSIGN_URL.format(callsign=callsign), timeout=HTTP_TIMEOUT)
        if r.status_code != 200:
            return None
        return (r.json().get("response") or {}).get("flightroute")
    except requests.RequestException:
        return None


def fetch_aircraft(icao24):
    if not icao24:
        return None
    try:
        r = requests.get(ADSBDB_AIRCRAFT_URL.format(icao24=icao24), timeout=HTTP_TIMEOUT)
        if r.status_code != 200:
            return None
        return (r.json().get("response") or {}).get("aircraft")
    except requests.RequestException:
        return None


def build_plane_payload(state, user_lat, user_lon):
    icao24 = state[0]
    callsign = (state[1] or "").strip()
    lon, lat = state[5], state[6]
    baro_alt_m = state[7] or 0
    velocity_ms = state[9] or 0
    geo_alt_m = state[13] or 0
    altitude_m = geo_alt_m or baro_alt_m
    airline_icao = callsign[:3] if len(callsign) >= 3 else ""

    route = fetch_route(callsign)
    aircraft = fetch_aircraft(icao24)
    airline = (route or {}).get("airline") or {}
    origin = (route or {}).get("origin") or {}
    destination = (route or {}).get("destination") or {}

    eta_minutes = None
    if destination.get("latitude") is not None and velocity_ms > 50:
        dist_km = haversine_km(lat, lon, destination["latitude"], destination["longitude"])
        eta_minutes = round(dist_km / (velocity_ms * 3.6) * 60)
        if eta_minutes <= 0 or eta_minutes > 24 * 60:
            eta_minutes = None

    return {
        "icao24": icao24,
        "callsign": callsign,
        "origin_country": state[2],
        "distance_km": round(haversine_km(user_lat, user_lon, lat, lon), 1),
        "altitude_ft": int(altitude_m * 3.28084),
        "speed_kts": int(velocity_ms * 1.94384),
        "airline": {
            "icao": airline.get("icao") or airline_icao,
            "iata": airline.get("iata") or "",
            "name": airline.get("name") or "",
        },
        "aircraft_icao": (aircraft or {}).get("icao_type") or "",
        "origin": {
            "iata": origin.get("iata_code"), "icao": origin.get("icao_code"),
            "name": origin.get("name"), "city": origin.get("municipality"),
        } if origin else None,
        "destination": {
            "iata": destination.get("iata_code"), "icao": destination.get("icao_code"),
            "name": destination.get("name"), "city": destination.get("municipality"),
        } if destination else None,
        "eta_minutes": eta_minutes,
    }


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Planes Overhead</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=VT323&family=Silkscreen:wght@400;700&display=swap" rel="stylesheet">
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body {
  height: 100%; background: #0a0a0a; color: #fff;
  font-family: 'VT323', monospace; overflow: hidden;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  padding: 24px;
}
.status-bar {
  font-family: 'Silkscreen', monospace; font-size: 11px; color: #6b7280;
  letter-spacing: 2px; margin-bottom: 18px;
  display: flex; align-items: center; gap: 8px;
}
.status-bar .dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: #22c55e; box-shadow: 0 0 8px #22c55e;
  animation: pulse 1.6s ease-in-out infinite;
}
@keyframes pulse { 50% { opacity: 0.3; } }
.board-frame {
  background: linear-gradient(145deg, #2a2a2a, #0e0e0e);
  padding: 14px; border-radius: 14px;
  box-shadow: 0 30px 60px rgba(0,0,0,0.7),
              inset 0 2px 1px rgba(255,255,255,0.08),
              inset 0 -2px 4px rgba(0,0,0,0.6);
  width: min(96vw, 1100px); aspect-ratio: 16 / 9; max-height: 80vh;
}
.board {
  position: relative; width: 100%; height: 100%;
  background: #000; border-radius: 6px;
  box-shadow: inset 0 0 40px rgba(0,0,0,0.9);
  display: grid; grid-template-columns: 1fr 1.4fr; grid-template-rows: 1fr 1fr;
  padding: 28px 36px; gap: 20px 36px; overflow: hidden;
}
.dot-overlay {
  position: absolute; inset: 0; pointer-events: none;
  background-image: radial-gradient(rgba(255,255,255,0.045) 1px, transparent 1.4px);
  background-size: 5px 5px; z-index: 2;
}
.cell { position: relative; z-index: 1; display: flex; flex-direction: column; justify-content: center; min-width: 0; }
.cell-logo { align-items: center; justify-content: center; }
#logo-slot { width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; }
#logo-slot img {
  max-width: 90%; max-height: 80%; object-fit: contain;
  image-rendering: pixelated; image-rendering: crisp-edges;
  filter: contrast(1.15) saturate(1.2) drop-shadow(0 0 6px rgba(255,255,255,0.15));
}
#logo-slot .placeholder {
  font-size: clamp(60px, 9vw, 130px); color: #ef4444;
  text-shadow: 0 0 12px rgba(239,68,68,0.6), 0 0 24px rgba(239,68,68,0.3);
}
.line {
  font-family: 'VT323', monospace; font-size: clamp(28px, 4.5vw, 56px);
  line-height: 1.05; letter-spacing: 2px; text-transform: uppercase;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.red    { color: #ff2a2a; text-shadow: 0 0 4px rgba(255,42,42,0.9), 0 0 12px rgba(255,42,42,0.5), 0 0 24px rgba(255,42,42,0.25); }
.white  { color: #f5f5f5; text-shadow: 0 0 4px rgba(255,255,255,0.6), 0 0 12px rgba(255,255,255,0.25); }
.yellow { color: #ffc93b; text-shadow: 0 0 4px rgba(255,201,59,0.9), 0 0 14px rgba(255,201,59,0.45); }
.cell-name { gap: 6px; }
.cell-cities { gap: 10px; }
.cell-cities .line { font-size: clamp(22px, 3.4vw, 42px); letter-spacing: 1.5px; }
.cell-stats { gap: 6px; justify-content: center; }
.cell-stats .stat {
  display: flex; align-items: baseline; gap: 18px;
  font-family: 'VT323', monospace; font-size: clamp(24px, 3.6vw, 46px); letter-spacing: 2px;
}
.cell-stats .k { color: #ffc93b; text-shadow: 0 0 6px rgba(255,201,59,0.6); min-width: 4ch; }
.cell-stats .v { color: #f5f5f5; text-shadow: 0 0 6px rgba(255,255,255,0.4); flex: 1; text-align: right; font-variant-numeric: tabular-nums; }
.cell-stats .stat { font-size: clamp(20px, 2.8vw, 36px); gap: 12px; }
.line.small { font-size: clamp(18px, 2.8vw, 36px); opacity: 0.85; }
.line.big   { font-size: clamp(34px, 5.5vw, 64px); }

/* controls row */
.controls {
  display: flex; flex-wrap: wrap; align-items: center; gap: 14px 22px;
  font-family: 'Silkscreen', monospace; font-size: 11px;
  letter-spacing: 2px; color: #6b7280;
  margin-bottom: 18px;
}
.controls .ctl-group { display: flex; align-items: center; gap: 8px; }
.controls label { color: #6b7280; }
.controls select, .controls input, .controls .btn {
  background: #111; color: #ffc93b;
  font-family: 'Silkscreen', monospace; font-size: 11px; letter-spacing: 2px;
  border: 1px solid #333; padding: 5px 10px; border-radius: 4px;
  text-transform: uppercase;
}
.controls input { width: 80px; text-align: center; color: #f5f5f5; }
.controls input::placeholder { color: #444; }
.controls .btn { cursor: pointer; color: #6b7280; }
.controls .btn:hover { color: #ffc93b; border-color: #ffc93b; }
.controls .btn.active { color: #ffc93b; border-color: #ffc93b; }
.controls select:focus, .controls input:focus, .controls .btn:focus {
  outline: 1px solid #ffc93b; outline-offset: 1px;
}
.board::after {
  content: ''; position: absolute; inset: 0; pointer-events: none;
  background: linear-gradient(rgba(0,0,0,0) 50%, rgba(0,0,0,0.18) 50%);
  background-size: 100% 3px; z-index: 3; mix-blend-mode: multiply;
}
@media (max-width: 720px) {
  .board { grid-template-columns: 1fr; grid-template-rows: auto auto auto auto; padding: 20px; gap: 14px; }
  .board-frame { aspect-ratio: auto; height: auto; }
  .line { font-size: clamp(22px, 7vw, 40px); }
}
</style>
</head>
<body>
  <div class="status-bar">
    <span class="dot"></span>
    <span id="status">LOCATING…</span>
  </div>
  <div class="controls">
    <span class="ctl-group">
      <label>ZIP</label>
      <input id="zip-input" type="text" maxlength="5" inputmode="numeric" placeholder="20431">
      <button id="zip-go" class="btn">GO</button>
      <button id="use-location" class="btn">USE MY LOCATION</button>
    </span>
    <span class="ctl-group">
      <label>RADIUS</label>
      <select id="radius">
        <option value="10">10 KM</option>
        <option value="25">25 KM</option>
        <option value="50">50 KM</option>
        <option value="75" selected>75 KM</option>
        <option value="100">100 KM</option>
        <option value="150">150 KM</option>
        <option value="250">250 KM</option>
      </select>
    </span>
    <span class="ctl-group">
      <label>UNITS</label>
      <button id="units-toggle" class="btn">KM</button>
    </span>
  </div>
  <div class="board-frame">
    <div class="board">
      <div class="dot-overlay"></div>
      <div class="cell cell-logo"><div id="logo-slot"><div class="placeholder">✈</div></div></div>
      <div class="cell cell-name">
        <div class="line red"    id="airline-name">———</div>
        <div class="line white"  id="callsign">———</div>
        <div class="line white small" id="aircraft-type">———</div>
      </div>
      <div class="cell cell-cities">
        <div class="line yellow big" id="route-codes">———</div>
        <div class="line yellow"     id="origin-city">———</div>
        <div class="line yellow"     id="destination-city">———</div>
      </div>
      <div class="cell cell-stats">
        <div class="stat"><span class="k">ALT</span><span class="v" id="stat-alt">—</span></div>
        <div class="stat"><span class="k">SPD</span><span class="v" id="stat-spd">—</span></div>
        <div class="stat"><span class="k">DIST</span><span class="v" id="stat-dist">—</span></div>
        <div class="stat"><span class="k">ETA</span><span class="v" id="stat-eta">—</span></div>
      </div>
    </div>
  </div>
<script>
const REFRESH_MS = 12000;
const KM_TO_MI = 0.621371;
const statusEl = document.getElementById('status');
const logoSlot = document.getElementById('logo-slot');
const radiusEl = document.getElementById('radius');
const zipInput = document.getElementById('zip-input');
const zipGo    = document.getElementById('zip-go');
const useLoc   = document.getElementById('use-location');
const unitsBtn = document.getElementById('units-toggle');

let userLat = null, userLon = null;
let timer = null;
let units = 'km';

const set = (id, txt) => { document.getElementById(id).textContent = txt || '———'; };
const setStatus = t => statusEl.textContent = String(t).toUpperCase();
const fmtDist = km => units === 'mi'
  ? `${(km * KM_TO_MI).toFixed(1)} MI`
  : `${km.toFixed(1)} KM`;

const LOGO_SOURCES = (iata, icao) => [
  iata && `https://content.airhex.com/content/logos/airlines_${iata}_350_100_r.png`,
  iata && `https://pics.avs.io/200/80/${iata}.png`,
  iata && `https://daisycon.io/images/airline/?width=300&height=100&iata=${iata}`,
  icao && `https://content.airhex.com/content/logos/airlines_${icao}_350_100_r.png`,
  icao && `https://daisycon.io/images/airline/?width=300&height=100&icao=${icao}`,
].filter(Boolean);

function renderLogo(airline) {
  const sources = LOGO_SOURCES(airline?.iata, airline?.icao);
  if (!sources.length) {
    logoSlot.innerHTML = '<div class="placeholder">✈</div>';
    return;
  }
  logoSlot.innerHTML = '<div class="placeholder">✈</div>';
  let i = 0;
  const img = new Image();
  img.alt = airline?.iata || airline?.icao || 'logo';
  img.onload  = () => { logoSlot.innerHTML = ''; logoSlot.appendChild(img); };
  img.onerror = () => { i++; if (i < sources.length) img.src = sources[i]; };
  img.src = sources[0];
}

function formatEta(min) {
  if (min == null) return '—';
  if (min < 60) return `${min}m`;
  return `${Math.floor(min/60)}h ${String(min%60).padStart(2,'0')}m`;
}

function clearBoard(msg) {
  logoSlot.innerHTML = '<div class="placeholder">✈</div>';
  set('airline-name', msg || 'AWAITING');
  set('callsign', '———');
  set('aircraft-type', '———');
  set('route-codes', '———');
  set('origin-city', '———');
  set('destination-city', '———');
  set('stat-alt','—'); set('stat-spd','—'); set('stat-dist','—'); set('stat-eta','—');
}

function renderPlane(plane, nearbyCount) {
  renderLogo(plane.airline);
  set('airline-name', (plane.airline?.name || plane.airline?.icao || 'UNKNOWN').toUpperCase());
  set('callsign', (plane.callsign || plane.icao24 || '———').toUpperCase());
  set('aircraft-type', (plane.aircraft_icao || '———').toUpperCase());

  const o = plane.origin, d = plane.destination;
  const code = c => c ? (c.iata || c.icao || '—') : '—';
  set('route-codes', `${code(o)}–${code(d)}`);
  set('origin-city', (o?.city || o?.name || 'UNKNOWN ORIGIN').toUpperCase());
  set('destination-city', (d?.city || d?.name || 'UNKNOWN DEST').toUpperCase());

  set('stat-alt', `${plane.altitude_ft.toLocaleString()} FT`);
  set('stat-spd', `${plane.speed_kts} KTS`);
  set('stat-dist', fmtDist(plane.distance_km));
  set('stat-eta', formatEta(plane.eta_minutes));

  setStatus(`${nearbyCount} AIRCRAFT · CLOSEST ${fmtDist(plane.distance_km)}`);
}

async function tick() {
  if (userLat == null) return;
  const radius = radiusEl.value || 75;
  try {
    const r = await fetch(`/api/planes?lat=${userLat}&lon=${userLon}&radius=${radius}`);
    const data = await r.json();
    if (!r.ok)     { setStatus(data.error || `ERROR ${r.status}`); return; }
    if (data.empty){ setStatus(`NO PLANES WITHIN ${fmtDist(data.radius_km)}`); clearBoard('NO PLANES'); return; }
    renderPlane(data.plane, data.nearby_count);
  } catch (e) { setStatus('NETWORK ERROR'); }
}

function startPolling() {
  if (timer) clearInterval(timer);
  tick();
  timer = setInterval(tick, REFRESH_MS);
}

function useBrowserLocation() {
  if (!navigator.geolocation) { setStatus('GEOLOCATION UNSUPPORTED'); return; }
  setStatus('LOCATING…');
  navigator.geolocation.getCurrentPosition(
    pos => {
      userLat = pos.coords.latitude; userLon = pos.coords.longitude;
      setStatus(`WATCHING ${userLat.toFixed(2)}, ${userLon.toFixed(2)}`);
      startPolling();
    },
    err => setStatus('LOCATION DENIED — TRY ZIP'),
    { enableHighAccuracy: false, timeout: 10000, maximumAge: 60000 }
  );
}

async function useZip(zip) {
  zip = String(zip || '').trim();
  if (!/^\d{5}$/.test(zip)) { setStatus('ENTER A 5-DIGIT ZIP'); return; }
  setStatus(`LOOKING UP ${zip}…`);
  try {
    const r = await fetch(`https://api.zippopotam.us/us/${zip}`);
    if (!r.ok) { setStatus('ZIP NOT FOUND'); return; }
    const data = await r.json();
    const place = data.places?.[0];
    if (!place) { setStatus('ZIP NOT FOUND'); return; }
    userLat = parseFloat(place.latitude);
    userLon = parseFloat(place.longitude);
    setStatus(`WATCHING ${place['place name'].toUpperCase()} ${zip}`);
    startPolling();
  } catch (e) { setStatus('ZIP LOOKUP FAILED'); }
}

zipGo.addEventListener('click', () => useZip(zipInput.value));
zipInput.addEventListener('keydown', e => { if (e.key === 'Enter') useZip(zipInput.value); });
useLoc.addEventListener('click', useBrowserLocation);
radiusEl.addEventListener('change', () => { if (userLat != null) tick(); });
unitsBtn.addEventListener('click', () => {
  units = units === 'km' ? 'mi' : 'km';
  unitsBtn.textContent = units.toUpperCase();
  if (userLat != null) tick();
});

useBrowserLocation();
</script>
</body>
</html>"""


@app.route("/")
def index():
    return render_template_string(INDEX_HTML)


@app.route("/api/planes")
def planes():
    try:
        lat = float(request.args["lat"]); lon = float(request.args["lon"])
    except (KeyError, ValueError):
        return jsonify(error="lat and lon query params are required"), 400
    try:
        radius = float(request.args.get("radius", DEFAULT_RADIUS_KM))
    except ValueError:
        radius = DEFAULT_RADIUS_KM
    radius = max(MIN_RADIUS_KM, min(MAX_RADIUS_KM, radius))
    try:
        states = fetch_nearby_states(lat, lon, radius)
    except requests.HTTPError as e:
        code = e.response.status_code if e.response is not None else 502
        msg = "OpenSky is rate-limiting anonymous requests — try again in a minute." \
            if code == 429 else f"OpenSky returned HTTP {code}."
        return jsonify(error=msg), 502
    except requests.RequestException as e:
        return jsonify(error=f"Could not reach OpenSky: {e}"), 502
    airborne = [s for s in states
                if not s[8] and s[5] is not None and s[6] is not None
                and haversine_km(lat, lon, s[6], s[5]) <= radius]
    if not airborne:
        return jsonify(empty=True, nearby_count=0, radius_km=radius)
    airborne.sort(key=lambda s: haversine_km(lat, lon, s[6], s[5]))
    return jsonify(empty=False, nearby_count=len(airborne), radius_km=radius,
                   plane=build_plane_payload(airborne[0], lat, lon))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
