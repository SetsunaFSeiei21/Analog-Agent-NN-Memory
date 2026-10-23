# Opamp116 五方法烟测

适用于 `Sample_Optimizer_Circuit/Opamp116/Opamp116.sp` 与
`Opamp116_params.sp`，器件命名为 XNM0/XNM1/...、XPM0/...，接口为
`.subckt DUT VINP VINN VOUT VDD VSS`。

本次适配包括：

- 注册 Opamp116 的参考晶体管、信号路径和节点初值。
- 保留共享 W、不同 L 的 Wilson 偏置约束；LUT 收集每只管实际使用的 L 范围。
- 识别源极不接电源轨、但由 IBIAS 独立驱动的二极管参考支路。
- 参考管并联倍数 M 参与电流与宽度换算，保证其总电流按 IBIAS 处理。
- 多个参考组共享 L 时联合选择一次 L，避免后一个组覆盖前一个组的选择。
- 烟测脚本默认选择 Opamp116 和 five 模式，维持 32 点、8 workers。

你已经在本地添加网表时，把补丁放到 harness 下，在仓库根目录执行以下命令。
`--exclude` 保留你已有的两个网表文件；它们应与本说明对应的器件命名和参数绑定一致。

```bash
cd /share/home/202411094934/python_project/harness
git apply --check --exclude='analog-agent/Sample_Optimizer_Circuit/Opamp116/*' opamp116_sampling_support.patch
git apply --exclude='analog-agent/Sample_Optimizer_Circuit/Opamp116/*' opamp116_sampling_support.patch
cd analog-agent
bash scripts/smoke_test/submit_sampling.sh
```

如果尚未添加网表，应用补丁时省略 `--exclude` 即可。

本补丁沿用 `src/sample_optimize/parameter_ranges.json` 的采样范围，
没有把参数文件的初值当作固定测试点。当前默认 W 为 0.5–10 µm、L 为
0.35–1 µm、M 为 1–50、IBIAS 为 0.5–5 µA。若要覆盖原设计的较大尺寸，
需在该 JSON 的 `circuit_parameter_overrides.Opamp116` 中另外指定范围。
参数文件中的 IBIAS_A=1e-6 是示例初值，原设计复现须使用原 testbench 的偏置电流。

输出目录仍是 `smoke_test_results/<运行标识>/Opamp116/`，提交后脚本会打印完整路径。
采样完成与电路性能达标是两个不同的结果，需结合 metrics 和 DC operating point 检查。

验证：

```bash
python -m pytest tests/test_opamp116_sampling.py tests/test_advanced_sampling.py tests/test_sampling_performance.py tests/test_lvt_sampling.py -q
```

开发环境结果为 57 项通过，包括新增的 10 项 Opamp116 回归检查。
另有 1 项现有测试因仓库缺少 `test/opamp0_open_loop/Opamp0_open_loop.cir`
失败；已在修改前的代码中复现同一失败。
Shell 语法和补丁应用检查通过。gm/ID 测试使用独立解析晶体管模型；
开发环境没有 ngspice 和 Sky130 PDK，未声称完成真实 SPICE 仿真或保证采样性能达标。
