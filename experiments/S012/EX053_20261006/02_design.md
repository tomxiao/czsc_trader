# 前瞻设计

固定基线为真实C4603 momentum10/h6/.02，仅none风险门改vol或kurt并用known_only。none时unknown policy不生效；两风险明确恢复未知385日参与，只入场、不risk_exit。若root选择两止损邻接，精确继承真实C4704全参数，只改trailing_stop=.03/.10。基线只引用不重跑，固定选项与完整52来源绑定。
