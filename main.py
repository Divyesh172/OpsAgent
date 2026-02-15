import os
import json
import logging
import warnings
import requests
import gspread
import re
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from twilio.twiml.messaging_response import MessagingResponse
from dotenv import load_dotenv
import secrets
import database
from datetime import datetime

# --- CONFIGURATION ---
warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger("OpsAgent")

load_dotenv()
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

# Initialize DB (Ensures tables and staff/khata logic are ready)
database.init_db()

try:
    from thefuzz import process
except ImportError:
    logger.critical("⚠️ Run: pip install thefuzz")

app = FastAPI()
SECRET_KEY = os.getenv("SESSION_SECRET") or secrets.token_hex(32)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)
templates = Jinja2Templates(directory="templates")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# --- AI SETUP ---
model = None
try:
    import google.generativeai as genai
    genai.configure(api_key=GOOGLE_API_KEY)
    # Using the flash model for low-latency hackathon responses
    model = genai.GenerativeModel('models/gemini-2.5-flash')
    logger.info("✅ Gemini AI Ready")
except:
    logger.error("❌ AI Init Failed")

# --- AUTH UTILS ---
CLIENT_SECRETS_FILE = "client_secret.json"
SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive.file', 'https://www.googleapis.com/auth/userinfo.email']

