"""统一改密服务。

这是「用户管理页管理员主动重置」与「密码重置申请处理」两条入口唯一的改密出口：
所有修改 users.password 的操作都必须经过 reset_user_password()，以复用同一套
密码哈希方式、审计日志与待处理申请的收尾逻辑。

改密成功后会按 user_id 把该用户所有 pending 状态的 password_reset_requests
批量置为 completed。这样做的目的是消除「直接改密后旧的 pending 申请仍然悬挂」
的冲突：否则旧申请还能被管理员再次处理，造成二次改密，且用户因为已有 pending
申请而无法重新提交新的重置请求。批量关闭后顶栏闹铃（按 status='pending' 计数）
会归零，用户也能正常重新走申请流程。
"""

from werkzeug.security import generate_password_hash

from database import get_db
from utils.audit import log_action

MIN_PASSWORD_LENGTH = 4
PASSWORD_HASH_METHOD = "pbkdf2:sha256"


def validate_password(new_password, confirm_password=None):
    """校验新密码。

    返回 ``(pwd, error)``：成功时 ``pwd`` 为 strip 后的密码、``error`` 为 None；
    失败时返回 ``(None, 错误信息)``。confirm_password 传 None 表示不校验二次确认。
    """
    pwd = (new_password or "").strip()
    if len(pwd) < MIN_PASSWORD_LENGTH:
        return None, "新密码长度不能少于4个字符"
    if confirm_password is not None and pwd != (confirm_password or "").strip():
        return None, "两次输入的密码不一致"
    return pwd, None


def validate_password_form(form, new_key="new_password", confirm_key="confirm_password"):
    """从 request.form 读取并校验新密码，返回 (pwd, error)。

    表单里**没有**确认密码字段时把 confirm_password 传成 None（跳过二次确认），
    用于兼容旧版重置表单（旧模板的确认框没有 name，从不提交）以及直接调用接口的
    客户端；只要表单提供了该字段（哪怕为空），就必须与新密码一致。
    两个前端重置弹窗都带 name 且 required，UI 路径始终执行二次确认。
    """
    confirm = form[confirm_key] if confirm_key in form else None
    return validate_password(form.get(new_key), confirm)


def reset_user_password(user_id, new_password, operator, source, request_id=None):
    """重置用户密码，并关闭该用户所有待处理的密码重置申请。

    约定：新密码的长度与二次确认校验由调用方事先通过 validate_password() 完成，
    本函数不重复校验，只接收已校验过的明文密码。

    :param operator: 操作人用户名，用于审计日志与 processed_by 字段
    :param source: "admin_direct"（管理员主动重置）或 "reset_request"（处理申请）
    :param request_id: source 为 "reset_request" 时的申请 ID，仅用于审计文案
    :return: {"username": 用户名, "closed_pending": 被关闭的 pending 申请数}
    :raises ValueError: 用户不存在
    """
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT username FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError("用户不存在")
        username = row["username"]

        cur.execute(
            "UPDATE users SET password = %s WHERE id = %s",
            (generate_password_hash(new_password, method=PASSWORD_HASH_METHOD), user_id),
        )

        cur.execute(
            "SELECT COUNT(*) AS c FROM password_reset_requests "
            "WHERE user_id = %s AND status = 'pending'",
            (user_id,),
        )
        closed = cur.fetchone()["c"]

        if closed > 0:
            cur.execute(
                """UPDATE password_reset_requests
                   SET status = 'completed', processed_at = NOW(), processed_by = %s
                   WHERE user_id = %s AND status = 'pending'""",
                (operator, user_id),
            )

        conn.commit()
    except Exception:
        # MySQL 下不能只依赖连接关闭时的隐式回滚，异常路径显式回滚
        conn.rollback()
        raise
    finally:
        conn.close()

    # log_action 内部会自行 get_db() 开连接、commit、close，必须等上面的连接
    # close 之后再调用，否则 SQLite 下会锁库。
    if source == "admin_direct":
        detail = f"管理员主动重置用户 {username} 的密码"
    elif source == "reset_request":
        detail = f"处理密码重置申请 #{request_id}，重置用户 {username} 的密码"
    else:
        detail = f"重置用户 {username} 的密码（来源：{source}）"
    if closed > 0:
        detail += f"；同时关闭该用户 {closed} 条待处理申请"
    log_action(operator, "reset_user_password", "user", user_id, detail)

    return {"username": username, "closed_pending": closed}
