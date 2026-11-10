# -*- coding: utf-8 -*-
"""界面多语言 (中文/English): 以中文原文为 key, 英文为值; 中文模式下直接返回原文。
   t('文本') / t('已保存 {n} 个音符', n=3); 缺 key 回退中文原文。
   切换: set_lang('en') — 弹窗每次构造时取 t() 天生即时;
   常驻界面由 MainWindow.retranslate_ui() 显式刷新, 画布文字在 paintEvent 取 t()。"""
LANG = 'zh'
_EN = {
    # ---------------- mainwindow 工具条 / 行控件 ----------------
    '播放 / 暂停 (空格)': 'Play / Pause (Space)',
    '停止并回到开头': 'Stop and return to start',
    '文件': 'File',
    '打开 MIDI 文件 (Ctrl+O)': 'Open MIDI file (Ctrl+O)',
    '音源': 'SoundFont',
    '加载音源 SF2': 'Load SoundFont SF2',
    '编曲': 'Editor',
    '打开钢琴卷帘编辑器 (Ctrl+E)': 'Open piano roll editor (Ctrl+E)',
    '另存 MIDI (Ctrl+S)': 'Save MIDI as (Ctrl+S)',
    '悬浮': 'Float',
    '悬浮播放条 (置顶显示, 可拖动)': 'Floating player bar (always on top, draggable)',
    '自定义设置': 'Customize',
    '键位 / 音域分配 / 播放整形 / 开始延迟 / 音域高亮':
        'Keymap / octave mapping / play shaping / start delay / range highlight',
    '音符': 'Notes',
    '音符字母显示设置 (卷帘音符上显示的文字)':
        'Note label display settings (text shown on notes)',
    '设置': 'Settings',
    '输出设备 / 语言': 'Output device / Language',
    '🔇 静音': '🔇 Mute',
    '音源静音 (只影响发声, 不影响键盘输出)':
        'Mute SoundFont playback (keyboard output unaffected)',
    '卷帘': 'Roll',
    '显示/折叠主窗口卷帘演示区 (折叠时不渲染)':
        'Show/collapse the main roll preview (no rendering when collapsed)',
    '轨道': 'Tracks',
    '显示/隐藏轨道架 (静音/独奏/改名)': 'Show/hide track rack (mute/solo/rename)',
    '启用键盘输出': 'Keyboard output',
    '速度': 'Speed',
    '音色#': 'Preset#',
    'SF2 音色编号 (0=钢琴)': 'SF2 preset number (0=piano)',
    '移调': 'Transpose',
    '移调分析…': 'Transpose analysis…',
    '音源: 无': 'SoundFont: none',
    '音源: {f}': 'SoundFont: {f}',
    '跟随': 'Follow',
    '播放时卷帘自动跟随播放头': 'Auto-follow playhead while playing',
    '打开 MIDI 文件开始 (拖放 .mid/.sf2, 空格 = 播放/停止回0, '
    '▶ = 从当前指针位置起播, Ctrl+E = 编辑器)':
        'Open a MIDI file to start (drag & drop .mid/.sf2, Space = play/stop, '
        '▶ = play from playhead, Ctrl+E = editor)',
    # ---------------- 状态栏 / 消息框 ----------------
    '悬浮播放条已开启: 总在最前 · 按住标题可拖动 · 进度条可拖动定位':
        'Floating bar on: always on top · drag title to move · drag progress to seek',
    '打开 MIDI': 'Open MIDI',
    '错误': 'Error',
    'MIDI 解析失败:\n{e}': 'MIDI parse failed:\n{e}',
    '已打开 {f} · 拍号 {a}/{b} · tempo 变化 {c} 处 · 点 🖥 卷帘 查看':
        'Opened {f} · time sig {a}/{b} · {c} tempo changes · open Roll to view',
    '选择 SF2 音源': 'Choose SF2 SoundFont',
    'SF2 加载失败': 'SF2 load failed',
    '提示': 'Info',
    '请先打开 MIDI 文件再编辑': 'Open a MIDI file before editing',
    '请先添加一条音轨再打开编辑器':
        'Add a track before opening the piano roll',
    '↶ 撤销': '↶ Undo',
    '💾 另存 MIDI': '💾 Save MIDI as',
    'P 画笔(点击创建, 点音符记时值) · E 选择 · 右键删除 · 拖动移动 · 边缘拉伸 · Ctrl+拖动复制 · 播放中编辑被忽略':
        'P pencil (click to create, click a note to copy its length) · '
        'E select · right-click delete · drag move · edge resize · '
        'Ctrl+drag copy · editing ignored while playing',
    '已记录时值 {l:g} 拍 (新音符将使用该时值)':
        'Recorded length {l:g} beat(s) — new notes will use it',
    '未保存的改动': 'Unsaved changes',
    '编辑器中有未保存的改动。\n是否另存到 MIDI 文件?':
        'The editor has unsaved changes.\nSave them to a MIDI file?',
    '请先打开 MIDI 文件': 'Open a MIDI file first',
    '当前没有音符可保存': 'No notes to save',
    '另存 MIDI': 'Save MIDI as',
    '保存失败': 'Save failed',
    '已保存 {n} 个音符 → {p}': 'Saved {n} notes → {p}',
    '键位已更新': 'Keymap updated',
    '设置已应用': 'Settings applied',
    '请先打开 MIDI 文件再分析移调': 'Open a MIDI file before transposing analysis',
    '没有可演奏音符: 请先打开 MIDI,\n并确认键位映射有效 / 调整移调':
        'No playable notes: open a MIDI file first,\n'
        'and check the keymap / transpose settings',
    '映射错误': 'Mapping error',
    '{n} 秒后开始演奏, 请切换到游戏窗口…':
        'Playing in {n}s — switch to the game window…',
    '演奏完成 (播完停在结尾)': 'Playback finished (stopped at the end)',
    '权限提示': 'Permission notice',
    '当前不是管理员权限。\n若游戏以管理员运行, 按键将无法送达,\n请以管理员身份重启本程序。':
        'Not running as administrator.\nIf the game runs elevated, keys will not be '
        'delivered.\nPlease restart this program as administrator.',
    '不支持': 'Unsupported',
    '键盘输出仅支持 Windows (SendInput)':
        'Keyboard output requires Windows (SendInput)',
    '编辑器已打开: 改动实时提交到播放数据 · 关闭时可选 另存/放弃':
        'Editor open: edits commit live · choose save/discard on close',
    '整形: 推迟 {a} 丢弃 {b}': 'shaping: deferred {a} dropped {b}',
    '可演奏 {a}/{b} (含黑键 {c}) | 未映射·超域 {d} | 重叠: 合并{e} 截断{g} 去重{h} | 移调 {v:+d}':
        'playable {a}/{b} (black {c}) | unmapped/out {d} | overlap: '
        'merged {e} truncated {g} dedup {h} | transpose {v:+d}',
    '音源已静音': 'SoundFont muted',
    '音源已恢复发声': 'SoundFont unmuted',
    '音符字母显示已应用': 'Note label display applied',
    '输出设备已切换': 'Output device switched',
    '输出设备已保存, 将在下次加载音源时生效':
        'Output device saved; takes effect when the SoundFont loads next time',
    '界面语言已切换': 'Language switched',
    '无法播放, 输出设备切换失败:\n{e}': 'Cannot play — output device switch failed:\n{e}',
    # ---------------- 轨道架 / 悬浮条 ----------------
    '轨道架': 'Track Rack',
    '单击行=当前轨 · 双击名称改名 · M 静音 / S 独奏':
        'Click row = current · double-click name to rename · M mute / S solo',
    '轨道 {n}': 'Track {n}',
    '🎼 轨道 ▾': '🎼 Tracks ▾',
    '选择当前轨 (新音符归属此轨) · M 静音 / S 独奏':
        'Pick current track (new notes go here) · M mute / S solo',
    '悬浮播放条': 'Floating Player',
    '未加载 MIDI': 'No MIDI loaded',
    # ---------------- 编辑器 ----------------
    '钢琴卷帘': 'Piano Roll',
    '画笔 P': 'Pencil P',
    '选择 E': 'Select E',
    '框选': 'Rubber',
    '删除': 'Erase',
    '概览条: 打开 MIDI 后在此拖动视野窗口浏览 / 缩放整曲':
        'Overview: open a MIDI, then drag the view window to pan / zoom the song',
    '概览条: 打开 MIDI 或分析音频后在此拖动视野':
        'Overview: open MIDI or analyze audio, then drag the view here',
    '无': 'Off',
    '1/6 拍': '1/6 beat',
    '1/4 拍': '1/4 beat',
    '1/3 拍': '1/3 beat',
    '1/2 拍': '1/2 beat',
    '1 拍': '1 beat',
    '1 小节': '1 bar',
    '自定义': 'Custom',
    '对齐: {s}': 'Snap: {s}',
    '对齐: {s} ▾': 'Snap: {s} ▾',
    '撤销 {a}': 'Undo {a}',
    '  · 有未保存改动': '  · unsaved changes',
    '  · 无未保存改动': '  · no unsaved changes',
    '播放中 · 改动被忽略 (暂停/停止后可编辑; 选择与浏览不受限)':
        'Playing · edits ignored (pause/stop to edit; selecting and browsing still work)',
    '播放中 · 改动被忽略 (暂停/停止后可编辑)':
        'Playing · edits ignored (pause/stop to edit)',
    '已取消本次操作': 'Operation cancelled',
    '画笔: 空白处按下画出音符 · 拖动定长 · 右键删除':
        'Pencil: press on empty to draw · drag to size · right-click delete',
    '选择: 点选/框选 · 拖动移动 · 右缘拉伸 · 右键删除':
        'Select: click/box · drag move · right edge resize · right-click delete',
    '全选 {n} 个音符': 'Selected all {n} notes',
    '删除 {n} 个音符': 'Deleted {n} notes',
    '复制 {n} 个音符 → 右移 {s} ticks': 'Copied {n} notes → shifted {s} ticks',
    '改长 {d:+g}拍': 'resized {d:+g} beats',
    '移动 {d:+g}拍': 'moved {d:+g} beats',
    '移调 {d:+d} 半音': 'transposed {d:+d} semitones',
    '共 {n} 个音符 · 选中 {m}': '{n} notes · {m} selected',
    '{nn} · 长 {l:g}拍': '{nn} · {l:g} beats',
    '{nn} · {pos} · 长 {l:g}拍': '{nn} · {pos} · {l:g} beats',
    '{n}个音符 · Δ{d:+g}拍 · {p:+d}半音': '{n} notes · Δ{d:+g} beats · {p:+d} semitones',
    '{nn} · 左缘 {d:+g}拍': '{nn} · left edge {d:+g} beats',
    '{nn} · 长 {l:g}拍 ×{s:.2f}': '{nn} · {l:g} beats ×{s:.2f}',
    '{n}个音符 · ×{s:.2f}': '{n} notes · ×{s:.2f}',
    '{n}个音符 · 右缘 {d:+g}拍': '{n} notes · right edge {d:+g} beats',
    '画笔P': 'Pencil P',
    '选择E': 'Select E',
    ' · 对齐 {s} · 选中 {n} · Alt临时关对齐 · Ctrl+拖动复制 · Ctrl+Z撤销 · 空格播放':
        ' · snap {s} · selected {n} · Alt=bypass snap · Ctrl+drag=copy · '
        'Ctrl+Z undo · Space play',
    # ---------------- 卷帘画布文字 ----------------
    '打开一个 .mid 文件开始  (支持拖放)': 'Open a .mid file to start  (drag & drop works)',
    '↑ 还有 {n} 个音符 (在键盘区滚轮向上查看)':
        '↑ {n} more notes above (scroll up over the keys)',
    '↓ 还有 {n} 个音符 (在键盘区滚轮向下查看)':
        '↓ {n} more notes below (scroll down over the keys)',
    # ---------------- 键位校验 ----------------
    '{row} 白键需要 7 个按键(依次对应 C D E F G A B), 当前 {n} 个':
        '{row}: white keys need 7 keys (C D E F G A B in order), got {n}',
    '{row} 白键有重复': '{row}: duplicate white keys',
    '{row} 黑键最多 5 个(对应 C# D# F# G# A#), 当前 {n} 个':
        '{row}: black keys take at most 5 (C# D# F# G# A#), got {n}',
    '{row} 黑键有重复': '{row}: duplicate black keys',
    '{row} 黑键与白键键位重复': '{row}: black keys duplicate white keys',
    '按键 {ch} 在 {a} 与 {b} 中重复': 'Key {ch} is used in both {a} and {b}',
    '八度 C{o} 的分配值非法: {v}': 'Invalid mapping for octave C{o}: {v}',
    '没有任何八度被映射到键位（请在"音域分配…"中设置）':
        'No octave is mapped to keys (set it in "Octave mapping…")',
    # ---------------- sound.py ----------------
    'FluidSynth 音频驱动启动失败(可设 FLUID_AUDIO_DRIVER 指定如 dsound)':
        'FluidSynth audio driver failed to start (set FLUID_AUDIO_DRIVER, e.g. dsound)',
    'pyfluidsynth 不可用: {e}': 'pyfluidsynth unavailable: {e}',
    '未安装': 'not installed',
    'SF2 加载失败(文件损坏或不是有效 SoundFont)':
        'SF2 load failed (file corrupt or not a valid SoundFont)',
    # ---------------- 对话框 ----------------
    '音域分配': 'Octave Mapping',
    '八度分配（多个八度可共用一排；不映射 = 该八度不演奏）':
        'Octaves (rows can be shared; "none" = not played)',
    '八度': 'Octave',
    '分配到': 'Row',
    '不映射': 'None',
    '恢复默认': 'Defaults',
    '取消': 'Cancel',
    '确定': 'OK',
    '自定义键位': 'Custom Keymap',
    '每排键位（白键 7 个依次对应 C D E F G A B；黑键 0~5 个依次对应 C# D# F# G# A#）':
        'Row keys (7 white keys for C D E F G A B; 0-5 black keys for C# D# F# G# A#)',
    '排': 'Row',
    '白键 (7 个)': 'White (7)',
    '黑键 (0~5 个, 留空 = 不映射)': 'Black (0-5, empty = unmapped)',
    '黑键 (0~5 个)': 'Black (0-5)',
    '未映射': 'unmapped',
    '键位无效': 'Invalid keymap',
    '请选择偏移量': 'Choose transpose offset',
    '共 {n} 个音符事件 · 统计基于当前音域分配（点表头排序, 双击行 = 选择并确定）':
        '{n} note events · based on current octave mapping '
        '(click headers to sort, double-click a row to choose)',
    '偏移': 'Offset',
    '黑键数': 'Black',
    '未分配·超域': 'Unmapped/Out',
    '可演奏': 'Playable',
    '备注': 'Note',
    '★ 推荐': '★ best',
    '当前': 'current',
    '请先选择一个偏移量': 'Pick an offset first',
    '键位 (白键 7 = CDEFGAB · 黑键 0~5 = C#D#F#G#A#, 留空不映射)':
        'Keymap (7 white = CDEFGAB · 0-5 black = C#D#F#G#A#, empty = unmapped)',
    '音域分配 (八度 → 排)': 'Octave mapping (octave → row)',
    '播放': 'Playback',
    '重叠处理': 'Overlap',
    '合并为长音': 'Merge into held note',
    '截断重敲': 'Truncate & re-hit',
    '按键模式': 'Key mode',
    '长按保持': 'Hold',
    '固定敲击': 'Tap',
    '最短按住': 'Min hold',
    '同键间隔': 'Same-key gap',
    '敲击时长': 'Tap length',
    '开始延迟': 'Start delay',
    '显示': 'Display',
    '音域高亮 (绿色边框)': 'Range highlight (green frame)',
    '演奏谱字符大小': 'Score label size',
    '演奏谱视图音块字母的显示字号': 'Font size of note letters on the performance strip',
    '主窗轨道名字号': 'Deck track name size',
    '主窗口音轨甲板轨道名称的显示字号': 'Font size of track names on the main deck',
    '演奏谱轨名字号': 'Score lane name size',
    '演奏谱/悬浮窗车道轨名的显示字号 (独立于音符字母字号)':
        'Lane name size on the strip/float (independent of the note letter size)',
    '演奏谱蓝线宽度': 'Score line width',
    '演奏谱音符蓝线的粗细': 'Thickness of note lines on the performance strip',
    '蓝线圆点大小': 'Line dot size',
    '演奏谱音符蓝线首尾圆点的直径': 'Diameter of the dots at both ends of note lines',
    '演奏谱每页小节数': 'Strip bars per page',
    '跟随模式: 演奏谱按此小节数整页翻页 (1|2→3|4→…)':
        'Follow mode: the strip flips whole pages of this many bars (1|2→3|4→…)',
    '演奏谱字符': 'Score label style',
    '演奏谱音块显示的字符风格': 'Character style shown on performance strip blocks',
    '键位字母': 'Key letters',
    '简谱': 'Numbered (Jianpu)',
    '音名': 'Note names',
    '简谱基准八度': 'Jianpu base octave',
    '简谱中音区基准: 该八度不加点, 高八度数字上加·, 低八度下加·':
        'Jianpu middle octave: no dots here; · above digits one octave up, · below one octave down',
    # ---- 音符设置弹窗 (新增) ----
    '音符字母': 'Note Labels',
    '卷帘音符上显示的文字 (主窗卷帘与编辑器同步生效)':
        'Text drawn on notes (applies to the main roll and the editor)',
    '显示模式': 'Mode',
    '音名+八度 (C4)': 'Note name + octave (C4)',
    '纯音名 (C)': 'Note name (C)',
    '唱名 (do re mi)': 'Solfège (do re mi)',
    '简谱 (1 2 3)': 'Numbered notation (1 2 3)',
    '键位 (显示输出按键)': 'Keymap (show output key)',
    '自定义 (12 音)': 'Custom (12 pitches)',
    '不显示': 'Hidden',
    '自定义 12 音级 (每格最多 2 字符, 留空 = 该音级不显示)':
        'Custom 12 pitch classes (up to 2 chars each, empty = hidden)',
    '空 = 不显示': 'empty = hidden',
    '预览: {s}': 'Preview: {s}',
    '音名+八度: 现状默认, 如 C4 / C#4': 'Note+octave: current default, e.g. C4 / C#4',
    '纯音名: 只显示音级, 如 C / C#': 'Note name: pitch class only, e.g. C / C#',
    '唱名: 固定唱名+八度, 黑键带升号, 如 do[4] / ♯do[5]':
        'Solfège: fixed-do with octave, sharps on black keys, e.g. do[4] / ♯do[5]',
    '简谱: 以 C 调记谱+八度, 黑键带升号, 如 1[4] / ♯4[5]':
        'Numbered: in C with octave, sharps on black keys, e.g. 1[4] / ♯4[5]',
    '键位: 已映射显示按键字母, 未映射显示音名; 黑键加♯, 如 A[4] / ♯C[5]':
        'Keymap: mapped notes show the key letter, unmapped show the note name;'
        ' sharps on black keys, e.g. A[4] / ♯C[5]',
    '自定义: 按音级 (C..B) 逐格填写显示字符': 'Custom: fill text per pitch class (C..B)',
    '不显示: 音符上不画任何文字': 'Hidden: draw no text on notes',
    # ---- 设置弹窗 (新增) ----
    '发声输出设备 (SF2 试听与演奏发声的音频输出)':
        'Audio output device (for SoundFont playback)',
    '驱动': 'Driver',
    '自动': 'Auto',
    '设备': 'Device',
    '系统默认': 'System default',
    '切换设备需重建音源; 播放中不可切换':
        'Switching rebuilds the audio engine; not allowed while playing',
    '语言 / Language': '语言 / Language',
    '中文': '中文 (Chinese)',
    '切换立即生效; 如编辑器已打开将先关闭':
        'Applies immediately; an open editor is closed first',
    # ---------------- 对齐 / 通用 ----------------
    '第一排': 'Row 1',
    '第二排': 'Row 2',
    '第三排': 'Row 3',
    '最小化': 'Minimize',
    '最大化 / 还原': 'Maximize / Restore',
    '关闭': 'Close',
    # ---------------- 每轨独立音源 / 编辑器选区分析 (O 轮) ----------------
    '轨道音源': 'Track Sound Source',
    '音源': 'Sound',
    '音源 (留空 = 使用全局音源)': 'SoundFont (empty = use the global one)',
    '当前': 'Current',
    '使用全局音源': 'Use global SoundFont',
    '浏览 SF2…': 'Browse SF2…',
    '该轨音源 (单独指定 SF2 / 音色#)': 'Track sound source (separate SF2 / preset#)',
    '立即生效; 仅本次会话有效 (重新载入 MIDI 后还原为全局音源)':
        'Applies now; session-only (reset to the global SoundFont when the MIDI reloads)',
    '轨道音源已应用': 'Track sound source applied',
    '轨道音源 / 重命名': 'Track Sound Source / Rename',
    '轨道名称 / 音源': 'Track name / SoundFont',
    '名称': 'Name',
    '未设独立音源': 'No separate SoundFont',
    '不设独立音源': 'No separate SoundFont',
    '该轨静音/取消静音 (独立于主窗静音)':
        'Mute/unmute this track only (independent of the main mute button)',
    '单击 设为当前轨 · 双击 音源/重命名':
        'Click to make current · double-click for SoundFont/Rename',
    '选择当前轨 (新音符归属此轨)': 'Pick current track (new notes go here)',
    '选择当前轨 (新音符归属此轨) · 滑轮切换 · 尾部勾选显示音符':
        'Pick active track · mouse wheel switches · trailing checkbox shows notes',
    '显示该轨音符': 'Show this track\'s notes',
    # ---------------- 甲板右键/删除音轨 (Q 轮, 纯文字) ----------------
    '删除音轨': 'Delete Track',
    '音源 / 重命名…': 'SoundFont / Rename…',
    '至少保留一条音轨': 'At least one track must remain',
    '将删除音轨「{name}」及其 {n} 个音符, 确定?':
        'Delete track "{name}" and its {n} notes?',
    '音轨已删除': 'Track deleted',
    # ---------------- 变速编辑器 (Q 轮, 纯文字) ----------------
    '拖动顶部拉手 上下拉起变速 lanes · 拖动条 改 BPM · 双击 精确 BPM · 右键 分割/删除':
        'Drag the top grip to pull the tempo lanes up/down · drag a bar to change'
        ' BPM · double-click exact BPM · right-click split/delete',
    '当前: {v} BPM': 'Current: {v} BPM',
    '精确 BPM…': 'Exact BPM…',
    '上下拖动条 改 BPM (吸附整数) · 双击条 精确 BPM · 右键 分割/删除':
        'Drag a bar vertically to change BPM (snaps) · double-click exact BPM ·'
        ' right-click split/delete',
    '拖动顶部拉手 上下拉起演奏谱 · 字母=演奏事件 · 蓝线=未播余量(首尾圆点) · '
    '跟随模式整页翻页 · 刻度行双击改/插速度 · 右键 精确/删除 · 滚轮同卷帘':
        'Drag the top grip to pull the performance strip up/down · letters = events ·'
        ' blue lines = remaining duration (dots at ends) · follow mode pages ·'
        ' double-click ruler for tempo · right-click precise/delete · wheel = roll',
    '在光标处分割': 'Split at cursor',
    # ---------------- 音符属性/剪贴板/加选 (Q 轮, 纯文字) ----------------
    '音符属性': 'Note Properties',
    '音高': 'Pitch',
    '力度': 'Velocity',
    '起点': 'Start',
    '时值': 'Duration',
    '已修改音符属性': 'Note properties changed',
    '已复制 {n} 个音符': 'Copied {n} notes',
    '已剪切 {n} 个音符': 'Cut {n} notes',
    '已粘贴 {n} 个音符': 'Pasted {n} notes',
    '剪贴板为空': 'Clipboard is empty',
    '没有选中的音符': 'No notes selected',
    '删除事件 (与前一合并)': 'Delete event (merge into previous)',
    '最早的事件不可删除': 'The earliest event cannot be deleted',
    '精确 BPM': 'Exact BPM',
    'BPM (20 ~ 400)': 'BPM (20 ~ 400)',
    '单击/拖动 定位播放头 · 双击 设置该轨音源':
        'Click/drag to seek · double-click for this track\'s SoundFont',
    '音源 / 重命名': 'SoundFont / Rename',
    '请先在轨道架为音轨指定 SF2 音源:\n工具条 轨道 → 每行 音源 按钮':
        'Assign an SF2 per track first:\ntoolbar Tracks → the Sound button on each row',
    'SF2 请通过 轨道架 的 音源 按钮为音轨单独指定':
        'Assign SF2 files per track via the Sound button in the Track Rack',
    '分析': 'Analyze',
    '分析选中音符移调的黑键数量 (逻辑同主窗移调分析)':
        'Black-key counts per transpose offset for the selection '
        '(same logic as the main-window analysis)',
    '请先框选/选择音符后再分析': 'Box-select or select notes before analyzing',
    '已将选中音符移调 {n:+d} 半音': 'Transposed the selection by {n:+d} semitones',
    'Line (自适应)': 'Line (adaptive)',
    '模型扒谱环境自检 (Python / PyTorch / GPU / FFmpeg / 权重)':
        'Transcription env check (Python / PyTorch / GPU / FFmpeg / weights)',
    '运行环境自检': 'Run environment check',
    '逐项检测模型扒谱所需环境, 并给出对应显卡的安装建议':
        'Check every requirement for model transcription, with install tips '
        'matched to your GPU',
    '点击「运行环境自检」检测 Python / PyTorch / GPU / FFmpeg / 模型权重':
        'Click "Run environment check" to test Python / PyTorch / GPU / '
        'FFmpeg / model weights',
    '截断': 'Truncate',
    '当前音轨同音高重叠截断: 每个音符结束 ≤ 下一同音高音符起始 (可撤销)':
        'Truncate same-pitch overlaps in the current track: each note ends '
        'at or before the next same-pitch note start (undoable)',
    '当前音轨无同音高重叠': 'No same-pitch overlaps in the current track',
    '已截断 {n} 处同音高重叠': 'Truncated {n} same-pitch overlap(s)',
    # ---------------- 多音高分析 / 模型扒谱 ----------------
    '扒谱': 'Transcribe',
    '多音高分析': 'Multipitch',
    '模型扒谱': 'Model transcribe',
    '导入音频: librosa 多音高识别 → 声组织 (只读参考层)':
        'Import audio: librosa multipitch → sound tissue (read-only reference)',
    '导入音频: MuScriptor 模型 → 按乐器建轨写音符':
        'Import audio: MuScriptor model → tracks/notes by instrument',
    '选择音频': 'Choose audio',
    '多音高分析中: 生成声组织…': 'Multipitch analysis: building tissue…',
    '多音高分析失败': 'Multipitch analysis failed',
    '模型扒谱失败': 'Model transcription failed',
    '声组织就绪 · {n} 条轨迹': 'Tissue ready · {n} trajectory/trajectories',
    '模型扒谱中: 已选 {n} 种乐器…': 'Model transcribing: {n} instrument(s)…',
    '模型扒谱中: 自动检测乐器…': 'Model transcribing: auto-detect instruments…',
    '模型扒谱完成 · 已写入 {n} 个音符': 'Model done · wrote {n} note(s)',
    '开始模型扒谱': 'Start model transcription',
    '导入音频: 多音高→声组织(只读) + MuScriptor→按乐器建轨写音符':
        'Import audio: multipitch→sound tissue (RO) + MuScriptor→tracks/notes',
    '导入音频转录': 'Import audio for transcription',
    '音频 (*.wav *.mp3 *.flac *.ogg *.m4a *.aac);;全部 (*.*)':
        'Audio (*.wav *.mp3 *.flac *.ogg *.m4a *.aac);;All (*.*)',
    '扒谱中: 声组织分析 + MuScriptor 写轨…':
        'Transcribing: analyzing tissue + writing tracks…',
    '扒谱完成 · 已写入 {n} 个音符': 'Transcription done · wrote {n} note(s)',
    '扒谱失败': 'Transcription failed',
    '轨道 1': 'Track 1',
    '选择乐器': 'Select instruments',
    '不选 = 自动检测全部乐器; 勾选后只识别所选乐器 (MuScriptor 硬约束)。\n'
    '名称对应官方 list-instruments。':
        'None selected = auto-detect all instruments; checked = hard-constrain '
        'to those groups (MuScriptor).\nNames match official list-instruments.',
    '全选': 'Select all',
    '全不选 (自动检测)': 'Clear (auto-detect)',
    '开始扒谱': 'Start transcription',
    '扒谱中: 已选 {n} 种乐器 · 声组织 + MuScriptor 写轨…':
        'Transcribing: {n} instrument(s) · tissue + MuScriptor…',
    '扒谱中: 自动检测乐器 · 声组织 + MuScriptor 写轨…':
        'Transcribing: auto-detect instruments · tissue + MuScriptor…',
    # ---------------- 原曲播放 / 导入 MIDI 到当前轨 ----------------
    '播放原曲': 'Play original',
    '勾选后与钢琴卷帘同步播放原曲音频 (Alt+F1 切换);\n'
    '扒谱时自动使用该音频; 否则请先选择音频文件':
        'When checked, play original audio synced with the piano roll '
        '(Alt+F1 toggles);\ntranscription uses that audio; otherwise pick a file first',
    '音量': 'Vol',
    '原曲播放音量': 'Original playback volume',
    '选择音频…': 'Choose audio…',
    '选择要作为原曲播放的音频文件':
        'Choose an audio file to play as the original',
    '导入 MIDI': 'Import MIDI',
    '导入 MIDI 并覆盖当前显示音轨上的全部音符':
        'Import MIDI and overwrite all notes on the current track',
    '原曲: {f}': 'Original: {f}',
    '原曲: 未选择': 'Original: none',
    '选择原曲音频': 'Choose original audio',
    '已选择原曲: {f}': 'Original set: {f}',
    '导入 MIDI 到当前音轨': 'Import MIDI onto current track',
    'MIDI 文件 (*.mid *.midi);;全部 (*.*)':
        'MIDI files (*.mid *.midi);;All (*.*)',
    '导入失败': 'Import failed',
    '无法读取 MIDI:\n{e}': 'Cannot read MIDI:\n{e}',
    '该 MIDI 没有可导入的音符': 'This MIDI has no notes to import',
    '已导入 MIDI 到当前音轨 · {n} 个音符':
        'Imported MIDI onto current track · {n} note(s)',
    '显示声组织': 'Show tissue',
    '显示 / 隐藏 Tonteppich (Sound Tissue / 声组织) 层':
        'Show / hide Tonteppich (Sound Tissue) layer',
    '音量增幅': 'Volume boost',
    '增强该轨音源响度 (100%=原声, 最高 800%)':
        'Boost this track\'s SoundFont level (100%=original, up to 800%)',
    '音源…': 'Sound…',
    '为当前音轨指定 SF2 音源, 并可增强响度至 800%':
        'Assign an SF2 to the current track; boost volume up to 800%',
    # ---------------- FL 甲板 / BPM / 映射范围 (P 轮, 纯文字) ----------------
    '导入 MIDI 后在此显示音轨': 'Import a MIDI to see tracks here',
    '新增空音轨 (在编辑器中选中该轨绘制音符)':
        'Add an empty track (select it in the editor to draw notes)',
    '已新增音轨 {n}: 在编辑器中选中该轨即可绘制音符':
        'Track {n} added: select it in the editor to draw notes',
    '新音轨 {n}': 'New Track {n}',
    '单击/拖动 定位播放头 · 双击 设置该轨音源 · 滑轮 前进/后退':
        'Click/drag to seek · double-click for this track\'s SoundFont · '
        'wheel to jump forward/back',
    '该轨音源 (单独指定 SF2 / 音色#)': 'Track sound source (separate SF2 / preset#)',
    '映射范围': 'Mapping scope',
    '合并所有音轨': 'All tracks merged',
    '仅当前音轨': 'Current track only',
    '键盘映射/演奏只输出所选范围的音符':
        'Keyboard mapping/performance only outputs notes in the selected scope',
    '播放速度 (导入 MIDI 时读取文件 BPM; 改值即变速)':
        'Playback tempo (file BPM is read on import; edit to change tempo)',
    'BPM': 'BPM',
    '已打开 {f} · 拍号 {a}/{b} · BPM {bpm} · tempo 变化 {c} 处 · 点 编曲 编辑':
        'Opened {f} · time sig {a}/{b} · BPM {bpm} · {c} tempo changes · '
        'open Editor to edit',
}


def set_lang(lang):
    """切换界面语言 ('zh'/'en'); 未知值回退中文"""
    global LANG
    LANG = lang if lang in ('zh', 'en') else 'zh'


def get_lang():
    return LANG


def t(key, **kw):
    """取当前语言的文案; 英文缺 key 时回退中文原文; kw 为 .format 填充"""
    txt = key if LANG == 'zh' else _EN.get(key, key)
    return txt.format(**kw) if kw else txt
