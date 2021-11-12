from dotenv import dotenv_values

try:
    config = dotenv_values(".env")
except:
    config = dotenv_values("../.env")

BOT_TOKEN = config.get("BOT_TOKEN")
MONGODB_URL = config.get("MONGODB_URL")
PREFIX = config.get("PREFIX")
MAIN_SERVER = int(config.get("MAIN_SERVER"))
ERROR_SERVER = int(config.get("ERROR_SERVER"))
ERROR_CHANNEL = int(config.get("ERROR_CHANNEL"))
WEB_API_URL = config.get("WEB_API_URL")
SERVICE_ACCOUNT_FILE = config.get("SERVICE_ACCOUNT_FILE")
DRIVE_PARENT_FOLDER_ID = config.get("DRIVE_PARENT_FOLDER_ID")
BOT_CHANNEL_ID = int(config.get("BOT_CHANNEL_ID"))
GEONAMES_USERNAME = config.get("GEONAMES_USERNAME")
CLEARANCE_SPREADSHEET_ID = config.get("CLEARANCE_SPREADSHEET_ID")
SLACK_APP_TOKEN = config.get("SLACK_APP_TOKEN")
SLACK_CLIENT_ID = config.get("SLACK_CLIENT_ID")
SLACK_CLIENT_SECRET = config.get("SLACK_CLIENT_SECRET")
SLACK_REDIRECT_DOMAIN = config.get("SLACK_REDIRECT_DOMAIN")
EMBED_COLOUR = int(config.get("EMBED_COLOUR"), 16)

<<<<<<< HEAD
MODULES = {}  # {"clearance": False, "google_drive": False, "leveling": False}
=======
MODULES = {}
>>>>>>> 1b484a5 (Undoing all of this. ffs me.)
COGS = {}
