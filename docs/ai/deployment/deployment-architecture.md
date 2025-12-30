---
phase: deployment
title: Deployment Architecture
description: Kiến trúc triển khai Elysia (Cloudflare + Nginx + Docker)
---

# Deployment Architecture

## Sơ đồ tổng quan
```mermaid
flowchart LR
    U[User] --> CF[Cloudflare\nDNS + CDN + SSL]
    CF --> NG[Nginx on Azure VM\n80/443]
    NG --> FE[Frontend (Next.js)\nport 3000]
    NG --> BE[Backend (Elysia API)\nport 8000]
    BE --> DB[Vector DB (Weaviate)\nDocker service]
    BE --> LLM[Transformers/LLM\nDocker service]
```

## Thành phần chính
- **Cloudflare**: DNS, SSL/TLS (Full strict), CDN, DDoS protection, WebSocket pass-through.
- **Nginx (VM)**: Reverse proxy, force HTTPS, điều phối frontend (3000) và backend (8000), giữ WebSocket ổn định.
- **Docker Compose**: Chạy frontend, backend, Weaviate, transformers/LLM; dễ restart/rollback.
- **Systemd (tùy chọn)**: Tự động khởi động Docker Compose sau reboot.

## Luồng triển khai rút gọn
1) Tạo Azure VM và cài Docker theo `azure-vm-setup.md`.  
2) Chạy `docker compose up -d` để khởi động frontend/backend/DB.  
3) Cấu hình Cloudflare + Nginx theo `cloudflare-nginx-setup.md`.  
4) Kiểm tra health:  
   - `https://<domain>/` → frontend  
   - `https://<domain>/api/health` → backend  
   - WebSocket ở `/ws/` (qua Nginx + Cloudflare).

## Checklist nhanh
- [ ] DNS A record trỏ đúng IP, Proxy bật (orange cloud).  
- [ ] Cloudflare SSL mode = Full (strict), Always Use HTTPS = On.  
- [ ] Nginx config load thành công (`nginx -t`).  
- [ ] Docker services chạy ổn (`docker compose ps`).  
- [ ] Health endpoints trả 200, WebSocket kết nối được.  
- [ ] Đã bật auto-start (systemd) nếu cần.

