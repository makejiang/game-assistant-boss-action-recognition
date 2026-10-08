---
name: game-assistant-boss-action-recognition
description: "体验 Boss 招式识别游戏助手（《鬼武者：剑之道》，Boss 佐佐木岩流）。用于用户说'打开 Boss 招式识别'、'启动招式识别助手'、'我要用鬼武者助手'、'Boss 招式识别 Demo' 等场景：先弹窗提醒已支持游戏；再确保游戏助手服务已开启（未启动时自动部署，服务端与模型会自动检测更新，模型清单见 models），随后确保 BAR / Knowledge 子服务开启；最后以 BARDemo/ 为工作目录启动 BARDemo.exe。用户说'关闭服务'、'停止服务'、'关掉服务'等时判定为关闭服务：一条 shutdown 命令先结束 BARDemo.exe 再关闭游戏助手服务。"
argument-hint: "可选：用户原话（例如：打开 Boss 招式识别）"
user-invocable: true
models: Action,ASR,LLM,Embedding,OCR,Rerank,Splitter        # 模型下载策略：all=全部下载；skip=跳过下载；<模型名列表>=只下载指定（如 MMR,LLM）。脚本自己读这里，命令不用传。
install_dir: "D:\\Driver\\Package\\0-Intel_SDK"        # 预装服务安装目录：空=默认 %LOCALAPPDATA%\GameAssistant；否则用指定路径作为服务安装目录。脚本自己读这里，命令不用传。
---

# BARDemo 技能说明

本文档描述游戏助手各模式的功能与操作方式，以及 skill 触发后 agent 要执行的完整流程。

> 提示：游戏助手服务在后台运行，不用时说"关闭服务"即可同时关闭 BARDemo 与后台服务。

---

## 已支持游戏（提示）

- 支持《鬼武者：剑之道》（Boss：佐佐木岩流）
- 更多游戏支持 Vibe Coding 自由创作，欢迎玩家自行探索与尝试

用户询问"支持某游戏吗 / 某游戏能不能用"时，可直接据此回答，无需运行任何命令。

## 弹窗提醒（skill 触发即弹）

适用时机：skill 触发后先执行提醒弹窗，再继续后续步骤（**无论用户原话是否带游戏名**）。弹窗只做提醒，**纯展示、不可点选、不收集任何输入，不改变后续流程**。

执行（「关闭」/×/Esc 可关闭；15 秒无操作自动关闭）：
```powershell
python ./scripts/game_notice_dialog.py
```
- 弹窗内容：显著位置展示"已支持游戏列表（不断完善中，欢迎玩家贡献）"，列表下方附引导语"更多游戏支持 Vibe Coding 自由创作，欢迎玩家自行探索与尝试"。
- stdout 一行 JSON：`acknowledged`=用户已关闭；`error` 时把 `message` 原样转达给用户。
- 无论哪种返回，都照常继续后续流程。

### 演示视频（文字回复必带）

识别效果演示：https://www.bilibili.com/video/BV1X4Hm61Exg （《鬼武者：剑之道》· Boss 佐佐木岩流）

本 skill 触发后的**首次文字回复必须给出这条链接**，并说明它是识别效果演示；与实际安装进度无关，弹窗返回 `acknowledged` 还是 `error` 都不得省略。

---

## 执行流程（skill 触发后按序执行）

0. 意图分流：若用户原话包含 `关闭服务`、`停止服务`、`关掉服务` 等，判定为 `关闭服务`，执行「关闭服务」节后直接结束 skill（**不弹窗、不装依赖、不做健康检查**）；否则按 1→6 执行
1. 弹窗提醒（见上方「弹窗提醒」节）
2. 安装部署脚本依赖（见「环境依赖」）
3. 确保服务已开启，未启动则自动部署（见「服务健康检查与部署」）
4. 确保 BAR / Knowledge 服务已开启（见「确保 BAR / Knowledge 服务已开启」）
5. 确保 Demo 资产就绪（见「确保 Demo 资产就绪」）
6. 启动 BARDemo.exe（见「启动 Demo」）

## 环境依赖

