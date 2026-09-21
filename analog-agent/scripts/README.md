# Analog-Agent Slurm 脚本

从参考项目沿用“提交脚本 → 通用 Slurm runner → Python 入口”的分工。当前采样用 CPU 和 ngspice，不申请 GPU；Slurm account 和 partition 不写死，使用集群默认值或在提交时设置。所有命令都从 `analog-agent/` 目录执行。

## Smoke test

确认计算节点能执行 `ngspice`，并确认默认条件 JSON 的 `PDK_PATH` 指向实际模型文件。烟测参数统一在 `scripts/smoke_test/submit_sampling.sh` 顶部配置，包括电路目录、指标、采样量、Conda 环境和 Slurm 资源。先把 `DRY_RUN` 改为 `1`，运行脚本查看提交命令；确认后改回 `0` 并提交：

```bash
bash scripts/smoke_test/submit_sampling.sh
```

脚本默认使用 `newbase`，为 `5t_ota` 提交 6 点、2 个 worker 的 CPU 作业，提取 `DC_GAIN UGF PM POWER`；工作副本放在 `smoke_test_circuits/`，每次输出单独存放于 `smoke_test_results/<运行标识>/5t_ota/`。Slurm 标准输出和报错在 `hpc_logs/smoke_test/<运行标识>/`。作业会保留仿真 workspace，成功后核对 SQLite 和两个 CSV。

如果 Conda 安装位置不同，在脚本顶部设置 `CONDA_HOME`。如集群要求指定账号或分区，在同一配置区填写：

```bash
SLURM_ACCOUNT="你的账号"
SLURM_PARTITION="可运行 CPU 作业的分区"
```

脚本自身不申请 GPU；账号和分区留空时使用集群默认值。

## 正式采样

在 `scripts/run/submit_sampling.sh` 顶部设置 `SOURCE_DIR`、`CIRCUIT_NAME`、`CIRCUIT_TYPE`、`N_POINTS`、`N_WORKERS`、`METRICS`、`TARGET_ROOT` 等参数。提交时无需传参：

```bash
bash scripts/run/submit_sampling.sh
```

`scripts/run/slurm_run.sh` 是通用作业执行器，`scripts/run/run_sampling.sh` 负责采样前检查、复制电路、调用 `python -m src.sample_optimize.sample_only`；这两个内部脚本由提交脚本调用。数据默认写入 `sampling_database/<电路名>/`。首次采样只移动工作副本，保留源电路。再次采样同一电路时，沿用已有历史数据目录。同一个电路的并发作业会被锁阻止；不同电路可分别提交。

默认正式采样允许单点仿真失败并把失败信息写入数据库。要在首个失败点停止，把脚本顶部的 `CONTINUE_ON_ERROR` 改为 `0`。条件目录、ngspice 路径、是否保留工作区及 Slurm 资源也都在同一配置区修改。提交后用打印的 Slurm job ID 检查队列与日志。

当前仓库的旧单元测试仍引用 `examples/five_t_ota`；此处没有改动测试文件，运行完整测试套件时仍会在该旧路径失败。

## Git 提交与推送

`scripts/git/push.sh` 适配自参考项目的 Git 脚本。它只暂存 `analog-agent/` 内的修改，在当前分支创建提交，然后推送到已有的 `origin`；不会重新初始化 Git、改分支名或改远端。先修改 `scripts/git/commit_message.txt`，再直接运行：

```bash
bash scripts/git/push.sh
```

如果暂存区里已有其他目录的修改，脚本会停止，以免把不相关文件一起提交。执行该脚本会真实创建 Git 提交并推送远端，请先检查 `git status --short`。
