# DMS 开发指南

> 面向开发者：如何搭建环境、理解项目结构、添加新功能、运行测试。

---

## 目录

1. [环境搭建](#环境搭建)
2. [项目结构详解](#项目结构详解)
3. [开发工作流](#开发工作流)
4. [添加新功能](#添加新功能)
5. [数据库操作规范](#数据库操作规范)
6. [前端开发规范](#前端开发规范)
7. [测试指南](#测试指南)
8. [日志与调试](#日志与调试)
9. [常见问题](#常见问题)

---

## 环境搭建

### 前置要求

- Python 3.10+
- Git
- （可选）MySQL 5.7+ 用于生产环境模拟

### 快速启动（3 步）

```bash
# 1. 克隆项目
git clone https://github.com/feng197907/EquipmentManagement.git
cd EquipmentManagement

# 2. 创建虚拟环境并安装依赖
python -m venv .venv
.venv\Scripts\activate     # Windows
# source .venv/bin/activate  # Linux/Mac
pip install -r requirements.txt

# 3. 启动开发服务器
python app.py
```

访问 `http://localhost:5000`，使用 `admin` / `admin123` 登录。

### 依赖清单

```
flask>=2.3.0          # Web 框架
flask-login>=0.6.0    # 用户认证
werkzeug>=2.3.0       # WSGI 工具
gunicorn>=21.0.0      # 生产 WSGI 服务器
pymysql>=1.1.0        # MySQL 驱动
python-dotenv>=1.0.0  # 环境变量管理
openpyxl>=3.1.0       # Excel 导出
```

---

## 项目结构详解

```
EquipmentManagement/
├── app.py                    # 应用工厂函数 create_app()
│                              #   注册 14 个 Blueprint
│                              #   注入全局模板上下文
│
├── config.py                 # 静态配置
│                              #   · 7 种角色 + 22 项权限定义
│                              #   · 文档类型 / 设备状态枚举
│                              #   · SECRET_KEY / 上传配置
│
├── database.py               # 数据层核心
│                              #   · DB_TYPE 自动检测（MySQL/SQLite）
│                              #   · DDL 双语法建表
│                              #   · get_system_setting() 键值对配置
│
├── extensions.py             # Flask 扩展单例
│                              #   · LoginManager 实例
│
├── blueprints/               # 路由层（14 个模块）
│   ├── __init__.py           #   统一导出所有 Blueprint
│   ├── auth.py               #   登录/注销
│   ├── dashboard.py          #   看板/提醒/审计日志
│   ├── devices.py            #   设备 CRUD
│   ├── maintenance.py        #   维护计划/记录/维修
│   ├── spare_part.py         #   备件库存管理
│   ├── documents.py          #   文档上传/审批/历史
│   ├── approvals.py          #   审批流程
│   ├── borrowing.py          #   文档借阅
│   ├── device_changes.py     #   设备状态变更审批
│   ├── users.py              #   用户管理
│   ├── settings.py           #   系统设置
│   ├── password.py           #   密码重置
│   ├── search.py             #   全局搜索
│   └── esign.py              #   电子签名
│
├── models/                   # 领域模型
│   ├── user.py               #   User 类（UserMixin）
│   ├── maintenance.py        #   维护计划/记录模型
│   ├── spare_part.py         #   备件/入库/消耗/预警模型
│   └── electronic_signature.py # 电子签名模型
│
├── templates/                # Jinja2 模板
│   ├── base.html             #   基础布局（侧边栏 + 导航）
│   ├── login.html            #   登录页（独立布局）
│   ├── device_*.html         #   设备相关页面
│   ├── spare_part_*.html     #   备件相关页面
│   ├── components/           #   可复用组件
│   │   ├── esign_modal.html  #     电子签名弹窗
│   │   └── maintenance_dashboard.html # 维护看板组件
│   └── ...
│
├── static/                   # 静态资源
│   ├── css/                  #   自定义样式（6 层级联）
│   │   ├── variables.css     #     CSS 变量
│   │   ├── base.css          #     Reset + 排版
│   │   ├── layout.css        #     布局
│   │   ├── components.css    #     组件
│   │   ├── pages.css         #     页面
│   │   └── pages-enhanced.css #   增强页面
│   └── vendor/               #   第三方库（本地化）
│       ├── bootstrap.min.css #     Bootstrap 5.3.3
│       ├── bootstrap.bundle.min.js
│       └── lucide.min.js     #     图标库
│
├── utils/                    # 工具函数
│   ├── decorators.py         #   权限装饰器
│   ├── audit.py              #   审计日志写入
│   ├── file_utils.py         #   文件处理
│   ├── helpers.py            #   辅助函数
│   ├── logging_config.py     #   日志配置
│
├── tests/                    # 测试文件
│   ├── test_api.py           #   API 集成测试
│   ├── test_auth.py          #   认证测试
│   ├── test_esign.py         #   电子签名测试
│   └── test_maintenance.py   #   维护模块测试
│
├── scripts/                  # 一次性/历史脚本
│   ├── db/                   #   数据库迁移工具（一次性，用完即可）
│   │   ├── import_mysql.py           # 从 sqlite_export.json 导入 MySQL
│   │   └── migrate_sqlite_to_mysql.py # SQLite 整库迁到 MySQL
│   ├── webhook_server.py     #   GitHub Webhook 监听器（已停用，见下方说明）
│   └── webhook-deploy.sh     #   自动部署脚本（同上）
│
├── deploy/                   # 部署
│   ├── compose-deploy.sh     #   一键发布（拉代码→建镜像→换容器→等健康）
│   ├── status.sh             #   上线状态自检（只读，8 项）
│   ├── nginx-http-direct.conf.example  # nginx 反代样例（HTTP 直连）
│   ├── nginx-ssl.conf.example          # nginx 反代样例（HTTPS）
│   ├── dms.service           #   ⚠️ 历史：systemd 单元，已由 Docker 取代
│   └── dms-webhook.service   #   ⚠️ 历史：Webhook 服务单元，服务已停用
│
└── docs/                     # 文档
    ├── 上线操作手册.md         #   发布/回滚/排错（运维必看）
    ├── ARCHITECTURE.md       #   架构文档
    ├── DEVELOPMENT.md        #   本文件
    ├── API_REFERENCE.md      #   API 参考
    ├── 使用手册.md            #   用户手册
    └── PRD-2026-05-11.md     #   产品需求文档（2026-05 版）
```

> **关于 webhook 与 systemd**：这两套是 Docker 改造之前的上线方式。
> 现在服务器上 `dms` 和 `dms-webhook` 两个 systemd 服务都是 `inactive`，
> 发布统一走 `deploy/compose-deploy.sh`。相关文件保留仅为追溯，
> 不要在正在用容器的机器上再 `systemctl start dms`，会抢占 `127.0.0.1:5000`。

---

## 开发工作流

### 日常开发流程

```
1. 拉取最新代码
   git pull origin main

2. 确认数据库状态
   python -c "from database import init_db; init_db()"

3. 启动开发服务器
   python app.py

4. 修改代码 → 浏览器刷新（开发模式自动检测变更）

5. 提交代码
   git add -A
   git commit -m "feat: 描述你的改动"
   git push origin main
```

### 代码提交规范

推荐 [Conventional Commits](https://www.conventionalcommits.org/) 格式：

```
feat: 新增忘记密码功能
fix: 修复 SQLite 语法残留导致 MySQL 报错
refactor: 将 app.py 拆分为 Blueprint 模块化架构
style: 统一下拉菜单样式
docs: 更新 API 参考文档
test: 添加电子签名模块测试
```

---

## 添加新功能

### 添加新 Blueprint 模块

**步骤 1**：创建 `blueprints/your_module.py`

```python
from flask import Blueprint, render_template
from flask_login import login_required
from database import get_db

your_bp = Blueprint("your_module", __name__)

@your_bp.route("/your-path")
@login_required
def your_view():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM your_table")
    items = cur.fetchall()
    conn.close()
    return render_template("your_template.html", items=items)
```

**步骤 2**：在 `blueprints/__init__.py` 中导出

```python
from blueprints.your_module import your_bp
```

**步骤 3**：在 `app.py` 的 `create_app()` 中注册

```python
app.register_blueprint(your_bp)
```

### 添加新数据表

**步骤 1**：在 `database.py` 的 `init_db()` 中添加 DDL

```python
if DB_TYPE == "mysql":
    cur.execute("""
        CREATE TABLE IF NOT EXISTS your_table (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(200) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
else:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS your_table (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
```

**步骤 2**：在 `templates/` 中创建对应的页面模板

**步骤 3**：在 `tests/` 中添加数据表存在性测试

---

## 数据库操作规范

### 获取连接

```python
from database import get_db

conn = get_db()
cur = conn.cursor()
# ... 数据库操作 ...
conn.close()
```

### 跨数据库兼容的 SQL 写法

| 操作 | SQLite | MySQL |
|------|--------|-------|
| 当前时间 | `datetime('now')` | `NOW()` |
| 提取年份 | `strftime('%Y', col)` | `YEAR(col)` |
| 占位符 | `?` | `%s` |
| 自增主键 | `INTEGER PRIMARY KEY AUTOINCREMENT` | `INT AUTO_INCREMENT PRIMARY KEY` |

**必须使用 `DB_TYPE` 分支**来编写跨数据库兼容的 SQL：

```python
if DB_TYPE == "mysql":
    cur.execute("SELECT YEAR(created_at) FROM devices")
else:
    cur.execute("SELECT strftime('%Y', created_at) FROM devices")
```

### 系统设置读写

```python
from database import get_system_setting, set_system_setting

# 读取
enabled = get_system_setting("borrowing_enabled")  # 返回字符串或 None

# 写入
set_system_setting("borrowing_enabled", "true")
```

### 事务使用

```python
conn = get_db()
try:
    cur = conn.cursor()
    cur.execute("INSERT INTO ...")
    cur.execute("UPDATE ...")
    conn.commit()
except Exception:
    conn.rollback()
    raise
finally:
    conn.close()
```

---

## 前端开发规范

### CSS 架构约定

修改样式时，按以下层级确定写入位置：

1. **全局变量** → `variables.css`
2. **基础元素** → `base.css`
3. **布局结构** → `layout.css`
4. **UI 组件** → `components.css`
5. **特定页面** → `pages.css` 或页面内 `<style>` 块

### 表单元素约定

- input 文本输入：`class="form-control"`
- select 下拉菜单：`class="form-select"`（不要同时添加 `form-control`）
- 小尺寸变体：`class="form-control-sm"` / `class="form-select form-select-sm"`
- 筛选栏中的表单元素会在 `filter-bar` 容器中自动适配高度

### JavaScript 约定

- 使用原生 JavaScript（无 jQuery 依赖）
- 弹窗操作使用 `showModal()` / `hideModal()` 模式
- API 调用使用 `fetch()` + Promise 链
- Icon 初始化：页面加载后调用 `lucide.createIcons()`

### 模板约定

- 所有页面继承 `base.html`（登录页除外）
- 页面标题使用 `page-hero` 组件
- 数据表格使用 `data-table-header` + `table` 组合
- 筛选栏使用 `filter-bar` 或 `form-row-inline` 容器
- 弹窗模态框放在页面底部，通过 JS 控制显示

---

## 测试指南

### 运行测试

```bash
# 运行所有测试
python -m pytest tests/ -v

# 运行特定模块测试
python -m pytest tests/test_esign.py -v

# 运行特定测试函数
python -m pytest tests/test_esign.py::test_sign_verify -v
```

### 测试文件清单

| 文件 | 测试对象 | 用例数 |
|------|----------|--------|
| `test_api.py` | API 端点集成测试 | - |
| `test_auth.py` | 登录/注销/权限 | - |
| `test_esign.py` | 电子签名验证 | 14 |
| `test_maintenance.py` | 维护计划/记录 | - |
| `test_password_and_bell.py` | 密码重置 + 提醒 | - |

### 编写测试规范

```python
import pytest
from app import create_app

@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client

def test_your_feature(client):
    # 1. 准备数据
    # 2. 执行操作
    # 3. 断言结果
    response = client.get("/your-path")
    assert response.status_code == 200
```

---

## 日志与调试

### 日志文件位置

| 日志 | 路径 | 内容 |
|------|------|------|
| 应用日志 | `logs/app.log` | 请求、SQL 执行、业务流程 |
| 错误日志 | `logs/error.log` | 异常堆栈、启动错误 |
| 审计日志 | `audit_logs` 表 | 用户操作审计追踪 |

### 常用调试命令

```bash
# 实时查看应用日志
tail -f logs/app.log

# 搜索错误
grep -i "error\|exception" logs/app.log

# 查看最近的 50 条日志
tail -n 50 logs/app.log
```

---

## 常见问题

### 启动报错：`ImportError: No module named 'flask'`

确保已激活虚拟环境：

```bash
.venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

### 数据库报错 `no such table`

运行数据库初始化：

```bash
python -c "from database import init_db; init_db()"
```

### 端口被占用

```bash
# Windows
netstat -ano | findstr :5000

# Linux
lsof -i :5000
```

### MySQL 连接失败

1. 检查 `.env` 文件中的数据库配置
2. 确认 MySQL 服务正在运行
3. 如不需要 MySQL，删除或注释 `.env` 中的数据库配置，
   系统会自动降级到 SQLite

### CSS 修改不生效

浏览器缓存可能持有旧版本。在 `base.html` 中已使用 `?v=2` 查询参数做缓存破坏。
如果仍然不生效，在对应 CSS 链接后手动更新版本号。

---

*本文档随项目演进持续更新。如有疑问，请查阅 [架构文档](./ARCHITECTURE.md) 或提交 Issue。*
