import os

# Backend API
API_BASE_URL = os.getenv("BICENTRA_API_URL", "http://localhost:8001")

# Auth — the desktop app logs in with email/password and gets a JWT token
ACCESS_TOKEN = None

# Delays
ACTION_DELAY = 0.3  # seconds between screenshot and action
SCREENSHOT_INTERVAL = 0.5  # seconds to wait after action before next screenshot

# Safety
MAX_STEPS = 50
FAILSAFE_ENABLED = True  # PyAutoGUI failsafe — move mouse to corner to abort
