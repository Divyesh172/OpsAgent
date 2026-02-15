import streamlit as st
import pandas as pd
import gspread
import plotly.express as px
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
import json
import warnings
from streamlit_autorefresh import st_autorefresh
import database
import sqlite3
import hashlib

# --- CONFIGURATION ---
warnings.simplefilter(action='ignore', category=FutureWarning)
warnings.simplefilter(action='ignore', category=UserWarning)

st.set_page_config(page_title="OpsAgent", page_icon="⚡", layout="wide", initial_sidebar_state="collapsed")
st.markdown("<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}</style>", unsafe_allow_html=True)

# Auto-refresh data every 30 seconds
st_autorefresh(interval=30000, key="datarefresh")

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/userinfo.email'
]

# --- SECURITY UTILS ---

def hash_pass(password):
    """Returns SHA-256 hash of the password."""
    return hashlib.sha256(password.encode()).hexdigest()

def ensure_security_schema():
    """Automatically adds a password column to the DB if it doesn't exist."""
    conn = sqlite3.connect(database.DB_NAME)
    c = conn.cursor()
    try:
        c.execute("SELECT password_hash FROM users LIMIT 1")
    except sqlite3.OperationalError:
        c.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
        conn.commit()
    finally:
        conn.close()

def authenticate(email, password):
    """
    Checks credentials.
    Returns: (Success (bool), Message (str))
    """
    conn = sqlite3.connect(database.DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE email=?", (email,))
    user = c.fetchone()
    conn.close()

    if not user:
        return False, "❌ User not found. Please register via the Main App first."

    stored_hash = user['password_hash']

    # CASE 1: First time user (Registered via Google, but no Dashboard password yet)
    if not stored_hash:
        return False, "SET_PASSWORD"

    # CASE 2: Regular Login
    if stored_hash == hash_pass(password):
        return True, "✅ Login Successful"
    else:
        return False, "❌ Incorrect Password"

def set_initial_password(email, new_password):
    """Sets the password for a user who has none."""
    conn = sqlite3.connect(database.DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE users SET password_hash=? WHERE email=?", (hash_pass(new_password), email))
    conn.commit()
    conn.close()
    return True

# --- INITIALIZATION ---
ensure_security_schema()

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "user_email" not in st.session_state:
    st.session_state.user_email = None
if "setup_mode" not in st.session_state:
    st.session_state.setup_mode = False

# --- LOGIN SCREEN ---
if not st.session_state.authenticated:
    col1, col2, col3 = st.columns([1, 1.5, 1])
    with col2:
        st.title("⚡ OpsAgent Secure Login")
        st.info("Enter your registered email to access the dashboard.")

        email_input = st.text_input("Email Address")
        pass_input = st.text_input("Password", type="password")

        # Primary Login Button
        if st.button("Login"):
            if email_input and pass_input:
                success, msg = authenticate(email_input, pass_input)

                if success:
                    st.session_state.authenticated = True
                    st.session_state.user_email = email_input
                    st.session_state.setup_mode = False
                    st.rerun()
                elif msg == "SET_PASSWORD":
                    st.session_state.setup_mode = True
                else:
                    st.error(msg)
            else:
                st.error("Please fill in all fields.")

        # Secondary Confirmation (Outside the Login Button block)
        if st.session_state.setup_mode:
            st.warning("⚠️ First time login detected.")
            st.write("Since you registered via Google, please set a password for this Dashboard.")

            if st.button("Confirm Set Password"):
                if email_input and pass_input:
                    set_initial_password(email_input, pass_input)
                    st.success("✅ Password set! Please click Login again.")
                    st.session_state.setup_mode = False # Reset mode
                else:
                    st.error("Password cannot be empty.")

    st.stop() # Stop execution here if not logged in

# --- MAIN DASHBOARD LOGIC (Protected) ---

user_email = st.session_state.user_email

def get_data(email):
    user = database.get_user_by_email(email)
    if not user:
        return None, None, "User database error."

    try:
        creds_dict = json.loads(user['creds_json'])
        sheet_id = user['sheet_id']

        creds = Credentials.from_authorized_user_info(creds_dict, SCOPES)
        if creds.expired and creds.refresh_token:
            try: creds.refresh(GoogleRequest())
            except: pass

        client = gspread.authorize(creds)

        if sheet_id:
            sheet = client.open_by_key(sheet_id)
        else:
            sheet = client.open("OpsAgent_DB_v1")

        # Load Inventory
        try:
            inv_rows = sheet.worksheet("Inventory").get_all_values()
            if len(inv_rows) > 1:
                df_inv = pd.DataFrame(inv_rows[1:], columns=inv_rows[0])
                if 'Quantity' in df_inv.columns:
                    df_inv['Quantity'] = pd.to_numeric(df_inv['Quantity'], errors='coerce').fillna(0)
            else:
                df_inv = pd.DataFrame()
        except: df_inv = pd.DataFrame()

        # Load Sales
        try:
            sales_rows = sheet.worksheet("Sales").get_all_values()
            if len(sales_rows) > 1:
                df_sales = pd.DataFrame(sales_rows[1:], columns=sales_rows[0])

                # --- 🚨 FIX: Remove columns with empty headers ---
                df_sales = df_sales.loc[:, df_sales.columns != '']
                # -------------------------------------------------

                if len(df_sales.columns) >= 3:
                    # ... (keep the rest of your code here)
                    df_sales.rename(columns={
                        df_sales.columns[0]: 'Item Name',
                        df_sales.columns[1]: 'Quantity',
                        df_sales.columns[2]: 'Sold Price'
                    }, inplace=True)
            else:
                df_sales = pd.DataFrame()
        except: df_sales = pd.DataFrame()

        return df_inv, df_sales, "Live"

    except Exception as e:
        return None, None, str(e)

# Sidebar for Logout
with st.sidebar:
    st.write(f"Logged in as: **{user_email}**")
    if st.button("🔒 Logout"):
        st.session_state.authenticated = False
        st.session_state.user_email = None
        st.rerun()

col_main, col_btn = st.columns([6, 1])
with col_main:
    st.title(f"⚡ Dashboard")
with col_btn:
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()

df_inv, df_sales, status = get_data(user_email)

if status != "Live":
    st.error(f"⚠️ System Error: {status}")
    st.stop()

rev = 0
if df_sales is not None and not df_sales.empty and 'Sold Price' in df_sales.columns:
    rev = pd.to_numeric(df_sales['Sold Price'], errors='coerce').sum()

low_stock = 0
if df_inv is not None and not df_inv.empty and 'Quantity' in df_inv.columns:
    low_stock = df_inv[df_inv['Quantity'] < 10].shape[0]

m1, m2, m3 = st.columns(3)
m1.metric("Revenue", f"₹{rev:,.0f}")
m2.metric("Low Stock", low_stock)
m3.metric("Transactions", len(df_sales) if df_sales is not None else 0)

st.divider()

st.subheader("📦 Live Inventory")
if df_inv is not None and not df_inv.empty and 'Quantity' in df_inv.columns:
    df_inv = df_inv.sort_values(by="Quantity")
    fig = px.bar(df_inv, x='Quantity', y='Item Name', orientation='h', text='Quantity')
    try:
        st.plotly_chart(fig, width="stretch")
    except:
        st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No Inventory Data")

st.subheader("📝 Recent Sales")
if df_sales is not None and not df_sales.empty:
    try:
        st.dataframe(df_sales.iloc[::-1].head(10), width="stretch")
    except:
        st.dataframe(df_sales.iloc[::-1].head(10), width="stretch")