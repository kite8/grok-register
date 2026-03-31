# Grok Register 的 OpenResty 反向代理说明

## 1. 先说明这个项目里两个服务分别是什么

根据仓库当前配置，这两个地址对应的是两套不同的 Web 服务：

- `http://<服务器IP>:18600`
  - 对应 `console` 服务
  - 来自根目录 `docker-compose.yml` 里的 `console` 容器
  - 默认映射：`18600:18600`
  - 用途：Grok Register 的任务控制台

- `http://<服务器IP>:8000/admin`
  - 对应 `grok2api` 服务的后台页面
  - 来自根目录 `docker-compose.yml` 里的 `grok2api` 容器
  - 默认映射：`8000:8000`
  - 用途：`grok2api` 的管理后台，后台接口实际走的是 `/v1/admin/...`

仓库里的直接依据：

- `docker-compose.yml` 中 `console` 暴露 `18600`
- `docker-compose.yml` 中 `grok2api` 暴露 `8000`
- `readme.md` 中启动后访问地址就是：
  - `http://<你的服务器IP>:18600`
  - `http://<你的服务器IP>:8000/admin`

## 2. 为什么不建议同一个域名用路径拆分

不建议做成下面这种形式：

- `http://example.com/` -> `18600`
- `http://example.com/admin` -> `8000/admin`

原因不是 OpenResty 做不到，而是这两个应用默认都使用绝对路径 `/static/...`：

- 控制台页面 `apps/console/templates/index.html` 依赖 `/static/app.css` 和 `/static/app.js`
- `grok2api` 后台页面依赖 `/static/common/...`、`/static/admin/...`

这样一来，只要把两个服务挂到同一个域名下，它们就会争用 `/static`，页面资源很容易串掉。

所以推荐方案是：

- 方案 A：两个子域名
- 方案 B：两个独立站点
- 方案 C：没有域名时，用 OpenResty 暴露两个新端口

最稳的是方案 A。

## 3. 推荐方案：两个子域名分别反代

建议你准备两个域名解析到同一台服务器：

- `console.example.com` -> 反代到 `127.0.0.1:18600`
- `grok-admin.example.com` -> 反代到 `127.0.0.1:8000`

注意：

- `grok-admin.example.com` 要代理整个 `8000` 服务，不要只代理 `/admin`
- 因为后台页面除了 `/admin/...`，还会访问：
  - `/v1/admin/...`
  - `/static/...`
  - 以及部分 SSE / WebSocket 路径

## 4. OpenResty 配置示例

下面给出两份站点配置。你可以在 1Panel 里新建两个站点，然后把对应配置写进 OpenResty 的站点配置文件。

### 4.1 控制台站点

适用目标：

- `https://console.example.com` -> `http://127.0.0.1:18600`

```nginx
server {
    listen 80;
    listen 443 ssl http2;
    server_name console.example.com;

    # 证书路径请按 1Panel 实际签发位置填写
    ssl_certificate     /www/sites/console.example.com/ssl/fullchain.pem;
    ssl_certificate_key /www/sites/console.example.com/ssl/privkey.pem;

    # 上传体积可按需调整；控制台本身通常不需要太大
    client_max_body_size 20m;

    location / {
        # 反代到控制台服务
        proxy_pass http://127.0.0.1:18600;

        # 透传真实访问域名和客户端信息
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # 如果后面页面有流式输出，这两项更稳妥
        proxy_http_version 1.1;
        proxy_buffering off;

        # 避免后端响应超时过短
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }
}
```

### 4.2 grok2api 后台站点

适用目标：

- `https://grok-admin.example.com` -> `http://127.0.0.1:8000`

```nginx
server {
    listen 80;
    listen 443 ssl http2;
    server_name grok-admin.example.com;

    # 证书路径请按 1Panel 实际签发位置填写
    ssl_certificate     /www/sites/grok-admin.example.com/ssl/fullchain.pem;
    ssl_certificate_key /www/sites/grok-admin.example.com/ssl/privkey.pem;

    # grok2api 可能涉及文件上传、图片、视频相关请求，建议放大一点
    client_max_body_size 200m;

    location / {
        # 反代整个 grok2api 服务，而不是只转 /admin
        proxy_pass http://127.0.0.1:8000;

        # 透传真实来源信息
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # 对 SSE / WebSocket / 长连接更友好
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_buffering off;

        # grok2api 有流式返回，超时建议放宽
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
```

