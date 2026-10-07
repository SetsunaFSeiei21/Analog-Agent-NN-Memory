# 每个设计点的晶体管 DC 工作点

每次仿真记录 DUT 内全部 NMOS/PMOS，包括偏置管。一个设计点对应一份静态快照；
随机、LHS、Sobol、gm/ID、带约束贝叶斯及 `PointSimulator` 使用同一采集和存储合同。
神经网络输入与九个性能指标合同保持原样，本改动只采集和保存工作点。

## DC 条件

使用 `power_condition.json` 的 `PDK_PATH`、`CORNER`、`TEMP`、`VDD`、`VSS`、`VCM`，
接法为 `.subckt DUT VINP VINN VOUT VDD VSS` 的单位增益跟随器：`VINP=VCM`，`VINN=VOUT`。
条件与接法随每个快照保存，不把默认温度或共模电压写死在数据中。

五方法流程复用已有的独立 OP 调用，只扩展其输出字段，不增加 OP 次数；每个设计仍是
一次 OP 加上所需性能测试平台。原三方法和直接单点接口补上这一次 OP 调用。
只提供 AC 类指标子集、条件目录中未提供 `power_condition.json` 时，使用已提供 AC、
stability、CMRR 或 PSRR 条件的相同静态跟随器偏置，并明确保存实际条件。
只有 slew 条件时须额外提供 `power_condition.json`，否则工作点记录为配置失败。

这份快照代表静态参考偏置。slew 测试的脉冲初始低电平、瞬态高电平及变化过程中
各器件状态可能不同，即使脉冲幅度相同，也不等于这份 DC 快照。

## CSV：每个设计点一行

电路目录中生成：

```text
design_parameters.csv
metrics.csv
dc_operating_points.csv
sampling_history.sqlite3
```

一次完整导出后，三个 CSV 的第 N 条数据对应同一个设计点，均按 SQLite 的 `sample_id`
递增排列。原设计和指标 CSV 的列名不变；工作点 CSV 包含 `csv_row_index`（从 0 开始）、
`sample_id`、`design_key`、`access_level`、OP 状态、实际偏置条件和每只 MOS 的展开字段。
`sample_id` 在本电路数据库中唯一，跨电路合并时应同时使用电路名。

例如以下各列均位于同一行，表示该设计点的不同器件：

```text
sample_id,op_status,...,XMN_INP.id_a,XMN_INP.gm_s,XMN_INP.vgs_v,...,XMP_OUT.gm_s,XMP_OUT.cgs_f,...
```

器件名称统一为大写并按名称排序。失败点仍占一行，不会使三个文件错位。
数值缺失在 CSV 中为 `nan`，SQLite 中为 `NULL`；不能用零替代缺失值。
CSV 是同一个 SQLite 读取快照生成的兼容导出，各文件分别原子替换。
五方法仍默认每 10 批导出，结束或可捕获异常退出时强制导出，SQLite 每批提交。
仿真工作目录复制会排除这份可能较大的 CSV。
对于 60,000 点等大数据集，可加 `--csv_export_interval_batches 0`，仅在结束或可捕获异常时
导出三份 CSV，避免反复重写整个宽表。所有已提交工作点仍即时保存在 SQLite。

## 器件字段及符号

| 列名（省略器件前缀） | 含义及单位 |
|---|---|
| `device_type`, `model_name` | NMOS/PMOS 类型与模型名 |
| `id_a`, `gm_s`, `gds_s`, `gmbs_s` | ngspice 原始模型输出；电流 A，电导/跨导 S |
| `vth_v`, `vdsat_v` | 原始模型阈值及饱和电压，V |
| `vd_v`, `vg_v`, `vs_v`, `vb_v` | DUT 中 D/G/S/B 端相对节点 0 的电压，V |
| `vgs_v`, `vds_v`, `vbs_v` | 由端电压计算的带符号 `Vg−Vs`、`Vd−Vs`、`Vb−Vs`，V |
| `model_vgs_v`, `model_vds_v`, `model_vbs_v` | ngspice `@MOS[vgs/vds/vbs]` 的原始值，V |
| `vgs_normalized_v`, `vds_normalized_v`, `vbs_normalized_v` | 端电压差乘 NMOS 的 +1 / PMOS 的 −1，V |
| `reverse_body_bias_v` | 相反方向的归一化体源电压，V |
| `gmid_v_inv` | `abs(gm/id)`，V⁻¹；近零电流时为空 |
| `intrinsic_gain_v_v` | `abs(gm/gds)`，V/V；近零 `gds` 时为空 |
| `saturation_margin_v` | `vds_normalized_v − abs(vdsat_v)`，V |
| `w_um`, `l_um`, `multiplicity` | 参数表达式解析后的实际 W/L（μm）与 M；如 `2*M_FACTOR` 会展开 |
| `cgg_f`, `cgs_f`, `cgd_f`, `cgb_f`, `cdg_f`, `cdd_f`, `cds_f`, `cdb_f`, `csg_f`, `csd_f`, `css_f`, `csb_f`, `cbg_f`, `cbd_f`, `cbs_f`, `cbb_f` | 模型输出的端电荷小信号电容矩阵，F |
| `capbd_f`, `capbs_f` | 模型输出的体漏/体源结电容，F |

