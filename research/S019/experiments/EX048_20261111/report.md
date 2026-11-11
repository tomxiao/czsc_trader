# 新授权阶段三第2轮：连续退出的参数交互与敏感性

Status: COMPLETE；RSCH；阶段三优化研究。

123个配置全部完成，92个通过原中心六门。两个渐进族的有限诊断点均守住原邻点经济条件；领先硬退出配置仍暴露ATR下调方向的跳变。新增各族领先点为C0966、C1010、C1045。下一轮以少数代表的费用配对回答连续调仓成本问题，再决定阶段三收口。

原中心NAR≥55%、Calmar≥5、日末MDD≤25%且≤同费用买持80%；60日闭合中位数≥6，至少3笔窗口覆盖≥90%。正式邻域80%及费用压力条件保持。

## 尝试与收获

本轮为事前固定因素诊断：5个锚点，各有效轴相对上下5%、渐进退出二轴角点、参与三轴角点及全轴同向变化，共123个配置。6个EX046原型ATR点严格核对原请求，仅实验归属不同后复用；117个新策略账户和1个共享买持全部完成。5个中心复算的逐柱、逐日、目标与成交经济路径精确一致。

硬退出原型控制与C0829的ATR三档Calmar跨度分别为0.887772、0.901875，扩域提高收益后，ATR跳变问题仍在。C0829的ATR下调5%得到Calmar4.361202，全轴下调5%为4.261307；其有限非中心点经济通过率90%（N=20），原型控制为100%（N=20），最低Calmar4.541592。这里保留实际点集分母，完整笛卡尔邻域尚待阶段四。

单向渐进原型C0801（复算C0855/C0993）在本轮26个有限非中心点全部满足邻点经济条件；全组最低Calmar4.920761。ATR三档跨度0.103196，退出二轴含中心跨度0.110033；参与阈值和参与三轴仍有更明显的收益/回撤取舍。参与阈值下调点C0998的Calmar4.999471734按未舍入值未过中心门5。

可恢复渐进C0924和原型C0804（复算C0903/C1047）的26个有限非中心点分别全部满足邻点经济条件；全组最低Calmar4.760296和4.868951。ATR三档跨度分别0.142743和0.314086，退出二轴跨度0.167850和0.323005。本轮联合配置下的ATR反应较平缓；C0924最高NAR的代价是中心Calmar仅5.026881，多个邻近配置低于中心5而仍高于邻点4.5。

硬退出本轮原六门后最高NAR为C0966：NAR71.480296%、MDD14.110987%、Calmar5.065577253。该配置作为新的中心达标实现保留；其自身完整邻域尚未展开，所属锚点的有限诊断另列。

单向渐进本轮原六门后最高NAR为C1010：NAR66.945249%、MDD13.350808%、Calmar5.014322087。该配置作为新的中心达标实现保留；其自身完整邻域尚未展开，所属锚点的有限诊断另列。

可恢复渐进本轮原六门后最高NAR为C1045：NAR70.900478%、MDD14.112207%、Calmar5.024053077。该配置作为新的中心达标实现保留；其自身完整邻域尚未展开，所属锚点的有限诊断另列。

C0966与C1010来自参与q/t/h联合变化；C1045来自C0924六轴同时下调5%。它们是完整参数协作结果。全部123点中92点通过原中心六门，余31点均仅Calmar未过；全部点通过MDD和原频率目标。正式中心排序保持六门后未舍入NAR，有限诊断未添加新评分或淘汰门。

账本保留完整期末持仓及浮动盈亏。C0966和C1010的MDD均在2024-04-03至04-19，分别于2024-11-05和11-06恢复；C1045同段MDD于2024-07-03恢复。C0924及其全轴上调点的MDD仍在2026-10-07至样本终点10-30，未恢复。C1045相对原可恢复控制的2022、2023年收益较低，2024至2026较高，主要增长增量在2025、2026；近期收益改善与早期反例同时保留。

固定因素对照回答了搜索后的局部敏感方向；这与第1轮Optuna自适应提议各有用途。5个锚点覆盖的跨组反向联动仍有限。17个中心、控制、最高NAR和不利代表共266934条决定完成独立业务重建，全部通过；全部配置完整指标、方向范围、正反例与路径见[有限交互分析](others/diagnostic_analysis.md)及[结构化证据](others/diagnostic_analysis.json)。

方案及实际参数见[事前方案](protocols/plan.md)、[完整配置](protocols/specs.json)。

## 完整账户成绩

