# Snow Studio · Snow 原琴工作站

面向「原琴」玩法的 MIDI 钢琴卷帘工作站。导入 MIDI 后可以在编辑器里修整音符，播放时把音符转换成游戏窗口可识别的键盘输入，并可用 FluidSynth 试听。

本仓库是**免安装便携版（基础版）**。

> ⚠️ 草稿：本文档由 AI 整理，待作者人工校准。标有 `TODO` 的地方需要确认。

<!-- TODO: 放一张主界面截图 -->

## 下载与运行

1. 到 [Releases](https://github.com/LinnaSonwW/Snow-Studio/releases) 下载 `Snow-Studio-basic-win64.zip`。
2. 解压到任意目录。路径里有中文或空格都可以。
3. 双击 `Snow原琴工作站.exe` 启动。如果 exe 打不开，可以双击 `run.bat`。

不需要安装 Python 或任何依赖，压缩包里已经包含嵌入式 Python 3.10、PySide6、mido、FluidSynth 和 FFmpeg。

**系统要求**：Windows 10 / 11，64 位。

> 游戏若以管理员权限运行，本程序也需要右键「以管理员身份运行」，键盘输出才能生效。

## 功能

| 能力 | 说明 |
|------|------|
| MIDI 编辑 | 多轨钢琴卷帘：画笔 / 选择工具、拖动拉伸、复制粘贴、撤销、对齐吸附 |
| 演奏输出 | 按键位映射把音符转换成 Windows 物理按键 |
| 试听播放 | 每轨独立 SF2 音源，音量增幅最高 800% |
| 原曲对照 | 编辑器内同步播放参考音频 |
| 演奏谱 | 节奏谱 / 轨道谱两种排版，播放时高亮当前音符 |
| 悬浮演奏谱 | 置顶透明悬浮窗；悬停进度条呼出工具栏；径向菜单调整乐谱、播放、声音设置，长按确认后生效 |
| 变速编辑 | 编辑 BPM 曲线 |

基础版不含音频扒谱模型（多音高分析、Transkun、MuScriptor）。<!-- TODO: 说明扒谱扩展的获取方式，或提供完整版下载 -->

## 快速上手

1. 点「打开」或直接把 `.mid` 文件拖进窗口。
2. 「编曲」（`Ctrl+E`）进入钢琴卷帘编辑器。
3. 在「设置 → 键位」确认键位映射，勾选「启用键盘输出」。
4. 切到游戏窗口，按空格播放。可以在设置里加 0–10 秒开始延迟，留出切换窗口的时间。

| 快捷键 | 作用 |
|--------|------|
| `空格` | 播放 / 暂停 |
| `P` / `E` | 画笔 / 选择工具 |
| `G` | 循环切换对齐档位 |
| `Ctrl+Z` / `Ctrl+S` | 撤销 / 另存 MIDI |
| `←` `→` `↑` `↓` | 微移 / 移调（`Shift` = 八度） |

## 目录结构

```
Snow原琴工作站.exe   启动器
run.bat              备用启动脚本
app/                 程序源码 (Python + QML), 入口 app/演示.py
libs/                PySide6、mido 等第三方库
python/              嵌入式 Python 3.10
runtime/fluidsynth/  FluidSynth 音源引擎
runtime/ffmpeg/      FFmpeg 音频解码
data/                扩展下载、模型和运行时数据
```

仓库里只保存 `app/`、`run.bat` 和文档。`python/`、`libs/`、`runtime/` 和启动器体积较大，只放在 Release 的 zip 里。

### 从源码运行

把仓库克隆到 Release 解压出的目录里覆盖 `app/`，或者在已装 Python 3.10+ 的环境里运行：

```bash
pip install PySide6 mido pyfluidsynth
python app/演示.py
```

## 许可

<!-- TODO: 选择许可证并添加 LICENSE 文件 -->

压缩包内第三方组件按各自许可分发：Python（PSF）、PySide6（LGPL-3.0）、FluidSynth（LGPL-2.1）、FFmpeg（GPL）。

## 声明

本项目为玩家自制工具，与米哈游及《原神》官方无关。使用键盘输出功能前，请自行了解游戏的用户协议。
