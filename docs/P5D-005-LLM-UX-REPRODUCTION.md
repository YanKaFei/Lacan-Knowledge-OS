# P5D-005 — 真实 LLM 接口可用性（复现 / 设计 / 验证）

- 阶段：LLM Interface Usability（**产品层**）
- 缺陷登记：`_data/daily_use/defects/P5D-005_llm_interface_usability.md`
- 结论：**FIXED**。全量回归 **144 套件 + 78 校验器，`failed=[]` / `skipped=[]` / `quick_mode=false` / `exit_code=0`**
  （`_data/index/TEST_RUN.json`，`recorded_at=2026-09-29T17:11:10Z`）；
  冻结核心与谱系**均未变**（见 §6）。
- HEAD：`f70402e5b852923028283c93f81dbfb12f1911f4`（改动前 = 改动后）

---

## 1. 修的是什么（用户视角）

一次真实 LLM 研究要等 **45–60 秒**。修复前这段时间里，界面只有一句静态文案，
而且**没有地方**看模型、看凭据、换端点、重试或分辨"这次是真算还是命中缓存"。
修完之后：

| 用户的问题 | 修复前 | 修复后 |
|---|---|---|
| 还要等多久？在干什么？ | 静态一句 `Researching corpus…` | 真实秒表 `Working… 12s · corpus retrieval → evidence contract (…)`，逐秒递增 |
| 能不等了吗？ | 点了只是"别再等了" | 同上，但长请求已作业化，**提交 0.007s 返回**，页面不再假死 |
| 用的是哪个模型？ | 看不到 | 答案头部 `llm: deepseek-chat · 44.6s · computed now` |
| 这次是缓存还是真算？ | 一样，看不出来 | `served from cache` / `computed now` / `forced recompute` |
| 想换模型怎么办？ | 只能改环境变量再重启 | **Model provider settings** 面板：改 Model / Base URL → Save → 下次研究生效 |
| 凭据配好了吗？ | 失败后才知道 | 面板显示 `Credentials: found (~/.dsh/.credentials.yaml)`（只报有没有） |
| 端点通不通？ | 只能发一次研究试试 | **Test connection**：真发一次 `max_tokens=4` 的极小请求，报状态/耗时/端点回的模型名 |
| 失败了只能重打一遍？ | 是 | 错误卡给出 **Retry once**（**只**对基础设施类失败，且只重发 1 次）+ **Open provider settings** |

## 2. 修复前实测（本机真实产品路径）

| 场景 | 实测 |
|---|---|
| `provider=mock` | 16.7 s → `VALIDATED_WITH_QUALIFICATIONS`（3 claims / 3 citations）|
| `provider=llm` | 44.6 s / 61.8 s → 1 claim |
| 不同问题 | 28.3 s → `VALIDATION_FAILED` |
| 弃权类问题 + `llm` | 21.3 s → `ABSTAINED`（**没有**调用模型）|
| 无凭据 + `llm` | `PROVIDER_UNAVAILABLE`（`research_disabled=false`）|
| 同一问题再问 | 0.0 s（命中产品缓存）|

数字都对，问题是**这些数字当时一个也没有出现在界面上**。

## 3. 根因

- **RC-A（等待不可见）**：产品与核心之间是**一次阻塞往返**；核心的 `_audit` 只在返回后才存在，
  没有任何中途进度可读。产品层既没计时，也没作业化。
- **RC-B（设置无入口）**：provider 只由进程环境变量构造（核心每请求构造
  `OpenAICompatibleProvider(timeout=120)`）；MCP 的 `lacan.research` **没有** `model` 参数
  （scholarly schema 禁改），产品层没有任何设置面，也没有让 MCP 子进程重新继承环境的手段。
- **RC-C（失败无恢复）**：`api.research` 里没有任何重试；而"重试"必须有纪律 ——
  学术判定（`VALIDATION_FAILED` / `ABSTAINED`）重发一次不会变成证据。
