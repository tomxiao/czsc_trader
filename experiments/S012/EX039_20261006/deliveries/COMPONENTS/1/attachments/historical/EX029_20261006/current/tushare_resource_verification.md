# Tushare DXY/GVZ资源核查与实现方案

用户最新指令：tushare有这两个数据吗？有的话就优先使用，没有的话告诉我要接入哪个数据源，需要如何实现。

## 已核实

Tushare官方[index_global目录](https://tushare.pro/wctapi/documents/211.md)未列ICE DXY或GVZ；[fx_obasic](https://tushare.pro/document/2?doc_id=178)目录标注FX_BASKET的USDOLLAR。实查fx_obasic返回69个FXCM品种，仅USDOLLAR.FXCM命中美元指数/波动率相关搜索，无DXY/USDX/GVZ；见[实际目录回执](tushare_inventory.json)。这证明公开可确认目录中的情况，不声称穷尽未公开Tushare接口。

[FXCM官方](https://www.fxcm.com/za/help/forex-baskets-usdollar-the-dollar-index/)说明USDOLLAR为欧元、英镑、日元、澳元四腿篮子，基值10000。[ICE官方](https://www.ice.com/fixed-income-data-services/index-solutions/currency-indices)将DXY列为ICE U.S. Dollar Index；六币权重口径不同。可以把USDOLLAR作为明确命名的替代美元强弱研究变量，不能标为DXY或称等价复现。

## 可选路线

1. 最省平台改动：若用户接受美元强弱代理，则通过现有Dataset.FXCM_DAILY准备USDOLLAR.FXCM，复用现有Tushare与FXCM可得时间契约。仅取得标的目录，尚未抓取或确认2020—2026完整报价覆盖；正式前驱取数后才确认可用窗口。它是机制替代方案，不自动扩展为DXY授权。
2. GVZ建议用FRED的[GVZCLS](https://fred.stlouisfed.org/series/GVZCLS)，其明确来源CBOE、日频收盘值。使用现有FRED密钥配置和requests能力，调用官方[series/observations](https://fred.stlouisfed.org/docs/api/fred/series_observations.html)。取2020-01-01—2026-09-30及必要预热；保存原响应、首次发布/修订日期、拉取时间与SHA。FRED转载更新时间可能晚于CBOE，应按所选获取渠道可得时间对齐，不能将FRED观察日期直接当作可用时刻。ALFRED首次发布可得日期若不能恢复，则明确留证缺口，不能补造历史真实时刻。
3. 必须是DXY时：数据源ICE Data Indices的DXY原指数，先确认全窗口EOD历史导出/API、收盘定义与授权。当前官方页面已确认指数身份，没有确认免登录免费完整历史接口；可能需要数据许可或授权分发商，费用需另行确认。不可把美元指数期货连续合约、FXCM篮子或美联储贸易加权美元指数改名代替。

CBOE官方公开CSV入口在本次网页工具中重定向后不可访问，尚未核实直连可用和覆盖；当前建议以已经确认的FRED官方分发序列为GVZ方案，不将网页抓取或未验证CSV链接作为既定实现。

## DFLS实现边界

已有ProviderBinding仅能绑定已有强类型Dataset，当前没有通用FRED指数或黄金波动率Dataset。不能把GVZ塞进只接受VIX的VIX_DAILY，也不能借用US_POLICY_UNCERTAINTY的数据契约；RSCH不直接在实验里绕过DFLS拉取真实行情。

建议获批后暂切DEV，增加一个语义明确的黄金预期波动率日序列契约及FRED提供器。最小字段Date/Close/AvailableDate，原始来源CBOE、分发FRED、serie_id=GVZCLS，公开获取仍统一Dataflows.prepare/fetch；明确美国源日历、缺失/重复/非正值、日期覆盖、修订和时间契约，聚焦测试这些输入边界。若另获批ICE DXY，再增加独立美元指数语义契约及有权限的ICE提供器。复用现有凭据配置、缓存、版本和PrepareRef，不新增第三方依赖。

如选USDOLLAR+GVZ，只需USDOLLAR沿现有FXCM入口，DEV最小增加GVZ一条契约和提供器；之后回RSCH，新建S012受管正式取数前驱，先冻结方向/父对照/主期限并核验完整性与可得时点，再做固定机制研究。当前仅资源审查和元数据查询，未取得新外部来源或DEV实施批准。
