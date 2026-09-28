# Alertmanager 通用 Adapter 实施方案

## 1. 项目目标

开发一个统一的 `alertmanager-adapter` 服务，用于接收 Prometheus Alertmanager 的 Webhook 消息，并根据告警标签自动选择对应通知渠道和目标 Webhook。

核心路由维度：

- `environment`
- `severity`
- `team`

路由结果：

- `channels[]`

当前支持的通知渠道：

- `feishu`
- `dingtalk`
- `wecom`

Webhook 最终定位方式：

`environment + team + channel`

示例：

```text
environment=production
severity=critical
team=ops

=> channels=[feishu,dingtalk,wecom]

=> production + ops + feishu   -> PROD_OPS_FEISHU_WEBHOOK
=> production + ops + dingtalk -> PROD_OPS_DINGTALK_WEBHOOK
=> production + ops + wecom    -> PROD_OPS_WECOM_WEBHOOK
```

职责划分：

- Prometheus：产生告警、添加 `environment` 等外部标签
- Alertmanager：告警分组、抑制、repeat、severity 路由
- Adapter：解析告警、匹配业务路由、格式转换、发送、重试、日志、指标

Adapter 不负责重新实现 Alertmanager 的告警聚合和抑制逻辑。

---

## 2. 技术栈

使用：

```text
Python 3.12
uv（Python 环境与依赖管理）
FastAPI
Uvicorn
Pydantic
httpx
PyYAML
prometheus-client
tenacity
```

要求：

- 无数据库
- 无 Redis
- 无 Celery
- 无 Kafka / RabbitMQ
- 无 Web UI
- 服务必须无状态
- 配置来自 ConfigMap
- Secret 来自 Kubernetes Secret / 环境变量

---

## 3. 整体架构

```text
Prometheus
   |
   | alerts
   v
Alertmanager
   |
   | webhook JSON
   v
alertmanager-adapter
   |
   |-- 读取 environment
   |-- 读取 severity
   |-- 读取 team
   |
   |-- 匹配 routes
   |
   |-- 得到 channels[]
   |
   +--> Feishu
   +--> DingTalk
   +--> WeCom
```

多环境示例：

```text
production
  ops
    feishu
    dingtalk
    wecom

  backend
    feishu
    dingtalk

  dba
    feishu
    wecom

test
  ops
    feishu

dev
  ops
    feishu
```

---

## 4. 项目目录

按照以下目录实现：

```text
alertmanager-adapter/
├── app/
│   ├── main.py
│   │
│   ├── api/
│   │   └── alertmanager.py
│   │
│   ├── core/
│   │   ├── config.py
│   │   ├── logging.py
│   │   └── router.py
│   │
│   ├── models/
│   │   └── alertmanager.py
│   │
│   ├── services/
│   │   ├── dispatcher.py
│   │   ├── formatter.py
│   │   └── senders/
│   │       ├── base.py
│   │       ├── feishu.py
│   │       ├── dingtalk.py
│   │       └── wecom.py
│   │
│   └── utils/
│       └── helpers.py
│
├── config/
│   └── config.yaml
│
├── deploy/
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── configmap.yaml
│   ├── secret-example.yaml
│   └── servicemonitor.yaml
│
├── tests/
│   ├── test_router.py
│   ├── test_formatter.py
│   ├── test_dispatcher.py
│   └── test_alertmanager_api.py
│
├── Dockerfile
├── pyproject.toml
├── uv.lock
├── .python-version
├── README.md
└── .gitignore
```

---

## 5. API

提供以下接口：

### 5.1 Alertmanager Webhook

```http
POST /api/v1/alertmanager
```

接收 Alertmanager 标准 Webhook JSON。

### 5.2 健康检查

```http
GET /healthz
```

只检查进程是否存活。

### 5.3 就绪检查

```http
GET /readyz
```

至少检查：

- 配置成功加载
- 路由配置合法

