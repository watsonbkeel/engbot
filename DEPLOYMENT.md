# 完整部署指南

本指南帮助其他用户从零开始部署整套英语口语陪练系统（云端服务器 + 树莓派边缘设备 + 微信小程序）。

## 系统架构

```
┌──────────────┐         HTTPS          ┌─────────────────┐
│  微信小程序   │◀─────────────────────▶│   云端服务器     │
│  家长设置端   │    english.bkeel.com   │   Public API    │
└──────────────┘                        │   Brain API     │
                                        └─────────────────┘
                                                ▲
                                                │ HTTPS
                                                │ /students/s001
                                                │
                                        ┌─────────────────┐
                                        │   树莓派 4B      │
                                        │   Edge 录音播放  │
                                        │   本地唤醒识别   │
                                        └─────────────────┘
```

- **云端服务器**：运行 Public API（公共接口）和 Brain API（学生专属课堂）
- **树莓派**：音频采集、本地唤醒、远程语音识别与合成
- **微信小程序**：家长配置、查看学习记录

---

## 前置要求

### 云端服务器
- **系统**：Ubuntu 22.04+ 或 Debian 13+
- **配置**：2 核 4GB 内存，20GB 硬盘
- **网络**：公网 IP，开放 80/443 端口
- **域名**：已配置 HTTPS 证书（Let's Encrypt 或 Cloudflare Origin CA）

### 树莓派
- **硬件**：树莓派 4B（4GB 内存推荐）
- **系统**：Raspberry Pi OS（64-bit，基于 Debian）
- **音频**：USB 声卡 + 麦克风 + 耳机
- **网络**：能连接互联网（WiFi 或以太网）

### 开发环境
- **Python**：3.11+
- **Node.js**：18+ （小程序构建）
- **微信开发者工具**：小程序上传

---

## 第一步：克隆代码

```bash
git clone https://github.com/watsonbkeel/engbot.git
cd engbot
```

---

## 第二步：云端服务器部署

### 2.1 安装依赖

```bash
# 更新系统
sudo apt update && sudo apt upgrade -y

# 安装 Python 和必要工具
sudo apt install -y python3.11 python3.11-venv python3-pip \
    nginx certbot python3-certbot-nginx \
    sqlite3 ffmpeg

# 创建部署目录
sudo mkdir -p /opt/english-class
sudo chown $USER:$USER /opt/english-class
```

### 2.2 部署代码

```bash
# 复制代码到部署目录
cd /path/to/engbot
sudo cp -r english_class pi prompts tests scripts data requirements.txt pyproject.toml /opt/english-class/

# 创建虚拟环境并安装依赖
cd /opt/english-class
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

### 2.3 下载语音模型

```bash
# 创建模型目录
mkdir -p /opt/english-class/models

# 下载 Vosk 英文模型
cd /opt/english-class/models
wget https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
unzip vosk-model-small-en-us-0.15.zip
rm vosk-model-small-en-us-0.15.zip

# 下载 Vosk 中文模型
wget https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip
unzip vosk-model-small-cn-0.22.zip
rm vosk-model-small-cn-0.22.zip
```

### 2.4 配置服务

```bash
# 创建配置目录
sudo mkdir -p /etc/english-class/students
sudo mkdir -p /var/lib/english-class
sudo mkdir -p /var/lib/english-class-brain/s001

# 复制配置模板
cd /path/to/engbot
sudo cp .env.example /etc/english-class/public.env
sudo cp .env.example /etc/english-class/students/s001.env

# 编辑配置文件，填写真实值
sudo nano /etc/english-class/public.env
sudo nano /etc/english-class/students/s001.env
```

**必须修改的配置项**：
```ini
# /etc/english-class/public.env
LLM_API_KEY=你的大模型API密钥
ASR_API_KEY=你的语音识别API密钥（或留空用 Vosk）
TTS_API_KEY=你的语音合成API密钥

# /etc/english-class/students/s001.env
PUBLIC_URL=https://你的域名.com
BRAIN_TOKEN=随机生成的64位字符串
EDGE_TOKEN=随机生成的64位字符串
```

生成随机 Token：
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

### 2.5 初始化数据库

```bash
cd /opt/english-class
.venv/bin/python -c "from english_class.store import Store; \
    Store('/var/lib/english-class/class.sqlite3', \
    secret_key_file='/var/lib/english-class/.key', \
    timezone='Asia/Shanghai').migrate()"

# 创建学生账号并生成凭证
.venv/bin/python scripts/provision.py s001 \
    --port 9101 \
    --output /tmp/s001-credentials \
    --public-url https://你的域名.com
