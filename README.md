# 🎯 Cloudreve + Datasets 无限存储部署指南

## 核心原理

```
用户 → Cloudreve → WebDAV 桥接 → Datasets Git LFS
         ↓
    仅元数据在容器
    真实文件在 Datasets 仓库
```

**关键突破**：
- ✅ 文件分块上传到 Datasets（50MB/块）
- ✅ 使用 Git LFS 管理大文件
- ✅ 容器内只保存元数据（~1KB/文件）
- ✅ 支持 500GB 单文件
- ✅ 总容量无限制

---

## 📋 准备工作

### Step 1: 创建 Datasets 仓库

1. 访问：https://huggingface.co/new-dataset
2. 填写信息：
   - **Owner**: 你的用户名
   - **Dataset name**: `cloudreve-storage`（或任意名称）
   - **License**: 选择 `other`
   - **Visibility**: Private（推荐）

3. 点击 **Create dataset**

### Step 2: 获取 Access Token

1. 访问：https://huggingface.co/settings/tokens
2. 点击 **New token**
3. 设置：
   - **Name**: `Cloudreve Storage`
   - **Role**: `write`（必须有写权限）
4. 复制生成的 Token（格式：`hf_xxxxxxxxxxxxx`）

---

## 🚀 部署到 Hugging Face Spaces

### Step 1: 创建 Space

1. 访问：https://huggingface.co/new-space
2. 配置：
   - **Owner**: 你的用户名
   - **Space name**: `cloudreve-unlimited`（或任意名称）
   - **License**: MIT
   - **Select the Space SDK**: **Docker**
   - **Space hardware**: CPU basic（免费）

### Step 2: 配置环境变量

在 Space 的 **Settings** → **Variables and secrets** 中添加：

#### 必需环境变量

```bash
# Hugging Face 配置（必填！）
HF_TOKEN=hf_xxxxxxxxxxxxxxxxxx
HF_DATASET_REPO=你的用户名/cloudreve-storage

# 管理员密码
SYS_TOKEN=你的超级密码
```

#### 可选环境变量

```bash
# WebDAV 备份（用于备份数据库）
WEBDAV_URL=https://你的WebDAV地址
WEBDAV_USERNAME=用户名
WEBDAV_PASSWORD=密码

# 同步间隔（秒）
SYNC_INTERVAL=3600
```

### Step 3: 上传文件

将以下文件上传到 Space 根目录：

```
你的-space/
├── Dockerfile          # 使用新版本
├── boot.py            # 使用新版本
├── nginx.conf         # 使用更新版本
├── fake_site/
│   └── index.html
└── README.md
```

### Step 4: 等待构建

- Space 会自动构建（5-10 分钟）
- 查看 **Logs** 确认启动成功
- 看到 `SYSTEM ONLINE - DATASETS STORAGE MODE` 表示成功

### Step 5: 访问服务

```
https://你的用户名-space名称.hf.space/xmj
```

首次访问会提示创建管理员账户。

---

## 🔧 工作原理详解

### 1. 文件上传流程

```
用户上传 500GB 文件
    ↓
Cloudreve 接收（不保存到本地磁盘）
    ↓
WebDAV 桥接服务器拦截
    ↓
分块：500GB ÷ 50MB = 10,240 块
    ↓
逐块上传到 Datasets Git LFS
    ↓
元数据保存到容器（仅 2KB）
```

**关键**：容器内只有元数据，真实文件在 Datasets 仓库。

### 2. 文件下载流程

```
用户请求文件
    ↓
Cloudreve 查询元数据
    ↓
WebDAV 从 Datasets 拉取分块
    ↓
边下载边发送给用户（流式传输）
    ↓
不占用容器磁盘空间
```

### 3. 存储结构

#### Datasets 仓库结构

```
你的用户名/cloudreve-storage/
├── chunks/
│   ├── abc123_0000.chunk  (50MB)
│   ├── abc123_0001.chunk  (50MB)
│   ├── abc123_0002.chunk  (50MB)
│   └── ...
├── .gitattributes
└── README.md
```

#### 容器内结构

```
/usr/local/sys_kernel/
├── datasets_meta/
│   ├── 5f4dcc3b5aa765d61d8327deb882cf99.json  # 文件元数据
│   └── ...
├── data/
│   └── data.db  # Alist 数据库
├── sys.db       # Cloudreve 数据库
└── boot.py
```

每个文件的元数据示例：
```json
{
  "name": "movie.mp4",
  "size": 10737418240,
  "hash": "abc123def456",
  "chunks": [
    {"index": 0, "name": "abc123def456_0000.chunk", "size": 52428800},
    {"index": 1, "name": "abc123def456_0001.chunk", "size": 52428800}
  ],
  "upload_time": 1234567890
}
```

---

## 📊 容量对比

| 项目 | 不使用 Datasets | 使用 Datasets |
|------|----------------|--------------|
| **单文件大小** | ~10GB | **500GB+** |
| **总容量** | 50GB（免费版） | **无限** |
| **容器磁盘占用** | 全部文件 | 仅元数据（~1KB/文件） |
| **重启后** | 文件丢失 | **永久保存** |
| **内存占用** | 高 | 低（流式传输） |
| **下载速度** | 受限 | 取决于网络 |

