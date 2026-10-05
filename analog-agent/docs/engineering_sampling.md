# 五方法工程采样

五方法模式用于建立神经网络数据集：增加正常工作点，同时保留失效点和边界点。
它不以最大增益、最大 UGF 或最小功耗为优化目标。CLI 默认启用五方法；
`Sampling_Controller` 保留原有三方法 Python API，完整模式使用
`src.sample_optimize.advanced.controller.DatasetSamplingController`。

代码阅读顺序：`advanced/config.py` → `profiles.py` → `context.py` →
`lut.py` → `gmid.py` → `operating_point.py` → `bayesian.py` → `controller.py`，
最后查看 `history_store.py`、`simulating.py` 的联动和两个新增测试文件。

## 配置与运行

```bash
cd analog-agent
python -m pip install -r requirements-sampling.txt
python -m src.sample_optimize.sample_only \
  --src_path Sample_Optimizer_Circuit/Opamp0 \
  --circuit_type single_ended_opamp --circuit_name Opamp0 \
  --target_path sampling_database_v2 \
  --simulation_condition_path /path/to/conditions \
  --sampling_config_path configs/sampling/five_method.json \
  --metrics DC_GAIN UGF PM CMRR P_PSRR N_PSRR P_SR N_SR POWER \
  --n_points 60000 --n_workers 16 --seed 42
```

先将六份仿真条件 JSON 的 `PDK_PATH` 改成本机文件。完整模式核对六份条件的
PDK、corner、温度、VDD、VSS 和 VCM 一致；默认 TT、27°C、1.8 V、VCM=0.9 V。
ACDC reference 的功耗条件为25°C，若使用它，应将所有测试平台温度统一。
首次运行复制源电路，不移动或改写源文件；实际设计值仅写入独立仿真 workspace。

`n_points` 表示本轮**新增唯一且已保存的仿真设计点**，包含失败点，不表示全部指标正常的点数。
旧的已完成运行不占新一轮配额。默认 Random、LHS、Sobol、gm/ID、Bayesian 各20%；
60000点对应每种12000点。整数配额采用最大余数法，余数相同时按上述顺序。
权重可设为0，但必须显式列出五个方法，至少一个权重为正。

五方法共用 `parameter_ranges.json` 解析后的离散 W/L/M/R/C/I 范围。
`circuit_parameter_overrides` 仍是可选、可部分覆盖，其余参数回退到通用范围。
`device_control_ranges` 不改变 Controller 的通用范围回退规则。
Sobol 按2的幂生成块，再投影、截取和去重；最终集合不宣称保持完整 Sobol 平衡性质。
LHS 的分层性质同样会受到离散投影和去重影响。

## gm/ID：离散目标与真实工作点分开

默认目标为 `[8.0,20.0,0.5]`，单位 V⁻¹。每个共享尺寸组独立取值。
以下三个配置等价：省略 `group_gmid_overrides`、设置 `{}`、设置 `null`。
可只覆盖个别组，未覆盖组继续使用默认目标：

```json
{
  "gmid": {
    "default_range": [8.0, 20.0, 0.5],
    "group_gmid_overrides": {
      "Opamp0": {"DESVAR_W3": [10.0, 16.0, 0.5]},
      "5t_ota": {"WIN": [12.0, 20.0, 0.5]}
    }
  }
}
```

也可在单电路配置中直接写 `{"WIN":[12,20,0.5]}`。组名是该组的宽度参数名，
不是晶体管实例名。未知组或电路名会报错，避免拼写错误被忽略。

| 电路 | 组的宽度参数 | 允许处于三极区的自级联偏置器件示例 |
|---|---|---|
| 5t_ota | WBIAS, WIN, WLOAD | — |
| two_stage_opamp_otaf | WBIAS, WIN, WLOAD, W2P | — |
| two_stage_folded_opamp | WPBIAS, WNBIAS, WPCAS_BIAS, WNCAS_BIAS, WIN, WPFOLD, WPCAS, WNCAS, W2P | XMP_PCAS_SOURCE, XMN_NCAS_SOURCE |
| Opamp0 | DESVAR_W1 … DESVAR_W7 | XNM6 |
| Opamp1 | DESVAR_W1, W2, W4, W5, W6, W7, W8, W9, W10（均含DESVAR_前缀） | XPM10, XNM10 |