如果你的 OpenResty 主配置里还没有这段 `map`，需要放到 `http {}` 里：

```nginx
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}
```

说明：

- `proxy_buffering off`
  - 对 `text/event-stream` 很重要，避免 SSE 被缓冲
- `Upgrade` / `Connection`
  - 给 WebSocket 预留
- `proxy_read_timeout 3600s`
  - 避免长时间生成或流式输出时被代理层提前断开

## 5. 1Panel 里的实际操作建议

如果你是在 1Panel 中安装的 OpenResty，推荐这样做：

1. 在 1Panel 里新建两个站点
2. 站点一绑定 `console.example.com`
3. 站点二绑定 `grok-admin.example.com`
4. 给两个站点分别申请 SSL
5. 进入每个站点的 OpenResty 配置，把上面的 `location /` 或整段 `server` 配置按 1Panel 的管理方式填进去
6. 重载 OpenResty

如果 1Panel 的站点界面是“反向代理”模式而不是直接改完整配置，通常填下面这些参数即可：

- 控制台站点
  - 代理目标：`http://127.0.0.1:18600`

- grok2api 站点
  - 代理目标：`http://127.0.0.1:8000`

然后再到“高级配置”或“附加配置”里补这些常用项：

```nginx
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_http_version 1.1;
proxy_buffering off;
proxy_read_timeout 3600s;
proxy_send_timeout 3600s;
```

对于 `grok2api` 站点，再补：

```nginx
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection $connection_upgrade;
client_max_body_size 200m;
```

## 6. 如果你暂时没有域名

如果当前只有服务器 IP，没有域名，也可以用 OpenResty 对外再开两个端口，例如：

- `http://<服务器IP>:80` -> `127.0.0.1:18600`
- `http://<服务器IP>:8081` -> `127.0.0.1:8000`

示例：

```nginx
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:18600;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_buffering off;
    }
}

server {
    listen 8081;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
```

这种做法能用，但它本质上还是“换了两个对外端口”，不如子域名方案干净。

## 7. 不推荐的配置方式

### 7.1 不推荐只代理 `/admin`

例如下面这种不建议直接上生产：

```nginx
location /admin/ {
    proxy_pass http://127.0.0.1:8000/admin/;
}
```

原因：

- 后台页面不仅访问 `/admin/...`
- 它还会访问 `/v1/admin/...`
- 还会访问 `/static/...`
- 两个应用的 `/static/...` 又会互相冲突

所以只代理 `/admin` 路径通常是不完整的。

### 7.2 不推荐同域名路径拆分

下面这种也不推荐：

```nginx
location / {
    proxy_pass http://127.0.0.1:18600;
}

location /admin/ {
    proxy_pass http://127.0.0.1:8000/admin/;
}
```

原因同上，核心冲突点就是两个应用都用了绝对路径 `/static`。

## 8. 配好后如何验证

### 控制台验证

访问：

- `https://console.example.com`

确认：

- 页面能正常打开
- CSS 和 JS 正常加载
- 创建任务页面无静态资源 404

### grok2api 后台验证

访问：

- `https://grok-admin.example.com/admin`

确认：

- 会跳转到 `/admin/login`
- 登录页样式正常
- 登录后 `/admin/token`、`/admin/config`、`/admin/cache` 正常
- 浏览器开发者工具里没有 `/static/...` 或 `/v1/admin/...` 的 404

### SSE / WebSocket 验证

如果你后续还打算通过该域名直接用 `grok2api` 的聊天、绘图、视频等能力，再额外确认：

- 流式输出不被截断
- WebSocket 页面可正常连接

如果这部分异常，优先检查：

- `proxy_buffering off`
- `proxy_http_version 1.1`
- `Upgrade / Connection`
- `proxy_read_timeout`

## 9. 最终建议

对于你当前这个项目，最稳妥的 OpenResty 反代方式是：

- `console.example.com` -> `127.0.0.1:18600`
- `grok-admin.example.com` -> `127.0.0.1:8000`

不要把控制台和 `grok2api admin` 强行挂在同一个域名的不同路径下，除非你愿意继续改应用里的静态资源路径和后台页面路由。
