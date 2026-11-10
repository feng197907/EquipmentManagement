# 备件库存管理 Blueprint
from datetime import datetime

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from database import DB_TYPE, get_db
from models.spare_part import (
    SPARE_PART_CATEGORIES,
    SPARE_PART_CATEGORY_LABELS,
    SparePart,
    SparePartAlert,
    SparePartConsumption,
    SparePartInbound,
)
from utils.audit import log_action
from utils.decorators import admin_required, permission_required
from utils.excel_export import export_to_excel

spare_part_bp = Blueprint("spare_part", __name__, url_prefix="/spare-parts")


@spare_part_bp.route("/")
@login_required
def spare_part_list():
    """备件库存管理主页"""
    category = request.args.get("category", "").strip()
    search = request.args.get("q", "").strip()
    stock_filter = request.args.get("stock", "").strip()
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    per_page = 20

    parts, pagination = SparePart.get_all(
        page=page, per_page=per_page,
        category=category if category else None,
        search=search if search else None,
        stock_filter=stock_filter if stock_filter else None,
    )

    # 获取未解决预警数
    try:
        alert_count = SparePartAlert.get_unresolved_count()
    except Exception:
        alert_count = 0

    return render_template(
        "spare_parts.html",
        parts=parts,
        pagination=pagination,
        categories=SPARE_PART_CATEGORIES,
        category_labels=SPARE_PART_CATEGORY_LABELS,
        selected_category=category,
        search=search,
        stock_filter=stock_filter,
        alert_count=alert_count,
    )


@spare_part_bp.route("/export")
@login_required
def spare_part_export():
    """导出备件列表为 Excel（与设备列表导出风格一致）"""
    category = request.args.get("category", "").strip()
    search = request.args.get("q", "").strip()
    stock_filter = request.args.get("stock", "").strip()

    conn = get_db()
    cur = conn.cursor()

    conditions = ["sp.is_active = 1"]
    params = []
    if category:
        conditions.append("sp.category = %s")
        params.append(category)
    if search:
        conditions.append("(sp.code LIKE %s OR sp.name LIKE %s OR sp.specification LIKE %s OR sp.brand LIKE %s)")
        like = f"%{search}%"
        params.extend([like, like, like, like])
    if stock_filter == "low":
        conditions.append("sp.current_stock > 0 AND sp.current_stock <= sp.safety_stock_min")
    elif stock_filter == "out":
        conditions.append("sp.current_stock <= 0")
    elif stock_filter == "normal":
        conditions.append("sp.current_stock > sp.safety_stock_min")
    elif stock_filter == "over":
        conditions.append("sp.safety_stock_max > 0 AND sp.current_stock >= sp.safety_stock_max")

    where = "WHERE " + " AND ".join(conditions)
    cur.execute(
        f"""SELECT sp.code, sp.name, sp.category, sp.specification, sp.unit,
                   sp.brand, sp.current_stock, sp.safety_stock_min, sp.safety_stock_max,
                   sp.weighted_avg_price, sp.supplier_name, sp.supplier_contact,
                   sp.supplier_phone, sp.remark, sp.created_at
            FROM spare_parts sp
            {where}
            ORDER BY sp.created_at DESC, sp.id DESC""",
        params,
    )
    rows = cur.fetchall()
    conn.close()

    headers = ["序号", "备件编码", "备件名称", "分类", "规格型号", "单位", "品牌",
               "库存量", "安全库存下限", "安全库存上限", "加权均价(元)",
               "供应商", "供应商联系人", "供应商电话", "备注", "创建时间"]
    export_rows = [
        [
            i,
            row["code"],
            row["name"],
            SPARE_PART_CATEGORY_LABELS.get(row["category"], row["category"]),
            row["specification"],
            row["unit"],
            row["brand"],
            row["current_stock"],
            row["safety_stock_min"],
            row["safety_stock_max"],
            round(float(row["weighted_avg_price"] or 0), 2),
            row["supplier_name"],
            row["supplier_contact"],
            row["supplier_phone"],
            row["remark"],
            row["created_at"],
        ]
        for i, row in enumerate(rows, 1)
    ]

    return export_to_excel(
        filename_prefix="备件列表",
        sheet_title="备件列表",
        headers=headers,
        rows=export_rows,
    )


