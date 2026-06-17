"""API client for communicating with the Bicentra backend."""

import platform

import requests
import config
from config import logger
import auth_store
import system_info as sysinfo


class BicentraAPI:
    def __init__(self):
        self.base_url = config.API_BASE_URL.rstrip("/")
        self.token = None
        self.refresh_token = None
        self.email = None
        self.session = requests.Session()

    def _headers(self):
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _log_request(self, method, url, status_code, response_text=""):
        logger.debug(f"{method} {url} → {status_code}")
        if status_code >= 400:
            logger.debug(f"  Response: {response_text[:500]}")

    def login(self, email: str, password: str) -> bool:
        """Authenticate, store JWT token, and save encrypted to disk.

        Sends device metadata so the backend can record an "active session"
        row visible in the Devices page.
        """
        url = f"{self.base_url}/api/auth/token/desktop/"
        logger.debug(f"POST {url}")

        # Best-effort device metadata.
        try:
            info = sysinfo.detect_system()
            payload = {
                "email": email,
                "password": password,
                "platform_name": info.platform_name or "",
                "platform_version": info.platform_version or "",
                "machine_name": platform.node() or "",
                "cpu_cores": info.cpu_cores or None,
                "total_ram_gb": round(info.total_ram_gb, 2) if info.total_ram_gb else None,
                "is_apple_silicon": bool(info.is_apple_silicon),
                "app_version": getattr(config, "APP_VERSION", ""),
            }
        except Exception:
            payload = {"email": email, "password": password}

        resp = self.session.post(url, json=payload)
        self._log_request("POST", url, resp.status_code, resp.text)
        if resp.status_code == 200:
            data = resp.json()
            self.token = data.get("access")
            self.refresh_token = data.get("refresh")
            self.email = email
            config.ACCESS_TOKEN = self.token
            # Save encrypted
            auth_store.save_tokens(self.token, self.refresh_token or "", email)
            logger.debug("Token acquired and saved")
            return True
        print(f"  Login error: {resp.status_code} — {resp.text[:300]}")
        return False

    def restore_session(self) -> bool:
        """Try to restore a saved session from encrypted storage."""
        saved = auth_store.load_tokens()
        if not saved:
            return False

        self.token = saved.get("access")
        self.refresh_token = saved.get("refresh")
        self.email = saved.get("email")
        config.ACCESS_TOKEN = self.token

        # Verify the token is still valid
        url = f"{self.base_url}/api/auth/users/me/"
        logger.debug(f"GET {url} (verifying saved token)")
        try:
            resp = self.session.get(url, headers=self._headers(), timeout=10)
            self._log_request("GET", url, resp.status_code)
            if resp.status_code == 200:
                logger.debug(f"Session restored for {self.email}")
                return True
        except requests.RequestException:
            pass

        # Token expired — try refresh
        if self.refresh_token:
            logger.debug("Access token expired, trying refresh...")
            if self._refresh():
                return True

        # Failed — clear stale tokens
        self.logout()
        return False

    def _refresh(self) -> bool:
        """Refresh the access token using the refresh token.

        Hits the desktop-specific refresh endpoint so the device session
        gets validated server-side. If the session was force-logged-out,
        the backend returns 401 and we clear local tokens.
        """
        url = f"{self.base_url}/api/auth/token/desktop/refresh/"
        logger.debug(f"POST {url}")
        try:
            resp = self.session.post(url, json={"refresh": self.refresh_token})
        except requests.RequestException as e:
            logger.error(f"refresh request failed: {e}")
            return False
        self._log_request("POST", url, resp.status_code, resp.text)
        if resp.status_code == 200:
            data = resp.json()
            self.token = data.get("access")
            # simplejwt may rotate the refresh token; preserve if not returned
            new_refresh = data.get("refresh")
            if new_refresh:
                self.refresh_token = new_refresh
            config.ACCESS_TOKEN = self.token
            auth_store.save_tokens(self.token, self.refresh_token or "", self.email or "")
            logger.debug("Token refreshed and saved")
            return True
        return False

    def logout(self):
        """Tell the backend we're logging out, then clear tokens locally.

        Best-effort — even if the server call fails (offline, token expired),
        we still wipe the local store so the next launch goes back to the
        login screen.
        """
        if self.token:
            try:
                url = f"{self.base_url}/api/auth/token/desktop/logout/"
                logger.debug(f"POST {url}")
                resp = self.session.post(url, headers=self._headers(), timeout=10)
                self._log_request("POST", url, resp.status_code, resp.text)
            except requests.RequestException as e:
                logger.debug(f"logout request failed (offline?): {e}")
        self.token = None
        self.refresh_token = None
        self.email = None
        config.ACCESS_TOKEN = None
        auth_store.clear_tokens()
        logger.debug("Logged out, tokens cleared")

    def list_flows(self, pms: str):
        """Fetch available flows for a given PMS."""
        url = f"{self.base_url}/api/desktop/flows/?pms={pms}"
        logger.debug(f"GET {url}")
        resp = self.session.get(url, headers=self._headers())
        self._log_request("GET", url, resp.status_code, resp.text)
        if resp.status_code == 200:
            return resp.json().get("flows", [])
        return []

    def create_session(self, pms_software: str, flow_name: str, flow_inputs: dict | None = None):
        """Start a new desktop automation session for a recorded flow."""
        url = f"{self.base_url}/api/desktop/sessions/create/"
        logger.debug(f"POST {url}")
        payload = {
            "pms_software": pms_software,
            "flow_name": flow_name,
            "flow_inputs": flow_inputs or {},
        }
        resp = self.session.post(url, json=payload, headers=self._headers())
        self._log_request("POST", url, resp.status_code, resp.text)
        if resp.status_code == 201:
            return resp.json(), None
        error = f"{resp.status_code} — {resp.text[:500]}"
        return None, error

    def next_step(self, session_id: str, screen_width: int = 0, screen_height: int = 0):
        """Ask backend for the next deterministic action. Screen size lets backend convert pct->pixels."""
        url = f"{self.base_url}/api/desktop/sessions/{session_id}/next/"
        payload = {
            "screen_width": screen_width,
            "screen_height": screen_height,
        }
        logger.debug(f"POST {url} (screen={screen_width}x{screen_height})")
        resp = self.session.post(url, json=payload, headers=self._headers(), timeout=30)
        self._log_request("POST", url, resp.status_code, resp.text)
        if resp.status_code == 200:
            return resp.json()
        return None

    def cancel_session(self, session_id: str) -> bool:
        url = f"{self.base_url}/api/desktop/sessions/{session_id}/cancel/"
        logger.debug(f"POST {url}")
        resp = self.session.post(url, headers=self._headers())
        self._log_request("POST", url, resp.status_code, resp.text)
        return resp.status_code == 200

    def create_flow(self, flow_data: dict):
        """Save a recorded flow to the backend DB."""
        url = f"{self.base_url}/api/desktop/flows-crud/"
        logger.debug(f"POST {url}")
        resp = self.session.post(url, json=flow_data, headers=self._headers())
        self._log_request("POST", url, resp.status_code, resp.text)
        if resp.status_code == 201:
            return resp.json(), None
        return None, f"{resp.status_code} — {resp.text[:500]}"

    def list_my_flows(self, pms: str | None = None):
        """List all flows the user's org has created (DB-only)."""
        url = f"{self.base_url}/api/desktop/flows-crud/"
        if pms:
            url += f"?pms_software={pms}"
        logger.debug(f"GET {url}")
        resp = self.session.get(url, headers=self._headers())
        self._log_request("GET", url, resp.status_code, resp.text)
        if resp.status_code == 200:
            data = resp.json()
            # DRF pagination returns {count, next, previous, results}
            if isinstance(data, dict) and "results" in data:
                return data["results"]
            return data
        return []

    def delete_flow(self, flow_id: str) -> bool:
        url = f"{self.base_url}/api/desktop/flows-crud/{flow_id}/"
        logger.debug(f"DELETE {url}")
        resp = self.session.delete(url, headers=self._headers())
        self._log_request("DELETE", url, resp.status_code, resp.text)
        return resp.status_code in (200, 204)

    # ──────────── Sessions ────────────
    def list_sessions(
        self,
        page: int = 1,
        page_size: int = 25,
        pms_software: str | None = None,
        status: str | None = None,
        flow_name: str | None = None,
        started_after: str | None = None,
        started_before: str | None = None,
        q: str | None = None,
    ) -> dict:
        """Returns {results, count, next, previous} or {results: [...]} for legacy."""
        params = {"page": page, "page_size": page_size}
        if pms_software: params["pms_software"] = pms_software
        if status: params["status"] = status
        if flow_name: params["flow_name"] = flow_name
        if started_after: params["started_after"] = started_after
        if started_before: params["started_before"] = started_before
        if q: params["q"] = q
        url = f"{self.base_url}/api/desktop/sessions/"
        logger.debug(f"GET {url} params={params}")
        resp = self.session.get(url, params=params, headers=self._headers(), timeout=30)
        self._log_request("GET", url, resp.status_code, resp.text)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                return {"results": data, "count": len(data), "next": None, "previous": None}
            return data
        return {"results": [], "count": 0, "next": None, "previous": None}

    def get_session_detail(self, session_id: str) -> dict | None:
        url = f"{self.base_url}/api/desktop/sessions/{session_id}/"
        logger.debug(f"GET {url}")
        resp = self.session.get(url, headers=self._headers(), timeout=30)
        self._log_request("GET", url, resp.status_code, resp.text)
        return resp.json() if resp.status_code == 200 else None

    def delete_session(self, session_id: str) -> bool:
        url = f"{self.base_url}/api/desktop/sessions/{session_id}/delete/"
        logger.debug(f"POST {url}")
        resp = self.session.post(url, headers=self._headers(), timeout=15)
        self._log_request("POST", url, resp.status_code, resp.text)
        return resp.status_code in (200, 204)

    def share_session(self, session_id: str) -> dict | None:
        url = f"{self.base_url}/api/desktop/sessions/{session_id}/share/"
        logger.debug(f"POST {url}")
        resp = self.session.post(url, headers=self._headers(), timeout=15)
        self._log_request("POST", url, resp.status_code, resp.text)
        return resp.json() if resp.status_code == 200 else None

    def unshare_session(self, session_id: str) -> bool:
        url = f"{self.base_url}/api/desktop/sessions/{session_id}/unshare/"
        logger.debug(f"POST {url}")
        resp = self.session.post(url, headers=self._headers(), timeout=15)
        self._log_request("POST", url, resp.status_code, resp.text)
        return resp.status_code in (200, 204)

    def export_session(self, session_id: str) -> dict | None:
        """Returns the JSON export payload."""
        url = f"{self.base_url}/api/desktop/sessions/{session_id}/export/"
        logger.debug(f"GET {url}")
        resp = self.session.get(url, headers=self._headers(), timeout=30)
        self._log_request("GET", url, resp.status_code, resp.text)
        return resp.json() if resp.status_code == 200 else None

    def upload_action_screenshot(
        self, session_id: str, action_id: str, png_bytes: bytes
    ) -> bool:
        url = (
            f"{self.base_url}/api/desktop/sessions/{session_id}"
            f"/actions/{action_id}/screenshot/"
        )
        files = {"screenshot": (f"step_{action_id}.png", png_bytes, "image/png")}
        # Don't include Content-Type: application/json for multipart
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            resp = self.session.post(url, files=files, headers=headers, timeout=30)
            self._log_request("POST", url, resp.status_code, resp.text)
            return resp.status_code in (200, 201)
        except requests.RequestException as e:
            logger.error(f"upload_action_screenshot failed: {e}")
            return False

    def report_action_executed(
        self,
        session_id: str,
        action_id: str,
        executed_at: str | None = None,
        duration_ms: int | None = None,
        status: str = "executed",
        error: str = "",
    ) -> bool:
        url = (
            f"{self.base_url}/api/desktop/sessions/{session_id}"
            f"/actions/{action_id}/executed/"
        )
        payload = {"status": status, "error": error}
        if executed_at: payload["executed_at"] = executed_at
        if duration_ms is not None: payload["duration_ms"] = duration_ms
        try:
            resp = self.session.post(url, json=payload, headers=self._headers(), timeout=15)
            self._log_request("POST", url, resp.status_code, resp.text)
            return resp.status_code in (200, 201)
        except requests.RequestException as e:
            logger.error(f"report_action_executed failed: {e}")
            return False

    def upload_session_video(
        self, session_id: str, mp4_bytes: bytes, duration_ms: int | None = None
    ) -> bool:
        url = f"{self.base_url}/api/desktop/sessions/{session_id}/video/"
        files = {"video": (f"session_{session_id}.mp4", mp4_bytes, "video/mp4")}
        data = {}
        if duration_ms is not None:
            data["duration_ms"] = str(duration_ms)
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            resp = self.session.post(
                url, files=files, data=data, headers=headers, timeout=120
            )
            self._log_request("POST", url, resp.status_code, resp.text)
            return resp.status_code in (200, 201)
        except requests.RequestException as e:
            logger.error(f"upload_session_video failed: {e}")
            return False
