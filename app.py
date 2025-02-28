from datetime import datetime, timezone, timedelta
import pytz
import csv
from flask import Flask, request, jsonify, render_template
import requests
import xml.etree.ElementTree as ET

app = Flask(__name__)

# URL kust XML andmed laadida
url = "https://www.ilmateenistus.ee/ilma_andmed/xml/observations.php"

def fetch_weather_data():
    response = requests.get(url)
    if response.status_code != 200:
        return None
    return ET.fromstring(response.content)


def get_text(element, tag):
    node = element.find(tag)
    return node.text if node is not None else None


# Täpsed lubatud jaamad
wanted_stations = {"Tartu-Tõravere", "Tallinn-Harku", "Pärnu"}

# Ilmastikunähtuste kategooriad
snow_sleet = {"Light snow shower", "Moderate snow shower", "Heavy snow shower", "Light sleet", "Moderate sleet",
              "Light snowfall", "Moderate snowfall", "Heavy snowfall"}
rain = {"Light shower", "Moderate shower", "Heavy shower", "Light rain", "Moderate rain", "Heavy rain"}
special = {"Glaze", "Hail", "Thunder"}

# RBF väärtused
rbf_values = {
    "Tallinn": {"Car": 4, "Scooter": 3.5, "Bike": 3},
    "Tartu": {"Car": 3.5, "Scooter": 3, "Bike": 2.5},
    "Pärnu": {"Car": 3, "Scooter": 2.5, "Bike": 2}
}

def save_order_to_csv(order_data, filename="orders.csv"):
    with open(filename, mode="a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file,
                                fieldnames=["city", "vehicle", "rbf", "atef", "wsef", "wpef", "total_fee", "timestamp",
                                            "weather_phenomenon", "weather_category", "air_temperature"])
        if file.tell() == 0:
            writer.writeheader()
        writer.writerow(order_data)


@app.route('/')
def index():
    return render_template("index.html")


@app.route('/calculate_fee', methods=['GET'])
def calculate_fee():
    city = request.args.get('city', '').strip()
    vehicle = request.args.get('vehicle', '').strip()

    if city not in rbf_values or vehicle not in rbf_values[city]:
        return jsonify({"error": "Invalid input. Please enter a valid city and vehicle type."}), 400

    root = fetch_weather_data()
    if root is None:
        return jsonify({"error": "Failed to fetch weather data."}), 500

    timestamp = root.get("timestamp")
    if timestamp:
        utc_dt = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
        tallinn_tz = pytz.timezone("Europe/Tallinn")
        tallinn_dt = utc_dt.astimezone(tallinn_tz)
        formatted_timestamp = tallinn_dt.strftime("%Y-%m-%d %H:%M:%S %Z")
    else:
        formatted_timestamp = "Unknown"

    city_data = next(({
        "Air temperature (°C)": float(get_text(station, "airtemperature") or 0),
        "Wind speed (m/s)": float(get_text(station, "windspeed") or 0),
        "Weather phenomenon": get_text(station, "phenomenon"),
        "Timestamp": formatted_timestamp
    } for station in root.findall("station") if get_text(station, "name").startswith(city)), None)

    if not city_data:
        return jsonify({"error": "Weather data not available for the selected city."}), 404

    air_temp = city_data["Air temperature (°C)"]
    wind_speed = city_data["Wind speed (m/s)"]
    phenomenon = city_data["Weather phenomenon"]

    if phenomenon in snow_sleet:
        category = "Snow or Sleet"
    elif phenomenon in rain:
        category = "Rain"
    elif phenomenon in special:
        return jsonify(
            {"error": "Usage of selected vehicle type is forbidden due to dangerous weather conditions."}), 403
    else:
        category = "Other"

    rbf = rbf_values[city][vehicle]
    atef = 0
    wsef = 0
    wpef = 0

    if vehicle in ["Scooter", "Bike"]:
        if air_temp < -10:
            atef = 1
        elif -10 <= air_temp < 0:
            atef = 0.5

    if vehicle == "Bike":
        if 10 <= wind_speed < 20:
            wsef = 0.5
        elif wind_speed >= 20:
            return jsonify({"error": "Usage of selected vehicle type is forbidden due to high wind speed."}), 403

    if vehicle in ["Scooter", "Bike"]:
        if category == "Snow or Sleet":
            wpef = 1
        elif category == "Rain":
            wpef = 0.5

    total_fee = rbf + atef + wsef + wpef

    # Salvestame tellimuse CSV faili
    order_data = {
        "city": city,
        "vehicle": vehicle,
        "rbf": rbf,
        "atef": atef,
        "wsef": wsef,
        "wpef": wpef,
        "total_fee": total_fee,
        "timestamp": formatted_timestamp,
        "weather_phenomenon": phenomenon,
        "weather_category": category,
        "air_temperature": air_temp
    }
    save_order_to_csv(order_data)

    return jsonify(order_data)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
