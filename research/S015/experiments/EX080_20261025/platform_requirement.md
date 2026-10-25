# 阶段四阻塞：连续局部端点的浮点尾差

状态：用户已授权并完成最小DEV修复，提交`9f876c54`。84项聚焦测试及Ruff通过；29个中心完整构造177邻点，16份历史发布计划只读认证通过，已有C7600计划保持一致。用户随后批准切回RSCH完成阶段四。以下保留问题发生时的事实及方案；原缺陷复现结果不改写。

## 可复现事实

公共`ParameterAxis`以`RealDomain(0.0, 0.05)`、中心`1.001 / 0.999 - 1`及`BoundedLocalStep(RelativeChangeLimit(0.05))`构造失败，报`continuous local step misses domain; declare a smaller limit`。不是实际域过窄：精确上下端点都在合法域内。平台先以十进制字符串转有理数精确计算端点，再转float；实际float再转十进制有理数时，微小舍入可能使距中心的变化量超过原最大变化。

29个中心中18个的空间轴至少一个方向受影响，10个两个方向同时误判。完整[公开API复现](src/float_boundary_reproduction.py)及[结果](others/float_boundary_reproduction.json)已保存。一个零门槛中心的3点计划已发布，其他计划未完成；没有运行参数账户。

## 最小实施方案

修改范围仅为[参数邻域生成器](../../../../packages/strategy_evaluator/src/strategy_evaluator/parameter_neighborhood.py)的连续`RealDomain`且`quantum is None`端点转换。保留现有精确有理数最大变化、域判断和所有公开类型/API；当最近float因表示误差越过原变化上限时，取朝中心方向相邻的可表示float，再按原精确条件验证合法、不同于中心且不超限。

拟增核心逻辑（须在DEV获批后实施和测试）：

```python
value = float(exact)
if domain.quantum is None and abs(_number(value) - _number(axis.center)) > maximum:
    value = math.nextafter(value, float(axis.center))
```

此逻辑限定于连续实数分支，不作用于整数、离散实数、有序或类别轴；原本真实越域的方向仍在转换前拒绝。不能通过改变5%标准、放宽公差、修改中心参数或事后删点绕过错误。

## 契约与验证

- 公开签名、载荷、协议及目标不变；实际可表示端点仍按既有强类型事实记录。
- 聚焦覆盖双边费用门槛、若干实际连续门槛、单方向舍入、零点绝对尺度、开闭域、不可表示的不同值、离散真实超限和类别保持。
- 验证序列化往返、TDR参数计划绑定、现有历史计划只读认证；不能改写旧计划或历史资格。
- 修复后重新完成29份计划，预期177个邻点关系，继续原阶段四，不扩展策略搜索。

原阻塞涉及项目AGENTS的跨角色授权边界。用户曾选择只完成不受影响项，随后明确要求“先修复平台缺陷”，现已按上述最小范围完成，并批准恢复完整阶段四；未扩大平台修改范围。
