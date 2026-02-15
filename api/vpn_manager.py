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
        ssh_cmd = f"ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 {server['ssh_user']}@{server['ip']} \"{command}\""
        logger.info(f"SSH команда: {ssh_cmd[:100]}...")
        try:
            result = subprocess.run(ssh_cmd, shell=True, capture_output=True, text=True, timeout=30)
            logger.info(f"SSH код: {result.returncode}")
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

    def _get_free_uuid_from_pool(self, server_id):
        """Берёт свободный UUID из пула для сервера"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT id, uuid, email FROM uuid_pool
                WHERE server_id = ? AND is_used = 0
                LIMIT 1
            """, (server_id,))

            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
        finally:
            conn.close()

    def _mark_uuid_used(self, pool_id):
        """Помечает UUID из пула как использованный"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("UPDATE uuid_pool SET is_used = 1 WHERE id = ?", (pool_id,))
            conn.commit()
        finally:
            conn.close()

    def _mark_uuid_free(self, uuid_value, server_id):
        """Возвращает UUID в пул (при деактивации подписки)"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                UPDATE uuid_pool SET is_used = 0
                WHERE uuid = ? AND server_id = ?
            """, (uuid_value, server_id))
            conn.commit()
        finally:
            conn.close()

    def get_pool_stats(self):
        """Статистика по пулу UUID"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT s.name, s.id as server_id,
                    (SELECT COUNT(*) FROM uuid_pool WHERE server_id = s.id) as total,
                    (SELECT COUNT(*) FROM uuid_pool WHERE server_id = s.id AND is_used = 0) as free,
                    (SELECT COUNT(*) FROM uuid_pool WHERE server_id = s.id AND is_used = 1) as used
                FROM servers s
                WHERE s.is_active = 1
            """)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def create_subscription(self, telegram_id, username, duration_days=30):
        """
        Создает подписку БЕЗ SSH и БЕЗ перезапуска Xray.
        Берёт свободный UUID из предгенерированного пула.
        """
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

            # Берём свободный UUID из пула для первого сервера
            first_server = servers[0]
            pool_entry = self._get_free_uuid_from_pool(first_server['id'])

            if not pool_entry:
                logger.error(f"Нет свободных UUID в пуле для сервера {first_server['name']}")
                return None

            client_uuid = pool_entry['uuid']
            subscription_token = self.generate_uuid()

            # Создаем подписку
            expires_at = datetime.now() + timedelta(days=duration_days)
            cursor.execute("""
                INSERT INTO subscriptions (user_id, uuid, subscription_token, expires_at)
                VALUES (?, ?, ?, ?)
            """, (user_id, client_uuid, subscription_token, expires_at.strftime('%Y-%m-%d %H:%M:%S')))

            subscription_id = cursor.lastrowid

            # Назначаем UUID на серверы
            config_links = []
            server_names = []
            used_pool_ids = []

            for server in servers:
                # Для первого сервера используем уже полученный UUID
                if server['id'] == first_server['id']:
                    pool = pool_entry
                else:
                    # Для дополнительных серверов ищем тот же UUID в их пуле
                    # (если пулы генерились с одинаковыми UUID на все серверы)
                    # Или берём отдельный свободный UUID
                    pool = self._get_free_uuid_from_pool(server['id'])
                    if not pool:
                        logger.warning(f"Нет свободных UUID для сервера {server['name']}, пропускаю")
                        continue

                server_name = server['name']
                config_link = self.create_vless_link(
                    pool['uuid'] if server['id'] != first_server['id'] else client_uuid,
                    server,
                    server_name
                )

                # Сохраняем связь подписка-сервер
                cursor.execute("""
                    INSERT INTO subscription_servers (subscription_id, server_id, config_link)
                    VALUES (?, ?, ?)
                """, (subscription_id, server['id'], config_link))

                config_links.append(config_link)
                server_names.append(server_name)
                used_pool_ids.append((pool['id'], server['id']))

            if not config_links:
                logger.error("Не удалось назначить UUID ни на один сервер")
                conn.rollback()
                return None

            # Помечаем UUID как использованные
            for pool_id, _ in used_pool_ids:
                cursor.execute("UPDATE uuid_pool SET is_used = 1 WHERE id = ?", (pool_id,))

            conn.commit()

            logger.info(f"Подписка создана для {telegram_id} без SSH/restart!")

            return {
                'uuid': client_uuid,
                'subscription_token': subscription_token,
                'config_links': config_links,
                'server_names': server_names,
                'expires_at': expires_at.strftime('%Y-%m-%d %H:%M:%S'),
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
                subscription['config_link'] = subscription['config_links'][0]
                subscription['server_name'] = ', '.join(subscription['server_names'])
            else:
                subscription['config_links'] = []
                subscription['server_names'] = []

            return subscription
        finally:
            conn.close()

    def deactivate_subscription(self, subscription_id):
        """Деактивирует подписку и возвращает UUID в пул"""
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

            # Возвращаем UUID в пул для каждого сервера
            for row in server_ids:
                cursor.execute("""
                    UPDATE uuid_pool SET is_used = 0
                    WHERE uuid = ? AND server_id = ?
                """, (client_uuid, row['server_id']))

            # Деактивируем подписку
            cursor.execute("UPDATE subscriptions SET is_active = 0 WHERE id = ?", (subscription_id,))
            conn.commit()

            logger.info(f"Подписка {subscription_id} деактивирована, UUID возвращён в пул")
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

            # Статистика пула
            cursor.execute("SELECT COUNT(*) FROM uuid_pool WHERE is_used = 0")
            free_uuids = cursor.fetchone()[0]

            return {
                'total_users': total_users,
                'active_subscriptions': active_subs,
                'active_servers': active_servers,
                'free_uuids': free_uuids
            }
        finally:
            conn.close()