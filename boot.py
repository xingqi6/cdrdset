import os
import subprocess
import time
import signal
import sys
import re
import json
import urllib.request
from datetime import datetime

# === 1. 环境变量 ===
WEBDAV_URL = os.environ.get("WEBDAV_URL", "").rstrip('/')
WEBDAV_USER = os.environ.get("WEBDAV_USERNAME")
WEBDAV_PASS = os.environ.get("WEBDAV_PASSWORD")
BACKUP_PATH = os.environ.get("WEBDAV_BACKUP_PATH", "backup_data").strip('/')
SYNC_INTERVAL = int(os.environ.get("SYNC_INTERVAL", 600)) 
SYS_TOKEN = os.environ.get("SYS_TOKEN", "123456") 

# === 2. 路径定义 ===
CORE_DIR = "/usr/local/sys_kernel"
ALIST_BIN = f"{CORE_DIR}/io_driver"
CLOUD_BIN = f"{CORE_DIR}/net_service"
ALIST_DB_LOCAL = f"{CORE_DIR}/data/data.db"
CLOUD_DB_LOCAL = f"{CORE_DIR}/sys.db"
PREFIX_ALIST = "sys_io_snap_"
PREFIX_CLOUD = "sys_net_snap_"

p_nginx = None
p_alist = None
p_cloud = None

# === 3. 智能 DNS 穿透 (核心修复代码) ===
def resolve_ip_doh(domain):
    """通过 Google DoH 获取域名的真实 A 记录"""
    print(f">>> [Kernel] Resolving {domain} via Google DoH...")
    try:
        # 使用 Google Public DNS over HTTPS
        url = f"https://dns.google/resolve?name={domain}&type=A"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            if "Answer" in data:
                for answer in data["Answer"]:
                    if answer["type"] == 1: # A record
                        return answer["data"]
    except Exception as e:
        print(f">>> [Kernel] DoH Lookup Failed for {domain}: {e}")
    return None

def patch_network_smart():
    print(">>> [Kernel] Initializing network patch...")
    
    # 我们需要修复两个域名，防止 S3 链接不上
    targets = ["s3.huggingface.co", "huggingface.co"]
    
    # 优先使用 hosts 文件解析
    try:
        with open("/etc/nsswitch.conf", "w") as f:
            f.write("hosts: files dns\nnetworks: files\n")
    except: pass

    resolved_map = {}
    
    # 1. 动态获取 IP
    for domain in targets:
        ip = resolve_ip_doh(domain)
        if ip:
            resolved_map[domain] = ip
            print(f">>> [Kernel] Got IP for {domain}: {ip}")
        else:
            # 获取失败时的保底 IP (AWS US-East-1)
            print(f">>> [Kernel] Failed to resolve {domain}, using fallback.")
            resolved_map[domain] = "18.172.170.60" 

    # 2. 写入 /etc/hosts
    try:
        with open("/etc/hosts", "a") as f:
            f.write("\n# Smart DoH Patch\n")
            for domain, ip in resolved_map.items():
                f.write(f"{ip} {domain}\n")
        
        # 打印出来确认
        # with open("/etc/hosts", "r") as f: print(f.read())
        print(">>> [Kernel] Network patch applied.")
            
    except Exception as e:
        print(f">>> [Kernel] Host write error: {e}")

