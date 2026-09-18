from __future__ import annotations

import json
import logging
import math
import shutil

import numpy as np

from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Mapping, Optional, Sequence, List, Tuple
from random_sampling import Random_Sampler
from lhs_sampling import LHS_Sampler
from sobol_sampling import Sobol_Sampler
from simulating import Simulator
from dataclasses import dataclass

from ..utils import (
    Bounds,
    DEFAULT_DEVICE_RULES,
    SUPPORTED_DEVICE_TYPES,
    DeviceRule,
    ParameterSpec,
    analyze_parameter_usage,
    read_parameter_names,
    resolve_parameter_bounds,
)

__all__ = ["Sampling_Controller"]


DeviceControlKey = tuple[str, str]

DEFAULT_PARAMETER_RANGE_CONFIG_PATH = (
    Path(__file__).resolve().parent / "parameter_ranges.json"
)


def _parse_bounds(raw_bounds: object, rule_name: str) -> Bounds:
    """
    将 JSON 中的：

    [lower_bound, upper_bound, step]

    转换成：

    (lower_bound, upper_bound, step)
    """

    if not isinstance(raw_bounds, (list, tuple)) or len(raw_bounds) != 3:
        raise ValueError(
            f"范围规则 {rule_name!r} 必须是 "
            "[lower_bound, upper_bound, step]"
        )

    if any(
        isinstance(value, bool) or not isinstance(value, (int, float))
        for value in raw_bounds
    ):
        raise TypeError(f"范围规则 {rule_name!r} 中的值必须是数值")

    lower_bound, upper_bound, step = map(float, raw_bounds)

    if not all(math.isfinite(value) for value in (lower_bound, upper_bound, step)):
        raise ValueError(f"范围规则 {rule_name!r} 必须使用有限数值")

    if lower_bound >= upper_bound:
        raise ValueError(
            f"范围规则 {rule_name!r} 的 lower_bound 必须小于 upper_bound"
        )

    if step <= 0:
        raise ValueError(f"范围规则 {rule_name!r} 的 step 必须大于 0")

    return lower_bound, upper_bound, step


def _get_config_section(
    raw_config: dict,
    section_name: str,
) -> dict:
    section = raw_config.get(section_name, {})

    if not isinstance(section, dict):
        raise TypeError(f"{section_name} 必须是 JSON object")

    return section


def _load_parameter_range_config(
    config_path: Path,
    circuit_name: str,
) -> tuple[
    dict[str, Bounds],
    dict[DeviceControlKey, Bounds],
    dict[str, Bounds],
]:
    """
    从 parameter_ranges.json 中读取：

    1. 通用控制参数范围；
    2. 器件类型与控制参数范围；
    3. 当前电路的单独参数范围。
    """

    if not config_path.is_file():
        raise FileNotFoundError(f"参数范围配置文件不存在：{config_path}")

    try:
        raw_config = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"参数范围配置文件不是合法 JSON：{config_path}"
        ) from exc

    if not isinstance(raw_config, dict):
        raise TypeError("参数范围配置文件的顶层必须是 JSON object")

    raw_control_ranges = _get_config_section(
        raw_config,
        "control_parameter_ranges",
    )

    raw_device_ranges = _get_config_section(
        raw_config,
        "device_control_ranges",
    )

    raw_circuit_overrides = _get_config_section(
        raw_config,
        "circuit_parameter_overrides",
    )

    # ========================================================
    # 通用控制参数范围
    #
    # "W": [lower, upper, step]
    # "L": [lower, upper, step]
    # "R": [lower, upper, step]
    # "C": [lower, upper, step]
    # ========================================================

    control_parameter_ranges: dict[str, Bounds] = {}

    for control_parameter, raw_bounds in raw_control_ranges.items():
        if not isinstance(control_parameter, str):
            raise TypeError("控制参数名称必须是字符串")

        normalized_control = control_parameter.upper()

        if normalized_control in control_parameter_ranges:
            raise ValueError(f"控制参数范围重复：{normalized_control}")

        control_parameter_ranges[normalized_control] = _parse_bounds(
            raw_bounds,
            normalized_control,
        )

    if not control_parameter_ranges:
        raise ValueError("control_parameter_ranges 不能为空")

    # ========================================================
    # 器件类型 + 控制参数范围
    #
    # JSON:
    # "NMOS.W": [lower, upper, step]
    #
    # Python:
    # ("NMOS", "W"): (lower, upper, step)
    # ========================================================

    device_control_ranges: dict[DeviceControlKey, Bounds] = {}

    for raw_key, raw_bounds in raw_device_ranges.items():
        if not isinstance(raw_key, str):
            raise TypeError("device_control_ranges 的键必须是字符串")

        if raw_key.count(".") != 1:
            raise ValueError(
                f"器件范围键 {raw_key!r} 必须使用 "
                "DEVICE_TYPE.CONTROL_PARAMETER 格式"
            )

        device_type, control_parameter = raw_key.split(".", maxsplit=1)

        normalized_device_type = device_type.upper()
        normalized_control = control_parameter.upper()

        if normalized_device_type not in SUPPORTED_DEVICE_TYPES:
            raise ValueError(
                f"不支持的器件类型 {normalized_device_type!r}，"
                f"当前支持：{sorted(SUPPORTED_DEVICE_TYPES)}"
            )

        normalized_key = (
            normalized_device_type,
            normalized_control,
        )

        if normalized_key in device_control_ranges:
            raise ValueError(f"器件范围重复：{raw_key}")

        device_control_ranges[normalized_key] = _parse_bounds(
            raw_bounds,
            raw_key,
        )

    # ========================================================
    # 当前电路的单参数覆盖
    #
    # "circuit_parameter_overrides": {
    #     "five_t_ota": {
    #         "WTAIL_VAL": [1.0, 50.0, 0.5]
    #     }
    # }
    # ========================================================

    raw_parameter_overrides = raw_circuit_overrides.get(circuit_name, {})

    if not isinstance(raw_parameter_overrides, dict):
        raise TypeError(
            f"电路 {circuit_name!r} 的参数覆盖必须是 JSON object"
        )

    parameter_overrides: dict[str, Bounds] = {}

    for parameter_name, raw_bounds in raw_parameter_overrides.items():
        if not isinstance(parameter_name, str):
            raise TypeError("参数覆盖名称必须是字符串")

        normalized_parameter_name = parameter_name.casefold()

        if normalized_parameter_name in {
            name.casefold() for name in parameter_overrides
        }:
            raise ValueError(f"参数覆盖重复：{parameter_name}")

        parameter_overrides[parameter_name] = _parse_bounds(
            raw_bounds,
            f"{circuit_name}.{parameter_name}",
        )

    return (
        control_parameter_ranges,
        device_control_ranges,
        parameter_overrides,
    )
    
