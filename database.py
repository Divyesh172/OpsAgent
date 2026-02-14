import sqlite3
import json

DB_NAME = "opsagent.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # Ensure table exists with sheet_id
    c.execute('''
              CREATE TABLE IF NOT EXISTS users (
                                                   email TEXT PRIMARY KEY,
                                                   phone_number TEXT,
                                                   creds_json TEXT,
                                                   sheet_id TEXT
              )
              ''')
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
    clean_phone = phone.replace(" ", "").replace("-", "")
    c.execute("SELECT * FROM users WHERE phone_number=? OR phone_number=?", (clean_phone, "+" + clean_phone))
    return c.fetchone()

def get_user_by_email(email):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE email=?", (email,))
    return c.fetchone()