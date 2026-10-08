# BARDemo — Boss 招式识别游戏助手

基于游戏助手服务端的 BAR（Boss Action Recognition）服务，实时识别 Boss 招式并提供辅助。  
以《鬼武者：剑之道》为示例游戏，适配 Boss 佐佐木岩流。

---

## 目录结构

```
Boss招式识别Demo/
├── BARDemo/          # 打包好的 Demo 主程序（BARDemo.exe + 资源，不随 skill 分发，首次运行自动下载）
│   ├── config.json   # 全部可调参数（服务地址、热键、识别阈值等）
│   ├── videos/       # 子弹时间模式的招式讲解视频
│   └── voices/       # 模式提示音
├── scripts/          # skill 配套脚本
│   ├── deploy.py               # 游戏助手服务端部署器
│   ├── service_manager.py      # 服务管理：health / deploy / status / ensure / ensure-demo / shutdown
│   └── game_notice_dialog.py   # 已支持游戏提醒弹窗（纯展示）
├── thirdparty/       # 第三方组件：mpv 播放器、SpeedHack 变速 DLL（不随 skill 分发，首次运行自动下载）
├── README.md         # 本文件
└── SKILL.md          # skill 说明：agent 自动执行的完整流程与契约
```

> `BARDemo/` 与 `thirdparty/` 不随 skill 分发：首次执行时 `service_manager.py ensure-demo` 会自动从 ModelScope 数据集下载并解压到 skill 根目录（换包改 `service_manager.py` 顶部的 `DEMO_PACKAGES`）；两个目录必须保持现有相对位置，单独挪走任一目录都会导致找不到变速 DLL / 视频播放器。BAR 参考帧库（`saves_barservice_onimusha_final_optimized.7z`）同理不随 skill 分发：部署时若服务端尚未安装帧库，会自动从 ModelScope 数据集下载并合并进服务端 `saves/`（换包改 `deploy.py` 顶部的 `BAR_SAVES_URL`）。

---

## 启动

**方式一：手动启动** —— 前置条件：游戏助手服务端已在本机运行（端口自动探测：新版 `22919`，旧版 `9190`；可用 `python scripts/service_manager.py health` 确认，服务未启动时先执行 `python scripts/service_manager.py ensure` 自动部署）；`BARDemo/` 与 `thirdparty/` 缺失时先执行 `python scripts/service_manager.py ensure-demo` 下载。**必须以 `BARDemo/` 为工作目录启动**（config.json 里的变速 DLL 与 mpv 播放器都是 `..\thirdparty\...` 相对路径）：

```powershell
cd BARDemo
.\BARDemo.exe
```

**方式二：agent / skill 自动执行** —— 按 SKILL.md 流程：弹窗提醒已支持游戏 → 确保服务端已开启（未启动自动部署）→ 确保 BAR / Knowledge 子服务开启 → 启动 BARDemo.exe。

启动后程序会：
1. 自动搜索游戏窗口（`OnimushaWotS_Demo.exe`）或测试用 mpv 播放器（`mpv.exe`）
2. 以 10fps 实时截取画面
3. 持续通过 OCR 检测是否进入 Boss 战
4. 默认进入**观战模式**

---

## 服务部署与更新

服务端与 AI 模型不随 skill 分发，首次使用由 `service_manager.py deploy` 自动下载安装（服务包 + 7 个模型 + BAR 参考帧库）。此后每次部署时会联网检测服务端与模型更新：检测到更新会弹窗询问「立即更新 / 暂不更新」，**10 秒无操作自动选"暂不更新"**（服务用当前版本照常启动，该版本之后不再重复询问）。更新以事务方式应用——全部下载成功才停服覆盖安装，覆盖时保留 `saves/`（BAR 参考帧库、存档数据）与 `models/`（未更新的模型）。

---

## 开始识别

