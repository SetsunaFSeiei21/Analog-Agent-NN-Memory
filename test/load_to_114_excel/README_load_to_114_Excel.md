# load_to_114：九指标与 DC/Excel 独立测试

本目录沿用仓库 `test/two_stage_opamp_otaf_excel` 的测量与导出格式，包含 16 只 Sky130 LVT MOS、21 个独立设计参数、9 项性能指标。测试格式基于远端 `main` 提交 `ab6aad06c1e254a485b50d5b02d8b6267839a4a1`。

该提交尚未包含 `load_to_114`。这里使用本次已经确定的 21 参数网表快照，保持其 D/G/S/B 连接、W/L/m 表达式、内部偏置电流与 Miller 补偿电容；没有调整为其他电路。

## 放置位置与运行

将整个 `load_to_114_excel` 目录放到 `harness/test/` 下。目录内包括：

- `load_to_114_all_metrics.cir`：完整测试台，内嵌 DUT、全部参数、DC/AC/瞬态分析。
- `load_to_114_export_excel.py`：DC raw 到 CSV、JSON、Excel 的导出程序。
- `.spiceinit`：与仓库其他测试相同的 `set ngbehavior=hs` 设置。
- `requirements-load_to_114-excel.txt`：Excel 导出依赖。
- 本说明文件。

在服务器上执行：

```bash
cd /share/home/202411094934/python_project/harness/test/load_to_114_excel
python3 -m pip install -r requirements-load_to_114-excel.txt
ngspice -b -o load_to_114.log load_to_114_all_metrics.cir
```

必须从此测试目录运行，让 ngspice 读取这里的 `.spiceinit` 并找到配套导出程序。首次运行前检查 `.cir` 顶部的 `.lib`；已填入此前使用的路径：

```spice
.lib "/share/home/202411094934/python_project/pdk/sky130A/libs.tech/ngspice/sky130.lib.spice" tt
```

模型库必须包含 `sky130_fd_pr__nfet_01v8_lvt` 和 `sky130_fd_pr__pfet_01v8_lvt`。

## 修改和复现设计点

直接编辑 `.cir` 的 `DESIGN PARAMETERS` 区域再运行。它是独立快照，不读取 `Sample_Optimizer_Circuit` 下的 `.sp` 或 `_params.sp`，也不访问采样数据库。

21 个独立参数为 `DESVAR_W1..W8`、`DESVAR_L1..L8`、`DESVAR_M1..M3`、`CCOMP_F`、`IBIAS_A`。W/L 使用裸数值，单位为 μm；电流为 A，电容为 F，M 为正整数。

当前默认值与此前生成的参数文件一致：参考电流 1 μA，补偿电容 1 pF，M1=1、M2=4、M3=1。它们只是初始尺寸，尚未用真实 PDK 验证为正常偏置或稳定的设计点。

若要复现某一行 `dc_not_converged`，必须从该行对应的设计参数记录复制全部 21 个值到这里，包括 IBIAS_A 与 CCOMP_F。仅复制 OP 宽表里部分 MOS 的 W/L/m 不足以完整复现；默认参数测试也不等于复现该失败点。

端口沿用原始电路映射：`in1 -> VINN`，`in2 -> VINP`。原来的 `ibias` 为内部节点 VBIAS，电流源方向为 VDD 到 VBIAS。所有 NMOS bulk 接 VSS，所有 PMOS bulk 接 VDD。

保留的主要约束为：输入差分对、NMOS cascode 对、一级 PMOS 镜像对分别共享各自的 W/L/m；尾管 m=`1+2*DESVAR_M1`；二级 PMOS/NMOS m=`DESVAR_M1*DESVAR_M2`；cascode 偏置管 m=`DESVAR_M3`。

二级 NMOS `XNM8` 仍使用 W3/L3、栅极接 VBIAS，因此它相对于参考 NMOS 的电流比例还依赖 `(W3/L3)/(W1/L1)`；测试没有强制这两组几何参数相等。

## 测试条件与结果

