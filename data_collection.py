import requests
import json
import logging
from uagents import Agent, Context, Model, Protocol
from uagents.setup import fund_agent_if_low
from dotenv import load_dotenv
import os
from oauthlib.oauth2 import BackendApplicationClient
from requests_oauthlib import OAuth2Session
import rasterio
import numpy as np
import matplotlib.pyplot as plt
import ee  # Importing Google Earth Engine
import geemap
from PIL import Image as img
from wand.image import Image
from data_sharing import data_sharing_proto, CollectedData
import time
from datetime import datetime, timedelta
# Authenticate Google Earth Engine


load_dotenv()

# Environment variables
OPEN_WEATHER_API_KEY = os.getenv("OPEN_WEATHER_API_KEY")

SERVICE_ACCOUNT_PATH = "C:/Users/amanb/Downloads/fetch/project/amanbawa96-962dbd7e7042.json"
SOILGRIDS_URL = "https://rest.isric.org/soilgrids/v2.0/properties/query"

credentials = ee.ServiceAccountCredentials(None, SERVICE_ACCOUNT_PATH)
ee.Initialize(credentials)

# API Endpoints
GEOCODE_URL = "http://api.openweathermap.org/geo/1.0/direct"
BASE_WEATHER_URL = "https://api.openweathermap.org/data/3.0/onecall"

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Agent setup
data_col_agent = Agent(
    name="data_collection_agent",
    seed="data_collection",
    port = 8001,
    endpoint="http://localhost:8001/submit"
)

fund_agent_if_low(wallet_address=data_col_agent.wallet.address())
logger.info(f"Agent address: {data_col_agent.address}")

# Weather Request and Response Models
class LocationRequest(Model):
    city: str
    state: str = ""
    country: str = ""


class CollectedData(Model):
    data: dict


def get_daily_weather_aggregate(lat, lon, start_date, end_date, api_key, city):
    # Check if data for the given city already exists
    output_filename = f"data_collection_weather_{city}.json"

    if os.path.exists(output_filename):
        logger.info(f"Using existing weather data from {output_filename}")
        with open(output_filename, 'r') as json_file:
            aggregated_weather_data = json.load(json_file)
        return aggregated_weather_data

    # If the file does not exist, make API calls
    logger.info("Fetching weather data from OpenWeather API")
    aggregated_weather_data = []
    current_date = start_date

    day = 1
    while current_date <= end_date:
        url = f"{BASE_WEATHER_URL}/day_summary?lat={lat}&lon={lon}&date={current_date.strftime('%Y-%m-%d')}&appid={api_key}"
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            logger.info(f"Fetching data for day {day}")
            day+= 1
            aggregated_weather_data.append(data)
        else:
            logger.error(f"Failed to retrieve data for {current_date.strftime('%Y-%m-%d')}: {response.status_code}")

        current_date += timedelta(days=1)
        time.sleep(1)  # Sleep for 1 second to ensure we don't exceed rate limits

    # Save data to JSON file for future use
    with open(output_filename, 'w') as json_file:
        json.dump(aggregated_weather_data, json_file, indent=4)
    logger.info(f"Weather data saved to {output_filename}")

    return aggregated_weather_data


def aggregate_weather_data(weather_data):
    # Aggregating temperature, humidity, cloud cover, etc.
    temp_min = min([day['temperature']['min'] for day in weather_data])
    temp_max = max([day['temperature']['max'] for day in weather_data])
    temp_avg = sum([day['temperature']['afternoon'] for day in weather_data]) / len(weather_data)
    humidity_avg = sum([day['humidity']['afternoon'] for day in weather_data]) / len(weather_data)
    total_precipitation = sum([day['precipitation']['total'] for day in weather_data])

    key_events = []
    for day in weather_data:
        if day['temperature']['max'] == temp_max:
            key_events.append(f"Highest temperature recorded on {day['date']} with {temp_max}K")
        if day['precipitation']['total'] > 10:  # Arbitrary threshold for notable rainfall
            key_events.append(f"Notable rainfall of {day['precipitation']['total']}mm on {day['date']}")

    return {
        "temperature": {
            "min": temp_min,
            "max": temp_max,
            "average": temp_avg
        },
        "humidity": {
            "average": humidity_avg
        },
        "total_precipitation": total_precipitation,
        "key_events": key_events
    }

