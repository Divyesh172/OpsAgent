import subprocess
import sys
import time
import os
import signal
import webbrowser
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Global list to track running processes
processes = []

def run_process(command, name):
    """
    Helper to start a background process and log its status.
    """
    try:
        # Windows and Linux/Mac handle process groups differently
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
    """
    Stops all services and the Ngrok tunnel when the script exits.
    """
    print("\n🛑 Shutting down OpsAgent ecosystem...")

    # 1. Stop Ngrok
    try:
        from pyngrok import ngrok
        ngrok.kill()
    except ImportError:
        pass

    # 2. Stop Python Processes (Backend, Dashboard, Scheduler)
    for p in processes:
        try:
            if sys.platform == "win32":
                # Force kill on Windows
                subprocess.call(['taskkill', '/F', '/T', '/PID', str(p.pid)])
            else:
                # Graceful kill on Linux/Mac
                os.killpg(os.getpgid(p.pid), signal.SIGTERM)
        except Exception:
            pass
    print("👋 System Offline.")

def setup_tunnel_and_twilio():
    """
    1. Starts a secure Ngrok tunnel to the Backend (Port 8000).
    2. Prints the exact URL needed for Twilio.
    """
    print("\n🌐 Initializing Public Access Tunnel...")

    try:
        from pyngrok import ngrok

        # Start Ngrok on Port 8000
        # log=False keeps the console clean
        public_url = ngrok.connect(8000).public_url
        print(f"🔗 Public URL Generated: {public_url}")

        # Generate the Webhook URL
        webhook_url = f"{public_url}/whatsapp"

        print("\n" + "="*60)
        print("⚠️  ACTION REQUIRED: UPDATE TWILIO SANDBOX")
        print("="*60)
        print(f"Go to: https://console.twilio.com/us1/develop/sms/settings/whatsapp-sandbox")
        print(f"Paste this into 'When a message comes in':")
        print(f"\n👉  {webhook_url}\n")
        print("="*60 + "\n")

        return public_url

    except ImportError:
        print("❌ Error: 'pyngrok' not installed.")
        print("   Run: pip install pyngrok")
        return None
    except Exception as e:
        print(f"❌ Tunnel Error: {e}")
        return None

if __name__ == "__main__":
    print("🚀 OpsAgent Auto-Launcher v3.0")
    print("   (Backend + Scheduler + Dashboard + Tunnel)")

    # 1. Start Backend API (Port 8000)
    # We bind to 0.0.0.0 to allow external access if needed
    run_process(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"],
        "Backend API"
    )

    # 2. Start Scheduler (Background Worker)
    run_process(
        [sys.executable, "scheduler.py"],
        "Scheduler (Munim)"
    )

    # 3. Setup Ngrok Tunnel
    # Wait 2 seconds for Backend to spin up before tunneling
    time.sleep(2)
    setup_tunnel_and_twilio()

    # 4. Start Dashboard (Port 8501)
    run_process(
        [sys.executable, "-m", "streamlit", "run", "dashboard.py", "--server.port", "8501"],
        "Dashboard UI"
    )

    print("\n⚡ System Online & Ready!")
    print("   👉 Dashboard: http://localhost:8501")
    print("   👉 Backend:   http://localhost:8000")
    print("   (Press Ctrl+C to Stop All Services)\n")

    # Open Dashboard in Browser
    time.sleep(1)
    try:
        webbrowser.open("http://localhost:8501")
    except:
        pass

    # Keep script running to monitor child processes
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        kill_all()