@spare_part_bp.route("/stats")
@login_required
def spare_part_stats():
    """备件成本统计看板"""
    conn = get_db()
    cur = conn.cursor()

    # 总备件种类
    cur.execute("SELECT COUNT(*) as cnt FROM spare_parts WHERE is_active = 1")
    total_parts = cur.fetchone()["cnt"]

    # 低库存备件数
    cur.execute("SELECT COUNT(*) as cnt FROM spare_parts WHERE is_active = 1 AND current_stock > 0 AND current_stock <= safety_stock_min")
    low_stock_count = cur.fetchone()["cnt"]

    # 缺货备件数
    cur.execute("SELECT COUNT(*) as cnt FROM spare_parts WHERE is_active = 1 AND current_stock <= 0")
    out_of_stock_count = cur.fetchone()["cnt"]

    # 总库存金额
    cur.execute("SELECT SUM(current_stock * weighted_avg_price) as total_value FROM spare_parts WHERE is_active = 1")
    row = cur.fetchone()
    total_stock_value = round(float(row["total_value"] or 0), 2)

    # 总消耗金额（本月）
    if DB_TYPE == "sqlite":
        cur.execute(
            "SELECT SUM(sc.quantity * sc.unit_price) as total "
            "FROM spare_part_consumptions sc "
            "WHERE strftime('%Y-%m', sc.consumed_at) = strftime('%Y-%m', 'now')"
        )
    else:
        cur.execute(
            "SELECT SUM(sc.quantity * sc.unit_price) as total "
            "FROM spare_part_consumptions sc "
            "WHERE DATE_FORMAT(sc.consumed_at, '%Y-%m') = DATE_FORMAT(NOW(), '%Y-%m')"
        )
    row = cur.fetchone()
    month_consumption = round(float(row["total"] or 0), 2)

    # 按设备统计备件消耗（TOP10）
    cur.execute("""
        SELECT COALESCE(d_mr.device_code, d_rr.device_code) as device_code,
               COALESCE(d_mr.device_name, d_rr.device_name) as device_name,
               SUM(sc.quantity * sc.unit_price) as total_cost,
               COUNT(DISTINCT sc.id) as consumption_count
        FROM spare_part_consumptions sc
        LEFT JOIN maintenance_record mr ON mr.id = sc.maintenance_record_id
        LEFT JOIN devices d_mr ON d_mr.id = mr.device_id
        LEFT JOIN repair_record rr ON rr.id = sc.maintenance_record_id
        LEFT JOIN devices d_rr ON d_rr.id = rr.device_id
        WHERE sc.maintenance_record_id IS NOT NULL
          AND (d_mr.id IS NOT NULL OR d_rr.id IS NOT NULL)
        GROUP BY COALESCE(d_mr.id, d_rr.id),
                 COALESCE(d_mr.device_code, d_rr.device_code),
                 COALESCE(d_mr.device_name, d_rr.device_name)
        ORDER BY total_cost DESC
        LIMIT 10
    """)
    device_stats = cur.fetchall()

    # 按备件统计消耗（TOP10）
    cur.execute("""
        SELECT sp.code, sp.name, sp.specification, sp.unit,
               SUM(sc.quantity) as total_qty,
               SUM(sc.quantity * sc.unit_price) as total_cost
        FROM spare_part_consumptions sc
        JOIN spare_parts sp ON sp.id = sc.spare_part_id
        GROUP BY sp.id, sp.code, sp.name, sp.specification, sp.unit
        ORDER BY total_cost DESC
        LIMIT 10
    """)
    part_stats = cur.fetchall()

    # 按供应商统计采购金额
    cur.execute("""
        SELECT sp.supplier_name,
               SUM(si.quantity * si.unit_price) as total_amount,
               COUNT(DISTINCT si.id) as inbound_count
        FROM spare_part_inbounds si
        JOIN spare_parts sp ON sp.id = si.spare_part_id
        WHERE sp.supplier_name IS NOT NULL AND sp.supplier_name != ''
        GROUP BY sp.supplier_name
        ORDER BY total_amount DESC
        LIMIT 10
    """)
    supplier_stats = cur.fetchall()

    # 按维修类型统计备件消耗对比（含维修记录）
    cur.execute("""
        SELECT COALESCE(mr.maintenance_type, 'repair') as maintenance_type,
               COUNT(DISTINCT sc.id) as count,
               SUM(sc.quantity * sc.unit_price) as total_cost
        FROM spare_part_consumptions sc
        LEFT JOIN maintenance_record mr ON mr.id = sc.maintenance_record_id
        LEFT JOIN repair_record rr ON rr.id = sc.maintenance_record_id
        WHERE sc.maintenance_record_id IS NOT NULL
          AND (mr.id IS NOT NULL OR rr.id IS NOT NULL)
        GROUP BY COALESCE(mr.maintenance_type, 'repair')
    """)
    type_stats = cur.fetchall()

    conn.close()

    return render_template(
        "spare_part_stats.html",
        total_parts=total_parts,
        low_stock_count=low_stock_count,
        out_of_stock_count=out_of_stock_count,
        total_stock_value=total_stock_value,
        month_consumption=month_consumption,
        device_stats=device_stats,
        part_stats=part_stats,
        supplier_stats=supplier_stats,
        type_stats=type_stats,
    )


