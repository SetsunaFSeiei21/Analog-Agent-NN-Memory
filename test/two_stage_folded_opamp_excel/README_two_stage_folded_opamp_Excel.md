# two_stage_folded_opamp：九指标与 DC/Excel 测试

按 `test/opamp0_excel` 的测量和导出方式独立构建，包含 **22 只 MOS、23 个设计参数、9 项指标**。
源文件为 `analog-agent/Sample_Optimizer_Circuit/two_stage_folded_opamp/two_stage_folded_opamp.sp` 和 `two_stage_folded_opamp_params.sp`，对应提交 `6a1363ef6be90905c52dde54e39f59df258c1ee5`。

测试副本统一使用 `sky130_fd_pr__nfet_01v8_lvt` / `sky130_fd_pr__pfet_01v8_lvt`；保留源电路的 D/G/S/B、W/L、m 表达式、偏置电流和补偿网络。
默认供电 1.8 V、VCM 0.72 V、负载 1 pF、tt、27 °C。DC 和 AC 采用该 VCM；压摆测试沿用 Opamp0 的 0.7→1.1 V 脉冲。

`RNULL_OHM`（Ω）和 `CCOMP_F`（F）是 DUT 内部的补偿元件；`LOAD_C` 是测试台外部负载电容，三者独立。它们的数值都记录在 `Setup` 中。

## 运行

在仓库根目录执行：

```bash
cd test/two_stage_folded_opamp_excel
python3 -m pip install -r requirements-two_stage_folded_opamp-excel.txt
ngspice -b two_stage_folded_opamp_all_metrics.cir
```

首次运行前，将 `.cir` 顶部的 `.lib` 路径改为本机的 `sky130.lib.spice`。
目录中的 `.spiceinit` 设置 `ngbehavior=hs`；从本目录启动 ngspice，让它读取该设置。
需要包含上述 LVT 模型的 Sky130 PDK。默认参数沿用源文件，尚未在真实 PDK 上验证其偏置、稳定性或性能。

## 修改参数

直接编辑 `two_stage_folded_opamp_all_metrics.cir` 中的 `DESIGN PARAMETERS` 后重新运行。
测试条件在同一文件的 `TEST CONDITIONS` 中。W/L 的单位为 μm（`.option scale=1u`），电流为 A，m 无量纲。
这是包含 DUT 与参数的独立快照，不读取原目录的 `_params.sp`。修改源文件或 Excel 不会自动修改此测试。
Excel 是本次仿真的报告；需要更改工作点时，修改 `.cir` 并重跑。修改参数后不要用旧 raw 文件生成“新”结果。

## 结果

| 文件 | 内容 |
|---|---|
| `two_stage_folded_opamp_metrics.txt` | 一行 CSV 表头加一行九指标数值 |
| `two_stage_folded_opamp_dc_operating_point.raw` | 在 AC/transient 之前保存的单个 DC 工作点，ASCII，全精度 |
| `two_stage_folded_opamp_dc_operating_point.csv` | 一个设计点一行、全部 MOS 电气量展开的宽表 |
| `two_stage_folded_opamp_results.xlsx` | 四张工作表：工作点、电容、电气指标、输入与条件 |

Excel 中的四张表：

- `DC_Operating_Point`：每只 MOS 的实际模型、四端连接、W/L/m、节点电压、Id、gm/gds/gmbs、Vth/Vdsat 和诊断量。
- `MOS_Capacitances`：BSIM 原生电容矩阵、结电容及电荷，保留交叉项符号。
- `Metrics`：DC gain、UGF、PM、CMRR、PSRR±、上升/下降 SR、静态功耗。
- `Setup`：从 raw 读回的设计参数与主要测试条件，以及实际 VINP/VINN/VOUT、跟随误差和模型库位置。

DC 数据来自 `XDUT_CM` 静态单位增益跟随器；功耗也只计算这一个实例。
W/L 从模型内部米值换算为 μm。模型电流、跨导和电容已经包含 m，不再重复乘 m。
PMOS 的端电压差保留原始符号。`Vov_est_V` 和 `Saturation_margin_V` 仅用于诊断，不作为无条件的区域分类。
Excel 派生列使用公式，打开 Excel/LibreOffice 后重算；CSV/可选 JSON 已包含算好的数值。

增益在具有 DC 反馈、AC 输入注入的实例上测量；UGF/PM 取同一次 AC 扫描的首次下降单位增益交点。
CMRR 按 Opamp0 方式重建差模/共模增益比；PSRR 使用同样的闭环跟随器定义。
SR 取已稳定输出幅度的 10%–90% 平均斜率。缺失交点或有效跃迁输出 `nan`，不会填成 0。
DC 导出成功并不代表该设计点性能合格；同时检查跟随误差、指标缺失及稳定性。

若自动导出失败，修好 Python 依赖后可单独重试，并检查此命令的退出码：

```bash
python3 two_stage_folded_opamp_export_excel.py --netlist two_stage_folded_opamp_all_metrics.cir
```

