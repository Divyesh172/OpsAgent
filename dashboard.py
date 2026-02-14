import streamlit as st
import pandas as pd
import gspread
import plotly.express as px
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
import os
from streamlit_autorefresh import st_autorefresh

# 1. Page Configuration
st.set_page_config(page_title="OpsAgent Live Dashboard", page_icon="⚡", layout="wide")

# 2. Auto-Refresh: Triggers a rerun every 5 seconds to keep the demo live
st_autorefresh(interval=5000, key="datarefresh")

# 3. Google API Scopes (Must match main.py)
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive.file'
]

@st.cache_data(ttl=2)  # Low TTL ensures the UI reflects new WhatsApp messages immediately
def load_data():
    """Authenticates with Google and fetches the latest data from the Sheet."""
    if not os.path.exists('token.json'):
        return None, None

    try:
        # Authenticate and refresh token if expired
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())

        client = gspread.authorize(creds)

        # Open the specific DB created by main.py
        DB_NAME = "OpsAgent_DB_v1"
        sheet = client.open(DB_NAME)

        # --- Process Inventory ---
        inv_data = sheet.worksheet("Inventory").get_all_records()
        df_inv = pd.DataFrame(inv_data)
        if not df_inv.empty:
            # Force numeric types (essential for charts and math)
            df_inv['Quantity'] = pd.to_numeric(df_inv['Quantity'], errors='coerce').fillna(0)
            df_inv['Cost'] = pd.to_numeric(df_inv['Cost'], errors='coerce').fillna(0)

        # --- Process Sales ---
        sales_data = sheet.worksheet("Sales").get_all_records()
        df_sales = pd.DataFrame(sales_data)
        if not df_sales.empty:
            # Main.py writes 3 columns: [item, quantity, amount]
            # Ensure headers match for math operations
            df_sales.columns = ['Item Name', 'Quantity', 'Sold Price']
            df_sales['Sold Price'] = pd.to_numeric(df_sales['Sold Price'], errors='coerce').fillna(0)
            df_sales['Quantity'] = pd.to_numeric(df_sales['Quantity'], errors='coerce').fillna(0)

        return df_inv, df_sales

    except Exception as e:
        st.sidebar.error(f"Sync Error: {e}")
        return None, None

# --- UI LAYOUT ---

st.title("⚡ OpsAgent Command Center")

# Sidebar for manual controls and status
with st.sidebar:
    st.header("System Status")
    if os.path.exists('token.json'):
        st.success("🟢 Connected to Google Sheets")
    else:
        st.error("🔴 Not Authorized. Login via main.py first.")

    if st.button("🔄 Force Sync Now"):
        st.cache_data.clear()
        st.rerun()

# Load and visualize data
df_inv, df_sales = load_data()

if df_inv is not None and not df_inv.empty:
    # 1. Metrics Row
    col1, col2, col3 = st.columns(3)

    total_revenue = df_sales['Sold Price'].sum() if df_sales is not None else 0
    low_stock_items = df_inv[df_inv['Quantity'] < 10].shape[0]
    total_sales_count = len(df_sales) if df_sales is not None else 0

    col1.metric("💰 Total Revenue", f"₹{total_revenue:,.2f}")
    col2.metric("📦 Low Stock Alerts", f"{low_stock_items} Items")
    col3.metric("🛒 Sales Recorded", f"{total_sales_count}")

    # 2. Inventory Visualization
    st.divider()
    st.subheader("Real-time Inventory Levels")

    # Color-coded bar chart (Green for high stock, Red for low)
    fig_inv = px.bar(
        df_inv,
        x='Item Name',
        y='Quantity',
        color='Quantity',
        color_continuous_scale='RdYlGn',  # Red to Green scale
        template="plotly_dark"
    )
    st.plotly_chart(fig_inv, width=True)

    # 3. Recent Transactions Table
    if df_sales is not None and not df_sales.empty:
        st.subheader("Recent Sales (WhatsApp Stream)")
        st.dataframe(df_sales.iloc[::-1], width='stretch') # Show latest first

else:
    # Empty state UI
    st.info("👋 Waiting for data... Send your first WhatsApp message (e.g., 'Sold 10 units of Maggi') to see it here!")
    st.image("https://via.placeholder.com/800x400.png?text=Waiting+for+WhatsApp+Stream...", width='stretch')