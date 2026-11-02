#!/usr/bin/env bash
# 一键发布：拉代码 -> 重建镜像 -> 替换容器 -> 等健康检查通过
#
#   ./deploy/compose-deploy.sh               正常发布（先拉 GitHub）
#   ./deploy/compose-deploy.sh --skip-fetch  跳过拉取，只重建镜像（GitHub 连不上时用）
#
# 详细说明见 docs/上线操作手册.md
set -euo pipefail
cd "$(dirname "$0")/.."

SKIP_FETCH=0
for arg in "$@"; do
    case "$arg" in
        --skip-fetch) SKIP_FETCH=1 ;;
        -h|--help)
            # 打印文件头部的注释块（跳过 shebang，遇到第一行非注释即停）
            awk 'NR>1 { if ($0 ~ /^#/) { sub(/^# ?/, ""); print } else { exit } }' "$0"
            exit 0
            ;;
        *)
            echo "未知参数：$arg（可用：--skip-fetch, --help）" >&2
            exit 2
            ;;
    esac
done

if [ ! -f .env ]; then
    echo "缺少 .env。先执行：cp .env.example .env 并填入真实值" >&2
    exit 1
fi

if [ "$SKIP_FETCH" = "1" ]; then
    echo "== 1/4 跳过拉取（--skip-fetch），直接使用当前目录里的代码 =="
    echo "   当前版本：$(git log --oneline -1)"
else
    echo "== 1/4 拉取最新代码 =="
    # 部署目录只做部署，不留本地改动，所以直接 reset 到远端。
    # 用 reset 而不是 pull，是因为历史上服务器和本地产生过同内容不同 hash 的提交，
    # pull 会因为分叉报错。
    fetched=0
    for attempt in 1 2 3; do
        if git fetch origin; then
            fetched=1
            break
        fi
        echo "   第 ${attempt} 次拉取失败，3 秒后重试..." >&2
        sleep 3
    done

    if [ "$fetched" != "1" ]; then
        cat >&2 <<'EOF'

!! 三次都没连上 GitHub，没有改动任何代码。

   服务器到 github.com 的 443 有时会被阻断。两条路：

   路一（推荐）：本地打增量包传上来
     本地：  git bundle create /tmp/dms.bundle <线上当前版本>..main
     上传：  用你惯用的方式把 /tmp/dms.bundle 放到服务器 /tmp/
     服务器：git fetch /tmp/dms.bundle main && git merge --ff-only FETCH_HEAD
             git update-ref refs/remotes/origin/main "$(git rev-parse HEAD)"
             然后重新执行 ./deploy/compose-deploy.sh --skip-fetch

   路二：确认代码已经是想发布的版本，直接
     ./deploy/compose-deploy.sh --skip-fetch

EOF
        exit 1
    fi

    git reset --hard origin/main
    echo "   当前版本：$(git log --oneline -1)"
fi

echo "== 2/4 构建镜像 =="
docker compose build

echo "== 3/4 替换容器 =="
docker compose up -d

echo "== 4/4 等待健康检查（通常 30~60 秒）=="
for i in $(seq 1 40); do
    st=$(docker inspect --format '{{.State.Health.Status}}' dms-app 2>/dev/null || echo missing)
    echo "   [$i] $st"
    if [ "$st" = "healthy" ]; then
        echo
        echo "发布完成。"
        echo "  应用探针：$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:5000/healthz || echo '无响应')"
        echo "  对外访问：$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/login || echo '无响应')"
        echo "  想再确认一遍：./deploy/status.sh"
        exit 0
    fi
    sleep 2
done

echo
echo "健康检查未通过。排查顺序：" >&2
echo "  1) docker compose logs --tail 100 app     # 看应用报错" >&2
echo "  2) docker compose ps                      # 看容器状态" >&2
echo "  3) 回滚见 docs/上线操作手册.md 的「回滚」一节" >&2
exit 1
