# 用户管理 Blueprint
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from werkzeug.security import generate_password_hash

from config import (
    ADMIN_MENU_PERMISSIONS,
    DEFAULT_MENU_PERMISSIONS,
    MENU_PERMISSIONS,
    ROLE_GROUPS,
    ROLE_LABELS,
    ROLES,
    get_role_label,
    is_valid_role,
    parse_permissions,
    serialize_permissions,
)
from database import get_db
from utils.audit import log_action
from utils.decorators import admin_required
from utils import password_utils as password_service
from utils.password_utils import validate_password, validate_password_form

users_bp = Blueprint("users", __name__)


@users_bp.route("/users")
@admin_required
def user_list():
    """用户列表"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, username, role, status, permissions FROM users ORDER BY id ASC")
    users = cur.fetchall()
    conn.close()
    # 将角色键转换为标签用于显示，并解析权限
    users_with_labels = []
    for user in users:
        user_dict = dict(user)
        user_dict["role_label"] = get_role_label(user_dict.get("role", ""))
        user_dict["menu_permissions"] = parse_permissions(user_dict.get("permissions", "[]"))
        users_with_labels.append(user_dict)

    return render_template(
        "users.html",
        users=users_with_labels,
        role_labels=ROLE_LABELS,
        ROLE_GROUPS=ROLE_GROUPS,
        MENU_PERMISSIONS=MENU_PERMISSIONS,
    )


@users_bp.route("/users/create", methods=["POST"])
@admin_required
def create_user():
    """创建用户"""
    username = request.form.get("username", "").strip()
    role = request.form.get("role", "equipment_engineer").strip()
    # 获取菜单权限选择
    selected_permissions = request.form.getlist("menu_permissions")

    if not username:
        flash("用户名不能为空。", "warning")
        return redirect(url_for("users.user_list"))
    password, error = validate_password(request.form.get("password"))
    if error:
        flash(error, "danger")
        return redirect(url_for("users.user_list"))
    # 验证角色是否合法（使用 config.ROLES）
    if not is_valid_role(role):
        flash(f"角色不合法，请选择有效的角色。", "warning")
        return redirect(url_for("users.user_list"))

    # 管理员默认拥有所有权限
    if role == "admin":
        permissions_str = serialize_permissions(ADMIN_MENU_PERMISSIONS)
    else:
        permissions_str = serialize_permissions(selected_permissions)

    conn = get_db()
    cur = conn.cursor()
    try:
        hashed = generate_password_hash(password, method='pbkdf2:sha256')
        cur.execute(
            "INSERT INTO users (username, password, role, permissions) VALUES (%s, %s, %s, %s)",
            (username, hashed, role, permissions_str),
        )
        conn.commit()
        user_id = cur.lastrowid
        # 审计日志使用角色标签
        role_display = get_role_label(role)
        log_action(
            current_user.username, "create_user", "user", user_id,
            f"创建用户 {username} ({role_display})",
        )
        flash("用户已创建。", "success")
    except Exception:
        conn.rollback()
        flash("创建失败，用户名可能已存在。", "danger")
    finally:
        conn.close()
    return redirect(url_for("users.user_list"))


@users_bp.route("/users/<int:user_id>/toggle", methods=["POST"])
@admin_required
def toggle_user(user_id):
    """切换用户状态"""
    if current_user.id == user_id:
        flash("不能停用当前登录用户。", "warning")
        return redirect(url_for("users.user_list"))
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, username, status FROM users WHERE id = %s", (user_id,))
    user_row = cur.fetchone()
    if user_row is None:
        conn.close()
        flash("用户不存在。", "warning")
        return redirect(url_for("users.user_list"))
    new_status = "inactive" if user_row["status"] == "active" else "active"
    cur.execute("UPDATE users SET status = %s WHERE id = %s", (new_status, user_id))
    conn.commit()
    log_action(
        current_user.username, "toggle_user", "user", user_id,
        f"用户 {user_row['username']} 状态改为 {new_status}",
    )
    conn.close()
    flash("用户状态已更新。", "success")
    return redirect(url_for("users.user_list"))


@users_bp.route("/users/<int:user_id>/permissions", methods=["POST"])
@admin_required
def update_user_permissions(user_id):
    """更新用户菜单权限"""
    if current_user.id == user_id:
        flash("不能修改当前登录用户的权限。", "warning")
        return redirect(url_for("users.user_list"))

    selected_permissions = request.form.getlist("menu_permissions")
    permissions_str = serialize_permissions(selected_permissions)

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT username, role FROM users WHERE id = %s", (user_id,))
    user_row = cur.fetchone()
    if user_row is None:
        conn.close()
        flash("用户不存在。", "warning")
        return redirect(url_for("users.user_list"))

    # 管理员角色不能修改权限（始终拥有所有权限）
    if user_row["role"] == "admin":
        conn.close()
        flash("管理员角色已拥有所有权限，无需单独配置。", "info")
        return redirect(url_for("users.user_list"))

    cur.execute(
        "UPDATE users SET permissions = %s WHERE id = %s",
        (permissions_str, user_id),
    )
    conn.commit()
    log_action(
        current_user.username, "update_user_permissions", "user", user_id,
        f"更新用户 {user_row['username']} 的菜单权限",
    )
    conn.close()
    flash("用户权限已更新。", "success")
    return redirect(url_for("users.user_list"))


@users_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def delete_user(user_id):
    """删除用户（仅 admin 可删除已停用用户）"""
    if current_user.id == user_id:
        flash("不能删除当前登录用户。", "warning")
        return redirect(url_for("users.user_list"))

    # 只有 admin 角色可以删除用户
    if current_user.role != "admin":
        flash("只有管理员可以删除用户。", "danger")
        return redirect(url_for("users.user_list"))

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, username, status, role FROM users WHERE id = %s", (user_id,))
    user_row = cur.fetchone()
    if user_row is None:
        conn.close()
        flash("用户不存在。", "warning")
        return redirect(url_for("users.user_list"))

    # 只能删除已停用的用户
    if user_row["status"] != "inactive":
        conn.close()
        flash("只能删除已停用的用户，请先停用该用户。", "warning")
        return redirect(url_for("users.user_list"))

    # 不能删除其他 admin 用户
    if user_row["role"] == "admin":
        conn.close()
        flash("不能删除管理员账号。", "warning")
        return redirect(url_for("users.user_list"))

    # 执行删除
    cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
    conn.commit()
    log_action(
        current_user.username, "delete_user", "user", user_id,
        f"删除用户 {user_row['username']}",
    )
    conn.close()
    flash(f"用户 {user_row['username']} 已删除。", "success")
    return redirect(url_for("users.user_list"))


@users_bp.route("/users/<int:user_id>/reset-password", methods=["POST"])
@admin_required
def reset_user_password(user_id):
    """管理员在用户管理页主动重置其他用户的密码"""
    if current_user.id == user_id:
        flash("不能重置当前登录用户的密码。", "warning")
        return redirect(url_for("users.user_list"))

    pwd, error = validate_password_form(request.form)
    if error:
        flash(error, "danger")
        return redirect(url_for("users.user_list"))

    try:
        result = password_service.reset_user_password(
            user_id, pwd, current_user.username, "admin_direct"
        )
    except ValueError as exc:
        flash(str(exc), "warning")
        return redirect(url_for("users.user_list"))

    flash(f"用户 {result['username']} 的密码已重置。", "success")
    return redirect(url_for("users.user_list"))
