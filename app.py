"""Planes Overhead — adsb.lol backend (cloud-friendly, no auth)."""

import math
import requests
from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)

ADSBLOL_URL = "https://api.adsb.lol/v2/lat/{lat}/lon/{lon}/dist/{nm}"
ADSBDB_CALLSIGN_URL = "https://api.adsbdb.com/v0/callsign/{callsign}"
ADSBDB_AIRCRAFT_URL = "https://api.adsbdb.com/v0/aircraft/{icao24}"

DEFAULT_RADIUS_KM = 75
MIN_RADIUS_KM = 5
MAX_RADIUS_KM = 400
EARTH_RADIUS_KM = 6371
KM_TO_NM = 0.539957
HTTP_TIMEOUT = 8
USER_AGENT = "planes-overhead/1.0"


def haversine_km(lat1, lon1, lat2, lon2):
    to_rad = math.radians
    d_lat = to_rad(lat2 - lat1)
    d_lon = to_rad(lon2 - lon1)
    a = (math.sin(d_lat / 2) ** 2
         + math.cos(to_rad(lat1)) * math.cos(to_rad(lat2)) * math.sin(d_lon / 2) ** 2)
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def fetch_nearby_aircraft(lat, lon, radius_km):
    nm = max(1, int(radius_km * KM_TO_NM))
    url = ADSBLOL_URL.format(lat=lat, lon=lon, nm=nm)
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    return r.json().get("ac") or []


def fetch_route(callsign):
    if not callsign:
        return None
    try:
        r = requests.get(ADSBDB_CALLSIGN_URL.format(callsign=callsign),
                         headers={"User-Agent": USER_AGENT}, timeout=HTTP_TIMEOUT)
        if r.status_code != 200:
            return None
        return (r.json().get("response") or {}).get("flightroute")
    except requests.RequestException:
        return None


def fetch_aircraft_info(icao24):
    if not icao24:
        return None
    try:
        r = requests.get(ADSBDB_AIRCRAFT_URL.format(icao24=icao24),
                         headers={"User-Agent": USER_AGENT}, timeout=HTTP_TIMEOUT)
        if r.status_code != 200:
            return None
        return (r.json().get("response") or {}).get("aircraft")
    except requests.RequestException:
        return None


