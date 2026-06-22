import os
import logging

# ── App identity ────────────────────────────────────────
APP_VERSION = "0.2.0"

# ── Debug mode ──────────────────────────────────────────
DEBUG = False #os.getenv("BICENTRA_DEBUG", "0") == "1"

# ── Backend API ─────────────────────────────────────────
if DEBUG:
    API_BASE_URL = os.getenv("BICENTRA_API_URL", "https://beta.api.bicentra.ai")
else:
    API_BASE_URL = os.getenv("BICENTRA_API_URL", "https://api.bicentra.ai")

# ── Auth ────────────────────────────────────────────────
ACCESS_TOKEN = None

# ── Delays ──────────────────────────────────────────────
ACTION_DELAY = 0.05
SCREENSHOT_INTERVAL = 0.1

# ── Safety ──────────────────────────────────────────────
MAX_STEPS = 50
FAILSAFE_ENABLED = True

# ── Logging ─────────────────────────────────────────────
LOG_LEVEL = logging.DEBUG if DEBUG else logging.WARNING

logging.basicConfig(
    level=LOG_LEVEL,
    format="[%(levelname)s] %(message)s" if DEBUG else "%(message)s",
)
logger = logging.getLogger("bicentra")
