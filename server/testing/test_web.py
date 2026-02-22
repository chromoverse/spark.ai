from app.agent.shared.tools.web import search,  scrape
from app.agent.shared.tools.ai import init
import asyncio
import json


# result.data
results_dict = [
    {
      "url": "https://www.weather-atlas.com/en/nepal/janakpur",
      "success": True,
      "title": "Weather today - Janakpur, Nepal",
      "text": "",
      "links": [
        "https://www.weather-atlas.com/en/nepal/janakpur",
        "https://www.weather-atlas.com/en/nepal/janakpur-weather-tomorrow",
        "https://www.weather-atlas.com/en/nepal/janakpur-long-term-weather-forecast",
        "https://www.weather-atlas.com/en/nepal/janakpur-climate",
        "https://www.weather-atlas.com/en/nepal/janakpur-weather-january",
        "https://www.weather-atlas.com/en/nepal/janakpur-weather-february",
        "https://www.weather-atlas.com/en/nepal/janakpur-weather-march",
        "https://www.weather-atlas.com/en/nepal/janakpur-weather-april",
        "https://www.weather-atlas.com/en/nepal/janakpur-weather-may",
        "https://www.weather-atlas.com/en/nepal/janakpur-weather-june",
        "https://www.weather-atlas.com/en/nepal/janakpur-weather-july",
        "https://www.weather-atlas.com/en/nepal/janakpur-weather-august",
        "https://www.weather-atlas.com/en/nepal/janakpur-weather-september",
        "https://www.weather-atlas.com/en/nepal/janakpur-weather-october",
        "https://www.weather-atlas.com/en/nepal/janakpur-weather-november",
        "https://www.weather-atlas.com/en/nepal/janakpur-weather-december",
        "https://www.weather-atlas.com/en/nepal/janakpur#collapse-today",
        "https://www.weather-atlas.com/en/nepal/janakpur#collapse-current",
        "https://www.weather-atlas.com/en/nepal/janakpur#collapse-hourly",
        "https://www.weather-atlas.com/i/contact",
        "https://www.weather-atlas.com/i/about-us#aboutus",
        "https://www.weather-atlas.com/i/about-us#data",
        "https://weather.com/",
        "https://developer.apple.com/weatherkit/data-source-attribution/",
        "https://www.weather-atlas.com/i/about-us#weather",
        "https://www.weather-atlas.com/n",
        "https://www.weather-atlas.com/n/storm-chandra-brings-snow-wind-and-flooding-risk-across-the-uk",
        "https://www.weather-atlas.com/n/cyclone-gezani-devastates-northeastern-madagascar",
        "https://www.weather-atlas.com/n/blocked-weather-pattern-keeps-rain-over-the-united-kingdom",
        "https://www.weather-atlas.com/n/storm-marta-triggers-deadly-floods-in-northern-morocco",
        "https://www.weather-atlas.com/n/storm-leonardo-batters-iberia-with-floods-and-evacuations",
        "https://www.weather-atlas.com/n/tropical-storm-hits-the-philippines-four-killed",
        "https://www.weather-atlas.com/en/nepal/birta",
        "https://www.weather-atlas.com/en/nepal/loharpatti",
        "https://www.weather-atlas.com/en/nepal/mahottari",
        "https://www.weather-atlas.com/en/nepal/dhamaura",
        "https://www.weather-atlas.com/en/nepal/bijalpura",
        "https://www.weather-atlas.com/en/nepal/sripur",
        "https://www.weather-atlas.com/en/nepal/siraha",
        "https://www.weather-atlas.com/en/nepal/lalbhitti",
        "https://www.weather-atlas.com/en/nepal/dhalkebar",
        "https://www.weather-atlas.com/en/nepal/berhampuri",
        "https://www.weather-atlas.com/en/nepal/betauna",
        "https://www.weather-atlas.com/en/nepal/phulparasi",
        "https://www.weather-atlas.com/en/nepal/malangawa",
        "https://www.weather-atlas.com/en/nepal/gurdham",
        "https://www.weather-atlas.com/en/nepal/khutauna",
        "https://www.weather-atlas.com/en/nepal/lahan",
        "https://www.weather-atlas.com/en/nepal/gopalpur",
        "https://www.weather-atlas.com/en/nepal/rasuwa"
      ]
    },
    {
      "url": "https://meteum.ai/weather/en/janakpur",
      "success": True,
      "title": "Weather in Janakpur \u2014 Weather forecast in Janakpur, Janakpur, Nepal",
      "text": "Weather mapWeather in Janakpur(Janakpur, Janakpur, Nepal)Janakpur, current weather: clear. No precipitation expected today. Air temperature +17\u00b0, feels like +17\u00b0. Wind speed 1.4 Meters per second, north-easterly. Pressure 740 millimeters of mercury. Humidity 81%. Sunrise 07:01, Sunset 18:15. This time yesterday +17\u00b0+17\u00b0Feels like +17\u00b0This time yesterday +17\u00b0Yesterday +17\u00b0Clear. No precipitation expected today1.4 m/s, NE74081%Hourly forecast is loadingAir quality forecast125AQIUnhealthy for sensitiveEnjoy your usual outdoor activities. \u0421onsider reducing outdoor activities if you experience any symptoms.3:45 pmAQI\u20141296:45 pmAQI\u20141209:45 pmAQI\u201413812:45 amAQI\u20141513:45 amAQI\u20141476:45 amAQI\u20141429:45 amAQI\u201413512:45 pmAQI\u2014110Monthly forecastWeather forecast on mapsWeather radarWeather  : radar, precipitation and lightning map onlineSnow depthWeather  : snow depth on the mapTemperatureWeather  : temperature map onlineWindWeather  : wind speed and direction on a mapPressureWeather  : atmospheric pressure on a mapWeather articlesWho are the hurricane hunters? Into the eye of the storm: The daring work of hurricane huntersMonthly weatherJanuary+14\u00b0February+18\u00b0March+23\u00b0April+28\u00b0May+30\u00b0June+30\u00b0July+28\u00b0August+28\u00b0September+27\u00b0October+25\u00b0November+20\u00b0December+15\u00b0Access rain map on your phone easierDownload Weather in Janakpur(Janakpur, Janakpur, Nepal)Janakpur, current weather: clear. No precipitation expected today. Air temperature +17\u00b0, feels like +17\u00b0. Wind speed 1.4 Meters per second, north-easterly. Pressure 740 millimeters of mercury. Humidity 81%. Sunrise 07:01, Sunset 18:15. This time yesterday +17\u00b0+17\u00b0Feels like +17\u00b0This time yesterday +17\u00b0Yesterday +17\u00b0Clear. No precipitation expected today1.4 m/s, NE74081%Hourly forecast is loading Janakpur, current weather: clear. No precipitation expected today. Air temperature +17\u00b0, feels like +17\u00b0. Wind speed 1.4 Meters per second, north-easterly. Pressure 740 millimeters of mercury. Humidity 81%. Sunrise 07:01, Sunset 18:15. This time yesterday +17\u00b0+17\u00b0Feels like +17\u00b0This time yesterday +17\u00b0Yesterday +17\u00b0Clear. No precipitation expected today1.4 m/s, NE74081% Janakpur, current weather: clear. No precipitation expected today. Air temperature +17\u00b0, feels like +17\u00b0. Wind speed 1.4 Meters per second, north-easterly. Pressure 740 millimeters of mercury. Humidity 81%. Sunrise 07:01, Sunset 18:15. This time yesterday +17\u00b0 Enjoy your usual outdoor activities. \u0421onsider reducing outdoor activities if you experience any symptoms. Weather forecast on mapsWeather radarWeather  : radar, precipitation and lightning map onlineSnow depthWeather  : snow depth on the mapTemperatureWeather  : temperature map onlineWindWeather  : wind speed and direction on a mapPressureWeather  : atmospheric pressure on a map Weather  : radar, precipitation and lightning map online Weather articlesWho are the hurricane hunters? Into the eye of the storm: The daring work of hurricane huntersMonthly weatherJanuary+14\u00b0February+18\u00b0March+23\u00b0April+28\u00b0May+30\u00b0June+30\u00b0July+28\u00b0August+28\u00b0September+27\u00b0October+25\u00b0November+20\u00b0December+15\u00b0 Weather articlesWho are the hurricane hunters? Into the eye of the storm: The daring work of hurricane hunters Monthly weatherJanuary+14\u00b0February+18\u00b0March+23\u00b0April+28\u00b0May+30\u00b0June+30\u00b0July+28\u00b0August+28\u00b0September+27\u00b0October+25\u00b0November+20\u00b0December+15\u00b0 FAQWhat's the weather like in Janakpur?Weather in Janakpur right now: clear, air temperature +17\u00b0, feels like +17\u00b0. Wind speed and direction is 1.4 m/s, NE, humidity is 81%, atmospheric pressure is 740 mmHg. No precipitation is expected for the next 2 hours. Today: +13\u2060\u2026\u2060+17\u2060\u00b0, clear, no precipitation, light winds at 2\u00a0m\u2060/\u2060s.What's the temperature in Janakpur?Weather in Janakpur right now: air temperature +17\u00b0. Feels like +17\u00b0, clear. The temperature is +19\u00b0 in the morning, +26\u00b0 during the day, +18\u00b0 in the evening, and +14\u00b0 at night.What's the wind speed and direction in Janakpur?The wind speed in Janakpur right now is 1.4 m/s, NE. Wind speed and direction: 2.4 m/s, N in the morning, 2.5 m/s, SW during the day, 1.7 m/s, NE in the evening, and 2.2 m/s, N at night. Atmospheric pressure is 740 - 742 mmHg, humidity is 54 - 80%, which also affects how the weather feels.What's the humidity in Janakpur?The humidity in Janakpur right now is 81%. The humidity level is 70% in the morning, 54% during the day, 78% in the evening, and 80% at night. Weather in Janakpur right now: clear, air temperature +17\u00b0, feels like +17\u00b0. Wind speed and direction is 1.4 m/s, NE, humidity is 81%, atmospheric pressure is 740 mmHg. No precipitation is expected for the next 2 hours. Today: +13\u2060\u2026\u2060+17\u2060\u00b0, clear, no precipitation, light winds at 2\u00a0m\u2060/\u2060s. Weather in Janakpur right now: air temperature +17\u00b0. Feels like +17\u00b0, clear. The temperature is +19\u00b0 in the morning, +26\u00b0 during the day, +18\u00b0 in the evening, and +14\u00b0 at night. The wind speed in Janakpur right now is 1.4 m/s, NE. Wind speed and direction: 2.4 m/s, N in the morning, 2.5 m/s, SW during the day, 1.7 m/s, NE in the evening",
      "links": [
        "https://meteum.ai/weather/en?via=hl",
        "https://meteum.ai/weather/en/janakpur/maps/nowcast?via=mnc",
        "https://meteum.ai/weather/en/janakpur/pollution?via=mppltn",
        "https://meteum.ai/weather/en/janakpur/month?via=mcbot",
        "https://meteum.ai/weather/en/janakpur/maps/nowcast?via=mmapwb",
        "https://meteum.ai/weather/en/janakpur/maps/snow?via=mmapwb",
        "https://meteum.ai/weather/en/janakpur/maps/temperature?via=mmapwb",
        "https://meteum.ai/weather/en/janakpur/maps/wind?via=mmapwb",
        "https://meteum.ai/weather/en/janakpur/maps/pressure?via=mmapwb",
        "https://meteum.ai/weather/en/blog",
        "https://meteum.ai/weather/en/blog/who-are-the-hurricane-hunters",
        "https://meteum.ai/weather/en/janakpur/month/january?via=cnav",
        "https://meteum.ai/weather/en/janakpur/month/february?via=cnav",
        "https://meteum.ai/weather/en/janakpur/month/march?via=cnav",
        "https://meteum.ai/weather/en/janakpur/month/april?via=cnav",
        "https://meteum.ai/weather/en/janakpur/month/may?via=cnav",
        "https://meteum.ai/weather/en/janakpur/month/june?via=cnav",
        "https://meteum.ai/weather/en/janakpur/month/july?via=cnav",
        "https://meteum.ai/weather/en/janakpur/month/august?via=cnav",
        "https://meteum.ai/weather/en/janakpur/month/september?via=cnav",
        "https://meteum.ai/weather/en/janakpur/month/october?via=cnav",
        "https://meteum.ai/weather/en/janakpur/month/november?via=cnav",
        "https://meteum.ai/weather/en/janakpur/month/december?via=cnav",
        "https://meteum.ai/meteum",
        "https://meteum.ai/weather/en/janakpur/details?via=malert",
        "https://meteum.ai/weather/en/janakpur/sources?via=malert",
        "https://meteum.ai/weather/en/janakpur/details/today?via=main",
        "https://meteum.ai/weather/en/janakpur/details/tomorrow?via=main",
        "https://meteum.ai/weather/en/janakpur/details/day-2?via=main",
        "https://meteum.ai/weather/en/janakpur/details/day-3?via=main",
        "https://meteum.ai/weather/en/janakpur/details/day-4?via=main",
        "https://meteum.ai/weather/en/janakpur/details/day-5?via=main",
        "https://meteum.ai/weather/en/janakpur/details/day-6?via=main",
        "https://meteum.ai/weather/en/janakpur/details/day-7?via=main",
        "https://meteum.ai/weather/en/janakpur/details/day-8?via=main",
        "https://meteum.ai/weather/en/janakpur/details/day-9?via=main",
        "https://meteum.ai/weather/en/janakpur/details/today?via=mfrcst",
        "https://meteum.ai/weather/en/janakpur/details/tomorrow?via=mfrcst",
        "https://meteum.ai/weather/en/janakpur/details/day-2?via=mfrcst",
        "https://meteum.ai/weather/en/janakpur/details/day-3?via=mfrcst",
        "https://meteum.ai/weather/en/janakpur/details/day-4?via=mfrcst",
        "https://meteum.ai/weather/en/janakpur/details/day-5?via=mfrcst",
        "https://meteum.ai/weather/en/janakpur/details/day-6?via=mfrcst",
        "https://meteum.ai/weather/en/janakpur/details/day-7?via=mfrcst",
        "https://meteum.ai/weather/en/janakpur/details/day-8?via=mfrcst",
        "https://meteum.ai/weather/en/janakpur/details/day-9?via=mfrcst"
      ]
    },
    {
      "url": "https://www.theweathernetwork.com/en/city/np/pradesh-2/janakpur/hourly",
      "success": True,
      "title": "Janakpur, P2, NP Hourly Forecast - The Weather Network",
      "text": "Janakpur, P2, NP Hourly ForecastJanakpur, P2, NPUpdateda few seconds ago30\u00b022\u00b014\u00b0Temperature17\u00b0Tue10pm16\u00b0Tue11pm16\u00b0Wed12am15\u00b0Wed1am15\u00b0Wed2am14\u00b0Wed3am14\u00b0Wed4am14\u00b0Wed5am14\u00b0Wed6am16\u00b0Wed7am19\u00b0Wed8am23\u00b0Wed9am25\u00b0Wed10am27\u00b0Wed11am28\u00b0Wed12pm29\u00b0Wed1pm29\u00b0Wed2pm28\u00b0Wed3pm27\u00b0Wed4pm24\u00b0Wed5pm22\u00b0Wed6pm20\u00b0Wed7pm19\u00b0Wed8pm19\u00b0Wed9pm18\u00b0Wed10pm17\u00b0Wed11pm17\u00b0Thu12am16\u00b0Thu1am16\u00b0Thu2am15\u00b0Thu3am15\u00b0Thu4am15\u00b0Thu5am14\u00b0Thu6am16\u00b0Thu7am19\u00b0Thu8am22\u00b0Thu9am25\u00b0Thu10am27\u00b0Thu11am28\u00b0Thu12pm29\u00b0Thu1pm29\u00b0Thu2pm29\u00b0Thu3pm27\u00b0Thu4pm24\u00b0Thu5pm23\u00b0Thu6pm22\u00b0Thu7pm21\u00b0Thu8pm20\u00b0Thu9pm20\u00b0Thu10pm20\u00b0Thu11pm20\u00b0Fri12am19\u00b0Fri1am18\u00b0Fri2am17\u00b0Fri3am17\u00b0Fri4am16\u00b0Fri5am16\u00b0Fri6am18\u00b0Fri7am21\u00b0Fri8am24\u00b0Fri9am26\u00b0Fri10am28\u00b0Fri11am29\u00b0Fri12pm30\u00b0Fri1pm30\u00b0Fri2pm29\u00b0Fri3pm28\u00b0Fri4pm25\u00b0Fri5pm23\u00b0Fri6pm22\u00b0Fri7pm20\u00b0Fri8pm19\u00b0Fri9pmTue Feb 1710pm17\u00b0Feels17WindWind GustHumidity6km/hNW9km/h71%P.O.P.0%Clear11pm16\u00b0Feels16P.O.P.0%Wed Feb 1812am16\u00b0Feels16P.O.P.0%1am15\u00b0Feels15P.O.P.0%2am15\u00b0Feels15P.O.P.0%3am14\u00b0Feels14P.O.P.0%4am14\u00b0Feels14P.O.P.0%5am14\u00b0Feels14P.O.P.0%6am14\u00b0Feels14P.O.P.0%7am16\u00b0Feels16P.O.P.0%8am19\u00b0Feels19P.O.P.0%9am23\u00b0Feels23P.O.P.0%10am25\u00b0Feels25P.O.P.0%11am27\u00b0Feels27P.O.P.0%12pm28\u00b0Feels28P.O.P.0%1pm29\u00b0Feels29P.O.P.0%2pm29\u00b0Feels29P.O.P.0%3pm28\u00b0Feels28P.O.P.0%4pm27\u00b0Feels27P.O.P.0%5pm24\u00b0Feels24P.O.P.0%6pm22\u00b0Feels22P.O.P.0%7pm20\u00b0Feels20P.O.P.0%8pm19\u00b0Feels19P.O.P.0%9pm19\u00b0Feels19P.O.P.0%10pm18\u00b0Feels18P.O.P.0%11pm17\u00b0Feels17P.O.P.0%Thu Feb 1912am17\u00b0Feels17P.O.P.0%1am16\u00b0Feels16P.O.P.0%2am16\u00b0Feels16P.O.P.0%3am15\u00b0Feels15P.O.P.0%4am15\u00b0Feels15P.O.P.0%5am15\u00b0Feels15P.O.P.0%6am14\u00b0Feels14P.O.P.0%7am16\u00b0Feels16P.O.P.0%8am19\u00b0Feels19P.O.P.0%9am22\u00b0Feels22P.O.P.0%10am25\u00b0Feels25P.O.P.0%11am27\u00b0Feels27P.O.P.0%12pm28\u00b0Feels28P.O.P.0%1pm29\u00b0Feels29P.O.P.0%2pm29\u00b0Feels29P.O.P.0%3pm29\u00b0Feels29P.O.P.20%4pm27\u00b0Feels27P.O.P.20%5pm24\u00b0Feels24P.O.P.20%6pm23\u00b0Feels23P.O.P.20%7pm22\u00b0Feels22P.O.P.20%8pm21\u00b0Feels21P.O.P.20%9pm20\u00b0Feels20P.O.P.20%10pm20\u00b0Feels20P.O.P.20%11pm20\u00b0Feels20P.O.P.20%Fri Feb 2012am20\u00b0Feels20P.O.P.20%1am19\u00b0Feels19P.O.P.10%2am18\u00b0Feels18P.O.P.0%3am17\u00b0Feels17P.O.P.10%4am17\u00b0Feels17P.O.P.0%5am16\u00b0Feels16P.O.P.0%6am16\u00b0Feels16P.O.P.0%7am18\u00b0Feels18P.O.P.0%8am21\u00b0Feels21P.O.P.0%9am24\u00b0Feels24P.O.P.0%10am26\u00b0Feels26P.O.P.0%11am28\u00b0Feels28P.O.P.0%12pm29\u00b0Feels29P.O.P.0%1pm30\u00b0Feels30P.O.P.0%2pm30\u00b0Feels30P.O.P.0%3pm29\u00b0Feels29P.O.P.0%4pm28\u00b0Feels28P.O.P.0%5pm25\u00b0Feels25P.O.P.0%6pm23\u00b0Feels23P.O.P.0%7pm22\u00b0Feels22P.O.P.0%8pm20\u00b0Feels20P.O.P.0%9pm19\u00b0Feels19P.O.P.0%7 DaysAll 7 days14 DaysAll 14 daysRadar MapSee all mapsContent continues belowContent continues belowContent continues belowWeather for more locationsVacationSchoolsSkiAirportsCottageAttractionsParksGolfCampingBeachesMarineContent continues below",
      "links": [
        "https://www.theweathernetwork.com/en/city/np/pradesh-2/janakpur/7-days",
        "https://www.theweathernetwork.com/en/city/np/pradesh-2/janakpur/14-days",
        "https://www.theweathernetwork.com/en/maps/radar?lat=26.733&lng=85.925&zoom=7",
        "https://www.theweathernetwork.com/en/vacation",
        "https://www.theweathernetwork.com/en/school",
        "https://www.theweathernetwork.com/en/ski",
        "https://www.theweathernetwork.com/en/airport",
        "https://www.theweathernetwork.com/en/cottage",
        "https://www.theweathernetwork.com/en/attraction",
        "https://www.theweathernetwork.com/en/park",
        "https://www.theweathernetwork.com/en/golf",
        "https://www.theweathernetwork.com/en/camping",
        "https://www.theweathernetwork.com/en/beach",
        "https://www.theweathernetwork.com/en/marine",
        "https://www.sportinglife.ca/en-CA/winter-shop/?utm_source=twn&utm_medium=display_dec1_tiles&utm_campaign=the+winter+shop_POI"
      ]
    }
  ]