不要检查外部飞书/钉钉/企微网络连通性，否则会导致 Pod 因第三方故障不断 NotReady。

### 5.4 Metrics

```http
GET /metrics
```

暴露 Prometheus metrics。

---

## 6. Alertmanager Payload

兼容 Alertmanager 标准 Webhook，例如：

```json
{
  "receiver": "adapter",
  "status": "firing",
  "groupLabels": {
    "alertname": "PodContainerCriticalMemoryUsage"
  },
  "commonLabels": {
    "alertname": "PodContainerCriticalMemoryUsage",
    "severity": "critical",
    "environment": "production",
    "team": "ops",
    "namespace": "production"
  },
  "commonAnnotations": {
    "summary": "Pod 容器内存使用率超过 Limit 的 90%"
  },
  "alerts": [
    {
      "status": "firing",
      "labels": {
        "alertname": "PodContainerCriticalMemoryUsage",
        "severity": "critical",
        "environment": "production",
        "team": "ops",
        "namespace": "production",
        "pod": "order-service-xxxxx",
        "container": "order-service"
      },
      "annotations": {
        "summary": "Pod 容器内存使用率超过 Limit 的 90%",
        "description": "当前 Memory Limit 使用率 95%"
      },
      "startsAt": "2026-09-23T08:00:00Z",
      "endsAt": "0001-01-01T00:00:00Z"
    }
  ]
}
```

Pydantic Model 需要兼容 Alertmanager 实际可能附带的额外字段，不要因为未知字段直接返回 422。

---

## 7. 标签获取规则

优先从：

```text
commonLabels
```

读取：

- `environment`
- `severity`
- `team`
- `alertname`

如果 `commonLabels` 中不存在，则从第一条：

```text
alerts[0].labels
```

读取。

默认值：

```text
environment -> unknown
severity    -> warning
team        -> ops
```

如果发生默认值兜底，需要记录 warning 日志：

```text
route_fallback=true
```

---

## 8. 路由模型

路由匹配核心维度：

```text
environment + severity + team
```

匹配后返回：

```text
channels[]
```

例如：

```text
production + critical + ops
=> feishu,dingtalk,wecom
```

第一版优先实现精确匹配。

允许后续扩展：

```text
team: "*"
severity: "*"
environment: "*"
```

如果实现通配符，优先级必须固定：

```text
完整精确匹配
>
单字段通配
>
多字段通配
>
default
```

但第一版可以只实现：

```text
精确匹配 + default
```

---

## 9. config.yaml

实现以下配置：

```yaml
server:
  host: 0.0.0.0
  port: 8080

routing:

  routes:

    - environment: production
      severity: critical
      team: ops
      channels:
        - feishu
        - dingtalk
        - wecom

    - environment: production
      severity: warning
      team: ops
      channels:
        - feishu

    - environment: production
      severity: critical
      team: backend
      channels:
        - feishu
        - dingtalk

    - environment: production
      severity: warning
      team: backend
      channels:
        - feishu

    - environment: production
      severity: critical
      team: dba
      channels:
        - feishu
        - wecom

    - environment: production
      severity: warning
      team: dba
      channels:
        - feishu

    - environment: test
      severity: critical
      team: ops
      channels:
        - feishu

    - environment: test
      severity: warning
      team: ops
      channels:
        - feishu

  default:
    channels:
      - feishu
    webhook_ref:
      feishu: DEFAULT_FEISHU_WEBHOOK


webhooks:

  production:

    ops:
      feishu: PROD_OPS_FEISHU_WEBHOOK
      dingtalk: PROD_OPS_DINGTALK_WEBHOOK
      wecom: PROD_OPS_WECOM_WEBHOOK

    backend:
      feishu: PROD_BACKEND_FEISHU_WEBHOOK
      dingtalk: PROD_BACKEND_DINGTALK_WEBHOOK

    dba:
      feishu: PROD_DBA_FEISHU_WEBHOOK
      wecom: PROD_DBA_WECOM_WEBHOOK

  test:

    ops:
      feishu: TEST_OPS_FEISHU_WEBHOOK
```

