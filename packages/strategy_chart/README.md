# 策略运行复盘图

`strategy_chart` 为 TDR 离线回测图和 PTE 前瞻图提供相同的图表资源，无交易、网络或账户依赖。
调用方保留页面标题、回测绩效指标、数据读取及身份校验职责。TDR将此组件嵌入回测绩效指标之后的
“策略运行复盘”章节，PTE用于前瞻观察，两者共用观察投影和交互方式。

## 接入

Python 使用 `get_chart_assets()` 取得不可变 `ChartAssets(css, javascript)`，使用
`chart_body()` 生成工具栏、图表和事件区。离线文档内嵌资源；服务端可以通过自己的静态路由提供。
父容器使用 `strategy-chart` 类名，浏览器调用：

```javascript
const view = mountStrategyChart(container, context);
// 删除页面区域前释放 ResizeObserver、监听器和动态节点。
view.destroy();
```

每个容器只允许挂载一次，销毁后可重新挂载。选择器、主题变量和交互均限定在该容器。
上下文提供 `mode`（`BACKTEST` 或 `PAPER`）、`strategy`、`window`、`market_data.bars`、
`observations` 及 `execution`。调用方负责验证来源及身份；渲染器不推导交易规则。
完整投影类型见 [strategy-chart.d.ts](src/strategy_chart/static/strategy-chart.d.ts)。
`observations`、行情及执行的三个数组必须显式提供，包括空数组；非法模式或缺少容器结构直接报错。

成交记录使用 `fee`，交易日使用 `session`。仅有交易日的记录使用 `time_precision: "SESSION"`，
不生成虚构时刻；有时刻的记录按北京时间显示。

## 解释与布局

顺序为价格、持仓、信号、事件。宽屏信号区域显示“当前判断、判断依据、接下来关注”三栏；
“解释”仅将第二栏切换为“怎么看这个判断”，保留第一栏判断及事件区域。
布局优先适配宽屏并压缩工具栏与信号区高度；信号区左侧保留区域名称，各栏标题固定在左上方。
窄屏按可用宽度调整排列。日期选择联动图表与事件区，不提供单独的“事件日期”选择项。

新观察读取 SRT 已固化的 `signal_panel.explanation`：`state_key`、`case_key`、`judgment`、
`basis[{key,text}]`、`next_watch`、`explanation`。文本使用 `textContent`，不执行 HTML 或表达式。
旧观察保留原始序列、状态及声明口径，并显示“该记录未提供解释”，不利用当前策略反推历史文案。
观察不可用和日期无观察分别显示；非交易日仍显示所选日期的事件，不沿用前一交易日的判断。

两种宿主共用同一资源，不复制策略文案、不依赖 PTE 服务生成回测图。历史文件保持原样。
策略负责声明解释事实，SRT负责解析并固化快照，宿主负责投影，SC只按合同渲染；升级静态资源不会
为旧观察补造解释，也不会改变策略计划或账户账本。

## 聚焦验证

`node --test packages/strategy_chart/tests/chart.test.cjs` 从仓库根目录运行公开挂载接口测试，
覆盖解释切换、纯文本安全、日期联动、非交易日、费用与时间精度、不可用及旧观察、
无行情时的事件保留、多实例隔离、销毁和重新挂载。测试使用确定性 DOM 适配器；
实际宽屏与窄屏的视觉布局另外通过浏览器检查，不用适配器测试代替像素验证。
