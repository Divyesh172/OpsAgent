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
import traceback

warnings.simplefilter(action='ignore', category=FutureWarning)
warnings.simplefilter(action='ignore', category=UserWarning)

st.set_page_config(page_title="OpsAgent", page_icon="⚡", layout="wide", initial_sidebar_state="collapsed")
st.markdown("<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}</style>", unsafe_allow_html=True)
st_autorefresh(interval=30000, key="datarefresh")

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/userinfo.email'
]

query_params = st.query_params
user_email = query_params.get("email")

if not user_email:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.title("⚡ OpsAgent Dashboard")
        st.info("Please enter the email you used to login.")
        user_email_input = st.text_input("Email Address")
        if st.button("Open Dashboard"):
            if user_email_input:
                st.query_params["email"] = user_email_input
                st.rerun()
            else:
                st.error("Please enter an email.")
    st.stop()

def get_data(email):
    user = database.get_user_by_email(email)
    if not user:
        return None, None, "User not found in database. Please register first."

    try:
        creds_dict = json.loads(user['creds_json'])
        sheet_id = user['sheet_id'] # GET ID

        creds = Credentials.from_authorized_user_info(creds_dict, SCOPES)
        if creds.expired and creds.refresh_token:
            try: creds.refresh(GoogleRequest())
            except: pass

        client = gspread.authorize(creds)

        # OPEN BY KEY (THE FIX)
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
                if len(df_sales.columns) >= 3:
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

col_main, col_btn = st.columns([6, 1])
with col_main:
    st.title(f"⚡ Dashboard: {user_email}")
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
        st.dataframe(df_sales.iloc[::-1].head(10), use_container_width=True)