# loOpamp116：21 参数电流比例约束版五方法烟测

适用于 `Sample_Optimizer_Circuit/loOpamp116/loOpamp116.sp` 和
`loOpamp116_params.sp`，统一接口为 `.subckt DUT VINP VINN VOUT VDD VSS`。

## 参数与匹配关系

主网表包含 15 只 MOS 和内部参考电流源。独立参数是 `DESVAR_W1..W8`、
`DESVAR_L1..L8`、`DESVAR_M1..M4` 和 `IBIAS_A`，共 21 个。

| 宽度/长度组 | 器件 | 倍乘表达式 |
|---|---|---|
| W1/L1 | XNM0、XNM6 | 分别为 M1、2*M3+M4 |
| W2/L2 | XNM10、XNM1、XNM2 | 分别为 M1、2*M3+M4、M2 |
| W3/L3 | XNM8、XNM9 输入对 | M3 |
| W4/L4 | XNM3 cascode 偏置管 | M4 |
| W5/L5 | XNM7、XNM5 cascode 对 | M3 |
| W6/L6 | XPM0、XPM3 偏置镜像 | 分别为 M2、M4 |
| W7/L7 | XPM1、XPM4 有源负载 | M3 |
| W8/L8 | XPM2 输出管 | M3 |

**L1 与 L2 独立**，不合并偏置网络的沟道长度。所有 NMOS bulk 接 VSS；
XPM0/1/3/4 bulk 接 VDD，XPM2 bulk 保留接自身 source 节点 N8。

三个 profile 字典继续使用大小写一致的 `loOpamp116`。REFERENCES 按 W1..W8
依次使用 XNM0、XNM1、XNM8、XNM3、XNM7、XPM0、XPM1、XPM2。
XNM2、XPM3、XPM4 由共享 W 组覆盖，不再重复列为参考管；SIGNAL 仍覆盖原信号通路。
通用 gm/ID 采样器按实际 bulk 引脚查询多维 LUT，支持非零体偏置的浮动源极参考管。

W/L 初值按功能组重新编号，M1..M4 初值均为 1，IBIAS_A 初值为 1e-6 A。
这是一组示例初值，未调优，也不保证与旧 28 参数版具有相同工作点或性能。

## 应用补丁与提交

两份补丁最终得到同一版本，按当前工作区选择一份：

- `loOpamp116_21params_update.patch`：用于已经应用 28 参数补丁、通用体偏置补丁，
  并把网表保存为本轮确认的 21 参数连接和表达式版本的工作区。
  该网表仍带旧的 28 参数注释时，也由增量补丁一并修正。
- `loOpamp116_21params_full_41249a8.patch`：用于干净提交
  `41249a8315ddccd9fc7215340df186431b3d032b`，整合 21 参数网表、参数、profile、
  通用体偏置修复、测试和文档。无需再应用旧的 28 参数或通用体偏置补丁。

增量路径：将补丁放在 harness 目录，在仓库根目录执行：

```bash
cd /share/home/202411094934/python_project/harness
git apply --check loOpamp116_21params_update.patch
git apply loOpamp116_21params_update.patch
cd analog-agent
bash scripts/smoke_test/submit_sampling.sh
```

整合路径使用同样的 `git apply --check` 和 `git apply`，文件名换为
`loOpamp116_21params_full_41249a8.patch`。两份只选一份；先检查再应用。
若只有前两份补丁而尚未保存新网表，请先保存本轮确认的网表，再走增量路径。
检查失败时不要使用 `--reject` 或跳过参数文件，应先核对工作区是否符合对应基准。

烟测脚本已选择 loOpamp116、five 模式、32 点和 8 workers，不需要修改脚本。
运行结果位于 `smoke_test_results/<运行标识>/loOpamp116/`，日志与路径由脚本打印。

21 参数版必须使用新的结果目录，不能恢复旧参数化或旧 bulk 接法的运行。已有数据保留原样；
烟测脚本会自动创建新的结果目录。

## 采样范围与结果解释

参数文件提供初值，不决定采样范围。继续使用 `src/sample_optimize/parameter_ranges.json`：
通用 W 为 0.5–10 um、L 为 0.35–1 um、M 为 1–50、IBIAS 为 0.5–5 uA。
M 范围约束的是 M1..M4 独立变量；派生倍乘 `2*M3+M4` 可以达到 150，
不是再独立抽取一个 M，也不在派生表达式上另外截断。五种方法保留相同绑定。
若要覆盖示例中的大尺寸，应显式配置 `circuit_parameter_overrides.loOpamp116`，
而非仅修改参数初值。新编号按功能重排，旧的自定义参数范围或 gm/ID 组覆盖须重新核对，
不能仅删除不存在的参数名就认为含义相同。仓库默认没有该电路的自定义范围覆盖。

匹配与尺寸比例不保证工作点可行或九项性能达标。应检查实际支路电流、输入对及
级联管的饱和余量，以及 VOUT 对 VCM 的直流跟随误差。正常电流方向下忽略漏电，
N3 节点满足 I(NM6)=I(NM8)+I(NM9)+I(NM3)，尾支路需要同时供给输入对与偏置支路。
理想镜像且输入平衡时，输入对各支路名义电流为 M3/M1*IBIAS_A，
cascode 偏置支路为 M4/M1*IBIAS_A，尾支路为 (2*M3+M4)/M1*IBIAS_A。
这些比例依赖镜像管工作区和实际偏置，不能把器件倍乘直接当成已实现的电流比例。
`nominal_lut` 对非强制参考支路仍使用名义电流启发式，不保证真实 gm/ID 精确等于抽样目标；
真实值由后续 BSIM OP 保存。

## 验证

在安装采样测试依赖的环境中运行：

```bash
cd analog-agent
PYTHONPATH=. python -m pytest tests/test_opamp116_sampling.py tests/test_advanced_sampling.py tests/test_sampling_performance.py tests/test_gmid_body_bias.py -q
```

测试检查 21 个独立参数且全部被引用、L1/L2 独立变化、输入对/级联对匹配、
`2*M3+M4` 表达式和共享倍乘、8 个完整且无重复的尺寸组，以及条件/非条件
gm/ID 候选生成、参考管 M 换算和一般共享 W/不同 L 组的 LUT 长度覆盖。
通用体偏置回归另覆盖 NMOS/PMOS、源体相连或体端接电源、非零 VSS、参考组排序及越界拒绝。
gm/ID 回归使用解析器件模型；真实 Sky130 性能和可行率仍须在集群完成烟测。