```

### 2.6 创建 systemd 服务

**Public API 服务**：
```bash
sudo nano /etc/systemd/system/english-public.service
```
```ini
[Unit]
Description=English Class Public API
After=network.target

[Service]
Type=simple
User=english-public
Group=english-public
WorkingDirectory=/opt/english-class
EnvironmentFile=/etc/english-class/public.env
ExecStart=/opt/english-class/.venv/bin/python -m english_class.run public
Restart=on-failure
RestartSec=10
StateDirectory=english-class

[Install]
WantedBy=multi-user.target
```

**Brain API 服务**（实例化服务，支持多学生）：
```bash
sudo nano /etc/systemd/system/english-brain@.service
```
```ini
[Unit]
Description=English Class Student Brain %i
After=network.target english-public.service

[Service]
Type=simple
User=english-%i
Group=english-%i
WorkingDirectory=/opt/english-class/students/%i
EnvironmentFile=/etc/english-class/students/%i.env
ExecStart=/opt/english-class/.venv/bin/python -m english_class.run brain
Restart=on-failure
RestartSec=10
StateDirectory=english-class-brain/%i

[Install]
WantedBy=multi-user.target
```

**创建服务用户**：
```bash
sudo useradd -r -s /bin/false english-public
sudo useradd -r -s /bin/false english-s001
sudo chown -R english-public:english-public /var/lib/english-class
sudo chown -R english-s001:english-s001 /var/lib/english-class-brain/s001
```

**启动服务**：
```bash
sudo systemctl daemon-reload
sudo systemctl enable english-public english-brain@s001
sudo systemctl start english-public english-brain@s001

# 检查状态
sudo systemctl status english-public english-brain@s001
```

### 2.7 配置 Nginx

```bash
sudo nano /etc/nginx/sites-available/english-class
```
```nginx
upstream english_public {
    server 127.0.0.1:9100;
}

upstream english_brain_s001 {
    server 127.0.0.1:9101;
}