**必须一次性安装全部依赖（使用国内镜像源加速；镜像不可用时切换其它镜像或回退官方 PyPI 重试），本步骤未完成禁止进入下载/启动等任何后续步骤**：

```powershell
pip install requests py7zr modelscope -i https://mirrors.aliyun.com/pypi/simple/
```

BARDemo.exe 已自带全部运行依赖，无需安装；上面 3 个包是部署脚本需要的。

下文命令里的 `python` 还必须**带 tkinter**（部署/下载进度弹窗、提醒弹窗都依赖它）。默认 `python` 不满足时（如精简发行版缺 tkinter、或依赖没装齐），换用本机另一个装有 tkinter 的解释器，并在命令里写明它的绝对路径。

若报"找不到 python / pip"或类似错误，说明这台机器没装 Python：告诉用户先安装 Python 3.9 以上版本（安装时勾选 Add to PATH），**不要继续后面的步骤**。

## 服务健康检查与部署（全自动，无需你操心）

`ensure-demo` 与「启动 Demo」前都要服务在跑。服务没起来时，`deploy` 会在后台先部署（首次部署要下载服务包和 7 个模型，耗时较长；已装机器只做秒级的更新检测）。「游戏助手服务」需要在用户整个游戏过程中**后台常驻**——脚本拉起的后台进程在某些 Agent 沙盒里会随前台命令结束被回收，部署完成后必须确认服务能跨命令存活，见「Agent 环境适配」第 2 条（不确认就宣告完成，服务可能在用户手里立刻失效）。

**模型下载策略与预装目录不用传参**：脚本每次执行时自己读本文件 frontmatter 的 `models` 和 `install_dir`，所有命令直接执行即可。`install_dir` 是**预装目录**。服务端目录按以下优先级确定，命中即用、绝不重新下载解压：①上次用户选择并记住的目录（记在 `%LOCALAPPDATA%\GameAssistant\chosen_server_dir.txt`）→ ②预装目录 `install_dir` → ③默认目录 `%LOCALAPPDATA%\GameAssistant`；三处都没有解压好的服务端（以目录内含服务端 exe 为准）时才弹窗问用户——「自动下载并安装（默认）」把安装包下载到默认目录并解压到那里，「选择已解压的服务端目录」直接使用用户指定的目录，10 秒无操作自动选自动下载。日志、状态文件与模型下载缓存跟随实际使用的服务端目录。

独立使用场景（如纯部署）：
```powershell
python ./scripts/service_manager.py health    # 仅检查
python ./scripts/service_manager.py deploy    # 后台部署
python ./scripts/service_manager.py status    # 轮询进度
python ./scripts/service_manager.py ensure    # 检查+按需部署
```

**服务端口自动探测**：新版服务端默认监听 `22919`，旧版（已发布的部署）监听 `9190`，脚本自动探测实际端口并以身份校验确认（避免端口被其它程序占用时误判健康）。`health` 返回 `healthy` 时带 `"port": <实际端口>`，后续「确保 BAR / Knowledge 服务已开启」的 curl 一律用这个端口。

1. 先健康检查（瞬间返回）：
```powershell
python ./scripts/service_manager.py health
```
   返回 `healthy` → 记下返回里的 `port`，进入「确保 BAR / Knowledge 服务已开启」。
   返回 `unhealthy` → 继续第 2 步。

2. 后台部署（立即返回，不阻塞）：
```powershell
python ./scripts/service_manager.py deploy
```
   返回值（一行 JSON）：

   | `status` | 含义 | 你要做的 |
   |---|---|---|
   | `started` | 部署已在后台开始 | 告诉用户已开始（首次部署要下载服务包和 7 个模型，耗时较长），然后每 30 秒轮询一次 `status` |
   | `busy` | 已有别的后台任务在跑 | 告诉用户稍等，每 30 秒轮询 `status` |
   | `error` | 失败 | 把 `message` 原样转达给用户，结束 |

