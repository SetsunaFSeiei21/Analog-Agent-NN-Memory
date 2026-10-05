# ACDC 对照测试平台

这套修改按所提供的 Opamp24 ACDC 平台连接测试电路，并适配 repo 的
`.subckt DUT VINP VINN VOUT VDD VSS` 接口。六份模板继续输出现有九个指标，
`Simulator`、CSV 列名及神经网络数据接口无需修改。器件与测量语句均写在一行。

## 安装

补丁基于 `main` 的 `62b075fae13b05d56dee8e380c10600803643951`。
在仓库根目录运行：

```bash
git apply --check /path/to/acdc_reference_testbenches.patch
git apply /path/to/acdc_reference_testbenches.patch
```

如果本地已经应用之前的 AC/CMRR/slew 补丁，或修改过这些模板，补丁可能无法直接应用。
可以改用完整文件压缩包：查看并覆盖其中六个 `tb_*.cir`，添加 `configs/testbench/acdc_reference/`、
本文档及测试文件。新补丁已包含之前的直流反馈和 slew 时间搜索修正。

## 条件与试跑

现有 `default_simulate_condition/` JSON 保留原值。新增的
`configs/testbench/acdc_reference/` 包含六份可直接传给 Simulator 的条件文件：

| 条件 | ACDC 对照配置 |
|---|---|
| VDD / VSS | 1.8 V / 0 V |
| VCM | 0.72 V，即 0.4 × 1.8 V |
| 输出电容 | 1 pF |
| AC 扫频 | 每十倍频程 10 点，0.1 Hz 到 1 GHz |
| Gain / CMRR / PSRR 取值频率 | 0.1 Hz |
| AC、稳定性、CMRR、PSRR、slew 温度 | 显式设为 27 °C |
| 静态功耗温度 | 25 °C，匹配样例的 `FIND ... AT=25` |
| slew 输入 | 0.52 V 到 0.92 V 的脉冲，中心为 0.72 V |

先检查这六份 JSON 中的 `PDK_PATH`。现有 `.lib PDK_PATH CORNER` 入口继续使用，
不需要把示例的四个 PDK `.include` 路径复制进模板。若改变电源电压，须自行调整
`VCM` 和 slew 的 `VIN_LOW` / `VIN_HIGH`；这里的 JSON 数值不会自动按比例更新。

在已有 Python 或命令行调用中指定：

```text
simulation_condition_path=Path("configs/testbench/acdc_reference")
--simulation_condition_path configs/testbench/acdc_reference
```

也可以在 `analog-agent/` 下使用现有运行脚本。这个脚本先复制源电路，再交给 Controller：

```bash
ANALOG_SIMULATION_CONDITION_PATH="$PWD/configs/testbench/acdc_reference" \
ANALOG_KEEP_WORKSPACE=1 ANALOG_CONTINUE_ON_ERROR=1 \
bash scripts/run/run_sampling.sh \
  Sample_Optimizer_Circuit/Opamp0 Opamp0 single_ended_opamp \
  sampling_database_acdc_trial 30 1 \
  DC_GAIN UGF PM CMRR P_PSRR N_PSRR P_SR N_SR POWER
```

`sampling_database_acdc_trial` 应使用新的历史根目录。已有目录会触发历史复用，
相同设计点不会重新仿真，而且源电路可能被历史目录中的副本替代。
不同测试条件的结果应分别保存，避免与旧条件数据混在一起。
试跑 Opamp0 前，源文件应采用你已修正的 `XNM2/XNM3 m={2*DESVAR_M1}` 网表。
这个补丁只更新测试平台，没有把该网表修正或候选参数范围合入源电路。

上述命令重新采样 30 个点。若需要复测同一批设计参数，直接用 `Simulator.simulate_batch`
传入原来的参数数组，避免将“换了测试平台”和“换了设计点”混为一次对比。
`keep_workspace` 下的 `ac.log`、`stability.log` 和 `power.log` 都有 `vout_dc`、
`follower_error_v`，可用于检查直流输出是否跟随指定输入。

## 六份模板的对应关系

| 模板 | 与所给平台的关系 |
|---|---|
| `tb_ac.cir` | 非反相端固定 VCM；反相端经 1T F 电容接 1 V AC 源，输出经 1T H 电感反馈到反相端；对应 x1 |
| `tb_stability.cir` | 使用同一个反馈和激励电路，计算单位反馈环路的相位裕度 |
| `tb_cmrr.cir` | 两个 1 V AC 源分别串在 VCM 参考和输出上，对应 vcmac1/vcmac2 与 x2；增加一个反相激励 DUT 以恢复 ADM/ACM |
| `tb_psrr.cir` | 两个电压跟随器分别注入正、负供电纹波，对应 x3/x4；负电源测试的负载电容接全局 0 |
| `tb_power.cir` | 电压跟随器单点 OP，对应 x5 在 25 °C 的功耗；同时计入正、负电源贡献 |
| `tb_slew.cir` | 所给平台没有执行瞬态 slew 测量，保留 repo 的脉冲方法，并修正 TRIG/TARG 的搜索起点及非正时间处理 |

