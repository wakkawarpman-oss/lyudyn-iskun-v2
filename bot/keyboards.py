from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder

def get_main_keyboard():
    """Ergonomic, high-efficiency tactical keyboard for mobile devices."""
    builder = ReplyKeyboardBuilder()
    # Row 1: Immediate Safety & Alerts
    builder.button(text="🟢 ВІДБІЙ МОНІТОРИНГ")
    builder.button(text="🛸 Радар Контур")
    # Row 2: Location & City Logistics
    builder.button(text="📍 Мій район")
    builder.button(text="🚇 Метро & Транспорт")
    # Row 3: Tactical Threat Overview & Map
    builder.button(text="🎯 Прогноз загроз")
    builder.button(text="🌐 Веб-мапа")
    # Row 4: Instant Data Sync & Deep Tools
    builder.button(text="🔄 АКТУАЛІЗАЦІЯ ПОДІЙ")
    builder.button(text="🎛 Більше функцій...")
    builder.adjust(2, 2, 2, 2)
    return builder.as_markup(resize_keyboard=True)

def get_more_keyboard():
    """Secondary keyboard for deep intelligence, satellite feeds, and system tools."""
    builder = ReplyKeyboardBuilder()
    builder.button(text="🔥 Супутник NASA")
    builder.button(text="🕸️ Мережа ІПСО")
    builder.button(text="🎖 Ключові інциденти")
    builder.button(text="💥 Резонанс")
    builder.button(text="📊 Аналітика")
    builder.button(text="📋 Звіт (12 год)")
    builder.button(text="📡 Статус системи")
    builder.button(text="📈 Графік активності")
    builder.button(text="📊 Експорт CSV")
    builder.button(text="🔑 Мій ключ")
    builder.button(text="🐾 ТУПО МЯВ")
    builder.button(text="🔙 Головне меню")
    builder.adjust(2, 2, 2, 2, 2, 2)
    return builder.as_markup(resize_keyboard=True)

def get_more_inline_keyboard():
    """Inline widget for advanced intelligence functions."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔥 Супутник NASA", callback_data="more:satellite")
    builder.button(text="🕸️ Мережа ІПСО", callback_data="more:network")
    builder.button(text="🎖 Ключові інциденти", callback_data="more:top")
    builder.button(text="📊 Аналітика", callback_data="more:analytics")
    builder.button(text="📋 Звіт (12 год)", callback_data="more:report")
    builder.button(text="📡 Статус", callback_data="more:status")
    builder.button(text="🔑 API Ключ", callback_data="more:key")
    builder.button(text="🐾 Муркотіння", callback_data="more:meow")
    builder.adjust(2, 2, 2, 2)
    return builder.as_markup()
