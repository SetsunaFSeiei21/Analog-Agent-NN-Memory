# Analog-Agent Slurm 脚本

从参考项目沿用“提交脚本 → 通用 Slurm runner → Python 入口”的分工。当前采样用 CPU 和 ngspice，不申请 GPU；Slurm account 和 partition 不写死，使用集群默认值或在提交时设置。所有命令都从 `analog-agent/` 目录执行。

## Smoke test

先将示例网表中的 `.include` 改为 `5t_ota_params.sp`，确认计算节点能执行 `ngspice`，并确认默认条件 JSON 的 `PDK_PATH` 指向实际模型文件。提交前可先看完整命令：

```bash
ANALOG_DRY_RUN=1 bash scripts/smoke_test/submit_sampling.sh
ANALOG_CONDA_ENV=newbase bash scripts/smoke_test/submit_sampling.sh
```

第二行按实际 Python 环境设置 `ANALOG_CONDA_ENV`；若作业已继承正确的 Python 环境，可以不设置。Conda 安装位置不同则加 `ANALOG_CONDA_HOME=/实际/conda/路径`。脚本为 `5t_ota` 提交 6 点、2 个 worker 的 CPU 作业，提取 `DC_GAIN UGF PM POWER`；工作副本放在 `smoke_test_circuits/`，每次输出单独存放于 `smoke_test_results/<运行标识>/5t_ota/`。Slurm 标准输出和报错在 `hpc_logs/smoke_test/<运行标识>/`。作业会保留仿真 workspace，成功后核对 SQLite 和两个 CSV。

如需要指定集群资源：

```bash
ANALOG_CONDA_ENV=newbase ANALOG_SLURM_ACCOUNT=b_phzhwu \
  ANALOG_SLURM_PARTITION=ex01A800 bash scripts/smoke_test/submit_sampling.sh
```

账号和分区取自参考项目的示例，请按当前集群 CPU 作业规则选择；脚本自身不申请 GPU。`--partition` 未指定时使用集群默认分区。

## 正式采样

```bash
ANALOG_CONDA_ENV=newbase bash scripts/run/submit_sampling.sh \
  Sample_Optimizer_Circuit/5t_ota 5t_ota single_ended_opamp \
  300 8 DC_GAIN UGF PM POWER
```

参数依次为：源目录、电路名、电路类型、采样点数、worker 数、指标列表。`scripts/run/slurm_run.sh` 是通用作业执行器，`scripts/run/run_sampling.sh` 负责采样前检查、复制电路、调用 `python -m src.sample_optimize.sample_only`。数据默认写入 `sampling_database/<电路名>/`；提交时可用 `ANALOG_TARGET_ROOT` 指定其他根目录。首次采样只移动工作副本，保留源电路。再次采样同一电路时，沿用已有历史数据目录。同一个电路的并发作业会被锁阻止；不同电路可分别提交。

默认正式采样允许单点仿真失败并把失败信息写入数据库；要在首个失败点停止，可设置 `ANALOG_CONTINUE_ON_ERROR=0`。自定义条件目录用 `ANALOG_SIMULATION_CONDITION_PATH`，指定 ngspice 路径用 `ANALOG_NGSPICE_COMMAND`，保留工作区用 `ANALOG_KEEP_WORKSPACE=1`。资源使用 `ANALOG_SLURM_ACCOUNT`、`ANALOG_SLURM_PARTITION`、`ANALOG_SLURM_TIME`、`ANALOG_SLURM_MEM` 设置。提交后用打印的 Slurm job ID 检查队列与日志。

当前仓库的旧单元测试仍引用 `examples/five_t_ota`；此处没有改动测试文件，运行完整测试套件时仍会在该旧路径失败。

## Git 提交与推送

`scripts/git/push.sh` 适配自参考项目的 Git 脚本。它只暂存 `analog-agent/` 内的修改，在当前分支创建提交，然后推送到已有的 `origin`；不会重新初始化 Git、改分支名或改远端。首次使用可修改 `scripts/git/commit_message.txt`，也可以在命令行直接指定提交信息：

```bash
bash scripts/git/push.sh "Add sampling Slurm scripts"
# 或使用 scripts/git/commit_message.txt 中的提交信息
bash scripts/git/push.sh
```

如果暂存区里已有其他目录的修改，脚本会停止，以免把不相关文件一起提交。执行该脚本会真实创建 Git 提交并推送远端，请先检查 `git status --short`。
