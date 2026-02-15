import sqlite3
import logging
import gspread

# Configure logging to match the rest of the app
logger = logging.getLogger("OpsAgent")

DB_NAME = "opsagent.db"

def init_db():
    """
    Initializes the SQLite database with robust schema handling.
    Now includes 'password_hash' natively to support the Dashboard.
    """
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # 1. Create Core Table
    c.execute('''
              CREATE TABLE IF NOT EXISTS users (
                                                   email TEXT PRIMARY KEY,
                                                   phone_number TEXT,
                                                   creds_json TEXT,
                                                   sheet_id TEXT,
                                                   password_hash TEXT
              )
              ''')

    # 2. Migration Check: Ensure password_hash exists (for older DB versions)
    try:
        c.execute("SELECT password_hash FROM users LIMIT 1")
    except sqlite3.OperationalError:
        logger.info("🔧 Migrating Database: Adding password_hash column...")
        c.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")

    conn.commit()
    conn.close()

def save_user(email, creds_json):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # Check if exists
    c.execute("SELECT * FROM users WHERE email=?", (email,))
    if c.fetchone():
        c.execute("UPDATE users SET creds_json=? WHERE email=?", (creds_json, email))
    else:
        c.execute("INSERT INTO users (email, creds_json) VALUES (?, ?)", (email, creds_json))
    conn.commit()
    conn.close()

def save_sheet_id(email, sheet_id):
    """Saves the specific Sheet ID for the user."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE users SET sheet_id=? WHERE email=?", (sheet_id, email))
    conn.commit()
    conn.close()

def link_phone(email, phone):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE users SET phone_number=? WHERE email=?", (phone, email))
    conn.commit()
    conn.close()

def get_user_by_phone(phone):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    # Handle variations of +91 vs 91 vs raw
    clean_phone = phone.replace(" ", "").replace("-", "")
    c.execute("SELECT * FROM users WHERE phone_number=? OR phone_number=?", (clean_phone, "+" + clean_phone))
    return c.fetchone()

def get_user_by_email(email):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE email=?", (email,))
    return c.fetchone()

# --- NEW: CENTRALIZED SHEET MANAGER ---
def initialize_user_sheet(client, email):
    """
    Creates or Connects to the 'OpsAgent_DB_v1' Google Sheet.
    Defines the schema for Inventory, Staff, and Cash Flow.
    """
    SHEET_NAME = "OpsAgent_DB_v1"

    try:
        # 1. Try to open existing sheet
        try:
            sheet = client.open(SHEET_NAME)
            logger.info(f"✅ Found existing database for {email}")
        except gspread.SpreadsheetNotFound:
            logger.info(f"✨ Creating new database for {email}...")
            sheet = client.create(SHEET_NAME)

            # --- SCHEMA DEFINITION ---

            # A. Inventory Sheet
            sheet.sheet1.update_title("Inventory")
            sheet.sheet1.append_row(["Item Name", "Quantity", "Cost", "Date", "Alert Status"])

            # B. Sales Sheet (Revenue)
            sheet.add_worksheet("Sales", 1000, 10).append_row(
                ["Item Name", "Quantity", "Sold Price", "Date", "Mode", "Party"]
            )

            # C. Ledger Sheet (Expenses)
            sheet.add_worksheet("Ledger", 1000, 5).append_row(
                ["Expense Name", "Amount", "Date", "Category"]
            )

            # D. Khata Sheet (Cash Flow / Payments) - REQUIRED FOR PS02
            sheet.add_worksheet("Khata", 1000, 6).append_row(
                ["Customer", "Amount", "Reason", "Date", "Status", "Phone"]
            )

            # E. Staff Sheet (Scheduling) - REQUIRED FOR PS02
            sheet.add_worksheet("Staff", 1000, 5).append_row(
                ["Name", "Role", "Shift", "Status", "Phone"]
            )

            # F. Sample Data for Staff (So the demo isn't empty)
            sheet.worksheet("Staff").append_row(["Raju", "Helper", "Morning", "Present", "+919999999999"])
            sheet.worksheet("Staff").append_row(["Shyam", "Manager", "Evening", "Absent", "+918888888888"])

        # 2. Save the ID to SQLite so we can open by Key later (Faster/Reliable)
        save_sheet_id(email, sheet.id)
        return sheet

    except Exception as e:
        logger.error(f"❌ Failed to initialize Sheet for {email}: {e}")
        raise e