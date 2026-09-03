import re
content = open("bot/main.py").read()

import_statement = "from bot.broadcaster import init_broadcaster"
if import_statement not in content:
    content = content.replace("from bot.critical_alerts import CriticalAlertSystem", "from bot.critical_alerts import CriticalAlertSystem\n" + import_statement)

init_statement = """    # Initialize broadcaster
    broadcaster = init_broadcaster(bot, os.getenv("REDIS_URL", "redis://redis:6379/0"))
    await broadcaster.start()"""

if "init_broadcaster" not in content.split("async def main():")[1]:
    content = content.replace("bot = Bot(token=BOT_TOKEN)", f"bot = Bot(token=BOT_TOKEN)\n{init_statement}")

open("bot/main.py", "w").write(content)