3. 轮询进度：
```powershell
python ./scripts/service_manager.py status
```
   返回 `{task, status, stage, progress, detail}`：
   - `running` → 把 `stage` 和 `progress` 讲给用户听，30 秒后再查一次
   - `done` → 服务已就绪（完成判据是真实端口探测，不是日志关键词）；但陈旧记录同样会返回 `done`，仍须用一条**新命令** `health` 实探一次（并按「Agent 环境适配」第 2 条确认跨命令存活）再放行
   - `error` → 把 `detail` 转达给用户，结束
   - `idle` → 还没有任务记录，30 秒后再查一次；连续两次都是 `idle` 就重新执行一次 `deploy`

> 简化用法：`python ./scripts/service_manager.py ensure` 一条命令完成"健康检查 + 按需部署 + 等到就绪"，**会阻塞直到服务就绪才输出一行 JSON**（`healthy` 带 `port` / `error`），适合不介意命令长时间挂起的场景（Agent 沙盒里命令超时被杀会连累部署，见「Agent 环境适配」第 2 条）。

> 服务是全局共享的，不要主动关闭；用户明确要求关闭服务时，按「关闭服务」节执行。

### 版本更新与确认弹窗（脚本自动处理，你要知道怎么向用户解释）

`deploy` 启动时会联网检测服务端与模型更新（约几秒）。服务端更新的判定：默认**双条件同时满足**才更新——①本地服务端 exe 的修改时间早于 ModelScope 上压缩包的修改时间（files API 的 `CommittedDate`）；②SHA256 与本地记录不一致（防止本地已从 GitHub 装了更新版本被误降级）。若压缩包修改时间的所有来源都拿不到（API 无字段且响应头无 Last-Modified），则**退化为仅按 SHA256 不一致判定**（日志会写明降级原因）。模型更新按仓库内容指纹与清单变化判定。

检测到更新会弹窗询问「立即更新 / 暂不更新」（弹窗里每个选择都会写入日志，倒计时自动选择与用户主动点击可区分），**10 秒无操作自动选"暂不更新"**——暂不更新属正常路径，服务用当前版本继续启动（status 最终仍是 done），且该版本之后不再询问，直到出现更新的版本才再次弹窗。`status` 长时间停在「等待用户确认 (10%)」即是在等用户点弹窗。

更新规则：只更新**已安装过的模型**（未装过的模型不会被主动下载）；服务端与模型作为一个事务更新——全部下载成功才会停服覆盖安装，任一下载失败自动继续使用当前版本；覆盖安装**保留用户数据**：`saves/`（BAR 参考帧库与存档数据库）与 `models/`（未更新的模型）原样保留、包内骨架不落地，旧版 `caches/` 目录自动清理；更新期间服务会短暂关闭。ModelScope 下载失败时才会转 GitHub 源，转用前弹窗会明示"国内直连速度有较大概率很慢、耗时较久"。无网络时直接跳过检测照常启动。

## Agent 环境适配（沙盒代理 / 后台进程回收 / 文件删除限制——命令执行前先读）

通过 Agent 启动本助手时，三类沙盒机制会造成故障，症状与对策如下。其中**第 1 条（回环免代理）和第 3 条（删除权限放行）是启动脚本前就要主动做的**，第 2 条是出问题时的排障知识：

1. **沙盒代理**：Agent 沙盒/企业网络常注入 `http_proxy`/`https_proxy`，会把发往 `127.0.0.1` 的本机请求也送进代理——症状是部署/健康检查失败、BARDemo 连不上服务。**每次执行本 skill 的命令前，先在当前 shell 设置回环免代理（幂等，已含回环条目则跳过）**：
   ```powershell
   $env:NO_PROXY="127.0.0.1,localhost"; $env:no_proxy="127.0.0.1,localhost"
   ```
   `service_manager` 拉起的所有子进程会自动合并该变量，无需你传递；这一步覆盖的是你自己直接执行的命令（curl 之类另有 `--noproxy "*"` 兜底，见「确保 BAR / Knowledge 服务已开启」）。不管沙盒里还是宿主机上，这个变量都必须有——不能假设环境里没有代理。
