# syntax=docker/dockerfile:1.7
#
# DMS 运行时镜像：只跑 gunicorn，不装 nginx / 数据库。
# 生产拓扑（阿里云 101.201.48.64）：
#   宿主机 nginx (443/80) -> 127.0.0.1:5000（本容器, network_mode: host）
#                        -> 127.0.0.1:3306（宿主机 MariaDB）
#
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=5 \
    GUNICORN_BIND=127.0.0.1:5000 \
    GUNICORN_WORKERS=2

WORKDIR /app

# 时区数据。python:3.11-slim 默认没装 tzdata，缺了它 glibc 会退回 UTC，
# datetime.now() 写进审计日志的时间会整体偏移 8 小时——GMP 追溯不能这么错。
RUN set -eux; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources; \
    fi; \
    if [ -f /etc/apt/sources.list ]; then \
        sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list; \
    fi; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends tzdata; \
    ln -snf /usr/share/zoneinfo/$TZ /etc/localtime; \
    echo $TZ > /etc/timezone; \
    rm -rf /var/lib/apt/lists/*

# 依赖单独一层，改代码不会触发重装。三个源轮着试，阿里云机器上通常第一个就命中。
COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    set -eux; \
    for index_url in \
        https://pypi.tuna.tsinghua.edu.cn/simple \
        https://mirrors.aliyun.com/pypi/simple/ \
        https://pypi.org/simple \
    ; do \
        echo "Trying pip index: ${index_url}"; \
        if pip install --retries "${PIP_RETRIES}" --default-timeout "${PIP_DEFAULT_TIMEOUT}" --index-url "${index_url}" -r requirements.txt; then \
            exit 0; \
        fi; \
    done; \
    echo "pip install failed on all configured indexes"; \
    exit 1

COPY . .

RUN mkdir -p uploads logs

EXPOSE 5000

# 探针打的是应用自己的 /healthz（会真的查一次数据库），不是只看进程活着
HEALTHCHECK --interval=30s --timeout=10s --start-period=25s --retries=3 \
    CMD python -c "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/healthz',timeout=5).status==200 else 1)"

# 绑 127.0.0.1 而不是 0.0.0.0：对外只应该有 nginx，5000 不直接暴露
CMD ["sh", "-c", "exec gunicorn --bind ${GUNICORN_BIND} --workers ${GUNICORN_WORKERS} --timeout 120 --access-logfile - --error-logfile - 'app:create_app()'"]
