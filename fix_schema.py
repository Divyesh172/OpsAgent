import gspread
import json
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
import os

# --- CONFIG ---
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive.file'
]

def fix_database_schema():
    print("🔧 Starting Database Schema Repair...")

    # 1. Load Credentials
    if not os.path.exists('token.json'):
        print("❌ Error: 'token.json' not found. Please Login via the Website first.")
        return

    creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleRequest())

    client = gspread.authorize(creds)

    # 2. Open Sheet
    try:
        sheet = client.open("OpsAgent_DB_v1")
        print(f"✅ Connected to Sheet: {sheet.title}")
    except Exception as e:
        print(f"❌ Could not find 'OpsAgent_DB_v1'. Error: {e}")
        return

    # 3. Fix "Staff" Sheet
    try:
        sheet.worksheet("Staff")
        print("✅ 'Staff' tab already exists.")
    except gspread.WorksheetNotFound:
        print("⚠️ 'Staff' tab missing. Creating it...")
        ws = sheet.add_worksheet("Staff", 1000, 6)
        ws.append_row(["Name", "Role", "Shift", "Status", "Phone", "AlertStatus"])
        # Add Sample Data
        ws.append_row(["Raju", "Helper", "Morning", "Present", "+919999999999", ""])
        ws.append_row(["Shyam", "Manager", "Evening", "Absent", "+918888888888", ""])
        print("✨ 'Staff' tab created with sample data.")

    # 4. Fix "Khata" Sheet
    try:
        sheet.worksheet("Khata")
        print("✅ 'Khata' tab already exists.")
    except gspread.WorksheetNotFound:
        print("⚠️ 'Khata' tab missing. Creating it...")
        ws = sheet.add_worksheet("Khata", 1000, 7)
        ws.append_row(["Customer", "Amount", "Reason", "Date", "Status", "Phone", "AlertStatus"])
        print("✨ 'Khata' tab created.")

    print("\n✅ Repair Complete! Restart your system now.")

if __name__ == "__main__":
    fix_database_schema()