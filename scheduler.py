import time
import gspread
import os
import logging
import urllib.parse
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from twilio.rest import Client
from dotenv import load_dotenv
from thefuzz import process  # <--- Added for Fuzzy Matching

# --- 1. CONFIGURATION & SETUP ---

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [MUNIM] - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

load_dotenv()

# Twilio Config
TWILIO_SID = os.getenv("TWILIO_SID")
TWILIO_AUTH = os.getenv("TWILIO_AUTH")
TWILIO_FROM = "whatsapp:+14155238886" # Sandbox Number
TWILIO_TO = os.getenv("TWILIO_TO_NUMBER") # Target Owner Number

# Initialize Twilio Client safely
client_twilio = None
if TWILIO_SID and TWILIO_AUTH:
    try:
        client_twilio = Client(TWILIO_SID, TWILIO_AUTH)
        logger.info("✅ Twilio Client Connected")
    except Exception as e:
        logger.error(f"❌ Twilio Init Failed: {e}")
else:
    logger.warning("⚠️ Twilio credentials missing. SMS alerts will be DISABLED.")

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive.file'
]

# --- 2. ROBUST AUTHENTICATION ---

def get_sheet_client():
    """
    Connects to Google Sheets using the shared token.json.
    Automatically refreshes expired tokens.
    """
    if not os.path.exists('token.json'):
        logger.warning("⏳ Waiting for User Login... (token.json missing)")
        return None

    try:
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)

        # Auto-refresh if expired
        if creds and creds.expired and creds.refresh_token:
            logger.info("🔄 Refreshing expired Google Token...")
            creds.refresh(GoogleRequest())
            # Write back to file to keep Main.py and Dashboard in sync
            with open('token.json', 'w') as token:
                token.write(creds.to_json())

        return gspread.authorize(creds)
    except Exception as e:
        logger.error(f"⚠️ Auth Error: {e}")
        return None

# --- 3. INTELLIGENT SUPPLIER LOOKUP ---

def get_supplier_info(sheet, item_name):
    """
    Uses Fuzzy Matching to find the supplier.
    Example: 'Maggi' will match 'Maggi Noodles' in the supplier list.
    """
    try:
        supp_tab = sheet.worksheet("Suppliers")
        records = supp_tab.get_all_records()

        # Extract all supplier item names for matching
        supplier_items = [str(r.get('Item Name', '')) for r in records]

        # Fuzzy Match: Find best match with score > 80
        match, score = process.extractOne(item_name, supplier_items)

        if score > 80:
            # Find the full record for the matched item
            for row in records:
                if row.get('Item Name') == match:
                    logger.info(f"🔎 Fuzzy Match: '{item_name}' -> '{match}' (Score: {score})")
                    return row.get('Supplier Name'), str(row.get('Phone Number'))

        logger.info(f"🤷‍♂️ No supplier found for '{item_name}'")
        return None, None

    except Exception as e:
        logger.error(f"⚠️ Supplier Lookup Error: {e}")
        return None, None

# --- 4. CORE MONITORING LOOP ---

def check_inventory_risks():
    client = get_sheet_client()
    if not client: return

    try:
        sheet = client.open("OpsAgent_DB_v1")
        inventory_tab = sheet.worksheet("Inventory")

        # Fetch all data (Rows)
        rows = inventory_tab.get_all_values()

        # Skip Header (Row 0)
        # Data structure expected: [Name, Qty, Cost, Date, AlertStatus]
        for i, row in enumerate(rows[1:]):
            row_num = i + 2  # Sheets are 1-indexed + header

            # Safety check for empty rows
            if len(row) < 2: continue

            item_name = row[0]
            qty_str = row[1]

            # Safe Access to Alert Status (Column E / Index 4)
            alert_status = row[4] if len(row) > 4 else ""

            try:
                qty = int(qty_str)
            except ValueError:
                continue # Skip if quantity isn't a number

            # --- LOGIC: LOW STOCK (< 10) ---
            if qty < 10 and alert_status != "SENT":
                logger.warning(f"🚨 LOW STOCK: {item_name} ({qty} left)")

                if not client_twilio:
                    logger.info("Skipping SMS (Twilio not configured).")
                    continue

                # 1. Find Supplier (Fuzzy)
                supp_name, supp_phone = get_supplier_info(sheet, item_name)

                msg_body = f"⚠️ *Low Stock Alert: {item_name}*\nOnly {qty} units left."

                # 2. Generate Reorder Link
                if supp_name and supp_phone:
                    # Construct WhatsApp Click-to-Chat Link
                    text_to_send = f"Namaste {supp_name}, please send 50 units of {item_name}."
                    encoded_text = urllib.parse.quote(text_to_send)
                    clean_phone = supp_phone.replace(" ", "").replace("-", "").strip()

                    wa_link = f"https://wa.me/{clean_phone}?text={encoded_text}"
                    msg_body += f"\n\n👇 *1-Click Reorder from {supp_name}:*\n{wa_link}"
                else:
                    msg_body += "\n(No supplier info found)"

                # 3. Send Alert
                try:
                    if TWILIO_TO:
                        client_twilio.messages.create(
                            body=msg_body,
                            from_=TWILIO_FROM,
                            to=TWILIO_TO
                        )
                        # Mark as SENT to avoid spamming every minute
                        inventory_tab.update_cell(row_num, 5, "SENT")
                        logger.info(f"✅ Alert sent for {item_name}")
                    else:
                        logger.warning("⚠️ TWILIO_TO_NUMBER not set in .env")

                except Exception as e:
                    logger.error(f"❌ Twilio Send Failed: {e}")

            # --- LOGIC: RESET ALERT ---
            # If stock is replenished (>= 10), clear the "SENT" flag so it can alert again later.
            elif qty >= 10 and alert_status == "SENT":
                inventory_tab.update_cell(row_num, 5, "")
                logger.info(f"✅ Restock detected for {item_name}. Alert reset.")

    except gspread.SpreadsheetNotFound:
        logger.warning("📉 Database 'OpsAgent_DB_v1' not found yet.")
    except Exception as e:
        logger.error(f"⚠️ Logic Error in Munim Loop: {e}")

if __name__ == "__main__":
    logger.info("🟢 Munim (Scheduler) Started. Press Ctrl+C to stop.")

    while True:
        try:
            check_inventory_risks()
        except KeyboardInterrupt:
            logger.info("🛑 Munim stopping...")
            break
        except Exception as e:
            logger.critical(f"💥 CRITICAL CRASH: {e}")
            logger.info("🔄 Restarting loop in 60 seconds...")

        # Check every 60 seconds
        time.sleep(60)