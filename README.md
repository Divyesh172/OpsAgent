# ⚡ OpsAgent: The Invisible ERP

**OpsAgent** is a "Headless ERP" for modern retail. It turns **WhatsApp** into a high-powered accountant and inventory manager, allowing shopkeepers to manage sales, stock, and expenses using natural language.

Powered by **Google Gemini AI**, **FastAPI**, and **Google Sheets**.

## 🚀 Features
-   **🗣️ Voice-to-Sheet:** "Sold 2 Maggi" → Updates Inventory & Sales automatically.
-   **📸 Image Scanning:** Scan bills/products to log data.
-   **📊 Live Dashboard:** Real-time revenue and stock tracking.
-   **🔔 Auto-Alerts:** WhatsApp alerts for low stock.
-   **⚡ One-Click Run:** Entire system (Backend, UI, Scheduler, Tunnel) launches with one script.

## 🛠️ Tech Stack
-   **AI:** Google Gemini 1.5 Flash
-   **Stack:** FastAPI (Backend) + Streamlit (Frontend) + SQLite (Auth)
-   **Data:** Google Sheets (User Database)
-   **Integrations:** Twilio (WhatsApp) + Ngrok (Tunneling)

## ⚙️ Quick Start

### 1. Install
```bash
git clone [https://github.com/yourusername/opsagent.git](https://github.com/yourusername/opsagent.git)
cd opsagent

# Setup Virtual Env
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install Dependencies
pip install -r requirements.txt

```

### 2. Configure Secrets
Create a .env file with your keys:
```bash
GOOGLE_API_KEY=your_gemini_key
SESSION_SECRET=random_secret_string
TWILIO_SID=your_sid
TWILIO_AUTH=your_auth
TWILIO_TO_NUMBER=+919999999999
NGROK_AUTH_TOKEN=your_ngrok_token
```
Note: Also place your Google OAuth client_secret.json in the root folder.

### 3. Run Everything 🚀
This single script launches the Backend, Dashboard, Scheduler, and Public Tunnel automatically.
```bash
python run_system.py
```
The script will open the Dashboard and print your WhatsApp Webhook URL in the terminal.

### 📱 Usage
1. Login to the Dashboard with Google.

2. Link your WhatsApp number.

3. Chat with the Twilio Sandbox number to manage your shop!

### 🛡️ License
MIT License