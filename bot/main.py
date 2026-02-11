import logging
import sys
import os
from datetime import datetime
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes
)

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.config import TELEGRAM_BOT_TOKEN, ADMIN_TELEGRAM_ID
from bot.keyboards import main_menu, buy_subscription_menu, admin_menu, servers_menu
from api.vpn_manager import VPNManager
from api.database import init_database

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Инициализация
vpn_manager = VPNManager()


# ============== КОМАНДЫ ==============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    user = update.effective_user

    await update.message.reply_text(
        f"Привет, {user.first_name}!\n\n"
        f"Я бот для управления VPN подписками.\n\n"
        f"Выбери действие:",
        reply_markup=main_menu()
    )


async def my_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать ключ пользователя"""
    telegram_id = update.effective_user.id
    subscription = vpn_manager.get_active_subscription(telegram_id)

    if not subscription:
        await update.message.reply_text(
            "У вас нет активной подписки.\n\n"
            "Нажмите 'Купить подписку' чтобы получить ключ.",
            reply_markup=main_menu()
        )
        return

    expires_at = datetime.strptime(subscription['expires_at'], '%Y-%m-%d %H:%M:%S')
    days_left = (expires_at - datetime.now()).days

    await update.message.reply_text(
        f"Ваш ключ доступа:\n\n"
        f"<code>{subscription['config_link']}</code>\n\n"
        f"Сервер: {subscription.get('server_name', 'N/A')}\n"
        f"Действует до: {expires_at.strftime('%d.%m.%Y')}\n"
        f"Осталось дней: {days_left}\n\n"
        f"Нажмите на ключ чтобы скопировать",
        parse_mode='HTML',
        reply_markup=main_menu()
    )


async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню покупки подписки"""
    # Проверяем есть ли доступные сервера
    server = vpn_manager.get_available_server()

    if not server:
        await update.message.reply_text(
            "К сожалению, все сервера заполнены.\n"
            "Попробуйте позже или обратитесь в поддержку.",
            reply_markup=main_menu()
        )
        return

    await update.message.reply_text(
        "Выберите тариф:\n\n"
        "1 месяц - 300 руб\n"
        "3 месяца - 800 руб (экономия 100 руб)\n"
        "6 месяцев - 1500 руб (экономия 300 руб)\n"
        "12 месяцев - 2500 руб (экономия 1100 руб)",
        reply_markup=buy_subscription_menu()
    )


async def instruction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Инструкция по подключению"""
    await update.message.reply_text(
        "Инструкция по подключению:\n\n"
        "1. Скачайте приложение:\n"
        "   iOS: v2rayTUN или Happ\n"
        "   Android: v2rayNG\n\n"
        "2. Купите подписку и получите ключ\n\n"
        "3. Скопируйте ключ (нажмите на него)\n\n"
        "4. В приложении нажмите + и выберите\n"
        "   'Import from clipboard'\n\n"
        "5. Подключитесь к VPN\n\n"
        "Готово!",
        reply_markup=main_menu()
    )


async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Контакты поддержки"""
    await update.message.reply_text(
        "Поддержка:\n\n"
        "Telegram: @your_support\n\n"
        "Отвечаем в течение 1 часа",
        reply_markup=main_menu()
    )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика пользователя"""
    telegram_id = update.effective_user.id
    subscription = vpn_manager.get_active_subscription(telegram_id)

    if not subscription:
        await update.message.reply_text(
            "Статистика:\n\n"
            "Нет активной подписки",
            reply_markup=main_menu()
        )
        return

    expires_at = datetime.strptime(subscription['expires_at'], '%Y-%m-%d %H:%M:%S')
    created_at = datetime.strptime(subscription['created_at'], '%Y-%m-%d %H:%M:%S')
    days_left = max(0, (expires_at - datetime.now()).days)
    days_used = (datetime.now() - created_at).days

    await update.message.reply_text(
        f"Ваша статистика:\n\n"
        f"Статус: Активна\n"
        f"Сервер: {subscription.get('server_name', 'N/A')}\n"
        f"Подписка до: {expires_at.strftime('%d.%m.%Y')}\n"
        f"Осталось дней: {days_left}\n"
        f"Использовано дней: {days_used}",
        reply_markup=main_menu()
    )


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Админ панель"""
    telegram_id = update.effective_user.id

    if telegram_id != ADMIN_TELEGRAM_ID:
        await update.message.reply_text("Доступ запрещен")
        return

    await update.message.reply_text(
        "Админ панель",
        reply_markup=admin_menu()
    )


