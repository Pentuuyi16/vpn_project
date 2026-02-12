#!/usr/bin/env python3
"""
Веб-сервер для subscription URLs
Позволяет клиентам автоматически получать все VLESS конфигурации через один URL
"""
import os
import sys
import base64
import logging
from flask import Flask, Response, abort

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.vpn_manager import VPNManager
from api.database import init_database

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
vpn_manager = VPNManager()


@app.route('/sub/<token>')
def get_subscription(token):
    """
    Возвращает subscription в формате base64
    Формат: каждая VLESS ссылка на новой строке, закодировано в base64
    """
    try:
        # Получаем подписку по токену
        conn = vpn_manager._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT sub.id, sub.is_active, sub.expires_at
            FROM subscriptions sub
            WHERE sub.subscription_token = ?
        """, (token,))

        result = cursor.fetchone()

        if not result:
            logger.warning(f"Subscription not found: {token}")
            abort(404, description="Subscription not found")

        subscription = dict(result)

        if not subscription['is_active']:
            logger.warning(f"Subscription expired: {token}")
            abort(403, description="Subscription expired")

        # Получаем все config_links для этой подписки
        cursor.execute("""
            SELECT ss.config_link, srv.name
            FROM subscription_servers ss
            JOIN servers srv ON ss.server_id = srv.id
            WHERE ss.subscription_id = ?
            ORDER BY srv.name
        """, (subscription['id'],))

        servers = cursor.fetchall()
        conn.close()

        if not servers:
            logger.warning(f"No servers found for subscription: {token}")
            abort(404, description="No servers configured")

        # Формируем список VLESS ссылок
        vless_links = [dict(s)['config_link'] for s in servers]

        # Объединяем все ссылки через новую строку
        subscription_content = '\n'.join(vless_links)

        # Кодируем в base64
        encoded_content = base64.b64encode(subscription_content.encode('utf-8')).decode('utf-8')

        logger.info(f"Subscription served: {token}, servers: {len(vless_links)}")

        # Возвращаем с правильными заголовками
        return Response(
            encoded_content,
            mimetype='text/plain',
            headers={
                'Content-Disposition': 'inline; filename="subscription.txt"',
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'Pragma': 'no-cache',
                'Expires': '0',
                'Subscription-Userinfo': f'upload=0; download=0; total=0; expire={subscription["expires_at"]}'
            }
        )

    except Exception as e:
        logger.error(f"Error serving subscription {token}: {e}")
        abort(500, description="Internal server error")


@app.route('/health')
def health_check():
    """Health check endpoint"""
    return {'status': 'ok'}


@app.route('/')
def index():
    """Root endpoint"""
    return {
        'service': 'VPN Subscription Server',
        'version': '1.0',
        'endpoints': ['/sub/<token>', '/health']
    }


def main():
    """Запуск сервера"""
    # Инициализируем БД если не существует
    init_database()

    # Получаем настройки из переменных окружения
    host = os.getenv('SUBSCRIPTION_HOST', '0.0.0.0')
    port = int(os.getenv('SUBSCRIPTION_PORT', 8080))

    logger.info(f"Starting subscription server on {host}:{port}")

    # Запускаем сервер
    app.run(host=host, port=port, debug=False)


if __name__ == '__main__':
    main()
