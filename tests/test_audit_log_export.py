# 审计日志导出：筛选导出 / 全部导出 / admin 权限 / xlsx 内容安全
import os
import re
import tempfile
from io import BytesIO

import pytest
from flask import render_template
from openpyxl import load_workbook
from werkzeug.security import generate_password_hash

from database import get_db, init_db

ADMIN_USER = "admin"
ADMIN_PASSWORD = "audit-export-admin-only"
NON_ADMIN_USER = "qa_user"
NON_ADMIN_PASSWORD = "audit-export-qa-only"

# (user, action, target_type, target_id, log_time)
LOGS = [
    ("alice", "ACTION-A1", "device", 1, "2026-10-01 09:00:00"),
    ("alice", "ACTION-A2", "document", 2, "2026-10-05 10:30:00"),
    ("bob", "ACTION-B1", "device", 3, "2026-10-10 11:00:00"),
    ("bob", "ACTION-B2", "user", 4, "2026-10-15 12:00:00"),
    ("carol", "ACTION-C1", "document", 5, "2026-10-20 13:00:00"),
]

HEADERS = [
    "操作人", "时间", "操作", "目标类型", "目标ID",
    "详情", "操作前值", "操作后值", "修改原因", "IP",
]


@pytest.fixture()
def client(monkeypatch):
    """临时 sqlite + 真实登录，避免依赖本地 .env 里的 MySQL 配置。"""
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    import database as dbmod

    monkeypatch.setattr(dbmod, "DB_PATH", tmp)
    monkeypatch.setattr(dbmod, "DB_TYPE", "sqlite")
    init_db()

    conn = get_db()
    cur = conn.cursor()

    def _upsert(username, password, role):
        pwd_hash = generate_password_hash(password)
        cur.execute("SELECT id FROM users WHERE username = %s", (username,))
        if cur.fetchone():
            cur.execute(
                "UPDATE users SET password = %s, role = %s, status = 'active' WHERE username = %s",
                (pwd_hash, role, username),
            )
        else:
            cur.execute(
                "INSERT INTO users (username, password, role, status, permissions) "
                "VALUES (%s, %s, %s, 'active', '[]')",
                (username, pwd_hash, role),
            )

    _upsert(ADMIN_USER, ADMIN_PASSWORD, "admin")
    _upsert(NON_ADMIN_USER, NON_ADMIN_PASSWORD, "qa_manager")

    for user, action, target_type, target_id, log_time in LOGS:
        cur.execute(
            "INSERT INTO audit_logs "
            "(user, action, target_type, target_id, details, before_value, after_value, reason, ip_address, log_time) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (user, action, target_type, target_id, f"{action} 详情", "", "", "", "127.0.0.1", log_time),
        )
    conn.commit()
    conn.close()

    from app import create_app

    app = create_app()
    app.config["TESTING"] = True

    with app.test_client() as c:
        resp = c.post(
            "/login",
            data={"username": ADMIN_USER, "password": ADMIN_PASSWORD},
        )
        assert resp.status_code == 302, "admin 登录失败，后续断言都不可信"
        yield c

    try:
        os.remove(tmp)
    except OSError:
        pass


def _login_as(client, username, password):
    client.get("/logout")
    resp = client.post("/login", data={"username": username, "password": password})
    assert resp.status_code == 302


def _db_count():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM audit_logs")
    count = cur.fetchone()["c"]
    conn.close()
    return count


def _read_xlsx(response):
    assert response.status_code == 200
    assert "spreadsheetml" in response.headers["Content-Type"]
    assert "attachment" in response.headers["Content-Disposition"]
    assert ".xlsx" in response.headers["Content-Disposition"]
    wb = load_workbook(BytesIO(response.data), read_only=True, data_only=True)
    try:
        return list(wb.active.iter_rows(values_only=True))
    finally:
        wb.close()


def _insert_logs(rows):
    conn = get_db()
    cur = conn.cursor()
    for user, action, target_type, target_id, log_time in rows:
        cur.execute(
            "INSERT INTO audit_logs "
            "(user, action, target_type, target_id, details, before_value, after_value, reason, ip_address, log_time) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (user, action, target_type, target_id, "批量日志", "", "", "", "10.0.0.1", log_time),
        )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------- 页面按钮


def test_admin_page_has_two_enabled_export_buttons(client):
    html = client.get("/audit_log").get_data(as_text=True)
    block = re.search(
        r'<div class="search-actions audit-export-actions">(.*?)</div>', html, re.S
    )
    assert block, "找不到导出按钮所在的 search-actions 区块"
    part = block.group(1)
    assert "导出筛选结果" in part
    assert "导出全部" in part
    assert part.count('formaction="/audit_log/export"') == 2
    assert 'name="scope" value="filtered"' in part
    assert 'name="scope" value="all"' in part
    assert "disabled" not in part, "admin 的导出按钮不应被禁用"
    assert "导出功能仅管理员可用" not in html


def test_non_admin_template_renders_disabled_export_buttons(client):
    """当前 /audit_log 整页是 admin 专属，直接渲染模板验证禁用态标记。"""
    with client.application.test_request_context("/audit_log"):
        html = render_template(
            "audit_log.html",
            rows=[],
            target_types=[],
            result_limit=500,
            filter_user="",
            filter_target_type="",
            start_date="",
            end_date="",
            can_export=False,
        )
    assert 'aria-disabled="true"' in html
    assert html.count("disabled") >= 2
    assert "导出功能仅管理员可用" in html


