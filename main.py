import os
import re
import io
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional

import pytesseract
import uvicorn
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from PIL import Image
from starlette.middleware.sessions import SessionMiddleware

# Google Calendar API imports
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request as GoogleRequest
import pickle

# --- Configuration ---
load_dotenv()

# Load environment variables
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
TENANT_ID = os.getenv("TENANT_ID", "common")
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
REDIRECT_PATH = os.getenv("REDIRECT_PATH", "/auth/callback")
SCOPE = os.getenv("SCOPE", "Calendars.ReadWrite User.Read").split()
SESSION_KEY = os.getenv("SESSION_KEY", "a_super_secret_key")
# Explicitly define the base URL to ensure the redirect_uri is always correct.
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")


# --- App Initialization ---
app = FastAPI()
# MODIFIED: Added samesite='lax' to the session middleware to fix the "state does not match" error.
app.add_middleware(SessionMiddleware, secret_key=SESSION_KEY, same_site='lax')
templates = Jinja2Templates(directory=".") # Assumes index.html is in the same directory

# --- 1. OCR Service Logic ---

def preprocess_image(image_bytes: bytes) -> Image.Image:
    """Preprocesses the image for better OCR results."""
    try:
        image = Image.open(io.BytesIO(image_bytes))
        # Convert to grayscale and increase contrast for better text recognition
        image = image.convert('L')
        return image
    except Exception as e:
        print(f"Error preprocessing image: {e}")
        raise ValueError("Could not process the provided image file.")

def extract_text_from_image(image: Image.Image) -> str:
    """Extracts text from a PIL Image using pytesseract."""
    try:
        # Use Page Segmentation Mode 6 (Assume a single uniform block of text)
        # This can be more effective for tables than the default.
        custom_config = r'--psm 6'
        return pytesseract.image_to_string(image, config=custom_config)
    except pytesseract.TesseractNotFoundError:
        raise RuntimeError(
            "Tesseract is not installed or not in your PATH. "
            "Please install it to use the OCR functionality."
        )
    except Exception as e:
        print(f"Error during OCR extraction: {e}")
        raise ValueError("Failed to extract text from the image.")

# --- 2. Parser Service Logic (MODIFIED) ---

def get_next_weekday_date(day_name: str) -> datetime.date:
    """Calculates the date of the next upcoming weekday."""
    today = datetime.now().date()
    days_of_week = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    try:
        target_day_index = days_of_week.index(day_name.lower())
    except ValueError:
        return today
        
    days_ahead = (target_day_index - today.weekday() + 7) % 7
    if days_ahead == 0: # If today is the target day, schedule for the same day next week
        days_ahead = 7
    return today + timedelta(days=days_ahead)

def parse_time(time_str: str) -> Optional[datetime.time]:
    """Parses time strings like '9:00 AM', '14:30' into a time object."""
    try:
        time_str = time_str.replace(" ", "").upper()
        # Attempt to parse different time formats
        for fmt in ("%I:%M%p", "%H:%M"):
            try:
                return datetime.strptime(time_str, fmt).time()
            except ValueError:
                continue
    except Exception:
        return None
    return None

def parse_timetable_text(text: str) -> List[Dict]:
    crns = re.findall(r'(\d{5})', text, re.MULTILINE)
    print("Extracted CRNs:", crns)
    from pyvt import Timetable
    vt = Timetable()
    events = []
    day_map = {'M': 'Monday', 'T': 'Tuesday', 'W': 'Wednesday', 'R': 'Thursday', 'F': 'Friday', 'S': 'Saturday', 'U': 'Sunday'}
    for crn in crns:
        try:
            section = vt.crn_lookup(crn, open_only=False)
            if section:
                # Handle ARR (Arranged) days
                if 'ARR' in section.days:
                    events.append({
                        "subject": f"{section.code} {section.name}",
                        "location": section.location,
                        "needs_days_input": True,  # Flag for frontend
                        "start_time_str": section.start_time,
                        "end_time_str": section.end_time
                    })
                else:
                    # For each day character, create an event
                    for d in section.days:
                        if d in day_map:
                            event_date = get_next_weekday_date(day_map[d])
                            start_time = parse_time(section.start_time)
                            end_time = parse_time(section.end_time)
                            if start_time and end_time:
                                events.append({
                                    "subject": f"{section.code} {section.name}",
                                    "start_datetime": datetime.combine(event_date, start_time),
                                    "end_datetime": datetime.combine(event_date, end_time),
                                    "location": section.location,
                                    "day": day_map[d]
                                })
        except Exception as e:
            print(f"Error for CRN {crn}: {e}")
    return events




# --- 3. Google Calendar Service Logic ---
SCOPES = ['https://www.googleapis.com/auth/calendar.events']

def get_calendar_service():
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(GoogleRequest())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=8080)
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    service = build('calendar', 'v3', credentials=creds)
    return service