server {
    listen 80;
    server_name 你的域名.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name 你的域名.com;

    ssl_certificate /etc/letsencrypt/live/你的域名.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/你的域名.com/privkey.pem;

    location / {
        proxy_pass http://english_public;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /students/s001/ {
        rewrite ^/students/s001/(.*) /$1 break;
        proxy_pass http://english_brain_s001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    client_max_body_size 10M;
}
```

```bash
sudo ln -s /etc/nginx/sites-available/english-class /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 2.8 申请 HTTPS 证书

```bash
sudo certbot --nginx -d 你的域名.com
```

### 2.9 验证部署

```bash
curl https://你的域名.com/api/status
curl https://你的域名.com/students/s001/health
```

---

## 第三步：树莓派边缘设备部署

### 3.1 准备树莓派

```bash
# SSH 登录树莓派
ssh pi@树莓派IP

# 更新系统
sudo apt update && sudo apt upgrade -y

# 安装依赖
sudo apt install -y python3.11 python3.11-venv python3-pip \
    alsa-utils espeak-ng portaudio19-dev
```

### 3.2 部署代码

```bash
# 创建部署目录
sudo mkdir -p /opt/english-class
sudo chown $USER:$USER /opt/english-class

# 从云端复制代码（或用 git clone）
scp -r user@云端IP:/opt/english-class/pi /opt/english-class/
scp -r user@云端IP:/opt/english-class/prompts /opt/english-class/

# 安装依赖
cd /opt/english-class
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install httpx python-dotenv vosk soundfile numpy
```

### 3.3 下载唤醒模型

```bash
mkdir -p /opt/english-class-edge/models
cd /opt/english-class-edge/models
wget https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip
unzip vosk-model-small-cn-0.22.zip
rm vosk-model-small-cn-0.22.zip
```

### 3.4 配置音频设备

```bash
# 列出音频设备
aplay -l
arecord -l

# 测试播放
aplay -D plughw:CARD=Audio,DEV=0 /usr/share/sounds/alsa/Front_Center.wav

# 测试录音
arecord -D plughw:CARD=Audio,DEV=0 -d 3 -f S16_LE -r 16000 -c 1 test.wav
aplay test.wav
```

### 3.5 配置服务

```bash
# 从云端获取凭证（在 2.5 步生成的）
# 或手动创建 .env
sudo nano /opt/english-class/.env
```
```ini
BRAIN_URL=https://你的域名.com/students/s001
EDGE_TOKEN=从云端生成的EDGE_TOKEN
CAPTURE_DEVICE=plughw:CARD=Audio,DEV=0
PLAYBACK_DEVICE=plughw:CARD=Audio,DEV=0
VOSK_ZH_PATH=/opt/english-class-edge/models/vosk-model-small-cn-0.22
VAD_THRESHOLD=450
MIC_GAIN=1.0
ALLOW_INSECURE_HTTP=0
```

### 3.6 创建 systemd 服务

```bash
sudo nano /etc/systemd/system/english-edge.service
```
```ini
[Unit]
Description=English Class Edge Device
After=network.target

[Service]
Type=simple
User=chs
Group=chs
WorkingDirectory=/opt/english-class
EnvironmentFile=/opt/english-class/.env
ExecStart=/opt/english-class/.venv/bin/python -m pi.english_voice --env /opt/english-class/.env
Restart=on-failure
RestartSec=10
StateDirectory=english-class-edge

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable english-edge
sudo systemctl start english-edge

# 检查状态
sudo systemctl status english-edge
journalctl -u english-edge -f
```

### 3.7 验证连接

说：**"小陈同学，学英语"**，检查是否有语音回应。

---

## 第四步：微信小程序部署

### 4.1 构建小程序

```bash
cd /path/to/engbot
python3 scripts/build_miniprogram.py \
    --output /tmp/english-miniprogram \
    --connection miniprogram/utils/english-env.local.js
```

编辑连接配置：
```bash
nano /tmp/english-miniprogram/utils/english-env.local.js
```
```javascript
export const apiUrl = 'https://你的域名.com'
export const studentId = 's001'
export const parentToken = '从云端生成的家长Token'
export const allowHttpForLan = false
```

### 4.2 上传小程序

1. 打开**微信开发者工具**
2. 导入项目：选择 `/tmp/english-miniprogram` 目录
3. 填写 AppID（在微信公众平台申请）
4. 配置**服务器域名白名单**：
   - `request 合法域名`：`https://你的域名.com`
   - `downloadFile 合法域名`：`https://你的域名.com`
5. 点击**上传**，填写版本号和备注
6. 登录**微信公众平台** → 版本管理 → 提交审核

---

## 常见问题

### Q1：云端服务启动失败
```bash
# 检查日志
sudo journalctl -u english-public -n 50
sudo journalctl -u english-brain@s001 -n 50

# 常见原因：
# - 端口被占用：lsof -i:9100
# - 配置文件错误：检查 /etc/english-class/*.env
# - 数据库权限：sudo chown english-public /var/lib/english-class/class.sqlite3
```

### Q2：树莓派无声音
```bash
# 检查设备
aplay -l
amixer

# 检查服务日志
journalctl -u english-edge -f

# 常见原因：
# - 音频设备配置错误：重新运行 aplay -l 确认设备号
# - 音量为 0：amixer set Master 80%
# - USB 声卡未插好：重新插拔
```

### Q3：小程序"大脑未连接"
```bash
# 检查云端 Brain 服务
curl https://你的域名.com/students/s001/health

# 常见原因：
# - Brain 服务未启动
# - Nginx 配置错误
# - 凭证不匹配：检查小程序 parentToken 和云端 /tmp/s001-credentials/README.txt
```

### Q4：语音识别失败（503）
```bash
# 检查 Vosk 模型
ls -lh /opt/english-class/models/

# 检查日志
sudo journalctl -u english-public -n 50 | grep -i asr

# 常见原因：
# - Vosk 模型未下载
# - ASR_BACKEND 配置错误
# - ASR_FALLBACK 未启用
```

---

## 安全建议

1. **定期更新系统**：
   ```bash
   sudo apt update && sudo apt upgrade -y
   ```

2. **限制 SSH 访问**：
   - 禁用密码登录，只用密钥
   - 修改默认 SSH 端口
   - 配置防火墙（ufw）

3. **备份数据库**：
   ```bash
   sudo sqlite3 /var/lib/english-class/class.sqlite3 ".backup /备份路径/class-$(date +%Y%m%d).sqlite3"
   ```

4. **监控服务**：
   ```bash
   # 定时检查服务状态
   */5 * * * * systemctl is-active english-public || systemctl restart english-public
   ```

---

## 下一步

- [API 文档](docs/API.md)
- [代码结构](docs/CODE_MAP.md)
- [升级说明](docs/UPGRADE.md)
- [测试报告](docs/TEST_REPORT.md)

---

## 技术支持

- GitHub Issues：https://github.com/watsonbkeel/engbot/issues
- 邮箱：watson@bkeel.com