注意：

```text
PROD_OPS_FEISHU_WEBHOOK
```

表示环境变量名称，不是真实 URL。

代码通过：

```python
os.getenv("PROD_OPS_FEISHU_WEBHOOK")
```

读取真实 URL。

---

## 10. Webhook 获取

输入：

```text
environment=production
team=ops
channel=feishu
```

查找：

```yaml
webhooks:
  production:
    ops:
      feishu: PROD_OPS_FEISHU_WEBHOOK
```

得到：

```text
PROD_OPS_FEISHU_WEBHOOK
```

然后：

```python
webhook_url = os.getenv("PROD_OPS_FEISHU_WEBHOOK")
```

如果变量缺失：

- 记录 error
- 当前 channel 标记失败
- 不影响其他 channel
- 禁止打印完整 URL
- 禁止打印 token

---

## 11. Dispatcher

Dispatcher 负责：

1. 获取路由
2. 获取 channel 列表
3. 获取 Webhook
4. 调用不同 sender
5. 汇总结果

多个 channel 必须并行发送，例如使用：

```python
asyncio.gather(..., return_exceptions=True)
```

不要串行发送。

例如：

```text
alert
  |
  +--> Feishu
  +--> DingTalk
  +--> WeCom
```

某一个平台失败，不允许阻塞其他平台。

---

## 12. Sender 抽象

创建：

```text
app/services/senders/base.py
```

统一接口，例如：

```python
class BaseSender:
    async def send(
        self,
        webhook_url: str,
        message: NotificationMessage
    ) -> SendResult:
        ...
```

实现：

```text
FeishuSender
DingTalkSender
WeComSender
```

后续可以方便增加：

```text
SlackSender
TeamsSender
TelegramSender
```

---

## 13. 统一消息模型

先把 Alertmanager Payload 转成内部统一结构，再交给具体 Sender。

例如：

```text
NotificationMessage

status
alertname
severity
environment
team
namespace
summary
description
alerts_count
starts_at
alerts[]
```

不要在每个 Sender 中重复解析 Alertmanager Payload。

---

## 14. 告警展示格式

三个平台尽量保持一致。

FIRING：

```text
🚨 Kubernetes 告警

状态：FIRING
级别：CRITICAL
环境：production
团队：ops

告警：
PodContainerCriticalMemoryUsage

Namespace：
production

Pod：
order-service-7f987

Container：
order-service

描述：
Memory Limit 使用率 95%，存在 OOMKilled 风险。

开始时间：
2026-09-23 16:00:00

当前告警数量：
2
```

RESOLVED：

```text
✅ Kubernetes 告警恢复

状态：RESOLVED
级别：CRITICAL
环境：production
团队：ops

告警：
PodContainerCriticalMemoryUsage
```

如果一个 Alertmanager Group 中存在多个 alerts：

- 显示总数量
- 展示前 N 条，例如最多 10 条
- 超过 10 条时显示：

```text
其余 15 条告警已省略
```

避免单条消息过长。

---

## 15. 飞书

实现：

```text
app/services/senders/feishu.py
```

第一版建议：

```text
interactive card
```

如果实现复杂，可以先实现：

```text
post
```

必须支持：

- firing
- resolved

HTTP 客户端使用：

```text
httpx.AsyncClient
```

配置合理 timeout。

---

## 16. 钉钉

实现：

```text
app/services/senders/dingtalk.py
```

第一版使用：

```text
msgtype=markdown
```

例如：

```json
{
  "msgtype": "markdown",
  "markdown": {
    "title": "Kubernetes Critical Alert",
    "text": "..."
  }
}
```

第一版先支持普通机器人 Webhook。

代码结构预留：

```text
timestamp
sign
secret
```

以便后续支持加签机器人。

---

## 17. 企业微信

实现：

```text
app/services/senders/wecom.py
```

