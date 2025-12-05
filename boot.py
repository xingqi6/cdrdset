import os
import subprocess
import time
import signal
import sys
import re
from datetime import datetime

# === 1. 环境变量配置 ===
WEBDAV_URL = os.environ.get("WEBDAV_URL", "").rstrip('/')
WEBDAV_USER = os.environ.get("WEBDAV_USERNAME")
WEBDAV_PASS = os.environ.get("WEBDAV_PASSWORD")
BACKUP_PATH = os.environ.get("WEBDAV_BACKUP_PATH", "backup_data").strip('/')
# 默认 600秒 (10分钟)
SYNC_INTERVAL = int(os.environ.get("SYNC_INTERVAL", 600)) 

# === 2. 隐蔽路径定义 (本地) ===
CORE_DIR = "/usr/local/sys_kernel"
ALIST_BIN = f"{CORE_DIR}/io_driver"
CLOUD_BIN = f"{CORE_DIR}/net_service"

# 本地数据库路径
ALIST_DB_LOCAL = f"{CORE_DIR}/data/data.db"
CLOUD_DB_LOCAL = f"{CORE_DIR}/sys.db"

# 远程文件前缀 (用于识别)
PREFIX_ALIST = "sys_io_snap_"
PREFIX_CLOUD = "sys_net_snap_"

# 全局进程
p_nginx = None
p_alist = None
p_cloud = None

# === 3. 工具函数 ===

def run_cmd(cmd):
    """静默执行命令"""
    try:
        subprocess.run(cmd, shell=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False

def get_remote_url(filename=""):
    """拼接完整的 WebDAV URL"""
    # 最终格式: https://dav.com/backup_path/filename
    return f"{WEBDAV_URL}/{BACKUP_PATH}/{filename}"

def ensure_remote_dir():
    """确保远程备份文件夹存在"""
    if not WEBDAV_URL: return
    url = f"{WEBDAV_URL}/{BACKUP_PATH}/" # MKCOL 需要尾部斜杠通常比较稳妥
    # 发送 MKCOL 请求创建目录
    cmd = f"curl -X MKCOL -u '{WEBDAV_USER}:{WEBDAV_PASS}' '{url}' --silent --insecure"
    subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def list_remote_files():
    """列出远程目录下的文件，返回文件名列表"""
    if not WEBDAV_URL: return []
    url = f"{WEBDAV_URL}/{BACKUP_PATH}/"
    
    # 使用 curl 获取目录列表 XML
    cmd = [
        "curl", "-X", "PROPFIND", 
        "-u", f"{WEBDAV_USER}:{WEBDAV_PASS}", 
        url, "--header", "Depth: 1", "--silent", "--insecure"
    ]
    try:
        output = subprocess.check_output(cmd).decode('utf-8')
        # 使用简单的正则提取 href (这比引入 XML 解析库更隐蔽)
        # 匹配 <d:href>/path/to/file</d:href> 或 <D:href>
        matches = re.findall(r'<[a-zA-Z0-9:]*href>([^<]+)</[a-zA-Z0-9:]*href>', output, re.IGNORECASE)
        
        # 清洗路径，只保留文件名
        filenames = []
        for m in matches:
            decoded_name = m.rstrip('/').split('/')[-1]
            if decoded_name:
                filenames.append(decoded_name)
        return filenames
    except Exception as e:
        print(f">>> [Kernel] List error: {e}")
        return []

def cleanup_old_backups(prefix):
    """保留最新的 5 份备份，删除旧的"""
    files = list_remote_files()
    # 筛选出属于当前前缀的备份文件
    target_files = [f for f in files if f.startswith(prefix)]
    
    # 按文件名排序 (因为文件名包含时间戳，所以 ASCII 排序等于时间排序)
    target_files.sort()
    
    # 如果超过 5 个
    if len(target_files) > 5:
        to_delete = target_files[:-5] # 取除了最后5个之外的所有文件
        print(f">>> [Kernel] Rotating logs... deleting {len(to_delete)} old files.")
        for f in to_delete:
            del_url = get_remote_url(f)
            run_cmd(f"curl -X DELETE -u '{WEBDAV_USER}:{WEBDAV_PASS}' '{del_url}' --silent --insecure")

def do_backup():
    """执行备份：上传新文件 -> 轮替旧文件"""
    if not WEBDAV_URL: return
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 1. 备份 Alist (io_driver)
    if os.path.exists(ALIST_DB_LOCAL):
        alist_name = f"{PREFIX_ALIST}{timestamp}.db"
        run_cmd(f"curl -u '{WEBDAV_USER}:{WEBDAV_PASS}' -T '{ALIST_DB_LOCAL}' '{get_remote_url(alist_name)}' --silent --insecure")
        cleanup_old_backups(PREFIX_ALIST)

    # 2. 备份 Cloudreve (net_service)
    if os.path.exists(CLOUD_DB_LOCAL):
        cloud_name = f"{PREFIX_CLOUD}{timestamp}.db"
        run_cmd(f"curl -u '{WEBDAV_USER}:{WEBDAV_PASS}' -T '{CLOUD_DB_LOCAL}' '{get_remote_url(cloud_name)}' --silent --insecure")
        cleanup_old_backups(PREFIX_CLOUD)

    print(f">>> [Kernel] Sync completed at {timestamp}")

def restore_latest():
    """启动时恢复最新的那一份"""
    if not WEBDAV_URL: return
    print(">>> [Kernel] Initializing environment...")
    
    # 确保远程目录存在 (如果第一次运行)
    ensure_remote_dir()
    
    files = list_remote_files()
    
    # 1. 恢复 Alist
    alist_backups = sorted([f for f in files if f.startswith(PREFIX_ALIST)])
    if alist_backups:
        latest = alist_backups[-1]
        print(f">>> [Kernel] Loading IO module: {latest}")
        run_cmd(f"curl -u '{WEBDAV_USER}:{WEBDAV_PASS}' '{get_remote_url(latest)}' -o '{ALIST_DB_LOCAL}' --silent --insecure")
    
    # 2. 恢复 Cloudreve
    cloud_backups = sorted([f for f in files if f.startswith(PREFIX_CLOUD)])
    if cloud_backups:
        latest = cloud_backups[-1]
        print(f">>> [Kernel] Loading Net module: {latest}")
        run_cmd(f"curl -u '{WEBDAV_USER}:{WEBDAV_PASS}' '{get_remote_url(latest)}' -o '{CLOUD_DB_LOCAL}' --silent --insecure")

# === 4. 服务管理 ===

def start_services():
    global p_nginx, p_alist, p_cloud
    os.makedirs(f"{CORE_DIR}/data", exist_ok=True)
    
    # 启动 Alist
    p_alist = subprocess.Popen([ALIST_BIN, "server", "--no-prefix"], cwd=CORE_DIR)
    time.sleep(2) # 等待数据库生成
    
    # 启动 Cloudreve
    p_cloud = subprocess.Popen([CLOUD_BIN, "-c", "conf.ini"], cwd=CORE_DIR)
    
    # 启动 Nginx
    print(">>> [Kernel] System Online.")
    p_nginx = subprocess.Popen(["nginx", "-g", "daemon off;"])

def stop_handler(signum, frame):
    print(">>> [Kernel] Shutting down...")
    if p_nginx: p_nginx.terminate()
    if p_cloud: p_cloud.terminate()
    if p_alist: p_alist.terminate()
    do_backup() # 退出前强制备份一次
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
        # 达到设定的秒数
        if step >= SYNC_INTERVAL:
            do_backup()
            step = 0
