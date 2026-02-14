#!/bin/bash

# Deploy script for VPS
VPS_IP="85.239.48.88"
VPS_USER="root"
PROJECT_PATH="/root/vpn_project"

echo "Deploying to VPS..."

# Copy new files
scp api/subscription_server.py ${VPS_USER}@${VPS_IP}:${PROJECT_PATH}/api/
scp scripts/migrate_multiserver.py ${VPS_USER}@${VPS_IP}:${PROJECT_PATH}/scripts/
scp api/database.py ${VPS_USER}@${VPS_IP}:${PROJECT_PATH}/api/
scp api/vpn_manager.py ${VPS_USER}@${VPS_IP}:${PROJECT_PATH}/api/
scp bot/main.py ${VPS_USER}@${VPS_IP}:${PROJECT_PATH}/bot/
scp bot/config.py ${VPS_USER}@${VPS_IP}:${PROJECT_PATH}/bot/
scp requirements.txt ${VPS_USER}@${VPS_IP}:${PROJECT_PATH}/

echo "Files copied. Now run setup on VPS..."

# Run setup on VPS
ssh ${VPS_USER}@${VPS_IP} << 'ENDSSH'
cd /root/vpn_project

# Install Flask
source venv/bin/activate
pip install flask==3.0.0

# Update database
sqlite3 vpn.db << 'ENDSQL'
CREATE TABLE IF NOT EXISTS subscription_servers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subscription_id INTEGER NOT NULL,
    server_id INTEGER NOT NULL,
    config_link TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (subscription_id) REFERENCES subscriptions(id),
    FOREIGN KEY (server_id) REFERENCES servers(id),
    UNIQUE(subscription_id, server_id)
);

ALTER TABLE subscriptions ADD COLUMN subscription_token TEXT;
ENDSQL

# Update .env
echo "SUBSCRIPTION_URL_BASE=https://syntax-vpn.tech/sub" >> .env

echo "Setup complete!"
ENDSSH

echo "Deployment finished!"
