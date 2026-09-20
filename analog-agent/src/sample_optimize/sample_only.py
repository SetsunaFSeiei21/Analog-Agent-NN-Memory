import argparse
import json
import logging

from pathlib import Path

from src.sample_optimize.sampling_controller import Sampling_Controller
from src.utils import DEFAULT_DEVICE_RULES, DeviceRule


def main(args: argparse.Namespace) -> None:
    parameter_aliases = None
    if args.parameter_aliases is not None:
        parameter_aliases = json.loads(args.parameter_aliases.read_text(encoding="utf-8"))

    device_rules = DEFAULT_DEVICE_RULES
    if args.device_rules is not None:
        rule_data = json.loads(args.device_rules.read_text(encoding="utf-8"))
        device_rules = tuple(DeviceRule(**rule) for rule in rule_data)

    with Sampling_Controller(
        src_path=args.src_path,
        circuit_name=args.circuit_name,
        circuit_type=args.circuit_type,
        target_path=args.target_path,
        metrics=args.metrics,
        simulation_condition_path=args.simulation_condition_path,
        seed=args.seed,
        parameter_aliases=parameter_aliases,
        device_rules=device_rules,
        log_level=getattr(logging, args.log_level),
        console_log=args.console_log,
        ngspice_command=args.ngspice_command,
        simulation_timeout_seconds=args.simulation_timeout_seconds,
        keep_workspace=args.keep_workspace,
        max_duplicate_rounds=args.max_duplicate_rounds,
    ) as controller:
        result = controller.sample(
            n_points=args.n_points,
            n_workers=args.n_workers,
            continue_on_error=args.continue_on_error,
        )

    print(result)


if __name__ == "__main__":
    arg_parser = argparse.ArgumentParser(description="电路采样与 ngspice 批量仿真")

    arg_parser.add_argument(
        "--src_path",
        type=Path,
        required=True,
        help="需要仿真的电路所在目录。",
    )
    arg_parser.add_argument(
        "--circuit_type",
        type=str,
        choices=["single_ended_opamp"],
        required=True,
        help="电路类型。",
    )
    arg_parser.add_argument(
        "--circuit_name",
        type=str,
        required=True,
        help="电路名称，例如 ota5。",
    )
    arg_parser.add_argument(
        "--target_path",
        type=Path,
        required=True,
        help="电路及采样数据的保存目录。",
    )
    arg_parser.add_argument(
        "--metrics",
        nargs="+",
        choices=["DC_GAIN", "UGF", "PM", "CMRR", "P_PSRR", "N_PSRR", "P_SR", "N_SR", "POWER"],
        required=True,
        help="需要提取的性能指标，可传多个。",
    )
    arg_parser.add_argument(
        "--simulation_condition_path",
        type=Path,
        default=None,
        help="仿真条件 JSON 所在目录；不传则使用默认条件。",
    )
    arg_parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="采样随机种子。",
    )
    arg_parser.add_argument(
        "--parameter_aliases",
        type=Path,
        default=None,
        help="参数别名 JSON 文件路径。",
    )
    arg_parser.add_argument(
        "--device_rules",
        type=Path,
        default=None,
        help="器件识别规则 JSON 文件路径。",
    )
    arg_parser.add_argument(
        "--log_level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="日志级别。",
    )
    arg_parser.add_argument(
        "--console_log",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="是否向终端输出日志。",
    )
    arg_parser.add_argument(
        "--ngspice_command",
        type=str,
        default="ngspice",
        help="ngspice 命令或可执行文件路径。",
    )
    arg_parser.add_argument(
        "--simulation_timeout_seconds",
        type=float,
        default=300.0,
        help="每次 ngspice 命令的超时时间，单位为秒。",
    )
    arg_parser.add_argument(
        "--keep_workspace",
        action="store_true",
        help="保留仿真工作目录，便于调试。",
    )
    arg_parser.add_argument(
        "--max_duplicate_rounds",
        type=int,
        default=50,
        help="采样点重复时最多补采的轮数。",
    )
    arg_parser.add_argument(
        "--n_points",
        type=int,
        required=True,
        help="采样点总数，至少为 3。",
    )
    arg_parser.add_argument(
        "--n_workers",
        type=int,
        required=True,
        help="并行仿真的工作进程数。",
    )
    arg_parser.add_argument(
        "--continue_on_error",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="单个采样点失败后是否继续。",
    )

    args = arg_parser.parse_args()
    main(args)