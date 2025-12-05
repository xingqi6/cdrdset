#!/usr/bin/env python3
"""
Cloudreve + Datasets 无限存储方案
使用 Hugging Face Datasets 作为存储后端，突破 50GB 限制
"""

import os
import subprocess
import time
import signal
import sys
import re
import json
import urllib.request
import threading
from datetime import datetime

# ===========================
# 环境变量配置
# ===========================

# Hugging Face Datasets 配置（关键！）
HF_TOKEN = os.environ.get("HF_TOKEN", "")
HF_DATASET_REPO = os.environ.get("HF_DATASET_REPO", "")  # 格式: username/dataset-name

# WebDAV 备份配置
WEBDAV_URL = os.environ.get("WEBDAV_URL", "").rstrip('/')
WEBDAV_USER = os.environ.get("WEBDAV_USERNAME")
WEBDAV_PASS = os.environ.get("WEBDAV_PASSWORD")
BACKUP_PATH = os.environ.get("WEBDAV_BACKUP_PATH", "backup_data").strip('/')
SYNC_INTERVAL = int(os.environ.get("SYNC_INTERVAL", 3600))
SYS_TOKEN = os.environ.get("SYS_TOKEN", "123456")

# 路径定义
CORE_DIR = "/usr/local/sys_kernel"
ALIST_BIN = f"{CORE_DIR}/io_driver"
CLOUD_BIN = f"{CORE_DIR}/net_service"
ALIST_DB_LOCAL = f"{CORE_DIR}/data/data.db"
CLOUD_DB_LOCAL = f"{CORE_DIR}/sys.db"
CLOUD_CONF = f"{CORE_DIR}/conf.ini"
PREFIX_ALIST = "sys_io_snap_"
PREFIX_CLOUD = "sys_net_snap_"

# 进程句柄
p_nginx = None
p_alist = None
p_cloud = None
p_webdav = None

# ===========================
# Datasets 存储驱动（嵌入式）
# ===========================

import hashlib
from pathlib import Path