2. **后台进程常驻**：`deploy` 是脚本用 Popen 拉起后台进程后立即返回，而「游戏助手服务」要在用户整个游戏过程中长期存活——某些 Agent 沙盒会在前台命令结束时把脚本拉起的后台进程整树回收（SIGTERM/杀进程树）。症状：`status` 刚到 `done`、健康检查刚通过，下一条命令再查服务就没了；或 `status` 长时间停在 `running` 且毫无进展；或 `deploy` 后 30 秒 `status` 报 `error` 且 `log/deploy/stdout.log` 为 0 字节（日志有内容的失败不算）。因此**宣告完成前必须确认服务能跨命令存活**：
   - 部署/启动完成后等 30 秒，用一条**新命令**执行 `python ./scripts/service_manager.py health`。`healthy` → 后台进程未被回收，正常继续；`unhealthy`（或 `status` 卡在 `running` 超过 5 分钟无进展且 `health` 失败）→ 该沙盒会回收后台进程，改用下面的常驻方式重做第 3、6 步（优先后台任务，其次 CIM）。
   - **常驻方式一（优先）：用你的后台任务能力启动脚本**：若你具备后台执行任务/后台进程的能力，**优先把 `service_manager` 命令（`deploy`）放到后台任务里运行**——沙盒回收的是「前台命令结束时拉起的后台进程」，挂在你的后台任务下的服务进程不会随后台任务结束而消失（任务本身很快返回也没关系，服务进程已经常驻），之后照常每 30 秒轮询 `status`。这比下面任何兜底手段都可靠，能用就用。
   - **常驻方式二（无后台任务能力时的兜底）：CIM 拉起脱离进程树**：用 CIM 创建进程，新进程挂在系统 WmiPrvSE 之下、不属于你的命令进程树，前台命令结束时不会被连带回收（`<python绝对路径>`、`<项目根绝对路径>` 替换为实际值，路径含空格也不影响；CIM 创建的进程不继承你 shell 的工作目录和临时环境变量——所以必须用绝对路径，`$env:NO_PROXY` 也不用传，脚本子进程会自行合并回环免代理）：
     ```powershell
     powershell -NoProfile -Command "Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = '<python绝对路径> <项目根绝对路径>\scripts\service_manager.py ensure'; CurrentDirectory = '<项目根绝对路径>' } | Select-Object ReturnValue, ProcessId"
     ```
     `ReturnValue = 0` 表示创建成功。之后照常每 30 秒轮询 `status` 到 `done`，再用一条新命令 `health` 复核。`ensure-demo` 也会被回收，但它是前台阻塞命令、本身不受影响；`shutdown` 不受影响（按端口/进程名停止，常驻方式拉起的进程一样能正常关闭）。无长活后台任务能力、CIM 也不可用时，改用 `service_manager.py ensure`（前台阻塞，仅命令存活期间可用，注意 agent 命令超时风险）。
   - 向用户说明：在此类沙盒里服务可能随 Agent 会话结束而停止，下次要玩时说一声"打开 Boss 招式识别"即可重新拉起。
   - 进程存活问题**不要**靠计划任务或修改系统/安全设置解决。
3. **文件删除限制（启动脚本前先放行删除权限）**：Agent 沙盒常禁止脚本删除文件，而部署/启动流程里到处是删除与改名操作——覆盖安装要清掉旧内容、解压要在安装目录父级建/清 `_extract_*`/`_unwrap_*` 临时目录、模型要从下载缓存移动落位到服务端模型目录、状态文件要原子替换、BAR 参考帧库刷新要先清旧子树。**删除权限没放行时，后续任何一处删除被拦都会让脚本卡住**（退化成整目录复制或反复重试，耗时数分钟到数十分钟毫无进展）甚至报错中断、模型全部留在下载缓存目录（`<服务根目录>/_modelscope_download_cache/`），助手等于没装成。因此**第一次执行 `deploy`/`ensure` 前，先主动请求放行对安装目录的删除/写入权限**（默认 `%LOCALAPPDATA%\GameAssistant`，frontmatter `install_dir` 非空时为该路径；连同其父目录下的 `_extract_*`/`_unwrap_*` 临时目录一并放行，或临时关闭对应的文件防护）——向用户说明这是部署必需的文件操作、征得同意后在沙盒权限里批准，**不要等脚本失败后再补**。补救与判据：
   - 已中招时：`status` 返回 `error` 且 `detail`/日志里有「无法把模型 XXX 安装到 …（移动/复制均被拒绝…请放行后重试）」，说明连复制写入都被拦截：按上面放行后**重新执行原来的 `deploy` 命令**——已下载的模型缓存在重跑时会复用，不会重新下载。
   - 脚本内置回退：仅移动被拒时会**自动改为复制安装**（复制是纯写入，沙盒不拦），日志出现「移动/删除被沙盒拒绝，已改为覆盖复制安装」即说明模型已就位，**无需你处理**；仅下载缓存会残留在原处多占一份磁盘，之后放行删除重新部署即可清掉。
   - 落位成功的判据：部署日志出现逐条的「安装完成: <模型名> → <目标目录>」，且服务端模型目录里能看到模型文件。模型只躺在 `_modelscope_download_cache/` 而模型目录为空 = 落位失败，按上一条放行后重跑。
   - **守卫拦截批量删除时**（与进程存活无关）：stderr 有宿主批量删除确认标记（如 WorkBuddy 的 `SAFE_DELETE_BULK_CONFIRM_REQUIRED`）时，不要原地重试——把被拦目标**移入系统临时目录**（移动不计入删除数）再重跑；脚本因目标不存在而自动跳过，无需人工确认；移入的旧数据不会自动删除，之后自行清理即可（在临时目录内删除不受拦）。

