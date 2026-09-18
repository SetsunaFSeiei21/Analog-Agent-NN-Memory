from __future__ import annotations

import math
import re

from dataclasses import dataclass
from pathlib import Path
from typing import (
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Union,
)

from .spice_parser import (
    SpiceInstance,
    expression_contains_parameter,
    parse_spice_instances,
)


Bounds = Tuple[float, float, float]

DeviceControlKey = Tuple[str, str]


SUPPORTED_DEVICE_TYPES = frozenset(
    {
        "NMOS",
        "PMOS",
        "RESISTOR",
        "CAPACITOR",
    }
)


@dataclass(frozen=True)
class DeviceRule:
    """
    根据实例前缀和模型名称识别器件类型。

    instance_prefixes:
        允许的 SPICE 实例前缀，例如 ("M", "X")

    device_type:
        NMOS、PMOS、RESISTOR 或 CAPACITOR

    model_pattern:
        用于匹配模型名称的正则表达式
    """

    instance_prefixes: Tuple[str, ...]

    device_type: str

    model_pattern: str

    def __post_init__(self) -> None:

        normalized_device_type = (
            self.device_type.upper()
        )

        if (
            normalized_device_type
            not in SUPPORTED_DEVICE_TYPES
        ):
            raise ValueError(
                f"不支持的器件类型："
                f"{self.device_type}，"
                f"当前支持："
                f"{sorted(SUPPORTED_DEVICE_TYPES)}"
            )

    def matches(
        self,
        instance: SpiceInstance,
    ) -> bool:

        normalized_prefixes = {
            prefix.upper()
            for prefix in self.instance_prefixes
        }

        if (
            instance.instance_prefix
            not in normalized_prefixes
        ):
            return False

        if instance.model_name is None:
            return False

        return (
            re.search(
                self.model_pattern,
                instance.model_name,
                flags=re.IGNORECASE,
            )
            is not None
        )


# ============================================================
# 默认器件模型识别规则
#
# 对于其他 PDK，可以在调用时将自定义规则放在这些规则前面。
# ============================================================

DEFAULT_DEVICE_RULES: Tuple[
    DeviceRule,
    ...
] = (

    DeviceRule(
        instance_prefixes=("M", "X"),
        device_type="PMOS",
        model_pattern=r"pfet|pmos|pch",
    ),

    DeviceRule(
        instance_prefixes=("M", "X"),
        device_type="NMOS",
        model_pattern=r"nfet|nmos|nch",
    ),

    DeviceRule(
        instance_prefixes=("X",),
        device_type="RESISTOR",
        model_pattern=(
            r"resistor|res|rpoly|rdiff"
        ),
    ),

    DeviceRule(
        instance_prefixes=("X",),
        device_type="CAPACITOR",
        model_pattern=(
            r"capacitor|cap|mim|mom"
        ),
    ),
)


@dataclass(frozen=True)
class ParameterUsage:
    """
    参数在某一个器件实例中的使用信息。
    """

    instance_name: str

    device_type: str

    model_name: Optional[str]

    control_parameter: str

    source_path: Path

    line_number: int


@dataclass(frozen=True)
class ParameterSpec:
    """
    一个设计参数经过分析后得到的统一信息。
    """

    parameter_name: str

    circuit_parameter_name: str

    device_type: str

    control_parameter: str

    usages: Tuple[
        ParameterUsage,
        ...
    ]


def _classify_device(
    instance: SpiceInstance,
    device_rules: Sequence[DeviceRule],
) -> Optional[str]:
    """
    判断器件属于：

    NMOS
    PMOS
    RESISTOR
    CAPACITOR
    """

    # 原生 SPICE 电阻：
    #
    # R1 node1 node2 value
    if instance.instance_prefix == "R":
        return "RESISTOR"

    # 原生 SPICE 电容：
    #
    # C1 node1 node2 value
    if instance.instance_prefix == "C":
        return "CAPACITOR"

    # M 和 X 实例通过模型名称判断
    for device_rule in device_rules:

        if device_rule.matches(instance):

            return (
                device_rule
                .device_type
                .upper()
            )

    return None


def _canonicalize_control_parameter(
    device_type: str,
    control_parameter: str,
) -> str:
    """
    统一控制参数名称。

    WIDTH       -> W
    LENGTH      -> L

    对于电阻：
        VALUE、RES、RESISTANCE -> R

    对于电容：
        VALUE、CAP、CAPACITANCE -> C
    """

    normalized_control = (
        control_parameter.upper()
    )

    common_aliases = {
        "WIDTH": "W",
        "LENGTH": "L",
    }

    normalized_control = (
        common_aliases.get(
            normalized_control,
            normalized_control,
        )
    )

    if device_type == "RESISTOR":

        resistor_aliases = {
            "VALUE": "R",
            "RES": "R",
            "RESISTANCE": "R",
        }

        return resistor_aliases.get(
            normalized_control,
            normalized_control,
        )

    if device_type == "CAPACITOR":

        capacitor_aliases = {
            "VALUE": "C",
            "CAP": "C",
            "CAPACITANCE": "C",
        }

        return capacitor_aliases.get(
            normalized_control,
            normalized_control,
        )

    return normalized_control


