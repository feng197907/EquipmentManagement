#!/usr/bin/env bash
# 一键发布：拉代码 -> 重建镜像 -> 替换容器 -> 等健康检查通过
#
#   ./deploy/compose-deploy.sh
#
# 服务器上 ./deploy/compose-deploy.sh 也是同一套流程。
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
    echo "缺少 .env。先执行：cp .env.example .env 并填入真实值" >&2
    exit 1
fi

echo "== 1/4 拉取最新代码 =="
# 部署目录只做部署，不留本地改动，所以直接 reset 到远端。
# 用 reset 而不是 pull，是因为历史上服务器和本地产生过同内容不同 hash 的提交，
# pull 会因为分叉报错。
git fetch origin
git reset --hard origin/main
echo "   当前版本：$(git log --oneline -1)"

echo "== 2/4 构建镜像 =="
docker compose build

echo "== 3/4 替换容器 =="
docker compose up -d

echo "== 4/4 等待健康检查 =="
for i in $(seq 1 30); do
    st=$(docker inspect --format '{{.State.Health.Status}}' dms-app 2>/dev/null || echo missing)
    echo "   [$i] $st"
    if [ "$st" = "healthy" ]; then
        echo "发布完成。外部验证：curl -s -o /dev/null -w '%{http_code}\\n' http://127.0.0.1:5000/healthz"
        exit 0
    fi
    sleep 2
done

echo "健康检查未通过，排查：" >&2
echo "  docker compose logs --tail 100 app" >&2
echo "  docker compose ps" >&2
exit 1
