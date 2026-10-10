# docker-nginx-reload

Minimal demo: **nginx → gateway → business**，用 Docker Compose 组装。

目标：

1. 复现 gateway recreate 换 IP 后，nginx 转发失败（502）
2. 用动态 DNS 解析修复该问题

## Architecture

```
client -> nginx(:8080) -> gateway(:8080) -> business(:8000 /hello)
```

| Service  | Role                                         | Language |
|----------|----------------------------------------------|----------|
| nginx    | reverse proxy to gateway                     | nginx    |
| gateway  | forwards `/` to business `/hello`            | Go       |
| business | returns `{"message":"hello from business"}`  | Python   |

Compose 网络使用固定网段 `172.28.0.0/16`，以便用 `docker run --ip` 占住旧 IP。

## Run

```bash
docker compose up --build -d
curl -i http://localhost:8080/
# expect 200 + {"message":"hello from business"}
```

---

## 问题配置（会复现 502）

`nginx/nginx.conf` 里如果写成静态 `upstream`，nginx **只在加载配置时解析一次** `gateway` DNS：

```nginx
http {
    upstream gateway_upstream {
        server gateway:8080;   # 启动时解析，之后不再更新
    }

    server {
        listen 80;

        location / {
            proxy_pass http://gateway_upstream;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_connect_timeout 2s;
            proxy_read_timeout 5s;
        }
    }
}
```

gateway 容器 recreate 后拿到新 IP，nginx 仍访问旧 IP → **502 Bad Gateway**。  
注意：单独 `docker compose up -d --force-recreate gateway` 经常会复用同一个 IP，不一定能复现。

---

## 复现命令（强制换 IP）

先把 nginx 改成上面的「问题配置」，然后：

```bash
# 0) 重建环境（改过 network subnet / nginx 配置后建议执行）
docker compose down
docker compose up --build -d

# 1) 确认通路正常
curl -i http://localhost:8080/

# 2) 记录当前 gateway 容器 IP（字段 IPAddress，不是 Gateway）
OLD_IP=$(docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' demo-gateway)
echo "old gateway ip: $OLD_IP"

# 3) 删掉 gateway，用临时容器占住旧 IP（否则 Docker 常把同一 IP 再分给新 gateway）
docker compose stop gateway
docker compose rm -f gateway

docker run -d --name ip-holder \
  --network docker-nginx-reload_demo \
  --ip "$OLD_IP" \
  alpine sleep 3600

# 4) 重新启动 gateway，确认 IP 已变化
docker compose up -d gateway
NEW_IP=$(docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' demo-gateway)
echo "new gateway ip: $NEW_IP"

# 5) 问题配置下：通常返回 502
curl -i http://localhost:8080/

# 6) reload nginx 后会重新解析 DNS，临时恢复
docker compose exec nginx nginx -s reload
curl -i http://localhost:8080/

# 7) 清理占位容器
docker rm -f ip-holder
```

如果 `docker run --ip` 报错：

```text
user specified IP address is supported only when connecting to networks with user configured subnets
```

说明网络没有自定义 subnet。确认 `docker-compose.yml` 里有：

```yaml
networks:
  demo:
    driver: bridge
    ipam:
      config:
        - subnet: 172.28.0.0/16
```

然后执行 `docker compose down && docker compose up --build -d` 重建网络。

---

## 修复配置（当前仓库默认）

修改点：使用 Docker 内置 DNS `127.0.0.11`，并把 upstream 放到变量里再 `proxy_pass`，让 nginx **按请求（或 `valid` TTL）重新解析**。

**Before（有问题）：**

```nginx
upstream gateway_upstream {
    server gateway:8080;
}

location / {
    proxy_pass http://gateway_upstream;
}
```

**After（已修复，见 `nginx/nginx.conf`）：**

```nginx
http {
    # Docker embedded DNS
    resolver 127.0.0.11 valid=5s ipv6=off;

    server {
        listen 80;
        server_name _;

        location / {
            set $gateway_upstream gateway:8080;
            proxy_pass http://$gateway_upstream;   # 变量触发运行时 DNS 解析
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_connect_timeout 2s;
            proxy_read_timeout 5s;
        }
    }
}
```

要点：

| 改动 | 作用 |
|------|------|
| `resolver 127.0.0.11` | 使用 Docker 嵌入式 DNS |
| `valid=5s` | DNS 结果最多缓存 5 秒 |
| `set $gateway_upstream ...` + `proxy_pass http://$var` | 强制运行时解析；静态 `upstream` / 非变量 `proxy_pass` 不会这样 |

---

## 验证修复仍然有效

使用当前（修复后）配置，重复上面的「复现命令」第 1–5 步：

```bash
docker compose up --build -d nginx   # 确保用的是修复后的 nginx 镜像

# ... 占旧 IP + recreate gateway（同上方第 2–4 步）...

# DNS cache 最多 valid=5s，稍等再请求
sleep 6
curl -i http://localhost:8080/
# expect 200（无需 nginx -s reload）

docker rm -f ip-holder
```

---

## Cleanup

```bash
docker rm -f ip-holder 2>/dev/null || true
docker compose down
```
