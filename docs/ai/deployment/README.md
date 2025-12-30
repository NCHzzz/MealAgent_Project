---
phase: deployment
title: Deployment Documentation
description: Bộ tài liệu triển khai gọn cho hệ thống Elysia
---

# Deployment Documentation

## Bộ tài liệu rút gọn (3 file)

1) 📄 **[azure-vm-setup.md](./azure-vm-setup.md)**  
   Tạo và cấu hình Azure VM, cài Docker, chạy Docker Compose, mở port.

2) 📄 **[cloudflare-nginx-setup.md](./cloudflare-nginx-setup.md)**  
   Trỏ DNS Cloudflare, bật SSL, cấu hình Nginx reverse proxy (frontend + backend + WebSocket).

3) 📄 **[deployment-architecture.md](./deployment-architecture.md)**  
   Kiến trúc triển khai tổng thể, luồng traffic và các thành phần chính.

## Quick start ngắn

```bash
# 1) SSH vào VM
ssh -i <key.pem> azureuser@<public-ip>

# 2) Làm theo azure-vm-setup.md để cài Docker và chạy Docker Compose
# 3) Làm theo cloudflare-nginx-setup.md để trỏ domain và bật HTTPS
# 4) Kiểm tra kiến trúc và checklist trong deployment-architecture.md
```

## Liên quan

- docker-compose.dev.yml: cấu hình chạy không GPU
- docker-compose.prod.yml: cấu hình production (GPU/không GPU tùy chỉnh)
- `.env`: cần điền đầy đủ API keys/secret trước khi start dịch vụ
