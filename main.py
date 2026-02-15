import os
import json
import logging
import warnings
import requests
import gspread
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
from PIL import Image
from io import BytesIO

# --- CONFIGURATION ---
warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger("OpsAgent")

load_dotenv()
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

# Initialize DB
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
ACTIVE_MODEL_NAME = ""

def setup_ai():
    global model, ACTIVE_MODEL_NAME
    import google.generativeai as genai
    genai.configure(api_key=GOOGLE_API_KEY)

    # THE KITCHEN SINK LIST: Tests every possible valid model name
    candidates = [
        "models/gemini-1.5-flash",
        "models/gemini-1.5-flash-001",     # Specific version
        "models/gemini-1.5-flash-latest",
        "models/gemini-1.5-flash-8b",      # High speed version
        "models/gemini-1.5-pro",
        "models/gemini-1.5-pro-001",       # Specific version
        "models/gemini-1.0-pro",           # Stable previous gen
        "models/gemini-pro",               # Legacy alias
        "models/gemini-pro-vision"         # Legacy vision
    ]

    print("\n🤖 OpsAgent AI Auto-Discovery...")
    for m_name in candidates:
        try:
            print(f"   👉 Testing: {m_name}...", end=" ")
            test_model = genai.GenerativeModel(m_name)
            test_model.generate_content("Hi")

            model = test_model
            ACTIVE_MODEL_NAME = m_name
            print("✅ SUCCESS!")
            logger.info(f"✅ AI System Online using: {m_name}")
            return
        except Exception as e:
            print("❌") # Keep console clean
            pass

    # IF ALL FAIL: Print what IS available to help debug
    print("\n❌ ALL MODELS FAILED. Listing available models for your Key:")
    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                print(f"   - {m.name}")
    except:
        print("   (Could not list models. Check API Key.)")
    logger.critical("❌ AI Init Failed. See console for details.")

# Run setup
setup_ai()

# --- AUTH UTILS ---
CLIENT_SECRETS_FILE = "client_secret.json"
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/userinfo.email',
    'openid'
]

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
    s = s.strip()
    if s.startswith("```json"): s = s[7:]
    elif s.startswith("```"): s = s[3:]
    if s.endswith("```"): s = s[:-3]
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
    try:
        ws = sheet.worksheet("Staff")
        rows = ws.get_all_values()
        for i, row in enumerate(rows[1:]):
            if len(row) > 0 and staff_name.lower() in str(row[0]).lower():
                row_idx = i + 2
                ws.update_cell(row_idx, 4, status)
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

        user_info = session.get('https://www.googleapis.com/userinfo/v2/me').json()
        email = user_info['email']

        creds_json = flow.credentials.to_json()
        database.save_user(email, creds_json)

        with open("token.json", "w") as token_file:
            token_file.write(creds_json)
        logger.info("✅ Saved token.json for Scheduler")

        request.session['user_email'] = email

        try:
            client = gspread.authorize(flow.credentials)
            database.initialize_user_sheet(client, email)
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
        return RedirectResponse(f"http://localhost:8501/?email={email}", status_code=303)
    return RedirectResponse("/", status_code=303)

@app.post("/whatsapp")
async def reply_whatsapp(request: Request):
    form = await request.form()
    sender = form.get("From", "").replace("whatsapp:", "")
    body = form.get("Body", "")

    num_media = int(form.get("NumMedia", 0))
    media_url = form.get("MediaUrl0")

    user = database.get_user_by_phone(sender)
    if not user: return str(MessagingResponse().message("❌ Number not registered. Please Login."))

    client = get_user_client(user['creds_json'])
    if not client: return str(MessagingResponse().message("⚠️ Session Expired. Log in again."))

    try:
        prompt_text = f"""
        Analyze this business message (or image).
        Return STRICT JSON (no markdown): 
        {{
          "action": "SALE" | "RESTOCK" | "EXPENSE" | "STAFF", 
          "item": "Name", "qty": Integer, "price": Float, 
          "party": "Name", "mode": "CASH" | "UPI" | "UDHAR", 
          "staff_name": "Name", "staff_status": "Present" | "Absent",
          "reply": "Friendly confirmation"
        }}
        Context:
        - Message Text: "{body}"
        - "becha udhar pe" -> action: SALE, mode: UDHAR
        - Bill Image -> Extract total items and sum.
        """

        content_inputs = [prompt_text]

        # --- FIX 2: Authenticated Image Download ---
        if num_media > 0 and media_url:
            logger.info(f"📸 Downloading image: {media_url}")
            # Twilio requires Auth to download media
            auth = (os.getenv("TWILIO_SID"), os.getenv("TWILIO_AUTH"))
            img_response = requests.get(media_url, auth=auth)

            if img_response.status_code == 200:
                image_data = Image.open(BytesIO(img_response.content))
                content_inputs.append(image_data)
            else:
                logger.error(f"❌ Failed to download image: {img_response.status_code}")
                return str(MessagingResponse().message("❌ Error downloading image."))
        # -------------------------------------------

        response = model.generate_content(content_inputs)
        cleaned_text = clean_json_string(response.text)
        data = json.loads(cleaned_text)

        qty = int(data.get('qty') or 1)
        price = float(data.get('price') or 0.0)
        item = data.get('item') or "Unknown Item"

        sheet = client.open_by_key(user['sheet_id']) if user['sheet_id'] else client.open("OpsAgent_DB_v1")
        action = data.get('action')

        if action == "SALE":
            final_name = update_inventory_stock(sheet, item, -qty)
            sheet.worksheet("Sales").append_row([
                final_name, qty, price, str(datetime.now().date()), data.get('mode'), data.get('party', 'Walk-in')
            ])
            if data.get('mode') == "UDHAR":
                sheet.worksheet("Khata").append_row([
                    data.get('party', 'Guest'), price, item, str(datetime.now().date()), "Pending", ""
                ])

        elif action == "STAFF":
            msg = update_staff_status(sheet, data.get('staff_name'), data.get('staff_status'))
            return str(MessagingResponse().message(msg))

        elif action == "RESTOCK":
            final_name = update_inventory_stock(sheet, item, qty, price)
            sheet.worksheet("Ledger").append_row([f"Restock: {final_name}", price, str(datetime.now().date()), "Inventory"])

        return str(MessagingResponse().message(data.get('reply', 'Processed!')))

    except Exception as e:
        logger.error(f"Processing Error: {e}")
        return str(MessagingResponse().message(f"❌ Error: {str(e)}"))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)