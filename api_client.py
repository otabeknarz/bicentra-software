"""API client for communicating with the Bicentra backend."""

import requests
import config


class BicentraAPI:
    def __init__(self):
        self.base_url = config.API_BASE_URL.rstrip("/")
        self.token = config.ACCESS_TOKEN
        self.session = requests.Session()

    def _headers(self):
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def login(self, email: str, password: str, recaptcha_token: str = "desktop") -> bool:
        """Authenticate and store the JWT token."""
        resp = self.session.post(
            f"{self.base_url}/api/auth/token/",
            json={
                "email": email,
                "password": password,
                "g_recaptcha_token": recaptcha_token,
            },
        )
        if resp.status_code == 200:
            data = resp.json()
            self.token = data.get("access")
            config.ACCESS_TOKEN = self.token
            return True
        return False

    def create_session(self, pms_software: str, task_description: str) -> dict | None:
        """Start a new desktop automation session."""
        resp = self.session.post(
            f"{self.base_url}/api/desktop/sessions/create/",
            json={
                "pms_software": pms_software,
                "task_description": task_description,
            },
            headers=self._headers(),
        )
        if resp.status_code == 201:
            return resp.json()
        print(f"Failed to create session: {resp.status_code} {resp.text}")
        return None

    def send_screenshot(
        self,
        session_id: str,
        screenshot_b64: str,
        screen_width: int,
        screen_height: int,
        active_window: str = "",
    ) -> dict | None:
        """Send a screenshot and get back the next action."""
        resp = self.session.post(
            f"{self.base_url}/api/desktop/sessions/{session_id}/screenshot/",
            json={
                "screenshot": screenshot_b64,
                "screen_width": screen_width,
                "screen_height": screen_height,
                "active_window_title": active_window,
            },
            headers=self._headers(),
            timeout=60,
        )
        if resp.status_code == 200:
            return resp.json()
        print(f"Screenshot failed: {resp.status_code} {resp.text}")
        return None

    def cancel_session(self, session_id: str) -> bool:
        resp = self.session.post(
            f"{self.base_url}/api/desktop/sessions/{session_id}/cancel/",
            headers=self._headers(),
        )
        return resp.status_code == 200
