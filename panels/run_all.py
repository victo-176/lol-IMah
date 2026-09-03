#!/usr/bin/env python3
"""
Run all panels in parallel.
Edit PANELS list below to add/remove panels.
"""

import threading
import logging
import sys

logging.basicConfig(level=logging.INFO, format='%(asctime)s [MAIN] %(message)s')
logger = logging.getLogger(__name__)

# =========================== PANELS TO RUN ===========================
# Add your panels here. Each entry is (module_name, config_dict)
# or just module_name for panels with their own config at the top.

PANELS = [
    # Example 1: EVS SMS (has its own config in evs_sms.py)
    "evs_sms",

    # Example 2: Another panel (copy panel_template.py and fill in config)
    # "my_other_panel",

    # Example 3: Using config dict
    # {
    #     "module": "panel_template",
    #     "config": {
    #         "name": "My Panel",
    #         "panel_url": "http://1.2.3.4/ints",
    #         "login_type": "client",
    #         "username": "user",
    #         "password": "pass",
    #         "telegram_token": "BOT:TOKEN",
    #         "group_chat_id": -1001234567890,
    #         "bot_link": "https://t.me/mybot",
    #         "otp_group_link": "https://t.me/mygroup",
    #         "poll_interval": 15,
    #     }
    # },
]


def run_panel_standalone(module_name):
    """Run a panel that has its own config (like evs_sms.py)."""
    try:
        mod = __import__(f"panels.{module_name}", fromlist=["main"])
        mod.main()
    except Exception as e:
        logger.error(f"Panel {module_name} error: {e}")


def run_panel_with_config(module_name, config):
    """Run a panel using config dict with base_panel.py."""
    try:
        from panels.base_panel import BasePanel
        from panels import panel_template as template_mod

        # Create panel class from template
        class Panel(BasePanel):
            def fetch_otps_for_date(self, date_str):
                return template_mod.fetch_otps_for_date(self, date_str)

        panel = Panel(config)
        panel.run()
    except Exception as e:
        logger.error(f"Panel {config.get('name', module_name)} error: {e}")


def main():
    print("=" * 60)
    print("OTP Panel Runner")
    print("=" * 60)
    print(f"Starting {len(PANELS)} panel(s)...")
    print()

    threads = []

    for panel_config in PANELS:
        if isinstance(panel_config, str):
            # Just module name - run standalone
            t = threading.Thread(target=run_panel_standalone, args=(panel_config,), daemon=True)
            t.start()
            threads.append((panel_config, t))
            logger.info(f"Started panel: {panel_config}")
        elif isinstance(panel_config, dict):
            # Dict with module and config
            module = panel_config.get("module", "panel_template")
            config = panel_config.get("config", {})
            t = threading.Thread(target=run_panel_with_config, args=(module, config), daemon=True)
            t.start()
            threads.append((config.get("name", module), t))
            logger.info(f"Started panel: {config.get('name', module)}")

    print()
    print("All panels started!")
    print("Press Ctrl+C to stop all panels.")
    print()

    try:
        while True:
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down all panels...")
        sys.exit(0)


if __name__ == "__main__":
    main()
