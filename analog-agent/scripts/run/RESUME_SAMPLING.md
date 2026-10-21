# SQLite 并发修复与两次采样续跑

本补丁基于最新提交 `5133d5b9ebe34ee047cf5b9f88609d45410a42ad`（2026-10-21），直接修改采样源码，
并提供 5t_ota 和 two_stage_opamp_otaf 各自的续跑入口。无需额外安装器。
保留该提交的 LVT 网表、按具体模型建立的 LUT、参数范围和 VCM=0.72 V 默认条件。

## 1. 应用补丁

在包含 `analog-agent/` 的 Git 仓库根目录执行。将路径改成补丁的实际位置：

```bash
PATCH_FILE=/path/to/analog_sampling_sqlite_resume_5133d5b.patch
git apply --check "$PATCH_FILE"
git apply "$PATCH_FILE"
```

检查失败时先核对版本或冲突；检查通过后才执行第二条命令。
保留原数据库、归档电路、仿真条件、PDK 和 ngspice 版本。应用代码前确保该项目的
采样作业已经结束；不要在正在采样的同一工作目录修改源码。

## 2. 提交续跑任务

进入原项目目录并激活环境：

```bash
cd analog-agent
conda activate newbase

# 预览命令，不提交
DRY_RUN=1 bash scripts/run/submit_resume_5t_ota.sh
DRY_RUN=1 bash scripts/run/submit_resume_two_stage_opamp_otaf.sh

# 各提交一个 Slurm 作业
bash scripts/run/submit_resume_5t_ota.sh
bash scripts/run/submit_resume_two_stage_opamp_otaf.sh
```

两个入口均调用 `submit_resume_sampling.sh`。用 `bash` 运行，脚本内部会调用 `sbatch`。
也可以一次提交两个：`bash scripts/run/submit_resume_sampling.sh`。

正式提交前会只读校验两个任务的原采样实现，只有检查全部通过才调用 `sbatch`。
`DRY_RUN=1` 只显示命令，不读取历史数据库，也不代表兼容性验证通过。
这个补丁只允许 SQLite 修复引起的实现变化；如果旧任务是在本次 LVT/gm-ID/LUT
改动之前启动，必须使用与原任务一致的采样版本续跑，或在新数据目录开始新的任务。
不能用新算法继续写入旧任务并忽略指纹错误。

| 电路 | 恢复的 run ID | 原目标 | 默认 worker / CPU |
| --- | --- | ---: | ---: |
| 5t_ota | 1e9b2d5c2b0a4558824b7437f30305d8 | 60000 | 32 / 32 |
| two_stage_opamp_otaf | 8459175daab247d5aac6243418564861 | 60000 | 32 / 32 |

默认沿用 `sampling_database`、seed=42、九个指标、newbase 环境、ex01A800 分区、
80G 内存和原提交脚本的 1 GPU 请求。采样本身不使用 GPU。
每批原来是 32 点，因此本次续跑保持 batch_size 不变；更多 worker 不增加批内并发。
每个数值库进程的线程数设为 1，避免过度占用 CPU。

可通过环境变量调整资源或原数据路径，例如：

```bash
ANALOG_RESUME_WORKERS=16 bash scripts/run/submit_resume_5t_ota.sh
ANALOG_RESUME_TARGET_ROOT=/absolute/path/to/sampling_database \
    bash scripts/run/submit_resume_two_stage_opamp_otaf.sh
```

公共脚本顶部还支持 `ANALOG_SLURM_ACCOUNT`、`ANALOG_SLURM_PARTITION`、
`ANALOG_SLURM_GPUS`、`ANALOG_SLURM_MEM`、`ANALOG_SLURM_TIME`。
原任务若使用自定义配置，继续使用原来的 `ANALOG_SAMPLING_CONFIG`、
`ANALOG_SIMULATION_CONDITION_PATH` 等设置。
任务启动时还会核验参数范围、归档网表、仿真条件、PDK 和 ngspice；这些也必须与
原任务相同。续跑入口读取 `sampling_database/<电路>/` 中的归档网表。
日志位于 `hpc_logs/resume/日期/`，数据仍在原电路目录。中断的未提交批次会重跑。

## 3. 修改后的相关目录

以下路径均相对于 `analog-agent/`；其余原有文件继续保留。

| 目录 | 文件 | 状态及用途 |
| --- | --- | --- |
| src/sample_optimize/advanced/ | context.py | 修改，调用记录使用串行短事务和重试 |
| src/sample_optimize/advanced/ | controller.py | 修改，严格验证并迁移旧任务指纹 |
| src/sample_optimize/ | history_store.py | 修改，历史连接共用数据库锁 |
| src/sample_optimize/ | sqlite_access.py | 新增，每个数据库一把进程内锁及限时重试 |
| src/sample_optimize/ | resume_compat.py | 新增，验证仅包含本次存储修复的代码变化 |
| src/sample_optimize/ | storage_resume_compat.json | 新增，核验前后哈希及精确源码替换记录 |
| scripts/run/ | submit_resume_5t_ota.sh | 新增，五管 OTA 续跑入口 |
| scripts/run/ | submit_resume_two_stage_opamp_otaf.sh | 新增，二级运放续跑入口 |
| scripts/run/ | submit_resume_sampling.sh | 新增，共用 Slurm 参数和原 run ID |
| scripts/run/ | RESUME_SAMPLING.md | 新增，本使用说明 |
| tests/ | test_advanced_sampling.py | 修改，旧任务状态迁移和拒绝无关变化的测试 |
| tests/ | test_sqlite_concurrency.py | 新增，并发、重试、回滚和异常记录测试 |
| tests/ | test_resume_submission.py | 新增，提交参数、环境及单电路入口测试 |
| tests/ | test_resume_compat.py | 新增，服务器本地版本的严格兼容测试 |

## 4. 行为与边界

- SQL 写事务按数据库文件串行化，SPICE 调用在锁外并行执行。
- SQLite BUSY/LOCKED 时回滚并重试完整短事务，包括提交阶段；重试预算 300 秒。
  重试记录状态不会重复启动 SPICE，长期外部占锁或非锁错误仍会报错。
- 保留 DELETE 日志模式及原有防重复采样进程的 flock，不强行切换 WAL。
- 兼容性先验证保存配置完整性，再验证采样参数、种子、模型/工艺/测试条件和算法。
  仅允许已核验的存储修改。服务器原有的其他本地代码必须与原任务记录保持一致。
- 对本地修改版，在内存中逆向本次已知源码替换，核验修复前的完整代码哈希；不修改源文件。
  无关修改不会被忽略。不要手工改数据库指纹或放宽校验。
- 验证通过后，在一个事务内更新运行配置和状态指纹，并保存原实现哈希；保留已有样本、
  配额、随机数状态和待处理批次。

本地测试覆盖实际 SQLite 并发、外部锁和提交重试，以及模拟 Slurm 提交。
实际集群资源分配和共享文件系统需在服务器作业中验证。

本次运行上述相关回归共 80 项：79 项通过，1 项为原仓库已有失败。
`test_lvt_sampling.py::test_all_shipped_simulation_common_modes_are_072` 引用了
未提交的 `test/opamp0_open_loop/Opamp0_open_loop.cir`；在未应用补丁的
`5133d5b` 上也复现相同的 FileNotFoundError。