> 想先看识别效果，可以先浏览演示视频：[鬼武者：剑之道 · 佐佐木岩流](https://www.bilibili.com/video/BV1X4Hm61Exg)

**实际游戏（强烈推荐）**：启动"鬼武者：剑之道（试用版）"游戏，进入"佐佐木"Boss 战斗即可开始识别。强烈建议在实际游戏中使用本 skill，才能获得完整的招式识别、教学提示、子弹时间与 AI 战斗分析体验。

> 由于存档因账号而异，直接替换会提示存档损坏，所以无法提供 Demo 用的存档，需要自行打到 Boss 战斗前，最快 15 分钟。

**视频素材测试**：您也可以使用提供的视频素材来测试 Demo 效果。请使用 `game-assistant-boss-action-recognition\thirdparty\mpv\mpv.exe`（相对 skill 根目录为 `thirdparty\mpv\mpv.exe`）来播放视频，在 skill 根目录下执行：

```powershell
.\thirdparty\mpv\mpv.exe <视频素材路径>
```

播放快捷键：按 `F` 全屏播放，按 `Shift+L` 循环播放，按 `Q` 退出播放。

> **不要**用系统里安装的其他 mpv、PotPlayer、VLC 等任何其他播放器代替——BARDemo 的画面捕获与子弹时间讲解视频都绑定这个自带 mpv，换播放器会导致识别不到画面或互相冲突。
>
> 视频测试时，除了**子弹时间无法减慢视频速度**外（变速只对游戏进程生效），其它功能均正常。

---

## 关闭

一条命令完成（自动先结束 BARDemo.exe 进程，再关闭后台服务）：

```powershell
python scripts/service_manager.py shutdown
```

> 后台服务是全局共享的，关闭后攻略助手等其它功能也会随之不可用。

也可以对 agent 说"关闭服务" / "停止服务" / "关掉服务"，执行的就是同一条命令。

---

## 三种模式

### 观战模式（F1）

被动记录，适合复盘分析。

- 进入 Boss 战后开始计时
- 实时识别招式，将每次识别连同时间戳写入 Memory 服务
- 检测玩家与 Boss 的血量变化，将伤害事件写入 Memory；若伤害发生前 2 秒内有招式识别，自动关联（"防御失败"或"反击成功"）
- Boss 战结束后，汇总本场及历史统计，调用 AI 生成战斗分析报告，显示在屏幕右上角（持续 30 秒，可按 F1 提前关闭）

**写入 Memory 的事件类型**

| 事件 | 内容 |
|------|------|
| 进入/退出 Boss 战 | 回合 ID、结果 |
| 招式识别 | 招式名、得分、计时 |
| 玩家受伤 | 血量前后值、关联招式 |
| Boss 受伤 | 血量前后值、关联招式 |

---

### 教学模式（F2）

实时按键提示，帮助初学者应对招式。

- 识别到 Boss 招式后，在屏幕右侧中央弹出按键提示框（带流光边框）
- 提示框显示"招式名 → 应对按键"，3 秒后自动消失
- 同时在左侧面板实时显示玩家与 Boss 血量

---

### 子弹时间模式（F3）

识别到招式后自动暂停游戏并播放讲解视频，适合深度学习招式应对。

- 识别到招式后：
  1. 将游戏速度降至极慢（近似暂停）
  2. 在屏幕右侧播放该招式对应的讲解视频（循环）
  3. 在视频上方显示提示文字及"按 F4 恢复游戏"
- 按 **F4** 或 **ESC** 关闭视频并恢复游戏速度
- 再次按 **F3** 可强制恢复（适用于意外暂停时）
- 也可按 **F8** 手动触发暂停（程序会识别当前画面中的招式）

---

## 热键一览

| 热键 | 功能 |
|------|------|
| `F1` | 切换到**观战模式** / 关闭 AI 分析面板 |
| `F2` | 切换到**教学模式** |
| `F3` | 切换到**子弹时间模式**；若已在该模式则强制恢复游戏 |
| `F4` | 子弹时间：恢复游戏速度 + 关闭视频 |
| `F8` | 子弹时间：手动识别当前招式并暂停游戏 |
| `ESC` | 关闭子弹时间视频，恢复游戏速度 |
| `` ` `` | 按住录音，松开后语音识别切换模式（详见下方说明） |
| `F11` | 显示 / 隐藏左侧调试面板（其余 overlay 不受影响） |
| `F12` | 显示 / 隐藏 OCR 区域及血量检测范围的调试框 |

---

## 语音切换模式

按住反单引号键（`` ` ``）开始录音，松开后自动识别并切换模式。说话内容只需**包含对应关键词**即可，不需要完整句子：

| 关键词 | 切换到 |
|--------|--------|
| **观战** | 观战模式 |
| **教学** | 教学模式 |
| **子弹** 或 **暂停** | 子弹时间模式 |

示例："切换观战"、"教学模式"、"子弹时间"、"暂停一下" 均可触发。  
说的话不包含上述关键词时，不做任何切换。

---

## 调试面板（左侧，F11 开关）

实时显示以下信息：

- 当前模式 + Boss 战计时（`mm:ss`）+ 实际截图帧率
- 两个 OCR 检测区域的识别结果及是否匹配
- 玩家血量 / Boss 血量百分比
- 最近 5 条招式识别记录（时间 + 招式名 + 得分）

---

## Boss 战自动检测

程序通过 OCR 识别两个画面区域来判断 Boss 战状态：

| 条件 | 说明 |
|------|------|
| 进入 Boss 战 | 两个区域同时识别到目标文字（连续满足 3 帧） |
| 获胜 | 目标一存在，目标二消失（连续满足 3 帧） |
| 失败 | 目标一消失，目标二存在（连续满足 3 帧） |

退出 Boss 战后，程序继续监控画面，再次满足条件时自动进入新一轮。

---

## 依赖

- **BARDemo.exe**：免安装依赖（PyInstaller 打包，自带全部运行库），无需 pip install
- **部署脚本**（`scripts/deploy.py`、`scripts/service_manager.py`）：

```powershell
pip install requests py7zr modelscope -i https://mirrors.aliyun.com/pypi/simple/
```

- **提醒弹窗**（`scripts/game_notice_dialog.py`）：仅需 Python 自带的 tkinter