第一版使用机器人 Markdown 消息。

优先：

```text
markdown
```

如果当前机器人 API 支持且实现稳定，可选择：

```text
markdown_v2
```

不要让平台特定格式污染统一消息模型。

---

## 18. HTTP 重试

每个平台单独重试。

最多：

```text
3 次
```

退避：

```text
1s
2s
4s
```

建议使用：

```text
tenacity
```

重试策略：

```text
400 -> 不重试
401 -> 不重试
403 -> 不重试

408 -> 重试
429 -> 重试

500 -> 重试
502 -> 重试
503 -> 重试
504 -> 重试

timeout -> 重试
connection error -> 重试
```

所有请求必须设置 timeout。

---

## 19. API 返回策略

Alertmanager 请求成功被 Adapter 接收并完成一次发送流程后，HTTP 建议返回 200。

不要因为某一个第三方平台发送失败就返回 500，否则 Alertmanager 可能重复发送整批通知，造成其他已成功渠道重复告警。

Response 示例：

全部成功：

```json
{
  "status": "success",
  "environment": "production",
  "severity": "critical",
  "team": "ops",
  "channels": {
    "feishu": "success",
    "dingtalk": "success",
    "wecom": "success"
  }
}
```

部分成功：

```json
{
  "status": "partial_success",
  "channels": {
    "feishu": "success",
    "dingtalk": "failed",
    "wecom": "success"
  }
}
```

全部发送失败：

```json
{
  "status": "failed",
  "channels": {
    "feishu": "failed",
    "dingtalk": "failed"
  }
}
```

即使第三方全失败，只要请求 Payload 合法并已被 Adapter 正常处理，仍建议返回 HTTP 200。

以下情况可以返回 4xx：

- JSON 非法
- Payload 完全不符合 Alertmanager 格式
- 必要结构无法解析

---

## 20. 日志

建议 JSON 结构化日志。

日志至少包含：

```text
request_id
alertname
environment
severity
team
channel
status
http_status
duration_ms
route_match
fallback
```

示例：

```json
{
  "level": "INFO",
  "request_id": "6dc91...",
  "alertname": "PodContainerCriticalMemoryUsage",
  "environment": "production",
  "severity": "critical",
  "team": "ops",
  "channel": "feishu",
  "status": "success",
  "http_status": 200,
  "duration_ms": 123,
  "route_match": true,
  "fallback": false
}
```

严禁记录：

```text
完整 webhook URL
access token
secret
签名密钥
```

可以只记录目标平台，例如：

```text
target=feishu
```

---

## 21. Prometheus Metrics

使用：

```text
prometheus-client
```

暴露：

```text
GET /metrics
```

至少包含：

```text
alertmanager_adapter_requests_total

alertmanager_adapter_notifications_total

alertmanager_adapter_notification_failures_total

alertmanager_adapter_notification_duration_seconds

alertmanager_adapter_route_fallback_total
```

推荐 labels：

```text
environment
severity
team
channel
status
```

注意：

不要把：

```text
pod
alertname
namespace
```

全部作为 metrics labels，避免高基数。

示例：

```text
alertmanager_adapter_notifications_total{
  environment="production",
  severity="critical",
  team="ops",
  channel="feishu",
  status="success"
} 123
```

---

## 22. Kubernetes Secret

提供：

```text
deploy/secret-example.yaml
```

内容：

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: alertmanager-adapter-secret
  namespace: monitoring
type: Opaque

stringData:

  PROD_OPS_FEISHU_WEBHOOK: "https://example.invalid"
  PROD_OPS_DINGTALK_WEBHOOK: "https://example.invalid"
  PROD_OPS_WECOM_WEBHOOK: "https://example.invalid"

  PROD_BACKEND_FEISHU_WEBHOOK: "https://example.invalid"
  PROD_BACKEND_DINGTALK_WEBHOOK: "https://example.invalid"

  PROD_DBA_FEISHU_WEBHOOK: "https://example.invalid"
  PROD_DBA_WECOM_WEBHOOK: "https://example.invalid"

  TEST_OPS_FEISHU_WEBHOOK: "https://example.invalid"

  DEFAULT_FEISHU_WEBHOOK: "https://example.invalid"
