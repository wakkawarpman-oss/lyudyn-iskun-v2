import re

content = open("bot/broadcaster.py").read()

new_content = content + "\n\nbroadcaster = None\n\ndef init_broadcaster(bot, redis_url):\n    global broadcaster\n    broadcaster = RedisBroadcaster(bot, redis_url)\n    return broadcaster\n"

open("bot/broadcaster.py", "w").write(new_content)
