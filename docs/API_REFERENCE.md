# DMS API 参考文档

> 面向集成开发者和前端开发者。所有路由需要登录认证（标注 ✅ 的除外）。

---

## 目录

1. [认证说明](#认证说明)
2. [数据看板与首页](#数据看板与首页)
3. [设备管理](#设备管理)
4. [文档管理](#文档管理)
5. [借阅管理](#借阅管理)
6. [审批流程](#审批流程)
7. [设备状态变更](#设备状态变更)
8. [维护管理](#维护管理)
9. [备件管理](#备件管理)
10. [用户管理](#用户管理)
11. [密码重置](#密码重置)
12. [电子签名](#电子签名)
13. [全局搜索](#全局搜索)
14. [系统设置](#系统设置)
15. [数据导出](#数据导出)
16. [错误处理](#错误处理)

---

## 认证说明

所有 API 端点（除 `/login` 外）均需要用户认证。

- **认证方式**：Session Cookie（Flask-Login）
- **登录端点**：`POST /login`
- **注销端点**：`GET /logout`
- **未认证响应**：302 重定向到 `/login`

### 登录

```
POST /login
Content-Type: application/x-www-form-urlencoded

username=admin&password=admin123

Response: 302 → /dashboard（成功）或 /login（失败）
```

### 权限控制

API 端点通过以下方式控制访问：
- `@login_required` 装饰器：需要登录
- `current_user.has_permission("xxx")` 函数检查：需要特定权限
- `current_user.is_admin`：需要管理员角色
- 侧边栏菜单可见性基于 `MENU_PERMISSIONS` 配置

---

## 数据看板与首页

### 数据看板

```
GET /
GET /dashboard
```

**权限**：所有已登录用户

**响应**：渲染 `device_board.html`，显示设备统计概览。

**模板变量**：
| 变量 | 类型 | 说明 |
|------|------|------|
| `devices` | list | 设备列表 |
| `status_counts` | dict | 各状态设备数量 |
| `pagination` | object | 分页信息 |

### 仪表盘 API

```
GET /api/dashboard/due-maintenance
```

**响应示例**：
```json
{
  "count": 5,
  "items": [
    {
      "device_code": "EQ-001",
      "device_name": "反应釜",
      "type": "calibration",
      "next_date": "2026-06-01"
    }
  ]
}
```

```
GET /api/dashboard/calibration-overdue-count
```

**响应**：`{ "count": 3 }`

### 提醒中心

```
GET /reminders
```

**权限**：所有已登录用户

显示待办事项聚合：待审批文档、待处理设备变更、到期校准/维护。

### 审计日志

```
GET /audit_log
GET /audit_log/export
```

**权限**：仅 admin（页面与导出路由统一由 `@admin_required` 保护，页面按钮不再做重复判断）

`/audit_log` 支持 `user` / `start_date` / `end_date` / `target_type` 四个筛选参数，页面最多显示 500 条。

`/audit_log/export` 返回 `.xlsx` 附件，参数与页面筛选完全一致：

| 参数 | 说明 |
|------|------|
| `user` | 操作人，模糊匹配 |
| `start_date` / `end_date` | 日期范围，`YYYY-MM-DD`（含当天） |
| `target_type` | 目标类型，精确匹配 |

四个参数都不传（或全为空）时导出全表；只要带了任一有效条件就只导出筛选结果。
导出不受页面 500 条上限限制；筛选结果为 0 条时返回只有表头的空文件。

---

## 设备管理

### 设备详情

```
GET /<int:device_id>
```

**权限**：登录即可查看

**模板变量**：
| 变量 | 说明 |
|------|------|
| `device` | 设备完整信息 |
| `documents` | 关联文档列表 |
| `maintenance_plans` | 维护计划 |

### 编辑设备

```
GET /<int:device_id>/edit
POST /<int:device_id>/edit
```

**权限**：`device_management`

**POST 参数**：
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | 是 | 设备名称 |
| `model` | string | 否 | 型号 |
| `location` | string | 否 | 位置 |
| `department` | string | 否 | 部门 |

### 删除设备

```
POST /<int:device_id>/delete
```

**权限**：`device_management`

**响应**：302 重定向到设备看板

### 切换设备状态

```
POST /<int:device_id>/toggle
```

**权限**：`device_management`

切换设备启用/停用状态。

### 变更设备状态

```
POST /<int:device_id>/change_status
Content-Type: application/x-www-form-urlencoded

new_status=maintenance
```

**权限**：`device_operation`

**参数**：
| 参数 | 说明 |
|------|------|
| `new_status` | 目标状态：`active`, `maintenance`, `inactive`, `retired`, `debug`, `standby`, `repair` |

> 变更到关键状态（`inactive`/`retired`）将自动创建审批请求。

### 设备列表导出

```
GET /devices/export
```

**权限**：登录即可

**响应**：Excel 文件下载（`.xlsx`）

---

## 文档管理

### 上传文档

```
GET /upload_doc/<int:device_id>
POST /upload_doc/<int:device_id>
```

**权限**：`document_upload`

**POST 参数**（multipart/form-data）：
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `files[]` | file | 是 | 上传的文件 |
| `doc_type_per_file_N` | string | 否 | 每个文件的文档类型 |

### 下载文档

```
GET /download/<int:doc_id>
```

**权限**：`document_view`

**响应**：文件流（`Content-Disposition: attachment`）

### 删除文档

```
POST /delete_doc/<int:doc_id>
```

**权限**：`document_archive`

### 提交审批

```
POST /document/<int:doc_id>/submit
```

**权限**：`document_approval`

将文档状态从 `draft` 变更为 `pending`，进入审批流程。

### 文档列表

```
GET /documents
```

**权限**：`document_view`

**查询参数**：
| 参数 | 类型 | 说明 |
|------|------|------|
| `q` | string | 搜索关键词 |
| `doc_type` | string | 文档类型筛选 |
| `status` | string | 文档状态筛选 |
| `device` | string | 关联设备筛选 |
| `uploader` | string | 上传人筛选 |

### 文档历史

```
GET /documents/<int:doc_id>/history
```

**权限**：`document_view`

### 文档导出

```
GET /documents/export
```

**权限**：`document_view`

---

## 借阅管理

### 借阅文档

```
POST /borrow/<int:doc_id>
Content-Type: application/x-www-form-urlencoded

borrower=张三&department=生产部
```

**权限**：登录即可

### 归还文档

```
POST /return/<int:borrow_id>
```

**权限**：登录即可

### 借阅列表

```
GET /borrow_list
```

**权限**：登录即可

---

## 审批流程

### 审批待办列表

```
GET /approvals
```

**权限**：`document_approval`

显示所有待审批的文档和设备状态变更请求。

### 审批决定

```
POST /approvals/<int:request_id>/decide
Content-Type: application/x-www-form-urlencoded

decision=approved&comment=同意
```

**权限**：`document_approval` 或 `quality_approval`

**参数**：
| 参数 | 说明 |
|------|------|
| `decision` | `approved` 或 `rejected` |
| `comment` | 审批意见（可选） |

---

## 设备状态变更

### 变更请求列表

```
GET /device_changes
```

**权限**：登录即可

### 处理变更请求

```
POST /device_changes/<int:req_id>/decide
Content-Type: application/x-www-form-urlencoded

decision=approved&comment=确认报废
```

**权限**：`quality_approval`

---

## 维护管理

### 维护计划页面

```
GET /device/<int:device_id>/maintenance/
```

**权限**：`device_maintenance`

### 创建维护计划

```
POST /device/<int:device_id>/maintenance/plan

{
  "type": "calibration",
  "device_id": 1,
  "interval_days": 90,
  "description": "年度校准计划"
}
```

**权限**：`device_maintenance`

### 更新维护计划

```
PUT /device/<int:device_id>/maintenance/plan/<int:plan_id>
```

### 删除维护计划

```
DELETE /device/<int:device_id>/maintenance/plan/<int:plan_id>
```

### 关闭维护计划

```
POST /device/<int:device_id>/maintenance/plan/<int:plan_id>/close
```

### 创建维护记录

```
POST /device/<int:device_id>/maintenance/plan/<int:plan_id>/record

{
  "result": "qualified",
  "executed_by": "设备工程师张三",
  "remark": "校准完成，各项指标合格",
  "spare_parts": [
    {"spare_part_id": 1, "quantity": 2}
  ]
}
```

**权限**：`device_maintenance`

> 提交维护记录时可选关联备件消耗。

### 删除维护记录

```
POST /device/<int:device_id>/maintenance/record/<int:record_id>/delete
```

### 维护历史

```
GET /device/<int:device_id>/maintenance/history
```

**查询参数**：
| 参数 | 说明 |
|------|------|
| `type` | 维护类型筛选 |
| `year` | 年份筛选 |

### 维护计划 API

```
GET /device/<int:device_id>/maintenance/api/plans
GET /device/<int:device_id>/maintenance/api/records
```

**响应**：JSON 数组

### 维修记录

```
GET /device/<int:device_id>/maintenance/repair          # 维修列表
GET /device/<int:device_id>/maintenance/repair/new      # 新建维修页面
POST /device/<int:device_id>/maintenance/repair/new     # 提交维修记录
POST /device/<int:device_id>/maintenance/repair/<int:record_id>/delete  # 删除
```

### 全局维护列表

```
GET /maintenance/all
```

### 维护数据导出

```
GET /device/<int:device_id>/maintenance/export/plans     # 计划导出
GET /device/<int:device_id>/maintenance/export/history   # 历史导出
GET /device/<int:device_id>/maintenance/export/repair    # 维修导出
```

---

## 备件管理

### 备件列表

```
GET /spare-parts/
```

**权限**：`spare_part_management`

**查询参数**：
| 参数 | 说明 |
|------|------|
| `q` | 搜索关键词（名称/编码/型号/品牌） |
| `category` | 分类筛选 |
| `stock` | 库存状态：`low`/`out`/`normal`/`over` |

### 备件 API

```
GET    /spare-parts/api/spare-parts              # 获取所有备件
POST   /spare-parts/api/spare-parts              # 新增备件
PUT    /spare-parts/api/spare-parts/<int:part_id> # 编辑备件
POST   /spare-parts/api/spare-parts/<int:part_id>/toggle  # 启用/停用
```

**新增/编辑备件请求体**：
```json
{
  "name": "O型密封圈",
  "category": "seal",
  "specification": "50×3.5mm",
  "unit": "个",
  "brand": "NOK",
  "safety_stock_min": 10,
  "safety_stock_max": 100,
  "supplier_name": "XX密封件有限公司",
  "supplier_contact": "李经理",
  "supplier_phone": "13800000000",
  "remark": ""
}
```

### 备件入库

```
POST /spare-parts/api/spare-parts/<int:part_id>/inbound

{
  "quantity": 50,
  "unit_price": 12.50,
  "batch_no": "B2026-001",
  "inbound_date": "2026-05-25",
  "remark": "季度采购"
}
```

**权限**：`spare_part_management`

> 入库后自动更新 `current_stock` 和 `weighted_avg_price`。

### 备件消耗

```
POST /spare-parts/api/consumptions

{
  "spare_part_id": 1,
  "quantity": 3,
  "remark": "日常维修消耗"
}
```

**权限**：`spare_part_management`

> 消耗后自动扣减库存并触发预警检查。

### 批量消耗

```
POST /spare-parts/api/consumptions/batch

{
  "items": [
    {"spare_part_id": 1, "quantity": 2},
    {"spare_part_id": 3, "quantity": 1}
  ],
  "remark": "季度保养消耗"
}
```

### 预警管理

```
GET  /spare-parts/alerts                              # 预警列表
POST /spare-parts/api/alerts/<int:alert_id>/resolve   # 标记已处理
```

### 入库记录

```
GET /spare-parts/inbounds
```

### 消耗记录

```
GET /spare-parts/consumptions
```

### 成本统计

```
GET /spare-parts/stats
```

**查询参数**：
| 参数 | 说明 |
|------|------|
| `start_date` | 开始日期 |
| `end_date` | 结束日期 |
| `device_id` | 按设备筛选 |

### 备件数据导出

```
GET /spare-parts/export              # 备件列表导出
GET /spare-parts/inbounds/export     # 入库记录导出
GET /spare-parts/consumptions/export # 消耗记录导出
```

---

## 用户管理

### 用户列表

```
GET /users
```

**权限**：`user_management`

### 创建用户

```
POST /users/create
Content-Type: application/x-www-form-urlencoded

username=newuser&password=password123&role=equipment_engineer
```

**权限**：`user_management`

### 切换用户状态

```
POST /users/<int:user_id>/toggle
```

**权限**：`user_management`

启用/停用指定用户。

### 设置用户权限

```
POST /users/<int:user_id>/permissions

{
  "permissions": ["device_management", "document_view", "device_maintenance"]
}
```

**权限**：`user_management`（仅管理员可修改权限）

### 删除用户

```
POST /users/<int:user_id>/delete
```

**权限**：`user_management`

---

### 重置用户密码

```
POST /users/<int:user_id>/reset-password
```

**权限**：仅 `admin`（`@admin_required`）；不能重置当前登录用户自身，允许重置其他 admin 账号。

**表单参数**：`new_password`、`confirm_password`（两次输入需一致，新密码长度不少于 4 个字符）。

**响应**：`302 redirect` 回 `/users`，结果通过 `flash` 提示。

该端点与 `POST /admin/password-resets/<int:request_id>/reset`（执行密码重置）**共用同一改密服务** `utils/password_utils.reset_user_password()`：两者都会把用户密码改为新值、写入审计日志 `reset_user_password`，并**把该用户全部 `pending` 状态的密码重置申请批量置为 `completed`**。因此直接重置后旧的待处理申请不会再被二次处理，顶栏闹铃归零，用户也可重新提交申请。

---

## 密码重置

### 忘记密码

```
GET /forgot-password
POST /forgot-password

username=admin
```

**权限**：无需登录 ✅

提交后生成密码重置请求，管理员可在后台处理。

### 管理员密码重置列表

```
GET /admin/password-resets
```

**权限**：管理类角色（`admin`/`qa_manager`/`production_supervisor`）

### 执行密码重置

```
POST /admin/password-resets/<int:request_id>/reset
```

**权限**：仅 admin（`@admin_required`）

表单字段 `new_password` / `confirm_password`，管理员填写的新密码经服务端校验（至少 4 个字符、两次一致）后写入 `users.password`，**不是**设为系统默认值。

与 `POST /users/<int:user_id>/reset-password` 共用 `utils/password_utils.reset_user_password()`：同一事务内改密、把该用户所有 `pending` 申请批量置为 `completed`（含当前这条），提交后写一条 `reset_user_password` 审计日志。`action=cancel` 时只把该条置 `cancelled`，不改密码。

---

## 电子签名

### 签名验证 API

```
POST /esign/api/verify

{
  "username": "admin",
  "password": "admin123",
  "sign_meaning": "审批确认",
  "record_type": "approval_request",
  "record_id": 1
}
```

**权限**：`electronic_signature`

**响应示例**：
```json
{
  "success": true,
  "message": "签名验证成功",
  "sign_id": 42
}
```

**错误响应**：
```json
{
  "success": false,
  "error": "密码错误",
  "remaining_attempts": 2
}
```

**签名含义（sign_meaning）**：
| 值 | 说明 |
|------|------|
| `审批确认` | 文档审批签名 |
| `执行确认` | 维护/校准执行确认 |
| `审核确认` | QA 审核签名 |
| `变更确认` | 设备状态变更确认 |

### 签名锁定状态

```
GET /esign/api/lockout_status?username=admin
```

**响应**：
```json
{
  "locked": false,
  "remaining_attempts": 3
}
```

### 签名解锁

```
POST /esign/api/unlock

{
  "username": "admin",
  "admin_password": "admin_super_password"
}
```

### 签名记录

```
GET /esign/records                         # 签名记录列表
GET /esign/records/<record_type>/<int:record_id>  # 特定记录签名历史
```

**查询参数**（列表）：
| 参数 | 说明 |
|------|------|
| `record_type` | 业务类型筛选 |
| `sign_meaning` | 签名含义筛选 |

---

## 全局搜索

### 搜索 API

```
POST /search/api

{
  "q": "反应釜"
}
```

**权限**：登录即可

**响应**：
```json
{
  "devices": [...],
  "documents": [...],
  "spare_parts": [...]
}
```

### 搜索结果页面

```
GET /search/results?q=反应釜
```

**权限**：登录即可

---

## 系统设置

### 系统设置页面

```
GET /admin/settings
POST /admin/settings
```

**权限**：`system_settings`

**支持的设置项**：
| 设置键 | 说明 | 可选值 |
|--------|------|--------|
| `borrowing_enabled` | 借阅功能开关 | `true` / `false` |

---

## 数据导出

系统支持以下模块的 Excel 导出（`.xlsx` 格式，使用 `openpyxl` 库）：

| 导出端点 | 说明 |
|----------|------|
| `GET /devices/export` | 设备列表 |
| `GET /documents/export` | 文档列表 |
| `GET /spare-parts/export` | 备件列表 |
| `GET /spare-parts/inbounds/export` | 入库记录 |
| `GET /spare-parts/consumptions/export` | 消耗记录 |
| `GET /device/<id>/maintenance/export/plans` | 维护计划 |
| `GET /device/<id>/maintenance/export/history` | 维护历史 |
| `GET /device/<id>/maintenance/export/repair` | 维修记录 |

所有导出端点均支持当前页面的筛选参数（搜索关键词、分类、日期范围等）。

---

## 错误处理

### HTTP 状态码

| 状态码 | 说明 |
|--------|------|
| 200 | 成功 |
| 201 | 创建成功 |
| 302 | 重定向（登录/权限不足） |
| 400 | 请求参数错误 |
| 401 | 未认证 |
| 403 | 权限不足 |
| 404 | 资源不存在 |
| 429 | 请求频率限制（电子签名锁定） |
| 500 | 服务器内部错误 |

### API 错误响应格式

```json
{
  "error": "具体错误信息",
  "code": "ERROR_CODE"
}
```

### 常见错误

| 错误 | 原因 | 解决方案 |
|------|------|----------|
| `请先登录` | 未认证 | 先调用 `/login` |
| `权限不足` | 角色无相应权限 | 联系管理员分配权限 |
| `密码错误` | 电子签名密码不匹配 | 确认用户名和密码 |
| `账号已锁定` | 签名失败超限 | 等待 5 分钟或管理员解锁 |
| `库存不足` | 消耗量超过当前库存 | 先入库补充 |

---

*本文档基于系统 v2.0 生成，路由数按 `app.url_map`（除 static）核对为 86 条。如有疑问，请查阅 [架构文档](./ARCHITECTURE.md)。*