参考组 L、M 和无源器件先从相同的物理网格取样。根据参考组 LUT 电流密度与 W 范围，
从原 IBIAS_A 网格中选择相容电流；其余组再从原 L 网格中选择与初始尺寸约束相容的长度。
非参考支路的尺寸估计留出两倍余量，实际 W 仍需经联合解算满足严格边界。
因此 gm/ID 的 I 和其余组 L 是条件采样，所有上下限和步进不变；目标 gm/ID 仍独立抽样。
可将 `condition_lengths_on_width` 设为 `false`，改为独立抽取所有 L，再从各组尺寸估计的
共同电流区间抽取 I；窄 W 范围下这种消融的提案拒绝率可能明显较高。
默认 `sizing_mode="nominal_lut"`。先用逆 gm/ID 和体效应建立节点电压初值，
再将参考支路名义电流密度转换为共享 W；五个拓扑的参考管均采用 `ID/M=IBIAS_A`
的名义镜像关系，尾管、折叠支路和第二级的电流倍乘仍由原网表表达式保留。
实际支路电流偏离名义值时，由后续真实 OP 标注，不因预测的偏置失效而丢掉样本。
可选 `sizing_mode="coupled_lut"` 进一步联合求解节点 KCL 和参考 gm/ID，
共享 W 作为未知量；此模式仅接受残差达标的解，复杂拓扑的拒绝率和解算时间可能较高。
共享 W/L/M 绑定保持不变。计算出的 W 越界会拒绝提案，不截断到边界；
合法 W 再量化到工程网格。LUT 无解也拒绝，严格联合模式还拒绝残差过大的解，
这些提案不占设计仿真点数。

目标网格保证的是**采样目标**。真实 BSIM gm/ID 不会被强行改成目标值；
量化、宽度效应和 LUT 插值可使它偏离目标。SQLite 的 `proposal_json.gmid_targets`
保存目标，`observation_json.devices` 保存实际 gm、id、gm/id、节点电压和饱和余量。

首次使用自动构建 LUT，缓存于数据库根目录的 `.lut_cache`；可通过 `--lut_cache_path`
指定公共缓存。轴为 L、反向体偏置、|VGS|、|VDS|，其中 L 内部用米，电流密度用 A/m；
电路文件 W/L 仍用微米，显式使用 `scale=1u`。PMOS 的电源极性在生成测试平台时转换。
长度轴覆盖物理范围两端，默认最多12个合法长度，通过插值覆盖中间长度；
`max_lengths` 可提高至整个长度网格的点数。电压轴用 `[最小值,最大值,步进]`。
禁止越界外推。每个部分构建切片可恢复，完整缓存使用原子写入和构建锁。