偏置电流依然是 DUT 内部的设计参数。原平台外部的 `Ib` 端口不添加到标准五引脚接口。
TC 和温度扫描输出偏差不属于现有九指标协议，因此没有新增对应 CSV 列。
功耗在 25 °C 直接执行 OP，其余测试各自在指定温度运行，避免依赖温度扫描后的状态。

## 指标换算

原例部分变量是输出传递增益，不能直接当作 repo 中的抑制比：

| 原例 | repo 输出与处理 |
|---|---|
| `dcgain_` | 反相激励的增益幅度，以有正负号的 dB 保存；不执行 `abs(dcgain_)` |
| `gain_bandwidth_product_` | `UGF_Hz`，保留 Hz，不乘 `1e-4` |
| `phase_margin` | 使用 `180 + phase(-VOUT/VINN)` 的连续相位，在首个下降的单位增益交点取值 |
| `cmrrdc` | 原值为闭环共模输出传递 dB；保存在日志的 `reference_cm_response_db`，正式 CMRR 由 ADM/ACM 计算 |
| `DCPSRp` / `DCPSRn` | 原值为供电到输出的传递 dB；原值另存日志，正式 PSRR 输出对应的抑制比 dB |
| `Power` | 两路电源总静态功耗，单位 µW |

CMRR 的换算不要求“开环增益很大”。在线性小信号模型
`VOUT = gp·VINP + gn·VINN` 中，反相激励测得 `G=-gn`，原平台的闭环共模激励测得
`H=(gp+gn)/(1-gn)`，所以：

```text
ACM = H · (1 + G)
ADM = G + ACM / 2
CMRR = |ADM / ACM|
```

这保留了 repo 的 CMRR 定义。直接取 `-db(H)` 是高增益下的近似值，
日志也提供 `closed_cm_rejection_ref_db` 用于与原平台对照。

## 验证记录

运行环境：ngspice 42，官方 SkyWater Sky130 NFET/PFET TT 模型。
三项解析模型测试和现有 18 项 Phase 1 集成测试均通过。
另外对四个 repo 电路的默认参数分别运行原条件和 ACDC 条件，对你提供的 16 组修正后
Opamp0 参数运行 ACDC 条件，并对前述 Opamp0 验证点运行两套条件；共完成 156 次
真实 Sky130 ngspice 测试，没有非可恢复错误。
部分异常设计点的 UGF/PM 无交点，仍按现有逻辑记录为缺失值。

下表是 ACDC 条件下的部分结果；功耗按 25 °C，其余按 27 °C：

| 电路与参数 | 直流输出 V | 增益 dB | UGF Hz | PM ° |
|---|---:|---:|---:|---:|
| 5t_ota，repo 默认参数 | 0.721556 | 36.59468 | 28509380 | 83.49023 |
| two_stage_opamp_otaf，repo 默认参数 | 0.720417 | 72.90644 | 44230160 | 54.68000 |
| two_stage_folded_opamp，repo 默认参数 | 0.720189 | 83.76549 | 12599810 | 68.50260 |
| Opamp0，修正网表与前述验证参数 | 0.718982 | 52.09371 | 423871.2 | 87.62606 |
| Opamp0，修正网表与你提供的第 1 组参数 | 0.102161 | -12.00760 | 缺失 | 缺失 |

Opamp0 验证参数为：W1/W2/W4/W5/W6/W7=10，L1/L2/L5/L6=0.5，
W3=1，L3=5，L4/L7=0.15，M1=1，IBIAS_A=2e-7；W/L 单位 µm。

测试平台更换不会自动使异常参数组合成为有效运放。模板会记录直流跟随误差，
但没有自动剔除偏置异常样本，也没有仅凭很小的输出摆幅拒绝 slew 数值。
因此，得到完整九个数值与工作点合理是两项不同检查。

重跑验证：

```bash
cd analog-agent
PYTHONPATH=. python -m unittest discover -s tests -p 'test_phase1.py' -v
ANALOG_TEST_NGSPICE=ngspice PYTHONPATH=. python -m unittest discover -s tests -p 'test_ngspice_testbenches.py' -v
```

解析模型测试不需要安装 Sky130 PDK；它使用已知增益、共模增益、供电传递、
单极点、供电电流与瞬态响应的线性模型，检查实际模板渲染、SPICE 执行及结果解析。
未找到 ngspice 时，这三项测试会显式跳过。
