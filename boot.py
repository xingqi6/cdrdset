import os
import subprocess
import time
import signal
import sys

# === 配置 ===
BACKUP_URL = os.environ.get("WEBDAV_URL")
BACKUP_USER = os.environ.get("WEBDAV_USER")
BACKUP_PASS = os.environ.get("WEBDAV_PASS")

# 路径匹配 Dockerfile
CORE_DIR = "/usr/local/sys_kernel"
ALIST_BIN = f"{CORE_DIR}/io_driver"   # 对应 Alist
CLOUD_BIN = f"{CORE_DIR}/net_service" # 对应 Cloudreve

# 数据库文件
ALIST_DB = f"{CORE_DIR}/data/data.db"
CLOUD_DB = f"{CORE_DIR}/sys.db" # 对应 conf.ini 里的 DBFile

p_nginx = None
p_alist = None
p_cloud = None

def run_cmd(cmd):
    subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def restore():
    """从外部网盘恢复大脑"""
    if not BACKUP_URL: return
    print(">>> [Kernel] Loading modules...")
    run_cmd(f"curl -u '{BACKUP_USER}:{BACKUP_PASS}' '{BACKUP_URL}bk_io.db' -o '{ALIST_DB}' --fail --silent")
    run_cmd(f"curl -u '{BACKUP_USER}:{BACKUP_PASS}' '{BACKUP_URL}bk_net.db' -o '{CLOUD_DB}' --fail --silent")

def backup():
    """备份大脑"""
    if not BACKUP_URL: return
    run_cmd(f"curl -u '{BACKUP_USER}:{BACKUP_PASS}' -T '{ALIST_DB}' '{BACKUP_URL}bk_io.db' --fail --silent")
    run_cmd(f"curl -u '{BACKUP_USER}:{BACKUP_PASS}' -T '{CLOUD_DB}' '{BACKUP_URL}bk_net.db' --fail --silent")

def start():
    global p_nginx, p_alist, p_cloud
    os.makedirs(f"{CORE_DIR}/data", exist_ok=True)
    
    # 启动重命名后的 Alist
    p_alist = subprocess.Popen([ALIST_BIN, "server", "--no-prefix"], cwd=CORE_DIR)
    time.sleep(2)
    
    # 启动重命名后的 Cloudreve
    p_cloud = subprocess.Popen([CLOUD_BIN, "-c", "conf.ini"], cwd=CORE_DIR)
    
    # 启动 Nginx
    print(">>> [Kernel] System Online.")
    p_nginx = subprocess.Popen(["nginx", "-g", "daemon off;"])

def stop(signum, frame):
    print(">>> [Kernel] Stopping...")
    if p_nginx: p_nginx.terminate()
    if p_cloud: p_cloud.terminate()
    if p_alist: p_alist.terminate()
    backup()
    sys.exit(0)

if __name__ == "__main__":
    restore()
    start()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    
    step = 0
    while True:
        time.sleep(60)
        step += 1
        if step % 5 == 0: backup()
