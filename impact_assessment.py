from uagents import Agent, Context, Protocol, Field, Model
from uagents.setup import fund_agent_if_low
import requests
from data_sharing import data_sharing_proto, CollectedData
from azure.core.credentials import AzureKeyCredential
from azure.ai.textanalytics import TextAnalyticsClient
import xml.etree.ElementTree as ET
from dotenv import load_dotenv
import os
import logging
import json
from ai_engine import UAgentResponse, UAgentResponseType

load_dotenv()
# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

AGENT_MAILBOX_KEY = "5414c62b-6af7-48ff-85cf-81a1aaa2aa50"
# Initialize the Impact Assessment Agent
impact_assessment_agent = Agent(
    name="impact_assessment_agent",
    seed="impact_assessment_seed",
    port = 8002,
    endpoint="http://localhost:8002/submit"
)

fund_agent_if_low(impact_assessment_agent.wallet.address())
# Azure Cognitive Services setup
endpoint = os.getenv("AZURE_LANGUAGE_ENDPOINT")
key = os.getenv("AZURE_LANGUAGE_KEY")
text_analytics_client = TextAnalyticsClient(endpoint=endpoint, credential=AzureKeyCredential(key))

logger.info(f"Agent address: {impact_assessment_agent.address}")

# Weather Request and Response Models
class LocationRequest(Model):
    city: str =
    state: str = ""
    country: str = ""



def get_value(url):
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        if len(data) > 1 and len(data[1]) > 0:
            # Loop through the data to find the most recent value in or before 2021
            for record in sorted(data[1], key=lambda x: x.get("date"), reverse=True):
                year = int(record.get("date"))
                if year <= 2021 and record.get("value") is not None:
                    return record["value"], record["date"], record["countryiso3code"], record["country"]["value"]  # Return the value, year, and country code
    return None, None, None, None


def get_educational_expenditure(country_3_letter_code):
    url = f"https://sdmx.oecd.org/public/rest/data/OECD.EDU.IMEP,DSD_EAG_UOE_FIN@DF_UOE_FIN_INDIC_SOURCE_NATURE,3.0/{country_3_letter_code}.EXP._T.S13.INST_EDU.DIR_EXP.V.XDC.SOURCE?startPeriod=2021&endPeriod=2021"
    logger.info(url)
    # Make the HTTP request
    response = requests.get(url)
    if response.status_code == 200:
        # Parse the XML response
        root = ET.fromstring(response.content)

        # Define the namespaces used in the XML
        namespaces = {
            'message': 'http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message',
            'generic': 'http://www.sdmx.org/resources/sdmxml/schemas/v2_1/data/generic'
        }

        # Extract the ObsValue element
        # Notice the correct usage of namespaces and deep navigation
        obs_value_element = root.find(".//generic:Obs/generic:ObsValue", namespaces)

        # Extract and print the value if it exists
        if obs_value_element is not None:
            expenditure_value = obs_value_element.attrib.get("value")
            if expenditure_value:
                return expenditure_value
            else:
                logger.info("Expenditure value is empty.")
        else:
            logger.info("Expenditure value not found in the XML.")
    else:
        print("Failed to fetch data from the API. Status code:", response.status_code)

    return None

CITY_NAME = "London"
@impact_assessment_agent.on_event("startup")
async def ask_data(ctx:Context):
    ctx.logger.info(f"Asking data")

    location_request = LocationRequest(city=CITY_NAME, state="", country="")

    await ctx.send("agent1qfjd3x4ygc00rgpd67kuzwksh92tgj6m4ajqkn0hn5y6eagt0k4qvx88hnt", location_request)


@data_sharing_proto.on_message(model=CollectedData, replies={})
async def handle_collected_data(ctx: Context, sender: str, msg: CollectedData):
    ctx.logger.info(f"Received collected data from Data Collection Agent")

    # Extract country code from the collected data
    country_code = msg.data.get("country_code", None)
    if not country_code:
        ctx.logger.error("Country code is missing in the collected data.")
        return

    # Perform economic impact assessment
    economic_data = get_economic_educational_data(country_code)
    if economic_data:
        gdp, gdp_year, gdp_country = economic_data.get('GDP')
        poverty_rate, poverty_year = economic_data.get('poverty_rate')
        education_expense = economic_data.get("educational_expenditure")

        # Generate a detailed analysis
        analysis = generate_analysis(msg.data, gdp, gdp_year, poverty_rate, poverty_year, education_expense, gdp_country)

        output_filename = f"impact_analysis_{CITY_NAME}.json"
        with open(output_filename, 'w') as json_file:
            json.dump(analysis, json_file, indent=4)
        logger.info(f"Impact analysis saved to {output_filename}")

        #Send the economic impact response back
        await ctx.send(
            sender,
            EconomicImpactResponse(gdp=gdp, poverty_rate=poverty_rate, educational_expense=education_expense,
                                   analysis=analysis)
        )