@spare_part_bp.route("/inbounds")
@login_required
def inbound_list():
    """入库记录列表"""
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    per_page = 20

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as total FROM spare_part_inbounds")
    total = cur.fetchone()["total"]
    offset = (page - 1) * per_page
    cur.execute(
        """SELECT si.*, sp.code, sp.name, sp.specification, sp.unit
           FROM spare_part_inbounds si
           JOIN spare_parts sp ON sp.id = si.spare_part_id
           ORDER BY si.inbound_date DESC, si.id DESC
           LIMIT %s OFFSET %s""",
        (per_page, offset),
    )
    rows = cur.fetchall()
    conn.close()

    pagination = {
        "page": page, "per_page": per_page, "total": total,
        "pages": (total + per_page - 1) // per_page,
    }

    return render_template(
        "spare_part_inbounds.html",
        inbounds=rows,
        pagination=pagination,
    )


@spare_part_bp.route("/inbounds/export")
@login_required
def inbound_export():
    """导出入库记录为 Excel（与设备列表导出风格一致）"""
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()

    conn = get_db()
    cur = conn.cursor()

    conditions = []
    params = []
    if date_from:
        conditions.append("si.inbound_date >= %s")
        params.append(date_from)
    if date_to:
        conditions.append("si.inbound_date <= %s")
        params.append(date_to)

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    cur.execute(
        f"""SELECT si.id, sp.code, sp.name, sp.specification, sp.unit,
                   si.quantity, si.unit_price,
                   (si.quantity * si.unit_price) AS total_amount,
                   si.batch_no, si.inbound_date, si.created_by, si.created_at, si.remark
            FROM spare_part_inbounds si
            JOIN spare_parts sp ON sp.id = si.spare_part_id
            {where_clause}
            ORDER BY si.inbound_date DESC, si.id DESC""",
        params,
    )
    rows = cur.fetchall()
    conn.close()

    headers = ["序号", "备件编码", "备件名称", "规格型号", "单位",
               "入库数量", "单价(元)", "金额(元)", "批次号",
               "入库日期", "操作人", "录入时间", "备注"]
    export_rows = [
        [
            i,
            row["code"],
            row["name"],
            row["specification"],
            row["unit"],
            row["quantity"],
            round(float(row["unit_price"] or 0), 2),
            round(float(row["total_amount"] or 0), 2),
            row["batch_no"],
            row["inbound_date"],
            row["created_by"],
            row["created_at"],
            row["remark"],
        ]
        for i, row in enumerate(rows, 1)
    ]

    return export_to_excel(
        filename_prefix="备件入库记录",
        sheet_title="备件入库记录",
        headers=headers,
        rows=export_rows,
    )


