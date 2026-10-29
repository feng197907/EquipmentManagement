# DMS 设备管理系统 - Flask 应用工厂
import os
import sys

from dotenv import load_dotenv

# 加载 .env 文件中的环境变量
load_dotenv()

from flask import Flask

from config import (
    DOC_STATUS_LABELS,
    DEVICE_STATUS_LABELS,
    MENU_PERMISSIONS,
    ROLE_GROUPS,
    SECRET_KEY,
    UPLOAD_FOLDER,
)
from database import get_db, init_db
from blueprints import (
    approvals_bp,
    auth_bp,
    borrowing_bp,
    dashboard_bp,
    device_changes_bp,
    devices_bp,
    documents_bp,
    esign_bp,
    maintenance_bp,
    password_bp,
    search_bp,
    settings_bp,
    spare_part_bp,
    users_bp,
)
from extensions import login_manager
from utils.logging_config import setup_logging
from models.user import load_user


def create_app():
    """Flask 应用工厂函数"""
    app = Flask(__name__)

    # Flask 配置
    app.config["SECRET_KEY"] = SECRET_KEY
    app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
    app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

    # 初始化 Flask-Login
    login_manager.login_view = "auth.login"
    login_manager.init_app(app)
    app = setup_logging(app)

    # 注册用户加载回调
    login_manager.user_loader(load_user)

    # 注册 Blueprints
    app.register_blueprint(auth_bp)  # login, logout, index (保持原路径)
    app.register_blueprint(devices_bp)  # /device/<id> 等
    app.register_blueprint(documents_bp)  # upload_doc, download, documents 等
    app.register_blueprint(borrowing_bp)  # /borrow/<id>
    app.register_blueprint(approvals_bp)  # /approvals
    app.register_blueprint(device_changes_bp)  # /device_changes
    app.register_blueprint(users_bp)  # /users
    app.register_blueprint(dashboard_bp)  # dashboard, reminders, add_device 等
    app.register_blueprint(maintenance_bp)  # 维护计划相关路由
    app.register_blueprint(search_bp)  # 全局搜索
    app.register_blueprint(password_bp)  # 密码重置功能
    app.register_blueprint(settings_bp)  # 系统设置
    app.register_blueprint(esign_bp)  # 电子签名
    app.register_blueprint(spare_part_bp)  # 备件库存管理

    # 确保上传目录存在
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    # 初始化数据库
    init_db()

    # 全局上下文处理器 - 注入变量到所有模板
    @app.context_processor
    def inject_global_vars():
        """向所有模板注入全局变量"""
        try:
            conn = get_db()
            cur = conn.cursor()
            # 文档审批待处理数量
            cur.execute("SELECT COUNT(*) as total FROM approval_requests WHERE status = 'pending'")
            result = cur.fetchone()
            pending_count = result["total"] if result else 0
            # 设备状态变更待审批数量
            cur.execute("SELECT COUNT(*) as total FROM device_status_requests WHERE status = 'pending'")
            result = cur.fetchone()
            device_change_count = result["total"] if result else 0
            conn.close()
        except Exception:
            pending_count = 0
            device_change_count = 0

        # 判断当前用户是否有文档审批权限（控制顶部闹铃显示）
        can_view_approvals = False
        try:
            from flask_login import current_user
            if current_user.is_authenticated:
                can_view_approvals = current_user.has_permission("document_approval")
        except Exception:
            pass

        # 查询待处理的密码重置请求数量（管理类角色可见）
        password_reset_count = 0
        try:
            from flask_login import current_user
            if current_user.is_authenticated:
                # 检查用户角色是否在管理类中
                management_roles = ROLE_GROUPS.get("管理类", [])
                if current_user.role in management_roles:
                    conn2 = get_db()
                    cur2 = conn2.cursor()
                    cur2.execute("SELECT COUNT(*) as total FROM password_reset_requests WHERE status = 'pending'")
                    result2 = cur2.fetchone()
                    password_reset_count = result2["total"] if result2 else 0
                    conn2.close()
        except Exception:
            pass

        # 查询借阅功能开关
        borrowing_enabled = True  # 默认开启
        try:
            from database import get_system_setting
            val = get_system_setting("borrowing_enabled")
            borrowing_enabled = (val == "true") if val is not None else True
        except Exception:
            pass

        return dict(
            pending_count=pending_count,
            device_change_count=device_change_count,
            can_view_approvals=can_view_approvals,
            password_reset_count=password_reset_count,
            borrowing_enabled=borrowing_enabled,
            doc_status_labels=DOC_STATUS_LABELS,
            device_status_labels=DEVICE_STATUS_LABELS,
            MENU_PERMISSIONS=MENU_PERMISSIONS,
        )

    @app.route("/healthz")
    def healthz():
        """容器健康检查。

        故意不只看进程活着——进程活着但数据库连不上，这个系统对外就是坏的。
        真查一次库，连不上返回 503，让 docker 的 healthcheck 能反映出真实状态。
        """
        from flask import jsonify

        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("SELECT 1 AS ok")
            cur.fetchone()
            conn.close()
        except Exception as exc:
            return jsonify(status="degraded", db=type(exc).__name__), 503

        return jsonify(status="ok"), 200

    return app


# 创建应用实例（仅当直接运行时创建，避免 import 副作用）
if __name__ == "__main__":
    import traceback
    try:
        app = create_app()
        # 绑定到所有网络接口，允许外部访问
        # port 通过环境变量配置，默认 5000
        port = int(os.environ.get('PORT', 5000))
        app.run(host='0.0.0.0', port=port, debug=True, use_reloader=False)
    except Exception as e:
        # 启动异常写入错误日志
        import logging
        logger = logging.getLogger('error')
        logger.error(f'[STARTUP ERROR] 应用启动失败: {str(e)}', exc_info=True)
        # 同时输出到 stderr，确保能在 app.log 中看到
        print(f'[STARTUP ERROR] {str(e)}', file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
else:
    # 被其他模块导入时（如 pytest、gunicorn），不自动创建实例
    app = None

