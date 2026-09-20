from __future__ import annotations

import json
import logging
import math
import shutil
import uuid

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Tuple

import numpy as np

from ..utils import (
    Bounds,
    DEFAULT_DEVICE_RULES,
    SUPPORTED_DEVICE_TYPES,
    DeviceRule,
    ParameterSpec,
    add_rotating_file_handler,
    analyze_parameter_usage,
    close_logger,
    create_logger,
    get_child_logger,
    read_parameter_names,
    resolve_parameter_bounds,
)
from .history_store import SamplingHistoryStore
from .lhs_sampling import LHS_Sampler
from .random_sampling import Random_Sampler
from .simulating import Simulator
from .sobol_sampling import Sobol_Sampler


__all__ = ["Sampling_Controller", "SamplingResult"]


DeviceControlKey = Tuple[str, str]
DEFAULT_PARAMETER_RANGE_CONFIG_PATH = Path(__file__).resolve().parent / "parameter_ranges.json"


def _parse_bounds(raw_bounds: object, rule_name: str) -> Bounds:
    if not isinstance(raw_bounds, (list, tuple)) or len(raw_bounds) != 3:
        raise ValueError(f"范围规则 {rule_name!r} 必须是 [lower_bound, upper_bound, step]")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in raw_bounds):
        raise TypeError(f"范围规则 {rule_name!r} 中的值必须是数值")

    lower_bound, upper_bound, step = map(float, raw_bounds)
    if not all(math.isfinite(value) for value in (lower_bound, upper_bound, step)):
        raise ValueError(f"范围规则 {rule_name!r} 必须使用有限数值")
    if lower_bound >= upper_bound:
        raise ValueError(f"范围规则 {rule_name!r} 的 lower_bound 必须小于 upper_bound")
    if step <= 0:
        raise ValueError(f"范围规则 {rule_name!r} 的 step 必须大于 0")
    return lower_bound, upper_bound, step


def _get_config_section(raw_config: dict, section_name: str) -> dict:
    section = raw_config.get(section_name, {})
    if not isinstance(section, dict):
        raise TypeError(f"{section_name} 必须是 JSON object")
    return section


def _load_parameter_range_config(
    config_path: Path,
    circuit_name: str,
    logger: Optional[logging.Logger] = None,
) -> tuple[dict[str, Bounds], dict[DeviceControlKey, Bounds], dict[str, Bounds]]:
    active_logger = logger or logging.getLogger(__name__)
    if not config_path.is_file():
        raise FileNotFoundError(f"参数范围配置文件不存在：{config_path}")

    try:
        raw_config = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"参数范围配置文件不是合法 JSON：{config_path}") from exc
    if not isinstance(raw_config, dict):
        raise TypeError("参数范围配置文件的顶层必须是 JSON object")

    raw_control_ranges = _get_config_section(raw_config, "control_parameter_ranges")
    raw_device_ranges = _get_config_section(raw_config, "device_control_ranges")
    raw_circuit_overrides = _get_config_section(raw_config, "circuit_parameter_overrides")

    control_ranges: dict[str, Bounds] = {}
    for control_parameter, raw_bounds in raw_control_ranges.items():
        if not isinstance(control_parameter, str):
            raise TypeError("控制参数名称必须是字符串")
        normalized_control = control_parameter.upper()
        if normalized_control in control_ranges:
            raise ValueError(f"控制参数范围重复：{normalized_control}")
        control_ranges[normalized_control] = _parse_bounds(raw_bounds, normalized_control)
    if not control_ranges:
        raise ValueError("control_parameter_ranges 不能为空")

    device_ranges: dict[DeviceControlKey, Bounds] = {}
    for raw_key, raw_bounds in raw_device_ranges.items():
        if not isinstance(raw_key, str):
            raise TypeError("device_control_ranges 的键必须是字符串")
        if raw_key.count(".") != 1:
            raise ValueError(f"器件范围键 {raw_key!r} 必须使用 DEVICE_TYPE.CONTROL_PARAMETER 格式")

        device_type, control_parameter = raw_key.split(".", maxsplit=1)
        normalized_key = (device_type.upper(), control_parameter.upper())
        if normalized_key[0] not in SUPPORTED_DEVICE_TYPES:
            raise ValueError(
                f"不支持的器件类型 {normalized_key[0]!r}，当前支持：{sorted(SUPPORTED_DEVICE_TYPES)}"
            )
        if normalized_key in device_ranges:
            raise ValueError(f"器件范围重复：{raw_key}")
        device_ranges[normalized_key] = _parse_bounds(raw_bounds, raw_key)

    raw_overrides = raw_circuit_overrides.get(circuit_name, {})
    if not isinstance(raw_overrides, dict):
        raise TypeError(f"电路 {circuit_name!r} 的参数覆盖必须是 JSON object")

    overrides: dict[str, Bounds] = {}
    normalized_override_names: set[str] = set()
    for parameter_name, raw_bounds in raw_overrides.items():
        if not isinstance(parameter_name, str):
            raise TypeError("参数覆盖名称必须是字符串")
        normalized_name = parameter_name.casefold()
        if normalized_name in normalized_override_names:
            raise ValueError(f"参数覆盖重复：{parameter_name}")
        normalized_override_names.add(normalized_name)
        overrides[parameter_name] = _parse_bounds(raw_bounds, f"{circuit_name}.{parameter_name}")

    active_logger.debug(
        "参数范围配置读取完成：control=%d, device=%d, override=%d",
        len(control_ranges),
        len(device_ranges),
        len(overrides),
    )
    return control_ranges, device_ranges, overrides


