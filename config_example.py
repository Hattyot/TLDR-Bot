import collections

BOT_TOKEN = ""
PREFIX = ">>"
EMBED_COLOUR = 0x00A6AD
MONGODB_URL = "mongodb://10.171.63.66:27017"
DEV_IDS = []

MAIN_SERVER = 0

# for daily debate reminder
MOD_ROLE_ID = 0

# Error server and channel where to send error messages
ERROR_SERVER = 0
ERROR_CHANNEL = 0
WEB_API_URL = ""

# for google drive integration
# path to given credentials for the service account
SERVICE_ACCOUNT_FILE = ""
DRIVE_PARENT_FOLDER_ID = ""

# for when the bot cant dm the user
BOT_CHANNEL_ID = 0

# For the time command https://www.geonames.org/
GEONAMES_USERNAME = ""
CLEARANCE_SPREADSHEET_ID = ""

# Opinion Bee api
OPINIONBEE_KEY = ""

MODULES = {
    'google_drive': True,
    'webhooks': True,
    'watchlist': True,
    'timers': True,
    'reaction_menus': True,
    'custom_commands': True,
    'leveling_system': True,
    'invite_logger': True,
    'moderation': True,
    'ukparl_module': True,
    'clearance': True
}

COGS = {
    'admin': True,
    'dev': True,
    'events': True,
    'fun': True,
    'leveling': True,
    'mod': True,
    'privatemessages': True,
    'settings': True,
    'uk_parliament': True,
    'utility': True
}