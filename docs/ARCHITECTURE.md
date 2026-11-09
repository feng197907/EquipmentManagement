# DMS 系统架构文档

> 版本：v2.0 | 更新：2026-05-25 | 适用于模块化重构后的架构

---

## 目录

1. [架构概览](#架构概览)
2. [分层设计](#分层设计)
3. [Blueprint 模块](#blueprint-模块)
4. [数据层](#数据层)
5. [权限系统](#权限系统)
6. [模板渲染与静态资源](#模板渲染与静态资源)
7. [关键设计决策](#关键设计决策)

---

## 架构概览

DMS 采用 **Flask 应用工厂 + Blueprint 模块化** 架构，遵循关注点分离原则。

```
┌─────────────────────────────────────────────────────┐
│                    浏览器客户端                       │
├─────────────────────────────────────────────────────┤
│  HTTP Request                                       │
│  ▼                                                  │
│  ┌─────────┐                                        │
│  │ app.py   │  工厂函数 create_app()                  │
│  │ (入口)    │  · 注册 Blueprint                      │
│  └────┬─────┘  · 初始化 Flask-Login                  │
│       │         · 注入全局上下文                       │
│       ▼         · 初始化数据库                         │
│  ┌─────────────────────────────────────────────┐    │
│  │           Blueprints (14 个模块)               │    │
│  │  ┌────────┐ ┌──────────┐ ┌──────────┐        │    │
│  │  │ auth   │ │ devices  │ │ documents│  ...   │    │
│  │  └───┬────┘ └────┬─────┘ └────┬─────┘        │    │
│  └──────┼───────────┼────────────┼──────────────┘    │
│         │           │            │                    │
│         ▼           ▼            ▼                    │
│  ┌─────────────────────────────────────────────┐    │
│  │         database.py（数据访问层）              │    │
│  │  get_db() / init_db() / get_system_setting() │    │
│  │  ┌──────────┐          ┌──────────┐          │    │
│  │  │  SQLite   │  ←──→   │  MySQL    │         │    │
│  │  │ (开发环境) │  运行时   │ (生产环境) │         │    │
│  │  └──────────┘  切换    └──────────┘          │    │
│  └─────────────────────────────────────────────┘    │
│                                                      │
│  ┌─────────────────────────────────────────────┐    │
│  │         Templates (Jinja2 模板引擎)           │    │
│  │  base.html → 页面模板 → 组件模板              │    │
│  └─────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────┘
```

### 架构特点

| 特点 | 说明 |
|------|------|
| **工厂模式** | `create_app()` 延迟创建实例，支持多环境配置 |
| **模块化** | 14 个 Blueprint 独立路由，按功能域划分 |
| **双数据库** | SQLite（开发零配置）+ MySQL（生产高性能） |
| **SSR 渲染** | Jinja2 服务端模板渲染，无 SPA 框架 |
| **RBAC 权限** | 7 角色 × 22 权限粒度的访问控制 |

---

## 分层设计

### 层职责划分

```
┌──────────────┐  路由分发、请求响应
│  Blueprints  │  权限校验 @login_required
│  (Controller)│  业务逻辑编排
├──────────────┤
│   Models     │  数据类定义（User, MaintenancePlan 等）
│   (Domain)   │  不包含数据库操作
├──────────────┤
│  database.py │  SQL 执行、连接管理
│   (Data)     │  跨存储引擎抽象（SQLite/MySQL）
└──────────────┘
```

### 应用入口 `app.py`

```python
def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = SECRET_KEY
    login_manager.init_app(app)

    # 注册 14 个 Blueprint
    app.register_blueprint(auth_bp)
    app.register_blueprint(devices_bp)
    # ... 共 14 个

    init_db()                     # 自动建表
    return app
```

---

## Blueprint 模块

### 完整清单（14 个模块）

| Blueprint | 文件 | 路由前缀 | 核心功能 |
|-----------|------|----------|----------|
| `auth_bp` | `auth.py` | `/` | 登录/注销、设备列表首页、设备导出 |
| `dashboard_bp` | `dashboard.py` | `/` | 数据看板、提醒中心、用户故事、审计日志、新增设备 |
| `devices_bp` | `devices.py` | `/` | 设备详情、编辑、删除、状态变更、启用/停用 |
| `documents_bp` | `documents.py` | `/` | 文档上传/下载/删除/提交审批、文档列表、文档历史、文档导出 |
| `borrowing_bp` | `borrowing.py` | `/` | 文档借阅/归还、借阅列表 |
| `approvals_bp` | `approvals.py` | `/` | 审批待办列表、审批决定 |
| `device_changes_bp` | `device_changes.py` | `/` | 设备状态变更审批 |
| `maintenance_bp` | `maintenance.py` | `/device/<int:device_id>/maintenance` | 维护计划 CRUD、维护记录、维修记录、历史查看、数据导出 |
| `spare_part_bp` | `spare_part.py` | `/spare-parts` | 备件 CRUD、入库/消耗、库存预警、成本统计、数据导出 |
| `users_bp` | `users.py` | `/` | 用户 CRUD、角色权限分配、启用/停用、删除 |
| `settings_bp` | `settings.py` | `/` | 系统设置（借阅开关等） |
| `password_bp` | `password.py` | `/` | 忘记密码、管理员密码重置 |
| `search_bp` | `search.py` | `/search` | 全局搜索（设备/文档/备件） |
| `esign_bp` | `esign.py` | `/esign` | 电子签名验证、签名记录、锁定检测 |

### Blueprint 路由汇总

| 模块 | 路由数 | 主要方法 |
|------|--------|----------|
| auth | 4 | GET, POST |
| dashboard | 11 | GET, POST |
| devices | 6 | GET, POST |
| documents | 7 | GET, POST |
| borrowing | 3 | GET, POST |
| approvals | 2 | GET, POST |
| device_changes | 2 | GET, POST |
| maintenance | 18 | GET, POST, PUT, DELETE |
| spare_part | 16 | GET, POST, PUT |
| users | 5 | GET, POST |
| settings | 1 | GET, POST |
| password | 3 | GET, POST |
| search | 2 | GET, POST |
| esign | 5 | GET, POST |
| **小计** | **85** | |
| `/healthz` | 1 | GET（直接注册在 app 上，不属任何蓝图） |
| **总计** | **86** | |

> 统计口径：`app.url_map` 中除 `static` 外的全部路由。
> 其中 4 个 URL 上挂了多个端点（同一路径的 GET / POST 分开注册），
> 所以按端点计数是 86、按 URL 去重是 82。

---

## 数据层

### 数据库架构

```
┌─────────────────────────────────────┐
│           database.py               │
│  ┌─────────────────────────────┐   │
│  │  DB_TYPE 自动检测             │   │
│  │  · .env DB_TYPE=mysql       │   │
│  │  · MySQL 连接可用性验证       │   │
│  │  · 降级策略：MySQL→SQLite    │   │
│  └─────────────────────────────┘   │
│                                     │
│  核心函数：                          │
│  · get_db()      → 获取连接         │
│  · init_db()     → 自动建表         │
│  · get_system_setting() → 读取配置  │
│  · set_system_setting() → 写入配置  │
└─────────────────────────────────────┘
```

### 数据表清单（13 张表 + 系统设置表）

| 表名 | 说明 | 关键字段 |
|------|------|----------|
| `users` | 用户账号 | username, password_hash, role, permissions, is_active |
| `devices` | 设备台账 | code, name, model, status, location, department |
| `documents` | 文档记录 | title, doc_type, status, file_path, version, device_id |
| `approval_requests` | 审批请求 | document_id, status, requested_by, decided_by |
| `borrow_records` | 借阅记录 | document_id, borrower, borrow_date, return_date |
| `device_status_requests` | 设备状态变更 | device_id, new_status, requested_by, decided_by |
| `maintenance_plans` | 维护计划 | device_id, type, interval_days, next_date |
| `maintenance_records` | 维护记录 | plan_id, result, executed_by, executed_at |
| `repair_records` | 维修记录 | device_id, fault_description, repair_action |
| `spare_parts` | 备件目录 | code, name, category, current_stock, weighted_avg_price |
| `spare_part_inbounds` | 备件入库 | spare_part_id, quantity, unit_price, batch_no |
| `spare_part_consumptions` | 备件消耗 | spare_part_id, quantity, related_record_type/id |
| `spare_part_alerts` | 库存预警 | spare_part_id, alert_type, resolved |
| `electronic_signatures` | 电子签名 | user_id, sign_meaning, record_type, record_id, verified_at |
| `system_settings` | 系统配置(键值对) | key, value |
| `password_reset_requests` | 密码重置 | user_id, status, token, created_at |
| `audit_logs` | 审计日志 | user_id, action, target_type, target_id, timestamp |

### SQLite/MySQL 兼容策略

- DDL 建表语句按 `DB_TYPE` 分支，分别使用 SQLite 和 MySQL 语法
- `DATE()` → SQLite, `NOW()` → MySQL
- 占位符：SQLite 用 `?`, MySQL 用 `%s`
- `database.py` 在模块初始化时自动检测并设置 `DB_TYPE`

---

## 权限系统

### 访问控制模型

```
         ┌──────────┐
         │   User    │
         │   .role   │──→ 7 种角色之一
         │ .is_admin │
         └────┬─────┘
              │
    ┌─────────▼──────────┐
    │  ROLE_PERMISSIONS   │
    │  角色 → 功能权限列表  │
    │  config.py 中定义    │
    └─────────┬──────────┘
              │
    ┌─────────▼──────────┐
    │  MENU_PERMISSIONS   │
    │  菜单 → 访问控制     │
    │  base.html 侧边栏    │
    └────────────────────┘
```

### 7 种角色 × 22 项功能权限

| 角色 | 权限数 | 典型权限 |
|------|--------|----------|
| admin | 17 | 全部权限 |
| qa_manager | 5 | quality_approval, report_view, document_approval |
| equipment_engineer | 8 | device_maintenance, calibration_records, spare_part_management |
| validation_engineer | 5 | iqoqpq_management, validation_docs, document_approval |
| archivist | 4 | document_upload, document_archive, document_management |
| production_supervisor | 5 | production_approval, report_view, device_view |
| metrology_engineer | 5 | metrology_management, device_calibration, calibration_records |

### 权限检查机制

- **模板层**：`current_user.has_permission("xxx")` 控制菜单/按钮可见性
- **路由层**：`utils/decorators.py` 中的自定义装饰器
- **数据层**：`config.py` 的 `has_permission(role, permission)` 函数

---

## 模板渲染与静态资源

### 前端技术栈

| 组件 | 技术 | 版本 |
|------|------|------|
| CSS 框架 | Bootstrap | 5.3.3（本地化） |
| 图标库 | Lucide Icons | 本地化 JS |
| 模板引擎 | Jinja2 | Flask 内置 |
| 自定义样式系统 | variables/base/layout/components/pages CSS | 6 层级联 |

### CSS 架构

```
variables.css      → CSS 自定义属性（颜色、间距、圆角等）
    ↓
base.css           → Reset + 基础排版
    ↓
layout.css         → 布局（侧边栏、页面容器、网格）
    ↓
components.css     → UI 组件（按钮、表单、表格、筛选栏、弹窗）
    ↓
pages.css          → 页面级样式
    ↓
pages-enhanced.css → 增强页面样式
```

### 模板继承链

```
base.html（侧边栏 + 导航 + 全局上下文）
  ├── login.html（独立布局，不继承 base）
  └── 所有业务页面
       ├── device_*.html
       ├── spare_part_*.html
       ├── documents.html
       └── components/
            ├── esign_modal.html
            └── maintenance_dashboard.html
```

---

## 关键设计决策

### 为什么选择 SSR 而非 SPA

- 目标用户为制药企业员工，浏览器环境不可控
- 服务端渲染确保在低版本浏览器中正常工作
- 减少前端依赖，降低维护成本
- GMP 合规要求服务端控制所有数据输出

### 为什么选择双数据库模式

- **SQLite**：开发者零配置启动，适合本地测试
- **MySQL**：生产环境高性能、支持并发写入
- `database.py` 自动检测环境并选择，
  开发者无需手动配置

### 为什么从单文件重构为 Blueprint

- 原 `app.py` 1781 行，难以维护
- Blueprint 按功能域隔离，减少耦合
- 每个模块可独立测试、独立部署
- 便于团队协作（不同人负责不同模块）

### 为什么键值对做系统设置

- `system_settings` 表存储 `key → value`
- 避免频繁修改表结构
- 支持运行时动态配置（借阅开关、通知设置等）
- 通过 `get_system_setting()` / `set_system_setting()` API 读写

---

## 附录：完整路由表

请参阅 [API 参考文档](./API_REFERENCE.md) 了解每个端点的详细参数和响应。

---

*本文档随系统架构变化而更新。最后一次重构：2026-05-18 Blueprint 模块化。*
