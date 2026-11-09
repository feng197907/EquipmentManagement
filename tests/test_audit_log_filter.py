"""审计日志页 /audit_log 顶部筛选的回归测试。

筛选项：操作人（模糊）、时间范围（起止日期）、目标类型（精确）。
验证重点不只是「能筛」，还包括：
- 三个条件可以叠加，且互不干扰；
- 非法日期、不存在的目标类型被安全忽略；
- 用户输入走参数绑定，不会被当成 SQL 或 HTML 执行；
- 筛选后表单回显当前条件，重置按钮可用。
"""
import os
import tempfile

import pytest
from werkzeug.security import generate_password_hash

from database import init_db

TEST_PASSWORD = "audit-filter-test-only"

# (user, action, target_type, target_id, log_time)
LOGS = [
    ("alice", "ACTION-A1", "device", 1, "2026-10-01 09:00:00"),
    ("alice", "ACTION-A2", "document", 2, "2026-10-05 10:30:00"),
    ("bob", "ACTION-B1", "device", 3, "2026-10-10 11:00:00"),
    ("bob", "ACTION-B2", "user", 4, "2026-10-15 12:00:00"),
    ("carol", "ACTION-C1", "document", 5, "2026-10-20 13:00:00"),
]

ALL_ACTIONS = [row[1] for row in LOGS]


@pytest.fixture()
def client(monkeypatch):
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    import database as dbmod

    # 不依赖跑测试时外层的 DB_TYPE 环境变量，强制走临时 sqlite
    monkeypatch.setattr(dbmod, "DB_TYPE", "sqlite")
    monkeypatch.setattr(dbmod, "DB_PATH", tmp)
    init_db()

    conn = dbmod.get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET password = %s WHERE username = %s",
        (generate_password_hash(TEST_PASSWORD), "admin"),
    )
    cur.executemany(
        "INSERT INTO audit_logs (user, action, target_type, target_id, log_time) "
        "VALUES (%s, %s, %s, %s, %s)",
        LOGS,
    )
    conn.commit()
    conn.close()

    from app import create_app

    app = create_app()
    app.config["TESTING"] = True

    with app.test_client() as c:
        resp = c.post(
            "/login", data={"username": "admin", "password": TEST_PASSWORD}
        )
        assert resp.status_code == 302, "测试夹具登录失败"
        yield c

    try:
        os.remove(tmp)
    except OSError:
        pass


def _get(client, query=""):
    resp = client.get("/audit_log" + query)
    return resp, resp.data.decode("utf-8")


def _present(html, *actions):
    return [a for a in actions if a in html]


def test_page_renders_with_all_rows(client):
    resp, html = _get(client)
    assert resp.status_code == 200
    assert _present(html, *ALL_ACTIONS) == ALL_ACTIONS
    # 三个筛选项都在顶部表单里
    for name in ('name="user"', 'name="start_date"', 'name="end_date"',
                 'name="target_type"'):
        assert name in html
    assert 'href="/audit_log"' in html, "重置按钮应指向无参数的审计日志页"


def test_no_filter_shows_empty_state_when_no_rows(client, monkeypatch):
    """空表时页面仍可渲染，不能因为筛选项变空而报错。"""
    import database as dbmod

    conn = dbmod.get_db()
    conn.cursor().execute("DELETE FROM audit_logs")
    conn.commit()
    conn.close()

    resp, html = _get(client)
    assert resp.status_code == 200
    assert "暂无日志" in html
    assert "全部类型" in html


def test_filter_by_user_is_fuzzy(client):
    resp, html = _get(client, "?user=ali")
    assert resp.status_code == 200
    assert _present(html, "ACTION-A1", "ACTION-A2") == ["ACTION-A1", "ACTION-A2"]
    assert not _present(html, "ACTION-B1", "ACTION-B2", "ACTION-C1")
    assert 'value="ali"' in html, "筛选条件要回显"


def test_filter_by_target_type(client):
    resp, html = _get(client, "?target_type=device")
    assert resp.status_code == 200
    assert _present(html, "ACTION-A1", "ACTION-B1") == ["ACTION-A1", "ACTION-B1"]
    assert not _present(html, "ACTION-A2", "ACTION-B2", "ACTION-C1")
    assert 'value="device" selected' in html


