import requests
import math

def get_vrain_rainfall(lat, lon):
    """
    Lấy lượng mưa hiện tại từ Open-Meteo (miễn phí, chính xác).
    """
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&current=precipitation,rain,showers"
        f"&timezone=Asia%2FBangkok"
    )
    try:
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            precip = data.get("current", {}).get("precipitation", 0.0)
            return float(precip)
    except Exception as e:
        print(f"⚠️ Lỗi lấy lượng mưa: {e}")
    return 0.0

def get_weather_data(lat, lon):
    """
    Lấy dữ liệu thời tiết đầy đủ từ Open-Meteo:
    - Nhiệt độ hiện tại (°C)
    - Lượng mưa hiện tại (mm)
    - Xác suất mưa trong 1h tới (%)
    - Cảm giác nhiệt (°C)
    - Độ ẩm (%)
    """
    result = {
        "temperature": None,
        "feels_like": None,
        "humidity": None,
        "precipitation": 0.0,
        "precipitation_probability": 0,
        "weather_code": 0,
        "weather_desc": "Không rõ",
    }

    # Bảng mã WMO weather code sang mô tả tiếng Việt
    wmo_desc = {
        0: "Trời quang", 1: "Ít mây", 2: "Mây rải rác", 3: "Nhiều mây",
        45: "Sương mù", 48: "Sương mù đóng băng",
        51: "Mưa phùn nhẹ", 53: "Mưa phùn vừa", 55: "Mưa phùn dày",
        61: "Mưa nhẹ", 63: "Mưa vừa", 65: "Mưa to",
        80: "Mưa rào nhẹ", 81: "Mưa rào vừa", 82: "Mưa rào mạnh",
        95: "Giông bão", 96: "Giông kèm mưa đá nhẹ", 99: "Giông kèm mưa đá to",
    }

    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,apparent_temperature,relative_humidity_2m,"
            f"precipitation,weather_code"
            f"&hourly=precipitation_probability"
            f"&timezone=Asia%2FBangkok"
            f"&forecast_hours=1"
        )
        res = requests.get(url, timeout=6)
        if res.status_code == 200:
            data = res.json()
            cur = data.get("current", {})
            hourly = data.get("hourly", {})

            result["temperature"] = cur.get("temperature_2m")
            result["feels_like"]  = cur.get("apparent_temperature")
            result["humidity"]    = cur.get("relative_humidity_2m")
            result["precipitation"] = float(cur.get("precipitation", 0.0))
            
            wcode = cur.get("weather_code", 0)
            result["weather_code"] = wcode
            result["weather_desc"] = wmo_desc.get(wcode, f"Mã {wcode}")

            # Xác suất mưa giờ tiếp theo
            prob_list = hourly.get("precipitation_probability", [])
            if prob_list:
                result["precipitation_probability"] = int(prob_list[0])

    except Exception as e:
        print(f"⚠️ Lỗi lấy dữ liệu thời tiết: {e}")

    return result

def calculate_cloud_coords(target_lat, target_lon, distance_km, bearing_deg):
    """
    Tính tọa độ (Lat, Lon) của đám mây dựa vào vị trí nhà, khoảng cách và góc.
    """
    R = 6371.0
    lat1 = math.radians(target_lat)
    lon1 = math.radians(target_lon)
    brng = math.radians(bearing_deg)

    lat2 = math.asin(
        math.sin(lat1) * math.cos(distance_km / R) +
        math.cos(lat1) * math.sin(distance_km / R) * math.cos(brng)
    )
    lon2 = lon1 + math.atan2(
        math.sin(brng) * math.sin(distance_km / R) * math.cos(lat1),
        math.cos(distance_km / R) - math.sin(lat1) * math.sin(lat2)
    )

    return math.degrees(lat2), math.degrees(lon2)


if __name__ == "__main__":
    data = get_weather_data(10.8231, 106.6297)
    print(f"Nhiet do: {data['temperature']}°C | Cam giac: {data['feels_like']}°C")
    print(f"Do am: {data['humidity']}% | Mua: {data['precipitation']} mm")
    print(f"Xac suat mua: {data['precipitation_probability']}%")
    print(f"Thoi tiet: {data['weather_desc']}")
