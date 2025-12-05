# 基础镜像
FROM python:3.9-slim

# ===========================
# 1. 安装系统依赖
# ===========================
RUN apt-get update && apt-get install -y \
    nginx \
    curl \
    wget \
    procps \
    ca-certificates \
    sqlite3 \
    git \
    git-lfs \
    && rm -rf /var/lib/apt/lists/*

# 初始化 Git LFS
RUN git lfs install --system

# ===========================
# 2. 设置工作目录
# ===========================
WORKDIR /usr/local/sys_kernel

# ===========================
# 3. 下载 Alist
# ===========================
RUN wget https://github.com/alist-org/alist/releases/download/v3.35.0/alist-linux-amd64.tar.gz \
    && tar -zxvf alist-linux-amd64.tar.gz \
    && mv alist io_driver \
    && rm alist-linux-amd64.tar.gz \
    && chmod +x io_driver

# ===========================
# 4. 下载 Cloudreve
# ===========================
RUN wget https://github.com/cloudreve/cloudreve/releases/download/3.8.3/cloudreve_3.8.3_linux_amd64.tar.gz \
    && tar -zxvf cloudreve_3.8.3_linux_amd64.tar.gz \
    && mv cloudreve net_service \
    && rm cloudreve_3.8.3_linux_amd64.tar.gz \
    && chmod +x net_service

# ===========================
# 5. 复制配置文件
# ===========================
COPY fake_site /var/www/html
COPY nginx.conf /etc/nginx/sites-available/default
COPY boot.py /usr/local/sys_kernel/boot.py

# ===========================
# 6. 创建必要目录
# ===========================
RUN mkdir -p /usr/local/sys_kernel/data \
    && mkdir -p /usr/local/sys_kernel/datasets_meta \
    && mkdir -p /tmp/datasets_cache

# ===========================
# 7. 配置 Git（避免权限问题）
# ===========================
RUN git config --global user.email "storage@hf.space" \
    && git config --global user.name "HF Storage" \
    && git config --global safe.directory '*'

# ===========================
# 8. 暴露端口
# ===========================
EXPOSE 7860

# ===========================
# 9. 健康检查
# ===========================
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:7860/health || exit 1

# ===========================
# 10. 启动脚本
# ===========================
CMD ["python3", "-u", "/usr/local/sys_kernel/boot.py"]
