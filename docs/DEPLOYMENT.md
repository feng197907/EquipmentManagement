# DMS 部署指南

> 从本地开发到生产部署的完整流程。

> ## ⚠️ 本文档部分内容已过时（2026-11 起）
>
> 生产环境已经从 **systemd + 宿主机 gunicorn** 迁移到 **Docker 容器**（容器名 `dms-app`，
> 镜像 `equipment-management:latest`，`network_mode: host`）。
>
> - **日常发布 / 上线操作，请只看：[`上线操作手册.md`](./上线操作手册.md)**
> - 本文的「Linux 生产部署」「systemd 服务管理」两节是**历史流程**，现在照做会和容器
>   抢占 `127.0.0.1:5000`，导致 502。仅作查阅参考，不要执行。
> - 「数据库配置」「Nginx 反向代理」两节仍然有效。
> - 如果需要重新部署一台新服务器，用 `上线操作手册.md` 的附录 A。

---

## 目录

1. [环境要求](#环境要求)
2. [本地部署](#本地部署)
3. [Linux 生产部署](#linux-生产部署)（⚠️ 已过时，见上方说明）
4. [数据库配置](#数据库配置)
5. [systemd 服务管理](#systemd-服务管理)（⚠️ 已由 Docker 取代）
6. [GitHub Webhook 自动部署](#github-webhook-自动部署)
7. [Nginx 反向代理](#nginx-反向代理)
8. [故障排查](#故障排查)

---

## 环境要求

### 最低配置

| 项目 | 要求 |
|------|------|
| 操作系统 | Linux (CentOS 7+ / Ubuntu 18.04+) 或 Windows 10+ |
| Python | 3.10+ |
| 内存 | 512MB+ |
| 磁盘 | 1GB+ |
| 数据库 | SQLite（内置）或 MySQL 5.7+ |

### 推荐配置（生产环境）

| 项目 | 推荐值 |
|------|--------|
| CPU | 2 核+ |
| 内存 | 2GB+ |
| 数据库 | MySQL 8.0 |
| Web 服务器 | Nginx 1.18+ |
| WSGI 服务器 | Gunicorn 21.0+ |

---

## 本地部署

### Windows 开发环境

```bash
# 1. 克隆项目
git clone https://github.com/feng197907/EquipmentManagement.git
cd EquipmentManagement

# 2. 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境变量（可选）
copy .env.example .env
# 编辑 .env，按需修改数据库配置

# 5. 启动服务
python app.py
```

访问 `http://127.0.0.1:5000`

---

## Linux 生产部署

### 一键部署脚本

项目提供了 `server_deploy.sh` 自动化部署脚本：

```bash
# 方式一：直接执行
chmod +x server_deploy.sh
./server_deploy.sh

# 方式二：通过迁移脚本（新服务器推荐）
curl -sL https://raw.githubusercontent.com/feng197907/EquipmentManagement/main/migrate/quick_migrate.sh | bash
```

### 手动部署步骤

```bash
# 1. 创建项目目录
sudo mkdir -p /data/EquipmentManagement
cd /data/EquipmentManagement

# 2. 克隆代码
git clone https://github.com/feng197907/EquipmentManagement.git .

# 3. 安装 Python 依赖
pip3 install flask flask-login gunicorn pymysql python-dotenv openpyxl

# 4. 配置环境变量
cp .env.example .env
vim .env  # 填写服务器真实配置

# 5. 创建上传目录
mkdir -p uploads logs

# 6. 初始化数据库
python3 -c "from database import init_db; init_db()"

# 7. 测试启动
python3 app.py
# 按 Ctrl+C 停止

# 8. 使用 Gunicorn 正式启动
pkill -f gunicorn
nohup gunicorn --bind 0.0.0.0:5000 \
  --workers 2 \
  --timeout 120 \
  "app:create_app()" \
  > logs/gunicorn.log 2>&1 &

# 9. 验证服务
curl http://localhost:5000
```

---

## 数据库配置

### 默认 SQLite（零配置）

无需任何配置，直接启动即可。数据文件自动创建在项目根目录。

### 切换到 MySQL

**1. 创建数据库**

```sql
CREATE DATABASE dms_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'dms_user'@'localhost' IDENTIFIED BY 'your_password';
GRANT ALL PRIVILEGES ON dms_db.* TO 'dms_user'@'localhost';
FLUSH PRIVILEGES;
```

**2. 配置 .env 文件**

```env
DB_TYPE=mysql
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=dms_user
MYSQL_PASSWORD=your_password
MYSQL_DATABASE=dms_db

# Flask 密钥（生产环境务必修改）
SECRET_KEY=your-random-secret-string-here
```

**3. 重启服务**

```bash
sudo systemctl restart dms
```

### 环境变量完整列表

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DB_TYPE` | `sqlite` | 数据库类型：`sqlite` 或 `mysql` |
| `MYSQL_HOST` | `localhost` | MySQL 主机地址 |
| `MYSQL_PORT` | `3306` | MySQL 端口 |
| `MYSQL_USER` | `root` | MySQL 用户名 |
| `MYSQL_PASSWORD` | (空) | MySQL 密码 |
| `MYSQL_DATABASE` | `dms_db` | MySQL 数据库名 |
| `SECRET_KEY` | `dev-secret-key` | Flask 会话密钥 |
| `WEBHOOK_SECRET` | (空) | GitHub Webhook 密钥 |
| `PORT` | `5000` | 应用监听端口 |

---

## systemd 服务管理

### 安装服务

项目 `deploy/` 目录提供了 systemd 服务文件：

```bash
# 复制服务文件
sudo cp deploy/dms.service /etc/systemd/system/
sudo cp deploy/dms-webhook.service /etc/systemd/system/

# 重新加载配置
sudo systemctl daemon-reload

# 启动服务
sudo systemctl enable dms        # 开机自启
sudo systemctl start dms         # 立即启动
sudo systemctl enable dms-webhook # Webhook 自启
sudo systemctl start dms-webhook  # Webhook 启动
```

### 常用管理命令

```bash
# 查看服务状态
sudo systemctl status dms
sudo systemctl status dms-webhook

# 重启服务
sudo systemctl restart dms

# 查看日志
sudo journalctl -u dms -f          # 实时跟踪
sudo journalctl -u dms --since today # 当天日志

# 停止服务
sudo systemctl stop dms
```

---

## GitHub Webhook 自动部署

### 工作原理

```
本地 git push → GitHub 仓库 → Webhook 通知 → 服务器 :5001 端口
    → webhook_server.py 验证签名 → webhook-deploy.sh
    → git pull → 重启 Gunicorn
```

### 配置步骤

**1. 服务器端**

```bash
# 确保 webhook_server.py 在运行
sudo systemctl start dms-webhook

# 设置 Webhook 密钥（与 GitHub 端一致）
echo "WEBHOOK_SECRET=your-secret" >> .env
```

**2. GitHub 端**

1. 进入仓库 → Settings → Webhooks → Add webhook
2. 配置参数：

| 参数 | 值 |
|------|-----|
| Payload URL | `http://你的服务器IP:5001/webhook` |
| Content type | `application/json` |
| Secret | 你的 WEBHOOK_SECRET |
| Events | Just the `push` event |

**3. 验证部署**

```bash
# 查看部署日志
tail -f logs/webhook.log

# 手动触发测试
curl -X POST http://localhost:5001/webhook \
  -H "Content-Type: application/json" \
  -d '{"ref":"refs/heads/main"}'
```

---

## Nginx 反向代理

### 推荐配置

```nginx
server {
    listen 80;
    server_name your-domain.com;

    client_max_body_size 50M;  # 与 Flask MAX_CONTENT_LENGTH 一致

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # 静态文件直接由 Nginx 提供
    location /static/ {
        alias /data/EquipmentManagement/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # 上传文件
    location /uploads/ {
        alias /data/EquipmentManagement/uploads/;
    }
}
```

### 启用 HTTPS（推荐）

```bash
# 使用 Certbot 获取免费 SSL 证书
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

---

## 故障排查

### 服务无法启动

```bash
# 1. 检查端口占用
lsof -i :5000
netstat -tlnp | grep 5000

# 2. 检查日志
tail -100 logs/error.log
sudo journalctl -u dms -n 50

# 3. 手动启动测试
cd /data/EquipmentManagement
python3 app.py
```

### 数据库连接失败

```bash
# 验证 MySQL 连接
mysql -h localhost -u dms_user -p dms_db

# 检查 .env 配置是否正确
cat .env | grep MYSQL

# 测试数据库初始化
python3 -c "
from database import init_db, DB_TYPE
print(f'DB_TYPE: {DB_TYPE}')
init_db()
print('Database initialized successfully')
"
```

### Webhook 部署未触发

```bash
# 检查 Webhook 服务状态
sudo systemctl status dms-webhook

# 查看 Webhook 日志
tail -50 logs/webhook.log
sudo journalctl -u dms-webhook -n 50

# 确认 GitHub Webhook 配置
# 进入仓库 Settings → Webhooks → Recent Deliveries 查看发送状态
```

### 文件上传失败

```bash
# 检查上传目录权限
ls -la uploads/

# 确认磁盘空间
df -h /data

# 检查文件大小限制
grep MAX_CONTENT_LENGTH app.py
```

---

## 安全建议

1. **修改默认密码**：首次部署后立即修改 `admin` 和 `user` 的默认密码
2. **生产密钥**：将 `.env` 中的 `SECRET_KEY` 改为随机字符串
3. **防火墙**：只开放 80/443 端口，5000/5001 端口仅允许本地访问
4. **HTTPS**：生产环境务必启用 SSL/TLS
5. **定期备份**：设置自动化数据库备份任务
6. **日志轮转**：配置 logrotate 防止日志文件占满磁盘

---

*如有部署问题，请查阅 [开发指南](./DEVELOPMENT.md) 或提交 GitHub Issue。*
