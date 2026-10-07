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

    controller_class = Sampling_Controller
    extra = {}
    if args.sampling_mode == "five":
        from src.sample_optimize.advanced.controller import DatasetSamplingController
        controller_class = DatasetSamplingController
        extra = {"sampling_config_path": args.sampling_config_path, "lut_cache_path": args.lut_cache_path,
                 "csv_export_interval_batches": args.csv_export_interval_batches if args.csv_export_interval_batches is not None else 10}
    elif args.resume_run_id or args.sampling_config_path or args.lut_cache_path or args.csv_export_interval_batches is not None:
        raise ValueError("Resume/config/LUT/CSV options require --sampling_mode five")
    with controller_class(
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
        parameter_range_config_path=args.parameter_range_config_path,
        sample_access_level=args.access_level,
        **extra,
    ) as controller:
        resume = {"resume_run_id": args.resume_run_id} if args.sampling_mode == "five" else {}
        result = controller.sample(
            n_points=args.n_points,
            n_workers=args.n_workers,
            continue_on_error=args.continue_on_error,
            **resume,
        )

    print(result)


if __name__ == "__main__":
    arg_parser = argparse.ArgumentParser(description="电路采样与 ngspice 批量仿真")
    arg_parser.add_argument("--sampling_mode", choices=["five", "legacy"], default="five",
                            help="默认五方法；legacy 为原 Random/LHS/Sobol 兼容模式。")
    arg_parser.add_argument("--sampling_config_path", type=Path, help="五方法配置 JSON；默认均为20%%，gm/ID为[8,20,0.5]。")
    arg_parser.add_argument("--lut_cache_path", type=Path, help="LUT 缓存目录，默认数据库根目录/.lut_cache；首次建表也使用 n_workers。")
    arg_parser.add_argument("--csv_export_interval_batches", type=int,
                            help="五方法每多少批导出三份 CSV，默认10；设1每批导出，设0仅结束/异常时导出。SQLite 每批提交。")
    arg_parser.add_argument("--resume_run_id", help="恢复原运行（原 n_points 不变）；可用 latest。")

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
        "--parameter_range_config_path",
        type=Path,
        default=None,
        help="参数范围 JSON；电路参数可部分覆盖，其余回退到通用范围。默认使用包内 parameter_ranges.json。",
    )
    arg_parser.add_argument(
        "--access_level",
        choices=["train_visible", "hidden_eval", "final_blind"],
        default="train_visible",
        help="写入 SQLite 的数据访问分区。",
    )
    arg_parser.add_argument(
        "--n_points",
        type=int,
        required=True,
        help="本轮新增唯一仿真设计数（含失效点）；恢复时必须保持原总数。legacy 至少3。",
    )
    arg_parser.add_argument(
        "--n_workers",
        type=int,
        required=True,
        help="并发 ngspice 数量上限；五方法的 LUT 建表同样使用此值。",
    )
    arg_parser.add_argument(
        "--continue_on_error",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="单个采样点失败后是否继续。",
    )

    args = arg_parser.parse_args()
    main(args)
