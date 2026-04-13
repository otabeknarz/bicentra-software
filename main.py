"""
Bicentra Desktop — AI-powered pharmacy PMS automation agent.

Usage:
    python main.py

Environment variables:
    BICENTRA_API_URL    Backend API URL (default: http://localhost:8001)
    BICENTRA_EMAIL      Login email
    BICENTRA_PASSWORD   Login password
"""

import os
import sys
import time
import getpass

import config
from api_client import BicentraAPI
from automation import take_screenshot, get_active_window_title, execute_action


def print_banner():
    print()
    print("  ╔══════════════════════════════════════╗")
    print("  ║         Bicentra Desktop             ║")
    print("  ║   AI Pharmacy PMS Automation Agent   ║")
    print("  ╚══════════════════════════════════════╝")
    print()


def login(api: BicentraAPI) -> bool:
    email = os.getenv("BICENTRA_EMAIL") or input("Email: ")
    password = os.getenv("BICENTRA_PASSWORD") or getpass.getpass("Password: ")

    print("  Logging in...")
    if api.login(email, password):
        print("  ✓ Authenticated successfully")
        return True
    else:
        print("  ✗ Login failed. Check your credentials.")
        return False


def select_pms() -> str:
    pms_options = {
        "1": ("pioneer_rx", "PioneerRx"),
        "2": ("best_rx", "BestRx"),
        "3": ("framework_ltc", "Framework LTC"),
        "4": ("liberty", "Liberty Software"),
        "5": ("prime_rx", "PrimeRx"),
    }

    print("  Select PMS Software:")
    for key, (_, label) in pms_options.items():
        print(f"    {key}. {label}")

    choice = input("\n  Enter number (1-5): ").strip()
    if choice in pms_options:
        return pms_options[choice][0]

    print("  Invalid choice, defaulting to PioneerRx")
    return "pioneer_rx"


def run_session(api: BicentraAPI):
    pms = select_pms()
    print()
    task = input("  Describe the task:\n  > ")

    if not task.strip():
        print("  No task provided.")
        return

    print(f"\n  Starting session ({pms})...")
    session = api.create_session(pms, task)
    if not session:
        print("  ✗ Failed to create session.")
        return

    session_id = session["id"]
    print(f"  ✓ Session started: {session_id}")
    print(f"  ⚡ Running... (move mouse to top-left corner to abort)\n")

    step = 0
    while True:
        step += 1

        # Take screenshot
        screenshot_b64, width, height = take_screenshot()
        active_window = get_active_window_title()

        print(f"  Step {step}: Sending screenshot... ", end="", flush=True)

        # Send to backend and get action
        action = api.send_screenshot(
            session_id=session_id,
            screenshot_b64=screenshot_b64,
            screen_width=width,
            screen_height=height,
            active_window=active_window,
        )

        if action is None:
            print("✗ No response from server")
            break

        action_type = action.get("action_type", "failed")
        reason = action.get("reason", "")
        observation = action.get("ai_observation", "")

        if observation:
            print(f"\n    👁 {observation[:120]}")

        print(f"    → {action_type}", end="")
        if action_type in ("click", "double_click", "right_click"):
            print(f" at ({action.get('x')}, {action.get('y')})", end="")
        if action_type == "type":
            print(f" \"{action.get('text', '')[:50]}\"", end="")
        if action_type == "hotkey":
            print(f" {'+'.join(action.get('keys', []))}", end="")
        if reason:
            print(f"  — {reason[:80]}", end="")
        print()

        # Terminal states
        if action_type == "done":
            print(f"\n  ✓ Task completed! {reason}")
            break
        elif action_type == "failed":
            print(f"\n  ✗ Task failed: {reason}")
            break

        # Execute the action
        execute_action(action)

        # Brief pause before next screenshot
        time.sleep(config.SCREENSHOT_INTERVAL)

        # Safety limit
        if step >= config.MAX_STEPS:
            print(f"\n  ⚠ Reached max steps ({config.MAX_STEPS}). Stopping.")
            api.cancel_session(session_id)
            break


def main():
    print_banner()

    api = BicentraAPI()

    if not login(api):
        sys.exit(1)

    while True:
        print()
        print("  ─────────────────────────────")
        print("  1. Start new automation task")
        print("  2. Exit")
        choice = input("  > ").strip()

        if choice == "1":
            run_session(api)
        elif choice == "2":
            print("  Goodbye!")
            break
        else:
            print("  Invalid choice.")


if __name__ == "__main__":
    main()
