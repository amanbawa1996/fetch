import requests
import json
from uagents import Agent, Context, Model, Field, Protocol
from uagents.setup import fund_agent_if_low
from dotenv import load_dotenv
import os

load_dotenv()

# SEED_PHRASE = "Data collection agent"
#
# data_collection_agent = Agent(
#     name = "data_collection",
#     seed = SEED_PHRASE
# )

OPEN_WEATHER_API_KEY = os.getenv("OPEN_WEATHER_API_KEY")
print(OPEN_WEATHER_API_KEY)
GEOCODE_URL = "http://api.openweathermap.org/geo/1.0/direct"
BASE_URL = "https://api.openweathermap.org/data/3.0/onecall"

weather_agent = Agent(
    name = "weather_agent",
    seed = "temp_weather_agent",
    port = 8000,
    endpoint=["http://localhost:8000/submit"],
)

fund_agent_if_low(wallet_address= weather_agent.wallet.address())

class GeocodeRequest(Model):
    city : str
    # state: str = ""
    # country: str = ""

class GeocodeResponse(Model):
    lat: float
    lon: float

class WeatherRequest(Model):
    city: str
    state: str = ""
    country: str = ""
    exclude: str = "minutely,hourly"
    units: str = "metric"

class WeatherResponse(Model):
    data: dict

weather_proto = Protocol(name="weather_proto", version=1.0)

@weather_proto.on_query(model = GeocodeRequest, replies = {GeocodeResponse})
async def handle_geocode_request(ctx: Context, sender: str, msg: GeocodeRequest):
    ctx.logger.info("handle_geocode_request invoked")
    ctx.logger.info(f"Received message: {msg}")
    url = f"{GEOCODE_URL}?q={msg.city},{msg.state},{msg.country}&limit=1&appid={OPEN_WEATHER_API_KEY}"
    print(url)
    ctx.logger.info(url)
    try:

        response = requests.get(url)
        response.raise_for_status()
        geocode_data = response.json()

        if geocode_data:
            name = geocode_data[0]["name"]
            ctx.logger.info(f"The name returned is: {name}")
            lat = geocode_data[0]["lat"]
            lon = geocode_data[0]["lon"]
            ctx.logger.info(f"Successfully fetched geocodes for city: {msg.city}, state: {msg.state}, country: {msg.country}.")
            await ctx.send(sender, GeocodeResponse(lat = lat, lon = lon))
        else:
            raise ValueError("No geocode data found for the provided location")
    except (requests.exceptions.RequestException, ValueError) as e:
        # Log error if the API call fails
        ctx.logger.error(f"Failed to fetch geocode data: {e}")
        await ctx.send(sender, GeocodeResponse(lat=0.0, lon=0.0))

@weather_proto.on_message(model = WeatherRequest, replies = WeatherResponse)
async def handle_weather_request(ctx: Context, sender: str, msg: WeatherRequest):
    # First, get the latitude and longitude using the GeocodeRequest
    geocode_msg = GeocodeRequest(city=msg.city, state=msg.state, country=msg.country)
    geocode_response = await ctx.query(sender, geocode_msg, GeocodeResponse)

    if geocode_response.lat == 0.0 and geocode_response.lon == 0.0:
        ctx.logger.error(f"Failed to fetch geocode data for city: {msg.city}.")
        await ctx.send(sender, WeatherResponse(data={"error": "Geocode lookup failed."}))
        return

        # Construct the API request for weather data
    url = f"{BASE_URL}?lat={geocode_response.lat}&lon={geocode_response.lon}&exclude={msg.exclude}&units={msg.units}&appid={API_KEY}"

    try:
        response = requests.get(url)
        response.raise_for_status()
        weather_data = response.json()

        # Log the success and send the response
        ctx.logger.info(
            f"Successfully fetched weather data for coordinates ({geocode_response.lat}, {geocode_response.lon}).")
        await ctx.send(sender, WeatherResponse(data=weather_data))
    except requests.exceptions.RequestException as e:
        # Log error if the API call fails
        ctx.logger.error(f"Failed to fetch weather data: {e}")
        await ctx.send(sender, WeatherResponse(data={"error": str(e)}))

weather_agent.include(weather_proto)


if __name__ == "__main__":
    weather_agent.run()




# from uagents import Agent, Context, Model
# from uagents.setup import fund_agent_if_low
#
# class WeatherRequest(Model):
#     city: str
#
# class WeatherResponse(Model):
#     text: str
#
# weather_agent = Agent(
#     name="weather_agent",
#     seed="weather_agent_seed",
#     port=8001,
#     endpoint="http://localhost:8001/submit"
# )
# fund_agent_if_low(weather_agent.wallet.address())
# print(weather_agent.address)
# @weather_agent.on_query(model=WeatherRequest, replies={WeatherResponse})
# async def handle_weather_request(ctx: Context, sender: str, query: WeatherRequest):
#     # Simulated weather response
#     ctx.logger.info(f"Received WeatherRequest for city: {query.city}")
#     await ctx.send(sender, WeatherResponse(text=f"Weather in {query.city} is sunny."))
#
# if __name__ == "__main__":
#     weather_agent.run()