```

只能提供示例值。

README 明确说明：

```text
真实 Secret 不要提交 Git。
```

---

## 23. ConfigMap

提供：

```text
deploy/configmap.yaml
```

将 config.yaml 挂载到：

```text
/app/config/config.yaml
```

应用默认从：

```text
CONFIG_PATH=/app/config/config.yaml
```

读取。

允许通过环境变量：

```text
CONFIG_PATH
```

覆盖默认路径。

---

## 24. Kubernetes Deployment

提供：

```text
deploy/deployment.yaml
```

要求：

```text
replicas: 2
```

建议：

```yaml
resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 500m
    memory: 512Mi
```

使用：

```yaml
envFrom:
  - secretRef:
      name: alertmanager-adapter-secret
```

ConfigMap 挂载：

```yaml
volumeMounts:
  - name: config
    mountPath: /app/config/config.yaml
    subPath: config.yaml
```

Readiness：

```text
GET /readyz
```

Liveness：

```text
GET /healthz
```

使用 ClusterIP，不需要 Ingress。

---

## 25. Service

提供：

```text
deploy/service.yaml
```

Service：

```text
alertmanager-adapter
```

Namespace：

```text
monitoring
```

端口：

```text
8080
```

Alertmanager 内部调用：

```text
http://alertmanager-adapter.monitoring.svc:8080/api/v1/alertmanager
```

---

## 26. ServiceMonitor

提供：

```text
deploy/servicemonitor.yaml
```

供 kube-prometheus-stack 自动抓取 Adapter：

```text
/metrics
```

注意：

ServiceMonitor labels 需要预留 kube-prometheus-stack 常见 selector，例如：

```yaml
labels:
  release: kube-prometheus-stack
```

---

## 27. Dockerfile

使用多阶段或精简 Python 镜像。

推荐：

```text
python:3.12-slim
```

要求：

- 非 root 用户运行
- 安装依赖后清理缓存
- 设置合理 WORKDIR
- 默认监听 8080
- CMD 使用 uvicorn

例如逻辑：

```text
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

不要使用 `--reload`。

---

## 28. Prometheus environment 标签

不要在每一条 PrometheusRule 手工添加：

```yaml
environment: production
```

建议 kube-prometheus-stack values：

生产：

```yaml
prometheus:
  prometheusSpec:
    externalLabels:
      environment: production
```

测试：

```yaml
prometheus:
  prometheusSpec:
    externalLabels:
      environment: test
```

开发：

```yaml
prometheus:
  prometheusSpec:
    externalLabels:
      environment: dev
```

这样所有告警自动携带：

```text
environment
```

---

## 29. PrometheusRule team 标签

每条告警需要明确责任团队。

Kubernetes 基础设施告警：

```yaml
labels:
  severity: critical
  team: ops
```

应用告警：

```yaml
labels:
  severity: warning
  team: backend
```

数据库告警：

```yaml
labels:
  severity: critical
  team: dba
```

AI / MaaS：

```yaml
labels:
  severity: warning
  team: ai
```

---

## 30. AlertmanagerConfig

Alertmanager 只需要一个 Adapter Receiver。

示例逻辑：

```yaml
receivers:
  - name: adapter
    webhookConfigs:
      - sendResolved: true
        urlSecret:
          name: alertmanager-adapter-url
          key: url
```

Secret：

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: alertmanager-adapter-url
  namespace: monitoring

type: Opaque

stringData:
  url: "http://alertmanager-adapter.monitoring.svc:8080/api/v1/alertmanager"
