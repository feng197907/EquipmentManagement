"""
前端日志上报接口
接收浏览器端 JS 错误并写入 logs/js_error.log
"""
import logging
from flask import Blueprint, request, jsonify

log_bp = Blueprint('log', __name__)

js_error_logger = logging.getLogger('js_error')


@log_bp.route('/api/log/js-error', methods=['POST'])
def report_js_error():
    """接收前端上报的 JS 错误，写入 js_error.log"""
    try:
        data = request.get_json(silent=True) or {}

        message   = str(data.get('message', ''))[:2000]
        source    = str(data.get('source', ''))[:500]
        lineno    = data.get('lineno', '')
        colno     = data.get('colno', '')
        stack     = str(data.get('stack', ''))[:3000]
        error_type = str(data.get('type', 'error'))[:50]
        page_url  = str(data.get('url', request.referrer or ''))[:500]
        user_agent = request.headers.get('User-Agent', '')[:300]

        log_line = (
            f"[JS][{error_type}] {message} | "
            f"source={source} line={lineno} col={colno} | "
            f"page={page_url} | "
            f"ua={user_agent}"
        )
        if stack:
            log_line += f"\nStack:\n{stack}"

        js_error_logger.error(log_line)

    except Exception as e:
        logging.getLogger('error').error(f'[log_bp] 记录 JS 错误失败: {e}', exc_info=True)

    # 不管成功失败都返回 204，避免前端报错死循环
    return '', 204
