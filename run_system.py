import subprocess
import sys
import time

# 1. Start the Backend (FastAPI)
# We use Popen to run it in the background
backend = subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app", "--reload", "--port", "8000"])
print("🚀 Backend started on port 8000...")

# 2. Start the Scheduler (Munim)
scheduler = subprocess.Popen([sys.executable, "scheduler.py"])
print("🕒 Scheduler started...")

# 3. Start the Dashboard (Streamlit)
# We wait a second to ensure backend is ready
time.sleep(2)
dashboard = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "dashboard.py"])
print("📊 Dashboard started...")

try:
    backend.wait()
    scheduler.wait()
    dashboard.wait()
except KeyboardInterrupt:
    print("\n🛑 Shutting down OpsAgent...")
    backend.terminate()
    scheduler.terminate()
    dashboard.terminate()