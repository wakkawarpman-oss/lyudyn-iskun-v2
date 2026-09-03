import re
content = open("bot/handlers.py").read()

if "from bot.broadcaster import broadcaster" not in content:
    content = content.replace("import redis\nimport os", "import redis\nimport os\nfrom bot.broadcaster import broadcaster")

old_safe_send = """async def safe_send(bot, chat_id, text, **kwargs):
    try:
        await bot.send_message(chat_id, text, **kwargs)
    except Exception as e:
        logger.error(f"Error sending message to {chat_id}: {e}")"""

new_safe_send = """async def safe_send(bot, chat_id, text, **kwargs):
    try:
        if broadcaster:
            await broadcaster.enqueue(
                chat_id=chat_id, 
                text=text, 
                parse_mode=kwargs.get("parse_mode", "Markdown"),
                disable_web_page_preview=kwargs.get("disable_web_page_preview", True)
            )
        else:
            await bot.send_message(chat_id, text, **kwargs)
    except Exception as e:
        logger.error(f"Error sending message to {chat_id}: {e}")"""

if "await broadcaster.enqueue" not in content:
    content = content.replace(old_safe_send, new_safe_send)
    open("bot/handlers.py", "w").write(content)
