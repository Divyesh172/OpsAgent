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

# --- CONFIGURATION ---
warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger("OpsAgent")

load_dotenv()
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'

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
try:
    import google.generativeai as genai
    genai.configure(api_key=GOOGLE_API_KEY)
    def get_best_model():
        try:
            all_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
            priority = ['models/gemini-2.5-flash', 'models/gemini-1.5-flash', 'models/gemini-pro']
            for p in priority:
                if p in all_models: return p
            return all_models[0] if all_models else 'models/gemini-pro'
        except: return 'models/gemini-pro'
    model_name = get_best_model()
    model = genai.GenerativeModel(model_name, generation_config={"response_mime_type": "application/json"})
    logger.info(f"✅ AI Ready: {model_name}")
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
            ws.append_row([resolved_name, qty_change, cost, "Today", ""])
        else:
            return f"Stock Error: '{resolved_name}' not found."

    except Exception as e:
        logger.error(f"Stock Error: {e}")
    return resolved_name

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

    if not state or not redirect_uri:
        return HTMLResponse("Session expired. Login again.")

    try:
        flow = Flow.from_client_secrets_file(CLIENT_SECRETS_FILE, scopes=SCOPES, state=state, redirect_uri=redirect_uri)
        flow.fetch_token(authorization_response=str(request.url))

        session = flow.authorized_session()
        user_info = session.get('https://www.googleapis.com/userinfo/v2/me').json()
        email = user_info['email']

        creds_json = flow.credentials.to_json()
        database.save_user(email, creds_json)

        request.session['user_email'] = email

        # --- INITIALIZE SHEET & SAVE ID (THE FIX) ---
        try:
            client = gspread.authorize(flow.credentials)
            try:
                # Try opening existing
                sheet = client.open("OpsAgent_DB_v1")
            except gspread.SpreadsheetNotFound:
                # Create if new
                sheet = client.create("OpsAgent_DB_v1")
                # Add Header Rows
                sheet.sheet1.update_title("Inventory")
                sheet.sheet1.append_row(["Item Name", "Quantity", "Cost", "Date", "Alert Status"])
                sheet.add_worksheet("Sales", 1000, 10).append_row(["Item Name", "Quantity", "Sold Price", "Date", "Mode", "Party"])
                sheet.add_worksheet("Ledger", 1000, 5).append_row(["Expense Name", "Amount"])
                sheet.add_worksheet("Khata", 1000, 5).append_row(["Customer", "Amount", "Reason", "Date", "Status"])

            # --- SAVE ID TO DB ---
            database.save_sheet_id(email, sheet.id)
            logger.info(f"✅ Saved Sheet ID {sheet.id} for {email}")

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

    html = f"""
    <html>
    <head>
        <title>Connect WhatsApp</title>
        <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@600&display=swap" rel="stylesheet">
        <style>
            body {{ font-family: 'Plus Jakarta Sans', sans-serif; background: #f0f4f2; display: flex; justify-content: center; align-items: center; height: 100vh; }}
            .card {{ background: white; padding: 40px; border-radius: 20px; box-shadow: 0 10px 30px rgba(0,0,0,0.1); text-align: center; max-width: 400px; }}
            input {{ padding: 12px; border: 1px solid #ddd; border-radius: 8px; width: 100%; margin: 20px 0; font-size: 16px; }}
            button {{ background: #25D366; color: white; border: none; padding: 12px 24px; border-radius: 8px; font-weight: 600; cursor: pointer; width: 100%; }}
        </style>
    </head>
    <body>
        <div class="card">
            <h2>📱 Connect WhatsApp</h2>
            <p>Logged in as: <b>{email}</b></p>
            <p>Enter your WhatsApp number:</p>
            <form action="/save_phone" method="post">
                <input type="text" name="phone" placeholder="e.g. +919988776655" required>
                <button type="submit">Link Number</button>
            </form>
        </div>
    </body>
    </html>
    """
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
        dashboard_url = f"http://localhost:8501/?email={email}"

        return HTMLResponse(f"""
        <html>
        <head><title>Success</title></head>
        <body style="font-family: sans-serif; text-align: center; padding: 50px;">
            <h1 style="color: #25D366;">✅ Shop Connected!</h1>
            <p>You can now use WhatsApp to manage your shop.</p>
            <br>
            <a href="{dashboard_url}" style="background: #007bff; color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px; font-weight: bold;">🚀 Open Dashboard</a>
        </body>
        </html>
        """)

    return RedirectResponse("/")

@app.post("/whatsapp")
async def reply_whatsapp(request: Request):
    form = await request.form()
    sender = form.get("From", "").replace("whatsapp:", "")
    body = form.get("Body", "")
    media_url = form.get("MediaUrl0")
    media_type = form.get("MediaContentType0", "")

    user = database.get_user_by_phone(sender)
    if not user:
        return str(MessagingResponse().message("❌ Number not registered. Please Login at our website."))

    creds_json = user['creds_json']
    sheet_id = user['sheet_id'] # GET ID FROM DB

    client = get_user_client(creds_json)
    if not client:
        return str(MessagingResponse().message("⚠️ Session Expired. Please login again."))

    # AI LOGIC
    media_data = None
    if media_url:
        try: media_data = requests.get(media_url, timeout=10).content
        except: pass

    try:
        prompt = """
        Return JSON: {"action": "SALE"|"RESTOCK"|"EXPENSE", "item": "Name", "qty": Int, "price": Float, "party": "Name", "mode": "CASH"|"UPI"|"UDHAR", "reply": "Msg"}
        Rules: "Sold"->SALE, "Bought"->RESTOCK, "Paid"->EXPENSE.
        """
        content = [prompt]
        if body: content.append(f"Msg: {body}")
        if media_data: content.append({"mime_type": media_type or "image/jpeg", "data": media_data})

        response = model.generate_content(content)
        data = json.loads(response.text)

    except:
        return str(MessagingResponse().message("Samajh nahi aaya."))

    try:
        # OPEN BY KEY (ROBUST)
        if sheet_id:
            sheet = client.open_by_key(sheet_id)
        else:
            sheet = client.open("OpsAgent_DB_v1") # Fallback

        action = data.get('action')
        item = data.get('item', 'Item')
        qty = int(data.get('qty', 1))
        price = float(data.get('price', 0))
        party = data.get('party', '')
        mode = data.get('mode', 'CASH')

        if action == "RESTOCK":
            final = update_inventory_stock(sheet, item, qty, price)
            sheet.worksheet("Ledger").append_row([f"Stock: {final}", price])
        elif action == "SALE":
            final = update_inventory_stock(sheet, item, -qty)
            sheet.worksheet("Sales").append_row([final, qty, price, "Today", mode, party])
            if mode == "UDHAR": sheet.worksheet("Khata").append_row([party, price, item, "Today", "Pending"])
        elif action == "EXPENSE":
            sheet.worksheet("Ledger").append_row([item, price])

        return str(MessagingResponse().message(data.get('reply', 'Done!')))

    except Exception as e:
        logger.error(f"Sheet Error: {e}")
        return str(MessagingResponse().message("❌ Database Error."))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="error")