不安装 openpyxl 也可以验证 raw 并导出 CSV/JSON：

```bash
python3 two_stage_folded_opamp_export_excel.py --netlist two_stage_folded_opamp_all_metrics.cir --json-only
```

不要将不同次仿真的 raw、metrics 和 netlist 混用。
若出现 `Missing required DC vector`，先查看 ngspice 日志中第一条错误：是否模型未加载、尺寸无有效模型、OP 未收敛，或 PDK 内部 MOS 名称与导出查询不匹配。
当前查询沿用 Opamp0 的 `@m.xdut_cm.<实例>.m<模型名>[字段]` 层级；换用内部实例命名不同的 PDK 封装时，需要相应更新查询。

## 器件映射

| 器件 | 类型 | D | G | S | B | W 参数 | L 参数 | m |
|---|---|---|---|---|---|---|---|---|
| XMP_BIAS_REF | PMOS | VBP1 | VBP1 | VDD | VDD | {WPBIAS} | {LPBIAS} | 1 |
| XMP_VB3 | PMOS | VB3 | VBP1 | VDD | VDD | {WPBIAS} | {LPBIAS} | 1 |
| XMP_VB2 | PMOS | VB2 | VBP1 | VDD | VDD | {WPBIAS} | {LPBIAS} | 1 |
| XMP_PCAS_DIODE | PMOS | VB1 | VB1 | N_PBIAS | VDD | {WPCAS_BIAS} | {LPCAS_BIAS} | 1 |
| XMP_PCAS_SOURCE | PMOS | N_PBIAS | VB1 | VDD | VDD | {WPCAS_BIAS} | {LPCAS_BIAS} | 1 |
| XMN_BIAS_REF | NMOS | VB3 | VB3 | VSS | VSS | {WNBIAS} | {LNBIAS} | 1 |
| XMN_VB1 | NMOS | VB1 | VB3 | VSS | VSS | {WNBIAS} | {LNBIAS} | 1 |
| XMN_NCAS_DIODE | NMOS | VB2 | VB2 | N_NBIAS | VSS | {WNCAS_BIAS} | {LNCAS_BIAS} | 1 |
| XMN_NCAS_SOURCE | NMOS | N_NBIAS | VB2 | VSS | VSS | {WNCAS_BIAS} | {LNCAS_BIAS} | 1 |
| XMP_INPUT_TAIL | PMOS | N_INPUT_TAIL | VBP1 | VDD | VDD | {WPBIAS} | {LPBIAS} | {2*M1_FACTOR} |
| XMP_INN | PMOS | N_FOLD_N | VINN | N_INPUT_TAIL | VDD | {WIN} | {LIN} | {M1_FACTOR} |
| XMP_INP | PMOS | N_FOLD_P | VINP | N_INPUT_TAIL | VDD | {WIN} | {LIN} | {M1_FACTOR} |
| XMP_FOLD_P | PMOS | N_PCAS_P | N_PCAS_GATE | VDD | VDD | {WPFOLD} | {LPFOLD} | {M1_FACTOR} |
| XMP_FOLD_N | PMOS | N_PCAS_N | N_PCAS_GATE | VDD | VDD | {WPFOLD} | {LPFOLD} | {M1_FACTOR} |
| XMP_CAS_P | PMOS | OTA_OUT | VB1 | N_PCAS_P | VDD | {WPCAS} | {LPCAS} | {M1_FACTOR} |
| XMP_CAS_N | PMOS | N_PCAS_GATE | VB1 | N_PCAS_N | VDD | {WPCAS} | {LPCAS} | {M1_FACTOR} |
| XMN_SINK_P | NMOS | N_FOLD_P | VB3 | VSS | VSS | {WNBIAS} | {LNBIAS} | {2*M1_FACTOR} |
| XMN_SINK_N | NMOS | N_FOLD_N | VB3 | VSS | VSS | {WNBIAS} | {LNBIAS} | {2*M1_FACTOR} |
| XMN_CAS_P | NMOS | OTA_OUT | VB2 | N_FOLD_P | VSS | {WNCAS} | {LNCAS} | {M1_FACTOR} |
| XMN_CAS_N | NMOS | N_PCAS_GATE | VB2 | N_FOLD_N | VSS | {WNCAS} | {LNCAS} | {M1_FACTOR} |
| XMP_STAGE2 | PMOS | VOUT | OTA_OUT | VDD | VDD | {W2P} | {L2P} | {M1_FACTOR*M2_FACTOR} |
| XMN_STAGE2 | NMOS | VOUT | VB3 | VSS | VSS | {WNBIAS} | {LNBIAS} | {M1_FACTOR*M2_FACTOR} |

## 验证范围

仓库中的 `test/test_excel_testbenches.py` 检查源电路映射、参数/查询覆盖，以及合成 DC raw 到 CSV/JSON/XLSX 的导出。
它不替代真实 ngspice + Sky130 PDK 电气烟测，也不生成冒充仿真结果的默认工作点文件。