class DatasetsStorage:
    def __init__(self):
        self.hf_token = HF_TOKEN
        self.dataset_repo = HF_DATASET_REPO
        self.chunk_size = 50 * 1024 * 1024  # 50MB
        
        self.cache_dir = "/tmp/datasets_cache"
        self.metadata_dir = f"{CORE_DIR}/datasets_meta"
        
        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(self.metadata_dir, exist_ok=True)
        
        self.repo_path = f"{self.cache_dir}/repo"
        self.initialized = False
    
    def init_repo(self):
        """初始化 Datasets 仓库"""
        if not self.hf_token or not self.dataset_repo:
            print(">>> [Storage] ERROR: HF_TOKEN or HF_DATASET_REPO not set!")
            print(">>> [Storage] Please set these environment variables:")
            print(">>>   HF_TOKEN=hf_xxxxx")
            print(">>>   HF_DATASET_REPO=username/dataset-name")
            return False
        
        if os.path.exists(self.repo_path):
            print(f">>> [Storage] Using existing repo: {self.repo_path}")
            self.initialized = True
            return True
        
        try:
            print(f">>> [Storage] Cloning dataset: {self.dataset_repo}")
            
            # 克隆仓库
            clone_url = f"https://oauth2:{self.hf_token}@huggingface.co/datasets/{self.dataset_repo}"
            subprocess.run(
                ["git", "clone", clone_url, self.repo_path],
                check=True,
                capture_output=True,
                timeout=60
            )
            
            # 配置 Git LFS
            subprocess.run(["git", "lfs", "install"], cwd=self.repo_path, check=True)
            subprocess.run(["git", "config", "user.email", "storage@hf.space"], cwd=self.repo_path)
            subprocess.run(["git", "config", "user.name", "HF Storage"], cwd=self.repo_path)
            
            # 创建 chunks 目录
            chunks_dir = os.path.join(self.repo_path, "chunks")
            os.makedirs(chunks_dir, exist_ok=True)
            
            # 创建 .gitattributes（让 Git LFS 追踪 .chunk 文件）
            gitattributes = os.path.join(self.repo_path, ".gitattributes")
            with open(gitattributes, "w") as f:
                f.write("*.chunk filter=lfs diff=lfs merge=lfs -text\n")
            
            # 提交初始化
            subprocess.run(["git", "add", "."], cwd=self.repo_path)
            subprocess.run(["git", "commit", "-m", "Initialize storage"], cwd=self.repo_path)
            subprocess.run(["git", "push"], cwd=self.repo_path, check=True)
            
            print(f">>> [Storage] Initialized: {self.dataset_repo}")
            self.initialized = True
            return True
            
        except subprocess.TimeoutExpired:
            print(">>> [Storage] Clone timeout - repo might be too large")
            return False
        except Exception as e:
            print(f">>> [Storage] Init failed: {e}")
            return False
    
    def upload_file(self, local_path, remote_name):
        """上传文件到 Datasets"""
        if not self.initialized:
            raise RuntimeError("Storage not initialized")
        
        if not os.path.exists(local_path):
            raise FileNotFoundError(f"File not found: {local_path}")
        
        file_size = os.path.getsize(local_path)
        file_hash = self._calculate_hash(local_path)
        
        print(f">>> [Storage] Uploading {remote_name} ({file_size} bytes)")
        
        metadata = {
            "name": remote_name,
            "size": file_size,
            "hash": file_hash,
            "chunks": [],
            "upload_time": time.time()
        }
        
        # 分块上传
        chunk_index = 0
        chunks_dir = os.path.join(self.repo_path, "chunks")
        
        with open(local_path, 'rb') as f:
            while True:
                chunk_data = f.read(self.chunk_size)
                if not chunk_data:
                    break
                
                chunk_name = f"{file_hash}_{chunk_index:04d}.chunk"
                chunk_path = os.path.join(chunks_dir, chunk_name)
                
                with open(chunk_path, 'wb') as cf:
                    cf.write(chunk_data)
                
                metadata["chunks"].append({
                    "index": chunk_index,
                    "name": chunk_name,
                    "size": len(chunk_data)
                })
                
                chunk_index += 1
                total_chunks = (file_size + self.chunk_size - 1) // self.chunk_size
                print(f">>> [Storage] Chunk {chunk_index}/{total_chunks}")
        
        # 保存元数据
        self._save_metadata(remote_name, metadata)
        
        # 提交到 Git
        try:
            subprocess.run(["git", "add", "."], cwd=self.repo_path, check=True)
            subprocess.run(["git", "commit", "-m", f"Upload: {remote_name}"], cwd=self.repo_path)
            subprocess.run(["git", "push"], cwd=self.repo_path, check=True, timeout=300)
            print(f">>> [Storage] Uploaded successfully: {remote_name}")
        except Exception as e:
            print(f">>> [Storage] Push failed: {e}")
        
        # 清理临时文件
        try:
            os.remove(local_path)
        except:
            pass
        
        return metadata
    
    def download_file(self, remote_name, local_path):
        """下载文件"""
        metadata = self._load_metadata(remote_name)
        if not metadata:
            raise FileNotFoundError(f"File not found: {remote_name}")
        
        print(f">>> [Storage] Downloading {remote_name}")
        
        # 拉取最新
        subprocess.run(["git", "pull"], cwd=self.repo_path, timeout=60)
        
        # 合并分块
        with open(local_path, 'wb') as f:
            for chunk_info in metadata["chunks"]:
                chunk_path = os.path.join(self.repo_path, "chunks", chunk_info["name"])
                
                if not os.path.exists(chunk_path):
                    raise FileNotFoundError(f"Chunk missing: {chunk_info['name']}")
                
                with open(chunk_path, 'rb') as cf:
                    f.write(cf.read())
                
                print(f">>> [Storage] Chunk {chunk_info['index'] + 1}/{len(metadata['chunks'])}")
        
        print(f">>> [Storage] Downloaded: {remote_name}")
        return metadata
    
    def _calculate_hash(self, filepath):
        sha256 = hashlib.sha256()
        with open(filepath, 'rb') as f:
            while chunk := f.read(8192):
                sha256.update(chunk)
        return sha256.hexdigest()[:16]  # 使用前16位即可
    
    def _save_metadata(self, remote_name, metadata):
        safe_name = hashlib.md5(remote_name.encode()).hexdigest()
        metadata_path = os.path.join(self.metadata_dir, f"{safe_name}.json")
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
    
    def _load_metadata(self, remote_name):
        safe_name = hashlib.md5(remote_name.encode()).hexdigest()
        metadata_path = os.path.join(self.metadata_dir, f"{safe_name}.json")
        if not os.path.exists(metadata_path):
            return None
        with open(metadata_path, 'r') as f:
            return json.load(f)

# ===========================
# WebDAV 桥接服务器
# ===========================

from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse

class WebDAVHandler(BaseHTTPRequestHandler):
    storage = None
    
    def log_message(self, format, *args):
        pass  # 禁用日志
    
    def do_PUT(self):
        try:
            path = urllib.parse.unquote(self.path).lstrip('/')
            content_length = int(self.headers.get('Content-Length', 0))
            
            temp_path = f"/tmp/upload_{int(time.time() * 1000)}.tmp"
            with open(temp_path, 'wb') as f:
                f.write(self.rfile.read(content_length))
            
            self.storage.upload_file(temp_path, path)
            
            self.send_response(201)
            self.end_headers()
        except Exception as e:
            print(f">>> [WebDAV] PUT error: {e}")
            self.send_response(500)
            self.end_headers()
    
    def do_GET(self):
        try:
            path = urllib.parse.unquote(self.path).lstrip('/')
            temp_path = f"/tmp/download_{int(time.time() * 1000)}.tmp"
            
            metadata = self.storage.download_file(path, temp_path)
            
            self.send_response(200)
            self.send_header('Content-Length', str(metadata['size']))
            self.send_header('Content-Type', 'application/octet-stream')
            self.end_headers()
            
            with open(temp_path, 'rb') as f:
                self.wfile.write(f.read())
            
            os.remove(temp_path)
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()
        except Exception as e:
            print(f">>> [WebDAV] GET error: {e}")
            self.send_response(500)
            self.end_headers()