# ============== ОБРАБОТЧИКИ КНОПОК ==============

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик inline кнопок"""
    query = update.callback_query
    await query.answer()

    data = query.data
    telegram_id = query.from_user.id

    # Покупка подписки
    if data.startswith("buy_"):
        plan = data.replace("buy_", "")
        username = query.from_user.username

        plan_days = {
            "1_month": 30,
            "3_months": 90,
            "6_months": 180,
            "12_months": 365
        }

        days = plan_days.get(plan, 30)

        await query.edit_message_text("Создаю подписку...")

        result = vpn_manager.create_subscription(telegram_id, username, days)

        if result:
            expires_date = datetime.strptime(result['expires_at'], '%Y-%m-%d %H:%M:%S')

            await query.edit_message_text(
                f"Подписка активирована!\n\n"
                f"Тариф: {get_plan_name(plan)}\n"
                f"Сервер: {result.get('server_name', 'N/A')}\n"
                f"Действует до: {expires_date.strftime('%d.%m.%Y %H:%M')}\n\n"
                f"Ваш ключ доступа:\n\n"
                f"<code>{result['config_link']}</code>\n\n"
                f"Нажмите на ключ чтобы скопировать\n"
                f"Инструкция: /start -> Инструкция",
                parse_mode='HTML'
            )
        else:
            await query.edit_message_text(
                "Ошибка создания подписки.\n\n"
                "Возможно нет доступных серверов.\n"
                "Обратитесь в поддержку."
            )

    # Админ команды
    elif data == "admin_stats":
        if telegram_id != ADMIN_TELEGRAM_ID:
            return

        stats = vpn_manager.get_stats()
        servers = vpn_manager.get_all_servers()

        servers_info = "\n".join([
            f"  {s['name']}: {s['current_users']}/{s['max_users']}"
            for s in servers
        ]) or "  Нет серверов"

        await query.edit_message_text(
            f"Статистика:\n\n"
            f"Всего пользователей: {stats['total_users']}\n"
            f"Активных подписок: {stats['active_subscriptions']}\n"
            f"Серверов: {stats['active_servers']}\n\n"
            f"Сервера:\n{servers_info}",
            reply_markup=admin_menu()
        )

    elif data == "admin_servers":
        if telegram_id != ADMIN_TELEGRAM_ID:
            return

        servers = vpn_manager.get_all_servers()
        await query.edit_message_text(
            "Управление серверами:",
            reply_markup=servers_menu(servers)
        )

    elif data == "admin_check_expired":
        if telegram_id != ADMIN_TELEGRAM_ID:
            return

        count = vpn_manager.check_expired_subscriptions()
        await query.edit_message_text(
            f"Проверка завершена\n\n"
            f"Деактивировано подписок: {count}",
            reply_markup=admin_menu()
        )

    elif data == "back_to_menu":
        await query.message.delete()

    elif data == "back_to_admin":
        await query.edit_message_text(
            "Админ панель",
            reply_markup=admin_menu()
        )


def get_plan_name(plan):
    """Получить название тарифа"""
    names = {
        "1_month": "1 месяц - 300 руб",
        "3_months": "3 месяца - 800 руб",
        "6_months": "6 месяцев - 1500 руб",
        "12_months": "12 месяцев - 2500 руб"
    }
    return names.get(plan, "Неизвестный тариф")


# ============== ТЕКСТОВЫЕ СООБЩЕНИЯ ==============

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых кнопок"""
    text = update.message.text

    handlers = {
        "Мой ключ": my_key,
        "Купить подписку": buy,
        "Инструкция": instruction,
        "Поддержка": support,
        "Статистика": stats,
    }

    handler = handlers.get(text)
    if handler:
        await handler(update, context)


# ============== MAIN ==============

def main():
    """Запуск бота"""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN не задан!")
        return

    # Инициализируем БД
    init_database()

    # Создаем приложение
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Регистрируем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    # Запускаем бота
    logger.info("Бот запущен!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
