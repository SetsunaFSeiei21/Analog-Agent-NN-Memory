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
PDK、corner、温度、VDD、VSS 和 VCM 一致；默认 TT、27°C、1.8 V、VCM=0.72 V。
ACDC reference 的功耗条件为25°C，若使用它，应将所有测试平台温度统一。
首次运行复制源电路，不移动或改写源文件；实际设计值仅写入独立仿真 workspace。

`n_points` 表示本轮**新增唯一且已保存的仿真设计点**，包含失败点，不表示全部指标正常的点数。
旧的已完成运行不占新一轮配额。默认 Random、LHS、Sobol、gm/ID、Bayesian 各20%；
60000点对应每种12000点。整数配额采用最大余数法，余数相同时按上述顺序。
权重可设为0，但必须显式列出五个方法，至少一个权重为正。

五方法共用 `parameter_ranges.json` 解析后的离散 W/L/M/R/C/I 范围。
`circuit_parameter_overrides` 仍是可选、可部分覆盖，其余参数回退到通用范围。
`device_control_ranges` 不改变 Controller 的通用范围回退规则。
全局 `L=[0.35,1.0,0.01]`（µm）；NMOS 和 PMOS 都使用这个统一范围，
为后续切换到 1.8 V LVT 器件保留 PMOS 所需的长度下限。NMOS.L / PMOS.L 配置同步。
W、M、R、C、I 范围及已有电路覆盖保持原定义；自定义长度覆盖仍需适合所选模型。
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

Opamp0 使用 18 个设计参数：`DESVAR_W1..W7`、`DESVAR_L1..L7`、
`DESVAR_M0/M1/M2` 和 `IBIAS_A`。当前网表的 17 只 MOS 都是 LVT。
`XNM5/6` 共享 W3/L3；`XPM6/7/8/9` 共享 W1/L1。
M0 控制 XNM5；M1 控制输入对 XPM4/5，XPM6 使用 2*M1；
M2 控制 XPM0–3 和 XNM0/1，XNM2/3 使用 M1+M2。
所有 PMOS 的 bulk 接各自 source，NMOS bulk 接 VSS；工作点计算直接读取实际引脚。
配套参数文件只提供示例初值，采样边界仍由 `parameter_ranges.json` 解析。
更换网表、参数或 VCM 后应使用新的输出目录，不能续用旧条件的历史标签。

参考组 L、M 和无源器件先从相同的物理网格取样。根据参考组 LUT 电流密度与 W 范围，
从原 IBIAS_A 网格中选择相容电流；其余组再从原 L 网格中选择与初始尺寸约束相容的长度。
条件采样通过实际连接识别由单个 `IBIAS_A` 电流源驱动、没有其他漏源/电阻直流通路的
二极管参考支路，兼容 NMOS 和 PMOS，不要求它排在 `REFERENCES` 首位。
存在多个这样的参考组时，I 网格须同时满足它们的宽度约束；它们各自的参考 L 均保留
原始抽样值。其他组共享这些 L 时也不得重新选择该 L；其余共享 L 的约束联合求交。
非参考支路的尺寸估计留出两倍余量，最终 LUT 尺寸映射得到的 W 仍须满足严格边界。
因此 gm/ID 的 I 和其余组 L 是条件采样，所有上下限和步进不变；目标 gm/ID 仍独立抽样。
可将 `condition_lengths_on_width` 设为 `false`，改为独立抽取所有 L，再从各组尺寸估计的
共同电流区间抽取 I；窄 W 范围下这种消融的提案拒绝率可能明显较高。
默认 `sizing_mode="nominal_lut"`。先用逆 gm/ID 和体效应建立节点电压初值，
再将参考支路名义电流密度转换为共享 W。上述隔离参考支路使用总 `ID=IBIAS_A`，
即 `W=IBIAS_A / ((ID/W)_LUT * M)`；其他组采用 `ID/M=IBIAS_A` 的名义提案初值。
尾管、折叠支路和第二级的电流倍乘仍由原网表表达式保留。
实际支路电流偏离名义值时，由后续真实 OP 标注，不因预测的偏置失效而丢掉样本。
`ID/M=IBIAS_A` 仅是尺寸提案假设，不表示实际支路电流相同或 gm/ID 目标已经达成。
可选 `sizing_mode="coupled_lut"` 进一步联合求解节点 KCL 和参考 gm/ID，
共享 W 作为未知量；此模式仅接受残差达标的解，复杂拓扑的拒绝率和解算时间可能较高。
共享 W/L/M 绑定保持不变。计算出的 W 越界会拒绝提案，不截断到边界；
合法 W 再量化到工程网格。LUT 无解也拒绝，严格联合模式还拒绝残差过大的解，
这些提案不占设计仿真点数。

