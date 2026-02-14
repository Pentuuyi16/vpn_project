import subprocess
import json
import sqlite3
import uuid as uuid_lib
from datetime import datetime, timedelta
import os
import sys
import logging
import base64

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bot.config import DB_FILE, XRAY_CONFIG_PATH

logger = logging.getLogger(__name__)


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
        logger.info(f"SSH команда: {ssh_cmd[:100]}...")
        try:
            result = subprocess.run(ssh_cmd, shell=True, capture_output=True, text=True, timeout=30)
            logger.info(f"SSH код: {result.returncode}, stdout: {result.stdout[:200] if result.stdout else 'пусто'}, stderr: {result.stderr[:200] if result.stderr else 'пусто'}")
            return result.stdout.strip(), result.returncode == 0
        except Exception as e:
            logger.error(f"SSH ошибка: {e}")
            return str(e), False

    def generate_uuid(self):
        """Генерирует UUID"""
        return str(uuid_lib.uuid4())

    def get_available_servers(self):
        """Получает все доступные серверы с свободными местами"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT s.*,
                    (SELECT COUNT(DISTINCT ss.subscription_id)
                     FROM subscription_servers ss
                     JOIN subscriptions sub ON ss.subscription_id = sub.id
                     WHERE ss.server_id = s.id AND sub.is_active = 1) as current_users
                FROM servers s
                WHERE s.is_active = 1
                AND (SELECT COUNT(DISTINCT ss.subscription_id)
                     FROM subscription_servers ss
                     JOIN subscriptions sub ON ss.subscription_id = sub.id
                     WHERE ss.server_id = s.id AND sub.is_active = 1) < s.max_users
                ORDER BY current_users ASC
            """)

            servers = cursor.fetchall()
            return [dict(server) for server in servers]
        finally:
            conn.close()

    def get_available_server(self):
        """Находит один сервер с свободными местами (для обратной совместимости)"""
        servers = self.get_available_servers()
        return servers[0] if servers else None

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
        logger.info(f"Добавляю клиента {email} на сервер {server['ip']}")

        # Читаем текущий конфиг
        read_cmd = f"cat {XRAY_CONFIG_PATH}"
        config_str, success = self._ssh_command(server, read_cmd)

        if not success:
            logger.error(f"Не удалось прочитать конфиг: {config_str}")
            return False

        try:
            config = json.loads(config_str)
            logger.info("Конфиг успешно прочитан")
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга конфига: {e}, данные: {config_str[:500]}")
            return False

        # Добавляем клиента
        new_client = {
            "id": uuid,
            "flow": "xtls-rprx-vision",
            "email": email
        }

        config['inbounds'][0]['settings']['clients'].append(new_client)
        logger.info(f"Клиент добавлен в конфиг, всего клиентов: {len(config['inbounds'][0]['settings']['clients'])}")

        # Записываем обновленный конфиг
        config_json = json.dumps(config)
        config_b64 = base64.b64encode(config_json.encode()).decode()
        write_cmd = f'echo {config_b64} | base64 -d > {XRAY_CONFIG_PATH}'
        _, success = self._ssh_command(server, write_cmd)

        if not success:
            logger.error("Не удалось записать конфиг")
            return False

        logger.info("Конфиг записан, перезапускаю xray")

        # Перезапускаем Xray
        _, success = self._ssh_command(server, "systemctl restart xray")
        if success:
            logger.info("Xray перезапущен успешно")
        else:
            logger.error("Ошибка перезапуска xray")
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
        """Создает новую подписку для пользователя на всех доступных серверах"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            # Находим все доступные серверы
            servers = self.get_available_servers()
            if not servers:
                logger.error("Нет доступных серверов")
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

            # Генерируем один UUID для всех серверов
            client_uuid = self.generate_uuid()
            subscription_token = self.generate_uuid()  # Токен для subscription URL
            email = f"user_{telegram_id}_{int(datetime.now().timestamp())}"

            # Создаем подписку
            expires_at = datetime.now() + timedelta(days=duration_days)
            cursor.execute("""
                INSERT INTO subscriptions (user_id, uuid, subscription_token, expires_at)
                VALUES (?, ?, ?, ?)
            """, (user_id, client_uuid, subscription_token, expires_at.strftime('%Y-%m-%d %H:%M:%S')))

            subscription_id = cursor.lastrowid

            # Добавляем клиента на каждый сервер
            config_links = []
            server_names = []

            for server in servers:
                # Создаем VLESS ссылку для этого сервера
                server_name = server['name']
                config_link = self.create_vless_link(
                    client_uuid,
                    server,
                    server_name
                )

                # Добавляем клиента в Xray на сервере
                if not self.add_client_to_xray(server, client_uuid, email):
                    logger.error(f"Не удалось добавить клиента на сервер {server_name}")
                    # Продолжаем с другими серверами
                    continue

                # Сохраняем связь подписка-сервер
                cursor.execute("""
                    INSERT INTO subscription_servers (subscription_id, server_id, config_link)
                    VALUES (?, ?, ?)
                """, (subscription_id, server['id'], config_link))

                config_links.append(config_link)
                server_names.append(server_name)

            if not config_links:
                logger.error("Не удалось добавить клиента ни на один сервер")
                conn.rollback()
                return None

            conn.commit()

            return {
                'uuid': client_uuid,
                'subscription_token': subscription_token,
                'config_links': config_links,
                'server_names': server_names,
                'expires_at': expires_at.strftime('%Y-%m-%d %H:%M:%S'),
                # Для обратной совместимости
                'config_link': config_links[0] if config_links else None,
                'server_name': ', '.join(server_names)
            }
        except Exception as e:
            logger.error(f"Ошибка создания подписки: {e}")
            conn.rollback()
            return None
        finally:
            conn.close()

    def get_active_subscription(self, telegram_id):
        """Получает активную подписку пользователя со всеми серверами"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT sub.*
                FROM subscriptions sub
                JOIN users u ON sub.user_id = u.id
                WHERE u.telegram_id = ? AND sub.is_active = 1
                ORDER BY sub.expires_at DESC LIMIT 1
            """, (telegram_id,))

            result = cursor.fetchone()
            if not result:
                return None

            subscription = dict(result)

            # Получаем все сервера для этой подписки
            cursor.execute("""
                SELECT ss.config_link, srv.name as server_name, srv.ip
                FROM subscription_servers ss
                JOIN servers srv ON ss.server_id = srv.id
                WHERE ss.subscription_id = ?
                ORDER BY srv.name
            """, (subscription['id'],))

            servers_data = cursor.fetchall()
            if servers_data:
                subscription['config_links'] = [dict(s)['config_link'] for s in servers_data]
                subscription['server_names'] = [dict(s)['server_name'] for s in servers_data]
                # Для обратной совместимости
                subscription['config_link'] = subscription['config_links'][0]
                subscription['server_name'] = ', '.join(subscription['server_names'])
            else:
                # Fallback для старых подписок
                subscription['config_links'] = []
                subscription['server_names'] = []

            return subscription
        finally:
            conn.close()

    def deactivate_subscription(self, subscription_id):
        """Деактивирует подписку и удаляет клиента со всех серверов"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            # Получаем подписку
            cursor.execute("SELECT uuid FROM subscriptions WHERE id = ?", (subscription_id,))
            sub = cursor.fetchone()

            if not sub:
                return False

            client_uuid = sub['uuid']

            # Получаем все сервера для этой подписки
            cursor.execute("""
                SELECT ss.server_id
                FROM subscription_servers ss
                WHERE ss.subscription_id = ?
            """, (subscription_id,))

            server_ids = cursor.fetchall()

            # Удаляем клиента с каждого сервера
            for row in server_ids:
                server = self.get_server_by_id(row['server_id'])
                if server:
                    self.remove_client_from_xray(server, client_uuid)

            # Деактивируем подписку
            cursor.execute("UPDATE subscriptions SET is_active = 0 WHERE id = ?", (subscription_id,))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Ошибка деактивации: {e}")
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
                    (SELECT COUNT(DISTINCT ss.subscription_id)
                     FROM subscription_servers ss
                     JOIN subscriptions sub ON ss.subscription_id = sub.id
                     WHERE ss.server_id = s.id AND sub.is_active = 1) as current_users
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