```

Route：

```yaml
route:

  receiver: adapter

  groupBy:
    - environment
    - namespace
    - alertname

  groupWait: 30s
  groupInterval: 5m
  repeatInterval: 4h

  routes:

    - receiver: adapter
      matchers:
        - name: severity
          value: critical
          matchType: "="

      groupWait: 10s
      groupInterval: 2m
      repeatInterval: 1h

    - receiver: adapter
      matchers:
        - name: severity
          value: warning
          matchType: "="

      groupWait: 30s
      groupInterval: 5m
      repeatInterval: 4h
```

重要：

以下功能仍然由 Alertmanager 完成：

```text
group
inhibit
repeatInterval
severity routing
sendResolved
```

Adapter 不重复实现。

---

## 31. Critical 抑制 Warning

继续使用 Alertmanager 的 inhibitRules。

例如：

```text
PodContainerCriticalMemoryUsage
    inhibits
PodContainerHighMemoryUsage
```

要求：

```text
namespace
pod
container
```

相同。

Node Disk：

```text
NodeCriticalDiskUsage
    inhibits
NodeHighDiskUsage
```

要求：

```text
instance
mountpoint
device
```

相同。

PVC：

```text
PersistentVolumeClaimCriticalUsage
    inhibits
PersistentVolumeClaimHighUsage
```

要求：

```text
namespace
persistentvolumeclaim
```

相同。

不要把这个逻辑移到 Adapter。

---

## 32. 路由未匹配

任何未匹配 Route 的告警不能直接丢弃。

使用：

```yaml
default:
  channels:
    - feishu
```

并发送到：

```text
DEFAULT_FEISHU_WEBHOOK
```

日志：

```text
route_match=false
fallback=true
```

同时：

```text
alertmanager_adapter_route_fallback_total
```

加 1。

---

## 33. channel 发送失败

例如：

```text
feishu   success
dingtalk failed
wecom    success
```

行为：

- Feishu 正常完成
- WeCom 正常完成
- DingTalk 重试
- 重试失败后记录日志和 metrics
- 不影响其他 channel
- API 返回 partial_success
- HTTP 返回 200

---

## 34. 配置校验

应用启动时必须校验：

- routes 是否存在
- environment 是否为空
- severity 是否为空
- team 是否为空
- channels 是否合法
- channel 是否属于：
  - feishu
  - dingtalk
  - wecom
- webhooks 映射是否格式合法
- default route 是否存在

如果 config.yaml 本身非法：

- 应用启动失败
- `/readyz` 不可用
- 日志说明具体配置错误

不要静默忽略非法配置。

---

## 35. 单元测试

必须至少覆盖：

### Router

```text
production + critical + ops
=> feishu,dingtalk,wecom

production + warning + ops
=> feishu

production + critical + backend
=> feishu,dingtalk

test + critical + ops
=> feishu

不存在 route
=> default feishu
```

### 默认标签

```text
environment 缺失
=> unknown

team 缺失
=> ops

severity 缺失
=> warning
```

### Sender

Mock HTTP：

```text
Feishu 200
DingTalk 500 后重试成功
WeCom timeout 后最终失败
```

### Dispatcher

```text
一个 channel 失败
不影响其他 channel
```

### API

测试：

```text
有效 Alertmanager JSON
=> HTTP 200

非法 JSON
=> HTTP 400/422

firing
=> 正确格式

resolved
=> 正确格式
```

### Secret

确认日志不会出现：

```text
完整 webhook URL
token
secret
```

---

## 36. README

README 必须包含：

1. 项目用途
2. 架构说明
3. 本地运行
4. config.yaml 配置
5. Kubernetes Secret 配置
6. Docker build
7. Kubernetes deploy
8. AlertmanagerConfig 接入
9. Prometheus externalLabels 配置
10. PrometheusRule team label 使用
11. 飞书示例
12. 钉钉示例
13. 企业微信示例
14. curl 测试示例
15. Prometheus metrics 说明
16. 常见故障排查

---

## 37. 本地开发

支持：

```bash
uv sync --locked

export CONFIG_PATH=./config/config.yaml