|配置|候选|NAR|MDD|Calmar|60日闭合中位|至少3笔覆盖|中心六门|
|---|---|---:|---:|---:|---:|---:|---|
|hard_linear_control_trail_atr_lo|C0799|62.1402%|13.4919%|4.605738|6|99.8265%|未通过|
|hard_linear_control_trail_atr_hi|C0800|66.6627%|13.0337%|5.114659|6|99.8265%|通过|
|ramp_linear_winner_trail_atr_lo|C0802|62.7950%|12.2666%|5.119182|6|99.8265%|通过|
|ramp_linear_winner_trail_atr_hi|C0803|65.7899%|12.7541%|5.158350|6|99.8265%|通过|
|rebuild_linear_control_trail_atr_lo|C0805|66.2478%|12.2396%|5.412563|6|99.8265%|通过|
|rebuild_linear_control_trail_atr_hi|C0806|66.0971%|12.9641%|5.098477|6|99.8265%|通过|
|hard_linear_winner_center|C0951|68.9675%|13.1040%|5.263078|6|99.8265%|通过|
|hard_linear_control_center|C0972|67.2761%|12.2465%|5.493510|6|99.8265%|通过|
|ramp_linear_winner_center|C0993|64.7443%|12.3975%|5.222378|6|99.8265%|通过|
|rebuild_linear_winner_center|C1020|70.3681%|13.9984%|5.026881|6|99.8265%|通过|
|rebuild_linear_control_center|C1047|66.3048%|12.6141%|5.256417|6|99.8265%|通过|
|hard_linear_winner_weak_fraction_lo|C0952|68.8458%|13.0885%|5.260037|6|99.8265%|通过|
|hard_linear_winner_weak_fraction_hi|C0953|69.0895%|13.0827%|5.280988|6|99.8265%|通过|
|hard_linear_winner_quiet_fraction_lo|C0954|68.8169%|13.0210%|5.285061|6|99.8265%|通过|
|hard_linear_winner_quiet_fraction_hi|C0955|69.1393%|13.1692%|5.250071|6|99.8265%|通过|
|hard_linear_winner_participation_threshold_lo|C0956|71.0304%|13.9194%|5.102983|6|99.8265%|通过|
|hard_linear_winner_participation_threshold_hi|C0957|66.5658%|12.5259%|5.314231|6|99.8265%|通过|
|hard_linear_winner_participation_width_lo|C0958|69.3041%|13.1957%|5.252016|6|99.8265%|通过|
|hard_linear_winner_participation_width_hi|C0959|68.5826%|13.0108%|5.271218|6|99.8265%|通过|
|hard_linear_winner_trail_atr_lo|C0960|63.1985%|14.4911%|4.361202|6|99.8265%|未通过|
|hard_linear_winner_trail_atr_hi|C0961|68.2376%|13.7030%|4.979748|6|99.8265%|未通过|
|hard_linear_winner_participation_joint_0|C0962|71.2622%|13.9952%|5.091901|6|99.8265%|通过|
|hard_linear_winner_participation_joint_1|C0963|70.5609%|13.7194%|5.143150|6|99.8265%|通过|
|hard_linear_winner_participation_joint_2|C0964|66.7570%|12.5360%|5.325240|6|99.8265%|通过|
|hard_linear_winner_participation_joint_3|C0965|65.9866%|12.4695%|5.291843|6|99.8265%|通过|
|hard_linear_winner_participation_joint_4|C0966|71.4803%|14.1110%|5.065577|6|99.8265%|通过|
|hard_linear_winner_participation_joint_5|C0967|70.8184%|13.8532%|5.112052|6|99.8265%|通过|
|hard_linear_winner_participation_joint_6|C0968|67.1327%|12.5705%|5.340500|6|99.8265%|通过|
|hard_linear_winner_participation_joint_7|C0969|66.3814%|12.5147%|5.304265|6|99.8265%|通过|
|hard_linear_winner_all_lo|C0970|65.0578%|15.2671%|4.261307|6|99.8265%|未通过|
|hard_linear_winner_all_hi|C0971|65.8137%|13.5305%|4.864085|6|99.8265%|未通过|
|hard_linear_control_weak_fraction_lo|C0973|67.1573%|12.2637%|5.476123|6|99.8265%|通过|
|hard_linear_control_weak_fraction_hi|C0974|67.3885%|12.4626%|5.407245|6|99.8265%|通过|
|hard_linear_control_quiet_fraction_lo|C0975|66.9874%|12.1547%|5.511252|6|99.8265%|通过|
|hard_linear_control_quiet_fraction_hi|C0976|67.6073%|12.4004%|5.452044|6|99.8265%|通过|
|hard_linear_control_participation_threshold_lo|C0977|69.7832%|13.2594%|5.262907|6|99.8265%|通过|
|hard_linear_control_participation_threshold_hi|C0978|64.3906%|11.9424%|5.391747|6|99.8265%|通过|
|hard_linear_control_participation_width_lo|C0979|67.4255%|12.2654%|5.497232|6|99.8265%|通过|
|hard_linear_control_participation_width_hi|C0980|67.0928%|12.2568%|5.473938|6|99.8265%|通过|
|hard_linear_control_participation_joint_0|C0983|69.7229%|13.2070%|5.279229|6|99.8265%|通过|
|hard_linear_control_participation_joint_1|C0984|69.3749%|13.0739%|5.306352|6|99.8265%|通过|
|hard_linear_control_participation_joint_2|C0985|64.1828%|11.9353%|5.377580|6|99.8265%|通过|
|hard_linear_control_participation_joint_3|C0986|63.8694%|11.8762%|5.377944|6|99.8265%|通过|
|hard_linear_control_participation_joint_4|C0987|70.1682%|13.4273%|5.225801|6|99.8265%|通过|
|hard_linear_control_participation_joint_5|C0988|69.8285%|13.3084%|5.246959|6|99.8265%|通过|
|hard_linear_control_participation_joint_6|C0989|64.9634%|11.9941%|5.416278|6|99.8265%|通过|
|hard_linear_control_participation_joint_7|C0990|64.6255%|11.9544%|5.406006|6|99.8265%|通过|
|hard_linear_control_all_lo|C0991|64.1209%|14.1186%|4.541592|6|99.8265%|未通过|
|hard_linear_control_all_hi|C0992|64.1014%|13.1759%|4.865039|6|99.8265%|未通过|
|ramp_linear_winner_weak_fraction_lo|C0994|64.6306%|12.3879%|5.217234|6|99.8265%|通过|
|ramp_linear_winner_weak_fraction_hi|C0995|64.8477%|12.3841%|5.236380|6|99.8265%|通过|
|ramp_linear_winner_quiet_fraction_lo|C0996|64.4825%|12.2462%|5.265514|6|99.8265%|通过|
|ramp_linear_winner_quiet_fraction_hi|C0997|64.9866%|12.5307%|5.186201|6|99.8265%|通过|
|ramp_linear_winner_participation_threshold_lo|C0998|66.9399%|13.3894%|4.999472|6|99.8265%|未通过|
|ramp_linear_winner_participation_threshold_hi|C0999|62.0248%|11.9296%|5.199222|6|99.8265%|通过|
|ramp_linear_winner_participation_width_lo|C1000|64.8763%|12.4084%|5.228409|6|99.8265%|通过|
|ramp_linear_winner_participation_width_hi|C1001|64.5524%|12.3769%|5.215564|6|99.8265%|通过|
|ramp_linear_winner_exit_width_lo|C1004|64.8108%|12.3515%|5.247199|6|99.8265%|通过|
|ramp_linear_winner_exit_width_hi|C1005|64.6330%|12.4214%|5.203353|6|99.8265%|通过|
|ramp_linear_winner_exit_pair_0|C1006|62.8874%|12.3011%|5.112345|6|99.8265%|通过|
|ramp_linear_winner_exit_pair_1|C1007|62.7426%|12.2385%|5.126682|6|99.8265%|通过|
|ramp_linear_winner_exit_pair_2|C1008|65.8835%|12.7392%|5.171717|6|99.8265%|通过|
|ramp_linear_winner_exit_pair_3|C1009|65.6819%|12.7648%|5.145558|6|99.8265%|通过|
|ramp_linear_winner_participation_joint_0|C1010|66.9452%|13.3508%|5.014322|6|99.8265%|通过|
|ramp_linear_winner_participation_joint_1|C1011|66.5873%|13.2291%|5.033406|6|99.8265%|通过|
|ramp_linear_winner_participation_joint_2|C1012|61.9196%|11.7300%|5.278717|6|99.8265%|通过|
|ramp_linear_winner_participation_joint_3|C1013|61.5730%|11.7244%|5.251706|6|99.8265%|通过|
|ramp_linear_winner_participation_joint_4|C1014|67.3059%|13.5710%|4.959540|6|99.8265%|未通过|
|ramp_linear_winner_participation_joint_5|C1015|66.9731%|13.4654%|4.973701|6|99.8265%|未通过|
|ramp_linear_winner_participation_joint_6|C1016|62.5515%|12.1368%|5.153850|6|99.8265%|通过|
|ramp_linear_winner_participation_joint_7|C1017|62.1946%|12.1365%|5.124609|6|99.8265%|通过|
|ramp_linear_winner_all_lo|C1018|64.8658%|13.1821%|4.920761|6|99.8265%|未通过|
|ramp_linear_winner_all_hi|C1019|63.2133%|12.5398%|5.041009|6|99.8265%|通过|
|rebuild_linear_winner_weak_fraction_lo|C1021|70.2276%|13.9948%|5.018120|6|99.8265%|通过|
|rebuild_linear_winner_weak_fraction_hi|C1022|70.4668%|14.3579%|4.907883|6|99.8265%|未通过|
|rebuild_linear_winner_quiet_fraction_lo|C1023|70.0680%|13.9395%|5.026583|6|99.8265%|通过|
|rebuild_linear_winner_quiet_fraction_hi|C1024|70.6208%|14.2740%|4.947515|6|99.8265%|未通过|
|rebuild_linear_winner_participation_threshold_lo|C1025|71.7865%|14.7243%|4.875360|6|99.8265%|未通过|
|rebuild_linear_winner_participation_threshold_hi|C1026|68.5174%|13.8990%|4.929663|6|99.8265%|未通过|
|rebuild_linear_winner_participation_width_lo|C1027|70.4546%|14.0088%|5.029310|6|99.8265%|通过|
|rebuild_linear_winner_participation_width_hi|C1028|70.2221%|14.0113%|5.011822|6|99.8265%|通过|
|rebuild_linear_winner_trail_atr_lo|C1029|69.8429%|14.1056%|4.951411|6|99.8265%|未通过|
|rebuild_linear_winner_trail_atr_hi|C1030|70.4340%|14.4210%|4.884138|6|99.8265%|未通过|
|rebuild_linear_winner_exit_width_lo|C1031|70.3877%|14.0004%|5.027554|6|99.8265%|通过|
|rebuild_linear_winner_exit_width_hi|C1032|70.3024%|14.0412%|5.006866|6|99.8265%|通过|
|rebuild_linear_winner_exit_pair_0|C1033|69.7930%|14.3636%|4.859031|6|99.8265%|未通过|
|rebuild_linear_winner_exit_pair_1|C1034|69.8107%|14.1032%|4.949983|6|99.8265%|未通过|
|rebuild_linear_winner_exit_pair_2|C1035|70.4392%|14.4067%|4.889341|6|99.8265%|未通过|
|rebuild_linear_winner_exit_pair_3|C1036|70.3860%|14.3905%|4.891141|6|99.8265%|未通过|
|rebuild_linear_winner_participation_joint_0|C1037|71.5012%|14.6862%|4.868596|6|99.8265%|未通过|
|rebuild_linear_winner_participation_joint_1|C1038|71.5660%|14.5137%|4.930926|6|99.8265%|未通过|
|rebuild_linear_winner_participation_joint_2|C1039|68.2345%|13.7214%|4.972871|6|99.8265%|未通过|
|rebuild_linear_winner_participation_joint_3|C1040|68.0067%|13.7512%|4.945516|6|99.8265%|未通过|
|rebuild_linear_winner_participation_joint_4|C1041|71.9240%|14.9186%|4.821082|6|99.8265%|未通过|
|rebuild_linear_winner_participation_joint_5|C1042|71.9791%|14.7705%|4.873174|6|99.8265%|未通过|
|rebuild_linear_winner_participation_joint_6|C1043|68.9918%|14.1958%|4.860010|6|99.8265%|未通过|
|rebuild_linear_winner_participation_joint_7|C1044|68.7547%|14.1816%|4.848169|6|99.8265%|未通过|
|rebuild_linear_winner_all_lo|C1045|70.9005%|14.1122%|5.024053|6|99.8265%|通过|
|rebuild_linear_winner_all_hi|C1046|68.9280%|14.4798%|4.760296|6|99.8265%|未通过|
|rebuild_linear_control_weak_fraction_lo|C1048|66.2080%|12.6088%|5.250918|6|99.8265%|通过|
|rebuild_linear_control_weak_fraction_hi|C1049|66.4142%|12.6154%|5.264528|6|99.8265%|通过|
|rebuild_linear_control_quiet_fraction_lo|C1050|66.0333%|12.4145%|5.319033|6|99.8265%|通过|
|rebuild_linear_control_quiet_fraction_hi|C1051|66.5941%|12.8312%|5.190026|6|99.8265%|通过|
|rebuild_linear_control_participation_threshold_lo|C1052|68.7049%|13.5779%|5.060035|6|99.8265%|通过|
|rebuild_linear_control_participation_threshold_hi|C1053|63.4624%|12.4972%|5.078146|6|99.8265%|通过|
|rebuild_linear_control_participation_width_lo|C1054|66.4478%|12.6148%|5.267450|6|99.8265%|通过|
|rebuild_linear_control_participation_width_hi|C1055|66.1183%|12.6073%|5.244447|6|99.8265%|通过|
|rebuild_linear_control_exit_width_lo|C1058|66.3370%|12.6266%|5.253750|6|99.8265%|通过|
|rebuild_linear_control_exit_width_hi|C1059|66.2599%|12.5992%|5.259052|6|99.8265%|通过|
|rebuild_linear_control_exit_pair_0|C1060|66.2409%|12.2423%|5.410831|6|99.8265%|通过|
|rebuild_linear_control_exit_pair_1|C1061|66.1878%|12.3961%|5.339414|6|99.8265%|通过|
|rebuild_linear_control_exit_pair_2|C1062|66.0969%|12.9912%|5.087826|6|99.8265%|通过|
|rebuild_linear_control_exit_pair_3|C1063|66.1038%|12.9364%|5.109911|6|99.8265%|通过|
|rebuild_linear_control_participation_joint_0|C1064|68.6899%|13.5279%|5.077648|6|99.8265%|通过|
|rebuild_linear_control_participation_joint_1|C1065|68.3154%|13.3913%|5.101462|6|99.8265%|通过|
|rebuild_linear_control_participation_joint_2|C1066|63.3131%|12.2661%|5.161613|6|99.8265%|通过|
|rebuild_linear_control_participation_joint_3|C1067|62.9956%|12.2650%|5.136229|6|99.8265%|通过|
|rebuild_linear_control_participation_joint_4|C1068|69.0671%|13.7399%|5.026732|6|99.8265%|通过|
|rebuild_linear_control_participation_joint_5|C1069|68.7295%|13.6302%|5.042438|6|99.8265%|通过|
|rebuild_linear_control_participation_joint_6|C1070|63.9693%|12.7263%|5.026556|6|99.8265%|通过|
|rebuild_linear_control_participation_joint_7|C1071|63.6589%|12.7303%|5.000580|6|99.8265%|通过|
|rebuild_linear_control_all_lo|C1072|68.4834%|13.1844%|5.194264|6|99.8265%|通过|
|rebuild_linear_control_all_hi|C1073|63.5704%|13.0563%|4.868951|6|99.8265%|未通过|

