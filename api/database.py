import sqlite3
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bot.config import DB_FILE


def init_database():
    """Создает таблицы в базе данных"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Таблица пользователей
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE NOT NULL,
            username TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Таблица VPN серверов
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS servers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            ip TEXT NOT NULL,
            port INTEGER DEFAULT 443,
            public_key TEXT NOT NULL,
            ssh_user TEXT DEFAULT 'root',
            ssh_port INTEGER DEFAULT 22,
            max_users INTEGER DEFAULT 60,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Таблица подписок
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            uuid TEXT UNIQUE NOT NULL,
            subscription_token TEXT UNIQUE NOT NULL,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # Таблица связи подписок и серверов (many-to-many)
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

    # Пул предгенерированных UUID (уже добавлены в Xray конфиг)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS uuid_pool (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uuid TEXT NOT NULL,
            email TEXT NOT NULL,
            server_id INTEGER NOT NULL,
            is_used INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (server_id) REFERENCES servers(id),
            UNIQUE(uuid, server_id)
        )
    """)

    conn.commit()
    conn.close()
    print("База данных инициализирована")


def add_server(name, ip, port, public_key, ssh_user='root', max_users=60):
    """Добавляет новый VPN сервер"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO servers (name, ip, port, public_key, ssh_user, max_users)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (name, ip, port, public_key, ssh_user, max_users))

    conn.commit()
    server_id = cursor.lastrowid
    conn.close()

    print(f"Сервер '{name}' добавлен с ID: {server_id}")
    return server_id


def import_uuid_pool(uuids, server_id):
    """Импортирует пул UUID в базу данных"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    count = 0
    for item in uuids:
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO uuid_pool (uuid, email, server_id)
                VALUES (?, ?, ?)
            """, (item['uuid'], item['email'], server_id))
            if cursor.rowcount > 0:
                count += 1
        except Exception as e:
            print(f"Ошибка импорта {item['uuid']}: {e}")

    conn.commit()
    conn.close()
    return count


if __name__ == "__main__":
    init_database()