- **RC-D（溯源缺失）**：`view.advanced` 只有核心给的 `provider` / `duration_ms`；
  产品层没有把自己**实测**的东西（墙钟、缓存、尝试次数、配置里的模型名）附上去，
  `render.js` 也没有渲染。

## 4. 设计与实现（只加不减，全部可关）

| 能力 | 实现位置 | 对外接口 |
|---|---|---|
| 作业化长请求 | `workspace_ui/server/jobs.py`（有界 24 条，daemon 线程）| `POST /api/research/job` → **202** + `job_id`；`GET /api/research/job?id=`；`&result=1` 只在 DONE 时交付结果 |
| 真实进度 | `jobs.progress()` | 只报 `RUNNING/DONE/FAILED` + **真实 `elapsed_ms`**（不编百分比）|
| provider 设置 | `workspace_ui/server/provider_view.py` | `GET/POST /api/provider/settings`；落盘 `_workspace/settings/provider.json`（USER_WORKSPACE）；保存后写 `os.environ` + `reset_shared_client()` |
| 连通性自检 | `provider_view.test_connection()` | `POST /api/provider/test`（20 s 上限，只回状态/耗时/模型名/错误**类型**）|
| 有界重试 | `api.research(..., retry=True)` | **只**对 `PROVIDER_UNAVAILABLE` / `PROVIDER_CALL_FAILED` 重发 1 次，第二次绕过缓存；记 `attempts` / `retry_reason` |
| 缓存控制 | `api.research(..., use_cache=)` + `/api/research` 的 `fresh` | `use_cache=False` 真重算 |
| 实测溯源 | `api._provenance()` → `view.advanced` | `provider_model` / `wall_ms` / `cached` / `attempts` / `retry_reason` / `fresh_requested` |
| 溯源展示 | `render.js::provenanceNode` → `#answer-provenance` | `mock adapter (no model call) · 16.7s · computed now` |
| 等待体验 | `app.js`（`startWait/waitTick`、`runAsJob`）| 真实秒表 + 中性阶段文字 + 真能用的 Stop waiting |
| 失败可操作 | `renderError()` 的 `#error-actions` | 后端**显式**给 `actions`，前端只渲染与执行，不猜 |
| 设置入口按钮 | `index.html #provider-panel` + i18n（新增 21 个 key）| 面板文案随语言即时切换（无需刷新）|

**没有改**：冻结核心、`scholarly_api`（product_boundary 3 个组件哈希一致）、
MCP `lacan.research` 输入 schema、任何答案状态判定、任何 canonical 数据。

## 5. 验证

### 5.1 新增测试（23 项）

