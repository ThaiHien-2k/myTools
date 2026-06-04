import requests
import math

OWM_API_KEY = "caba72153195e76e835b0e35a82e4edb"

def get_vrain_rainfall(lat, lon):
    """
    Lấy lượng mưa hiện tại từ OpenWeatherMap (chính xác hơn cho real-time).
    """
    url = (
        f"https://api.openweathermap.org/data/2.5/weather"
        f"?lat={lat}&lon={lon}&appid={OWM_API_KEY}&units=metric"
    )
    try:
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            # OpenWeatherMap trả về lượng mưa trong 1h qua dưới dạng rain.1h
            rain = data.get("rain", {})
            precip = rain.get("1h", 0.0)
            return float(precip)
    except Exception as e:
        print(f"⚠️ Lỗi lấy lượng mưa (OWM): {e}")
    return 0.0

def get_weather_data(lat, lon):
    """
    Lấy dữ liệu thời tiết đầy đủ từ OpenWeatherMap:
    - Nhiệt độ hiện tại (°C)
    - Lượng mưa hiện tại (mm)
    - Xác suất mưa trong giờ tới (%)
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

    try:
        # Lấy thời tiết hiện tại
        url_curr = (
            f"https://api.openweathermap.org/data/2.5/weather"
            f"?lat={lat}&lon={lon}&appid={OWM_API_KEY}&units=metric&lang=vi"
        )
        res_curr = requests.get(url_curr, timeout=6)
        if res_curr.status_code == 200:
            data_curr = res_curr.json()
            main_data = data_curr.get("main", {})
            
            result["temperature"] = main_data.get("temp")
            result["feels_like"] = main_data.get("feels_like")
            result["humidity"] = main_data.get("humidity")
            
            rain = data_curr.get("rain", {})
            result["precipitation"] = float(rain.get("1h", 0.0))
            
            if "weather" in data_curr and len(data_curr["weather"]) > 0:
                w = data_curr["weather"][0]
                result["weather_code"] = w.get("id", 0)
                result["weather_desc"] = w.get("description", "Không rõ").capitalize()

        # Lấy dự báo để lấy xác suất mưa (pop)
        url_fc = (
            f"https://api.openweathermap.org/data/2.5/forecast"
            f"?lat={lat}&lon={lon}&appid={OWM_API_KEY}&units=metric&cnt=2"
        )
        res_fc = requests.get(url_fc, timeout=6)
        if res_fc.status_code == 200:
            data_fc = res_fc.json()
            if "list" in data_fc and len(data_fc["list"]) > 0:
                pop = data_fc["list"][0].get("pop", 0.0)
                result["precipitation_probability"] = int(pop * 100)

    except Exception as e:
        print(f"⚠️ Lỗi lấy dữ liệu thời tiết (OWM): {e}")

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