def _find_parameter_usages(
    instances: Sequence[SpiceInstance],
    parameter_name: str,
    device_rules: Sequence[DeviceRule],
) -> List[ParameterUsage]:
    """
    找出指定参数在全部器件实例中的使用位置。
    """

    usages: List[ParameterUsage] = []

    for instance in instances:

        device_type = _classify_device(
            instance,
            device_rules,
        )

        # ====================================================
        # 处理具名参数
        #
        # W={WN}
        # L={LN}
        # R={R_VALUE}
        # C={C_VALUE}
        # ====================================================

        for (
            control_parameter,
            expression,
        ) in instance.named_parameters:

            if not expression_contains_parameter(
                expression,
                parameter_name,
            ):
                continue

            if device_type is None:

                # 未识别的 X 可能是普通子电路调用。
                #
                # 例如：
                #
                # XAMP ... OPAMP
                # + WN={WN_VAL}
                #
                # 这种情况下 XAMP 本身不是物理器件，
                # 参数应该继续在子电路内部查找。
                if instance.instance_prefix == "X":
                    continue

                raise ValueError(
                    f"参数 {parameter_name!r} "
                    f"被实例 {instance.instance_name!r} "
                    "使用，但无法识别其器件类型。"
                    f"模型名称为："
                    f"{instance.model_name!r}。"
                    "请添加对应的 DeviceRule。"
                    f"位置：{instance.source_path}:"
                    f"{instance.line_number}"
                )

            normalized_control = (
                _canonicalize_control_parameter(
                    device_type,
                    control_parameter,
                )
            )

            usages.append(
                ParameterUsage(
                    instance_name=(
                        instance.instance_name
                    ),
                    device_type=device_type,
                    model_name=(
                        instance.model_name
                    ),
                    control_parameter=(
                        normalized_control
                    ),
                    source_path=(
                        instance.source_path
                    ),
                    line_number=(
                        instance.line_number
                    ),
                )
            )

        # ====================================================
        # 处理原生 R/C 的位置参数形式
        #
        # R1 node1 node2 {R_VALUE}
        # C1 node1 node2 {C_VALUE}
        # ====================================================

        if (
            instance.instance_prefix
            in {"R", "C"}
            and instance.positional_value
            is not None
            and expression_contains_parameter(
                instance.positional_value,
                parameter_name,
            )
        ):

            if instance.instance_prefix == "R":
                control_parameter = "R"

            else:
                control_parameter = "C"

            usages.append(
                ParameterUsage(
                    instance_name=(
                        instance.instance_name
                    ),
                    device_type=device_type,
                    model_name=None,
                    control_parameter=(
                        control_parameter
                    ),
                    source_path=(
                        instance.source_path
                    ),
                    line_number=(
                        instance.line_number
                    ),
                )
            )

    return usages


def analyze_parameter_usage(
    circuit_paths: Union[
        Path,
        str,
        Sequence[Union[Path, str]],
    ],
    parameter_name_lst: Sequence[str],
    parameter_aliases: Optional[
        Mapping[str, str]
    ] = None,
    device_rules: Sequence[
        DeviceRule
    ] = DEFAULT_DEVICE_RULES,
) -> List[ParameterSpec]:
    """
    分析所有设计变量控制的器件类型和控制参数。

    一个参数可以在多个器件实例中使用，但必须保证所有位置的：

    1. device_type 相同；
    2. control_parameter 相同。

    例如：

    WN 同时控制两个 NMOS 的 W：允许。

    SIZE 同时控制 NMOS.W 和 PMOS.W：报错。

    VALUE 同时控制 RESISTOR.R 和 CAPACITOR.C：报错。
    """

    instances = parse_spice_instances(
        circuit_paths
    )

    aliases = {
        parameter_name.casefold(): (
            circuit_parameter_name
        )

        for (
            parameter_name,
            circuit_parameter_name,
        )
        in (parameter_aliases or {}).items()
    }

    parameter_specs: List[
        ParameterSpec
    ] = []

    seen_parameter_names: set[str] = set()

    for parameter_name in parameter_name_lst:

        normalized_parameter_name = (
            parameter_name.casefold()
        )

        if (
            normalized_parameter_name
            in seen_parameter_names
        ):
            raise ValueError(
                f"参数名称重复："
                f"{parameter_name}"
            )

        seen_parameter_names.add(
            normalized_parameter_name
        )

        circuit_parameter_name = (
            aliases.get(
                normalized_parameter_name,
                parameter_name,
            )
        )

        usages = _find_parameter_usages(
            instances=instances,
            parameter_name=(
                circuit_parameter_name
            ),
            device_rules=device_rules,
        )

        if not usages:

            raise ValueError(
                f"参数 {parameter_name!r} "
                f"映射为 {circuit_parameter_name!r}，"
                "但没有连接到任何支持的 "
                "NMOS、PMOS、电阻或电容。"
                "可能原因包括："
                "参数名称不一致、"
                "缺少 parameter_aliases、"
                "或者当前 PDK 模型需要添加 "
                "DeviceRule。"
            )

        meanings = {
            (
                usage.device_type,
                usage.control_parameter,
            )

            for usage in usages
        }

        # 同一参数的所有使用位置必须具有相同语义
        if len(meanings) != 1:

            usage_details = "; ".join(

                f"{usage.instance_name} -> "
                f"{usage.device_type}."
                f"{usage.control_parameter} "
                f"({usage.source_path}:"
                f"{usage.line_number})"

                for usage in usages
            )

            raise ValueError(
                f"参数 {parameter_name!r} "
                "存在不一致的使用方式："
                f"{usage_details}"
            )

        (
            device_type,
            control_parameter,
        ) = next(iter(meanings))

        parameter_specs.append(
            ParameterSpec(
                parameter_name=parameter_name,
                circuit_parameter_name=(
                    circuit_parameter_name
                ),
                device_type=device_type,
                control_parameter=(
                    control_parameter
                ),
                usages=tuple(usages),
            )
        )

    return parameter_specs


