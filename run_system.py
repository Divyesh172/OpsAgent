import subprocess
import sys
import time
import os
import signal
import platform

# Global process list for cleanup
processes = []

def cleanup():
    """Kills all subprocesses started by this script."""
    print("\n🛑 Shutting down OpsAgent ecosystem...")
    for p in processes:
        try:
            if platform.system() == "Windows":
                # Force kill on Windows
                subprocess.call(['taskkill', '/F', '/T', '/PID', str(p.pid)])
            else:
                # Graceful kill on Unix/Mac
                os.killpg(os.getpgid(p.pid), signal.SIGTERM)
        except Exception:
            pass
    print("✅ All services stopped.")

def run_service(command, name):
    """Starts a service and adds it to the process list."""
    try:
        # Use preexec_fn=os.setsid on Unix to enable group killing
        # On Windows, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
        kwargs = {}
        if platform.system() != "Windows":
            kwargs['preexec_fn'] = os.setsid
        else:
            kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP

        p = subprocess.Popen(command, shell=False, **kwargs)
        processes.append(p)
        print(f"🚀 {name} started (PID: {p.pid})...")
        return p
    except Exception as e:
        print(f"❌ Failed to start {name}: {e}")
        sys.exit(1)

if __name__ == "__main__":
    print("⚡ Starting OpsAgent System...")

    # 1. Start Backend (FastAPI)
    # Reload is ON for dev, Port 8000
    backend = run_service(
        [sys.executable, "-m", "uvicorn", "main:app", "--reload", "--port", "8000"],
        "Backend API"
    )

    # 2. Start Scheduler (Munim)
    scheduler = run_service(
        [sys.executable, "scheduler.py"],
        "Scheduler (Munim)"
    )

    # 3. Start Dashboard (Streamlit)
    # Wait a moment for Backend to initialize
    time.sleep(3)
    dashboard = run_service(
        [sys.executable, "-m", "streamlit", "run", "dashboard.py", "--server.port", "8501", "--server.headless", "true"],
        "Dashboard UI"
    )

    print("\n✅ System Online!")
    print("   👉 Dashboard: http://localhost:8501")
    print("   👉 Backend:   http://localhost:8000")
    print("   👉 Press Ctrl+C to stop all services.\n")

    try:
        # Keep main script alive to monitor children
        while True:
            time.sleep(1)
            # Check if any critical service died
            if backend.poll() is not None:
                print("❌ Backend crashed! Shutting down...")
                break
            if scheduler.poll() is not None:
                print("❌ Scheduler crashed! Shutting down...")
                break
    except KeyboardInterrupt:
        pass
    finally:
        cleanup()