def create_google_event(event: Dict):
    service = get_calendar_service()
    
    # Get the weekday from event's day
    day_map = {'Monday': 0, 'Tuesday': 1, 'Wednesday': 2, 'Thursday': 3, 'Friday': 4, 'Saturday': 5, 'Sunday': 6}
    target_weekday = day_map.get(event.get('day'))
    
    start_dt = event['start_datetime']
    end_dt = event['end_datetime']
    
    # Import pytz for proper timezone handling
    import pytz
    eastern = pytz.timezone('America/New_York')
    
    # Ensure we have timezone-aware datetimes in Eastern timezone
    if start_dt.tzinfo is None:
        start_dt = eastern.localize(start_dt)
    if end_dt.tzinfo is None:
        end_dt = eastern.localize(end_dt)
    
    # If we have a specific day, calculate the next occurrence of that day
    if target_weekday is not None:
        today = datetime.now().date()
        current_weekday = today.weekday()
        days_ahead = (target_weekday - current_weekday) % 7
        if days_ahead == 0:  # If today is the target day, use today
            next_occurrence = today
        else:
            next_occurrence = today + timedelta(days=days_ahead)
        
        # Update the start and end datetime with the correct date
        start_dt = datetime.combine(next_occurrence, start_dt.time()).replace(tzinfo=start_dt.tzinfo)
        end_dt = datetime.combine(next_occurrence, end_dt.time()).replace(tzinfo=end_dt.tzinfo)
    
    # Calculate end date for recurrence (end of semester - December 14, 2025)
    end_of_semester = datetime(2025, 12, 14, 23, 59, 59, tzinfo=timezone.utc)
    end_date_str = end_of_semester.strftime("%Y%m%dT%H%M%SZ")
    
    # Get the day of the week for recurrence (Monday=MO, Tuesday=TU, etc.)
    weekday_codes = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU']
    byday_code = weekday_codes[start_dt.weekday()]

    event_body = {
        'summary': event['subject'],
        'location': event.get('location', ''),
        'start': {
            'dateTime': start_dt.isoformat(),
            'timeZone': 'America/New_York',
        },
        'end': {
            'dateTime': end_dt.isoformat(),
            'timeZone': 'America/New_York',
        },
        'recurrence': [
            f'RRULE:FREQ=WEEKLY;BYDAY={byday_code};UNTIL={end_date_str}'
        ],
        'reminders': {
            'useDefault': False,
            'overrides': [
                {'method': 'popup', 'minutes': 15}
            ]
        }
    }
    
    # Create the event
    created_event = service.events().insert(calendarId='primary', body=event_body).execute()
    return {"status": "success", "id": created_event.get('id')}


# --- FastAPI Endpoints (Google Calendar version) ---

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})



@app.post("/upload")
async def upload_timetable_image(request: Request, file: UploadFile = File(...)):
    if not file.content_type.startswith("image/"):
        return {"error": "File provided is not an image."}
    try:
        image_bytes = await file.read()
        preprocessed_image = preprocess_image(image_bytes)
        extracted_text = extract_text_from_image(preprocessed_image)
        parsed_events = parse_timetable_text(extracted_text)
        if not parsed_events:
            return {
                "error": "Could not parse any events. Try a clearer image or a different format.",
                "raw_text": extracted_text
            }
        return {"events": parsed_events}
    except (ValueError, RuntimeError) as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"An unexpected error occurred: {e}"}


# New endpoint: create events in Google Calendar
from fastapi import Body
@app.post("/create-events")
async def create_events_in_calendar(events: List[Dict] = Body(...)):
    # Deduplicate: Only one event per subject, day, start/end time, location
    unique_events = {}
    for event in events:
        key = (
            event.get('subject'),
            event.get('day'),
            event.get('start_time_str') or str(event.get('start_datetime')),
            event.get('end_time_str') or str(event.get('end_datetime')),
            event.get('location')
        )
        if key not in unique_events:
            unique_events[key] = event

    creation_results = []
    for event in unique_events.values():
        try:
            # Convert string dates to datetime objects if needed
            if isinstance(event.get('start_datetime'), str):
                event['start_datetime'] = datetime.fromisoformat(event['start_datetime'])
            if isinstance(event.get('end_datetime'), str):
                event['end_datetime'] = datetime.fromisoformat(event['end_datetime'])
            
            # Don't add timezone here - let create_google_event handle it properly
            # The datetimes should remain as naive (no timezone) so they can be 
            # properly localized to Eastern time in create_google_event
            
            # Create the recurring event
            if event.get('start_datetime') and event.get('end_datetime'):
                result = create_google_event(event)
                print(f"Created event: {event['subject']} on {event['day']}")  # Debug print
                creation_results.append(result)
        except Exception as e:
            print(f"Error creating event: {str(e)}")  # Debug print
            continue
                
    return {"results": creation_results, "message": f"Created {len(creation_results)} recurring events in Google Calendar."}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