| 套件 | 项数 | 覆盖 |
|---|---|---|
| `_scripts/_tests/test_llm_ux.py` | 14 | 设置形状/不回显密钥/非法值拒绝/坏持久化文件不灌环境/自检如实失败/作业生命周期与有界性/**重试纪律**（基础设施重发 1 次、`VALIDATION_FAILED`+`ABSTAINED`+`INSUFFICIENT_EVIDENCE` 永不重发）/mock 无模型调用/fresh 绕过缓存/无密钥材料 |
| `_scripts/_tests/test_llm_ux_job.py` | 2 | 真实 MCP → 核心 → **本地 OpenAI 兼容 stub**（故意 sleep 3 s）：提交 `0.007 s` 返回、40 次轮询 `elapsed_ms` 单调递增、DONE 后按需取结果、`provider_model`/`wall_ms` 实测、端点**恰好收到 1 次**请求；未知 job 如实报 `JOB_NOT_FOUND` |
| `_scripts/_tests/test_llm_ux_browser.py` | 7 | 真实 Chrome：面板可见且已填充、连通性自检如实、mock 溯源正则、`forced recompute`、等待秒数递增+取消文案、失败重试与两个动作按钮（并断言 Advanced 里 `attempts 2`）、新增文案 zh/en 即时切换（`no_reload=true`，0 console error）|

证据：`_workspace/ui_qa/p5d005_job_evidence.json`、
`_workspace/ui_qa/p5d005_llm_ux_browser.json`、
`_workspace/ui_qa/p5d005_suite_timing_final2.tsv`、
`_workspace/ui_qa/p5d005_regression_final2.log`。

### 5.2 浏览器实测（节选，全部 PASS）

```
test_01  model=deepseek-chat · base_url=https://api.deepseek.com/v1
         cred="Credentials: found (~/.dsh/.credentials.yaml)"
         cap ="Per-call cap: 120s (fixed in the frozen core; the product cannot change it)."
test_02  "OK · deepseek-flash · 1.12s"          ← 端点真的回答了（回显的模型名由端点解析决定）
test_03  "mock adapter (no model call) · 27.6s · computed now"
test_04  "mock adapter (no model call) · 1.2s · computed now · forced recompute"
test_05  "Working… 0s …" → "Working… 2s …" → "Stopped waiting. The backend job may still be running."
test_06  badge=PROVIDER_UNAVAILABLE · actions=["retry_once","provider_settings"] · attempts 2
test_07  面板标签 en↔zh 即时切换（"模型提供方设置" / "单次调用上限：120 秒…"），无刷新、0 console error
```

### 5.3 真实入口（127.0.0.1:3090）实测

- `POST /api/research/job` → **202，0.001 s**；36 次轮询 `RUNNING` 递增至 17 181 ms；
  DONE 17 619 ms；`advanced.wall_ms=17612`、`provider=mock`、`provider_model=null`、
  `provider_model_note="no model call (deterministic mock adapter)"`、`attempts=1`。
- 缓存：同一问题再问 `0.01 s`（`cached=true`）；`fresh:true` → `4.64 s`（`cached=false`、`fresh_requested=true`）。
- `GET /api/provider/settings` → 模型/端点/凭据来源/只读上限；`persisted=false`（未改用户设置）。

### 5.4 全量回归（绿）

```
_data/index/TEST_RUN.json
  suites = 144 · checks(validators) = 78 · failed_suites = [] · skipped = [] · quick_mode = false
  exit_code = 0 · recorded_at = 2026-09-29T17:11:10Z
耗时 top：test_phase2_deterministic 602.0s · phase4e_real_provider_smoke 284.8s ·
          phase4c1d_llm_integration 185.7s · **test_llm_ux_browser 76.2s** · **test_llm_ux_job 19.6s** ·
          **test_llm_ux 0.1s**
```

## 6. 边界与不变量（改后逐条复核）

| 检查 | 结果 |
|---|---|
| `core_freeze.py --verify` | **PASS**：39 个组件哈希一致（semantic=30 / product=3 / data_version=6）|
| `freeze_lineage.py --verify` | **PASS**：7 段；`semantic=0` / data_version=1 / product_runtime=6 |
| `check_ui_artifacts.py --url :3090` | **PASS**：16 个资产逐字节一致；入口模块与 i18n 词典均可服务 |
| `build_i18n.py --check` | **0 problems**；词典 460 条 = 364 translated / 70 hardcoded / 26 intentional（新增 21 条）|
| 密钥纪律 | 产品 API 不接受密钥、不落盘、不回显（专门测试扫返回值）；错误只报**类型** |
| MCP schema | `lacan.research` 输入未加字段（模型只能经环境变量生效）|
| 学术语义 | `VALIDATION_FAILED` / `ABSTAINED` / `INSUFFICIENT_EVIDENCE` 不重试、不改写；`ABSTAINED` 仍不调用模型 |
| HEAD | `f70402e5b852…` 改动前后一致 |

## 7. 过程中发现并修掉的两个问题（如实记录）

### 7.1 新控件缺可访问名（被 5A 套件当场抓住）

`#fresh-toggle` / `#provider-model` / `#provider-base-url` 三个 `<input>` 只有包裹式 `<label>`，
项目自己的无障碍审计（`check_accessibility.py`）不认这种写法 → `NO_ACCESSIBLE_NAME`，
`test_phase5a_accessibility` 与 `test_phase5a_keyboard_flows` 失败。
**修法**：给三个控件加 `aria-label` + `data-i18n-attr="aria-label"` + `data-i18n=<key>`
（既可访问名，又随语言切换）。两套件随后 OK。

### 7.2 测试夹具把自己的坏端点留成了"用户设置"（P5D-005-T1）

浏览器套件的失败路径用例会把 `base_url` 改成 `https://127.0.0.1:9/v1` 来验证重试。
第一次全量回归里，这个**测试端点泄漏**成了 `_workspace/settings/provider.json`，
于是**别的**套件（`test_llm_ux_job`）启动时被 `make_server → apply_persisted()` 换了端点，
表现为"成功路径竟然重试了"（`attempts=2`）——一次看起来很产品化的假象，根因是测试污染。

**修法（两处，都不弱化断言）**：
1. 测试自洽：`test_llm_ux_job` 在 `make_server()` **之后**重新钉住自己的 stub fixture，
   并当场断言 `effective()` 的端点/模型确实是 stub（不符就报"持久化设置偷改了端点"）；
   两套件都在 `tearDownClass` 还原环境变量与设置文件，并**断言文件状态与开始前一致**。
2. 产品加固：`apply_persisted()` 现在**先校验后应用** —— 坏掉的 `model` / `base_url`
   不再被灌进环境，而是记进 `LAST_APPLY["rejected"]`（新增测试覆盖）。
   理由：一个坏值会静默地让每一次研究都打到一个不存在的端点，而界面看不出来。

回归复现验证：**故意**预置那个坏设置文件后重跑三个新套件 → 23/23 OK，文件状态原样还原；
随后清掉该文件，全量回归 144 套件全绿。

### 7.3 环境瞬态（非本阶段引入，如实登记）

第一次全量回归里 `test_phase4e_real_abstention` 失败（`abstention` 块缺 `reason_codes`）；
**孤立重跑 3/3 OK**（103 s / 135 s / 103 s），最终回归里 OK 21.6 s。
这是该套件依赖真实模型输出的既有瞬态（历史记录里已有同类条目），与本阶段改动无关，未做任何"重跑到过"的处理。

## 8. 诚实边界（没做，以及为什么）

- **没有给核心加进度回调**：那要改冻结核心。所以进度只报"已耗时 + 阶段说明"，
  **不是**百分比进度条 —— 没有那个数据就不画它。
- **Stop waiting 不取消后端作业**：MCP 是一次阻塞往返，无法中断；文案如实写
  "The backend job may still be running."
- **没有 token / 成本统计**：核心 `audit` 不暴露 usage（实测 `usage-ish keys: []`）；
  产品层的自检会显示探测请求的 usage，但研究答案里不编。
- **重试次数固定 1 次**，且只在"请求开启缓存"的那一次研究上生效：
  基础设施抖动值得再试一次，但重试不该放大成重复计费，也不该被当成"重跑学术判定"。
- **模型名显示的是配置值**：`Test connection` 会另外显示端点**回显**的模型
  （实测同一请求配置 `deepseek-chat`、端点回显 `deepseek-flash`）—— 两个都如实并列，不合并。

## 9. 复现命令

```bash
cd <REPO>

# 1) 三个新套件
python3 -m unittest _scripts._tests.test_llm_ux
python3 -m unittest _scripts._tests.test_llm_ux_job
python3 -m unittest _scripts._tests.test_llm_ux_browser

# 2) 全量回归（要求 failed=[] 且 skipped=[]）
LACAN_SUITE_TIMING=_workspace/ui_qa/suite_timing.tsv bash _scripts/run_all_tests.sh

# 3) 不变量
python3 _scripts/_tools/core_freeze.py --verify
python3 _scripts/_tools/freeze_lineage.py --verify
python3 _scripts/_tools/build_i18n.py --check
python3 _scripts/_tools/check_ui_artifacts.py --url http://127.0.0.1:3090

# 4) 日用入口（改后需重启才吃到新路由）
bash _scripts/runtime/stop_lacan_os.sh && LACAN_NO_OPEN=1 bash _scripts/runtime/start_lacan_os.sh
```
