# S017：统一Calmar自检约定修订

用户已确认统一Calmar标准及RSCH制定/最终核验硬门、TDR按显式输入计算与排序的分工，并授权DEV补齐能力后由RSCH验收。本修订替代旧参数及压力年化收益门，保留MANDATE/7、原始账户及旧规则结果，不改写历史。

中心Calmar严格>同合同买持1.5倍，DD≤买持0.8倍且≤25%。完整邻域至少ceil(13N/16)点同时满足Calmar≥买持1.25倍、DD≤买持0.9倍；全部点DD≤25%。压力每侧0.2%时Calmar严格>同场景买持，保留相对/绝对DD规则。原双频率要求、2024—2025训练和2026封存边界不变。Calmar须DD>1e-12且商有限，缺失不补值、不删点。

新版排序以中心Calmar/DD分层，同层依次为邻域Calmar Q10、邻域DD Q90、滚动超额Calmar Q10、压力Calmar下降量、最大单笔盈利贡献及60日闭合中位。原数值精度及方向保持，不以旧年化指标替代。时间/集中度/统计不确定性不新增硬门。

DEV的236项SE、110项TDR聚焦检查通过；RSCH复用16个已发布账户验证新目标及逐柱公式，零新回放。4个旧年化邻域门失败点均通过新Calmar点条件；6压力Calmar目标均通过。完整N仍不足，不能称策略或阶段四已通过，当前无正式选型排名。

252个已发布邻点保留，2577个未运行点仍暂停；12并发尚未启动。研究目标由用户确认，RSCH对规则和最终研究结论负责；平台的类型、身份、时间、资源、证据及数值验证不替代研究验收。技术能力验收通过不自动恢复研究、打开封存样本或授权冻结/生产/远端操作。

依据：

- [calmar-v2-compute-request](evidence/e85d029b12b79e1e9e29c78107c1b7c22c4e7cc3f7f5a89e23fae6890386f040.md)
- [calmar-v2-dev-authorization](evidence/eb911d07526a32d523dbe5cb9eaccff5283ec7754f2c9828475db6d6b9259107.json)
- [calmar-v2-dev-completion](evidence/2e5f4e9a2b3fb33a28ab3a914b4eecc02fe8c1ab8a26458ebd737a8e06dd3e83.json)
- [calmar-v2-rsch-acceptance](evidence/8a0a9993abc4116220db01037ec9b04d273b04399130b12f46fc3dce83dc1271.json)
- [calmar-v2-targets](evidence/0f11398793a7eb641271374f0ea3aa15c013d5ec876ae40cacef92bf1030aaeb.json)
- [calmar-v2-acceptance-panel](evidence/6a02b47266394aad4c1f0b8b94756bbdfd5f156546653c6b091638d2b8ee92bb.json)
- [calmar-v2-acceptance-comparison](evidence/d0bb52496d87eb627f3ef2c59068ee1cdc81e88303cb4335ea314ebd0ef6f67d.json)
- [calmar-v2-acceptance-source](evidence/e42e7ae8b10f211fce258464d19f177a6999aca02df7d73896d9cafa9b1d3126.py)
- [calmar-v2-publication-source](evidence/a8b17543b203e895cd51fcd8e187c73428d9dfc7f3d1d9916ebf80c75617249a.py)
- [user-12-worker-authorization-and-pause](evidence/72f751e6c29d7daeac63c9c76ce4cb1891e1896a4c9e8735d98d5477afc23824.json)