def build_plane_payload(ac, user_lat, user_lon):
    icao24 = (ac.get("hex") or "").strip()
    callsign = (ac.get("flight") or "").strip()
    lat = ac.get("lat")
    lon = ac.get("lon")
    alt_baro = ac.get("alt_baro")
    alt_geom = ac.get("alt_geom")
    altitude_ft = 0
    if isinstance(alt_geom, (int, float)):
        altitude_ft = int(alt_geom)
    elif isinstance(alt_baro, (int, float)):
        altitude_ft = int(alt_baro)
    speed_kts = int(ac.get("gs") or 0)
    aircraft_type = (ac.get("t") or "").strip()
    airline_icao = callsign[:3] if len(callsign) >= 3 else ""

    route = fetch_route(callsign)
    aircraft = fetch_aircraft_info(icao24)
    airline = (route or {}).get("airline") or {}
    origin = (route or {}).get("origin") or {}
    destination = (route or {}).get("destination") or {}

    eta_minutes = None
    if destination.get("latitude") is not None and speed_kts > 50:
        dist_km = haversine_km(lat, lon, destination["latitude"], destination["longitude"])
        speed_kmh = speed_kts * 1.852
        eta_minutes = round(dist_km / speed_kmh * 60)
        if eta_minutes <= 0 or eta_minutes > 24 * 60:
            eta_minutes = None

    return {
        "icao24": icao24,
        "callsign": callsign,
        "distance_km": round(haversine_km(user_lat, user_lon, lat, lon), 1),
        "altitude_ft": altitude_ft,
        "speed_kts": speed_kts,
        "airline": {
            "icao": airline.get("icao") or airline_icao,
            "iata": airline.get("iata") or "",
            "name": airline.get("name") or "",
        },
        "aircraft_icao": (aircraft or {}).get("icao_type") or aircraft_type or "",
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
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Planes Overhead</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=VT323&family=Silkscreen:wght@400;700&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;background:#0a0a0a;color:#fff;font-family:'VT323',monospace;overflow:hidden;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:24px}
.status-bar{font-family:'Silkscreen',monospace;font-size:11px;color:#6b7280;letter-spacing:2px;margin-bottom:18px;display:flex;align-items:center;gap:8px}
.status-bar .dot{width:8px;height:8px;border-radius:50%;background:#22c55e;box-shadow:0 0 8px #22c55e;animation:pulse 1.6s ease-in-out infinite}
@keyframes pulse{50%{opacity:.3}}
.controls{display:flex;flex-wrap:wrap;align-items:center;gap:14px 22px;font-family:'Silkscreen',monospace;font-size:11px;letter-spacing:2px;color:#6b7280;margin-bottom:18px}
.controls .ctl-group{display:flex;align-items:center;gap:8px}
.controls select,.controls input,.controls .btn{background:#111;color:#ffc93b;font-family:'Silkscreen',monospace;font-size:11px;letter-spacing:2px;border:1px solid #333;padding:5px 10px;border-radius:4px;text-transform:uppercase}
.controls input{width:80px;text-align:center;color:#f5f5f5}
.controls .btn{cursor:pointer;color:#6b7280}
.controls .btn:hover{color:#ffc93b;border-color:#ffc93b}
.board-frame{background:linear-gradient(145deg,#2a2a2a,#0e0e0e);padding:14px;border-radius:14px;box-shadow:0 30px 60px rgba(0,0,0,.7),inset 0 2px 1px rgba(255,255,255,.08),inset 0 -2px 4px rgba(0,0,0,.6);width:min(96vw,1100px);aspect-ratio:16/9;max-height:80vh}
.board{position:relative;width:100%;height:100%;background:#000;border-radius:6px;box-shadow:inset 0 0 40px rgba(0,0,0,.9);display:grid;grid-template-columns:1fr 1.4fr;grid-template-rows:1fr 1fr;padding:28px 36px;gap:20px 36px;overflow:hidden}
.dot-overlay{position:absolute;inset:0;pointer-events:none;background-image:radial-gradient(rgba(255,255,255,.045) 1px,transparent 1.4px);background-size:5px 5px;z-index:2}
.cell{position:relative;z-index:1;display:flex;flex-direction:column;justify-content:center;min-width:0}
.cell-logo{align-items:center;justify-content:center}
#logo-slot{width:100%;height:100%;display:flex;align-items:center;justify-content:center}
#logo-slot img{max-width:90%;max-height:80%;object-fit:contain;image-rendering:pixelated;filter:contrast(1.15) saturate(1.2) drop-shadow(0 0 6px rgba(255,255,255,.15))}
#logo-slot .placeholder{font-size:clamp(60px,9vw,130px);color:#ef4444;text-shadow:0 0 12px rgba(239,68,68,.6)}
.line{font-family:'VT323',monospace;font-size:clamp(28px,4.5vw,56px);line-height:1.05;letter-spacing:2px;text-transform:uppercase;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.red{color:#ff2a2a;text-shadow:0 0 4px rgba(255,42,42,.9),0 0 12px rgba(255,42,42,.5)}
.white{color:#f5f5f5;text-shadow:0 0 4px rgba(255,255,255,.6)}
.yellow{color:#ffc93b;text-shadow:0 0 4px rgba(255,201,59,.9),0 0 14px rgba(255,201,59,.45)}
.cell-name{gap:6px}
.cell-cities{gap:10px}
.cell-cities .line{font-size:clamp(22px,3.4vw,42px)}
.cell-stats{gap:6px;justify-content:center}
.cell-stats .stat{display:flex;align-items:baseline;gap:18px;font-size:clamp(20px,2.8vw,36px);letter-spacing:2px}
.cell-stats .k{color:#ffc93b;min-width:4ch}
.cell-stats .v{color:#f5f5f5;flex:1;text-align:right;font-variant-numeric:tabular-nums}
.line.small{font-size:clamp(18px,2.8vw,36px);opacity:.85}
.line.big{font-size:clamp(34px,5.5vw,64px)}
.board::after{content:'';position:absolute;inset:0;pointer-events:none;background:linear-gradient(rgba(0,0,0,0) 50%,rgba(0,0,0,.18) 50%);background-size:100% 3px;z-index:3;mix-blend-mode:multiply}
@media (max-width:720px){.board{grid-template-columns:1fr;grid-template-rows:auto auto auto auto;padding:20px;gap:14px}.board-frame{aspect-ratio:auto;height:auto}.line{font-size:clamp(22px,7vw,40px)}}
</style></head><body>
<div class="status-bar"><span class="dot"></span><span id="status">LOCATING...</span></div>
<div class="controls">
<span class="ctl-group"><label>ZIP</label><input id="zip-input" type="text" maxlength="5" inputmode="numeric" placeholder="20431"><button id="zip-go" class="btn">GO</button><button id="use-location" class="btn">USE MY LOCATION</button></span>
    <span class="ctl-group">
      <label>AIRPORT</label>
      <input id="apt-input" type="text" maxlength="4" placeholder="DCA">
      <button id="apt-go" class="btn">GO</button>
    </span>
<span class="ctl-group"><label>RADIUS</label><select id="radius"><option value="10">10 KM</option><option value="25">25 KM</option><option value="50">50 KM</option><option value="75" selected>75 KM</option><option value="100">100 KM</option><option value="150">150 KM</option><option value="250">250 KM</option></select></span>
<span class="ctl-group"><label>UNITS</label><button id="units-toggle" class="btn">KM</button></span>
</div>
<div class="board-frame"><div class="board"><div class="dot-overlay"></div>
<div class="cell cell-logo"><div id="logo-slot"><div class="placeholder">PLANE</div></div></div>
<div class="cell cell-name"><div class="line red" id="airline-name">---</div><div class="line white" id="callsign">---</div><div class="line white small" id="aircraft-type">---</div></div>
<div class="cell cell-cities"><div class="line yellow big" id="route-codes">---</div><div class="line yellow" id="origin-city">---</div><div class="line yellow" id="destination-city">---</div></div>
<div class="cell cell-stats"><div class="stat"><span class="k">ALT</span><span class="v" id="stat-alt">-</span></div><div class="stat"><span class="k">SPD</span><span class="v" id="stat-spd">-</span></div><div class="stat"><span class="k">DIST</span><span class="v" id="stat-dist">-</span></div><div class="stat"><span class="k">ETA</span><span class="v" id="stat-eta">-</span></div></div>
</div></div>
<script>
const REFRESH_MS=12000,KM_TO_MI=0.621371;
const statusEl=document.getElementById('status'),logoSlot=document.getElementById('logo-slot');
const radiusEl=document.getElementById('radius'),zipInput=document.getElementById('zip-input');
const zipGo=document.getElementById('zip-go'),useLoc=document.getElementById('use-location'),unitsBtn=document.getElementById('units-toggle');
let userLat=null,userLon=null,timer=null,units='km';
const set=(id,t)=>{document.getElementById(id).textContent=t||'---'};
const setStatus=t=>statusEl.textContent=String(t).toUpperCase();
const fmtDist=km=>units==='mi'?`${(km*KM_TO_MI).toFixed(1)} MI`:`${km.toFixed(1)} KM`;
const LOGO_SOURCES=(iata,icao)=>[iata&&`https://content.airhex.com/content/logos/airlines_${iata}_350_100_r.png`,iata&&`https://pics.avs.io/200/80/${iata}.png`,icao&&`https://content.airhex.com/content/logos/airlines_${icao}_350_100_r.png`].filter(Boolean);
function renderLogo(a){const s=LOGO_SOURCES(a?.iata,a?.icao);if(!s.length){logoSlot.innerHTML='<div class="placeholder">PLANE</div>';return}logoSlot.innerHTML='<div class="placeholder">PLANE</div>';let i=0;const img=new Image();img.alt=a?.iata||a?.icao||'logo';img.onload=()=>{logoSlot.innerHTML='';logoSlot.appendChild(img)};img.onerror=()=>{i++;if(i<s.length)img.src=s[i]};img.src=s[0]}
function formatEta(m){if(m==null)return '-';if(m<60)return `${m}m`;return `${Math.floor(m/60)}h ${String(m%60).padStart(2,'0')}m`}
function clearBoard(msg){logoSlot.innerHTML='<div class="placeholder">PLANE</div>';set('airline-name',msg||'AWAITING');set('callsign','---');set('aircraft-type','---');set('route-codes','---');set('origin-city','---');set('destination-city','---');set('stat-alt','-');set('stat-spd','-');set('stat-dist','-');set('stat-eta','-')}
function renderPlane(p,n){renderLogo(p.airline);set('airline-name',(p.airline?.name||p.airline?.icao||'UNKNOWN').toUpperCase());set('callsign',(p.callsign||p.icao24||'---').toUpperCase());set('aircraft-type',(p.aircraft_icao||'---').toUpperCase());const o=p.origin,d=p.destination,code=c=>c?(c.iata||c.icao||'-'):'-';set('route-codes',`${code(o)}-${code(d)}`);set('origin-city',(o?.city||o?.name||'UNKNOWN ORIGIN').toUpperCase());set('destination-city',(d?.city||d?.name||'UNKNOWN DEST').toUpperCase());set('stat-alt',`${p.altitude_ft.toLocaleString()} FT`);set('stat-spd',`${p.speed_kts} KTS`);set('stat-dist',fmtDist(p.distance_km));set('stat-eta',formatEta(p.eta_minutes));setStatus(`${n} AIRCRAFT - CLOSEST ${fmtDist(p.distance_km)}`)}
async function tick(){if(userLat==null)return;const r=radiusEl.value||75;try{const res=await fetch(`/api/planes?lat=${userLat}&lon=${userLon}&radius=${r}`);const data=await res.json();if(!res.ok){setStatus(data.error||`ERROR ${res.status}`);return}if(data.empty){setStatus(`NO PLANES WITHIN ${fmtDist(data.radius_km)}`);clearBoard('NO PLANES');return}renderPlane(data.plane,data.nearby_count)}catch(e){setStatus('NETWORK ERROR')}}
function startPolling(){if(timer)clearInterval(timer);tick();timer=setInterval(tick,REFRESH_MS)}
function useBrowserLocation(){if(!navigator.geolocation){setStatus('GEOLOCATION UNSUPPORTED');return}setStatus('LOCATING...');navigator.geolocation.getCurrentPosition(p=>{userLat=p.coords.latitude;userLon=p.coords.longitude;setStatus(`WATCHING ${userLat.toFixed(2)}, ${userLon.toFixed(2)}`);startPolling()},e=>setStatus('LOCATION DENIED - TRY ZIP'),{enableHighAccuracy:false,timeout:10000,maximumAge:60000})}
async function useZip(z){z=String(z||'').trim();if(!/^\d{5}$/.test(z)){setStatus('ENTER A 5-DIGIT ZIP');return}setStatus(`LOOKING UP ${z}...`);try{const r=await fetch(`https://api.zippopotam.us/us/${z}`);if(!r.ok){setStatus('ZIP NOT FOUND');return}const d=await r.json();const pl=d.places?.[0];if(!pl){setStatus('ZIP NOT FOUND');return}userLat=parseFloat(pl.latitude);userLon=parseFloat(pl.longitude);setStatus(`WATCHING ${pl['place name'].toUpperCase()} ${z}`);startPolling()}catch(e){setStatus('ZIP LOOKUP FAILED')}}
const aptInput = document.getElementById('apt-input');
const aptGo = document.getElementById('apt-go');
async function useAirport(code) {
  code = String(code||'').trim().toUpperCase();
  if (!/^[A-Z]{3,4}$/.test(code)) { setStatus('ENTER 3 OR 4 LETTER AIRPORT CODE'); return; }
  setStatus(`LOOKING UP ${code}...`);
  try {
    const r = await fetch(`/api/airport/${code}`);
    if (!r.ok) { setStatus('AIRPORT NOT FOUND'); return; }
    const a = await r.json();
    userLat = a.lat; userLon = a.lon;
    setStatus(`WATCHING ${(a.iata||a.icao||code)} ${(a.name||'').toUpperCase()}`);
    startPolling();
  } catch (e) { setStatus('AIRPORT LOOKUP FAILED'); }
}
aptGo.addEventListener('click', () => useAirport(aptInput.value));
aptInput.addEventListener('keydown', e => { if (e.key === 'Enter') useAirport(aptInput.value); });

zipGo.addEventListener('click',()=>useZip(zipInput.value));
zipInput.addEventListener('keydown',e=>{if(e.key==='Enter')useZip(zipInput.value)});
useLoc.addEventListener('click',useBrowserLocation);
radiusEl.addEventListener('change',()=>{if(userLat!=null)tick()});
unitsBtn.addEventListener('click',()=>{units=units==='km'?'mi':'km';unitsBtn.textContent=units.toUpperCase();if(userLat!=null)tick()});
useBrowserLocation();
</script></body></html>"""


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
        aircraft_list = fetch_nearby_aircraft(lat, lon, radius)
    except requests.HTTPError as e:
        code = e.response.status_code if e.response is not None else 502
        return jsonify(error=f"adsb.lol returned HTTP {code}."), 502
    except requests.RequestException as e:
        return jsonify(error=f"Could not reach adsb.lol: {e}"), 502

    airborne = []
    for ac in aircraft_list:
        if not isinstance(ac, dict):
            continue
        if ac.get("lat") is None or ac.get("lon") is None:
            continue
        if ac.get("alt_baro") == "ground":
            continue
        if haversine_km(lat, lon, ac["lat"], ac["lon"]) > radius:
            continue
        airborne.append(ac)

    if not airborne:
        return jsonify(empty=True, nearby_count=0, radius_km=radius)
    airborne.sort(key=lambda a: haversine_km(lat, lon, a["lat"], a["lon"]))
    return jsonify(empty=False, nearby_count=len(airborne), radius_km=radius,
                   plane=build_plane_payload(airborne[0], lat, lon))




def fetch_airport_by_code(code):
    if not code:
        return None
    try:
        r = requests.get(f"https://api.adsbdb.com/v0/airport/{code}",
                         headers={"User-Agent": USER_AGENT}, timeout=HTTP_TIMEOUT)
        if r.status_code != 200:
            return None
        resp = r.json().get("response") or {}
        return resp.get("airport") or resp
    except requests.RequestException:
        return None


@app.route("/api/airport/<code>")
def airport(code):
    a = fetch_airport_by_code(code.upper())
    if not a or a.get("latitude") is None:
        return jsonify(error="Airport not found"), 404
    return jsonify(
        lat=a["latitude"], lon=a["longitude"],
        iata=a.get("iata_code") or "",
        icao=a.get("icao_code") or "",
        name=a.get("name") or "",
        city=a.get("municipality") or "",
    )


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