export PROD_OPS_FEISHU_WEBHOOK="..."
export PROD_OPS_DINGTALK_WEBHOOK="..."
export PROD_OPS_WECOM_WEBHOOK="..."

uv run --locked uvicorn app.main:app --host 0.0.0.0 --port 8080

uv run --locked pytest -q
```

提供 curl 示例：

```bash
curl -X POST \
  http://127.0.0.1:8080/api/v1/alertmanager \
  -H 'Content-Type: application/json' \
  -d @tests/fixtures/alert-firing.json
```

建议增加：

```text
tests/fixtures/
```

例如：

```text
alert-firing.json
alert-resolved.json
alert-multiple.json
```

---

## 38. 非功能要求

### 安全

- Webhook URL 不能进入 Git
- Webhook URL 不能输出日志
- Secret 只能来自环境变量 / K8s Secret
- Kubernetes Service 使用 ClusterIP
- 不暴露公网

### 可维护性

- Sender 插件化
- Router 与 Sender 解耦
- Alertmanager Payload 与平台消息格式解耦
- 配置通过 YAML 管理
- 添加环境、team、channel 不需要修改核心代码

### 稳定性

- 全异步
- channel 并发发送
- timeout
- retry
- 异常隔离
- 两副本部署
- health/readiness
- Prometheus metrics

---

## 39. 第一版禁止实现

第一版不要增加：

```text
Redis
Celery
PostgreSQL
MySQL
Kafka
RabbitMQ
Web UI
用户系统
权限系统
动态数据库路由
复杂规则 DSL
配置中心
```

保持简单。

---

## 40. 验收标准

实现完成后必须满足：

### 功能

- Alertmanager 能成功 POST 告警到 Adapter
- Adapter 能解析 Alertmanager 标准 JSON
- 能根据 `environment + severity + team` 匹配路由
- 能得到多个 channels
- 能根据 `environment + team + channel` 获取对应 Webhook
- 支持飞书
- 支持钉钉
- 支持企业微信
- 支持 firing
- 支持 resolved
- 支持多个 Alert 聚合消息
- 支持 default fallback

### 稳定性

- 第三方平台 timeout 不拖死请求
- 单个平台失败不影响其他平台
- 支持自动重试
- 所有 HTTP 请求设置 timeout
- 服务无状态
- 可运行两个及以上 replicas

### 安全

- Git 中不存在真实 Webhook
- 日志中不存在真实 Webhook/token
- Secret 使用 K8s Secret

### 可观测性

- `/healthz`
- `/readyz`
- `/metrics`
- JSON 日志
- channel 发送成功/失败 metrics
- fallback metrics

### Kubernetes

以下资源可以直接 apply：

```text
Deployment
Service
ConfigMap
Secret Example
ServiceMonitor
```

Pod 能正常通过：

```text
livenessProbe
readinessProbe
```

---

# Codex 执行要求

请直接在当前项目目录完成实现，不要只输出设计方案。

执行顺序：

1. 创建完整项目目录
2. 实现 Pydantic Models
3. 实现配置加载和校验
4. 实现 Router
5. 实现统一 NotificationMessage
6. 实现 Feishu Sender
7. 实现 DingTalk Sender
8. 实现 WeCom Sender
9. 实现 Dispatcher
10. 实现 FastAPI API
11. 实现 health/readiness/metrics
12. 实现结构化日志
13. 实现 retry/timeout
14. 编写单元测试
15. 生成 Dockerfile
16. 生成 Kubernetes YAML
17. 编写 README
18. 运行测试
19. 修复所有测试失败
20. 最终给出：
    - 实现说明
    - 文件列表
    - 本地启动命令
    - Docker build 命令
    - Kubernetes 部署命令
    - Alertmanager 接入方式
    - 测试结果

不要引入不必要的数据库、中间件或复杂基础设施。

如遇到第三方机器人 API 格式差异，优先保持 Sender 独立，不要修改 Router 和 Dispatcher 的核心接口。