@spare_part_bp.route("/consumptions/export")
@login_required
def consumption_export():
    """导出消耗记录为 Excel（与设备列表导出风格一致）"""
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()

    conn = get_db()
    cur = conn.cursor()

    conditions = []
    params = []
    if date_from:
        conditions.append("sc.consumed_at >= %s")
        params.append(date_from)
    if date_to:
        conditions.append("sc.consumed_at <= %s")
        params.append(date_to + " 23:59:59")

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    cur.execute(
        f"""SELECT sc.id, sp.code, sp.name, sp.specification, sp.unit,
                   sc.quantity, sc.unit_price,
                   (sc.quantity * sc.unit_price) AS total_amount,
                   COALESCE(d_mr.device_code, d_rr.device_code) as device_code,
                   COALESCE(d_mr.device_name, d_rr.device_name) as device_name,
                   sc.maintenance_record_id,
                   sc.consumed_by, sc.consumed_at, sc.remark
            FROM spare_part_consumptions sc
            LEFT JOIN spare_parts sp ON sp.id = sc.spare_part_id
            LEFT JOIN maintenance_record mr ON mr.id = sc.maintenance_record_id
            LEFT JOIN devices d_mr ON d_mr.id = mr.device_id
            LEFT JOIN repair_record rr ON rr.id = sc.maintenance_record_id
            LEFT JOIN devices d_rr ON d_rr.id = rr.device_id
            {where_clause}
            ORDER BY sc.consumed_at DESC, sc.id DESC""",
        params,
    )
    rows = cur.fetchall()
    conn.close()

    headers = ["序号", "备件编码", "备件名称", "规格型号", "单位",
               "消耗数量", "单价(元)", "金额(元)",
               "关联设备编码", "关联设备名称", "维修记录ID",
               "消耗人", "消耗时间", "备注"]
    export_rows = [
        [
            i,
            row["code"],
            row["name"],
            row["specification"],
            row["unit"],
            row["quantity"],
            round(float(row["unit_price"] or 0), 2),
            round(float(row["total_amount"] or 0), 2),
            row["device_code"],
            row["device_name"],
            row["maintenance_record_id"],
            row["consumed_by"],
            row["consumed_at"],
            row["remark"],
        ]
        for i, row in enumerate(rows, 1)
    ]

    return export_to_excel(
        filename_prefix="备件消耗记录",
        sheet_title="备件消耗记录",
        headers=headers,
        rows=export_rows,
    )


@spare_part_bp.route("/consumptions")
@login_required
def consumption_list():
    """消耗记录列表"""
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    per_page = 20

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as total FROM spare_part_consumptions")
    total = cur.fetchone()["total"]
    offset = (page - 1) * per_page
    cur.execute(
        """SELECT sc.*, sp.code, sp.name, sp.specification, sp.unit,
                  COALESCE(d_mr.device_code, d_rr.device_code) as device_code,
                  COALESCE(d_mr.device_name, d_rr.device_name) as device_name,
                  COALESCE(d_mr.id, d_rr.id) as device_id
           FROM spare_part_consumptions sc
           LEFT JOIN spare_parts sp ON sp.id = sc.spare_part_id
           LEFT JOIN maintenance_record mr ON mr.id = sc.maintenance_record_id
           LEFT JOIN devices d_mr ON d_mr.id = mr.device_id
           LEFT JOIN repair_record rr ON rr.id = sc.maintenance_record_id
           LEFT JOIN devices d_rr ON d_rr.id = rr.device_id
           ORDER BY sc.consumed_at DESC, sc.id DESC
           LIMIT %s OFFSET %s""",
        (per_page, offset),
    )
    rows = cur.fetchall()
    conn.close()

    pagination = {
        "page": page, "per_page": per_page, "total": total,
        "pages": (total + per_page - 1) // per_page,
    }

    return render_template(
        "spare_part_consumptions.html",
        consumptions=rows,
        pagination=pagination,
    )


@spare_part_bp.route("/alerts")
@login_required
def alert_list():
    """预警记录列表"""
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    per_page = 20

    conn = get_db()
    cur = conn.cursor()
    # 只查未解决的
    cur.execute("SELECT COUNT(*) as total FROM spare_part_alerts WHERE is_resolved = 0")
    total = cur.fetchone()["total"]
    offset = (page - 1) * per_page
    cur.execute(
        """SELECT sa.*, sp.code, sp.name, sp.specification, sp.current_stock as latest_stock
           FROM spare_part_alerts sa
           JOIN spare_parts sp ON sp.id = sa.spare_part_id
           WHERE sa.is_resolved = 0
           ORDER BY sa.created_at DESC
           LIMIT %s OFFSET %s""",
        (per_page, offset),
    )
    rows = cur.fetchall()
    conn.close()

    pagination = {
        "page": page, "per_page": per_page, "total": total,
        "pages": (total + per_page - 1) // per_page,
    }

    return render_template(
        "spare_part_alerts.html",
        alerts=rows,
        pagination=pagination,
        alert_types=SparePartAlert.ALERT_TYPES,
    )


