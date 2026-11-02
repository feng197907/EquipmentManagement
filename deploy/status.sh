#!/usr/bin/env bash
# 上线状态自检：只读，不改任何东西。发布完跑一遍，一眼看到底上没上。
#
#   ./deploy/status.sh
set -uo pipefail
cd "$(dirname "$0")/.."

echo "===== 1. 服务器上的代码版本 ====="
git log --oneline -1
dirty=$(git status --porcelain | wc -l | tr -d ' ')
if [ "$dirty" = "0" ]; then
    echo "   工作区干净"
else
    echo "   ⚠ 有 $dirty 个未提交改动（部署目录不该有本地改动）"
fi

echo
echo "===== 2. 容器状态 ====="
docker compose ps 2>/dev/null || echo "   docker compose 不可用"

echo
echo "===== 3. 容器健康 ====="
health=$(docker inspect --format '{{.State.Health.Status}}' dms-app 2>/dev/null)
if [ -z "$health" ]; then
    echo "   ✗ 容器 dms-app 不存在"
else
    echo "   $health"
    echo "   启动于：$(docker inspect --format '{{.State.StartedAt}}' dms-app 2>/dev/null)"
fi

echo
echo "===== 4. 应用探针（容器内 5000 端口）====="
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:5000/healthz 2>/dev/null)
echo "   /healthz -> ${code:-无响应}   （期望 200）"

echo
echo "===== 5. 对外访问（经 nginx 80 端口）====="
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1/login 2>/dev/null)
echo "   /login   -> ${code:-无响应}   （期望 200）"

echo
echo "===== 6. 静态资源版本号（浏览器缓存开关）====="
ver=$(curl -s --max-time 5 http://127.0.0.1/login 2>/dev/null | grep -o 'v=[0-9]*' | sort -u | tr '\n' ' ')
echo "   ${ver:-未取到}"
echo "   改了 CSS/JS 却没提这个号，用户会继续看旧样式"

echo
echo "===== 7. 镜像 ====="
docker images equipment-management:latest --format '   {{.Repository}}:{{.Tag}}  构建于 {{.CreatedSince}}   {{.Size}}' 2>/dev/null

echo
echo "===== 8. 磁盘（低于 2G 该清理了）====="
df -h / | awk 'NR==2 {print "   根分区已用 " $5 "，剩余 " $4}'