默认条件为 VDD=1.8 V、VSS=0 V、VCM=0.72 V、外部负载 1 pF、tt、27 °C。供电、输入共模、负载、AC 扫描与瞬态设置位于同一 `.cir` 的 `TEST CONDITIONS` 区域。

`CCOMP_F` 是 DUT 内部的补偿电容，`LOAD_C` 是测试台外部的负载电容，二者独立。

运行后生成：

- `load_to_114.log`：原始 ngspice 日志。
- `load_to_114_metrics.txt`：一行 CSV 表头和一行九指标数值。
- `load_to_114_dc_operating_point.raw`：AC/瞬态分析前保存的 ASCII DC 工作点。
- `load_to_114_dc_operating_point.csv`：一个设计点一行的全部 MOS 工作点宽表。
- `load_to_114_results.xlsx`：四张表，分别为 `DC_Operating_Point`、`MOS_Capacitances`、`Metrics`、`Setup`。

九项指标为 DC gain、UGF、PM、CMRR、PSRR+、PSRR-、上升 SR、下降 SR、静态功耗。算法沿用仓库现有独立测试：增益在 1 Hz 测量；UGF 与 PM 使用同一次 AC 扫描的首次下降单位增益交点；CMRR 使用差模/共模重建；PSRR 使用跟随器电源抑制定义；SR 使用输出跃迁 10%–90% 的平均斜率。缺失交点或有效跃迁保留 `nan`，有效负 dB、负 PM 不丢弃。

DC 工作点与静态功耗均来自单个安静的单位增益跟随器实例 `XDUT_CM`。同一文件中其他实例分别用于 AC、PSRR 和瞬态测量，不能将全部实例的供电电流相加作为单个运放的功耗。

DC 导出保留四端连接与电压、W/L/m、Id、gm、gds、gmbs、Vth、Vdsat、电容矩阵与电荷。模型电流、跨导、电容已含 m，不再额外乘 m；PMOS 端电压和 BSIM 电容矩阵保留原始符号。Excel 中派生诊断列用公式，打开 Excel 或 LibreOffice 后重算；CSV/JSON 已含计算值。

## 排查 OP 失败

首先看日志中的第一条实际错误：

```bash
rg -n -i 'error|fatal|singular|converg|timestep|unknown|no such' load_to_114.log
```

只有部分性能指标为 `nan`，并不必然表示 DC 未收敛；同时查看 raw 文件、跟随误差、节点电压和原始日志。结果文件存在或 ngspice 退出码为 0，也不能单独证明所有指标有效。

如果报告 `Missing required DC vector`，需检查模型是否载入、OP 是否求解成功、尺寸是否有可用模型，以及 PDK 内部器件名称是否与查询一致。

查询层级沿用仓库其他独立测试：`@m.xdut_cm.<器件名>.m<完整模型名>[字段]`。如果安装的 PDK 将原始 MOS 命名为 `m0`，而不是 `msky130_fd_pr__...`，须将此 `.cir` 中对应查询的末级实例名改为实际名称；这属于数据读取层级差异，不能直接当作电路不收敛。

本测试沿用仓库现有的原始字段覆盖，要求完整 DC 向量；缺失时导出程序报错，不生成伪造的正常工作点。不要混用不同次运行的 raw、metrics 和 netlist。每次运行会更新本目录的结果；需要对比多个设计点时，请分别保存整套输入与输出。

Python 依赖修复后可单独重新导出：

```bash
python3 load_to_114_export_excel.py --netlist load_to_114_all_metrics.cir
```

若只需要 CSV/JSON，不安装 openpyxl 也可运行：

```bash
python3 load_to_114_export_excel.py --netlist load_to_114_all_metrics.cir --json-only
```

## 已完成的检查

生成时检查了 16 只 MOS 的连接及尺寸表达式、21 个参数、31 个输入别名、496 个模型字段查询，并复用仓库测试流程验证合成 raw 到 CSV/JSON/XLSX 的导出。九指标测量代码与现有独立测试一致。

这些是结构与导出检查，不是实际电气仿真结果。当前环境没有 ngspice 与 Sky130 PDK，因此真实 DC/AC/瞬态验证需要在服务器上执行上面的命令。
