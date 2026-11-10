# 文档 Blueprint
import os
from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, send_from_directory, url_for
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from config import (
    DOC_STATUS_LABELS,
    DOC_TYPE_LABELS,
    DOC_TYPES,
)
from database import get_db, get_system_setting
from utils.audit import log_action
from utils.db_utils import commit_with_retry, execute_with_retry, get_next_version
from utils.decorators import admin_required
from utils.excel_export import export_to_excel
from utils.file_utils import allowed_file, compute_doc_hash, ensure_upload_dir

documents_bp = Blueprint("documents", __name__)


@documents_bp.route("/upload_doc/<int:device_id>", methods=["GET", "POST"])
@login_required
def upload_doc(device_id):
    """上传文档"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM devices WHERE id = %s", (device_id,))
    device = cur.fetchone()
    if device is None:
        conn.close()
        flash("设备不存在。", "warning")
        return redirect(url_for("auth.index"))

    # 检查审批流程是否启用
    approval_enabled = get_system_setting("approval_enabled", "true")
    auto_approve = get_system_setting("auto_approve_document", "false")

    # 审批流程关闭时，文档直接生效
    # 审批流程开启时，根据"文档自动生效"设置决定
    if approval_enabled != "true":
        initial_status = "active"
    elif auto_approve == "true":
        initial_status = "active"
    else:
        initial_status = "draft"

    if request.method == "POST":
        default_doc_type = request.form.get("default_doc_type") or request.form.get("doc_type_default")
        remarks = request.form.get("remarks", "").strip()
        files = request.files.getlist("files")

        if not files or all(f.filename == "" for f in files):
            flash("请选择要上传的文件。", "warning")
            return redirect(url_for("documents.upload_doc", device_id=device_id))

        success_count = 0
        error_msgs = []
        device_dir = ensure_upload_dir(device_id)
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        for idx, file in enumerate(files):
            if not file or file.filename == "":
                continue
            if not allowed_file(file.filename):
                error_msgs.append(f"「{file.filename}」文件类型不允许。")
                continue

            # 每个文件独立读取文档类型（优先 doc_type_map_{idx}，回退默认）
            doc_type = request.form.get(f"doc_type_map_{idx}") or default_doc_type
            if doc_type not in DOC_TYPE_LABELS:
                error_msgs.append(f"「{file.filename}」文档类型无效。")
                continue

            # 校准到期日：仅当文件类型为校准记录时处理
            calibration_due_date = None
            if doc_type == "calibration":
                calibration_due_date = request.form.get("calibration_due_date", "").strip() or None

            version = get_next_version(conn, device_id, doc_type)
            original_name = file.filename
            # 清理文件名中的危险字符，但保留中文等非ASCII字符
            safe_name = original_name.replace("..", ".").replace("/", "_").replace("\\", "_")
            # 存储文件名使用安全的ASCII版本（用于文件系统）
            stored_name = secure_filename(f"{doc_type}_{version}_{safe_name}")
            if not stored_name or stored_name == f"{doc_type}_{version}_":
                # 如果secure_filename去掉了所有字符，使用原始扩展名
                ext = safe_name.rsplit(".", 1)[-1] if "." in safe_name else "file"
                stored_name = f"{doc_type}_{version}_document.{ext}"
            file_path = os.path.join(device_dir, stored_name)
            file.save(file_path)
            # 存储相对于项目根目录的相对路径，兼容云服务器部署
            relative_path = os.path.relpath(file_path, base_dir)
            cur.execute(
                "INSERT INTO documents (device_id, doc_type, doc_name, version, file_path, uploaded_by, remarks, status, calibration_due_date) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (device_id, doc_type, safe_name, version, relative_path, current_user.username, remarks, initial_status, calibration_due_date),
            )
            conn.commit()
            doc_id = cur.lastrowid
            log_action(
                current_user.username, "upload_document", "document", doc_id,
                f"上传 {DOC_TYPE_LABELS.get(doc_type)} v{version}",
            )
            success_count += 1

        conn.close()

        # 汇总反馈
        total = sum(1 for f in files if f and f.filename != "")
        if success_count == total:
            msg = f"已成功上传 {success_count} 个文档"
            if initial_status == "active":
                msg += "并生效（审批流程已禁用）。"
            else:
                msg += "。"
            flash(msg, "success")
        elif success_count > 0:
            flash(f"上传完成：{success_count} 个成功，{len(error_msgs)} 个失败。", "success")
            for err in error_msgs[:3]:
                flash(err, "warning")
            if len(error_msgs) > 3:
                flash(f"还有 {len(error_msgs) - 3} 个文件上传失败。", "warning")
        else:
            for err in error_msgs[:3]:
                flash(err, "danger")
            flash("所有文件上传失败，请检查文件类型。", "danger")
            return redirect(url_for("documents.upload_doc", device_id=device_id))

        return redirect(url_for("devices.device_detail", device_id=device_id))
    conn.close()
    return render_template("upload_doc.html", device=device, doc_types=DOC_TYPES)


@documents_bp.route("/download/<int:doc_id>")
@login_required
def download_doc(doc_id):
    """下载文档"""
    from config import BASE_DIR

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM documents WHERE id = %s AND is_deleted = 0", (doc_id,))
    doc = cur.fetchone()
    if doc is not None and doc["status"] not in {"active", "archived"}:
        conn.close()
        flash("该文档当前状态不允许下载。", "warning")
        return redirect(url_for("devices.device_detail", device_id=doc["device_id"]))
    if doc is not None:
        cur.execute("UPDATE documents SET download_count = download_count + 1 WHERE id = %s", (doc_id,))
        conn.commit()
    conn.close()
    if doc is None:
        flash("文档不存在或已删除。", "warning")
        return redirect(url_for("auth.index"))
    log_action(
        current_user.username, "download_document", "document", doc_id,
        f"下载 {doc['doc_name']} v{doc['version']}",
    )
    # file_path 存储为相对路径，转换为服务器上的绝对路径
    file_path = doc["file_path"]
    # 如果是相对路径，拼接 BASE_DIR
    if not os.path.isabs(file_path):
        file_path = os.path.join(BASE_DIR, file_path)
    directory = os.path.dirname(file_path)
    filename = os.path.basename(file_path)
    return send_from_directory(
        directory, filename, as_attachment=True, download_name=doc["doc_name"],
    )


@documents_bp.route("/delete_doc/<int:doc_id>", methods=["POST"])
@admin_required
def delete_doc(doc_id):
    """删除文档"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM documents WHERE id = %s", (doc_id,))
    doc = cur.fetchone()
    if doc is None:
        conn.close()
        flash("文档不存在。", "warning")
        return redirect(url_for("auth.index"))
    cur.execute("UPDATE documents SET is_deleted = 1 WHERE id = %s", (doc_id,))
    conn.commit()
    log_action(
        current_user.username, "delete_document", "document", doc_id,
        f"删除 {doc['doc_name']} v{doc['version']}",
    )
    conn.close()
    flash("文档已删除。", "success")
    return redirect(url_for("devices.device_detail", device_id=doc["device_id"]))


