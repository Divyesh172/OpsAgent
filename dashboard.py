import streamlit as st
import pandas as pd
import gspread
import plotly.express as px
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
import os
import time
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

# 1. Page Configuration (Must be first)
st.set_page_config(
    page_title="OpsAgent App",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed" # Collapsed sidebar feels more "App-like"
)

# 2. Custom CSS to hide Streamlit UI elements (Makes it look like a native App)
hide_streamlit_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
            .block-container {padding-top: 1rem; padding-bottom: 1rem;}
            </style>
            """
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

# 3. Auto-Refresh: Increased to 10s to save API Quota
# If you didn't install this, run: pip install streamlit-autorefresh
st_autorefresh(interval=10000, key="datarefresh")

# 4. Google API Scopes
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive.file'
]

# --- ROBUST DATA LOADER ---
@st.cache_data(ttl=10) # Cache for 10 seconds to match refresh rate
def load_data():
    """
    Robustly fetches data. Returns (df_inv, df_sales, last_updated_str).
    Returns (None, None, ErrorMsg) on failure.
    """
    if not os.path.exists('token.json'):
        return None, None, "Waiting for Login..."

    try:
        # Re-load credentials from file to handle refresh updates
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)

        # Refresh if needed
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            # We don't write back here to avoid file lock contention with main.py

        client = gspread.authorize(creds)

        # Open DB safely
        try:
            sheet = client.open("OpsAgent_DB_v1")
        except gspread.SpreadsheetNotFound:
            return None, None, "Database not created yet."

        # --- Process Inventory ---
        inv_data = sheet.worksheet("Inventory").get_all_records()
        df_inv = pd.DataFrame(inv_data)

        # Clean Data
        if not df_inv.empty:
            df_inv['Quantity'] = pd.to_numeric(df_inv['Quantity'], errors='coerce').fillna(0)
            df_inv['Cost'] = pd.to_numeric(df_inv['Cost'], errors='coerce').fillna(0)

        # --- Process Sales ---
        sales_data = sheet.worksheet("Sales").get_all_records()
        df_sales = pd.DataFrame(sales_data)

        if not df_sales.empty:
            # Standardize headers (Handle cases where headers might vary)
            # Assuming Main.py writes: Item Name, Quantity, Sold Price
            if len(df_sales.columns) >= 3:
                df_sales.columns = ['Item Name', 'Quantity', 'Sold Price']
                df_sales['Sold Price'] = pd.to_numeric(df_sales['Sold Price'], errors='coerce').fillna(0)
                df_sales['Quantity'] = pd.to_numeric(df_sales['Quantity'], errors='coerce').fillna(0)

        timestamp = datetime.now().strftime("%H:%M:%S")
        return df_inv, df_sales, timestamp

    except Exception as e:
        return None, None, f"Sync Error: {str(e)}"

# --- UI LAYOUT ---

# Header Section
col_logo, col_status = st.columns([3, 1])
with col_logo:
    st.title("⚡ OpsAgent")
with col_status:
    # Live Status Indicator
    df_inv, df_sales, status_msg = load_data()
    if df_inv is not None:
        st.success(f"🟢 Live: {status_msg}")
    else:
        st.warning(f"⚠️ {status_msg}")

# Main Dashboard Logic
if df_inv is not None and not df_inv.empty:

    # 1. High-Level Metrics (Mobile Friendly)
    total_revenue = df_sales['Sold Price'].sum() if df_sales is not None and not df_sales.empty else 0
    low_stock_count = df_inv[df_inv['Quantity'] < 10].shape[0]
    total_sales_txn = len(df_sales) if df_sales is not None else 0

    m1, m2, m3 = st.columns(3)
    m1.metric("💰 Revenue", f"₹{total_revenue:,.0f}")
    m2.metric("⚠️ Low Stock", f"{low_stock_count}", delta_color="inverse")
    m3.metric("🛒 Transactions", f"{total_sales_txn}")

    st.markdown("---")

    # 2. Inventory Visuals (The "Manager View")
    st.subheader("📦 Live Inventory")

    if not df_inv.empty:
        # Sort by quantity to show lowest stock first (Critical for Ops)
        df_inv_sorted = df_inv.sort_values(by="Quantity", ascending=True)

        fig_inv = px.bar(
            df_inv_sorted,
            x='Quantity',
            y='Item Name',
            orientation='h', # Horizontal bars work better on mobile
            color='Quantity',
            color_continuous_scale='RdYlGn',
            text='Quantity',
            template="plotly_white"
        )
        fig_inv.update_layout(height=350, margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig_inv, use_container_width=True)

    # 3. Recent Sales Feed (The "Stream")
    st.subheader("📝 Recent Activity")

    if df_sales is not None and not df_sales.empty:
        # Show latest 5 transactions only to keep UI clean
        latest_sales = df_sales.iloc[::-1].head(5)

        for index, row in latest_sales.iterrows():
            with st.container():
                c1, c2 = st.columns([3, 1])
                c1.markdown(f"**{row['Item Name']}** (x{row['Quantity']})")
                c2.markdown(f"₹{row['Sold Price']}")
                st.markdown("""<hr style="margin: 5px 0; opacity: 0.2">""", unsafe_allow_html=True)
    else:
        st.info("No sales recorded yet. Waiting for WhatsApp...")

# --- EMPTY STATE (First Run) ---
elif status_msg == "Waiting for Login...":
    st.info("👋 Welcome! Please login via the main website to connect your sheet.")
    st.markdown("[Open Login Page](http://localhost:8000)")

elif df_inv is not None and df_inv.empty:
    st.info("✅ Database Connected! Send your first message on WhatsApp to populate data.")