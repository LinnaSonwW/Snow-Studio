# Snow Studio · Snow 原琴工作站

面向「原琴」玩法的 MIDI 钢琴卷帘工作站。导入 MIDI 后可以在编辑器里修整音符，播放时把音符转换成游戏窗口可识别的键盘输入，可实时渲染乐谱。

本仓库是**免安装便携版（基础版）**。

## 主界面
<img width="2560" height="1440" alt="image" src="https://github.com/user-attachments/assets/2ee977fb-5e90-4f52-8ca1-d5f26e8dd1c8" />

## 钢琴卷帘
<img width="2560" height="1393" alt="image" src="https://github.com/user-attachments/assets/29642529-df25-466a-8ca2-628795b6187f" />

## 扒谱界面
<img width="2560" height="1440" alt="image" src="https://github.com/user-attachments/assets/b83850ea-e8a1-4738-9636-e09e3f05052c" />

## 悬浮窗口
<img width="2279" height="1083" alt="image" src="https://github.com/user-attachments/assets/e583d32f-e54f-4d7a-840c-ddc14a54de43" />

## 悬浮交互
<img width="2251" height="422" alt="3c44026b92c400980899c6a98588f820" src="https://github.com/user-attachments/assets/c74a390c-904c-4b92-8dd4-11d305d6bf47" />
<img width="2233" height="1110" alt="image" src="https://github.com/user-attachments/assets/c9328084-10a9-40c0-ab66-8fddc375428c" />
<img width="2238" height="1124" alt="image" src="https://github.com/user-attachments/assets/3e1bfd80-ae58-4c31-8e75-c32498dce5f4" />
<img width="2242" height="1130" alt="image" src="https://github.com/user-attachments/assets/9c443f6c-ab9c-4721-a485-adab82793944" />
<img width="2223" height="1118" alt="image" src="https://github.com/user-attachments/assets/1bfbc4d1-2621-4966-9ae8-e4d6733b04d7" />

## 乐谱动效
<img width="2113" height="300" alt="image" src="https://github.com/user-attachments/assets/b9f3ee1f-633a-4577-bddd-7e5526de9f6f" />







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
| 音频转录 | 集成钢琴专用Transkun模型和多乐器识别MuScriptor模型辅助扒谱 |
| 演奏谱 | 节奏谱 / 轨道谱两种排版，播放时高亮当前音符 |
| 悬浮演奏谱 | 置顶透明悬浮窗；悬停进度条呼出工具栏；径向菜单调整乐谱、播放、声音设置，长按确认后生效 |
| 变速编辑 | 编辑 BPM 曲线 |

音频扒谱模型（多音高分析、Transkun、MuScriptor）

转录模型与分离模型下载链接：

https://pan.baidu.com/s/5qAFYYButfZ3lRNX2f5yGbw

在设置中下载模型依赖才能使用音频转谱功能

<img width="606" height="569" alt="image" src="https://github.com/user-attachments/assets/772dc91c-2b35-424d-b24e-c3e61c5087bf" />

设置按钮入口：中心按钮为设置

<img width="130" height="127" alt="image" src="https://github.com/user-attachments/assets/21abf883-b9bc-4808-a7e8-f394fe5fb49b" />


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