async def main ():
  query = input("Enter your query: ")

  # fetch web results with selenium
  web_search_tool = search.WebSearchTool()
  result = await web_search_tool.execute({"query": query, "max_results": 3})
  print(json.dumps(result.data, indent=2))

  print(150*"-")
  urls_core = result.data.get("results", [])
  urls = [item['url'] for item in urls_core]
  print("Extracted URLs:", urls)

  # web_scrape
  web_scraper = scrape.WebScrapeTool(max_chars=5000)
  result = await web_scraper._execute({"base_links": urls, "max_results": 3})
  print(json.dumps(result.data, indent=2))

  content = ""
  for item in result.data.get("results", []):
    content += item['text']

  print(100*"-")
  print("content", content)  

  print(150*"-")
  # ai summarize
  ai_summarize_tool = init.AiSummarizeTool()
  result = await ai_summarize_tool.execute({"context": content, "query": query})
  print(json.dumps(result.data, indent=2))


async def main_research():
  query = input("Enter your research query: ")
  
  from app.agent.shared.tools.web.research import WebResearchTool
  
  print(f"Researching: {query}...")
  research_tool = WebResearchTool()
  result = await research_tool._execute({"query": query, "max_results": 3})
  
  print(json.dumps(result.data, indent=2))
  
  if result.success:
      print("\n" + "="*50)
      print("SUMMARY:")
      print(result.data.get("summary"))
      print("\n" + "="*50)
      print("SOURCES:")
      for source in result.data.get("sources", []):
          print(f"- {source.get('title')} ({source.get('url')})")


if __name__ == "__main__":
  while True:
    print("\n1. Legacy Search -> Scrape -> Summarize")
    print("2. Unified Web Research Tool")
    choice = input("Select mode (1/2): ")
    
    if choice == "1":
        asyncio.run(main())
    elif choice == "2":
        asyncio.run(main_research())
    else:
        print("Invalid choice")