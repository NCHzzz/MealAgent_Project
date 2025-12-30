---
phase: deployment
title: Cloudflare + Nginx
description: Trỏ DNS, bật SSL, reverse proxy cho frontend/backend + WebSocket
---

# Cloudflare + Nginx (ngắn gọn)

## 1) Cloudflare DNS & SSL
1) Thêm domain vào Cloudflare, đổi nameserver theo hướng dẫn.  
2) DNS → Add record  
   - Type: `A`, Name: `@`, Content: `<public-ip>`, Proxy: **Proxied** (orange).  
   - Nếu cần `www` → CNAME `www` trỏ `@`.  
3) SSL/TLS → Overview: chọn **Full (strict)**.  
4) SSL/TLS → Edge Certificates: bật **Always Use HTTPS** và **HTTP/2**, **WebSockets** mặc định bật.

## 2) Cài Nginx trên VM
```bash
sudo apt install -y nginx
sudo ufw allow 80
sudo ufw allow 443
```

## 3) Cấu hình Nginx reverse proxy
File ví dụ `/etc/nginx/sites-available/elysia.conf`:
```nginx
server {
    listen 80;
    server_name mealagent.io.vn www.mealagent.io.vn;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name mealagent.io.vn www.mealagent.io.vn;

    # SSL do Cloudflare terminate ở edge, nhưng vẫn nên có cert tự ký để dùng Full (strict)
    ssl_certificate     /etc/ssl/certs/ssl-cert-snakeoil.pem;
    ssl_certificate_key /etc/ssl/private/ssl-cert-snakeoil.key;

    # Giới hạn header lớn cho WebSocket/chat
    proxy_buffers 8 16k;
    proxy_buffer_size 32k;

    # Frontend (Next.js) port 3000
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }

    # Backend API + WebSocket port 8000
    location /api/ {
        proxy_pass http://127.0.0.1:8000/api/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
    }

    location /ws/ {
        proxy_pass http://127.0.0.1:8000/ws/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

Áp dụng cấu hình:
```bash
sudo ln -s /etc/nginx/sites-available/elysia.conf /etc/nginx/sites-enabled/elysia.conf
sudo nginx -t
sudo systemctl reload nginx
```

## 4) Kiểm tra
```bash
curl -I https://mealagent.io.vn
curl -I https://mealagent.io.vn/api/health
```

## 5) Ghi chú nhanh
- Nếu cần chứng chỉ hợp lệ trên VM (để Full strict không cảnh báo), có thể cài `certbot` và cấp cert bằng HTTP challenge trước khi bật proxy Cloudflare, hoặc dùng Origin CA của Cloudflare.  
- Đảm bảo backend trả về health ở `/api/health` và WebSocket ở `/ws/` như config.  
- Khi đổi IP, cập nhật bản ghi A trong Cloudflare và chờ propagate (1-5 phút).  
- Nếu cần tắt Cloudflare tạm thời để debug: chuyển Proxy thành **DNS only**.

