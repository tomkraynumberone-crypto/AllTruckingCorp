"""Every sentence the bot says. Edit the wording here (keep the {placeholders})."""

ASK_ZIP = "What's your current ZIP code? I'll check available loads for you."
ZIP_ACK = "Got it! Checking loads for you. 👍"
ALREADY_LISTED = "You're already on the available list at {zip}. Send a new ZIP code if your location has changed."
ASK_TIME = "No problem! What time do you expect to be empty and ready for a load?"
TIME_ACK = "Thanks! I'll update your availability for {time}."
UNAVAILABLE_ACK = "Got it, thanks for letting us know. I've taken you off the available list."
CLARIFY = ("Just to confirm: are you empty and available for a load right now, or later? "
           "If later, what time?")
ZIP_NOTED_ASK_TIME = "Thanks, I have your ZIP as {zip}. What time do you expect to be empty and ready for a load?"
ZIP_UPDATED = "Thanks, I've updated your ZIP to {zip}."
ZIP_NOTED_ASK_STATUS = ("Thanks, I have your ZIP as {zip}. Are you empty and available for a load now? "
                        "If not, what time will you be ready?")

REFRESH = ("Quick update time! If you're empty and available, reply AVAILABLE and include your "
           "current ZIP code. If you're not ready yet, tell us what time you expect to be empty.")
REFRESH_NEED_ZIP = "Still need a ZIP code from: {names}"

PRIVATE_HINT = "Please send your availability in the dispatch group. I'll update the list from there."
NOT_AUTHORIZED = "Sorry, that command is only for dispatchers."

START_TEXT = (
    "Hi! I'm the driver availability assistant for this dispatch team.\n\n"
    "Drivers: tell me when you're empty (\"Available\"), send your ZIP code, or tell me what time "
    "you'll be ready. Tell me when you get loaded and I'll update the list.\n\n"
    "Dispatchers: use /available to see the current list. Send /help for all commands."
)

HELP_DRIVERS = (
    "For drivers:\n"
    "• \"Available\" / \"I'm empty\": you're ready for a load (I'll ask for your ZIP)\n"
    "• \"19237\" or \"ZIP 19237\": your current location\n"
    "• \"Available at 2 PM\" / \"Tomorrow morning\": you'll be ready later\n"
    "• \"I'm loaded\" / \"No longer available\": take yourself off the list\n"
    "• /myid: show your Telegram ID"
)
HELP_ADMIN = (
    "\nFor dispatchers:\n"
    "/available: current list (Name, ZIP; Name, will be available TIME)\n"
    "/status: counts of available and later drivers\n"
    "/refresh: ask everyone to update (and send ZIP)\n"
    "/remove <name or ID> (or reply to a driver's message): deactivate a driver\n"
    "/pause, /resume: stop or restart automatic messages\n"
    "/setgroup: use this group as the dispatch group (run inside the group)\n"
    "/settime HH:MM: morning message time (24-hour)\n"
    "/settimezone <Zone>: for example America/Chicago\n"
    "/schedule: show the current schedule and settings"
)
