# Alertmanager Adapter

无状态的 Alertmanager Webhook 适配器。按告警的 `environment + severity + team` 精确匹配路由，再按 `environment + team + channel` 找到环境变量中的机器人 Webhook，同时发送到飞书、钉钉和企业微信。告警分组、抑制和重复发送仍由 Alertmanager 管理。

## 工作方式

`Prometheus → Alertmanager → POST /api/v1/alertmanager → Router → Dispatcher → 平台机器人`。

同一组消息的多个平台并发发送。每个平台最多尝试 3 次，重试 408、429、5xx、连接失败和超时。单个平台失败时其他平台继续发送，合法请求返回 HTTP 200，响应体的 `status` 为 `success`、`partial_success` 或 `failed`。这避免 Alertmanager 因一个平台失败而重发已成功的平台消息。

## 本地运行

需要 [uv](https://docs.astral.sh/uv/)；项目通过 `.python-version` 固定 Python 3.12，并用 `pyproject.toml` 与 `uv.lock` 管理依赖。首次执行 `uv sync --locked` 会创建 `.venv` 并安装运行与测试依赖，无需手工创建虚拟环境或激活。请从项目根目录运行：

```bash
uv sync --locked
export CONFIG_PATH=./config/config.yaml
export PROD_OPS_FEISHU_WEBHOOK="https://..."
export PROD_OPS_DINGTALK_WEBHOOK="https://..."
export PROD_OPS_WECOM_WEBHOOK="https://..."
uv run --locked uvicorn app.main:app --host 0.0.0.0 --port 8080
```

PowerShell 设置配置路径：`$env:CONFIG_PATH="./config/config.yaml"`；Webhook 变量同样使用 `$env:变量名="..."`。运行测试：`uv run --locked pytest -q`。更新运行依赖使用 `uv add 包名`，更新测试依赖使用 `uv add --dev 包名`，并提交更新后的 `pyproject.toml` 与 `uv.lock`。

只需设置当前路由实际发送所需的 Webhook 环境变量；缺少某个平台的变量会将该平台标记失败并写入不含 URL 的日志。`GET /healthz` 检查进程；`GET /readyz` 表示配置已成功加载；`GET /metrics` 输出 Prometheus 指标。配置无效时应用启动失败。

## 路由配置与 Secret

编辑 [config/config.yaml](config/config.yaml)。`routing.routes` 使用精确的 `environment`、`severity`、`team` 组合；`channels` 可选 `feishu`、`dingtalk`、`wecom`。未匹配时使用 `routing.default`，默认发送到 `DEFAULT_FEISHU_WEBHOOK`，不会丢弃。`webhooks.production.ops.feishu: PROD_OPS_FEISHU_WEBHOOK` 是**环境变量名称**，不是 URL。新增路由时同时添加对应 `webhooks` 映射。缺少路由、默认路由、映射或非法 channel 会导致启动失败。

真实 Webhook URL 仅放在环境变量或 Kubernetes Secret 中。**真实 Secret 不要提交 Git**；[secret-example.yaml](deploy/secret-example.yaml) 只有无效示例 URL。日志只记录平台、状态和错误类型，不记录请求 URL、token、响应正文或异常正文。

## Docker 与 Kubernetes

```bash
docker build -t your-registry/alertmanager-adapter:1.0.0 .
docker push your-registry/alertmanager-adapter:1.0.0
```

镜像构建使用锁文件执行 `uv sync --frozen --no-dev`，只安装运行依赖。

将 [deployment.yaml](deploy/deployment.yaml) 的 `image` 改为推送后的不可变镜像标签。创建 `monitoring` 命名空间，并从安全来源创建 `alertmanager-adapter-secret`，其中的键名与 `config.yaml` 的引用一致。随后：

```bash
kubectl apply -f deploy/configmap.yaml
kubectl apply -f deploy/service.yaml
kubectl apply -f deploy/servicemonitor.yaml
kubectl apply -f deploy/deployment.yaml
kubectl -n monitoring rollout status deployment/alertmanager-adapter
```

ConfigMap 挂载到 `/app/config/config.yaml`，`CONFIG_PATH` 可覆盖此路径。部署为 2 个副本，Service 使用 ClusterIP。修改路由时同步更新 `config/config.yaml` 与 `deploy/configmap.yaml`；修改 ConfigMap 后重启 Deployment 以重新加载。

## Alertmanager 接入

Webhook 地址：`http://alertmanager-adapter.monitoring.svc:8080/api/v1/alertmanager`。可参考 [AlertmanagerConfig 示例](deploy/alertmanagerconfig-example.yaml) 和 [URL Secret 示例](deploy/alertmanager-adapter-url-example.yaml)。确保 `AlertmanagerConfig` 的标签与实际 Prometheus Operator 的 selector 匹配，然后按集群配置应用。`sendResolved: true` 负责恢复通知。路由的 `groupBy`、`groupWait`、`groupInterval`、`repeatInterval` 以及 critical 抑制 warning 规则在 Alertmanager 中维护；不要在 Adapter 中重复配置。

在 kube-prometheus-stack values 的 `prometheus.prometheusSpec.externalLabels` 设置环境，例如 `environment: production`。PrometheusRule 为每条规则设置 `team: ops`、`backend`、`dba` 等责任团队，并设置 `severity`。缺失标签时 Adapter 分别使用 `environment=unknown`、`severity=warning`、`team=ops`，记录 warning；若未匹配路由，会发送到默认 Webhook。

## 平台消息示例

飞书使用 `post` 富文本消息，标题为“Kubernetes 告警”，正文包含状态、级别、环境、团队和最多 10 条告警。钉钉使用 `msgtype=markdown`，企业微信使用 `msgtype=markdown`，两者正文同样包含上述内容。恢复消息标题显示“告警恢复”。钉钉第一版支持普通机器人 Webhook；加签机器人需要后续扩展 sender。

## curl 验证

以下命令均在项目根目录使用 PowerShell 执行。先运行一次 `uv sync --locked`。飞书和钉钉分别测试；切换测试目标时，在终端 1 按 `Ctrl+C` 停止服务，设置对应的 Webhook 环境变量后重新启动。环境变量只对启动它的终端及其子进程生效。**真实 Webhook URL 不要写入 fixture、配置文件或提交到 Git。**

### 测试飞书群告警

fixture `tests/fixtures/alert-test-feishu.json` 使用 `environment=test`、`severity=critical`、`team=ops`，只命中飞书路由。

**终端 1：配置并启动服务**

```powershell
$env:CONFIG_PATH = "./config/config.yaml"
$env:TEST_OPS_FEISHU_WEBHOOK = "你的飞书机器人 Webhook URL"
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8080
```

**终端 2：发送测试告警**

```powershell
curl.exe -X POST http://127.0.0.1:8080/api/v1/alertmanager `
  -H "Content-Type: application/json" `
  --data-binary "@tests/fixtures/alert-test-feishu.json"
```

飞书群收到消息后，响应应包含 `"status":"success"` 和 `"channels":{"feishu":"success"}`。

### 测试钉钉群告警

fixture `tests/fixtures/alert-test-dingtalk.json` 使用 `environment=test`、`severity=critical`、`team=ops-dingtalk-smoke`，只命中钉钉路由。

**终端 1：配置并启动服务**

```powershell
$env:CONFIG_PATH = "./config/config.yaml"
$env:TEST_OPS_DINGTALK_WEBHOOK = "你的钉钉机器人 Webhook URL"
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8080
```

**终端 2：发送测试告警**

```powershell
curl.exe -X POST http://127.0.0.1:8080/api/v1/alertmanager `
  -H "Content-Type: application/json" `
  --data-binary "@tests/fixtures/alert-test-dingtalk.json"
```

钉钉群收到消息后，响应应包含 `"status":"success"` 和 `"channels":{"dingtalk":"success"}`。该版本支持普通钉钉机器人 Webhook；需要加签的机器人须先扩展钉钉 Sender。

### 通用 Alertmanager Payload 示例

以下原有 fixture 使用 `production` 环境，会按生产路由发送；只验证测试群时请使用上面两份 `alert-test-*.json`。

```bash
curl -X POST http://127.0.0.1:8080/api/v1/alertmanager \
  -H 'Content-Type: application/json' \
  -d @tests/fixtures/alert-firing.json

curl -X POST http://127.0.0.1:8080/api/v1/alertmanager \
  -H 'Content-Type: application/json' \
  -d @tests/fixtures/alert-resolved.json
```

发送结果示例：`{"status":"partial_success","environment":"production","severity":"critical","team":"ops","channels":{"feishu":"success","dingtalk":"failed","wecom":"success"}}`。Payload 无效时返回 422。

## 监控与排查

`alertmanager_adapter_requests_total` 统计已处理请求；`alertmanager_adapter_notifications_total`、`alertmanager_adapter_notification_failures_total` 与 `alertmanager_adapter_notification_duration_seconds` 分平台统计发送；`alertmanager_adapter_route_fallback_total` 统计默认路由。指标标签只使用环境、级别、团队、平台和状态，不使用 Pod 或告警名。

- `/readyz` 不可用：检查容器启动日志中的配置校验位置，以及 ConfigMap 挂载路径。
- 响应 `failed` 且错误类型为 `MissingWebhookEnv`：检查 Secret 键名与 `webhooks` 引用一致，且 Pod 已重启读取新 Secret。
- 平台返回 400/401/403：检查机器人 Webhook、权限和平台安全策略；这些状态不重试。
- 平台超时或 5xx：每个 channel 最多尝试 3 次；查看通知失败指标与结构化日志中的 `request_id`、`channel`、`http_status`。
- 走了默认路由：检查 `commonLabels` 与首条告警的 `environment`、`severity`、`team`；查看 `route_match=false` 日志和 fallback 指标。
