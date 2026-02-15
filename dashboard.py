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

st.set_page_config(page_title="OpsAgent Headquarters", page_icon="⚡", layout="wide", initial_sidebar_state="collapsed")

# Custom CSS
st.markdown("""
<style>
    [data-testid="stMetricValue"] { font-size: 24px; font-weight: 700; color: #0f172a; }
    .stDataFrame { border-radius: 10px; overflow: hidden; }
    h1, h2, h3 { font-family: 'Plus Jakarta Sans', sans-serif; }
    div[data-testid="stToolbar"] { visibility: hidden; }
    footer { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

st_autorefresh(interval=10000, key="datarefresh")

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/userinfo.email',
    'openid' # <--- ADDED: Prevents "Scope has changed" errors
]

# --- HELPER: SAFE DATAFRAME CREATION ---
def safe_create_df(worksheet):
    """
    Robustly creates a DataFrame from a worksheet, ignoring empty/duplicate headers.
    """
    try:
        # Get raw values (list of lists) instead of records to avoid duplicate header error
        data = worksheet.get_all_values()

        if not data:
            return pd.DataFrame() # Empty sheet

        headers = data[0]
        rows = data[1:]

        # Create DF
        df = pd.DataFrame(rows, columns=headers)

        # 1. Remove columns with empty names (caused by empty columns in Sheets)
        df = df.loc[:, df.columns != '']

        # 2. Remove duplicate columns (if any accidentally exist)
        df = df.loc[:, ~df.columns.duplicated()]

        return df
    except Exception as e:
        print(f"⚠️ DF Creation Error: {e}")
        return pd.DataFrame()

# --- SECURITY UTILS ---
def hash_pass(password):
    return hashlib.sha256(password.encode()).hexdigest()

def authenticate(email, password):
    conn = sqlite3.connect(database.DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE email=?", (email,))
    user = c.fetchone()
    conn.close()

    if not user: return False, "❌ User not found."

    stored_hash = user['password_hash']
    if not stored_hash: return False, "SET_PASSWORD"

    if stored_hash == hash_pass(password): return True, "✅ Login Successful"
    else: return False, "❌ Incorrect Password"

def set_initial_password(email, new_password):
    conn = sqlite3.connect(database.DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE users SET password_hash=? WHERE email=?", (hash_pass(new_password), email))
    conn.commit()
    conn.close()
    return True

# --- LOGIN FLOW ---
if "authenticated" not in st.session_state: st.session_state.authenticated = False
if "user_email" not in st.session_state: st.session_state.user_email = None
if "setup_mode" not in st.session_state: st.session_state.setup_mode = False

# --- NEW: AUTO-LOGIN FROM URL ---
# This detects the "?email=..." from the backend redirect
if "email" in st.query_params and not st.session_state.authenticated:
    email_from_url = st.query_params["email"]
    # Verify user exists in DB
    user = database.get_user_by_email(email_from_url)
    if user:
        st.session_state.authenticated = True
        st.session_state.user_email = email_from_url
        st.session_state.setup_mode = False
        st.toast(f"✅ Welcome back, {email_from_url}!", icon="🚀")
        st.rerun()

if not st.session_state.authenticated:
    c1, c2, c3 = st.columns([1, 1, 1])
    with c2:
        st.title("⚡ OpsAgent Login")
        email_input = st.text_input("Email Address")
        pass_input = st.text_input("Password", type="password")

        if st.button("Access Dashboard", type="primary", width='stretch'):
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

        if st.session_state.setup_mode:
            st.warning("⚠️ First Login: Set your secure password.")
            if st.button("Confirm Password"):
                set_initial_password(email_input, pass_input)
                st.success("✅ Password Set!"); st.session_state.setup_mode = False
    st.stop()

# --- DATA FETCHING ---
user_email = st.session_state.user_email

@st.cache_data(ttl=5)
def get_all_data(email):
    user = database.get_user_by_email(email)
    if not user: return None

    try:
        creds_dict = json.loads(user['creds_json'])
        sheet_id = user['sheet_id']
        creds = Credentials.from_authorized_user_info(creds_dict, SCOPES)
        if creds.expired and creds.refresh_token: creds.refresh(GoogleRequest())
        client = gspread.authorize(creds)

        sheet = None
        if sheet_id:
            try: sheet = client.open_by_key(sheet_id)
            except: pass
        if not sheet: sheet = client.open("OpsAgent_DB_v1")

        # --- USE ROBUST HELPER FUNCTION ---
        df_inv = safe_create_df(sheet.worksheet("Inventory"))
        df_sales = safe_create_df(sheet.worksheet("Sales"))

        try: df_staff = safe_create_df(sheet.worksheet("Staff"))
        except: df_staff = pd.DataFrame(columns=["Name", "Role", "Shift", "Status"])

        try: df_khata = safe_create_df(sheet.worksheet("Khata"))
        except: df_khata = pd.DataFrame(columns=["Customer", "Amount", "Status"])

        return df_inv, df_sales, df_staff, df_khata

    except Exception as e:
        print(f"DEBUG Error: {e}")
        return None

# --- DASHBOARD UI ---
raw_data = get_all_data(user_email)

if raw_data is None:
    st.error("⚠️ Connection Error. Check terminal for details.")
    st.stop()

df_inv, df_sales, df_staff, df_khata = raw_data

# Top Bar
c1, c2 = st.columns([5, 1])
with c1:
    st.title("⚡ OpsAgent Headquarters")
    st.caption(f"Connected: {user_email}")
with c2:
    if st.button("Logout"):
        st.session_state.authenticated = False; st.rerun()

# Metrics
kpi1, kpi2, kpi3, kpi4 = st.columns(4)
rev = pd.to_numeric(df_sales['Sold Price'], errors='coerce').sum() if not df_sales.empty else 0
low_stock = df_inv[pd.to_numeric(df_inv['Quantity'], errors='coerce') < 10].shape[0] if not df_inv.empty else 0
staff_absent = df_staff[df_staff['Status'] == 'Absent'].shape[0] if not df_staff.empty else 0
pending_dues = df_khata[df_khata['Status'] == 'Pending']['Amount'].astype(float).sum() if not df_khata.empty else 0

kpi1.metric("Total Revenue", f"₹{rev:,.0f}", delta="Today")
kpi2.metric("Stock Alerts", f"{low_stock}", delta_color="inverse")
kpi3.metric("Staff Absent", f"{staff_absent}", delta_color="inverse")
kpi4.metric("Pending Dues", f"₹{pending_dues:,.0f}", delta="Risk")

st.markdown("---")

tab1, tab2, tab3 = st.tabs(["📊 Inventory & Sales", "👥 Staff", "💰 Khata"])

with tab1:
    col1, col2 = st.columns([2, 1])
    with col1:
        if not df_inv.empty:
            df_inv['Quantity'] = pd.to_numeric(df_inv['Quantity'], errors='coerce')
            fig = px.bar(df_inv, x='Item Name', y='Quantity', color='Quantity', color_continuous_scale='RdYlGn')
            st.plotly_chart(fig, width='stretch')
        else: st.info("No Data")
    with col2:
        st.subheader("🚨 Risk Radar")
        if low_stock > 0:
            st.error(f"⚠️ {low_stock} items low!")
            st.dataframe(df_inv[df_inv['Quantity'] < 10][['Item Name', 'Quantity']], hide_index=True)
        else: st.success("✅ Inventory Healthy")

with tab2:
    if not df_staff.empty:
        def color_status(val): return f'background-color: {"#dcfce7" if val == "Present" else "#fee2e2"}'
        st.dataframe(df_staff.style.applymap(color_status, subset=['Status']), width='stretch')
    else: st.info("No Staff Data")

with tab3:
    if not df_khata.empty:
        st.dataframe(df_khata[df_khata['Status'] == 'Pending'], width='stretch')
    else: st.info("No Pending Dues")