# ---------------------------------------------------------------- 筛选 / 全部


def test_export_filtered_uses_current_filters(client):
    rows = _read_xlsx(client.get("/audit_log/export?scope=filtered&user=alice"))
    assert list(rows[0]) == HEADERS
    actions = [r[2] for r in rows[1:]]
    assert sorted(actions) == ["ACTION-A1", "ACTION-A2"]
    assert all(r[0] == "alice" for r in rows[1:])


def test_export_filtered_respects_target_type_and_date(client):
    rows = _read_xlsx(
        client.get(
            "/audit_log/export?scope=filtered&target_type=device"
            "&start_date=2026-10-05&end_date=2026-10-31"
        )
    )
    assert [r[2] for r in rows[1:]] == ["ACTION-B1"]


def test_export_all_ignores_filters(client):
    expected = _db_count()
    rows = _read_xlsx(client.get("/audit_log/export?scope=all&user=alice"))
    assert len(rows) - 1 == expected, "导出全部应忽略筛选条件并包含所有行"
    actions = {r[2] for r in rows[1:]}
    for _, action, _, _, _ in LOGS:
        assert action in actions


def test_default_scope_is_filtered(client):
    rows = _read_xlsx(client.get("/audit_log/export?user=bob"))
    assert sorted(r[2] for r in rows[1:]) == ["ACTION-B1", "ACTION-B2"]


def test_invalid_scope_falls_back_to_filtered(client):
    rows = _read_xlsx(client.get("/audit_log/export?scope=<script>&user=carol"))
    assert [r[2] for r in rows[1:]] == ["ACTION-C1"]


def test_empty_result_still_produces_valid_xlsx(client):
    rows = _read_xlsx(client.get("/audit_log/export?scope=filtered&user=nobody"))
    assert len(rows) == 1
    assert list(rows[0]) == HEADERS


def test_export_is_not_capped_at_500_rows(client):
    """页面展示上限 500，但「导出全部」必须导出真正的全部。"""
    extra = [
        ("bulk", f"BULK-{i:04d}", "device", i, "2026-11-01 08:00:00")
        for i in range(520)
    ]
    _insert_logs(extra)

    page = client.get("/audit_log").get_data(as_text=True)
    assert "最多显示 500 条" in page

    rows = _read_xlsx(client.get("/audit_log/export?scope=all"))
    assert len(rows) - 1 >= 520, "导出不应受页面 500 条上限限制"


def test_filename_reflects_scope(client):
    filtered = client.get("/audit_log/export?scope=filtered")
    all_rows = client.get("/audit_log/export?scope=all")
    assert "audit_log_filtered_" in filtered.headers["Content-Disposition"]
    assert "audit_log_all_" in all_rows.headers["Content-Disposition"]


# ---------------------------------------------------------------- 权限


def test_non_admin_cannot_export_via_direct_url(client):
    _login_as(client, NON_ADMIN_USER, NON_ADMIN_PASSWORD)
    resp = client.get("/audit_log/export?scope=all")
    assert resp.status_code == 302, "非 admin 应被重定向而不是拿到文件"
    assert "spreadsheetml" not in resp.headers.get("Content-Type", "")


def test_anonymous_cannot_export(client):
    client.get("/logout")
    resp = client.get("/audit_log/export?scope=all")
    assert resp.status_code in (302, 401)
    assert "spreadsheetml" not in resp.headers.get("Content-Type", "")


# ---------------------------------------------------------------- 内容与审计


def test_export_action_itself_is_audited(client):
    before = _db_count()
    _read_xlsx(client.get("/audit_log/export?scope=all"))
    assert _db_count() == before + 1

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT action, details FROM audit_logs WHERE action = %s", ("export_audit_log",))
    rows = cur.fetchall()
    conn.close()
    assert len(rows) == 1
    assert "全部" in rows[0]["details"]


def test_formula_like_values_are_written_as_text(client):
    """用户输入以 = 开头时不能被 Excel 当公式执行。"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO audit_logs "
        "(user, action, target_type, target_id, details, before_value, after_value, reason, ip_address, log_time) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        ("mallory", "FORMULA-1", "device", 9, '=HYPERLINK("http://evil","click")',
         "+1", "-1", "@SUM(A1:A2)", "127.0.0.1", "2026-10-22 08:00:00"),
    )
    conn.commit()
    conn.close()

    resp = client.get("/audit_log/export?scope=filtered&user=mallory")
    wb = load_workbook(BytesIO(resp.data))
    try:
        ws = wb.active
        detail = ws["F2"]
        assert detail.data_type == "s", "公式样文本必须按字符串写入"
        assert str(detail.value).startswith("=HYPERLINK")
    finally:
        wb.close()


def test_export_escapes_control_characters(client):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO audit_logs "
        "(user, action, target_type, target_id, details, before_value, after_value, reason, ip_address, log_time) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        ("dave", "CTRL-1", "device", 10, "line1\x00line2\x07end",
         "", "", "", "127.0.0.1", "2026-10-23 08:00:00"),
    )
    conn.commit()
    conn.close()

    rows = _read_xlsx(client.get("/audit_log/export?scope=filtered&user=dave"))
    assert "\x00" not in rows[1][5]
    assert "line1" in rows[1][5]