## 确保 BAR / Knowledge 服务已开启

服务本体就绪后、启动 Demo 前，还要确认两个业务子服务已开启（服务刚装好或刚重启时它们默认不开）。已开启时以下全是毫秒级查询，开销可忽略。

**端口一律用 `health` 返回的 `port`**（新版 22919 / 旧版 9190，下文写作 `<port>`）。所有命令一律用 `curl.exe --noproxy "*"`：本机系统代理可能拦截 127.0.0.1 调用，`--noproxy "*"` 无条件绕开，不要换成 `Invoke-RestMethod`。

### BAR 服务（招式识别，BARDemo 必需）

1. 查询（body 的 `enable` 传 `null`，只查不改）：
```powershell
curl.exe --noproxy "*" -X POST http://127.0.0.1:<port>/bar/service/enable -H "Content-Type: application/json" -d '{\"enable\": null}'
```
   返回 JSON 里 `bar` 为 `true` → 已开启，进入「Knowledge 服务」。

2. `bar` 为 `false` → 启用，等待返回 `code` 为 `ok`：
```powershell
curl.exe --noproxy "*" -X POST http://127.0.0.1:<port>/bar/service/enable -H "Content-Type: application/json" -d '{\"enable\": true}'
```
   `code=ok` 后 BAR 还要加载 Action 模型，不是瞬间可用的：重新执行第 1 步查询确认 `bar` 变 `true`；仍为 `false` 就等 10 秒再查，最多约 90 秒。

3. 超时仍未开启 → 停下来把情况转达给用户，**不要继续启动 Demo**。

> 引号写法：上面 `-d '{\"enable\": null}'` 是 PowerShell 写法；若在 Git Bash / cmd 里执行，`-d` 参数改为 `-d '{"enable": null}'`。

### Knowledge 服务（Memory 检索 / AI 战斗分析）

1. 查询：
```powershell
curl.exe --noproxy "*" http://127.0.0.1:<port>/knowledge/service/enable
```
   返回里 `knowledge`、`embedding`、`splitter`、`rerank`、`llm` 均为 `true` → 已开启，本节完成，进入「确保 Demo 资产就绪」。

2. 任意一项为 `false` → 无条件按下列顺序逐条启用（已为 `true` 的项重复调用会直接返回 ok，无副作用，**不需要逐项判断**），每条等到 `code=ok` 再执行下一条：

```powershell
# llm
curl.exe --noproxy "*" -X POST http://127.0.0.1:<port>/llm/service/enable/true
# embedding
curl.exe --noproxy "*" -X POST http://127.0.0.1:<port>/knowledge/service/embedding/enable/true
# splitter
curl.exe --noproxy "*" -X POST http://127.0.0.1:<port>/knowledge/service/splitter/enable/true
# rerank
curl.exe --noproxy "*" -X POST http://127.0.0.1:<port>/knowledge/service/rerank/enable/true
# knowledge（依赖前面几项，必须最后调）
curl.exe --noproxy "*" -X POST http://127.0.0.1:<port>/knowledge/service/enable/true
```