@documents_bp.route("/document/<int:doc_id>/submit", methods=["POST"])
@login_required
def submit_document(doc_id):
    """提交文档审批"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM documents WHERE id = %s AND is_deleted = 0", (doc_id,))
    doc = cur.fetchone()
    if doc is None:
        conn.close()
        flash("文档不存在。", "warning")
        return redirect(url_for("auth.index"))
    if doc["status"] != "draft":
        conn.close()
        flash("当前状态不允许提交审批。", "warning")
        return redirect(url_for("devices.device_detail", device_id=doc["device_id"]))

    # 检查审批流程是否启用
    approval_enabled = get_system_setting("approval_enabled", "true")

    if approval_enabled != "true":
        # 审批未启用，直接生效
        execute_with_retry(cur, "UPDATE documents SET status = 'active' WHERE id = %s", (doc_id,))
        commit_with_retry(conn)
        log_action(
            current_user.username, "submit_document", "document", doc_id,
            "提交文档（审批已禁用，文档直接生效）",
            before_value={"status": "draft"}, after_value={"status": "active"},
        )
        conn.close()
        flash("文档已上传并生效（审批流程已禁用）。", "success")
        return redirect(url_for("devices.device_detail", device_id=doc["device_id"]))

    # 正常审批流程
    execute_with_retry(
        cur,
        "INSERT INTO approval_requests (doc_id, status, created_by, current_step) VALUES (%s, 'pending', %s, 1)",
        (doc_id, current_user.username),
    )
    request_id = cur.lastrowid
    from config import APPROVAL_STEPS

    for idx, step in enumerate(APPROVAL_STEPS, start=1):
        execute_with_retry(
            cur,
            "INSERT INTO approval_steps (request_id, step_order, approver_role) VALUES (%s, %s, %s)",
            (request_id, idx, step["role"]),
        )
    execute_with_retry(cur, "UPDATE documents SET status = 'pending' WHERE id = %s", (doc_id,))
    commit_with_retry(conn)
    log_action(
        current_user.username, "submit_document", "document", doc_id,
        "提交文档审批",
        before_value={"status": "draft"}, after_value={"status": "pending"},
    )
    conn.close()
    flash("已提交审批。", "success")
    return redirect(url_for("devices.device_detail", device_id=doc["device_id"]))


@documents_bp.route("/documents")
@login_required
def document_search():
    """文档检索"""
    query = request.args.get("q", "").strip()
    device_query = request.args.get("device", "").strip()
    uploader = request.args.get("uploader", "").strip()
    doc_type = request.args.get("doc_type", "").strip()
    status = request.args.get("status", "").strip()
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()
    sql = (
        "SELECT d.*, dev.device_code, dev.device_name "
        "FROM documents d JOIN devices dev ON dev.id = d.device_id WHERE d.is_deleted = 0"
    )
    params = []
    if query:
        sql += " AND d.doc_name LIKE %s"
        params.append(f"%{query}%")
    if device_query:
        sql += " AND (dev.device_code LIKE %s OR dev.device_name LIKE %s)"
        params.extend([f"%{device_query}%", f"%{device_query}%"])
    if uploader:
        sql += " AND d.uploaded_by LIKE %s"
        params.append(f"%{uploader}%")
    if doc_type:
        sql += " AND d.doc_type = %s"
        params.append(doc_type)
    if status:
        sql += " AND d.status = %s"
        params.append(status)
    if start_date:
        sql += " AND DATE(d.upload_time) >= DATE(%s)"
        params.append(start_date)
    if end_date:
        sql += " AND DATE(d.upload_time) <= DATE(%s)"
        params.append(end_date)
    sql += " ORDER BY d.upload_time DESC"
    conn = get_db()
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return render_template(
        "documents.html",
        rows=rows,
        query=query,
        device_query=device_query,
        uploader=uploader,
        doc_type=doc_type,
        status=status,
        start_date=start_date,
        end_date=end_date,
        doc_types=DOC_TYPES,
        doc_status_labels=DOC_STATUS_LABELS,
        doc_type_labels=DOC_TYPE_LABELS,
    )


@documents_bp.route("/documents/<int:doc_id>/history")
@login_required
def document_history(doc_id):
    """文档版本历史"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT d.*, dev.device_code, dev.device_name FROM documents d JOIN devices dev ON dev.id = d.device_id WHERE d.id = %s AND d.is_deleted = 0",
        (doc_id,),
    )
    current_doc = cur.fetchone()
    if current_doc is None:
        conn.close()
        flash("文档不存在。", "warning")
        return redirect(url_for("documents.document_search"))
    cur.execute(
        "SELECT d.*, dev.device_code, dev.device_name FROM documents d JOIN devices dev ON dev.id = d.device_id WHERE d.device_id = %s AND d.doc_type = %s AND d.is_deleted = 0 ORDER BY d.id DESC",
        (current_doc["device_id"], current_doc["doc_type"]),
    )
    history_rows = cur.fetchall()
    conn.close()
    return render_template(
        "document_history.html",
        current_doc=current_doc,
        history_rows=history_rows,
        doc_type_label=DOC_TYPE_LABELS.get(current_doc["doc_type"], current_doc["doc_type"]),
        doc_status_labels=DOC_STATUS_LABELS,
    )


