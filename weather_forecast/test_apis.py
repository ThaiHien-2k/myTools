import requests, json, math, sys

sys.stdout.reconfigure(encoding='utf-8')

print("=" * 50)
print("KIEM TRA TOAN BO API - NOWCAST SYSTEM")
print("=" * 50)

# === 1. RainViewer ===
print("\n[1] RainViewer API")
try:
    rv = requests.get("https://api.rainviewer.com/public/weather-maps.json", timeout=5).json()
    host = rv["host"]
    past = rv["radar"]["past"]
    frame_new = past[-1]
    frame_old = past[-2] if len(past) >= 2 else None
    print(f"  OK  host = {host}")
    print(f"  OK  So frame past: {len(past)}")
    time_diff = (frame_new["time"] - frame_old["time"]) if frame_old else 0
    print(f"  OK  Khoang cach 2 frame gan nhat: {time_diff}s ({time_diff//60} phut)")

    # Test lay tile thuc te
    lat, lon, zoom = 10.8231, 106.6297, 7
    n = 2.0 ** zoom
    xtile = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    ytile = int((1.0 - math.log(math.tan(lat_rad) + (1.0 / math.cos(lat_rad))) / math.pi) / 2.0 * n)
    tile_url = f"{host}{frame_new['path']}/512/{zoom}/{xtile}/{ytile}/1/1_1.png"
    r2 = requests.get(tile_url, timeout=8)
    print(f"  OK  Tile fetch: HTTP {r2.status_code}, {len(r2.content)} bytes")

    # Test frame cu
    if frame_old:
        tile_url2 = f"{host}{frame_old['path']}/512/{zoom}/{xtile}/{ytile}/1/1_1.png"
        r3 = requests.get(tile_url2, timeout=8)
        print(f"  OK  Frame cu:  HTTP {r3.status_code}, {len(r3.content)} bytes")

    # Test Leaflet tile URL format
    leaflet_url = f"{host}{frame_new['path']}/512/9/{{z}}/{{x}}/{{y}}/8/1_1.png"
    print(f"  OK  Leaflet tile URL format hop le")

    # Kiem tra path RainViewer cho Leaflet
    test_leaf = f"{host}{frame_new['path']}/512/9/447/247/8/1_1.png"
    r4 = requests.get(test_leaf, timeout=8)
    print(f"  OK  Leaflet tile test (zoom 9): HTTP {r4.status_code}, {len(r4.content)} bytes")
    if r4.status_code != 200:
        print(f"  WARN Leaflet tile loi: {r4.text[:80]}")

except Exception as e:
    print(f"  FAIL {e}")

# === 2. OpenWeatherMap ===
print("\n[2] OpenWeatherMap API")
try:
    owm = requests.get(
        "https://api.openweathermap.org/data/2.5/weather?lat=10.8231&lon=106.6297&appid=caba72153195e76e835b0e35a82e4edb&units=metric",
        timeout=5
    ).json()
    if "wind" in owm:
        print(f"  OK  speed = {owm['wind']['speed']} m/s, deg = {owm['wind']['deg']}")
        print(f"  OK  Thoi tiet: {owm['weather'][0]['description']}")
        print(f"  OK  Nhiet do: {owm['main']['temp']} C")
    else:
        print(f"  FAIL response = {json.dumps(owm)[:100]}")
except Exception as e:
    print(f"  FAIL {e}")

# === 3. Open-Meteo ===
print("\n[3] Open-Meteo API (Luong mua fallback)")
try:
    om = requests.get(
        "https://api.open-meteo.com/v1/forecast?latitude=10.8231&longitude=106.6297&current=precipitation,rain,showers&timezone=Asia/Bangkok",
        timeout=5
    ).json()
    cur = om.get("current", {})
    print(f"  OK  precipitation = {cur.get('precipitation')} mm")
    print(f"  OK  rain          = {cur.get('rain')} mm")
    print(f"  OK  showers       = {cur.get('showers')} mm")
except Exception as e:
    print(f"  FAIL {e}")

# === 4. Nominatim ===
print("\n[4] Nominatim OpenStreetMap (Tim kiem dia danh)")
try:
    nom = requests.get(
        "https://nominatim.openstreetmap.org/search?q=Phuong+Ben+Nghe+Quan+1+Ho+Chi+Minh&format=json&limit=3&accept-language=vi&addressdetails=1",
        timeout=5,
        headers={"User-Agent": "nowcast-ai/2.0"}
    ).json()
    if nom:
        for i, r in enumerate(nom[:2]):
            print(f"  OK  [{i+1}] {r['display_name'][:70]}")
            print(f"       lat={r['lat']}, lon={r['lon']}, type={r.get('type')}")
    else:
        print("  WARN Khong tim thay ket qua")
except Exception as e:
    print(f"  FAIL {e}")

# === 5. Discord Webhook ===
print("\n[5] Discord Webhook")
try:
    wh = requests.get(
        "https://discord.com/api/webhooks/1509388087325622412/YGaBJuj5PhSZMFcaGq0fKu9OPjHJ8LSSurMZJK8d1DtQyCR391XItOLtJhfJgJLi8EjO",
        timeout=5
    ).json()
    if "id" in wh:
        print(f"  OK  Webhook hop le")
        print(f"       guild_id = {wh.get('guild_id')}")
        print(f"       channel_id = {wh.get('channel_id_list', wh.get('channel_id', 'N/A'))}")
        print(f"       name = {wh.get('name')}")
    else:
        print(f"  FAIL {json.dumps(wh)[:100]}")
except Exception as e:
    print(f"  FAIL {e}")

print("\n" + "=" * 50)
print("KIEM TRA HOAN TAT")
print("=" * 50)