BSIM 模型的 PMOS 电压及电流输出可能采用归一化约定，因此 `id_a`、`model_*` 不被
擅自改符号；带符号端电压使用 `vgs_v/vds_v/vbs_v`。电容矩阵不是简单的正值两端电容，
原始负值保留，不取绝对值。模型版本不支持的字段为空并在 `op_missing_fields` 记录。
gm、id 和电容均使用实例输出，不再额外乘一次 M。

兼容的 `samples.observation_json.devices` 仍保留原先的 `gm/id/gds/vdsat` 和归一化
`vgs_v/vds_v` 键。新增 `vgs_raw_v/vds_raw_v/vbs_raw_v` 保存带符号端电压；SQL/CSV 的
`vgs_v/vds_v/vbs_v` 映射到这些 raw 字段，避免改变已有可行性逻辑。

## SQLite：按器件保存

| 表 | 一条记录代表什么 |
|---|---|
| `samples` | 现有设计参数、九指标、采样来源、访问分区及兼容 observation DTO |
| `dc_operating_points` | 一个设计点的 OP 状态、条件、MOS 端节点电压、缺失字段与失败原因 |
| `dc_device_operating_points` | 一只 MOS 的上述数值字段，主键为 `(sample_id, device_name)` |

新采样的三种记录在同一个事务中提交，重复设计或写入失败会整体回滚。
工作点通过外键继承父样本身份与访问分区，不单独产生训练/隐藏/盲测标签。
公共 `fetch_operating_point(sample_id)` 默认只读 `train_visible`；评估控制器必须明确
提供自己的 `access_levels`。CSV 与原兼容导出一样包含所有分区，训练仍应使用受访问控制的
SQLite 适配器，不直接使用 CSV 绕过隐藏/盲测分区。

查询可见输入管工作点的例子：

```sql
SELECT s.sample_id, s.design_values_json, d.device_name,
       d.gm_s, d.gmid_v_inv, d.vgs_v, d.vds_v, d.cgs_f
FROM samples s
JOIN dc_device_operating_points d USING (sample_id)
WHERE s.access_level = 'train_visible' AND d.device_name = 'XMN_INP'
ORDER BY s.sample_id;
```

## 状态、缓存与旧数据

`op_status` 与指标成功、是否电气可行分别记录：

| 状态 | 含义 |
|---|---|
| `complete` | DC 收敛且全部请求的原始模型字段取得；不等于性能达标 |
| `partial` | DC 收敛，但部分模型字段缺失；有效字段仍保存 |
| `failed` | OP 配置、执行或收敛失败；支持的电路仍保留全部 MOS 身份与实际尺寸 |
| `legacy_partial` | 从旧 observation 迁移的部分工作点，未假定未记录字段存在 |
| `not_recorded` | 原记录没有工作点，例如旧 CSV 迁移或仅外部指标写入 |

AC 或瞬态指标缺失时，成功取得的 OP 仍保存。OP 失败时，指标测试仍可继续取得部分值。
单点缓存命中复用同一个 `sample_id` 和工作点，既不追加样本，也不增加 SPICE 调用。
`PointSimulationResult.operating_point` 返回按上述 SQL 字段整理的工作点。

打开旧数据库时只迁移它已经保存的工作点，不启动 SPICE，不伪造 Cgs/Vth 或端电压。
未知字段为 `NULL/nan`；更新后真实仿真的新点取得完整字段。已有 v1 记录中归一化
`vgs_v` 不会被误当成带符号电压。仅版本 1 已知采集器升级到版本 2、且网表、PDK、
测试平台、电压、温度及 ngspice 等全部物理上下文相同时，允许在已完成的数据集上追加。
其他上下文变更仍要求新输出目录。未完成运行的恢复仍严格检查实现/配置指纹，更新前应
先完成当前运行。

可以单独从既有 SQLite 生成宽表：

```bash
cd analog-agent
python scripts/run/export_sampling_history.py --circuit-path sampling_database/Opamp1
```

该命令不运行 SPICE，只迁移已记录数据并重新导出三份 CSV。
旧 `Simulator.simulate()` 后接 `write_simulate_result()` 会复用匹配的最近一次仿真工作点；
使用 `simulate_batch()` 的外部调用方则可显式把 `result.observations` 传给保存接口。

## 验证

```bash
cd analog-agent
PYTHONPATH=. python -m pytest -q
```

另外设置 `ANALOG_TEST_NGSPICE` 为 ngspice 可执行路径、`ANALOG_TEST_SKY130_LIBRARY` 为包含 `tt`
section 的 Sky130 lib 文件后，工作点测试会对仓库五个电路运行真实 OP。
字段约定参见 [ngspice 用户手册，BSIM4 accessible instance parameters](https://ngspice.sourceforge.io/docs/ngspice-43-manual.pdf)。