全部原始定义、账户引用与逐门结果见[结果](others/results.json)。

## 验证、样本及资源

完整完成123个配置；已记录成功策略回放117、买持回放1。逐段统计完整性为True，历史未知计算任务0项另列保留，成功回放计数仅取已记录值。实际状态与失败/未知任务保留于[执行记录](others/attempts.json)。累计运行记录38.86分钟。

公共TDR执行会话及检查点，12账户进程、每进程1原生线程；完整参数、输入、源码与资源身份见[运行清单](protocols/run_manifest.json)。

本轮另复用6份精确历史账户证据，保留原候选与原请求；未计入新增账户回放。

适用的控制账户完整经济parity均PASS。独立业务审计覆盖17账户、266,934条决定，全部PASS，见[业务审计](others/semantic_audit.json)。

2021预热，2022-01-03至2026-10-30已见开发历史；MU/SOXX、HFQ整数单位、10万美元、每侧0.1%费用、原限价买入/市价卖出及历史数据假设保持。结构对照所得认识仍属于开发证据，完整新原型稳健性与独立前瞻检验另行安排。

## 下一步

继续新10轮额度内第3轮阶段三开发性费用诊断：复用共同参数原型C0798/C0801/C0804、三族最新最高NAR点C0966/C1010/C1045和窄退出区间C0909的标准账户，仅新增7个每侧0.2%同参数压力账户与1个共享买持。按完整账本、周期权益归一化费用和实际调仓解释费用反应；保持原中心六门与NAR排序。结果用于决定是否有具体优化问题，全部候选正式阶段四验收及完整邻域80%仍待批准。

本轮计入2026-11-11新授权10轮额度的第2轮，完成后剩8轮。旧授权及剩余2轮独立保留。[预算](others/budget.json)。
