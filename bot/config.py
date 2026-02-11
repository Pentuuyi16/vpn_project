import os
from dotenv import load_dotenv

load_dotenv()

# Telegram Bot
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ADMIN_TELEGRAM_ID = int(os.getenv('ADMIN_TELEGRAM_ID', 0))

# Xray config path on VPN servers
XRAY_CONFIG_PATH = '/usr/local/etc/xray/config.json'

# Database
DB_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'vpn.db')

# Pricing
PRICES = {
    '1_month': 300,
    '3_months': 800,
    '6_months': 1500,
    '12_months': 2500
}

# Server limits
MAX_USERS_PER_SERVER = 60