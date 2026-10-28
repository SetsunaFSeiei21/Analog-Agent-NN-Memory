# Opamp2：17 参数五方法烟测

适用于提交 `ab6aad06c1e254a485b50d5b02d8b6267839a4a1` 后新增的 Opamp2。
接口为 `.subckt DUT VINP VINN VOUT VDD VSS`，器件使用 Sky130 1.8 V LVT 模型。

## 网表与参数

`Sample_Optimizer_Circuit/Opamp2/` 包含 `Opamp2.sp`、`Opamp2_params.sp` 和
局部 `.spiceinit`。W/L 数值按微米填写，网表显式设置 `scale=1u`，电流单位为 A。

独立参数共 17 个：`DESVAR_W1..W7`、`DESVAR_L1..L7`、`DESVAR_M1/M2`、`IBIAS_A`。
主网表包含 15 只 MOS 和参考电流源，按原始 opamp2 器件编号命名。

- 修正原 MNM4 的 W/L 对调错误：XNM4 与 XNM5 共享 W3/L3。
- XNM4 的倍乘为 `2*DESVAR_M2`，输入对、NMOS cascode 对及 PMOS 负载使用 M2。
- 新增 `IBIAS_SRC NET6 VSS DC {IBIAS_A}`，从 PMOS 参考二极管支路抽取参考电流。
- NMOS bulk 全部接 VSS；XPM3 和 XPM0 的 bulk 保留连接各自 source。
- 按更新的参考网表，XNM7 的 source 接差分输入对的公共尾节点 `NET1`（参考中的 `sn`），bulk 仍接 VSS。
- XNM7 属于 cascode 偏置生成支路，允许处于三极区，不纳入 SIGNAL 饱和约束。

XNM7 从接地改接尾节点属于拓扑变化。修改后须在新结果目录重新仿真和采样，
不能将新网表与旧拓扑的 DC OP、性能标签或已有采样数据库混用；先检查新的 DC 工作点。

`profiles.py` 注册了 REFERENCES、SIGNAL 和 NODE_SEEDS，7 个宽度组完整覆盖所有 MOS。
NODE_SEEDS 是初始化估计，不是已验证工作点。参数初值同样是示例，未经真实 SPICE 调优。
采样边界继续由 `src/sample_optimize/parameter_ranges.json` 决定，五种采样方法共用物理网格。

## 应用与提交

将补丁放到 harness 目录，在仓库根目录执行：

```bash
cd /share/home/202411094934/python_project/harness
git apply --check Opamp2_17params_ab6aad0.patch
git apply Opamp2_17params_ab6aad0.patch
cd analog-agent
bash scripts/smoke_test/submit_sampling.sh
```

补丁将烟测入口的 CIRCUIT_NAME 选择为 `Opamp2`，提交 32 点、8 workers 的五方法烟测。
集群分区、账户、环境及 PDK 条件仍使用脚本和条件文件中的现有设置。
脚本每次创建 `smoke_test_results/<运行标识>/Opamp2/`，终端会打印日志和数据路径。
新电路应使用新结果目录；检查真实 OP、输入对与 cascode 饱和余量、跟随误差及九项指标。

## 验证

```bash
cd analog-agent
PYTHONPATH=. python -m pytest tests/test_opamp2_sampling.py tests/test_opamp116_sampling.py tests/test_advanced_sampling.py tests/test_sampling_performance.py tests/test_gmid_body_bias.py -q
```

测试覆盖修正后的 W/L、倍乘表达式、参考电流方向、bulk 连接、标准端口、
17 个参数全部引用、7 个尺寸组及条件/非条件 gm/ID 候选生成。
算法回归使用解析 LUT，不代替真实 Sky130 BSIM 仿真。
