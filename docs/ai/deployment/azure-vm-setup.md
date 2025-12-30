---
phase: deployment
title: Azure VM Setup (ngắn gọn)
description: Tạo VM, cài nền tảng, chạy Docker Compose cho Elysia
---

# Azure VM Setup (ngắn gọn)

## 1) Tạo VM
- Azure Portal → Create VM  
- OS: Ubuntu 22.04 LTS  
- Size gợi ý: `Standard_B2s` (dev) hoặc `Standard_B2ms` (dev/prod nhẹ)  
- Disk: 64GB OS + 128GB data (Weaviate)  
- Network: mở inbound SSH (22); sẽ mở thêm 80/443 sau.

## 2) SSH và cập nhật máy
```bash
ssh -i <key.pem> azureuser@<public-ip>
sudo apt update && sudo apt upgrade -y
sudo apt install -y curl git unzip
```

## 3) Cài Docker + Compose
```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker

# Compose plugin (Ubuntu repo)
sudo apt install -y docker-compose-plugin
```

## 4) Chuẩn bị dự án
```bash
git clone https://github.com/<your-org>/elysia.git ~/elysia-project
cd ~/elysia-project

# Chọn cấu hình
cp Docker/docker-compose.dev.yml Docker/docker-compose.yml  # dev/không GPU
# hoặc tự chỉnh docker-compose.prod.yml rồi copy sang docker-compose.yml
```

Tạo file `.env` ở thư mục gốc dự án với các secret/API keys bắt buộc cho backend, frontend, Weaviate, OpenAI, v.v.

## 5) Chạy dịch vụ
```bash
cd Docker
docker compose pull
docker compose up -d
docker compose ps
```

## 6) Mở port trên NSG (Azure)
- Thêm inbound rules: `80` (HTTP), `443` (HTTPS), `22` (SSH).  
- Nếu cần truy cập trực tiếp backend: mở `8000`; frontend: `3000` (thường không cần khi đã có Nginx).

## 7) Kiểm tra nhanh
```bash
curl http://localhost:8000/health || true
docker compose logs --tail 50
```

## 8) Auto-start (tùy chọn nhanh)
```bash
sudo tee /etc/systemd/system/elysia-docker.service >/dev/null <<'EOF'
[Unit]
Description=Elysia via Docker Compose
After=network-online.target docker.service
Wants=docker.service

[Service]
WorkingDirectory=/home/azureuser/elysia-project/Docker
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
Restart=always
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now elysia-docker
```

Tiếp theo: cấu hình domain/HTTPS theo `cloudflare-nginx-setup.md`.

