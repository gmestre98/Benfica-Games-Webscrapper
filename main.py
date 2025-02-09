import hashlib
import re
import googleapiclient.errors
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup
from dataclasses import dataclass
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from google.oauth2 import service_account
from googleapiclient.discovery import build

publicCalendarId='bdf16b615040c640df2576cac3b80c3ab60c6076621076ff8035fd0ebed7bcd7@group.calendar.google.com'
woman_emoji = "👩"
man_emoji = "👨"
sports_to_emojis = {
    'Andebol': "🤾‍♂️",
    'Futebol': "⚽",
    'Futsal': "⚽",
    'Basquetebol': "🏀",
    'Voleibol': "🏐",
    'Polo Aquático': "🤽‍♂️",
    'Rugby': "🏉",
    'Hóquei em Patins': "🏒"
}
allowed_sports = [
    'Andebol',
    'Futebol',
    'Futebol Feminino',
    'Futsal',
    'Basquetebol',
    'Voleibol',
    'Polo Aquático',
    'Rugby',
    'Hóquei em Patins'
]

@dataclass
class MyGame:
    date: str
    location: str
    competition: str
    title: str
    sport: str
    channels: list[str]

def getChromedriver():
    chrome_path='/usr/bin/google-chrome'
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.binary_location = chrome_path
    service = Service("/usr/bin/chromedriver")
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver

def readSportsEvents(driver):
    agenda_uri = 'https://www.slbenfica.pt/pt-pt/agora/agenda'
    agenda_item_pattern = re.compile(r'agenda-item-content')
    agenda_item_sport_pattern = re.compile(r'sport')
    agenda_item_location_pattern = re.compile(r'location')
    agenda_item_match_pattern = re.compile(r'match')
    agenda_item_competition_pattern = re.compile(r'competition')
    agenda_item_date_pattern = re.compile(r'startDateForCalendar')
    games_list = []
    driver.get(agenda_uri)
    content = driver.page_source
    soup = BeautifulSoup(content, features="html.parser")
    for element in soup.findAll('div', attrs={'class': agenda_item_pattern}):
        sport = element.find('p', class_=agenda_item_sport_pattern).text.strip()
        if sport not in allowed_sports:
            continue
        location = element.find('p', class_=agenda_item_location_pattern).text.strip()
        title = element.find('p', class_=agenda_item_match_pattern).text.strip()
        if 'vs' not in title: # Events that don't have a vs are not real games
            continue
        competition = element.find('p', class_=agenda_item_competition_pattern).text.strip()
        if 'Sub' in competition: # Skip youth games
            continue
        date = element.find('div', attrs={'class': agenda_item_date_pattern}).text.strip()
        img_tags = element.find_all('img')
        channels = []
        for img_tag in img_tags:
            # Check if the 'src' attribute contains "/CanaisTV/"
            if '/CanaisTV/' in img_tag['src']:
                # Extract the substring after "/CanaisTV/"
                channel = re.search(r'/CanaisTV/(.+)', img_tag['src']).group(1)
                if channel not in channels:
                    channels.append(channel)
        games_list.append(MyGame(date, location, competition, title, sport, channels))
    return games_list

def initializeCalendarService():
    SCOPES = ["https://www.googleapis.com/auth/calendar"]
    SERVICE_ACCOUNT_FILE = 'service_account.json'

    credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    service = build("calendar", "v3", credentials=credentials)
    return service

def constructISODateTime(date, timeDuration):
    input_format = "%m/%d/%Y %H:%M:%S"

    start_time = datetime.strptime(date, input_format)
    start_time = start_time.replace(tzinfo=timezone(offset=timedelta(hours=0)))
    end_time = start_time + timedelta(hours=timeDuration)
    
    iso_format_start = start_time.isoformat()
    iso_format_end = end_time.isoformat()
    
    return iso_format_start, iso_format_end

# This is the current best unique identifier we can obtain
def constructGameId(game):
    values = [game.competition, game.title]
    combined_string = ''.join(map(str, values))
    game_id = hashlib.sha256(combined_string.encode()).hexdigest()
    return game_id

def constructGameTitle(game):
    game_title = game.title + " | " + game.sport
    sport_emoji = sports_to_emojis.get(game.sport, "")
    if " Feminino" in game_title:
        game_title = sport_emoji + woman_emoji + " " + game_title
    elif "(F)" in game.competition or "Feminino" in game.competition:
        game_title = sport_emoji + woman_emoji + " " + game_title + " Feminino"
    else:
        # Default to Masculino since this is the case where more often Benfica doesn't specify the team
        game_title = sport_emoji + man_emoji + " " + game_title + " Masculino"
    return game_title

def constructGameDescription(game):
    if game.channels:
        description = game.competition + "\n\nDisponível nos canais:" 
        for channel in game.channels:
            description = description + "\n- " + channel
        return description
    else:
        return game.competition


def insertGameInCalendar(game, calendarService):
    defaultGameDurationHours = 2
    isoStartTime, isoEndTime = constructISODateTime(game.date, defaultGameDurationHours)
    game_id = constructGameId(game)
    game_title = constructGameTitle(game)
    game_description = constructGameDescription(game)
    event = {
        'summary': game_title,
        'location': game.location,
        'description': game_description,
        'id': game_id,
        'start': {
            'dateTime': isoStartTime,
            'timeZone': 'Europe/London',
        },
        'end': {
            'dateTime': isoEndTime,
            'timeZone': 'Europe/London',
        }
    }
    try:
        event = calendarService.events().insert(calendarId=publicCalendarId, body=event).execute()
        print('Event created: %s' % (event.get('htmlLink')))
    except googleapiclient.errors.HttpError as err:
        if err.resp.status == 409:
            existing_event = calendarService.events().get(calendarId=publicCalendarId, eventId=event['id']).execute()
            if existing_event.get('start', {}).get('dateTime') != isoStartTime:
                calendarService.events().update(calendarId=publicCalendarId, eventId=existing_event.get('id'), body=event).execute()
                print("Event time was updated:")
                print(existing_event.get('htmlLink'))
            else:
                calendarService.events().update(calendarId=publicCalendarId, eventId=existing_event.get('id'), body=event).execute()
                print("Event already exists:")
                print(existing_event.get('htmlLink'))
        else:
            raise err

def main():
    driver = getChromedriver()
    calendarService = initializeCalendarService()
    games_list = readSportsEvents(driver)
    for game in games_list:
            print(game.date)
            print(game.location)
            print(game.competition)
            print(game.title)
            print(game.sport)
            insertGameInCalendar(game, calendarService)

if __name__ == "__main__":
    main()