def test_unknown_target_type_is_ignored(client):
    resp, html = _get(client, "?target_type=not_exist")
    assert resp.status_code == 200
    assert _present(html, *ALL_ACTIONS) == ALL_ACTIONS


def test_target_type_options_come_from_all_rows(client):
    """筛到某个类型后，下拉里其它类型不能消失。"""
    _, html = _get(client, "?target_type=device")
    for value in ("device", "document", "user"):
        assert f'value="{value}"' in html


def test_filter_by_date_range(client):
    resp, html = _get(client, "?start_date=2026-10-05&end_date=2026-10-15")
    assert resp.status_code == 200
    assert _present(html, "ACTION-A2", "ACTION-B1", "ACTION-B2") == [
        "ACTION-A2", "ACTION-B1", "ACTION-B2"
    ]
    assert not _present(html, "ACTION-A1", "ACTION-C1")
    assert 'value="2026-10-05"' in html
    assert 'value="2026-10-15"' in html


def test_single_sided_date(client):
    _, html = _get(client, "?start_date=2026-10-15")
    assert _present(html, "ACTION-B2", "ACTION-C1") == ["ACTION-B2", "ACTION-C1"]
    assert not _present(html, "ACTION-A1", "ACTION-A2", "ACTION-B1")

    _, html = _get(client, "?end_date=2026-10-05")
    assert _present(html, "ACTION-A1", "ACTION-A2") == ["ACTION-A1", "ACTION-A2"]
    assert not _present(html, "ACTION-B1", "ACTION-B2", "ACTION-C1")


def test_combined_filters(client):
    resp, html = _get(
        client,
        "?user=bob&target_type=device"
        "&start_date=2026-10-01&end_date=2026-10-12",
    )
    assert resp.status_code == 200
    assert _present(html, "ACTION-B1") == ["ACTION-B1"]
    assert not _present(html, "ACTION-A1", "ACTION-A2", "ACTION-B2", "ACTION-C1")


def test_combined_filters_can_return_zero_rows(client):
    resp, html = _get(client, "?user=alice&target_type=user")
    assert resp.status_code == 200
    assert "暂无日志" in html


def test_invalid_dates_are_ignored(client):
    resp, html = _get(client, "?start_date=not-a-date&end_date=2026-99-99")
    assert resp.status_code == 200
    assert _present(html, *ALL_ACTIONS) == ALL_ACTIONS
    assert 'name="start_date"\n                   value=""' in html
    assert 'name="end_date"\n                   value=""' in html


def test_sql_injection_in_user_is_bound_not_executed(client):
    resp, html = _get(client, "?user=%27%20OR%201%3D1%20--")
    assert resp.status_code == 200
    assert "暂无日志" in html, "注入串不应匹配到任何日志"
    assert not _present(html, *ALL_ACTIONS)


def test_user_input_is_html_escaped(client):
    resp, html = _get(client, "?user=%3Cscript%3Ealert(1)%3C%2Fscript%3E")
    assert resp.status_code == 200
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_result_count_is_shown(client):
    """登录动作自身也会写一条审计日志，所以条数按库里实际行数断言，不写死。"""
    import database as dbmod

    conn = dbmod.get_db()
    total = conn.cursor().execute(
        "SELECT COUNT(*) AS c FROM audit_logs"
    ).fetchone()["c"]
    conn.close()

    _, html = _get(client)
    assert f"共 {total} 条" in html


def test_non_admin_cannot_access(client):
    """筛选改造不能绕过原有的管理员限制。"""
    import database as dbmod

    conn = dbmod.get_db()
    conn.cursor().execute(
        "INSERT INTO users (username, password, role) VALUES (%s, %s, %s)",
        ("staff", generate_password_hash(TEST_PASSWORD), "equipment_engineer"),
    )
    conn.commit()
    conn.close()

    from app import create_app

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        c.post("/login", data={"username": "staff", "password": TEST_PASSWORD})
        resp = c.get("/audit_log?user=alice")
        assert resp.status_code == 302
