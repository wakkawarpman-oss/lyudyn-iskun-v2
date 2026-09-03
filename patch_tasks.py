import sys

content = open("worker/tasks.py").read()

old_str = 'if not llm_data.get("is_kyiv_region", False):'
new_str = '''is_kyiv_region = llm_data.get("is_kyiv_region", False)
    channel_clean = payload.get("channel", "").lstrip("@").lower()
    kyiv_channels = ["1181169156", "kyivlive", "kyiv_novosti", "t_kyiv", "kyiv_alarm", "vakyiv", "kyivcityofficial", "los_solomas", "kyivoperat", "kyivoperativ", "kontur_map"]
    if channel_clean in kyiv_channels:
        is_kyiv_region = True
    if not is_kyiv_region:'''

if old_str in content:
    content = content.replace(old_str, new_str)
    open("worker/tasks.py", "w").write(content)
    print("Patched successfully!")
else:
    print("Could not find old_str!")