# ============================================================
# API 路由 - 备件 CRUD
# ============================================================


@spare_part_bp.route("/api/spare-parts", methods=["GET"])
@login_required
def api_get_spare_parts():
    """获取备件列表（供下拉选择用）"""
    rows = SparePart.get_active_list()
    result = []
    for row in rows:
        result.append({
            "id": row["id"],
            "code": row["code"],
            "name": row["name"],
            "specification": row.get("specification", ""),
            "unit": row.get("unit", ""),
            "current_stock": row["current_stock"],
            "weighted_avg_price": float(row["weighted_avg_price"] or 0),
            "display": f"{row['code']} {row['name']}（库存:{row['current_stock']}{row.get('unit','')}）",
        })
    return jsonify({"parts": result})


@spare_part_bp.route("/api/spare-parts", methods=["POST"])
@permission_required("device_maintenance")
def api_create_spare_part():
    """创建新备件"""
    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    category = data.get("category", "other").strip()

    if not name:
        return jsonify({"error": "备件名称为必填项"}), 400
    if category not in dict(SPARE_PART_CATEGORIES):
        return jsonify({"error": "无效的备件分类"}), 400

    part = SparePart(
        name=name,
        category=category,
        specification=data.get("specification", "").strip(),
        unit=data.get("unit", "个").strip() or "个",
        brand=data.get("brand", "").strip(),
        safety_stock_min=int(data.get("safety_stock_min", 0) or 0),
        safety_stock_max=int(data.get("safety_stock_max", 9999) or 9999),
        supplier_name=data.get("supplier_name", "").strip(),
        supplier_contact=data.get("supplier_contact", "").strip(),
        supplier_phone=data.get("supplier_phone", "").strip(),
        remark=data.get("remark", "").strip(),
    )
    part.save()

    log_action(
        current_user.username, "create_spare_part", "spare_parts", part.id,
        f"创建备件：{part.code} {part.name}",
    )

    return jsonify({
        "id": part.id,
        "code": part.code,
        "name": part.name,
        "message": "备件已创建",
    })


@spare_part_bp.route("/api/spare-parts/<int:part_id>", methods=["PUT"])
@permission_required("device_maintenance")
def api_update_spare_part(part_id):
    """更新备件信息"""
    part = SparePart.get_by_id(part_id)
    if part is None:
        return jsonify({"error": "备件不存在"}), 404

    data = request.get_json(silent=True) or {}

    old_name = part.name
    if "name" in data:
        name = data["name"].strip()
        if not name:
            return jsonify({"error": "备件名称为必填项"}), 400
        part.name = name
    if "category" in data:
        cat = data["category"].strip()
        if cat not in dict(SPARE_PART_CATEGORIES):
            return jsonify({"error": "无效的备件分类"}), 400
        part.category = cat
    if "specification" in data:
        part.specification = data["specification"].strip()
    if "unit" in data:
        part.unit = data["unit"].strip() or "个"
    if "brand" in data:
        part.brand = data["brand"].strip()
    if "safety_stock_min" in data:
        part.safety_stock_min = int(data["safety_stock_min"] or 0)
    if "safety_stock_max" in data:
        part.safety_stock_max = int(data["safety_stock_max"] or 9999)
    if "supplier_name" in data:
        part.supplier_name = data["supplier_name"].strip()
    if "supplier_contact" in data:
        part.supplier_contact = data["supplier_contact"].strip()
    if "supplier_phone" in data:
        part.supplier_phone = data["supplier_phone"].strip()
    if "remark" in data:
        part.remark = data["remark"].strip()

    part.save()

    log_action(
        current_user.username, "update_spare_part", "spare_parts", part_id,
        f"更新备件：{part.code} {old_name}",
    )

    return jsonify({"id": part.id, "message": "备件已更新"})


