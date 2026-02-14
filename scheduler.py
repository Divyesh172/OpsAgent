import time
import gspread
import os
import urllib.parse
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from twilio.rest import Client
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION ---
TWILIO_SID = os.getenv("TWILIO_SID")
TWILIO_AUTH = os.getenv("TWILIO_AUTH")
TWILIO_FROM = "whatsapp:+14155238886"

# CRITICAL: Get target number from Env or default to hardcoded for hackathon
# Best practice: Add TWILIO_TO_NUMBER in your .env file
TWILIO_TO = os.getenv("TWILIO_TO_NUMBER", "whatsapp:+917021539226")

# Check for missing keys to prevent startup crashes
if not TWILIO_SID or not TWILIO_AUTH:
    print("⚠️ WARNING: Twilio credentials missing in .env. Alerts will not be sent.")
    client_twilio = None
else:
    client_twilio = Client(TWILIO_SID, TWILIO_AUTH)

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive.file'
]

def get_sheet():
    """
    Robust sheet retrieval. Re-reads token.json every time to ensure
    it has the latest refresh token from main.py.
    """
    if not os.path.exists('token.json'):
        print("⏳ Munim waiting for login... (token.json not found)")
        return None

    try:
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)

        # Auto-refresh if expired
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            # Optional: Write back to file if you want to sync state,
            # but main.py usually handles the writing.

        client = gspread.authorize(creds)
        # Open by name. If name changes, this line needs update.
        return client.open("OpsAgent_DB_v1")
    except Exception as e:
        print(f"⚠️ Auth Error: {e}")
        return None

def get_supplier_info(sheet, item_name):
    """
    Looks for the supplier of a specific item.
    Returns: (Name, Phone) or (None, None)
    """
    try:
        supp_tab = sheet.worksheet("Suppliers")
        records = supp_tab.get_all_records()

        for row in records:
            # Case insensitive check
            if str(row.get('Item Name', '')).lower().strip() == item_name.lower().strip():
                return row.get('Supplier Name'), str(row.get('Phone Number'))
    except Exception as e:
        print(f"⚠️ Supplier Lookup Error: {e}")
        return None, None
    return None, None

def check_inventory_risks():
    print("🕵️‍♂️ Munim is checking inventory...")
    sheet = get_sheet()
    if not sheet: return

    try:
        inventory_tab = sheet.worksheet("Inventory")
        # Get all values including headers
        rows = inventory_tab.get_all_values()

        # Start from index 1 to skip header
        for i, row in enumerate(rows[1:]):
            # Row index in sheet is i + 2 (1-based index + header skipped)
            row_num = i + 2

            # Safe unpacking
            if len(row) < 2: continue

            item_name = row[0]
            qty_str = row[1]
            alert_status = row[4] if len(row) > 4 else ""

            try:
                qty = int(qty_str)
            except ValueError:
                continue

            # LOGIC: Low Stock Trigger
            if qty < 10 and alert_status != "SENT":
                print(f"🚨 ALERT TRIGGERED: Low stock for {item_name} ({qty} left)")

                if not client_twilio:
                    print("❌ Twilio client not active. Skipping SMS.")
                    continue

                # 1. FIND SUPPLIER
                supp_name, supp_phone = get_supplier_info(sheet, item_name)

                msg_body = f"⚠️ *Low Stock Alert: {item_name}*\nOnly {qty} units left."

                # 2. GENERATE "ONE-CLICK" REORDER LINK
                if supp_name and supp_phone:
                    text_to_send = f"Namaste {supp_name}, please send 50 units of {item_name} urgently."
                    encoded_text = urllib.parse.quote(text_to_send)
                    # Ensure phone number has no spaces/dashes for link
                    clean_phone = supp_phone.replace(" ", "").replace("-", "")
                    wa_link = f"https://wa.me/{clean_phone}?text={encoded_text}"

                    msg_body += f"\n\n👇 *Click to Reorder from {supp_name}:*\n{wa_link}"
                else:
                    msg_body += "\n(No supplier found in database)"

                # 3. SEND ALERT
                try:
                    client_twilio.messages.create(
                        body=msg_body,
                        from_=TWILIO_FROM,
                        to=TWILIO_TO
                    )
                    # Mark as sent to prevent spamming
                    inventory_tab.update_cell(row_num, 5, "SENT")
                    print(f"✅ Alert sent to Owner for {item_name}")
                except Exception as e:
                    print(f"❌ Twilio Send Failed: {e}")

            # RESET LOGIC: If stock goes back up, clear the "SENT" flag
            elif qty >= 10 and alert_status == "SENT":
                inventory_tab.update_cell(row_num, 5, "")
                print(f"🔄 Restock detected for {item_name}. Alert reset.")

    except Exception as e:
        print(f"⚠️ Logic Error in Munim Loop: {e}")

if __name__ == "__main__":
    print("🟢 Scheduler (Munim) Started. Press Ctrl+C to stop.")
    while True:
        try:
            check_inventory_risks()
        except Exception as e:
            # THIS IS THE CRITICAL HACKATHON FIX
            # If the internet dies or API fails, we catch it here, wait, and retry.
            print(f"💥 CRITICAL CRASH PREVENTED: {e}")
            print("🔄 Restarting loop in 60 seconds...")

        # Wait 60 seconds before next check
        time.sleep(60)