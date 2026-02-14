import time
import gspread
import os
import urllib.parse  # <--- Added for URL encoding
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from twilio.rest import Client
from dotenv import load_dotenv

load_dotenv()

# Config
TWILIO_SID = os.getenv("TWILIO_SID") # RIGHT
TWILIO_AUTH = os.getenv("TWILIO_AUTH") # RIGHT
TWILIO_FROM = "whatsapp:+14155238886"
TWILIO_TO = "whatsapp:+917021539226" # <--- YOUR NUMBER HERE

client_twilio = Client(TWILIO_SID, TWILIO_AUTH)

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive.file'
]

# scheduler.py fixes

def get_sheet():
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        # FIX: Open by name, not by ID
        return gspread.authorize(creds).open("OpsAgent_DB_v1")
    return None

def get_supplier_info(sheet, item_name):
    """
    Looks for the supplier of a specific item.
    Returns: (Name, Phone) or (None, None)
    """
    try:
        supp_tab = sheet.worksheet("Suppliers")
        records = supp_tab.get_all_records() # Expects headers: Item Name, Supplier Name, Phone Number

        for row in records:
            # Case insensitive check
            if str(row['Item Name']).lower().strip() == item_name.lower().strip():
                return row['Supplier Name'], str(row['Phone Number'])
    except:
        return None, None
    return None, None

def check_inventory_risks():
    print("🕵️‍♂️ Munim is checking inventory...")
    sheet = get_sheet()
    if not sheet: return

    try:
        inventory_tab = sheet.worksheet("Inventory")
        rows = inventory_tab.get_all_values()

        for i, row in enumerate(rows[1:]):
            row_num = i + 2
            item_name = row[0]
            qty_str = row[1]
            alert_status = row[4] if len(row) > 4 else ""

            try:
                qty = int(qty_str)
            except: continue

            if qty < 10 and alert_status != "SENT":
                print(f"⚠️ Low stock: {item_name}")

                # 1. FIND SUPPLIER
                supp_name, supp_phone = get_supplier_info(sheet, item_name)

                msg_body = f"⚠️ *Low Stock Alert: {item_name}*\nOnly {qty} units left."

                # 2. GENERATE "ONE-CLICK" LINK
                if supp_name and supp_phone:
                    # Create pre-filled WhatsApp link
                    text_to_send = f"Namaste {supp_name}, please send 50 units of {item_name} urgently."
                    encoded_text = urllib.parse.quote(text_to_send)
                    wa_link = f"https://wa.me/{supp_phone}?text={encoded_text}"

                    msg_body += f"\n\n👇 *Click to Reorder from {supp_name}:*\n{wa_link}"
                else:
                    msg_body += "\n(No supplier found in database)"

                # 3. SEND ALERT
                client_twilio.messages.create(body=msg_body, from_=TWILIO_FROM, to=TWILIO_TO)

                inventory_tab.update_cell(row_num, 5, "SENT")
                print("✅ Alert with Supplier Link Sent!")

            elif qty >= 10 and alert_status == "SENT":
                inventory_tab.update_cell(row_num, 5, "")

    except Exception as e:
        print(f"Loop Error: {e}")

if __name__ == "__main__":
    while True:
        check_inventory_risks()
        time.sleep(60)