缓存匹配模型及递归 include 内容、corner、温度、ngspice 版本、初始化、轴和参考宽度。
内部 MOS 名称从 PDK 文件解析，兼容原始 Sky130 与 open_pdks。
LUT 假设电流随 W 成比例，仅作为候选生成近似；**实际 ngspice OP 才决定可行性**。
参考：[medwatt/gmid](https://github.com/medwatt/gmid)，审阅版本
`6c4c5e164295c60a8b996f9dff8a79c64456ddaf`。本实现借鉴其多维 LUT 和 ID/W 尺寸映射，
使用原生 NumPy/SciPy/ngspice 实现，未引入其完整优化器或 pickle LUT。

## 工作点约束与贝叶斯方法

每个设计先在单位增益跟随器接法下做 OP。默认条件为：

1. 直流收敛并取得节点电压；
2. `abs(VOUT-VCM) <= 0.05 V`；
3. 指定信号通路器件的正向 `VDS-|VDSAT| >= 0 V`；
4. 信号器件电流幅值至少1e-12 A，避免把全关断状态当成饱和。

三项阈值都可在 `constraints` 修改。偏置器件不统一强制饱和。
不施加增益、UGF 或相位裕度等高性能门槛。OP 失效也继续尝试全部九个指标；
可取得的值仍保留，缺失值 CSV 为 `nan`、SQLite 为 `NULL`。
原 `samples.success` 仍表示全部请求指标取得，电气可行性独立存于 `observation_json.feasible`。

贝叶斯采样在单位化设计空间中，对 OP 二元可行标签建立有噪声的精确高斯过程回归。
其概率是高斯代理的近似，首版不宣称已校准的 GP 分类概率。采集函数结合可行性、
后验不确定性、边界不确定性和与已观测点的距离；20%的选点保留随机探索。
批内贪心距离惩罚减少选点聚集。预热默认32点，默认候选池1024点；
最多256个确定性、按类别平衡的历史点参与 GP 拟合，防止60000点的三次方开销。
全部可见历史参与覆盖距离计算。没有明确 OP 的旧行不被伪造为负标签。
不使用隐藏或 final-blind 标签；首版完整自适应模式只接受 `train_visible` 写入。

按配额完成比例轮转方法，每批保存结果，再供后续贝叶斯选点学习。
提案与 seed、配置和已保存数据有关，不依赖 worker 完成顺序。
贝叶斯使用 SciPy，采样不依赖 CUDA、PyTorch、BoTorch 或 ZeroSim checkpoint。

## 历史、保存与恢复

保存仍为 `design_parameters.csv`、`metrics.csv` 和 `sampling_history.sqlite3`。
两个 CSV 行一一对应、只含现有设计参数及九个指标；新增信息在 SQLite 中：

| 位置 | 内容 |
|---|---|
| samples.sample_method | 五种来源 |
| samples.observation_json | OP、可行性、失效原因和器件工作点 |
| samples.proposal_json | gm/ID 目标、LUT 标识或贝叶斯采集信息 |
| sampling_context | 已验证的仿真上下文及指纹 |
| sampling_state | 每方法配额、完成数、RNG、提案统计和待执行批次 |
| spice_invocations | LUT/设计调用、测试平台、完成或不确定状态 |

完整模式先核对源目录与归档网表，再检查测试平台、条件、PDK 递归 include、ngspice
和初始化指纹。没有指纹的旧 CSV/SQLite、或上下文不匹配的历史，**不得作为预热数据**。
它们保留原样，错误信息要求新的输出目录；不自动为旧标签补一个可信指纹。

每个批次在启动 SPICE 前持久化待执行点和生成后的 RNG。结果与配额进度在一个 SQLite
事务中提交；CSV 在事务之后原子导出。因此恢复时无需重新生成已保存点：
gm/ID 批次生成较慢时也保存已接受的草稿和 RNG，避免丢掉批内已经选出的候选。
完整模式使用 SQLite `DELETE` journal 和 `synchronous=FULL`，所有连接显式关闭；
它不依赖 WAL 的共享内存。正式输出目录仍需提供可靠的文件锁和原子文件操作。

```bash
# 保持上一条命令的 seed、n_points、配置和仿真条件，增加：
--resume_run_id latest
```

也可传具体 run_id。`n_points` 保持原运行总数，恢复只补剩余配额；worker 数可改变。
可靠保存的批次不重跑；SPICE 已执行但结果尚未提交的待执行批次可能重跑，
额外调用会保留在预算表中。中断发生在调用预留之后、执行状态确认之前的条目为
`reserved`：它表示可能发生的调用，不能断言是否真正启动或完成。
CSV 导出中断时，恢复后从 SQLite 重新生成，不会造成设计/指标行错位。

点预算、LUT 调用和具体 ngspice 进程数分开：一个完整设计通常为1次 OP + 6次指标平台。
gm/ID 解算拒绝、重复提案、缓存 LUT 复用不计设计点；LUT 构建单独计成本。
`max_proposals_per_point` 是单次执行中剩余配额的提案上限，达到后停止并保存进度，
不换成 Random。显式恢复给予剩余配额新的提案预算，并保留累计计数和 RNG。
更改物理范围或 gm/ID 设置应在新的运行目录启动，而不修改已有运行的协议。

## 兼容入口与验证

原三方法命令需显式加 `--sampling_mode legacy`，Python 原 API 行为保留。
旧历史兼容模式不提供完整模式的上下文验证、OP 标签或断点恢复，不可把它用于
给完整模式的旧数据“认证”。完整模式仍会拒绝未知来源历史。
`scripts/run/run_sampling.sh` 默认五方法，可通过 `ANALOG_SAMPLING_MODE=legacy`
恢复旧模式；配置、缓存和恢复参数分别为 `ANALOG_SAMPLING_CONFIG`、
`ANALOG_LUT_CACHE`、`ANALOG_RESUME_RUN_ID`。

```bash
PYTHONPATH=. python -m pytest -q
# 安装真实 ngspice 后加入电气验证：
ANALOG_TEST_NGSPICE=/path/to/ngspice PYTHONPATH=. python -m pytest -q
# 含真实 Sky130 器件工作点检查：
ANALOG_TEST_NGSPICE=/path/to/ngspice \
ANALOG_TEST_SKY130_LIBRARY=/path/to/sky130.lib.spice \
PYTHONPATH=. python -m pytest -q
```

建议先对每个拓扑做小规模试采，查看来源、实际 gm/ID 和电气可行率，再启动正式规模。
小规模验证仅证明流程和电气提取可运行，不能推断60000点时的有效率或最终 NN 收益。

首版实际验证使用 ngspice42、官方 Sky130 TT NMOS/PMOS 模型、27°C、seed=42，
每个拓扑五种方法各1点。为了在少量点中执行 GP 选点，试采配置使用 batch_size=1、
warmup_points=3、candidate_pool_size=128；gm/ID 目标、物理参数边界和尺寸模式使用默认值。
25个唯一设计及175次设计平台调用全部保存，缺失指标仍按协议保留。

| 拓扑 | 已保存点 | 全部九项指标取得 | OP 可行点 | 生成1个gm/ID点的提案数 |
|---|---:|---:|---:|---:|
| 5t_ota | 5 | 5 | 2 | 2 |
| two_stage_opamp_otaf | 5 | 4 | 2 | 6 |
| two_stage_folded_opamp | 5 | 1 | 0 | 235 |
| Opamp0 | 5 | 2 | 0 | 69 |
| Opamp1 | 5 | 4 | 0 | 246 |

这说明五拓扑的完整采样/保存流程可运行，也说明当前通用范围在复杂拓扑上仍需工程调参。
每种方法每拓扑只有1点，不能据此声称 gm/ID 或贝叶斯已提高有效率。
正式采60000点之前，应扩大试采并比较方法；可根据实际器件工作点配置可选组覆盖，
或调整显式电路参数范围，再冻结正式实验配置。
