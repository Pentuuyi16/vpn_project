#!/usr/bin/env python3
"""
Генерация пула UUID для Xray сервера.

Запускать НА VPN СЕРВЕРЕ (где стоит Xray):
    python3 generate_pool.py 100

Или удалённо через SSH (с бот-сервера):
    scp generate_pool.py root@72.56.100.176:/tmp/
    ssh root@72.56.100.176 "python3 /tmp/generate_pool.py 100"

Скрипт:
1. Генерирует N UUID
2. Добавляет их в /usr/local/etc/xray/config.json
3. Перезапускает Xray ОДИН раз
4. Выводит JSON со списком UUID для импорта в БД бота
"""
import json
import uuid
import sys
import subprocess
import shutil
from datetime import datetime

XRAY_CONFIG_PATH = '/usr/local/etc/xray/config.json'


def main():
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 100

    # Читаем конфиг
    with open(XRAY_CONFIG_PATH, 'r') as f:
        config = json.load(f)

    # Находим VLESS inbound
    vless_inbound = None
    for inbound in config.get('inbounds', []):
        if inbound.get('protocol') == 'vless':
            vless_inbound = inbound
            break

    if not vless_inbound:
        print("ОШИБКА: VLESS inbound не найден!")
        sys.exit(1)

    clients = vless_inbound['settings']['clients']

    # Собираем существующие UUID
    existing_uuids = {c['id'] for c in clients}
    print(f"Существующих клиентов: {len(existing_uuids)}")

    # Генерируем новые UUID
    new_uuids = []
    for i in range(count):
        new_uuid = str(uuid.uuid4())
        while new_uuid in existing_uuids:
            new_uuid = str(uuid.uuid4())
        existing_uuids.add(new_uuid)

        email = f"pool_{i+1:04d}"
        new_client = {
            "id": new_uuid,
            "flow": "xtls-rprx-vision",
            "email": email
        }
        clients.append(new_client)
        new_uuids.append({"uuid": new_uuid, "email": email})

    # Бэкап конфига
    backup_path = f"{XRAY_CONFIG_PATH}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(XRAY_CONFIG_PATH, backup_path)
    print(f"Бэкап: {backup_path}")

    # Записываем конфиг
    with open(XRAY_CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=2)

    print(f"Добавлено {count} клиентов в конфиг")
    print(f"Всего клиентов: {len(clients)}")

    # Перезапускаем Xray ОДИН раз
    result = subprocess.run(['systemctl', 'restart', 'xray'], capture_output=True, text=True)
    if result.returncode == 0:
        print("Xray перезапущен успешно!")
    else:
        print(f"ОШИБКА перезапуска: {result.stderr}")
        sys.exit(1)

    # Выводим JSON для импорта в БД бота
    output = {"server_ip": "", "uuids": new_uuids}
    output_path = f"/tmp/pool_uuids.json"
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\nJSON сохранён: {output_path}")
    print(f"Скопируйте на бот-сервер и импортируйте:")
    print(f"  scp root@<VPN_IP>:{output_path} /tmp/")
    print(f"  python3 scripts/import_pool.py /tmp/pool_uuids.json <server_id>")


if __name__ == "__main__":
    main()