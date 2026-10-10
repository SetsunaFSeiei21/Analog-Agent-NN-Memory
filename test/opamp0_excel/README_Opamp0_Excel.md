# Opamp0 九项性能指标及晶体管 DC 工作点导出

## 1. 使用

将 `Opamp0_all_metrics.cir`、`opamp0_export_excel.py` 和依赖清单放在同一个目录，并在这个目录运行。

```bash
python3 -m pip install -r requirements-opamp0-excel.txt
ngspice -b Opamp0_all_metrics.cir
```

运行前修改网表中的 PDK 路径，以及设计参数和测试条件。网表已经采用最新的 25 参数版本：W1–W9、L1–L9、M1–M6 和 IBIAS_A。示例 W/L 不是已验证的 golden point。

网表执行完 DC、AC、瞬态测试后，会自动调用 Python 导出器生成 Excel。ngspice 本身仍只依赖 PDK；如果 Python 或 openpyxl 未就绪，DC 原始数据和性能 TXT 仍会保留，并在日志中显示 Excel 导出失败原因。

如果已有仿真结果，只重新生成 Excel，无需重新仿真：

```bash
python3 opamp0_export_excel.py --netlist Opamp0_all_metrics.cir
```

## 2. 输出文件

| 文件 | 内容 |
|---|---|
| `opamp0_results.xlsx` | 晶体管工作点、电容及电荷、九项指标、设计参数及测试条件 |
| `opamp0_dc_operating_point.csv` | 宽表：一个设计点一行，列名为 `器件名__字段名`；UTF-8 BOM 编码便于 Excel 打开 |
| `opamp0_dc_operating_point.raw` | ngspice ASCII 原始 DC 解，保留约 15 位有效数字 |
| `opamp0_metrics.txt` | 保留之前的精确九列顺序，一个表头和一个结果行 |

Excel 有四张表：

1. `DC_Operating_Point`：每个晶体管一行，共 17 行。
2. `MOS_Capacitances`：每个晶体管一行，保留 16 个本征电容矩阵项、两个结电容和四个电荷。
3. `Metrics`：九项性能指标及单位。
4. `Setup`：本次解析后的设计参数、测试条件、实际输入输出电压及关键定义。

缺失性能指标保存为文字 `nan`，有效负指标保留，不替换成零。

## 3. DC 工作点基准

仅导出 `XDUT_CM` 的工作点。这个实例在 DC 下是静态电压跟随器，也是静态功耗的测量实例。导出使用原有的一次 `op` 求解，没有增加另一轮 DC 仿真，也没有保存瞬态过程中每个时间点的晶体管状态。

实际 `VINP`、`VINN`、`VOUT` 和跟随误差都会保存。电路工作异常时，`VINN`/`VOUT` 可能不等于设定的 VCM；导出器不会把这几个电压强行替换成 VCM。

脉冲测试的初始电平为 `SR_LOW`，它的瞬态初始状态不能与这里的静态工作点混为一谈。

## 4. 字段和单位

工作点表包含器件名、型号、D/G/S/B 节点、W/L、M、四个端点电压，以及：

- `VGS_V`、`VDS_V`、`VBS_V`：由实际端电压之差计算；保留符号。
- `Id_model_A`、`gm_S`、`gds_S`、`gmbs_S`：ngspice BSIM 原始读数。
- `Vth_model_V`、`Vdsat_model_V`：模型输出的阈值和饱和电压，保留模型符号。
- `gm_over_Id_per_V`：`abs(gm)/abs(Id)`。
- `gm_over_gds`：`abs(gm)/abs(gds)`。
- `ro_Ohm`：`1/abs(gds)`。
- `VDS_oriented_V`：NMOS 为 VDS，PMOS 为 VSD。
- `Vov_est_V`：按器件类型定向的栅源电压减去阈值幅值。
- `Saturation_margin_V`：`VDS_oriented_V - abs(Vdsat_model_V)`。

派生字段在 Excel 中为可审查的公式，Excel 打开后重新计算；宽表 CSV 中为已计算的数值。

饱和余量与过驱动电压是诊断量。正饱和余量不能单独证明晶体管已有效导通；负过驱动也不能直接否定弱反型设计。需要结合电流、gm/Id 和整个电路的工作状态判断。

原始器件电流、跨导、电导、电容和电荷已经包含 M 倍数，不再次乘 M。MOS 模型的 `id` 保留原生读数，不擅自改成另一个电流符号约定。

BSIM 的 `cgs`、`cgd` 等是电荷导数矩阵的条目，交叉项可能为负。Excel 保留原始值，不能把每个矩阵项都当作正值集总电容。

W/L 从模型的米单位转换成 µm。测试文件仍使用 Sky130 `scale=1u` 约定。

## 5. 数值与运行检查

导出器检查原始文件确实是单点、实数的 DC Operating Point，并检查全部 17 只晶体管的字段。缺失字段或截断文件会显式失败，不补零。Excel 采用临时文件写入完成后再替换目标文件。

本次已经用真实 Sky130 TT 模型验证：

1. 默认设计导出 17 只 MOS、25 个设计参数和全部九项性能指标。
2. 与原示例的九项性能数值一致。
3. 独立修改 W9/L9、M1–M6 后，器件绑定和导出值正确。
4. `m=2` 时 ngspice 的电流、gm、电容读数为同偏置 `m=1` 器件的两倍。
5. 工作点文件缺失字段或含多个 DC 点时，导出器拒绝生成误导性结果。

`opamp0_results_example.xlsx` 是上述默认示例的工作点展示。这组尺寸存在跟随误差和偏置问题，它展示的是实际仿真数据，不代表合格设计。
