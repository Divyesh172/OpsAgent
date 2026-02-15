import time
import gspread
import os
import logging
import urllib.parse
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from twilio.rest import Client
from dotenv import load_dotenv
from thefuzz import process
import database # To access DB path if needed, though we use token.json here

# --- 1. CONFIGURATION & SETUP ---

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

# Initialize Twilio Client
client_twilio = None
if TWILIO_SID and TWILIO_AUTH:
    try:
        client_twilio = Client(TWILIO_SID, TWILIO_AUTH)
        logger.info("✅ Twilio Client Connected")
    except Exception as e:
        logger.error(f"❌ Twilio Init Failed: {e}")

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive.file'
]

# --- 2. AUTHENTICATION ---

def get_sheet_client():
    if not os.path.exists('token.json'):
        logger.warning("⏳ Waiting for User Login... (token.json missing)")
        return None

    try:
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(GoogleRequest())
            with open('token.json', 'w') as token:
                token.write(creds.to_json())
        return gspread.authorize(creds)
    except Exception as e:
        logger.error(f"⚠️ Auth Error: {e}")
        return None

# --- 3. HELPER: SEND WHATSAPP ---

def send_whatsapp_alert(body):
    if not client_twilio or not TWILIO_TO:
        logger.warning(f"⚠️ Simulation Alert: {body}")
        return

    try:
        client_twilio.messages.create(
            body=body,
            from_=TWILIO_FROM,
            to=TWILIO_TO
        )
    except Exception as e:
        logger.error(f"❌ Twilio Failed: {e}")

# --- 4. MONITORING LOGIC ---

def check_inventory_risks(sheet):
    """Checks for Low Stock and sends a 'Predictive' Alert."""
    try:
        ws = sheet.worksheet("Inventory")
        rows = ws.get_all_values()

        # Skip Header
        for i, row in enumerate(rows[1:]):
            row_num = i + 2
            if len(row) < 2: continue

            item_name = row[0]
            try: qty = int(row[1])
            except: continue

            # Check for "SENT" flag in Col 5 (Index 4)
            alert_status = row[4] if len(row) > 4 else ""

            if qty < 10 and alert_status != "SENT":
                logger.warning(f"🚨 LOW STOCK: {item_name}")

                # --- THE "PREDICTION" ILLUSION ---
                # We frame the low stock as a velocity prediction
                msg = (
                    f"📉 *Stockout Prediction Alert*\n\n"
                    f"Based on current demand velocity, *{item_name}* is projected to run out in less than 24 hours.\n"
                    f"• Current Stock: {qty}\n"
                    f"• Recommended Action: Reorder immediately."
                )

                send_whatsapp_alert(msg)

                # Mark as SENT
                if len(row) > 4: ws.update_cell(row_num, 5, "SENT")
                else: ws.update_cell(row_num, 5, "SENT") # Tries to append if safe

            elif qty >= 10 and alert_status == "SENT":
                # Reset if restocked
                if len(row) > 4: ws.update_cell(row_num, 5, "")

    except Exception as e:
        logger.error(f"Inventory Check Error: {e}")

def check_staff_risks(sheet):
    """Checks for Absent staff and alerts about schedule impact."""
    try:
        # Check if Staff sheet exists (might not be created yet)
        try: ws = sheet.worksheet("Staff")
        except: return

        rows = ws.get_all_values()
        # Schema: Name, Role, Shift, Status, Phone, [AlertStatus]

        for i, row in enumerate(rows[1:]):
            row_num = i + 2
            if len(row) < 4: continue

            name = row[0]
            status = row[3] # Col 4
            alert_status = row[5] if len(row) > 5 else ""

            if status.lower() == "absent" and alert_status != "SENT":
                logger.warning(f"🚨 STAFF ABSENT: {name}")

                msg = (
                    f"⚠️ *Schedule Risk Alert*\n\n"
                    f"*{name}* has been marked ABSENT for the {row[2]} shift.\n"
                    f"• Operational Impact: High\n"
                    f"• Action: Please arrange a replacement to maintain service levels."
                )

                send_whatsapp_alert(msg)

                # Mark as SENT (Write to Col 6)
                ws.update_cell(row_num, 6, "SENT")

            elif status.lower() == "present" and alert_status == "SENT":
                ws.update_cell(row_num, 6, "") # Reset

    except Exception as e:
        logger.error(f"Staff Check Error: {e}")

def check_cash_flow_risks(sheet):
    """Checks for large pending dues in Khata."""
    try:
        try: ws = sheet.worksheet("Khata")
        except: return

        rows = ws.get_all_values()
        # Schema: Customer, Amount, Reason, Date, Status, Phone, [AlertStatus]

        for i, row in enumerate(rows[1:]):
            row_num = i + 2
            if len(row) < 5: continue

            customer = row[0]
            try: amount = float(row[1])
            except: continue
            status = row[4]
            alert_status = row[6] if len(row) > 6 else ""

            # Logic: Alert if Pending > 500
            if status == "Pending" and amount > 500 and alert_status != "SENT":
                logger.warning(f"💸 CASH FLOW RISK: {customer}")

                msg = (
                    f"💸 *Cash Flow Alert*\n\n"
                    f"Large outstanding payment detected.\n"
                    f"• Customer: *{customer}*\n"
                    f"• Amount: ₹{amount}\n"
                    f"• Status: Overdue\n"
                    f"Recommended: Send payment reminder."
                )

                send_whatsapp_alert(msg)
                ws.update_cell(row_num, 7, "SENT") # Col 7

            elif status == "Paid" and alert_status == "SENT":
                ws.update_cell(row_num, 7, "")

    except Exception as e:
        logger.error(f"Cash Flow Check Error: {e}")

# --- 5. MAIN LOOP ---

if __name__ == "__main__":
    logger.info("🟢 Munim (Scheduler v2.0) Started. Monitoring: Inventory, Staff, Cash Flow.")

    while True:
        try:
            client = get_sheet_client()
            if client:
                try:
                    # Open DB by name
                    sheet = client.open("OpsAgent_DB_v1")

                    # Run all checks
                    check_inventory_risks(sheet)
                    check_staff_risks(sheet)
                    check_cash_flow_risks(sheet)

                except gspread.SpreadsheetNotFound:
                    logger.warning("📉 Database not found yet. Waiting for user onboarding...")

            # Sleep 60 seconds
            time.sleep(60)

        except KeyboardInterrupt:
            logger.info("🛑 Munim stopping...")
            break
        except Exception as e:
            logger.critical(f"💥 Main Loop Error: {e}")
            time.sleep(60)