# Function to retrieve economic data from the World Bank API
def get_economic_educational_data(country_code):
    # World Bank API for GDP and Poverty data
    gdp_indicator = "NY.GDP.MKTP.CD"  # GDP in current USD
    poverty_indicator = "SI.POV.DDAY"  # Poverty headcount ratio at $2.15 a day (2017 PPP) (% of population)
    base_url = "https://api.worldbank.org/v2/country"

    # Construct URLs for both indicators
    gdp_url = f"{base_url}/{country_code}/indicator/{gdp_indicator}?format=json"
    poverty_url = f"{base_url}/{country_code}/indicator/{poverty_indicator}?format=json"

    # Fetch GDP data
    gdp_value, gdp_year, gdp_iso3count, gdp_country = get_value(gdp_url)
    # Fetch poverty data
    poverty_value, poverty_year, poverty_iso3count, poverty_country = get_value(poverty_url)

    educational_expenditure = get_educational_expenditure(gdp_iso3count)

    return {
        "GDP": (gdp_value, gdp_year, gdp_country),
        "poverty_rate": (poverty_value, poverty_year),
        "educational_expenditure": educational_expenditure
    }


# Function to generate a detailed analysis of all collected data using Azure Text Analytics
def generate_analysis(collected_data, gdp, gdp_year, poverty_rate, poverty_year, educational_expense, country):
    # Create a human-readable summary of collected data
    summary_parts = []

    # Economic Data Summary
    if gdp is not None:
        summary_parts.append(f"GDP of {country} in {gdp_year}: {gdp:.2f} USD.")
    else:
        summary_parts.append(f"GDP data for {country} is unavailable.")

    if poverty_rate is not None:
        summary_parts.append(f"Poverty rate in {country} in {poverty_year}: {poverty_rate}% of the population.")
    else:
        summary_parts.append(f"Poverty rate data for {country} is unavailable.")

    if educational_expense is not None:
        summary_parts.append(f"Educational expenditure of {country}: {educational_expense} USD.")
    else:
        summary_parts.append(f"No education data available for {country}.")

    # NDVI Analysis Summary
    if 'ndvi_data' in collected_data:
        ndvi_data = collected_data['ndvi_data']
        ndvi_summary = f"NDVI Summary: Mean: {ndvi_data.get('mean_ndvi', 'N/A')}, Max: {ndvi_data.get('max_ndvi', 'N/A')}, Min: {ndvi_data.get('min_ndvi', 'N/A')}"
        summary_parts.append(ndvi_summary)

    # Weather Data Analysis Summary
    if 'weather_data' in collected_data:
        weather_data = collected_data['weather_data']
        weather_summary = (
            f"Temperature: Max: {weather_data['temperature']['max']} K, "
            f"Avg: {weather_data['temperature']['average']:.2f} K. "
            f"Average Humidity: {weather_data['humidity']['average']:.2f}%. "
            f"Total Precipitation: {weather_data['total_precipitation']:.2f} mm. "
            f"Notable Weather Events: {', '.join(weather_data['key_events'])}"
        )
        summary_parts.append(weather_summary)

    # Soil Data Analysis Summary
    if 'soil_data' in collected_data:
        soil_summary = collected_data['soil_data']
        summary_parts.append(f"Soil Data: {soil_summary}")

    # Combine summaries
    combined_summary = "\n".join(summary_parts)

    # Analyze the summary with Azure Text Analytics to extract insights
    response = text_analytics_client.extract_key_phrases([combined_summary])
    key_phrases = response[0].key_phrases if not response[0].is_error else []

    # Create a dictionary for a cleaner output
    analysis_dict = {
        "Summary": combined_summary,
        "Key Insights": key_phrases
    }

    return analysis_dict




# Include protocol in the agent
impact_assessment_agent.include(data_sharing_proto)

# Run the agent
if __name__ == "__main__":
    impact_assessment_agent.run()
