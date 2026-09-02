with open('/Users/gonzo/Desktop/V2/lyudyn-iskun-v2/bot/handlers.py', 'r') as f:
    content = f.read()

import re

old_handle_photo = re.search(r'@router\.message\(F\.photo\).*?(?=@router\.message|\Z)', content, re.DOTALL).group(0)

new_handle_photo = """@router.message(F.photo)
async def handle_photo(message: types.Message, bot: Bot):
    await message.answer("⏳ <b>Ініційовано глибокий OSINT-аналіз...</b>\\n1. Витягую EXIF-метадані...\\n2. Запускаю GeoSpy AI для візуальної геолокації...\\n3. Аналізую техніку та руйнування через Vision AI...", parse_mode=ParseMode.HTML)
    
    file_id = message.photo[-1].file_id
    file = await bot.get_file(file_id)
    file_path = file.file_path
    
    downloaded_file = await bot.download_file(file_path)
    file_bytes = downloaded_file.read()
    base64_image = base64.b64encode(file_bytes).decode('utf-8')
    
    # Save temp file for EXIF/GeoSpy
    temp_path = f"temp_{file_id}.jpg"
    with open(temp_path, "wb") as f_temp:
        f_temp.write(file_bytes)
        
    osint_report = "🔎 <b>РЕЗУЛЬТАТИ OSINT-АНАЛІЗУ</b>\\n\\n"
    
    # 1. EXIF Extraction
    from worker.osint.exif_extractor import EXIFExtractor
    exif = EXIFExtractor().extract(temp_path)
    if exif.get("has_gps"):
        osint_report += f"📡 <b>EXIF GPS:</b> {exif['latitude']}, {exif['longitude']}\\n"
        if exif.get("datetime"):
            osint_report += f"⏰ <b>EXIF Час:</b> {exif['datetime']}\\n"
    else:
        osint_report += "📡 <b>EXIF метадані:</b> Очищені або відсутні (можливо, фото з Telegram/Viber).\\n"

    # 2. GeoSpy AI
    from worker.osint.ai_geolocation import ai_geo
    try:
        geospy = await asyncio.to_thread(ai_geo.analyze_image, temp_path)
        if geospy and geospy.get("coordinates"):
            osint_report += f"🌍 <b>GeoSpy AI (Візуальна локація):</b> {geospy.get('predicted_location', 'Знайдено')}\\n"
            osint_report += f"📍 <b>Координати:</b> {geospy['coordinates'][0]}, {geospy['coordinates'][1]}\\n"
    except:
        pass
        
    if os.path.exists(temp_path):
        os.remove(temp_path)
        
    osint_report += "\\n"

    if not OPENAI_API_KEY:
        await message.answer("❌ OPENAI_API_KEY не знайдено.")
        return

    def call_openai():
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENAI_API_KEY}"
        }
        sys_prompt = (
            "Ти військовий OSINT-аналітик. Твоя задача зробити детальний аналіз фото.\\n"
            "Поверни звіт у такому форматі (використовуй емодзі):\\n"
            "🛡 <b>Військова техніка/Зброя:</b> [Що ідентифіковано]\\n"
            "🔥 <b>Характер уражень:</b> [Ступінь і тип]\\n"
            "🌤 <b>Погода/Освітлення:</b> [Для крос-чеку часу]\\n"
            "⚠️ <b>Оцінка достовірності:</b> [Чи є ознаки фотошопу/старого фото]"
        )
        data = {
            "model": "gpt-4o-mini",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": sys_prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                    ]
                }
            ],
            "max_tokens": 500,
            "temperature": 0.1
        }
        return requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=data)

    try:
        resp = await asyncio.to_thread(call_openai)
        if resp.status_code == 200:
            result = resp.json()["choices"][0]["message"]["content"]
            osint_report += result
            await message.answer(osint_report, parse_mode=ParseMode.HTML)
        else:
            await message.answer(f"❌ Помилка Vision API: {resp.status_code}")
    except Exception as e:
        await message.answer(f"❌ Помилка під час аналізу: {str(e)}")

"""

content = content.replace(old_handle_photo, new_handle_photo)

with open('/Users/gonzo/Desktop/V2/lyudyn-iskun-v2/bot/handlers.py', 'w') as f:
    f.write(content)
