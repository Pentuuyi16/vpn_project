#!/usr/bin/env python3
"""
Миграция базы данных для поддержки нескольких серверов на одну подписку
"""
import sqlite3
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bot.config import DB_FILE


def migrate():
    """Выполняет миграцию базы данных"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    try:
        print("Начинаю миграцию...")

        # 1. Создаем новую таблицу subscription_servers
        print("Создаю таблицу subscription_servers...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS subscription_servers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subscription_id INTEGER NOT NULL,
                server_id INTEGER NOT NULL,
                config_link TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (subscription_id) REFERENCES subscriptions(id),
                FOREIGN KEY (server_id) REFERENCES servers(id),
                UNIQUE(subscription_id, server_id)
            )
        """)

        # 2. Проверяем есть ли колонка subscription_token в subscriptions
        cursor.execute("PRAGMA table_info(subscriptions)")
        columns = [col[1] for col in cursor.fetchall()]

        if 'subscription_token' not in columns:
            print("Добавляю колонку subscription_token...")
            cursor.execute("""
                ALTER TABLE subscriptions ADD COLUMN subscription_token TEXT
            """)

            # Генерируем токены для существующих подписок
            import uuid
            cursor.execute("SELECT id FROM subscriptions")
            for row in cursor.fetchall():
                token = str(uuid.uuid4())
                cursor.execute("UPDATE subscriptions SET subscription_token = ? WHERE id = ?",
                             (token, row[0]))

        # 3. Мигрируем данные из subscriptions в subscription_servers
        print("Мигрирую существующие подписки...")
        cursor.execute("""
            SELECT id, server_id, config_link
            FROM subscriptions
            WHERE server_id IS NOT NULL
        """)

        existing_subs = cursor.fetchall()
        for sub_id, server_id, config_link in existing_subs:
            try:
                cursor.execute("""
                    INSERT OR IGNORE INTO subscription_servers
                    (subscription_id, server_id, config_link)
                    VALUES (?, ?, ?)
                """, (sub_id, server_id, config_link))
            except Exception as e:
                print(f"Предупреждение: не удалось мигрировать подписку {sub_id}: {e}")

        conn.commit()
        print("Миграция завершена успешно!")
        print(f"Мигрировано подписок: {len(existing_subs)}")

        # Показываем статистику
        cursor.execute("SELECT COUNT(*) FROM subscription_servers")
        count = cursor.fetchone()[0]
        print(f"Записей в subscription_servers: {count}")

    except Exception as e:
        print(f"Ошибка миграции: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

    return True


if __name__ == "__main__":
    if migrate():
        print("\n✓ Миграция выполнена успешно!")
        sys.exit(0)
    else:
        print("\n✗ Ошибка миграции!")
        sys.exit(1)
