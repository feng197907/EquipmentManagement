import importlib

# 看板与提醒 Blueprint
from pathlib import Path
from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from config import DEVICE_STATUS_LABELS, DOC_STATUS_LABELS, ROLE_LABELS
from database import get_db, get_system_setting
from utils.audit import log_action
from utils.decorators import admin_required
from utils.helpers import build_calibration_reminders, get_document_rows
from utils.maintenance import build_due_maintenance_reminders, get_maintenance_type_label
from datetime import datetime, date, timezone


def _build_calibration_reminder_from_maintenance_plan(row):
    """将维护计划中的校准记录转换为校准提醒格式"""
    today = datetime.now(timezone.utc).date()

    next_due = row["next_due_date"]
    if isinstance(next_due, str):
        due_date = datetime.strptime(next_due, "%Y-%m-%d").date()
    elif hasattr(next_due, "date"):
        due_date = next_due.date()
    elif hasattr(next_due, "year"):
        due_date = next_due
    else:
        return None

    days_left = (due_date - today).days

    # 维护计划默认窗口也是60天内
    if days_left > 60:
        return None

    if days_left < 0:
        severity = "danger"
        label = "已逾期"
    elif days_left <= 30:
        severity = "warning"
        label = "即将到期"
    else:
        severity = "info"
        label = "需关注"

    return {
        "device_id": row["device_id"],
        "device_code": row["device_code"],
        "device_name": row["device_name"],
        "doc_id": None,
        "doc_name": "校准计划",
        "version": "-",
        "uploaded_by": row.get("created_by", ""),
        "upload_time": row.get("created_at", ""),
        "due_date": due_date.isoformat(),
        "days_left": days_left,
        "severity": severity,
        "label": label,
        "has_explicit_due": True,
        "source": "maintenance_plan",
        "plan_id": row["id"],
    }

dashboard_bp = Blueprint("dashboard", __name__)


def _load_user_manual_html():
    """读取并转换用户手册 markdown。"""
    manual_path = Path(__file__).resolve().parent.parent / "docs" / "使用手册.md"
    manual_md = manual_path.read_text(encoding="utf-8")
    markdown_lib = importlib.import_module("markdown")
    return markdown_lib.markdown(
        manual_md,
        extensions=["extra", "fenced_code", "tables", "toc"],
        output_format="html",
    )


@dashboard_bp.route("/")
@login_required
def home():
    """默认首页，跳转到设备看板"""
    return redirect(url_for("dashboard.dashboard"))


@dashboard_bp.route("/user-manual")
def user_manual():
    """用户手册页面"""
    return render_template(
        "user_manual.html",
        manual_html=_load_user_manual_html(),
        manual_title="用户手册",
    )


