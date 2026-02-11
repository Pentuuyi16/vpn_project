#!/bin/bash

echo "Установка VPN Bot..."

apt update
apt install -y python3 python3-pip python3-venv

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt

python3 -c "from api.database import init_database; init_database()"

echo ""
echo "Готово! Следующие шаги:"
echo "1. Добавьте сервер: python3 scripts/add_server.py 'Сервер 1' IP PORT PUBLIC_KEY"
echo "2. Запустите: python3 bot/main.py"
