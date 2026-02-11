#!/usr/bin/env python3
"""
Скрипт для добавления VPN сервера в базу данных.

Использование:
    python add_server.py "Сервер 1" 72.56.100.176 443 "vI3LwMqn8ft4D2HWHVDf01bSf57Mo7Idx4vNiY6Zpic"
"""
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.database import init_database, add_server


def main():
    if len(sys.argv) < 5:
        print("Использование: python add_server.py <имя> <ip> <port> <public_key> [max_users]")
        print("Пример: python add_server.py 'Сервер 1' 72.56.100.176 443 'vI3LwM...' 60")
        sys.exit(1)

    name = sys.argv[1]
    ip = sys.argv[2]
    port = int(sys.argv[3])
    public_key = sys.argv[4]
    max_users = int(sys.argv[5]) if len(sys.argv) > 5 else 60

    # Инициализируем БД если не существует
    init_database()

    # Добавляем сервер
    server_id = add_server(name, ip, port, public_key, max_users=max_users)
    print(f"Готово! Сервер добавлен с ID: {server_id}")


if __name__ == "__main__":
    main()
