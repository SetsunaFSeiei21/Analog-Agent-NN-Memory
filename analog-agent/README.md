# Analog Agent Phase 1

当前模块完成 Random、LHS、Sobol 参数采样、并行 ngspice 仿真、指标提取和历史数据保存。

## 输入目录约定

假设 `circuit_name="ota5"`，输入目录至少包含：

```text
ota5/
├── ota5.sp
└── ota5_params.sp
```

如果 `ota5.sp` 还引用其他本地模型或子电路文件，这些文件也应放在该目录中。Simulator 会把电路目录中的源文件和子目录复制到每个独立 workspace。

目前 `single_ended_opamp` 的 testbench 使用五引脚接口 `.subckt DUT VINP VINN VOUT VDD VSS`。偏置电流源应位于 DUT 内部，并通过参数文件中的 `.param IBIAS_A=10e-6` 控制；默认采样范围为 1–50 µA、步长 1 µA。六份默认仿真条件 JSON 不再提供 `IBIAS`。已有六引脚电路须调整接口；已有历史库的参数列若发生变化，使用新的电路名称或历史目录。

`examples/five_t_ota/` 提供完整的九参数示例，包括可采样的偏置电流、偏置管和 OTA 晶体管。电流源是理想直流参考源，电流值以安培表示；仿真供电消耗仍由电源端测得。首次运行会移动输入电路目录，建议先将示例目录复制到工作目录。运行真实 ngspice 前检查条件 JSON 中的 `PDK_PATH` 是否指向本机模型文件。

在 `analog-agent/` 目录下试跑：

```bash
mkdir -p circuits
cp -r examples/five_t_ota circuits/five_t_ota
python -m src.sample_optimize.sample_only --src_path circuits/five_t_ota --circuit_type single_ended_opamp --circuit_name five_t_ota --target_path sampling_database --metrics DC_GAIN UGF PM POWER --n_points 6 --n_workers 1 --keep_workspace
```

## 调用示例

```python
from pathlib import Path

from src.sample_optimize import Sampling_Controller


with Sampling_Controller(
    src_path=Path("circuits/ota5"),
    circuit_name="ota5",
    circuit_type="single_ended_opamp",
    target_path=Path("sampling_database"),
    metrics=["DC_GAIN", "UGF", "PM", "POWER"],
    simulation_condition_path=Path("conditions/ota5"),
    seed=42,
) as controller:
    result = controller.sample(n_points=300, n_workers=16)
```

请把 `analog-agent` 加入 `PYTHONPATH`，并通过包导入；不要直接执行包内的单个 `.py` 文件。

## 历史数据

第一次运行时，输入电路目录会被移动到：

```text
target_path/circuit_name/
```

该目录中的主要输出为：

```text
circuit_name/
├── sampling_history.sqlite3
├── design_parameters.csv
├── metrics.csv
├── simulation_failures.jsonl
└── logs/
    └── sampling.log
```

- `sampling_history.sqlite3` 是唯一可信数据源，使用事务保存运行记录和采样结果；
- 两个 CSV 由 SQLite 原子导出，用于兼容训练代码；
- 已存在的旧双 CSV 会在首次运行时自动迁移；
- 相同 design point 会被跳过，Controller 会继续补点；
- 同一电路历史库的参数列和指标列必须保持一致。

## 日志

Parser、Parameter Analyzer、Random/LHS/Sobol Sampler、Simulator 和 HistoryStore 都使用 Controller 创建的同一日志树。默认同时写入终端和 `logs/sampling.log`，单文件最大 10 MiB，保留 5 个轮转文件。
