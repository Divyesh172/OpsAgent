import os
import json
import gspread
import httpx
import io
from PIL import Image
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from twilio.twiml.messaging_response import MessagingResponse
import google.generativeai as genai
from dotenv import load_dotenv

# 1. Setup & Config
load_dotenv()
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
app = FastAPI()

# SECURITY: Add Session Middleware (Required for OAuth)
# 'secret_key' can be anything for dev
app.add_middleware(SessionMiddleware, secret_key="super-secret-hackathon-key")

templates = Jinja2Templates(directory="templates")

# Credentials from .env
TWILIO_SID = os.getenv("TWILIO_SID")
TWILIO_AUTH = os.getenv("TWILIO_AUTH")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-flash-latest')

# OAuth Configuration
CLIENT_SECRETS_FILE = "client_secret.json"
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive.file'
]
REDIRECT_URI = "http://localhost:8000/callback"

# Global variable to store user credentials (In production, use a database)
USER_CREDS = None

# --- OAUTH ROUTES ---

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/login")
async def login(request: Request):
    # Create the flow using the client secrets file
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, scopes=SCOPES, redirect_uri=REDIRECT_URI
    )
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent'
    )
    request.session['state'] = state
    return RedirectResponse(authorization_url)

@app.get("/callback")
async def callback(request: Request):
    global USER_CREDS

    try:
        state = request.session.get('state')
        flow = Flow.from_client_secrets_file(
            CLIENT_SECRETS_FILE, scopes=SCOPES, state=state, redirect_uri=REDIRECT_URI
        )

        # Exchange code for token
        flow.fetch_token(authorization_response=str(request.url))
        credentials = flow.credentials
        USER_CREDS = credentials

        with open('token.json', 'w') as token:
            token.write(credentials.to_json())

        return templates.TemplateResponse("index.html", {"request": request})

    except Exception as e:
        # If the code was already used, check if we have a valid token anyway
        if os.path.exists('token.json'):
            return templates.TemplateResponse("index.html", {"request": request})
        return HTMLResponse(f"<h1>Login Error</h1><p>{str(e)}</p>")

# --- HELPER: GET SHEET ---
def get_user_sheet():
    global USER_CREDS

    # 1. Load Credentials (Standard OAuth logic)
    if os.path.exists('token.json'):
        USER_CREDS = Credentials.from_authorized_user_file('token.json', SCOPES)
        if USER_CREDS.expired and USER_CREDS.refresh_token:
            from google.auth.transport.requests import Request
            USER_CREDS.refresh(Request())
            with open('token.json', 'w') as token:
                token.write(USER_CREDS.to_json())

    if not USER_CREDS: return None

    client = gspread.authorize(USER_CREDS)
    db_name = "OpsAgent_DB_v1"

    try:
        sheet = client.open(db_name)
        # ADD THIS: Direct link to find the "missing" file
        print(f"🔗 DATABASE FOUND! Access it here: {sheet.url}")
        return sheet
    except gspread.SpreadsheetNotFound:
        print(f"🚀 Creating new database: {db_name}...")
        sheet = client.create(db_name)
        # ADD THIS:
        print(f"✨ NEW DATABASE CREATED! Access it here: {sheet.url}")
        print(f"📍 CURRENT SHEET URL: {sheet.url}")

        # Setup Inventory Tab
        inventory = sheet.get_worksheet(0)
        inventory.update_title("Inventory")
        inventory.append_row(["Item Name", "Quantity", "Cost", "Date", "Alert Status"])

        # Setup Sales Tab
        sheet.add_worksheet(title="Sales", rows="100", cols="20")
        sheet.worksheet("Sales").append_row(["Item Name", "Quantity", "Sold Price"])

        # Setup Ledger Tab
        sheet.add_worksheet(title="Ledger", rows="100", cols="20")
        sheet.worksheet("Ledger").append_row(["Expense Name", "Amount"])

        # Setup Suppliers Tab
        sheet.add_worksheet(title="Suppliers", rows="100", cols="20")
        sheet.worksheet("Suppliers").append_row(["Item Name", "Supplier Name", "Phone Number"])

        print("✅ Database initialized with all tabs!")
        return sheet

# --- WHATSAPP LOGIC (Unchanged but using get_user_sheet) ---

def analyze_intent(user_input, image_data=None):
    # (Keep your existing analyze_intent code EXACTLY as it was)
    # ... [Paste your analyze_intent function here] ...
    # For brevity, I am not repasting the whole function, but YOU MUST include it.
    try:
        if image_data:
            print("📸 Analyzing Image...")
            prompt = """
            You are an automated accountant. Extract JSON:
            1. "action": "ADD_EXPENSE" or "UPDATE_INVENTORY"
            2. "item": Item Name
            3. "amount": Cost
            4. "quantity": 1
            5. "response_msg": Hinglish reply.
            Return ONLY JSON.
            """
            response = model.generate_content([prompt, image_data])
        else:
            print(f"📝 Analyzing Text: {user_input}")
            prompt = f"""
            Analyze Hinglish: "{user_input}"
            Extract JSON: {{ "action": "UPDATE_INVENTORY"|"RECORD_SALE"|"ADD_EXPENSE", "item": str, "quantity": int, "amount": float, "response_msg": str }}
            Return ONLY JSON.
            """
            response = model.generate_content(prompt)

        clean_text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_text)
    except Exception as e:
        print(f"AI Error: {e}")
        return None

@app.post("/whatsapp")
async def reply_whatsapp(request: Request):
    form_data = await request.form()
    body_text = form_data.get("Body", "")
    media_url = form_data.get("MediaUrl0")

    print(f"\n--- New Message: {body_text} ---")

    # 1. Check Sheet Connection
    sheet = get_user_sheet()
    if not sheet:
        print("❌ ERROR: USER_CREDS is empty. Did you login at localhost:8000?")
        return str(MessagingResponse().message("Boss, please login on the website first."))

    # 2. AI Analysis
    image_part = None
    if media_url:
        # (Keep your existing image download code here)
        pass

    data = analyze_intent(body_text, image_part)
    print(f"🤖 AI Parsed Data: {data}")

    if not data:
        print("❌ ERROR: Gemini failed to return valid JSON.")
        return str(MessagingResponse().message("Samajh nahi aaya, please try again."))

    # 3. Sheet Update
    try:
        action = data.get('action')
        print(f"🚀 Attempting Action: {action}")

        if action == "UPDATE_INVENTORY":
            target_sheet = sheet.worksheet("Inventory")
            target_sheet.append_row([data['item'], data['quantity'], data['amount'], "Today", ""])
            print("✅ Successfully wrote to Inventory")

        elif action == "RECORD_SALE":
            target_sheet = sheet.worksheet("Sales")
            target_sheet.append_row([data['item'], data['quantity'], data['amount']])
            print("✅ Successfully wrote to Sales")

        elif action == "ADD_EXPENSE":
            target_sheet = sheet.worksheet("Ledger")
            target_sheet.append_row([data['item'], data['amount']])
            print("✅ Successfully wrote to Ledger")

        return str(MessagingResponse().message(data['response_msg']))

    except Exception as e:
        print(f"❌ DATABASE ERROR: {str(e)}")
        return str(MessagingResponse().message("Sheet update fail ho gaya."))


if __name__ == "__main__":
    import uvicorn
    # NOTE: We run on port 8000 to match Google Console Redirect URI
    uvicorn.run(app, host="127.0.0.1", port=8000)