### Bulk 连接与体偏置

参考电流识别不要求 `B=S`，也不改写网表 bulk。初始 gm/ID 曲线、长度筛选、
节点电压初始化和严格 KCL 求解均按实际引脚查询体偏置轴：
NMOS 用 `VS-VB`，PMOS 用 `VB-VS`。初始筛选使用 profile 中的节点电压估计；
后续初始化按更新后的节点电压重复查询，并在最后一次节点更新后刷新电流密度。
这些估计仍是尺寸提案，不是已通过 SPICE 的工作点。

所有 `D=G` 的参考器件在逆查询时使用 `|VDS|=|VGS|`，与其是否直接承载 IBIAS 无关。
缓存键包含体偏置与二极管/固定 VDS 查询方式，防止误复用零体偏置曲线。
求解器内部电压以 VSS 为参考，SPICE 节点 `0` 仍表示绝对地，因此也支持非零 VSS。
严格求解发生 D/S 反向时，按有效源极重新计算体偏置。

现有 LUT 只覆盖反向体偏置；正向体偏置或超出 LUT 轴的查询拒绝提案，
不会夹到零体偏置或轴端点。`lut_out_of_domain` 的提案记录包含器件名和阶段，
便于区分初始曲线、长度筛选和节点初始化问题；严格 KCL 求解越界按残差失败拒绝。
若初始节点估计不适合新拓扑，应审阅 `NODE_SEEDS`，而不是把 bulk 自动改接 source。
最终电气可行性仍由真实 BSIM OP 决定；LUT 不替代井结构、体二极管和版图规则检查。

更改 bulk 连接后须使用新的输出目录，旧连接的已保存样本保留为旧电路版本。
本次修改改变 gm/ID 提案算法，不能用新代码直接恢复旧实现的未完成运行。
模型、工况和轴等缓存键仍匹配时，可以复用原有多维 MOS LUT，无需统一删除缓存。

目标网格保证的是**采样目标**。真实 BSIM gm/ID 不会被强行改成目标值；
量化、宽度效应和 LUT 插值可使它偏离目标。SQLite 的 `proposal_json.gmid_targets`
保存目标，`observation_json.devices` 保存实际 gm、id、gm/id、节点电压和饱和余量。

首次使用自动构建 LUT，缓存于数据库根目录的 `.lut_cache`；可通过 `--lut_cache_path`
指定公共缓存。轴为 L、反向体偏置、|VGS|、|VDS|，其中 L 内部用米，电流密度用 A/m；
电路文件 W/L 仍用微米，显式使用 `scale=1u`。PMOS 的电源极性在生成测试平台时转换。
每个实际模型型号独立建表并使用该型号关联的 L 范围，普通管和 LVT 的数据不混用，
也不把 NMOS 的短沟道范围带入 PMOS 表。长度轴覆盖各模型范围两端，
每个模型默认最多12个长度，通过插值覆盖中间长度；
`max_lengths` 可提高至整个长度网格的点数。电压轴用 `[最小值,最大值,步进]`。
禁止越界外推。每个部分构建切片可恢复，完整缓存使用原子写入和构建锁。
首次建表也使用 `--n_workers`：每个独立的模型型号/长度/体偏置切片在独立 workspace
中执行，最多同时启动该数量的 ngspice 进程。已有完整或部分缓存仍可复用；worker 数
不进入 LUT 缓存键。仅含一类 NMOS 和一类 PMOS 时默认最多168个切片；混合更多型号会相应增加。缓存命中时不再仿真。

缓存匹配模型及递归 include 内容、corner、温度、ngspice 版本、初始化、轴和参考宽度。
工作点与 LUT 均按网表实际型号从 PDK 解析内部 MOS 名称，兼容原始 Sky130 与 open_pdks。
LUT 缓存使用 schema v2，并将实际型号及各自长度轴纳入键；旧版普通管缓存不会误复用。
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

保存为 `design_parameters.csv`、`metrics.csv`、`dc_operating_points.csv` 和 `sampling_history.sqlite3`。
三个 CSV 行一一对应；前两个只含现有设计参数及九个指标，工作点 CSV 按设计点展开全部 MOS。
完整字段、带符号端电压、状态、缓存和旧数据导出见 [DC 工作点说明](dc_operating_points.md)。
新增信息在 SQLite 中：