def get_user_client(creds_json):
    try:
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_authorized_user_info(creds_dict, SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(GoogleRequest())
        return gspread.authorize(creds)
    except Exception as e:
        logger.error(f"Creds Error: {e}")
        return None

# --- HELPER FUNCTIONS ---

def clean_json_string(s):
    """
    Strips markdown formatting from AI output.
    Ensures the string can be parsed by json.loads().
    """
    s = s.strip()
    if s.startswith("```json"):
        s = s[7:]
    elif s.startswith("```"):
        s = s[3:]
    if s.endswith("```"):
        s = s[:-3]
    return s.strip()

def update_inventory_stock(sheet, item_name, qty_change, cost=0):
    resolved_name = item_name
    try:
        ws = sheet.worksheet("Inventory")
        rows = ws.get_all_values()
        existing_items = [str(r[0]) for r in rows[1:] if len(r) > 0]
        best_match, score = process.extractOne(item_name, existing_items) if existing_items else (None, 0)

        row_idx = None
        current_qty = 0

        if best_match and score > 80:
            resolved_name = best_match
            for i, r in enumerate(rows[1:]):
                if len(r) > 0 and str(r[0]) == resolved_name:
                    row_idx = i + 2
                    current_qty = int(r[1]) if len(r) > 1 and r[1] else 0
                    break

        if row_idx:
            new_qty = max(0, current_qty + qty_change)
            ws.update_cell(row_idx, 2, new_qty)
            if qty_change > 0 and cost > 0: ws.update_cell(row_idx, 3, cost)
        elif qty_change > 0:
            ws.append_row([resolved_name, qty_change, cost, str(datetime.now().date()), ""])
    except Exception as e:
        logger.error(f"Stock Error: {e}")
    return resolved_name

def update_staff_status(sheet, staff_name, status):
    """Updates the Staff sheet for PS02 tracking requirements."""
    try:
        ws = sheet.worksheet("Staff")
        rows = ws.get_all_values()
        for i, row in enumerate(rows[1:]):
            if len(row) > 0 and staff_name.lower() in str(row[0]).lower():
                row_idx = i + 2
                ws.update_cell(row_idx, 4, status) # Column 4 is Status
                return f"✅ Marked {row[0]} as {status}"
        return f"⚠️ Staff member '{staff_name}' not found."
    except Exception as e:
        logger.error(f"Staff Update Error: {e}")
        return "❌ Staff Update Failed"

# --- ROUTES ---

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/login")
async def login(request: Request):
    host = request.headers.get("host")
    proto = request.headers.get("x-forwarded-proto", "http")
    redirect_uri = f"{proto}://{host}/callback"
    flow = Flow.from_client_secrets_file(CLIENT_SECRETS_FILE, scopes=SCOPES, redirect_uri=redirect_uri)
    url, state = flow.authorization_url(access_type='offline', prompt='consent')
    request.session['state'] = state
    request.session['redirect_uri'] = redirect_uri
    return RedirectResponse(url)

@app.get("/callback")
async def callback(request: Request):
    state = request.session.get('state')
    redirect_uri = request.session.get('redirect_uri')
    if not state or not redirect_uri: return HTMLResponse("Session expired. Login again.")

    try:
        flow = Flow.from_client_secrets_file(CLIENT_SECRETS_FILE, scopes=SCOPES, state=state, redirect_uri=redirect_uri)
        flow.fetch_token(authorization_response=str(request.url))
        session = flow.authorized_session()

        # --- FIXED LINE HERE ---
        user_info = session.get('https://www.googleapis.com/userinfo/v2/me').json()

        email = user_info['email']
        database.save_user(email, flow.credentials.to_json())
        request.session['user_email'] = email

        try:
            client = gspread.authorize(flow.credentials)
            database.initialize_user_sheet(client, email) # Centralized init
        except Exception as e:
            logger.error(f"Sheet Init Error: {e}")

        return RedirectResponse("/onboard")
    except Exception as e:
        logger.error(f"Callback Error: {e}")
        return HTMLResponse(f"<h1>Login Error</h1><p>{str(e)}</p>")

@app.get("/onboard", response_class=HTMLResponse)
async def onboard_page(request: Request):
    email = request.session.get('user_email')
    if not email: return RedirectResponse("/")
    html = f"""<html><head><title>Connect WhatsApp</title></head>
            <body style="font-family:sans-serif; background:#f0f4f2; display:flex; align-items:center; justify-content:center; height:100vh;">
            <div style="background:white; padding:40px; border-radius:15px; text-align:center; box-shadow:0 4px 12px rgba(0,0,0,0.1);">
            <h2>📱 Connect WhatsApp</h2><p>Logged in as: <b>{email}</b></p>
            <form action="/save_phone" method="post">
                <input type="text" name="phone" placeholder="e.g. +919988776655" required style="padding:12px; width:100%; border:1px solid #ddd; border-radius:8px; margin-bottom:20px;">
                <button type="submit" style="padding:12px 24px; background:#25D366; color:white; border:none; border-radius:8px; cursor:pointer; font-weight:bold; width:100%;">Link Number</button>
            </form></div></body></html>"""
    return html

@app.post("/save_phone")
async def save_phone(request: Request):
    form = await request.form()
    phone = form.get("phone")
    email = request.session.get('user_email')
    if email and phone:
        clean_phone = phone.replace(" ", "").replace("-", "")
        if not clean_phone.startswith("+"):
            clean_phone = "+91" + clean_phone if len(clean_phone) == 10 else "+" + clean_phone
        database.link_phone(email, clean_phone)
        return RedirectResponse(f"http://localhost:8501/?email={email}")
    return RedirectResponse("/")

@app.post("/whatsapp")
async def reply_whatsapp(request: Request):
    form = await request.form()
    sender = form.get("From", "").replace("whatsapp:", "")
    body = form.get("Body", "")

    user = database.get_user_by_phone(sender)
    if not user: return str(MessagingResponse().message("❌ Number not registered. Please Login."))

    client = get_user_client(user['creds_json'])
    if not client: return str(MessagingResponse().message("⚠️ Session Expired. Log in again."))

    try:
        # Prompt designed to capture unstructured Hinglish and return specific structured fields
        prompt = f"""
        Analyze this business message: "{body}"
        Return STRICT JSON (no markdown or code blocks): 
        {{
          "action": "SALE" | "RESTOCK" | "EXPENSE" | "STAFF", 
          "item": "Name of product", 
          "qty": Integer, 
          "price": Float, 
          "party": "Customer/Party Name", 
          "mode": "CASH" | "UPI" | "UDHAR", 
          "staff_name": "Employee Name", 
          "staff_status": "Present" | "Absent",
          "reply": "Friendly confirmation message"
        }}
        Context:
        - "becha udhar pe" -> action: SALE, mode: UDHAR
        - "absent hai" -> action: STAFF, staff_status: Absent
        - "paid" -> action: EXPENSE
        """

        response = model.generate_content(prompt)

        # Clean AI markdown if present and parse
        cleaned_text = clean_json_string(response.text)
        data = json.loads(cleaned_text)

        sheet = client.open_by_key(user['sheet_id']) if user['sheet_id'] else client.open("OpsAgent_DB_v1")
        action = data.get('action')

        if action == "SALE":
            final_name = update_inventory_stock(sheet, data.get('item', 'Item'), -int(data.get('qty', 1)))
            sheet.worksheet("Sales").append_row([
                final_name, data.get('qty'), data.get('price'),
                str(datetime.now().date()), data.get('mode'), data.get('party', 'Walk-in')
            ])
            # For PS02 tracking of credit payments
            if data.get('mode') == "UDHAR":
                sheet.worksheet("Khata").append_row([
                    data.get('party', 'Guest'), data.get('price'), data.get('item'),
                    str(datetime.now().date()), "Pending", ""
                ])

        elif action == "STAFF":
            msg = update_staff_status(sheet, data.get('staff_name'), data.get('staff_status'))
            return str(MessagingResponse().message(msg))

        elif action == "RESTOCK":
            final_name = update_inventory_stock(sheet, data.get('item', 'Item'), int(data.get('qty', 1)), data.get('price'))
            sheet.worksheet("Ledger").append_row([f"Restock: {final_name}", data.get('price'), str(datetime.now().date()), "Inventory"])

        return str(MessagingResponse().message(data.get('reply', 'Processed!')))

    except Exception as e:
        logger.error(f"Processing Error: {e}")
        return str(MessagingResponse().message("Sorry, I couldn't process that. Try: 'Sold 5 Maggi' or 'Raju is absent'"))

if __name__ == "__main__":
    import uvicorn
    # Use standard port 8000 for local dev and Ngrok tunneling
    uvicorn.run(app, host="0.0.0.0", port=8000)