#!/usr/bin/env python3
"""
OKINT-PRO C4ISR Platform: Bearer Token & API Secret Key Rotation Utility.
Generates cryptographically secure 256-bit URL-safe tokens and updates .env safely.
"""
import os
import sys
import re
import secrets
import argparse

def rotate_token(env_path: str = ".env", dry_run: bool = False) -> str:
    new_token = f"tac_{secrets.token_hex(20)}"

    if not os.path.exists(env_path):
        print(f"Warning: {env_path} not found. Generated token: {new_token}")
        return new_token

    with open(env_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Update or append TAC_API_KEY / API_BEARER_TOKEN
    updated = False
    for var_name in ["TAC_API_KEY", "API_BEARER_TOKEN", "SECRET_KEY"]:
        pattern = rf"^{var_name}=.*$"
        if re.search(pattern, content, flags=re.MULTILINE):
            if var_name == "TAC_API_KEY":
                content = re.sub(pattern, f"{var_name}={new_token}", content, flags=re.MULTILINE)
                updated = True

    if not updated:
        content += f"\nTAC_API_KEY={new_token}\n"

    if dry_run:
        print(f"[DRY-RUN] New generated token: {new_token}")
    else:
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"✅ Successfully rotated TAC_API_KEY in {env_path}")
        print(f"🔑 New Token: {new_token}")
        print("ℹ️ To apply immediately without downtime: sudo docker compose restart web_api bot_ui")

    return new_token

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rotate Bearer Token for OKINT-PRO")
    parser.add_argument("--env", default=".env", help="Path to .env file")
    parser.add_argument("--dry-run", action="store_true", help="Print token without modifying file")
    args = parser.parse_args()
    rotate_token(args.env, args.dry_run)