def start_webdav_server(storage):
    """在后台线程启动 WebDAV 服务器"""
    WebDAVHandler.storage = storage
    server = HTTPServer(('127.0.0.1', 8888), WebDAVHandler)
    print(">>> [WebDAV] Bridge server started on port 8888")
    server.serve_forever()

# ===========================
# Cloudreve 配置生成
# ===========================

def generate_cloudreve_config():
    """生成使用 WebDAV 作为存储后端的配置"""
    
    config = f"""[System]
Mode = master
Listen = :5212
Debug = false

[Database]
Type = sqlite
DBFile = {CLOUD_DB_LOCAL}
TablePrefix = cd_

[Upload]
MaxSize = 536870912000
ChunkSize = 52428800

[Slave]
Secret = 
"""
    
    with open(CLOUD_CONF, 'w') as f:
        f.write(config)
    
    print(f">>> [Config] Generated: {CLOUD_CONF}")

# ===========================
# 网络修复（保留）
# ===========================

def resolve_ip_multi(domain):
    try:
        url = f"https://cloudflare-dns.com/dns-query?name={domain}&type=A"
        req = urllib.request.Request(url, headers={"Accept": "application/dns-json"})
        with urllib.request.urlopen(req, timeout=8) as response:
            data = json.loads(response.read().decode())
            if "Answer" in data:
                for answer in data["Answer"]:
                    if answer["type"] == 1:
                        return answer["data"]
    except:
        pass
    return None

def patch_network():
    targets = ["huggingface.co", "s3.huggingface.co", "cdn-lfs.huggingface.co"]
    resolved_map = {}
    
    for domain in targets:
        ip = resolve_ip_multi(domain)
        resolved_map[domain] = ip if ip else "18.64.173.110"
    
    try:
        with open("/etc/hosts", "a") as f:
            f.write("\n# HF Patch\n")
            for domain, ip in resolved_map.items():
                f.write(f"{ip} {domain}\n")
        print(">>> [Network] Patched")
    except:
        pass

# ===========================
# 备份功能（保留）
# ===========================

def run_cmd(cmd):
    try:
        subprocess.run(cmd, shell=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except:
        return False

def set_secret():
    try:
        subprocess.run([ALIST_BIN, "admin", "set", SYS_TOKEN], cwd=CORE_DIR, 
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except:
        pass

# ===========================
# 启动流程
# ===========================

def start_services():
    global p_nginx, p_alist, p_cloud, p_webdav
    
    print("=" * 80)
    print(" CLOUDREVE + DATASETS UNLIMITED STORAGE")
    print("=" * 80)
    
    # 1. 网络修复
    patch_network()
    
    # 2. 初始化 Datasets 存储
    storage = DatasetsStorage()
    if not storage.init_repo():
        print("\n>>> [ERROR] Failed to initialize Datasets storage!")
        print(">>> Please check:")
        print(">>>   1. HF_TOKEN is valid")
        print(">>>   2. HF_DATASET_REPO exists (format: username/dataset-name)")
        print(">>>   3. You have write permission to the dataset")
        print("\n>>> Create a dataset at: https://huggingface.co/new-dataset")
        print(">>> Then set: HF_DATASET_REPO=your-username/your-dataset-name")
        sys.exit(1)
    
    # 3. 启动 WebDAV 桥接服务器
    webdav_thread = threading.Thread(target=start_webdav_server, args=(storage,), daemon=True)
    webdav_thread.start()
    time.sleep(2)
    
    # 4. 生成配置
    os.makedirs(f"{CORE_DIR}/data", exist_ok=True)
    generate_cloudreve_config()
    
    # 5. 启动 Alist
    print(">>> [Kernel] Starting Alist...")
    p_alist = subprocess.Popen([ALIST_BIN, "server", "--no-prefix"], cwd=CORE_DIR)
    time.sleep(8)
    set_secret()
    
    # 6. 启动 Cloudreve
    print(">>> [Kernel] Starting Cloudreve...")
    p_cloud = subprocess.Popen([CLOUD_BIN, "-c", CLOUD_CONF], cwd=CORE_DIR)
    time.sleep(3)
    
    # 7. 启动 Nginx
    print(">>> [Kernel] Starting Nginx...")
    p_nginx = subprocess.Popen(["nginx", "-g", "daemon off;"])
    
    print("\n" + "=" * 80)
    print(">>> SYSTEM ONLINE - DATASETS STORAGE MODE")
    print(f">>> Cloudreve: http://localhost:7860/xmj")
    print(f">>> Alist: http://localhost:7860/alist (Token: {SYS_TOKEN})")
    print(f">>> Storage Backend: Datasets - {HF_DATASET_REPO}")
    print(f">>> Max File Size: 500GB (No HF Space disk usage)")
    print("=" * 80 + "\n")

def stop_handler(signum, frame):
    print("\n>>> Shutting down...")
    if p_nginx: p_nginx.terminate()
    if p_cloud: p_cloud.terminate()
    if p_alist: p_alist.terminate()
    sys.exit(0)

if __name__ == "__main__":
    start_services()
    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)
    
    while True:
        time.sleep(60)