@dataclass
class SamplingResult:
    
    target_path: Optional[Path] = None
    random_num: Optional[int] = None
    lhs_num: Optional[int] = None
    sobol_num: Optional[int] = None
    success: bool = False


class Sampling_Controller:

    def __init__(
        self,
        src_path: Path,
        circuit_name: str,
        circuit_type: str,
        target_path: Path,
        metrics: List[str],
        simulation_condition_path: Optional[Path] = None, 
        seed: int = 42,
        parameter_aliases: Optional[Mapping[str, str]] = None, # 用于解决参数文件和电路文件中的参数名称不一致。
        device_rules: Sequence[DeviceRule] = DEFAULT_DEVICE_RULES, # 用于根据模型名称判断器件类型
        log_level: int = logging.INFO,
        console_log: bool = True,
    ) -> None:
        self.src_path = Path(src_path)
        self.circuit_name = circuit_name
        self.circuit_type = circuit_type
        self.target_path = Path(target_path)
        self.metrics = list(metrics)
        self.log_level = log_level
        self.console_log = console_log
        self.log_path: Optional[Path] = None
        self.logger = self._create_logger()

        self.parameter_path = self.src_path / f"{self.circuit_name}_params.sp"
        self.circuit_path = self.src_path / f"{self.circuit_name}.sp"

        self.parameter_range_config_path = DEFAULT_PARAMETER_RANGE_CONFIG_PATH

        self.parameter_aliases = dict(parameter_aliases or {})
        self.device_rules = tuple(device_rules)

        try:
            self._find_history()
            self._add_file_handler()
            self.logger.info("开始初始化采样控制器：circuit=%s, type=%s", self.circuit_name, self.circuit_type)
            self.logger.info("电路工作目录：%s", self.src_path)
            self.logger.info("历史状态：%s", "已存在" if self.has_history else "新建")

            self._validate_input_paths()

            # 1. 读取参数名称
            self.parameter_name_lst = read_parameter_names(self.parameter_path)
            self.logger.info("读取到 %d 个电路参数", len(self.parameter_name_lst))
            self.logger.debug("参数名称：%s", self.parameter_name_lst)

            # 2. 判断每个参数控制的器件类型和控制属性
            self.parameter_spec_lst: list[ParameterSpec] = analyze_parameter_usage(
                circuit_paths=self.circuit_path,
                parameter_name_lst=self.parameter_name_lst,
                parameter_aliases=self.parameter_aliases,
                device_rules=self.device_rules,
            )
            self.logger.info("电路参数用途分析完成")
            self.logger.debug("参数用途：%s", self.parameter_spec_lst)

            # 3. 从 sample_optimize/parameter_ranges.json 读取范围
            (
                self.control_parameter_ranges,
                self.device_control_ranges,
                self.parameter_overrides,
            ) = _load_parameter_range_config(
                config_path=self.parameter_range_config_path,
                circuit_name=self.circuit_name,
            )
            self.logger.info("参数范围配置读取完成：%s", self.parameter_range_config_path)

            # 4. 得到与 parameter_name_lst 顺序一致的 bounds
            self.bounds: list[Bounds] = resolve_parameter_bounds(
                parameter_specs=self.parameter_spec_lst,
                control_parameter_ranges=self.control_parameter_ranges,
                device_control_ranges=self.device_control_ranges,
                parameter_overrides=self.parameter_overrides,
            )
            self.logger.info("已解析 %d 组参数范围", len(self.bounds))
            self.logger.debug("参数范围：%s", dict(zip(self.parameter_name_lst, self.bounds)))

            self.random_sampler = Random_Sampler(
                self.parameter_path,
                self.parameter_name_lst,
                self.bounds,
                seed,
            )

            self.lhs_sampler = LHS_Sampler(
                self.parameter_path,
                self.parameter_name_lst,
                self.bounds,
                seed,
            )

            self.sobol_sampler = Sobol_Sampler(
                self.parameter_path,
                self.parameter_name_lst,
                self.bounds,
                seed,
            )
            self.simulator = Simulator(self.metrics, self.circuit_type, self.circuit_name, output_path=self.target_path)
            self.logger.info("采样控制器初始化完成：metrics=%s, seed=%d", self.metrics, seed)
        except Exception:
            self.logger.exception("采样控制器初始化失败：circuit=%s", self.circuit_name)
            raise

    def _create_logger(self) -> logging.Logger:
        logger = logging.getLogger(f"{__name__}.{self.circuit_name}.{id(self)}")
        logger.setLevel(self.log_level)
        logger.propagate = False

        if self.console_log:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(self.log_level)
            console_handler.setFormatter(self._get_log_formatter())
            logger.addHandler(console_handler)
        else:
            logger.addHandler(logging.NullHandler())

        return logger

    @staticmethod
    def _get_log_formatter() -> logging.Formatter:
        return logging.Formatter(
            fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    def _add_file_handler(self) -> None:
        log_directory = self.src_path / "logs"
        log_directory.mkdir(parents=True, exist_ok=True)
        self.log_path = log_directory / "sampling_controller.log"

        file_handler = RotatingFileHandler(
            filename=self.log_path,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(self.log_level)
        file_handler.setFormatter(self._get_log_formatter())
        self.logger.addHandler(file_handler)

    def _validate_input_paths(self) -> None:
        self.logger.debug("开始检查输入路径")

        if not self.src_path.is_dir():
            raise NotADirectoryError(f"电路目录不存在：{self.src_path}")

        if not self.parameter_path.is_file():
            raise FileNotFoundError(f"参数文件不存在：{self.parameter_path}")

        if not self.circuit_path.is_file():
            raise FileNotFoundError(f"电路文件不存在：{self.circuit_path}")

        if not self.parameter_range_config_path.is_file():
            raise FileNotFoundError(
                f"参数范围配置文件不存在：{self.parameter_range_config_path}"
            )

        self.logger.info("输入路径检查完成")
    
    def _find_history(self) -> None:
        """
        如果历史电路目录存在，直接使用历史目录。

        如果不存在，将 src_path 整体移动到：
            target_path / circuit_name

        移动成功后，原始 src_path 自动删除。
        """

        source_path = self.src_path.resolve()
        history_path = (self.target_path / self.circuit_name).resolve()

        if history_path.exists():
            if not history_path.is_dir():
                raise NotADirectoryError(
                    f"历史路径存在，但不是文件夹：{history_path}"
                )

            self.logger.info("发现历史电路目录：%s", history_path)
            self.has_history = True
            self.src_path = history_path

        else:
            if not source_path.is_dir():
                raise NotADirectoryError(f"原始电路目录不存在：{source_path}")

            if source_path in history_path.parents:
                raise ValueError(
                    "历史数据库目录不能位于原始电路目录内部："
                    f"source={source_path}, target={history_path}"
                )

            self.target_path.mkdir(parents=True, exist_ok=True)

            self.logger.info("未发现历史电路目录，开始移动：%s -> %s", source_path, history_path)

            # 将整个源目录移动到数据库目录。
            # 成功后 source_path 自动消失。
            moved_path = shutil.move(
                str(source_path),
                str(history_path),
            )

            moved_path = Path(moved_path).resolve()

            if moved_path != history_path:
                raise RuntimeError(
                    "电路目录移动后的路径与预期不一致："
                    f"expected={history_path}, actual={moved_path}"
                )

            if source_path.exists():
                raise RuntimeError(
                    f"电路目录移动后，原始目录仍然存在：{source_path}"
                )

            self.has_history = False
            self.src_path = history_path
            self.logger.info("电路目录移动完成：%s", history_path)

        self.circuit_path = self.src_path / f"{self.circuit_name}.sp"
        self.parameter_path = self.src_path / f"{self.circuit_name}_params.sp"

        if not self.circuit_path.is_file():
            raise FileNotFoundError(
                f"数据库目录中不存在电路文件：{self.circuit_path}"
            )

        if not self.parameter_path.is_file():
            raise FileNotFoundError(
                f"数据库目录中不存在参数文件：{self.parameter_path}"
            )
            
    def _split_number(self, n_points: int) -> Tuple[int, int, int]:
        """
        将总采样数划分给 Random、LHS 和 Sobol。

        Sobol 的采样数必须是 2 的幂，Random 和 LHS
        平均分配剩余采样数。

        Returns:
            (random_num, lhs_num, sobol_num)
        """

        if isinstance(n_points, bool) or not isinstance(n_points, int):
            raise TypeError("n_points 必须是整数")

        if n_points < 3:
            raise ValueError("n_points 必须至少为 3，确保三种采样方法都有采样点")

        ideal_sobol_num = n_points / 3

        lower_exponent = math.floor(math.log2(ideal_sobol_num))
        lower_power = 2 ** lower_exponent
        upper_power = lower_power * 2

        lower_distance = ideal_sobol_num - lower_power
        upper_distance = upper_power - ideal_sobol_num

        # 选择较大的 2 次幂后，Random 和 LHS 必须至少各保留一个采样点。
        upper_power_available = n_points - upper_power >= 2

        if upper_distance < lower_distance and upper_power_available:
            sobol_num = upper_power
        else:
            sobol_num = lower_power

        remaining_num = n_points - sobol_num
        random_num = remaining_num // 2
        lhs_num = remaining_num - random_num

        self.logger.info(
            "采样数量划分完成：total=%d, random=%d, lhs=%d, sobol=%d",
            n_points,
            random_num,
            lhs_num,
            sobol_num,
        )

        return random_num, lhs_num, sobol_num
            
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

        self.logger.info(
            "准备开始采样：n_points=%d, n_workers=%d",
            n_points,
            n_workers,
        )

        try:
            random_num, lhs_num, sobol_num = self._split_number(n_points)

            self.logger.info(
                "采样数量划分：Random=%d, LHS=%d, Sobol=%d",
                random_num,
                lhs_num,
                sobol_num,
            )

            random_sample_points = self.random_sampler.generate_sample_point(
                random_num,
                n_workers,
            )

            lhs_sample_points = self.lhs_sampler.generate_sample_point(
                lhs_num,
            )

            sobol_sample_points = self.sobol_sampler.generate_sample_point(
                sobol_num,
            )

            all_sample_points = np.vstack(
                [
                    random_sample_points,
                    lhs_sample_points,
                    sobol_sample_points,
                ]
            )

            if all_sample_points.shape[0] != n_points:
                raise RuntimeError(
                    "最终采样点数量不正确："
                    f"expected={n_points}, actual={all_sample_points.shape[0]}"
                )

            self.logger.info(
                "采样点生成完成：shape=%s",
                all_sample_points.shape,
            )

            sample_results = self.simulator.simulate(
                circuit_path=self.src_path,
                n_workers=n_workers,
                design_parameters_array=all_sample_points,
                continue_on_error=continue_on_error,
            )

            self.logger.info(
                "SPICE 仿真完成：shape=%s",
                sample_results.shape,
            )

            self.simulator.write_simulate_result(
                design_parameters=all_sample_points,
                metrics=sample_results,
                design_parameter_name_lst=self.parameter_name_lst,
            )

            result_path = self.target_path / self.circuit_name

            self.logger.info(
                "采样结果保存完成：%s",
                result_path,
            )

            return SamplingResult(
                target_path=result_path,
                random_num=random_num,
                lhs_num=lhs_num,
                sobol_num=sobol_num,
                success=True,
            )

        except Exception:
            self.logger.exception(
                "电路采样失败：circuit=%s",
                self.circuit_name,
            )
            raise