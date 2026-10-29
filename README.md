# 设备档案文档管理系统 (DMS)

<div align="center">

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![Flask](https://img.shields.io/badge/Flask-3.0-green.svg)
![Bootstrap](https://img.shields.io/badge/Bootstrap-5.3-purple.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)
![Status](https://img.shields.io/badge/Status-Production-brightgreen.svg)

**面向制药企业的 GMP 合规设备档案与文档管理系统**

开箱即用 · 14 模块化 Blueprint · SQLite/MySQL 双数据库 · 78 条路由

[快速开始](#快速开始) · [功能概览](#功能概览) · [文档体系](#文档体系) · [部署指南](#部署指南) · [项目结构](#项目结构)

</div>

---

## 文档体系

完整的文档体系已建立，根据不同角色导航到相应文档：

| 文档 | 受众 | 内容 |
|------|------|------|
| 📖 [使用手册](docs/使用手册.md) | 最终用户 | 功能操作指南、角色权限说明、常见问题 |
| 🏗️ [架构文档](docs/ARCHITECTURE.md) | 开发者 / 架构师 | 系统架构、Blueprint 设计、数据层、权限模型 |
| 💻 [开发指南](docs/DEVELOPMENT.md) | 贡献者 | 环境搭建、项目结构、编码规范、测试指南 |
| 🚀 [部署指南](docs/DEPLOYMENT.md) | 运维人员 | 本地/生产部署、MySQL 配置、Webhook 自动部署 |
| 📡 [API 参考](docs/API_REFERENCE.md) | 集成开发者 | 78 条路由完整参数、请求/响应示例、错误码 |

---

## 功能概览

### 📋 核心功能

| 模块 | 功能 | 说明 |
|------|------|------|
| **设备管理** | 新增/编辑/停用/报废 | 完整的设备生命周期管理 |
| **设备看板** | 状态统计与列表 | 可视化设备分布情况 |
| **设备校准** | 校准计划与记录 | 确保设备精度合规 |
| **设备维护** | 维护计划与执行 | 预防性维护管理 |
| **备件管理** | 库存/入库/消耗/预警 | 备件全生命周期管理 |
| **文档中心** | 上传/下载/版本控制 | 支持多版本文档管理 |
| **借阅管理** | 借出/归还/审批 | 文档资产追踪 |
| **审批流程** | 多级审批+电子签名 | 数字化审批体验 |
| **提醒中心** | 待办事项与通知 | 不遗漏任何事项 |

### 🔐 权限系统

系统内置 **7 种角色**，精细化权限控制：

| 角色 | 说明 | 核心权限 |
|------|------|----------|
| **管理员** (admin) | 系统最高权限 | 所有功能 |
| **QA经理** (qa_manager) | 质量相关审批 | 文档审批、质量审批、报告查看 |
| **设备工程师** (equipment_engineer) | 设备操作维护 | 设备操作、校准、维护 |
| **验证工程师** (validation_engineer) | 验证文档管理 | IQ/OQ/PQ、文档审批 |
| **计量工程师** (metrology_engineer) | 计量校准 | 设备校准、计量管理 |
| **生产主管** (production_supervisor) | 生产审批 | 生产审批、文档审批、报告查看 |
| **文档管理员** (archivist) | 文档归档 | 文档上传、归档管理 |

> 💡 **审批权限说明**：拥有 `document_approval` 权限的角色（管理员、QA经理、验证工程师、生产主管）可处理审批待办。

### 📊 审计追踪

所有关键操作均记录审计日志，便于：
- 合规审查
- 问题追溯
- 操作统计

---

## 快速开始

### 环境要求

- Python 3.10+
- SQLite（默认）或 MySQL（可选）

### 安装步骤

```bash
# 1. 克隆项目
git clone https://github.com/YOUR_USERNAME/EquipmentManagement.git
cd EquipmentManagement

# 2. 安装依赖
pip install -r requirements.txt

# 3. 启动服务
python app.py
```

### Docker Compose 部署（生产用这套）

应用跑在容器里，MariaDB 和 nginx 留在宿主机。容器用 `network_mode: host` 直接复用宿主机网络栈，所以：

- 容器看到的 `127.0.0.1:3306` 就是宿主机的 MariaDB
- nginx 的 `proxy_pass http://127.0.0.1:5000` 不用改
- MariaDB 可以安全地 bind 到 `127.0.0.1`，不再对公网开放 3306

首次部署：

```bash
cp .env.example .env
vi .env                      # 填 MYSQL_PASSWORD 和 SECRET_KEY

docker compose up -d --build
docker compose ps            # 等 STATUS 出现 (healthy)
```

日常发布：

```bash
git pull origin main
docker compose up -d --build     # 重建镜像并替换容器，秒级切换
```

运维命令：

```bash
docker compose logs -f app                  # 跟日志
docker compose restart app                  # 只重启应用
docker compose exec app sh                  # 进容器
docker compose down                         # 停掉
```

上传文件和日志挂的是宿主机目录 `./uploads` 和 `./logs`，容器删了重建数据不丢，备份直接 `tar czf` 这两个目录即可。

镜像自带健康检查，打的是应用自己的 `/healthz`——它会真的查一次数据库，所以 `unhealthy` 表示"进程活着但库连不上"，比只看进程有意义。

> 旧的 `docker-compose-mysql.yml` + `.override.yml` 组合是「连数据库一起容器化」的独立跑法，本地开发想一键起 MySQL 时仍可用；生产不要用那套，会和宿主机的 MariaDB 抢 3306。

### 访问系统

> 🌐 **http://127.0.0.1:5000**

### 默认账号

| 角色 | 用户名 | 密码 |
|------|--------|------|
| 管理员 | admin | admin123 |
| 设备工程师 | user | user123 |

> ⚠️ **请首次登录后立即修改默认密码！**

---

## 系统截图

### 登录页面
![登录页面](docs/screenshots/login.png)

### 设备看板
![设备看板](docs/screenshots/dashboard.png)

### 设备列表
![设备列表](docs/screenshots/device-list.png)

### 设备详情
![设备详情](docs/screenshots/device-detail.png)

### 备件管理
![备件管理](docs/screenshots/spare-parts.png)

### 文档中心
![文档中心](docs/screenshots/document-center.png)

### 借阅管理
![借阅管理](docs/screenshots/borrowing.png)

### 审批流程
![审批流程](docs/screenshots/approval.png)

### 提醒中心
![提醒中心](docs/screenshots/reminder.png)

### 系统设置
![系统设置](docs/screenshots/settings.png)

---

## 部署指南

### 本地开发部署

```bash
# 使用虚拟环境
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
.venv\Scripts\activate     # Windows

# 安装依赖
pip install -r requirements.txt

# 启动服务
python app.py

# 实时查看应用日志
tail -f /data/EquipmentManagement/logs/app.log

# 查看错误日志
tail -f /data/EquipmentManagement/logs/error.log

# 搜索错误
grep -i "error\|exception" /data/EquipmentManagement/logs/app.log
```

### Linux 服务器部署

```bash
# 安装依赖
pip3 install flask gunicorn

# gunicorn 启动
pkill -f gunicorn
nohup gunicorn --bind 0.0.0.0:5000 --workers 2 app:app > gunicorn.log 2>&1 &
tail -f gunicorn.log

# 使用 systemd 管理服务
sudo cp deploy/*.service /etc/systemd/system/
sudo systemctl enable dms
sudo systemctl start dms
sudo systemctl status dms-webhook
```

### 一键迁移

新服务器快速部署：

```bash
curl -sL https://raw.githubusercontent.com/YOUR_USERNAME/EquipmentManagement/main/migrate/quick_migrate.sh | bash
```

---

## 自动化部署

本项目支持 **GitHub Webhook** 自动化部署。

### 配置步骤

1. GitHub 仓库 → Settings → Webhooks → Add webhook
2. 配置：
   - **Payload URL**: `http://YOUR_SERVER:5001/webhook`
   - **Content type**: `application/json`
   - **Secret**: `YOUR_WEBHOOK_SECRET`
   - **Events**: `push`

### 部署流程

```
Git Push → GitHub Webhook → 服务器自动拉取 → 重启服务
```

### 查看日志

```bash
# 实时查看部署日志
tail -f /var/log/webhook-deploy.log
```

---

## 项目结构

```
EquipmentManagement/
├── app.py                 # 应用入口
├── config.py              # 配置文件（角色、权限定义）
├── database.py            # 数据库初始化与迁移
├── extensions.py          # Flask 扩展初始化
├── requirements.txt       # Python 依赖
│
├── blueprints/           # 路由模块（Controller）
│   ├── __init__.py
│   ├── auth.py           # 认证模块（登录/注销）
│   ├── devices.py        # 设备管理
│   ├── maintenance.py    # 设备维护
│   ├── spare_part.py     # 备件管理
│   ├── documents.py      # 文档管理
│   ├── approvals.py      # 审批流程
│   ├── borrowing.py      # 借阅管理
│   ├── dashboard.py      # 仪表盘/看板
│   ├── esign.py         # 电子签名
│   ├── users.py         # 用户管理
│   ├── settings.py      # 系统设置
│   ├── password.py      # 密码重置
│   ├── search.py        # 全局搜索
│   └── device_changes.py # 设备变更审批
│
├── models/               # 数据模型
│   ├── __init__.py
│   ├── user.py          # 用户模型
│   ├── maintenance.py   # 维护计划/记录模型
│   ├── spare_part.py    # 备件/入库/消耗/预警模型
│   └── electronic_signature.py # 电子签名模型
│
├── templates/            # 前端模板（Jinja2）
│   ├── base.html        # 基础模板
│   ├── login.html      # 登录页
│   ├── index.html      # 首页
│   ├── device_*.html   # 设备相关页面
│   ├── spare_part_*.html # 备件相关页面
│   ├── documents.html  # 文档中心
│   ├── approvals.html  # 审批待办
│   ├── reminders.html   # 提醒中心
│   └── components/     # 可复用组件
│       └── esign_modal.html # 电子签名弹窗
│
├── static/              # 静态资源
│   ├── css/            # 样式文件
│   ├── js/             # JavaScript 文件
│   └── uploads/        # 上传文件存储
│
├── utils/               # 工具函数
│   ├── decorators.py   # 权限装饰器
│   ├── audit.py        # 审计日志
│   ├── file_utils.py   # 文件处理
│   └── db_utils.py    # 数据库工具
│
├── scripts/             # 脚本工具
│   ├── webhook_server.py  # Webhook 服务
│   └── ...
│
├── migrate/             # 数据库迁移脚本
│   ├── quick_migrate.sh
│   └── ...
│
├── docs/                # 文档
│   ├── 使用手册.md
│   └── screenshots/    # 截图目录
│
├── tests/               # 测试文件
│   ├── test_*.py
│   └── ...
│
└── deploy/              # 部署配置
    └── *.service       # systemd 服务文件
```

---

## 数据库配置

### 默认 SQLite（开箱即用）

无需任何配置，直接启动即可。数据文件：`dms.db`

### 可选 MySQL

```bash
# 1. 安装依赖
pip install pymysql cryptography

# 2. 修改 config.py 中的数据库配置
# 或在服务器上创建 .env 文件配置数据库连接
```

服务器上部署时，把 `.env.example` 复制为 `.env`，再填上服务器的真实配置即可。

---

## 备件管理模块

### 功能概览

| 功能 | 说明 |
|------|------|
| **备件库存** | 查看备件库存，支持按分类/名称搜索 |
| **入库管理** | 记录备件入库，自动更新库存和加权平均价 |
| **消耗记录** | 维修/维护时消耗备件，自动扣减库存 |
| **库存预警** | 低库存/缺货/超量/呆滞 自动预警 |
| **成本统计** | 备件消耗成本分析，按设备/类型统计 |

### 消耗记录关联

备件消耗可关联至：
- **维护记录** (`maintenance_record`)
- **维修记录** (`repair_record`)

在提交维护/维修记录时，可选择消耗的备件，系统自动：
1. 扣减备件库存
2. 记录消耗明细（数量、单价、总价）
3. 触发库存预警检查

---

## 常见问题

| 问题 | 解决方案 |
|------|----------|
| 登录后看不到内容 | 检查账号是否被停用或权限分配 |
| 上传失败 | 确认文件类型（pdf/doc/docx/xls/xlsx/jpg/png） |
| 服务启动失败 | 检查端口占用 `lsof -i:5000` |
| 数据库异常 | 删除 `dms.db` 重启自动重建 |
| 备件消耗不显示 | 检查 `spare_part_consumptions` 表是否有数据 |

---

## 参考文档

- 📖 [使用手册](docs/使用手册.md)

---

## 开源协议

MIT License

---

<div align="center">

**如果这个项目对你有帮助，请点个 ⭐ Star！**

</div>
