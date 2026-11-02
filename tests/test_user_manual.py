"""用户手册页面（/user-manual）的回归测试。

背景：这个路由在运行时读 docs/使用手册.md 做 markdown 渲染。
这个文件一度被 .dockerignore 整体排掉（镜像里有 docs 这一行），
容器里读不到就抛 FileNotFoundError，被全局异常处理器接住后，
用户打开的页面只剩一句 JSON：{"error": "发生未知错误"}。

下面两个测试分别守住两件事：
1. 页面能真的渲染出 markdown 内容，且不会退化成 JSON 报错；
2. 手册文件不会被 .dockerignore 排除在镜像之外（否则线上必挂）。
"""
import os
import tempfile
from pathlib import Path

import pytest

from database import init_db

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MANUAL_REL_PATH = "docs/使用手册.md"


def _dockerignore_excludes(rel_path):
    """按 .dockerignore 的规则粗略判断某个相对路径会不会被打包排除。

    只覆盖这个仓库实际用到的两类写法：目录级排除（docs）和 ! 反向例外。
    glob 通配（*.md 这种）按 Docker 的语义不跨目录，所以不参与判断。
    """
    ignored = False
    for raw in (PROJECT_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        negate = line.startswith("!")
        pattern = (line[1:] if negate else line).rstrip("/")
        if rel_path == pattern or rel_path.startswith(pattern + "/"):
            ignored = not negate
    return ignored


@pytest.fixture()
def client(monkeypatch):
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    import database as dbmod

    monkeypatch.setattr(dbmod, "DB_PATH", tmp)
    init_db()

    from app import create_app

    app = create_app()
    app.config["TESTING"] = True
    app.config["LOGIN_DISABLED"] = True

    with app.test_client() as c:
        yield c

    try:
        os.remove(tmp)
    except OSError:
        pass


def test_manual_source_exists():
    """手册源文件必须在仓库里，路径要和 dashboard.py 读的一致。"""
    assert (PROJECT_ROOT / MANUAL_REL_PATH).is_file()


def test_manual_source_ships_into_image():
    """.dockerignore 不能把手册排掉——排掉线上就是 JSON 报错。"""
    assert not _dockerignore_excludes(MANUAL_REL_PATH), (
        f"{MANUAL_REL_PATH} 被 .dockerignore 排除了，"
        "/user-manual 在容器里会读不到文件而报错"
    )


def test_user_manual_page_renders_markdown(client):
    """页面应返回 200 并渲染出 markdown 标题，而不是 JSON 报错。"""
    rv = client.get("/user-manual")
    assert rv.status_code == 200

    html = rv.data.decode("utf-8")
    assert "<h1" in html, "markdown 没有被渲染成 HTML"
    assert "使用手册" in html
    assert "发生未知错误" not in html, "页面退化成了全局异常处理器的 JSON 报错"


def test_user_manual_degrades_gracefully(client, monkeypatch):
    """手册文件缺失时应给可读提示，而不是抛异常变成 JSON。"""
    import blueprints.dashboard as dashboard_bp

    monkeypatch.setattr(
        dashboard_bp, "MANUAL_REL_PATH", Path("docs") / "__不存在的文件__.md"
    )
    monkeypatch.setattr(dashboard_bp, "_manual_cache", {"mtime": None, "html": None})

    rv = client.get("/user-manual")
    assert rv.status_code == 200

    html = rv.data.decode("utf-8")
    assert "手册暂时无法显示" in html
    assert "发生未知错误" not in html
