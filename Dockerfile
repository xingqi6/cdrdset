# 基础镜像
FROM python:3.9-slim

# === 1. 基础环境 (新增 ca-certificates) ===
RUN apt-get update && apt-get install -y \
    nginx \
    curl \
    wget \
    procps \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# === 2. 隐蔽目录 ===
WORKDIR /usr/local/sys_kernel

# === 3. 下载并伪装二进制文件 ===
# Alist -> io_driver
RUN wget https://github.com/alist-org/alist/releases/download/v3.35.0/alist-linux-amd64.tar.gz \
    && tar -zxvf alist-linux-amd64.tar.gz \
    && mv alist io_driver \
    && rm alist-linux-amd64.tar.gz

# Cloudreve -> net_service
RUN wget https://github.com/cloudreve/cloudreve/releases/download/3.8.3/cloudreve_3.8.3_linux_amd64.tar.gz \
    && tar -zxvf cloudreve_3.8.3_linux_amd64.tar.gz \
    && mv cloudreve net_service \
    && rm cloudreve_3.8.3_linux_amd64.tar.gz

# 赋予权限
RUN chmod +x io_driver net_service

# === 4. 植入配置文件 ===
COPY fake_site /var/www/html
COPY nginx.conf /etc/nginx/sites-available/default
COPY conf.ini /usr/local/sys_kernel/conf.ini
COPY boot.py /usr/local/sys_kernel/boot.py

# === 5. 权限与端口 ===
RUN mkdir -p /usr/local/sys_kernel/data
EXPOSE 7860

# === 6. 启动 ===
CMD ["python3", "-u", "/usr/local/sys_kernel/boot.py"]