@dataclass(frozen=True)
class SamplingResult:
    target_path: Path
    database_path: Path
    design_csv_path: Path
    metrics_csv_path: Path
    run_id: str
    requested_num: int
    random_num: int
    lhs_num: int
    sobol_num: int
    failed_num: int
    duplicate_skipped_num: int
    success: bool


class Sampling_Controller:
    def __init__(
        self,
        src_path: Path,
        circuit_name: str,
        circuit_type: str,
        target_path: Path,
        metrics: Sequence[str],
        simulation_condition_path: Optional[Path] = None,
        seed: int = 42,
        parameter_aliases: Optional[Mapping[str, str]] = None,
        device_rules: Sequence[DeviceRule] = DEFAULT_DEVICE_RULES,
        log_level: int = logging.INFO,
        console_log: bool = True,
        ngspice_command: str = "ngspice",
        simulation_timeout_seconds: Optional[float] = 300.0,
        keep_workspace: bool = False,
        max_duplicate_rounds: int = 50,
    ) -> None:
        if not isinstance(circuit_name, str) or not circuit_name.strip():
            raise ValueError("circuit_name 不能为空")
        if Path(circuit_name).name != circuit_name or circuit_name in {".", ".."}:
            raise ValueError("circuit_name 不能包含路径分隔符")
        if isinstance(max_duplicate_rounds, bool) or not isinstance(max_duplicate_rounds, int):
            raise TypeError("max_duplicate_rounds 必须是整数")
        if max_duplicate_rounds <= 0:
            raise ValueError("max_duplicate_rounds 必须大于 0")

        self.src_path = Path(src_path)
        self.circuit_name = circuit_name
        self.circuit_type = circuit_type
        self.target_path = Path(target_path).resolve()
        self.metrics = list(metrics)
        self.seed = seed
        self.parameter_aliases = dict(parameter_aliases or {})
        self.device_rules = tuple(device_rules)
        self.parameter_range_config_path = DEFAULT_PARAMETER_RANGE_CONFIG_PATH
        self.max_duplicate_rounds = max_duplicate_rounds
        self.log_level = log_level
        self.console_log = console_log
        self.log_path: Optional[Path] = None

        logger_name = f"analog_agent.sampling.{self.circuit_name}.{uuid.uuid4().hex}"
        self.logger = create_logger(logger_name, level=log_level, console=console_log)

        try:
            self._find_history()
            self.log_path = self.src_path / "logs" / "sampling.log"
            add_rotating_file_handler(self.logger, self.log_path, level=log_level)
            self.logger.info(
                "开始初始化采样控制器：circuit=%s, type=%s, history=%s",
                self.circuit_name,
                self.circuit_type,
                self.has_history,
            )

            parser_logger = get_child_logger(self.logger, "parser")
            analyzer_logger = get_child_logger(self.logger, "analyzer")
            self.parameter_name_lst = read_parameter_names(self.parameter_path, logger=parser_logger)
            self.parameter_spec_lst: list[ParameterSpec] = analyze_parameter_usage(
                circuit_paths=self.circuit_path,
                parameter_name_lst=self.parameter_name_lst,
                parameter_aliases=self.parameter_aliases,
                device_rules=self.device_rules,
                logger=analyzer_logger,
            )
            (
                self.control_parameter_ranges,
                self.device_control_ranges,
                self.parameter_overrides,
            ) = _load_parameter_range_config(
                self.parameter_range_config_path,
                self.circuit_name,
                logger=analyzer_logger,
            )
            self.bounds: list[Bounds] = resolve_parameter_bounds(
                self.parameter_spec_lst,
                self.control_parameter_ranges,
                self.device_control_ranges,
                self.parameter_overrides,
                logger=analyzer_logger,
            )

            self.random_sampler = Random_Sampler(
                self.parameter_path,
                self.parameter_name_lst,
                self.bounds,
                seed,
                logger=get_child_logger(self.logger, "sampler.random"),
            )
            self.lhs_sampler = LHS_Sampler(
                self.parameter_path,
                self.parameter_name_lst,
                self.bounds,
                seed,
                logger=get_child_logger(self.logger, "sampler.lhs"),
            )
            self.sobol_sampler = Sobol_Sampler(
                self.parameter_path,
                self.parameter_name_lst,
                self.bounds,
                seed,
                logger=get_child_logger(self.logger, "sampler.sobol"),
            )
            self.simulator = Simulator(
                metrics=self.metrics,
                circuit_type=self.circuit_type,
                circuit_name=self.circuit_name,
                simulate_condition_path=simulation_condition_path,
                output_path=self.target_path,
                ngspice_command=ngspice_command,
                timeout_seconds=simulation_timeout_seconds,
                keep_workspace=keep_workspace,
                logger=get_child_logger(self.logger, "simulator"),
            )
            self.history_store = SamplingHistoryStore(
                circuit_path=self.src_path,
                circuit_name=self.circuit_name,
                circuit_type=self.circuit_type,
                parameter_names=self.parameter_name_lst,
                metric_names=self.simulator.metrics,
                logger=get_child_logger(self.logger, "history"),
            )
            self.logger.info(
                "采样控制器初始化完成：parameters=%d, metrics=%s, seed=%s",
                len(self.parameter_name_lst),
                self.metrics,
                self.seed,
            )
        except Exception:
            self.logger.exception("采样控制器初始化失败：circuit=%s", self.circuit_name)
            raise

    def _set_circuit_paths(self) -> None:
        self.circuit_path = self.src_path / f"{self.circuit_name}.sp"
        self.parameter_path = self.src_path / f"{self.circuit_name}_params.sp"

    def _validate_circuit_directory(self, path: Path, label: str) -> None:
        if not path.is_dir():
            raise NotADirectoryError(f"{label}不存在：{path}")
        circuit_path = path / f"{self.circuit_name}.sp"
        parameter_path = path / f"{self.circuit_name}_params.sp"
        if not circuit_path.is_file():
            raise FileNotFoundError(f"{label}中不存在电路文件：{circuit_path}")
        if not parameter_path.is_file():
            raise FileNotFoundError(f"{label}中不存在参数文件：{parameter_path}")

    def _find_history(self) -> None:
        source_path = self.src_path.resolve()
        history_path = (self.target_path / self.circuit_name).resolve()

        if history_path.exists():
            self._validate_circuit_directory(history_path, "历史电路目录")
            if source_path != history_path and source_path.exists():
                self.logger.warning("历史目录已存在，本次传入的 src_path 将被忽略：%s", source_path)
            self.has_history = True
            self.src_path = history_path
            self.logger.info("使用历史电路目录：%s", history_path)
        else:
            self._validate_circuit_directory(source_path, "原始电路目录")
            if source_path in history_path.parents:
                raise ValueError(
                    "历史数据库目录不能位于原始电路目录内部："
                    f"source={source_path}, target={history_path}"
                )
            self.target_path.mkdir(parents=True, exist_ok=True)
            self.logger.info("移动电路目录到历史数据库：%s -> %s", source_path, history_path)
            moved_path = Path(shutil.move(str(source_path), str(history_path))).resolve()
            if moved_path != history_path or source_path.exists():
                raise RuntimeError(
                    "电路目录移动结果异常："
                    f"expected={history_path}, actual={moved_path}, source_exists={source_path.exists()}"
                )
            self.has_history = False
            self.src_path = history_path

        self._set_circuit_paths()
        if not self.parameter_range_config_path.is_file():
            raise FileNotFoundError(f"参数范围配置文件不存在：{self.parameter_range_config_path}")

    def _split_number(self, n_points: int) -> Tuple[int, int, int]:
        if isinstance(n_points, bool) or not isinstance(n_points, int):
            raise TypeError("n_points 必须是整数")
        if n_points < 3:
            raise ValueError("n_points 必须至少为 3，确保三种采样方法都有采样点")

        ideal_sobol_num = n_points / 3
        lower_power = 2 ** math.floor(math.log2(ideal_sobol_num))
        upper_power = lower_power * 2
        lower_distance = ideal_sobol_num - lower_power
        upper_distance = upper_power - ideal_sobol_num
        sobol_num = (
            upper_power
            if upper_distance < lower_distance and n_points - upper_power >= 2
            else lower_power
        )
        remaining_num = n_points - sobol_num
        random_num = remaining_num // 2
        lhs_num = remaining_num - random_num
        self.logger.info(
            "采样数量划分：total=%d, random=%d, lhs=%d, sobol=%d",
            n_points,
            random_num,
            lhs_num,
            sobol_num,
        )
        return random_num, lhs_num, sobol_num

    @staticmethod
    def _next_power_of_two(value: int) -> int:
        return 1 if value <= 1 else 1 << (value - 1).bit_length()

    def _generate_unique_points(
        self,
        sampler: Any,
        method: str,
        target_count: int,
        n_workers: int,
        accepted_keys: set[str],
    ) -> tuple[np.ndarray, int]:
        accepted_rows: list[np.ndarray] = []
        skipped_count = 0

        for round_index in range(1, self.max_duplicate_rounds + 1):
            remaining = target_count - len(accepted_rows)
            if remaining == 0:
                break
            batch_size = self._next_power_of_two(remaining) if method == "sobol" else remaining
            candidates = np.asarray(
                sampler.generate_sample_point(batch_size, n_workers),
                dtype=float,
            )
            if candidates.ndim != 2 or candidates.shape[1] != len(self.parameter_name_lst):
                raise RuntimeError(f"{method} 采样器返回了错误形状：{candidates.shape}")

            candidate_keys = [self.history_store.design_key(row) for row in candidates]
            historical_keys = self.history_store.find_existing_keys(candidate_keys)
            accepted_this_round = 0

            for row, design_key in zip(candidates, candidate_keys):
                if design_key in historical_keys or design_key in accepted_keys:
                    skipped_count += 1
                    continue
                accepted_rows.append(row.copy())
                accepted_keys.add(design_key)
                accepted_this_round += 1
                if len(accepted_rows) == target_count:
                    break

            self.logger.debug(
                "去重补点：method=%s, round=%d, generated=%d, accepted=%d, remaining=%d",
                method,
                round_index,
                len(candidates),
                accepted_this_round,
                target_count - len(accepted_rows),
            )

        if len(accepted_rows) != target_count:
            raise RuntimeError(
                f"{method} 在 {self.max_duplicate_rounds} 轮内无法补足唯一采样点："
                f"required={target_count}, actual={len(accepted_rows)}。"
                "参数空间可能已经耗尽，请扩大范围或减小采样数量。"
            )

        result = np.vstack(accepted_rows)
        self.logger.info(
            "%s 唯一采样点生成完成：points=%d, duplicate_skipped=%d",
            method,
            len(result),
            skipped_count,
        )
        return result, skipped_count

    def sample(
        self,
        n_points: int,
        n_workers: int,
        continue_on_error: bool = True,
    ) -> SamplingResult:
        if isinstance(n_points, bool) or not isinstance(n_points, int):
            raise TypeError("n_points 必须是整数")
        if n_points < 3:
            raise ValueError("n_points 必须至少为 3")
        if isinstance(n_workers, bool) or not isinstance(n_workers, int):
            raise TypeError("n_workers 必须是整数")
        if n_workers <= 0:
            raise ValueError("n_workers 必须大于 0")
        if not isinstance(continue_on_error, bool):
            raise TypeError("continue_on_error 必须是 bool")

        random_num, lhs_num, sobol_num = self._split_number(n_points)
        allocation = {"random": random_num, "lhs": lhs_num, "sobol": sobol_num}
        run_id = self.history_store.create_run(
            requested_points=n_points,
            n_workers=n_workers,
            allocation=allocation,
            config={
                "seed": self.seed,
                "continue_on_error": continue_on_error,
                "bounds": self.bounds,
                "raw_metrics": self.metrics,
            },
        )
        run_finalized = False
        self.logger.info("开始采样运行：run_id=%s, points=%d", run_id, n_points)

        try:
            accepted_keys: set[str] = set()
            random_points, random_skipped = self._generate_unique_points(
                self.random_sampler, "random", random_num, n_workers, accepted_keys
            )
            lhs_points, lhs_skipped = self._generate_unique_points(
                self.lhs_sampler, "lhs", lhs_num, n_workers, accepted_keys
            )
            sobol_points, sobol_skipped = self._generate_unique_points(
                self.sobol_sampler, "sobol", sobol_num, n_workers, accepted_keys
            )

            all_sample_points = np.vstack([random_points, lhs_points, sobol_points])
            sampling_methods = (
                ["random"] * random_num
                + ["lhs"] * lhs_num
                + ["sobol"] * sobol_num
            )
            if all_sample_points.shape != (n_points, len(self.parameter_name_lst)):
                raise RuntimeError(
                    "最终采样点形状不正确："
                    f"expected={(n_points, len(self.parameter_name_lst))}, actual={all_sample_points.shape}"
                )

            simulation_result = self.simulator.simulate_batch(
                circuit_path=self.src_path,
                n_workers=n_workers,
                design_parameters_array=all_sample_points,
                continue_on_error=continue_on_error,
            )
            failed_num = len(simulation_result.failure_records)
            self.history_store.write_batch(
                run_id=run_id,
                design_parameters=all_sample_points,
                metrics=simulation_result.metrics,
                sampling_methods=sampling_methods,
                failure_records=simulation_result.failure_records,
            )
            self.history_store.mark_run_completed(run_id, failed_num)
            run_finalized = True
            self.history_store.export_csv()

            duplicate_skipped_num = random_skipped + lhs_skipped + sobol_skipped
            self.logger.info(
                "采样运行完成：run_id=%s, persisted=%d, failed=%d, duplicate_skipped=%d",
                run_id,
                n_points,
                failed_num,
                duplicate_skipped_num,
            )
            return SamplingResult(
                target_path=self.src_path,
                database_path=self.history_store.database_path,
                design_csv_path=self.history_store.design_csv_path,
                metrics_csv_path=self.history_store.metrics_csv_path,
                run_id=run_id,
                requested_num=n_points,
                random_num=random_num,
                lhs_num=lhs_num,
                sobol_num=sobol_num,
                failed_num=failed_num,
                duplicate_skipped_num=duplicate_skipped_num,
                success=failed_num == 0,
            )
        except Exception as exc:
            if not run_finalized:
                self.history_store.mark_run_failed(run_id, exc)
            self.logger.exception("电路采样失败：run_id=%s, circuit=%s", run_id, self.circuit_name)
            raise

    def close(self) -> None:
        close_logger(self.logger)

    def __enter__(self) -> "Sampling_Controller":
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()