3. 五条全部调完后**回到第 1 步复查**：五项均 `true` → 完成；仍不齐 → 再重做一轮第 2~3 步；两轮后仍不齐 → 停下来把复查返回原样转达给用户，**不要继续启动 Demo**。

## 确保 Demo 资产就绪（BARDemo/ 与 thirdparty/ 不随 skill 分发）

`BARDemo/` 与 `thirdparty/` 不在 skill 包里，启动 Demo 前先执行（幂等：已就绪毫秒级返回，缺哪个包下载哪个）：

```powershell
python ./scripts/service_manager.py ensure-demo
```

- 返回 `{"status": "ready"}` → 就绪，进入「启动 Demo」。
- 返回 `{"status": "error", "message": ...}` → 把 `message` 原样转达给用户，结束，**不要继续启动 Demo**。
- 首次执行需下载约 94MB（BARDemo.7z + thirdparty.7z，解压到 skill 根目录），耗时取决于网速；命令会阻塞到下载解压完成才输出结果，**不需要轮询**。
- 下载期间会弹出「Boss 招式识别 Demo 资产下载」进度窗口（每个包一行实时进度，完成后自动关闭）；用户点 × 关窗 = 取消下载，命令返回 error，把 message 转达给用户即可。

## 启动 Demo

服务与 Demo 资产就绪后启动 BARDemo。**必须以 `BARDemo/` 为工作目录启动**——config.json 里变速 DLL 与 mpv 播放器都是 `..\thirdparty\...` 相对路径，工作目录不对会找不到：

```powershell
cd ./BARDemo; Start-Process .\BARDemo.exe -WindowStyle Hidden
```

`-WindowStyle Hidden` 让程序自带的控制台窗口完全不显示（既不弹出、也不占任务栏）；运行时输出由程序另行写入 `BARDemo/logs/bardemo_<日期>_<时间>.log`，需要查看时打开对应日志文件即可（结束 Demo 请用「关闭服务」）；**不要去掉该参数**；仍必须先 `cd` 进 `BARDemo/` 再启动。

启动后程序自动搜索游戏窗口（OnimushaWotS_Demo.exe）或 mpv 播放器并进入观战模式；模式、热键、语音切换等操作见下文。

## 返回值怎么读（所有命令都只输出一行 JSON）

| `status` | 含义 | 你要做的 |
|---|---|---|
| `started` | 任务已在后台开始 | 告诉用户已开始，然后每 30 秒轮询一次 `status` |
| `ready` | Demo 资产已就绪（ensure-demo） | 进入「启动 Demo」 |
| `busy` | 已有别的后台任务在跑 | 告诉用户稍等，每 30 秒轮询 `status`，完成后再重试本命令 |
| `healthy` / `unhealthy` | 服务可用 / 不可用（health；`healthy` 带 `port`） | 按上文流程继续或转部署 |
| `error` | 失败 | 把 `message` 原样转达给用户，结束 |

`status` 命令返回 `{task, status, stage, progress, detail}`，按「服务健康检查与部署」第 3 步处理。

`shutdown` 自带端口与进程检测，无需前置步骤；返回 `{status: done|error, client_stopped, message}`，`client_stopped=true` 表示 BARDemo.exe 也被一并结束。

## 关闭服务

一条命令完成：先结束 BARDemo.exe 进程（未在运行时静默跳过），再关闭游戏助手服务（优雅关失败自动转强杀）。服务是全局共享的，关闭后攻略助手等其它功能也不可用，完成后向用户说明这一点。

```powershell
python ./scripts/service_manager.py shutdown
```

把返回的 `message` 与 `client_stopped` 含义转达给用户，结束 skill；返回 `error` 时原样转达。

---

## 三种模式对比

