import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

META_APP_ID = os.getenv("META_APP_ID")
META_APP_SECRET = os.getenv("META_APP_SECRET")
META_REDIRECT_URI = os.getenv("META_REDIRECT_URI")
META_ADMIN_SECRET = os.getenv("META_ADMIN_SECRET")  # shared secret gating /auth/meta/* routes