---

## 🧪 本地测试

### 方法 1: Docker Compose

创建 `docker-compose.yml`:

```yaml
version: '3.8'

services:
  cloudreve:
    build: .
    ports:
      - "7860:7860"
    environment:
      - HF_TOKEN=hf_your_token
      - HF_DATASET_REPO=username/dataset-name
      - SYS_TOKEN=admin123
    volumes:
      - ./data:/usr/local/sys_kernel/data
```

运行：
```bash
docker-compose up
```

### 方法 2: 直接 Docker

```bash
# 构建镜像
docker build -t cloudreve-datasets .

# 运行容器
docker run -p 7860:7860 \
  -e HF_TOKEN=hf_your_token \
  -e HF_DATASET_REPO=username/dataset-name \
  -e SYS_TOKEN=admin123 \
  cloudreve-datasets
```

访问：`http://localhost:7860/xmj`

---

## 🐛 常见问题

### Q1: 启动失败 "Failed to initialize Datasets storage"

**原因**：
- HF_TOKEN 无效或没有写权限
- HF_DATASET_REPO 格式错误
- Datasets 仓库不存在

**解决**：
1. 检查 Token 是否有 `write` 权限
2. 确认仓库格式：`username/dataset-name`（不是 URL）
3. 确保仓库已创建

### Q2: 上传卡在 "Uploading chunk X/Y"

**原因**：
- 网络连接问题
- Git LFS 推送失败

**解决**：
1. 检查 Hugging Face 服务状态
2. 查看容器日志：`docker logs <container_id>`
3. 重试上传

### Q3: 下载失败 "Chunk missing"

**原因**：
- Datasets 仓库数据不完整
- Git LFS 文件未完全上传

**解决**：
1. 检查 Datasets 仓库中 chunks 目录
2. 手动 `git lfs pull` 拉取文件
3. 重新上传文件

### Q4: 容器重启后文件丢失

**原因**：
- 元数据目录未持久化

**解决**：
在 Docker 中挂载元数据目录：
```bash
-v /path/on/host:/usr/local/sys_kernel/datasets_meta
```

### Q5: 上传速度慢

**原因**：
- Hugging Face 网络限制
- Git LFS 推送速度限制

**优化**：
1. 使用付费 Space（更好的网络）
2. 减小分块大小（改 `chunk_size`）
3. 考虑使用 Cloudflare R2 等对象存储

---

## ⚠️ 重要限制

### Hugging Face Datasets 限制

1. **Git LFS 带宽**：免费账户有限制
2. **推送频率**：不要过于频繁推送
3. **单次推送**：建议不超过 5GB

### 建议

1. **批量上传**：多个小文件一次性提交
2. **避免频繁修改**：文件上传后尽量不要修改
3. **监控配额**：查看 Datasets 仓库大小

---

## 🔒 安全建议

### 1. Token 安全

- ✅ 使用环境变量，不要硬编码
- ✅ Token 设置最小权限（只给 Datasets 仓库写权限）
- ✅ 定期轮换 Token

### 2. 仓库隐私

- ✅ 设置 Datasets 为 Private
- ✅ 不要在公开仓库中包含敏感文件
- ✅ 定期审查仓库访问权限

### 3. 访问控制

在 `nginx.conf` 中添加：

```nginx
# IP 白名单
location /xmj {
    allow 你的IP;
    deny all;
    # ...
}
```

---

## 📈 性能优化

### 1. 调整分块大小

在 `boot.py` 中修改：

```python
self.chunk_size = 100 * 1024 * 1024  # 改为 100MB
```

**权衡**：
- 更大分块 = 更少的 Git 提交 = 更快
- 更小分块 = 更细粒度的断点续传

### 2. 使用 CDN

在 Datasets 前加 CDN（如 Cloudflare）：
```
用户 → Cloudflare CDN → Datasets
```

### 3. 升级硬件

- **CPU Upgrade**：更稳定的网络连接
- **更多内存**：可以缓存更多元数据

---

## 🎉 完成！

现在你的 Cloudreve 可以：

- ✅ 上传/下载 500GB 文件
- ✅ 不受 HF Space 50GB 限制
- ✅ 不占用容器磁盘空间
- ✅ 文件永久保存在 Datasets
- ✅ 支持断点续传
- ✅ 完全免费（在免费配额内）

---

## 📚 进阶玩法

### 1. 多仓库存储

修改代码支持多个 Datasets 仓库：
- `dataset-1`：视频文件
- `dataset-2`：文档文件
- `dataset-3`：备份文件

### 2. 加密存储

在上传前加密分块：
```python
# 使用 AES 加密
from cryptography.fernet import Fernet
cipher = Fernet(key)
encrypted_chunk = cipher.encrypt(chunk_data)
```

### 3. 智能去重

相同文件只存一份：
```python
# 检查文件哈希
if file_hash in existing_hashes:
    # 直接引用已有分块
    pass
```

---

## 🆘 获取帮助

- Hugging Face 论坛：https://discuss.huggingface.co
- Discord：https://hf.co/join/discord
- GitHub Issues：提交 Bug 报告

---

**祝部署顺利！🚀**