@spare_part_bp.route("/api/spare-parts/<int:part_id>/toggle", methods=["POST"])
@permission_required("device_maintenance")
def api_toggle_spare_part(part_id):
    """启用/停用备件"""
    part = SparePart.get_by_id(part_id)
    if part is None:
        return jsonify({"error": "备件不存在"}), 404

    part.is_active = 0 if part.is_active else 1
    part.save()

    status = "启用" if part.is_active else "停用"
    log_action(
        current_user.username, f"{'enable' if part.is_active else 'disable'}_spare_part",
        "spare_parts", part_id,
        f"{status}备件：{part.code} {part.name}",
    )

    return jsonify({"message": f"备件已{status}", "is_active": bool(part.is_active)})


# ============================================================
# API 路由 - 入库
# ============================================================


@spare_part_bp.route("/api/spare-parts/<int:part_id>/inbound", methods=["POST"])
@permission_required("device_maintenance")
def api_inbound(part_id):
    """备件入库"""
    part = SparePart.get_by_id(part_id)
    if part is None:
        return jsonify({"error": "备件不存在"}), 404

    data = request.get_json(silent=True) or {}
    try:
        quantity = int(data.get("quantity", 0))
    except (ValueError, TypeError):
        return jsonify({"error": "入库数量必须为有效数字"}), 400
    if quantity <= 0:
        return jsonify({"error": "入库数量必须大于0"}), 400

    try:
        unit_price = float(data.get("unit_price", 0))
    except (ValueError, TypeError):
        return jsonify({"error": "单价必须为有效数字"}), 400

    batch_no = data.get("batch_no", "").strip()
    inbound_date = data.get("inbound_date", datetime.now().strftime("%Y-%m-%d")).strip()

    # 创建入库记录
    inbound = SparePartInbound(
        spare_part_id=part_id,
        quantity=quantity,
        unit_price=unit_price,
        batch_no=batch_no if batch_no else None,
        inbound_date=inbound_date,
        remark=data.get("remark", "").strip(),
        created_by=current_user.username,
    )
    inbound.save()

    # 更新库存
    part.update_stock(delta=quantity, unit_price=unit_price if unit_price > 0 else None)

    # 检查预警：入库后如果不再缺货，标记低库存预警为已解决
    if part.current_stock > part.safety_stock_min:
        _resolve_stock_alerts(part_id, "low_stock")
    if part.safety_stock_max > 0 and part.current_stock < part.safety_stock_max:
        _resolve_stock_alerts(part_id, "over_stock")

    log_action(
        current_user.username, "inbound_spare_part", "spare_part_inbounds", inbound.id,
        f"备件入库：{part.code} {part.name}，数量 {quantity}，单价 {unit_price}",
    )

    return jsonify({
        "message": "入库成功",
        "current_stock": part.current_stock,
        "weighted_avg_price": part.weighted_avg_price,
    })


# ============================================================
# API 路由 - 消耗（用于维修记录关联）
# ============================================================


@spare_part_bp.route("/api/consumptions", methods=["POST"])
@permission_required("device_maintenance")
def api_consume():
    """记录备件消耗（维修时使用）"""
    data = request.get_json(silent=True) or {}
    part_id = data.get("spare_part_id")
    maintenance_record_id = data.get("maintenance_record_id")

    if not part_id:
        return jsonify({"error": "请选择备件"}), 400

    try:
        quantity = int(data.get("quantity", 0))
    except (ValueError, TypeError):
        return jsonify({"error": "消耗数量必须为有效数字"}), 400
    if quantity <= 0:
        return jsonify({"error": "消耗数量必须大于0"}), 400

    part = SparePart.get_by_id(part_id)
    if part is None:
        return jsonify({"error": "备件不存在"}), 404

    if part.current_stock < quantity:
        return jsonify({"error": f"库存不足，当前库存 {part.current_stock}{part.unit}"}), 400

    # 扣减库存
    consumption_price = float(part.weighted_avg_price or 0)
    part.update_stock(delta=-quantity)

    # 创建消耗记录
    consumption = SparePartConsumption(
        spare_part_id=part_id,
        maintenance_record_id=maintenance_record_id,
        quantity=quantity,
        unit_price=consumption_price,
        consumed_by=current_user.username,
        remark=data.get("remark", "").strip(),
    )
    consumption.save()

    # 检查预警
    _check_and_create_alerts(part)

    log_action(
        current_user.username, "consume_spare_part", "spare_part_consumptions", consumption.id,
        f"消耗备件：{part.code} {part.name}，数量 {quantity}，关联维修记录 {maintenance_record_id}",
    )

    return jsonify({
        "message": "消耗记录已保存",
        "current_stock": part.current_stock,
        "consumption_id": consumption.id,
    })


