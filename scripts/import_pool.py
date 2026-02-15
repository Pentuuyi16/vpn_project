#!/usr/bin/env python3
"""
Импорт пула UUID в базу данных бота.

Использование:
    python3 import_pool.py /tmp/pool_uuids.json <server_id>

server_id — ID сервера из таблицы servers в БД бота.
"""
import json
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from api.database import init_database, import_uuid_pool


def main():
    if len(sys.argv) < 3:
        print("Использование: python3 import_pool.py <pool_file.json> <server_id>")
        sys.exit(1)

    pool_file = sys.argv[1]
    server_id = int(sys.argv[2])

    with open(pool_file, 'r') as f:
        data = json.load(f)

    init_database()

    count = import_uuid_pool(data['uuids'], server_id)
    print(f"Импортировано {count} UUID для сервера {server_id}")


if __name__ == "__main__":
    main()