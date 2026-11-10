// osu!lazer UI 动画规范
// 基于 osu-framework 和 osu.Game 源码提取的常用缓动曲线、时长和交互规则
// 参考: osu.Framework/Graphics/Easing.cs, osu.Game/Graphics/UserInterface/OsuButton.cs

pragma Singleton
import QtQuick 2.15

QtObject {
    // ===== 缓动曲线 (QML Easing.Type) =====
    // osu 最常用: OutQuint, OutElastic, InOutQuint, InOutExpo
    readonly property int outQuint: Easing.OutQuint         // 按钮悬停、淡入淡出、缩放恢复
    readonly property int outElastic: Easing.OutElastic     // 按钮按下后弹回
    readonly property int inOutQuint: Easing.InOutQuint     // 面板滑入滑出
    readonly property int inOutExpo: Easing.InOutExpo       // 复选框勾选、下载按钮状态切换
    readonly property int outExpo: Easing.OutExpo           // 快速淡出
    readonly property int outCirc: Easing.OutCirc           // 圆形进度
    readonly property int outBack: Easing.OutBack           // 轻微超调回弹
    readonly property int inBack: Easing.InBack             // 压缩后弹出

    // ===== 动画时长 (ms) =====
    // 快速反馈
    readonly property int instant: 40          // 悬停初始闪烁 (OsuButton: 0→0.2 用 40ms)
    readonly property int veryFast: 150        // 最短交互
    readonly property int fast: 200            // 快速状态切换、FPS 计数器背景
    
    // 标准反馈
    readonly property int normal: 300          // 标准淡入淡出、下拉框展开
    readonly property int medium: 500          // 面包屑导航、扩展滑块、下载按钮
    readonly property int slow: 800            // 悬停层淡出、按钮悬停稳定 (0.2→0.1 用 800ms)
    
    // 长时反馈
    readonly property int elastic: 1000        // 弹性回弹 (按钮按下恢复)
    readonly property int veryLong: 4000       // 按钮按下缩放 (慢速 OutQuint 到 0.9)

    // ===== 按钮交互规则 (OsuButton.cs) =====
    // 悬停: 0 → FadeTo(0.2, 40ms, OutQuint) → FadeTo(0.1, 800ms, OutQuint)
    readonly property real hoverInitialAlpha: 0.2    // 悬停瞬间峰值
    readonly property real hoverFinalAlpha: 0.1      // 悬停稳定亮度
    readonly property int hoverPeakDuration: 40      // 到达峰值时长
    readonly property int hoverSettleDuration: 800   // 稳定时长
    
    // 悬停离开: FadeOut(800ms, OutQuint)
    readonly property int hoverLostDuration: 800
    
    // 按下: ScaleTo(0.9, 4000ms, OutQuint)
    readonly property real pressScale: 0.9           // 按下缩放目标
    readonly property int pressDuration: 4000        // 按下缩放时长 (很慢, 长按时会继续)
    
    // 释放: ScaleTo(1.0, 1000ms, OutElastic)
    readonly property real releaseScale: 1.0         // 释放恢复目标
    readonly property int releaseDuration: 1000      // 释放回弹时长
    
    // 禁用状态透明度
    readonly property real disabledAlpha: 0.3

    // ===== 常用组合动画参数 =====
    // 淡入: 用于面板、弹窗显示
    readonly property int fadeInDuration: 300
    readonly property int fadeInEasing: outQuint
    
    // 淡出: 用于面板、弹窗隐藏
    readonly property int fadeOutDuration: 300
    readonly property int fadeOutEasing: outQuint
    
    // 滑入/滑出: 用于侧边栏、设置面板
    readonly property int slideDuration: 500
    readonly property int slideEasing: inOutQuint
    
    // 弹出/收起: 用于下拉菜单、工具提示
    readonly property int popupDuration: 200
    readonly property int popupEasing: outQuint

    // ===== 通知和提示 =====
    readonly property int notificationDuration: 300     // 通知淡入淡出
    readonly property int tooltipDelay: 500             // 工具提示延迟显示

    // ===== 缩放和旋转 =====
    readonly property real scaleHoverAmount: 1.05       // 悬停轻微放大 (某些图标按钮用)
    readonly property int scaleHoverDuration: 200

    // ===== 颜色过渡 =====
    readonly property int colorTransitionDuration: 120  // 颜色切换 (如小球红蓝切换)
    readonly property int colorTransitionEasing: outQuint
}