# === 4. 基础工具函数 ===
def run_cmd(cmd):
    try:
        subprocess.run(cmd, shell=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except: return False

def set_secret():
    """强制设置 Alist 密码"""
    try:
        subprocess.run([ALIST_BIN, "admin", "set", SYS_TOKEN], cwd=CORE_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except: pass

# === 5. 备份逻辑 (WebDAV) ===
def get_remote_url(filename=""):
    return f"{WEBDAV_URL}/{BACKUP_PATH}/{filename}"

def ensure_remote_dir():
    if not WEBDAV_URL: return
    url = f"{WEBDAV_URL}/{BACKUP_PATH}/"
    cmd = f"curl -X MKCOL -u '{WEBDAV_USER}:{WEBDAV_PASS}' '{url}' --silent --insecure"
    subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def list_remote_files():
    if not WEBDAV_URL: return []
    url = f"{WEBDAV_URL}/{BACKUP_PATH}/"
    cmd = ["curl", "-X", "PROPFIND", "-u", f"{WEBDAV_USER}:{WEBDAV_PASS}", url, "--header", "Depth: 1", "--silent", "--insecure"]
    try:
        output = subprocess.check_output(cmd).decode('utf-8')
        matches = re.findall(r'<[a-zA-Z0-9:]*href>([^<]+)</[a-zA-Z0-9:]*href>', output, re.IGNORECASE)
        filenames = []
        for m in matches:
            decoded_name = m.rstrip('/').split('/')[-1]
            if decoded_name: filenames.append(decoded_name)
        return filenames
    except Exception: return []

def cleanup_old_backups(prefix):
    files = list_remote_files()
    target_files = sorted([f for f in files if f.startswith(prefix)])
    if len(target_files) > 5:
        for f in target_files[:-5]:
            run_cmd(f"curl -X DELETE -u '{WEBDAV_USER}:{WEBDAV_PASS}' '{get_remote_url(f)}' --silent --insecure")

def do_backup():
    if not WEBDAV_URL: return
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if os.path.exists(ALIST_DB_LOCAL):
        alist_name = f"{PREFIX_ALIST}{timestamp}.db"
        run_cmd(f"curl -u '{WEBDAV_USER}:{WEBDAV_PASS}' -T '{ALIST_DB_LOCAL}' '{get_remote_url(alist_name)}' --silent --insecure")
        cleanup_old_backups(PREFIX_ALIST)
    if os.path.exists(CLOUD_DB_LOCAL):
        cloud_name = f"{PREFIX_CLOUD}{timestamp}.db"
        run_cmd(f"curl -u '{WEBDAV_USER}:{WEBDAV_PASS}' -T '{CLOUD_DB_LOCAL}' '{get_remote_url(cloud_name)}' --silent --insecure")
        cleanup_old_backups(PREFIX_CLOUD)

def restore_latest():
    if not WEBDAV_URL: return
    ensure_remote_dir()
    files = list_remote_files()
    alist_backups = sorted([f for f in files if f.startswith(PREFIX_ALIST)])
    if alist_backups:
        run_cmd(f"curl -u '{WEBDAV_USER}:{WEBDAV_PASS}' '{get_remote_url(alist_backups[-1])}' -o '{ALIST_DB_LOCAL}' --silent --insecure")
    cloud_backups = sorted([f for f in files if f.startswith(PREFIX_CLOUD)])
    if cloud_backups:
        run_cmd(f"curl -u '{WEBDAV_USER}:{WEBDAV_PASS}' '{get_remote_url(cloud_backups[-1])}' -o '{CLOUD_DB_LOCAL}' --silent --insecure")

# === 6. 启动流程 ===
def start_services():
    global p_nginx, p_alist, p_cloud
    
    # 1. 优先执行网络修复
    patch_network_smart()
    
    os.makedirs(f"{CORE_DIR}/data", exist_ok=True)
    
    # 2. 启动 Alist
    p_alist = subprocess.Popen([ALIST_BIN, "server", "--no-prefix"], cwd=CORE_DIR)
    
    # 3. 设置密码
    time.sleep(5)
    set_secret() 
    
    # 4. 启动 Cloudreve
    p_cloud = subprocess.Popen([CLOUD_BIN, "-c", "conf.ini"], cwd=CORE_DIR)
    
    # 5. 启动 Nginx
    print(">>> [Kernel] System Online.")
    p_nginx = subprocess.Popen(["nginx", "-g", "daemon off;"])

def stop_handler(signum, frame):
    if p_nginx: p_nginx.terminate()
    if p_cloud: p_cloud.terminate()
    if p_alist: p_alist.terminate()
    do_backup()
    sys.exit(0)

if __name__ == "__main__":
    restore_latest()
    start_services()
    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)
    step = 0
    while True:
        time.sleep(1)
        step += 1
        if step >= SYNC_INTERVAL:
            do_backup()
            step = 0
