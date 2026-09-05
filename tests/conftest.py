"""
Pytest global fixtures and environment setup for C4ISR suite.
"""
import os

os.environ.setdefault("SECRET_KEY", "tac_master_test_secret_key_2026_c4isr_okint")
os.environ.setdefault("TESTING", "true")
os.environ.setdefault("DATABASE_URL", "sqlite:///events.db")
os.environ.setdefault("TACTICAL_API_TOKEN", "admin_tactical_token_2026")