@documents_bp.route("/documents/export")
@login_required
def export_documents():
    """导出文档列表为 Excel"""
    query = request.args.get("q", "").strip()
    device_query = request.args.get("device", "").strip()
    uploader = request.args.get("uploader", "").strip()
    doc_type = request.args.get("doc_type", "").strip()
    status = request.args.get("status", "").strip()
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()

    sql = (
        "SELECT d.*, dev.device_code, dev.device_name "
        "FROM documents d JOIN devices dev ON dev.id = d.device_id WHERE d.is_deleted = 0"
    )
    params = []
    if query:
        sql += " AND d.doc_name LIKE %s"
        params.append(f"%{query}%")
    if device_query:
        sql += " AND (dev.device_code LIKE %s OR dev.device_name LIKE %s)"
        params.extend([f"%{device_query}%", f"%{device_query}%"])
    if uploader:
        sql += " AND d.uploaded_by LIKE %s"
        params.append(f"%{uploader}%")
    if doc_type:
        sql += " AND d.doc_type = %s"
        params.append(doc_type)
    if status:
        sql += " AND d.status = %s"
        params.append(status)
    if start_date:
        sql += " AND DATE(d.upload_time) >= DATE(%s)"
        params.append(start_date)
    if end_date:
        sql += " AND DATE(d.upload_time) <= DATE(%s)"
        params.append(end_date)
    sql += " ORDER BY d.upload_time DESC"

    conn = get_db()
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()

    headers = ["设备编码", "设备名称", "文档名称", "类型", "版本", "状态", "上传人", "上传时间"]
    export_rows = [
        [
            row["device_code"],
            row["device_name"],
            row["doc_name"],
            DOC_TYPE_LABELS.get(row["doc_type"], row["doc_type"]),
            f"v{row['version']}",
            DOC_STATUS_LABELS.get(row["status"], row["status"]),
            row["uploaded_by"],
            row["upload_time"],
        ]
        for row in rows
    ]

    return export_to_excel(
        filename_prefix="documents",
        sheet_title="文档列表",
        headers=headers,
        rows=export_rows,
    )