def _validate_bounds(
    parameter_name: str,
    bounds: Bounds,
) -> Bounds:
    """
    检查参数范围：

    (lower_bound, upper_bound, step)
    """

    if len(bounds) != 3:

        raise ValueError(
            f"参数 {parameter_name!r} "
            "的范围必须为："
            "(lower, upper, step)"
        )

    lower_bound, upper_bound, step = map(
        float,
        bounds,
    )

    if not all(
        math.isfinite(value)

        for value in (
            lower_bound,
            upper_bound,
            step,
        )
    ):
        raise ValueError(
            f"参数 {parameter_name!r} "
            "的范围必须为有限数值"
        )

    if lower_bound >= upper_bound:

        raise ValueError(
            f"参数 {parameter_name!r} 中，"
            "lower_bound 必须小于 "
            "upper_bound"
        )

    if step <= 0:

        raise ValueError(
            f"参数 {parameter_name!r} 中，"
            "step 必须大于 0"
        )

    return (
        lower_bound,
        upper_bound,
        step,
    )


def resolve_parameter_bounds(
    parameter_specs: Sequence[
        ParameterSpec
    ],
    control_parameter_ranges: Mapping[
        str,
        Bounds,
    ],
    device_control_ranges: Optional[
        Mapping[
            DeviceControlKey,
            Bounds,
        ]
    ] = None,
    parameter_overrides: Optional[
        Mapping[str, Bounds]
    ] = None,
) -> List[Bounds]:
    """
    根据分析结果查询参数范围。

    匹配优先级：

    1. parameter_overrides
    2. device_control_ranges
    3. control_parameter_ranges

    最终输出顺序与 parameter_specs 完全一致。
    """

    normalized_control_ranges = {

        control_parameter.upper(): bounds

        for (
            control_parameter,
            bounds,
        )
        in control_parameter_ranges.items()
    }

    normalized_device_ranges = {

        (
            device_type.upper(),
            control_parameter.upper(),
        ): bounds

        for (
            (
                device_type,
                control_parameter,
            ),
            bounds,
        )
        in (
            device_control_ranges or {}
        ).items()
    }

    normalized_overrides = {

        parameter_name.casefold(): bounds

        for (
            parameter_name,
            bounds,
        )
        in (
            parameter_overrides or {}
        ).items()
    }

    resolved_bounds: List[Bounds] = []

    for parameter_spec in parameter_specs:

        selected_bounds = (
            normalized_overrides.get(
                parameter_spec
                .parameter_name
                .casefold()
            )
        )

        if selected_bounds is None:

            selected_bounds = (
                normalized_device_ranges.get(
                    (
                        parameter_spec
                        .device_type
                        .upper(),

                        parameter_spec
                        .control_parameter
                        .upper(),
                    )
                )
            )

        if selected_bounds is None:

            selected_bounds = (
                normalized_control_ranges.get(
                    parameter_spec
                    .control_parameter
                    .upper()
                )
            )

        if selected_bounds is None:

            raise KeyError(
                f"参数 "
                f"{parameter_spec.parameter_name!r} "
                "没有对应的范围规则："
                f"{parameter_spec.device_type}."
                f"{parameter_spec.control_parameter}"
            )

        resolved_bounds.append(
            _validate_bounds(
                parameter_spec.parameter_name,
                selected_bounds,
            )
        )

    return resolved_bounds