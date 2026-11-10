# EX044 参与连续带完整对照

24 配置，18 组成对比较，8 个阈值三档家族；新增账户 0。

|家族|参与半宽|达标点/3|NAR范围|Calmar范围|MDD范围|
|---|---:|---:|---|---|---|
|hard/hard|0.1|2|69.22%–71.06%|4.4882–5.1804|13.72%–15.42%|
|hard/linear|0.05|1|68.08%–70.37%|4.8845–5.1301|13.72%–14.36%|
|hard/linear|0.1|1|67.33%–70.59%|4.9030–5.0203|13.73%–14.06%|
|hard/linear|0.2|1|66.18%–70.31%|4.7613–5.0023|13.90%–14.06%|
|ramp/hard|0.1|0|66.32%–68.21%|4.2634–4.5993|14.83%–15.56%|
|ramp/linear|0.05|0|65.29%–67.51%|4.4003–4.5532|14.83%–15.17%|
|ramp/linear|0.1|0|64.53%–67.48%|4.3464–4.4465|14.85%–15.18%|
|ramp/linear|0.2|0|63.21%–67.08%|4.2121–4.4189|15.01%–15.18%|

|连续配置|匹配hard|ΔNAR百分点|ΔMDD百分点|ΔCalmar|改退出数|目标变化决策|
|---|---|---:|---:|---:|---:|---:|
|hard_linear05_center|hard_hard10_center|-0.6853|0.0008|-0.05027|0|965|
|hard_linear05_low|hard_hard10_low|0.9205|-1.0628|0.39630|0|750|
|hard_linear05_high|hard_hard10_high|-2.5733|-0.0025|-0.18663|0|829|
|hard_linear10_center|hard_hard10_center|-1.8743|0.1613|-0.19526|0|1451|
|hard_linear10_low|hard_hard10_low|1.3718|-1.3613|0.53207|0|1643|
|hard_linear10_high|hard_hard10_high|-3.3292|0.0090|-0.24583|0|1617|
|hard_linear20_center|hard_hard10_center|-2.8676|0.2576|-0.30070|0|3051|
|hard_linear20_low|hard_hard10_low|1.0882|-1.3674|0.51406|0|3115|
|hard_linear20_high|hard_hard10_high|-4.4775|0.1766|-0.38755|0|2795|
|ramp_linear05_center|ramp_hard10_center|-0.6943|-0.0024|-0.04607|0|990|
|ramp_linear05_low|ramp_hard10_low|0.8758|-0.3914|0.16778|0|756|
|ramp_linear05_high|ramp_hard10_high|-2.5798|0.0059|-0.17569|0|850|
|ramp_linear10_center|ramp_hard10_center|-1.8903|0.1643|-0.17647|0|1478|
|ramp_linear10_low|ramp_hard10_low|1.1590|-0.3799|0.18309|0|1670|
|ramp_linear10_high|ramp_hard10_high|-3.3358|0.0159|-0.22958|0|1578|
|ramp_linear20_center|ramp_hard10_center|-3.0682|0.2535|-0.28072|0|3014|
|ramp_linear20_low|ramp_hard10_low|0.7521|-0.3771|0.15546|0|3206|
|ramp_linear20_high|ramp_hard10_high|-4.6551|0.1762|-0.36391|0|2758|

共同入退场以真实成交时点匹配；实际仓位以持仓数量×估值价格/权益衡量。相同入退场且目标持有状态相同的差异，主要联系仓位路径解释。
JSON 保留全部年度差、正负贡献日、共同周期、独有周期、已见 2025 年 11 月反例及来源。三档平坦度与原六门达标分别报告。
daily_close/linear 当前保留为后续待检方向，本轮直接证据覆盖 hard 与 ramp05。

分析源码 SHA256：`9b7b633dabe52c188726fdd5b54a943a73fa3f977c4cc74e946459f4df55267f`

冻结 EX043 辅助源码 SHA256：`e76c0e487c9e46d4f6c8f3f698ff41411eb46dcc271bd7fe09b6fde6c6c68e0a`

完整数据与引用：`others/participation_comparison.json`。
