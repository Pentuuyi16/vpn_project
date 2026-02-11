import subprocess
import json
import sqlite3
import uuid as uuid_lib
from datetime import datetime, timedelta
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bot.config import DB_FILE, XRAY_CONFIG_PATH


class VPNManager:
    def __init__(self):
        self.db_file = DB_FILE

    def _get_connection(self):
        """Получить подключение к БД"""
        conn = sqlite3.connect(self.db_file)
        conn.row_factory = sqlite3.Row
        return conn

    def _ssh_command(self, server, command):
        """Выполняет команду на сервере по SSH"""
        ssh_cmd = f"ssh -o StrictHostKeyChecking=no {server['ssh_user']}@{server['ip']} \"{command}\""
        try:
            result = subprocess.run(ssh_cmd, shell=True, capture_output=True, text=True, timeout=30)
            return result.stdout.strip(), result.returncode == 0
        except Exception as e:
            print(f"SSH ошибка: {e}")
            return str(e), False

    def generate_uuid(self):
        """Генерирует UUID"""
        return str(uuid_lib.uuid4())

    def get_available_server(self):
        """Находит сервер с свободными местами"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT s.*,
                    (SELECT COUNT(*) FROM subscriptions sub
                     WHERE sub.server_id = s.id AND sub.is_active = 1) as current_users
                FROM servers s
                WHERE s.is_active = 1
                AND (SELECT COUNT(*) FROM subscriptions sub
                     WHERE sub.server_id = s.id AND sub.is_active = 1) < s.max_users
                ORDER BY current_users ASC
                LIMIT 1
            """)

            server = cursor.fetchone()
            return dict(server) if server else None
        finally:
            conn.close()

    def get_server_by_id(self, server_id):
        """Получает сервер по ID"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT * FROM servers WHERE id = ?", (server_id,))
            server = cursor.fetchone()
            return dict(server) if server else None
        finally:
            conn.close()

    def create_vless_link(self, uuid, server, name="VPN"):
        """Создает VLESS ссылку для клиента"""
        return (
            f"vless://{uuid}@{server['ip']}:{server['port']}"
            f"?encryption=none&flow=xtls-rprx-vision&security=reality"
            f"&sni=www.microsoft.com&fp=chrome&pbk={server['public_key']}"
            f"&type=tcp&headerType=none#{name}"
        )

    def add_client_to_xray(self, server, uuid, email):
        """Добавляет клиента в конфиг Xray через SSH"""
        # Читаем текущий конфиг
        read_cmd = f"cat {XRAY_CONFIG_PATH}"
        config_str, success = self._ssh_command(server, read_cmd)

        if not success:
            print(f"Не удалось прочитать конфиг: {config_str}")
            return False

        try:
            config = json.loads(config_str)
        except json.JSONDecodeError as e:
            print(f"Ошибка парсинга конфига: {e}")
            return False

        # Добавляем клиента
        new_client = {
            "id": uuid,
            "flow": "xtls-rprx-vision",
            "email": email
        }

        config['inbounds'][0]['settings']['clients'].append(new_client)

        # Записываем обновленный конфиг
        config_json = json.dumps(config, indent=2).replace('"', '\\"')
        write_cmd = f'echo "{config_json}" > {XRAY_CONFIG_PATH}'
        _, success = self._ssh_command(server, write_cmd)

        if not success:
            return False

        # Перезапускаем Xray
        _, success = self._ssh_command(server, "systemctl restart xray")
        return success

    def remove_client_from_xray(self, server, uuid):
        """Удаляет клиента из конфига Xray через SSH"""
        read_cmd = f"cat {XRAY_CONFIG_PATH}"
        config_str, success = self._ssh_command(server, read_cmd)

        if not success:
            return False

        try:
            config = json.loads(config_str)
        except:
            return False

        # Удаляем клиента
        clients = config['inbounds'][0]['settings']['clients']
        config['inbounds'][0]['settings']['clients'] = [c for c in clients if c['id'] != uuid]

        # Записываем и перезапускаем
        config_json = json.dumps(config, indent=2).replace('"', '\\"')
        write_cmd = f'echo "{config_json}" > {XRAY_CONFIG_PATH}'
        self._ssh_command(server, write_cmd)
        self._ssh_command(server, "systemctl restart xray")
        return True

    def create_subscription(self, telegram_id, username, duration_days=30):
        """Создает новую подписку для пользователя"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            # Находим доступный сервер
            server = self.get_available_server()
            if not server:
                print("Нет доступных серверов")
                return None

            # Проверяем/создаем пользователя
            cursor.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,))
            user = cursor.fetchone()

            if not user:
                cursor.execute(
                    "INSERT INTO users (telegram_id, username) VALUES (?, ?)",
                    (telegram_id, username)
                )
                user_id = cursor.lastrowid
            else:
                user_id = user[0]

            # Генерируем UUID
            client_uuid = self.generate_uuid()
            email = f"user_{telegram_id}_{int(datetime.now().timestamp())}"

            # Создаем ссылку
            config_link = self.create_vless_link(client_uuid, server, f"VPN_{username or telegram_id}")

            # Добавляем в Xray на сервере
            if not self.add_client_to_xray(server, client_uuid, email):
                print("Не удалось добавить клиента в Xray")
                return None

            # Сохраняем в БД
            expires_at = datetime.now() + timedelta(days=duration_days)
            cursor.execute("""
                INSERT INTO subscriptions (user_id, server_id, uuid, config_link, expires_at)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, server['id'], client_uuid, config_link, expires_at.strftime('%Y-%m-%d %H:%M:%S')))

            conn.commit()

            return {
                'uuid': client_uuid,
                'config_link': config_link,
                'expires_at': expires_at.strftime('%Y-%m-%d %H:%M:%S'),
                'server_name': server['name']
            }
        except Exception as e:
            print(f"Ошибка создания подписки: {e}")
            conn.rollback()
            return None
        finally:
            conn.close()

    def get_active_subscription(self, telegram_id):
        """Получает активную подписку пользователя"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT sub.*, srv.name as server_name
                FROM subscriptions sub
                JOIN users u ON sub.user_id = u.id
                JOIN servers srv ON sub.server_id = srv.id
                WHERE u.telegram_id = ? AND sub.is_active = 1
                ORDER BY sub.expires_at DESC LIMIT 1
            """, (telegram_id,))

            result = cursor.fetchone()
            return dict(result) if result else None
        finally:
            conn.close()

    def deactivate_subscription(self, subscription_id):
        """Деактивирует подписку"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            # Получаем подписку и сервер
            cursor.execute("""
                SELECT sub.uuid, sub.server_id FROM subscriptions sub
                WHERE sub.id = ?
            """, (subscription_id,))
            sub = cursor.fetchone()

            if not sub:
                return False

            server = self.get_server_by_id(sub['server_id'])
            if server:
                self.remove_client_from_xray(server, sub['uuid'])

            cursor.execute("UPDATE subscriptions SET is_active = 0 WHERE id = ?", (subscription_id,))
            conn.commit()
            return True
        except Exception as e:
            print(f"Ошибка деактивации: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def check_expired_subscriptions(self):
        """Проверяет и блокирует просроченные подписки"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT id FROM subscriptions
                WHERE is_active = 1 AND expires_at < datetime('now')
            """)

            expired = cursor.fetchall()
            count = 0

            for row in expired:
                if self.deactivate_subscription(row['id']):
                    count += 1

            return count
        finally:
            conn.close()

    def get_all_servers(self):
        """Получает список всех серверов со статистикой"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT s.*,
                    (SELECT COUNT(*) FROM subscriptions sub
                     WHERE sub.server_id = s.id AND sub.is_active = 1) as current_users
                FROM servers s
                ORDER BY s.id
            """)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_stats(self):
        """Получает общую статистику"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT COUNT(*) FROM users")
            total_users = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM subscriptions WHERE is_active = 1")
            active_subs = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM servers WHERE is_active = 1")
            active_servers = cursor.fetchone()[0]

            return {
                'total_users': total_users,
                'active_subscriptions': active_subs,
                'active_servers': active_servers
            }
        finally:
            conn.close()