@spare_part_bp.route("/api/consumptions/batch", methods=["POST"])
@permission_required("device_maintenance")
def api_batch_consume():
    """批量记录备件消耗（维修记录提交后调用）"""
    data = request.get_json(silent=True) or {}
    maintenance_record_id = data.get("maintenance_record_id")
    items = data.get("items", [])

    if not items:
        return jsonify({"message": "无备件消耗"})

    results = []
    errors = []

    for item in items:
        try:
            part_id = item.get("spare_part_id")
            quantity = int(item.get("quantity", 0))
            if not part_id or quantity <= 0:
                errors.append(f"无效的消耗项: {item}")
                continue

            part = SparePart.get_by_id(part_id)
            if part is None:
                errors.append(f"备件不存在 (ID:{part_id})")
                continue

            if part.current_stock < quantity:
                errors.append(f"{part.name} 库存不足")
                continue

            consumption_price = float(part.weighted_avg_price or 0)
            part.update_stock(delta=-quantity)

            consumption = SparePartConsumption(
                spare_part_id=part_id,
                maintenance_record_id=maintenance_record_id,
                quantity=quantity,
                unit_price=consumption_price,
                consumed_by=current_user.username,
            )
            consumption.save()
            results.append({
                "part_id": part_id,
                "name": part.name,
                "quantity": quantity,
                "consumption_id": consumption.id,
            })

            _check_and_create_alerts(part)

        except Exception as e:
            errors.append(f"处理备件 {item.get('spare_part_id')} 失败: {str(e)}")

    return jsonify({
        "message": f"已记录 {len(results)} 项备件消耗",
        "results": results,
        "errors": errors,
    })


# ============================================================
# API 路由 - 预警
# ============================================================


@spare_part_bp.route("/api/alerts/<int:alert_id>/resolve", methods=["POST"])
@permission_required("device_maintenance")
def api_resolve_alert(alert_id):
    """解决预警"""
    alert = SparePartAlert.get_by_id(alert_id)
    if alert is None:
        return jsonify({"error": "预警记录不存在"}), 404
    if alert.is_resolved:
        return jsonify({"message": "预警已解决"})

    alert.resolve()

    log_action(
        current_user.username, "resolve_spare_part_alert", "spare_part_alerts", alert_id,
        f"解决备件预警：{alert.alert_type_label}",
    )

    return jsonify({"message": "预警已标记为已解决"})


# ============================================================
# 辅助函数
# ============================================================


def _check_and_create_alerts(part):
    """检查并创建预警（在库存变更后调用）"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 低库存预警
    if part.current_stock <= part.safety_stock_min and part.current_stock > 0:
        alert = SparePartAlert(
            spare_part_id=part.id,
            alert_type="low_stock",
            current_stock=part.current_stock,
            threshold=part.safety_stock_min,
        )
        alert.save()

    # 缺货预警
    if part.current_stock <= 0:
        alert = SparePartAlert(
            spare_part_id=part.id,
            alert_type="low_stock",
            current_stock=0,
            threshold=part.safety_stock_min,
        )
        alert.save()

    # 超量预警
    if part.safety_stock_max > 0 and part.current_stock >= part.safety_stock_max:
        alert = SparePartAlert(
            spare_part_id=part.id,
            alert_type="over_stock",
            current_stock=part.current_stock,
            threshold=part.safety_stock_max,
        )
        alert.save()

    # 呆滞预警（12个月无出库）
    if part.check_idle():
        alert = SparePartAlert(
            spare_part_id=part.id,
            alert_type="idle",
            current_stock=part.current_stock,
            threshold=365,
        )
        alert.save()


def _resolve_stock_alerts(part_id, alert_type):
    """解决指定类型的未解决预警"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE spare_part_alerts SET is_resolved = 1, resolved_at = %s "
        "WHERE spare_part_id = %s AND alert_type = %s AND is_resolved = 0",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), part_id, alert_type),
    )
    conn.commit()
    conn.close()
