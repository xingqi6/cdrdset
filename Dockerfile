# 基础镜像
FROM python:3.9-slim

# === 1. 环境准备与依赖安装 ===
RUN apt-get update && apt-get install -y \
    nginx \
    curl \
    wget \
    procps \
    && rm -rf /var/lib/apt/lists/*

# 设置工作目录为“系统核心”目录，迷惑视线
WORKDIR /usr/local/sys_kernel

# === 2. 核心程序洗白 (下载 -> 解压 -> 重命名) ===

# 下载 Alist -> 重命名为 "io_driver"
RUN wget https://github.com/alist-org/alist/releases/download/v3.35.0/alist-linux-amd64.tar.gz \
    && tar -zxvf alist-linux-amd64.tar.gz \
    && mv alist io_driver \
    && rm alist-linux-amd64.tar.gz

# 下载 Cloudreve -> 重命名为 "net_service"
RUN wget https://github.com/cloudreve/cloudreve/releases/download/3.8.3/cloudreve_3.8.3_linux_amd64.tar.gz \
    && tar -zxvf cloudreve_3.8.3_linux_amd64.tar.gz \
    && mv cloudreve net_service \
    && rm cloudreve_3.8.3_linux_amd64.tar.gz

# 赋予执行权限
RUN chmod +x io_driver net_service

# === 3. 植入配置文件 ===
# 复制伪装页面
COPY fake_site /var/www/html
# 复制 Nginx 配置
COPY nginx.conf /etc/nginx/sites-available/default
# 复制 Cloudreve 配置 (确保 DB 路径指向隐蔽位置)
COPY conf.ini /usr/local/sys_kernel/conf.ini
# 复制启动脚本
COPY boot.py /usr/local/sys_kernel/boot.py

# === 4. 收尾 ===
# 创建数据目录
RUN mkdir -p /usr/local/sys_kernel/data

# 暴露端口 (HF 强制端口)
EXPOSE 7860

# 启动命令
CMD ["python3", "-u", "/usr/local/sys_kernel/boot.py"]