| 功能 | 观战模式 | 教学模式 | 子弹时间模式 |
|------|----------|----------|--------------|
| 记录招式到 Memory | ✓ | ✗ | ✗ |
| 招式提示显示 | ✓（左侧面板） | ✓（中央弹窗） | ✓（左侧面板） |
| 血量监测 | ✓（含伤害事件） | ✓（仅显示） | ✓（仅显示） |
| 暂停游戏 | ✗ | ✗ | ✓ |
| 播放讲解视频 | ✗ | ✗ | ✓ |
| AI 战斗分析 | ✓（退出后） | ✗ | ✗ |

---

## 热键说明

| 热键 | 作用 |
|------|------|
| `F1` | 切换到观战模式。若屏幕右上角正在显示 AI 分析报告，同时关闭该报告 |
| `F2` | 切换到教学模式 |
| `F3` | 切换到子弹时间模式。若当前已处于子弹时间模式，则强制恢复游戏速度并关闭视频和提示框 |
| `F4` | （子弹时间模式）恢复游戏速度，关闭讲解视频和提示框，继续等待下一个招式 |
| `F8` | （子弹时间模式）手动触发：识别当前画面中的招式，暂停游戏并播放对应视频 |
| `ESC` | （子弹时间模式）与 F4 相同，恢复游戏速度并关闭视频 |
| `` ` `` | 按住开始录音，松开后识别语音内容并切换模式（详见语音切换说明） |
| `F11` | 显示或隐藏左侧调试面板。其他所有显示内容（教学提示、子弹时间提示、AI 分析）不受影响 |
| `F12` | 显示或隐藏画面上的检测区域框（OCR 检测框及血量检测线），用于确认识别范围是否正确 |

---

## 语音切换模式

按住 `` ` ``（反单引号）录音，松开后自动识别内容，说话中**包含以下关键词**即可切换：

| 关键词 | 切换到 |
|--------|--------|
| **观战** | 观战模式 |
| **教学** | 教学模式 |
| **子弹** 或 **暂停** | 子弹时间模式 |

示例："切换观战"、"教学模式"、"子弹时间"、"暂停一下" 均可触发。

---

## 招式识别流程

所有模式共用同一套识别管线，识别结果依次经过以下过滤：

```
BAR 服务原始结果
    ↓ 前缀过滤（如"踱步"开头的招式直接忽略）
    ↓ 分数阈值（全局阈值 + 各招式独立阈值）
    ↓ 连续帧确认（同一招式需连续出现 N 帧）
    ↓ 冷却时间（同一招式 N 秒内不重复触发）
    ↓ 前置条件（如"投技"需要"二阶段"先触发）
    ↓ HP 条件（如"二阶段"需要 Boss 血量低于 60%）
    ↓ 最终输出给各模式
```

冷却计时在连续帧确认通过后才开始，被过滤掉的帧不会重置冷却。

---

## 子弹时间模式详细行为

**自动暂停触发条件**（同时满足）：
- 招式通过完整过滤管线
- 该招式与上次触发的招式**不同**（同一招式不连续触发，需先出现不同招式才能再次触发）

**恢复后的状态**：
- 重置连续帧计数（下次识别需重新连续 N 帧）
- 保留招式记录（防止同一招式恢复后立刻再次触发）
- 冷却时间正常计算

**游戏速度控制生命周期**：
- 切换到子弹时间模式时，速度控制组件启动
- 每次进入 Boss 战时检查组件是否运行，未运行则重新启动
- 退出 Boss 战时：先恢复速度至正常，再退出组件
- 切换到其他模式时，组件随之退出

---

## 观战模式 AI 分析

Boss 战结束后，程序汇总以下信息调用 AI 生成战斗分析报告：

**全局统计**（跨场累计）
- 总挑战次数、胜负次数、无伤通关次数
- 各招式出现次数及玩家防御失败 / 反击成功次数

**本场统计**
- 血量低于 15% 的危险次数
- 本场各招式出现次数

报告显示在屏幕右上角，持续 30 秒，按 F1 可提前关闭。

---

## 模式选择建议

| 情况 | 建议模式 |
|------|----------|
| 首次挑战 Boss，想了解每个招式的应对方法 | 子弹时间 |
| 已了解招式，练习实战反应速度 | 教学模式 |
| 正式挑战，想记录数据、分析薄弱点 | 观战模式 |