@dashboard_bp.route("/dashboard")
@login_required
def dashboard():
    """设备看板"""
    status_filter = request.args.get("status", "").strip()
    q = request.args.get("q", "").strip()
    try:
        page = max(1, int(request.args.get("page", 1)))
    except Exception:
        page = 1
    try:
        per_page = max(5, int(request.args.get("per_page", 20)))
    except Exception:
        per_page = 20
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT status, COUNT(*) as cnt FROM devices WHERE is_deleted IS NULL OR is_deleted = 0 GROUP BY status"
    )
    counts_rows = cur.fetchall()
    status_counts = {r["status"]: r["cnt"] for r in counts_rows}
    params = []
    where = "WHERE is_deleted IS NULL OR is_deleted = 0"
    if status_filter:
        where += " AND status = %s"
        params.append(status_filter)
    if q:
        where += " AND (device_code LIKE %s OR device_name LIKE %s OR model LIKE %s OR location LIKE %s)"
        like = f"%{q}%"
        params.extend([like, like, like, like])
    count_sql = f"SELECT COUNT(*) as total FROM devices {where}"
    cur.execute(count_sql, params)
    total = cur.fetchone()["total"]
    offset = (page - 1) * per_page
    list_sql = f"SELECT id, device_code, device_name, model, location, status FROM devices {where} ORDER BY status, device_code LIMIT %s OFFSET %s"
    list_params = params + [per_page, offset]
    cur.execute(list_sql, list_params)
    devices = [dict(r) for r in cur.fetchall()]

    # 备件预警统计
    try:
        cur.execute("SELECT COUNT(*) as cnt FROM spare_part_alerts WHERE is_resolved = 0")
        spare_alert_count = cur.fetchone()["cnt"]
        cur.execute("SELECT COUNT(*) as cnt FROM spare_parts WHERE is_active = 1 AND current_stock <= safety_stock_min AND current_stock > 0")
        spare_low_stock_count = cur.fetchone()["cnt"]
        cur.execute("SELECT COUNT(*) as cnt FROM spare_parts WHERE is_active = 1 AND current_stock <= 0")
        spare_out_stock_count = cur.fetchone()["cnt"]
    except Exception:
        spare_alert_count = 0
        spare_low_stock_count = 0
        spare_out_stock_count = 0

    conn.close()
    pagination = {"page": page, "per_page": per_page, "total": total, "pages": (total + per_page - 1) // per_page}
    return render_template(
        "device_board.html",
        status_counts=status_counts,
        devices=devices,
        status_labels=DEVICE_STATUS_LABELS,
        selected_status=status_filter,
        q=q,
        pagination=pagination,
        spare_alert_count=spare_alert_count,
        spare_low_stock_count=spare_low_stock_count,
        spare_out_stock_count=spare_out_stock_count,
    )


@dashboard_bp.route("/reminders")
@login_required
def reminders():
    """提醒中心"""
    # 筛选参数
    filter_severity = request.args.get("severity", "").strip()  # danger/warning/info/all
    filter_device = request.args.get("device", "").strip()

    conn = get_db()
    cur = conn.cursor()

    # 校准文档查询（支持设备名/编码筛选）
    if filter_device:
        cur.execute(
            "SELECT d.*, dev.device_code, dev.device_name FROM documents d "
            "JOIN devices dev ON dev.id = d.device_id "
            "WHERE d.doc_type = 'calibration' AND d.is_deleted = 0 "
            "AND (dev.device_code LIKE %s OR dev.device_name LIKE %s) "
            "ORDER BY d.upload_time DESC",
            (f"%{filter_device}%", f"%{filter_device}%"),
        )
    else:
        cur.execute(
            "SELECT d.*, dev.device_code, dev.device_name FROM documents d "
            "JOIN devices dev ON dev.id = d.device_id "
            "WHERE d.doc_type = 'calibration' AND d.is_deleted = 0 "
            "ORDER BY d.upload_time DESC"
        )
    calibration_rows = cur.fetchall()

    # 维护计划中的校准记录也纳入校准提醒
    if filter_device:
        cur.execute(
            "SELECT mp.*, dev.device_code, dev.device_name "
            "FROM maintenance_plan mp "
            "JOIN devices dev ON dev.id = mp.device_id "
            "WHERE mp.maintenance_type = 'calibration' AND mp.is_active = 1 AND mp.is_closed = 0 "
            "AND (dev.device_code LIKE %s OR dev.device_name LIKE %s) "
            "ORDER BY mp.next_due_date ASC",
            (f"%{filter_device}%", f"%{filter_device}%"),
        )
    else:
        cur.execute(
            "SELECT mp.*, dev.device_code, dev.device_name "
            "FROM maintenance_plan mp "
            "JOIN devices dev ON dev.id = mp.device_id "
            "WHERE mp.maintenance_type = 'calibration' AND mp.is_active = 1 AND mp.is_closed = 0 "
            "ORDER BY mp.next_due_date ASC"
        )
    maintenance_calibration_rows = cur.fetchall()
    cur.execute("SELECT COUNT(*) AS total FROM approval_requests WHERE status = 'pending'")
    pending_approvals = cur.fetchone()["total"]
    # 检查借阅功能是否开启
    borrowing_enabled_val = get_system_setting("borrowing_enabled")
    borrowing_enabled = (borrowing_enabled_val == "true") if borrowing_enabled_val else True
    if borrowing_enabled:
        cur.execute("SELECT COUNT(*) AS total FROM borrow_records WHERE status = 'borrowed'")
        borrowed_total = cur.fetchone()["total"]
    else:
        borrowed_total = 0

    # ---- 维护计划到期数据（与顶部铃铛数据源保持一致）----
    maintenance_data = build_due_maintenance_reminders(conn, days=7)
    conn.close()

    # 维护提醒列表：逾期 + 今日到期 + 7日内到期（校准类型已在校准提醒中展示，此处排除）
    _exclude_calibration = lambda items: [i for i in items if i.get("maintenance_type") != "calibration"]
    maintenance_reminders = (
        _exclude_calibration(maintenance_data["overdue"]) +
        _exclude_calibration(maintenance_data["due_today"]) +
        _exclude_calibration(maintenance_data["due_within_7days"])
    )
    _filtered_overdue = _exclude_calibration(maintenance_data["overdue"])
    _filtered_due_today = _exclude_calibration(maintenance_data["due_today"])
    maintenance_summary = {
        "overdue_count": len(_filtered_overdue),
        "due_today_count": len(_filtered_due_today),
        "due_7days_count": len(_exclude_calibration(maintenance_data["due_within_7days"])),
    }

    # 统一把 due_date 转成字符串，方便模板比较
    from datetime import date as _date
    for item in maintenance_reminders:
        dd = item.get("due_date")
        if dd is None:
            item["due_date_str"] = ""
        elif isinstance(dd, str):
            item["due_date_str"] = dd[:10]
        elif hasattr(dd, "isoformat"):
            item["due_date_str"] = dd.isoformat()[:10]
        else:
            item["due_date_str"] = str(dd)[:10]

    doc_reminders = build_calibration_reminders(calibration_rows)

    # 将维护计划中的校准记录转换为校准提醒格式并合并
    for row in maintenance_calibration_rows:
        reminder = _build_calibration_reminder_from_maintenance_plan(row)
        if reminder:
            doc_reminders.append(reminder)

    # 按到期日期排序
    doc_reminders.sort(key=lambda r: r["due_date"])
    all_reminders = doc_reminders

    # 状态筛选
    if filter_severity and filter_severity != "all":
        calibration_reminders = [r for r in all_reminders if r["severity"] == filter_severity]
    else:
        calibration_reminders = all_reminders

    # 统计各状态数量（用于筛选 tab 上的计数）
    severity_counts = {
        "danger": sum(1 for r in all_reminders if r["severity"] == "danger"),
        "warning": sum(1 for r in all_reminders if r["severity"] == "warning"),
        "info": sum(1 for r in all_reminders if r["severity"] == "info"),
        "all": len(all_reminders),
    }

    return render_template(
        "reminders.html",
        calibration_reminders=calibration_reminders,
        pending_approvals=pending_approvals,
        borrowed_total=borrowed_total,
        filter_severity=filter_severity or "all",
        filter_device=filter_device,
        severity_counts=severity_counts,
        # 维护提醒（新增，与铃铛计数对齐）
        maintenance_reminders=maintenance_reminders,
        maintenance_summary=maintenance_summary,
        today_str=__import__('datetime').date.today().isoformat(),
    )


@dashboard_bp.route("/user_stories")
@login_required
def user_stories():
    """用户故事与角色视角"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT status, COUNT(*) AS total FROM devices WHERE is_deleted IS NULL OR is_deleted = 0 GROUP BY status"
    )
    device_status_counts = {row["status"]: row["total"] for row in cur.fetchall()}
    cur.execute("SELECT COUNT(*) AS total FROM documents WHERE is_deleted = 0 AND status = 'pending'")
    pending_documents = cur.fetchone()["total"]
    cur.execute("SELECT COUNT(*) AS total FROM approval_requests WHERE status = 'pending'")
    pending_approvals = cur.fetchone()["total"]
    # 检查借阅功能是否开启
    borrowing_enabled_val = get_system_setting("borrowing_enabled")
    borrowing_enabled_dash = (borrowing_enabled_val == "true") if borrowing_enabled_val else True
    if borrowing_enabled_dash:
        cur.execute("SELECT COUNT(*) AS total FROM borrow_records WHERE status = 'borrowed'")
        borrowed_total = cur.fetchone()["total"]
        cur.execute(
            "SELECT b.*, d.doc_name, d.version, d.doc_type, dev.device_code, dev.device_name FROM borrow_records b JOIN documents d ON d.id = b.doc_id JOIN devices dev ON dev.id = d.device_id ORDER BY b.borrow_date DESC LIMIT 8"
        )
        recent_borrows = cur.fetchall()
    else:
        borrowed_total = 0
        recent_borrows = []
    cur.execute(
        "SELECT d.*, dev.device_code, dev.device_name FROM documents d JOIN devices dev ON dev.id = d.device_id WHERE d.is_deleted = 0 ORDER BY d.upload_time DESC LIMIT 8"
    )
    recent_documents = cur.fetchall()
    cur.execute(
        "SELECT d.*, dev.device_code, dev.device_name FROM documents d JOIN devices dev ON dev.id = d.device_id WHERE d.doc_type = 'calibration' AND d.is_deleted = 0 ORDER BY d.upload_time DESC"
    )
    calibration_rows = cur.fetchall()
    conn.close()
    calibration_reminders = build_calibration_reminders(calibration_rows)
    device_total = sum(device_status_counts.values())
    validation_links = [
        {"label": "文档检索", "endpoint": "documents.document_search"},
        {"label": "审批待办", "endpoint": "approvals.approvals"},
    ]
    archive_links = [
        {"label": "文档检索", "endpoint": "documents.document_search"},
    ]
    if borrowing_enabled_dash:
        archive_links.insert(0, {"label": "借阅记录", "endpoint": "borrowing.borrow_list"})
    if recent_documents:
        validation_links.insert(
            1, {"label": "版本历史", "endpoint": "documents.document_history", "doc_id": recent_documents[0]["id"]}
        )
        archive_links.append(
            {"label": "设备详情", "endpoint": "devices.device_detail", "device_id": recent_documents[0]["device_id"]}
        )
    role_cards = [
        {
            "role": "QA经理",
            "role_key": "qa_manager",
            "card_class": "qa",
            "avatar_icon": '<i data-lucide="shield-check"></i>',
            "summary": f"待审批 {pending_approvals} 项，文档待处理 {pending_documents} 份",
            "card_features": ["审批待办", "审计日志", "合规状态总览"],
            "links": [
                {"label": "审批待办", "endpoint": "approvals.approvals", "icon": "check-square"},
                {"label": "审计日志", "endpoint": "dashboard.audit_log", "icon": "scroll-text"},
                {"label": "设备看板", "endpoint": "dashboard.dashboard", "icon": "layout-grid"},
            ],
        },
        {
            "role": "设备工程师",
            "role_key": "equipment_engineer",
            "card_class": "engineer",
            "avatar_icon": '<i data-lucide="wrench"></i>',
            "summary": f"设备检索与详情页已可用，当前设备数 {device_total}",
            "card_features": ["设备详情", "文档检索", "设备校准"],
            "links": [
                {"label": "设备列表", "endpoint": "dashboard.dashboard", "icon": "server"},
                {"label": "文档检索", "endpoint": "documents.document_search", "icon": "search"},
                {"label": "新增设备", "endpoint": "dashboard.add_device", "icon": "plus-circle"},
            ],
        },
        {
            "role": "验证工程师",
            "role_key": "validation_engineer",
            "card_class": "validation",
            "avatar_icon": '<i data-lucide="file-check"></i>',
            "summary": f"最近版本记录 {len(recent_documents)} 条，可查看版本历史",
            "card_features": ["版本历史", "文档审批", "历史追溯"],
            "links": validation_links + [{"label": "设备看板", "endpoint": "dashboard.dashboard", "icon": "layout-grid"}],
        },
        {
            "role": "档案管理员",
            "role_key": "archivist",
            "card_class": "archive",
            "avatar_icon": '<i data-lucide="archive"></i>',
            "summary": f"当前借阅中 {borrowed_total} 份，可追踪归还状态" if borrowing_enabled_dash else "文档归档与管理",
            "card_features": ["借阅记录", "归还确认", "文档归档"] if borrowing_enabled_dash else ["文档归档", "文档检索"],
            "links": archive_links,
        },
        {
            "role": "生产主管",
            "role_key": "production_supervisor",
            "card_class": "production",
            "avatar_icon": '<i data-lucide="clipboard-list"></i>',
            "summary": "设备状态分布已在看板中展示，可快速了解运行与停用情况",
            "card_features": ["设备看板", "状态筛选", "设备详情"],
            "links": [
                {"label": "设备看板", "endpoint": "dashboard.dashboard", "icon": "layout-grid"},
                {"label": "提醒中心", "endpoint": "dashboard.reminders", "icon": "bell"},
            ],
        },
        {
            "role": "计量工程师",
            "role_key": "metrology_engineer",
            "card_class": "metrology",
            "avatar_icon": '<i data-lucide="ruler"></i>',
            "summary": f"校准提醒 {len(calibration_reminders)} 条，覆盖近期需关注文档",
            "card_features": ["校准提醒", "校准记录", "到期关注"],
            "links": [
                {"label": "提醒中心", "endpoint": "dashboard.reminders", "icon": "bell"},
                {"label": "文档检索", "endpoint": "documents.document_search", "icon": "search"},
                {"label": "设备看板", "endpoint": "dashboard.dashboard", "icon": "layout-grid"},
            ],
        },
    ]
    return render_template(
        "user_stories.html",
        role_cards=role_cards,
        role_labels=ROLE_LABELS,
        device_status_counts=device_status_counts,
        pending_documents=pending_documents,
        pending_approvals=pending_approvals,
        borrowed_total=borrowed_total,
        recent_documents=recent_documents,
        recent_borrows=recent_borrows,
        calibration_reminders=calibration_reminders,
        doc_status_labels=DOC_STATUS_LABELS,
        device_total=device_total,
    )


@dashboard_bp.route("/api/dashboard/due-maintenance")
@login_required
def api_due_maintenance():
    """获取到期维护看板数据（API）"""
    maintenance_type = request.args.get("type", "").strip()
    days = request.args.get("days", 7, type=int)
    for_login_popup = request.args.get("for_login_popup", 0, type=int)

    conn = get_db()
    reminders = build_due_maintenance_reminders(conn, days=days)
    conn.close()

    # 按类型筛选
    if maintenance_type:
        reminders["due_today"] = [r for r in reminders["due_today"] if r.get("maintenance_type") == maintenance_type]
        reminders["due_within_7days"] = [r for r in reminders["due_within_7days"] if r.get("maintenance_type") == maintenance_type]
        reminders["overdue"] = [r for r in reminders["overdue"] if r.get("maintenance_type") == maintenance_type]
        reminders["summary"] = {
            "due_today_count": len(reminders["due_today"]),
            "due_7days_count": len(reminders["due_within_7days"]),
            "overdue_count": len(reminders["overdue"]),
        }

    return jsonify({
        "success": True,
        "count": reminders["summary"]["due_today_count"] + reminders["summary"]["due_7days_count"] + reminders["summary"]["overdue_count"],
        "reminders": reminders["due_today"] + reminders["due_within_7days"] + reminders["overdue"],
        "for_login_popup": for_login_popup,
        "summary": reminders["summary"],
        "overdue": reminders["overdue"],
        "due_today": reminders["due_today"],
        "due_within_7days": reminders["due_within_7days"],
    })


@dashboard_bp.route("/api/dashboard/calibration-overdue-count")
@login_required
def api_calibration_overdue_count():
    """获取校准文档逾期数量（API，供顶部铃铛使用）"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT d.*, dev.device_code, dev.device_name "
        "FROM documents d JOIN devices dev ON dev.id = d.device_id "
        "WHERE d.doc_type = 'calibration' AND d.is_deleted = 0 "
        "ORDER BY d.upload_time DESC"
    )
    calibration_rows = cur.fetchall()

    # 同时纳入维护计划中的校准记录
    cur.execute(
        "SELECT mp.*, dev.device_code, dev.device_name "
        "FROM maintenance_plan mp "
        "JOIN devices dev ON dev.id = mp.device_id "
        "WHERE mp.maintenance_type = 'calibration' AND mp.is_active = 1 AND mp.is_closed = 0 "
        "ORDER BY mp.next_due_date ASC"
    )
    maintenance_calibration_rows = cur.fetchall()
    conn.close()

    all_reminders = build_calibration_reminders(calibration_rows)
    for row in maintenance_calibration_rows:
        reminder = _build_calibration_reminder_from_maintenance_plan(row)
        if reminder:
            all_reminders.append(reminder)

    overdue_count = sum(1 for r in all_reminders if r["severity"] == "danger")
    return jsonify({"overdue_count": overdue_count})