def analyze_soil_data(soil_data):
    """
    Analyzes the soil data and returns a summary with key soil properties.

    Parameters:
    - soil_data: dict, the JSON response from SoilGrids API

    Returns:
    - soil_summary: str, a summary report of the soil properties
    """

    layers = soil_data.get("properties", {}).get("layers", [])
    analysis_results = []
    all_null = True  # Flag to track if all mean values are null

    # Extract and analyze key soil properties
    analysis_results.append(f"At coordinates:{soil_data.get('geometry',{}).get('coordinates')}")
    for layer in layers:
        name = layer.get("name")
        if layer.get("depths") and len(layer["depths"]) > 0:
            depth = layer["depths"][0]  # Assume we're interested in the top layer for simplicity
            mean_value = depth.get("values", {}).get("mean")
            depth_range = depth.get("range", {})

            if mean_value is not None:
                all_null = False  # Found a non-null mean value
                depth_label = depth.get("label", f"{depth_range.get('top_depth', '?')} - {depth_range.get('bottom_depth', '?')} cm")
                analysis_results.append(f"{name.upper()} content at {depth_label}: {mean_value} ({layer['unit_measure']['mapped_units']})")

    # Check if all properties have null means
    if all_null:
        analysis_results.append("No valid soil data found for the provided coordinates.")

    # Generate a summary report
    soil_summary = "; ".join(analysis_results)  # Changed to use "; " instead of newline
    return soil_summary


# Function to get soil data
def get_soil_data(lat, lon):
    coordinate_offsets = [-0.5, 0, 0.5]

    # Iterate through possible offsets to find valid soil data
    for lat_offset in coordinate_offsets:
        for lon_offset in coordinate_offsets:
            adjusted_lat = lat + lat_offset
            adjusted_lon = lon + lon_offset
            url = f"{SOILGRIDS_URL}?lon={adjusted_lon}&lat={adjusted_lat}&property=clay&property=phh2o&property=sand&property=silt&property=soc&depth=0-5cm&depth=0-30cm&value=mean"
            try:
                response = requests.get(url, headers={"accept": "application/json"})
                response.raise_for_status()
                soil_data = response.json()

                # Check if all mean values are null using analyze_soil_data function
                if not analyze_soil_data(soil_data).startswith("No valid soil data"):
                    return soil_data  # Return the soil data if it's valid
            except requests.exceptions.RequestException as e:
                logger.error(f"Failed to fetch soil data for lat={adjusted_lat}, lon={adjusted_lon}: {e}")

    # If all attempts fail, return an error message
    return {"error": "No valid soil data found after retries"}



# Function for reverse geocoding
def reverse_geocode(lat, lon, api_key):
    url = f"http://api.openweathermap.org/geo/1.0/reverse?lat={lat}&lon={lon}&limit=1&appid={api_key}"
    response = requests.get(url)
    if response.status_code == 200 and len(response.json()) > 0:
        return response.json()[0].get("country")
    else:
        return None

def analyze_ndvi_data(ndvi_data):
    """
    Analyzes the NDVI data and returns a structured dictionary with key observations.

    Parameters:
    - ndvi_data: ndarray, a 2D array representing NDVI values in grayscale from the image.

    Returns:
    - ndvi_summary: dict, a summary report of NDVI observations.
    """
    if ndvi_data is None or ndvi_data.size == 0:
        return {
            "summary": "No NDVI data available for analysis."
        }

    # Normalize NDVI values back from grayscale
    ndvi_values = (ndvi_data / 255.0) * 2 - 1  # Rescaling grayscale values (0 to 255) to NDVI range (-1 to 1)
    ndvi_mean = ndvi_values.mean()
    ndvi_max = ndvi_values.max()
    ndvi_min = ndvi_values.min()

    # Determine the general trend in the NDVI values
    ndvi_trend = "stable"
    if ndvi_max - ndvi_min > 0.5:
        ndvi_trend = "fluctuating"
    elif ndvi_mean > 0.4:
        ndvi_trend = "consistently high"

    key_events = []
    if ndvi_max > 0.6:
        key_events.append(f"High vegetation density observed (Max NDVI: {ndvi_max:.2f})")
    if ndvi_min < -0.2:
        key_events.append(f"Low vegetation density or possibly barren land observed (Min NDVI: {ndvi_min:.2f})")

    # Create a structured summary report
    ndvi_summary = {
        "mean_ndvi": round(ndvi_mean, 2),
        "max_ndvi": round(ndvi_max, 2),
        "min_ndvi": round(ndvi_min, 2),
        "trend": ndvi_trend,
        "key_events": key_events if key_events else "No significant events observed."
    }

    return ndvi_summary

def convert_tiff_to_png(input_file, output_file):
    try:
        # Open the TIFF file using Wand and convert it to PNG
        with Image(filename=input_file) as img:
            img.format = 'png'
            img.save(filename=output_file)
        print(f"Successfully converted {input_file} to {output_file}")
    except Exception as e:
        print(f"Error during conversion: {e}")


