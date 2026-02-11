from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup


def main_menu():
    """Главное меню"""
    keyboard = [
        ['Мой ключ', 'Купить подписку'],
        ['Инструкция', 'Поддержка'],
        ['Статистика']
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def buy_subscription_menu():
    """Меню выбора тарифа"""
    keyboard = [
        [
            InlineKeyboardButton("1 месяц - 300р", callback_data="buy_1_month"),
            InlineKeyboardButton("3 месяца - 800р", callback_data="buy_3_months")
        ],
        [
            InlineKeyboardButton("6 месяцев - 1500р", callback_data="buy_6_months"),
            InlineKeyboardButton("12 месяцев - 2500р", callback_data="buy_12_months")
        ],
        [InlineKeyboardButton("Назад", callback_data="back_to_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)


def admin_menu():
    """Меню администратора"""
    keyboard = [
        [InlineKeyboardButton("Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("Сервера", callback_data="admin_servers")],
        [InlineKeyboardButton("Проверить просроченные", callback_data="admin_check_expired")]
    ]
    return InlineKeyboardMarkup(keyboard)


def servers_menu(servers):
    """Меню списка серверов"""
    keyboard = []

    for server in servers:
        status = "ON" if server['is_active'] else "OFF"
        text = f"{server['name']} [{server['current_users']}/{server['max_users']}] {status}"
        keyboard.append([InlineKeyboardButton(text, callback_data=f"server_{server['id']}")])

    keyboard.append([InlineKeyboardButton("Назад", callback_data="back_to_admin")])
    return InlineKeyboardMarkup(keyboard)