@dashboard_bp.route("/maintenance/all")
@login_required
def maintenance_all():
    """全局维护计划列表页（所有设备）"""
    conn = get_db()
    cur = conn.cursor()

    # 按紧迫度排序：逾期 > 今日到期 > 7日内 > 其余
    cur.execute(
        """SELECT mp.*, d.device_code, d.device_name, d.model
           FROM maintenance_plan mp
           JOIN devices d ON d.id = mp.device_id
           WHERE mp.is_active = 1
           AND (d.is_deleted IS NULL OR d.is_deleted = 0)
           ORDER BY mp.next_due_date ASC"""
    )
    rows = cur.fetchall()
    conn.close()

    return render_template(
        "maintenance_all.html",
        plans=rows,
    )


@dashboard_bp.route("/audit_log")
@admin_required
def audit_log():
    """审计日志"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM audit_logs ORDER BY log_time DESC LIMIT 500")
    rows = cur.fetchall()
    conn.close()
    return render_template("audit_log.html", rows=rows)


@dashboard_bp.route("/add_device", methods=["GET", "POST"])
@login_required
def add_device():
    """新增设备"""
    if request.method == "POST":
        device_code = request.form.get("device_code", "").strip()
        device_name = request.form.get("device_name", "").strip()
        model = request.form.get("model", "").strip()
        location = request.form.get("location", "").strip()
        if not device_code or not device_name:
            flash("设备编码和名称为必填项。", "warning")
            return redirect(url_for("dashboard.add_device"))
        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO devices (device_code, device_name, model, location) VALUES (%s, %s, %s, %s)",
                (device_code, device_name, model, location),
            )
            conn.commit()
            device_id = cur.lastrowid
            log_action(
                current_user.username, "create_device", "device", device_id,
                f"新增设备 {device_code}",
            )
            flash("设备已创建。", "success")
            return redirect(url_for("auth.index"))
        except Exception:
            conn.rollback()
            flash("设备编码已存在或保存失败。", "danger")
        finally:
            conn.close()
    return render_template("add_device.html")
