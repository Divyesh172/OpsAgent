import subprocess
import sys
import time
import os
import signal
import webbrowser
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Global list to track processes
processes = []

def run_process(command, name):
    try:
        if sys.platform == "win32":
            p = subprocess.Popen(command, shell=True, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        else:
            p = subprocess.Popen(command, shell=False, preexec_fn=os.setsid)
        processes.append(p)
        print(f"✅ Started {name} (PID: {p.pid})")
        return p
    except Exception as e:
        print(f"❌ Failed to start {name}: {e}")
        kill_all()
        sys.exit(1)

def kill_all():
    print("\n🛑 Shutting down OpsAgent ecosystem...")
    try:
        from pyngrok import ngrok
        ngrok.kill()
    except: pass

    for p in processes:
        try:
            if sys.platform == "win32":
                subprocess.call(['taskkill', '/F', '/T', '/PID', str(p.pid)])
            else:
                os.killpg(os.getpgid(p.pid), signal.SIGTERM)
        except: pass
    print("👋 System Offline.")

def setup_tunnel_and_twilio():
    print("\n🌐 Initializing Public Access Tunnel...")
    try:
        from pyngrok import ngrok
        public_url = ngrok.connect(8000).public_url
        print(f"🔗 Public URL Generated: {public_url}")

        print("\n" + "="*60)
        print("⚠️  ACTION REQUIRED: UPDATE TWILIO SANDBOX")
        print("="*60)
        print(f"Go to: https://console.twilio.com/us1/develop/sms/settings/whatsapp-sandbox")
        print(f"Paste this into 'When a message comes in':")
        print(f"\n👉  {public_url}/whatsapp\n")
        print("="*60 + "\n")
        return public_url
    except:
        print("❌ Tunnel Error. Run: pip install pyngrok")
        return None

if __name__ == "__main__":
    print("🚀 OpsAgent Auto-Launcher v3.2 (CORS Fix)")

    # 1. Start Backend (Hero Page)
    run_process(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"],
        "Backend API"
    )

    # 2. Start Scheduler
    run_process([sys.executable, "scheduler.py"], "Scheduler")

    # 3. Setup Tunnel
    time.sleep(2)
    setup_tunnel_and_twilio()

    # 4. Start Dashboard (Fixed Security Flags)
    run_process(
        [
            sys.executable, "-m", "streamlit", "run", "dashboard.py",
            "--server.port", "8501",
            "--server.headless", "true",
            "--server.enableCORS", "false",           # <--- ADDED THIS
            "--server.enableXsrfProtection", "false"  # <--- ADDED THIS
        ],
        "Dashboard UI"
    )

    print("\n⚡ System Online & Ready!")
    print("   👉 Hero Page: http://localhost:8000")
    print("   (Press Ctrl+C to Stop All Services)\n")

    # 5. Open ONLY the Hero Page
    time.sleep(2)
    try:
        webbrowser.open("http://localhost:8000")
    except: pass

    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        kill_all()