# Handler for Weather and NDVI Requests
@data_sharing_proto.on_message(model=LocationRequest, replies={CollectedData})
async def handle_data_request(ctx: Context, sender: str, msg: LocationRequest):
    ctx.logger.info(f"Received WeatherRequest for city: {msg.city}")

    # Step 1: Fetch geocode data
    url = f"{GEOCODE_URL}?q={msg.city},{msg.state},{msg.country}&limit=1&appid={OPEN_WEATHER_API_KEY}"
    ctx.logger.info(f"Geocode request URL: {url}")
    try:
        response = requests.get(url)
        response.raise_for_status()
        geocode_data = response.json()

        if geocode_data:
            lat = geocode_data[0]["lat"]
            lon = geocode_data[0]["lon"]
            ctx.logger.info(f"Successfully fetched geocodes: lat={lat}, lon={lon}")

            # Step 2: Fetch weather data

            start_date = datetime(2021, 1, 1)
            end_date = datetime(2021, 12, 31)


            # Get weather data for the year 2021
            weather_data = get_daily_weather_aggregate(lat, lon, start_date, end_date, OPEN_WEATHER_API_KEY, msg.city)

            # Aggregate weather data
            aggregated_weather = aggregate_weather_data(weather_data)

            #Step 3: Fetch NDVI data using Google Earth Engine
            ctx.logger.info("Fetching NDVI data using Google Earth Engine")
            point = ee.Geometry.Point([lon, lat])
            start_date = "2022-10-01"
            end_date = "2022-10-31"
            collection = ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED") \
                .filterBounds(point) \
                .filterDate(start_date, end_date) \
                .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 20))

            # Calculate NDVI
            def calculate_ndvi(image):
                ndvi = image.normalizedDifference(['B8', 'B4']).rename('NDVI')
                return image.addBands(ndvi)

            collection = collection.map(calculate_ndvi)
            ndvi_image = collection.median().select('NDVI')

            # Step 4: Generate download URL for the NDVI GeoTIFF
            geemap.ee_export_image(ndvi_image, filename='ndvi_image.tif', scale=30, region=point, file_per_band=False)

            # Step 5: Download the NDVI GeoTIFF locally
            ndvi_filename = 'ndvi_image.tif'


            ctx.logger.info(f"NDVI data downloaded successfully to {ndvi_filename}")

            convert_tiff_to_png('ndvi_image.tif', 'ndvi_image.png')

            try:
                ndvi_image_png = img.open("ndvi_image.png")
                # Convert image to a numpy array for further processing if needed
                ndvi_data = np.array(ndvi_image_png)

                ndvi_summary = analyze_ndvi_data(ndvi_data)
                print(ndvi_summary)

            except Exception as e:
                ctx.logger.error(f"Failed to load or process NDVI image: {e}")
                ndvi_summary = "NDVI data could not be analyzed due to an error."

            # Step 5: Store the NDVI value in the data response


            soil_data = get_soil_data(lat, lon)

            ctx.logger.info("Successfully fetched soil data")

            soil_summary = analyze_soil_data(soil_data)

            # Combine weather and soil data
            combined_data = {
                "weather_data": aggregated_weather,
                "soil_data": soil_summary
            }
            combined_data["ndvi_data"] = ndvi_summary

            country_code = reverse_geocode(lat, lon, OPEN_WEATHER_API_KEY)
            if country_code:
                combined_data["country_code"] = country_code



            # Write combined data to a JSON file
            output_filename = f"data_collection_{msg.city}.json"
            with open(output_filename, 'w') as json_file:
                json.dump(combined_data, json_file, indent=4)

            ctx.logger.info(f"Combined data saved to {output_filename}")


            # Send weather response data to the requester
            # await ctx.send(sender, CollectedData(data=combined_data))

            try:
                await send_data_to_impact_agent(ctx,combined_data)
            except Exception as e:
                ctx.logger.error(f"Failed to send data to Impact Assessment Agent: {e}")
                
        else:
            ctx.logger.error("No geocode data found for the provided location")
            await ctx.send(sender, CollectedData(data={"error": "No geocode data found"}))
    except requests.exceptions.RequestException as e:
        ctx.logger.error(f"Failed to fetch data: {e}")
        await ctx.send(sender, CollectedData(data={"error": str(e)}))





# Function to trigger sending data to Impact Assessment Agent
async def send_data_to_impact_agent(ctx,data):
    impact_agent_address = "agent1qd55537kkcuvwq0wd5tgwuw2lylul94wju62pa4wzfnwhy65xydekmlzh8x"
    await ctx.send(
        impact_agent_address,
        CollectedData(data=data)
    )
# Include data_sharing_proto in the agent

data_col_agent.include(data_sharing_proto)

if __name__ == "__main__":
    data_col_agent.run()