| 位置 | 内容 |
|---|---|
| samples.sample_method | 五种来源 |
| samples.observation_json | OP、可行性、失效原因和器件工作点 |
| dc_operating_points | 每个设计点的静态偏置条件、OP 状态和缺失字段 |
| dc_device_operating_points | 按 sample_id/器件名关联的全部 MOS 工程字段 |
| samples.proposal_json | gm/ID 目标、LUT 标识或贝叶斯采集信息 |
| sampling_context | 已验证的仿真上下文及指纹 |
| sampling_state | 每方法配额、完成数、RNG、提案统计和待执行批次 |
| spice_invocations | LUT/设计调用、测试平台、完成或不确定状态 |

完整模式先核对源目录与归档网表，再检查测试平台、条件、PDK 递归 include、ngspice
和初始化指纹。没有指纹的旧 CSV/SQLite、或上下文不匹配的历史，**不得作为预热数据**。
它们保留原样，错误信息要求新的输出目录；不自动为旧标签补一个可信指纹。

每个批次在启动 SPICE 前持久化待执行点和生成后的 RNG。结果与配额进度在一个 SQLite
事务中提交；CSV 默认每10批原子导出，正常结束及可捕获异常退出时强制导出。
可设 `--csv_export_interval_batches 1` 恢复每批导出；工作点宽表较大时可设
`--csv_export_interval_batches 0` 仅在结束/异常时导出。运行期间 CSV 可能比 SQLite
滞后，训练和恢复应以 SQLite 为准；进程被强制终止时，下一次恢复会重新导出。
因此恢复时无需重新生成已保存点：
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

## 性能与耗时定位

`--n_workers 8` 同时控制 LUT 建表及设计仿真的最大并发数，两阶段先后执行。
设计点通过共享队列动态派发，每个 worker 独占 workspace 和逐点预算状态；空闲
worker 领取下一点，结果最后按输入索引排序。调度线程负责文件操作和等待外部
ngspice 进程，避免为每个小批次另起 Python 进程。各方法轮转、随机数和反馈时机
保持原协议。历史标签和去重键按 sample_id 增量读取，已提交行在内存中复用。
gm/ID 固定偏置下的初始曲线及长度网格插值只计算一次，在候选之间复用；
目标抽样、长度/电流条件筛选、后续节点解算及提案拒绝规则不变。

默认 INFO 日志记录 LUT 进度、各方法候选生成、仿真批次和整体各阶段耗时。
单次 OP 或测试平台超过10秒时也输出耗时；`--log_level DEBUG` 可查看所有逐点、
逐平台耗时。返回的 `timings_seconds` 为本次调用的壁钟时间，包含 LUT、
各方法提案、历史读取、仿真、数据库写入和 CSV 导出；恢复调用的时间单独统计。
仿真批次时间包含 workspace 准备及所有点的等待，不是各子进程时间之和。

建表并行主要改善首次运行，增量历史和减少 CSV 重写主要改善大规模采样。
gm/ID 在狭窄尺寸范围下的提案拒绝仍可能耗时，查看 `proposal_gmid`；
贝叶斯查看 `proposal_bayesian`，平台收敛问题查看 `SPICE bench timing`。
仿真条件、收敛容差、瞬态步长和失效标签定义没有降低，实际速度依赖 CPU、
存储和电路收敛情况，不能仅由 worker 数推断加速倍数。

已完成的历史和 LUT 可继续复用。旧版本未完成运行的 implementation 指纹与新代码
不同，原有严格校验会拒绝直接续跑；请先用原版本完成该运行，再应用本补丁。
本版本内部的中断恢复仍保持草稿、配额和 RNG；CSV 导出间隔和 worker 数可改变。

## 兼容入口与验证

原三方法命令需显式加 `--sampling_mode legacy`，Python 原 API 行为保留。
旧历史兼容模式不提供完整模式的上下文验证、OP 标签或断点恢复，不可把它用于
给完整模式的旧数据“认证”。完整模式仍会拒绝未知来源历史。
`scripts/run/run_sampling.sh` 默认五方法，可通过 `ANALOG_SAMPLING_MODE=legacy`
恢复旧模式；配置、缓存和恢复参数分别为 `ANALOG_SAMPLING_CONFIG`、
`ANALOG_LUT_CACHE`、`ANALOG_RESUME_RUN_ID`；CSV 导出间隔可通过
`ANALOG_CSV_EXPORT_INTERVAL_BATCHES` 指定。

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
