from __future__ import annotations

import logging
import re

import numpy as np

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


@dataclass(frozen=True)
class SpiceInstance:
    """
    解析后的一条 SPICE 器件实例。
    """

    instance_name: str

    instance_prefix: str

    model_name: Optional[str]

    named_parameters: Tuple[
        Tuple[str, str],
        ...
    ]

    positional_value: Optional[str]

    source_path: Path

    line_number: int


@dataclass(frozen=True)
class _LogicalLine:
    """
    合并 + 续行后的一条完整 SPICE 语句。
    """

    text: str

    source_path: Path

    line_number: int


_PARAM_DIRECTIVE_PATTERN = re.compile(
    r"^\.param\b",
    flags=re.IGNORECASE,
)

_PARAMETER_NAME_PATTERN = re.compile(
    r"(?:^|\s)"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"\s*=",
)

_ASSIGNMENT_PATTERN = re.compile(
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"\s*=\s*"
    r"(?P<value>\{[^{}]*\}|[^\s]+)",
)

_IDENTIFIER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"[A-Za-z_][A-Za-z0-9_]*"
    r"(?![A-Za-z0-9_])",
)


def _normalize_paths(
    spice_paths: Union[
        Path,
        str,
        Sequence[Union[Path, str]],
    ],
) -> List[Path]:
    """
    将单个路径或多个路径统一转换成 Path 列表。
    """

    if isinstance(
        spice_paths,
        (str, Path),
    ):
        normalized_paths = [
            Path(spice_paths)
        ]

    else:
        normalized_paths = [
            Path(path)
            for path in spice_paths
        ]

    if not normalized_paths:
        raise ValueError(
            "At least one SPICE path is required."
        )

    return normalized_paths


def _read_logical_lines(
    spice_path: Path,
) -> List[_LogicalLine]:
    """
    读取 SPICE 文件并合并以 + 开头的续行。

    例如：

    XMN1 D G S B nfet_model
    + W={WN}
    + L={LN}

    会被合并成一条完整语句。
    """

    spice_path = Path(spice_path)

    if not spice_path.is_file():
        raise FileNotFoundError(
            f"SPICE file does not exist: "
            f"{spice_path}"
        )

    logical_lines: List[_LogicalLine] = []

    current_text: Optional[str] = None

    current_line_number = 0

    raw_lines = (
        spice_path
        .read_text(encoding="utf-8")
        .splitlines()
    )

    for line_number, raw_line in enumerate(
        raw_lines,
        start=1,
    ):

        stripped_line = raw_line.strip()

        # 忽略空行和 * 注释行
        if (
            not stripped_line
            or stripped_line.startswith("*")
        ):
            continue

        # 去掉 ngspice 的 $ 行内注释
        stripped_line = (
            stripped_line
            .split("$", maxsplit=1)[0]
            .strip()
        )

        if not stripped_line:
            continue

        # 处理 + 续行
        if stripped_line.startswith("+"):

            if current_text is None:
                raise ValueError(
                    "Continuation line has no "
                    "parent statement: "
                    f"{spice_path}:{line_number}"
                )

            current_text += (
                " "
                + stripped_line[1:].strip()
            )

            continue

        # 保存上一条语句
        if current_text is not None:

            logical_lines.append(
                _LogicalLine(
                    text=current_text,
                    source_path=spice_path,
                    line_number=(
                        current_line_number
                    ),
                )
            )

        current_text = stripped_line

        current_line_number = line_number

    if current_text is not None:

        logical_lines.append(
            _LogicalLine(
                text=current_text,
                source_path=spice_path,
                line_number=(
                    current_line_number
                ),
            )
        )

    return logical_lines


def read_parameter_names(
    parameter_path: Path,
    logger: Optional[logging.Logger] = None,
) -> List[str]:
    """
    按照 params.sp 中的出现顺序读取参数名称。

    支持：

    .param WN = 2

    也支持：

    .param WN=2 LN=0.5
    """

    parameter_names: List[str] = []

    seen_names: set[str] = set()

    active_logger = logger or logging.getLogger(__name__)
    logical_lines = _read_logical_lines(parameter_path)

    for logical_line in logical_lines:

        statement = logical_line.text

        if (
            _PARAM_DIRECTIVE_PATTERN.match(
                statement
            )
            is None
        ):
            continue

        parameter_body = (
            _PARAM_DIRECTIVE_PATTERN.sub(
                "",
                statement,
                count=1,
            )
            .strip()
        )

        matches = list(
            _PARAMETER_NAME_PATTERN.finditer(
                parameter_body
            )
        )

        if not matches:
            raise ValueError(
                "Invalid .param statement: "
                f"{logical_line.source_path}:"
                f"{logical_line.line_number}: "
                f"{statement}"
            )

        for match in matches:

            parameter_name = match.group(
                "name"
            )

            normalized_name = (
                parameter_name.casefold()
            )

            if normalized_name in seen_names:

                raise ValueError(
                    f"Duplicate parameter "
                    f"{parameter_name!r}: "
                    f"{logical_line.source_path}:"
                    f"{logical_line.line_number}"
                )

            seen_names.add(
                normalized_name
            )

            parameter_names.append(
                parameter_name
            )

    if not parameter_names:
        raise ValueError(
            f"No .param declarations found "
            f"in {parameter_path}"
        )

    active_logger.debug("读取参数名称完成：path=%s, count=%d", parameter_path, len(parameter_names))
    return parameter_names


def expression_contains_parameter(
    expression: str,
    parameter_name: str,
) -> bool:
    """
    判断表达式是否引用指定参数。

    支持：

    {WN}
    {2 * WN}
    {WN + DELTA_W}
    """

    identifiers = {
        match.group(0).casefold()

        for match
        in _IDENTIFIER_PATTERN.finditer(
            expression
        )
    }

    return (
        parameter_name.casefold()
        in identifiers
    )


def parse_spice_instances(
    circuit_paths: Union[
        Path,
        str,
        Sequence[Union[Path, str]],
    ],
    logger: Optional[logging.Logger] = None,
) -> List[SpiceInstance]:
    """
    解析电路网表中的 MOS、电阻、电容和独立电流源实例。

    支持实例前缀：

    M：原生 MOS
    X：PDK 器件或子电路
    R：原生电阻
    C：原生电容
    I：独立电流源（直流）

    本函数只负责语法解析，不判断具体器件类型。
    """

    active_logger = logger or logging.getLogger(__name__)
    instances: List[SpiceInstance] = []

    normalized_paths = _normalize_paths(
        circuit_paths
    )

    for circuit_path in normalized_paths:

        logical_lines = _read_logical_lines(
            circuit_path
        )

        in_control_block = False

        for logical_line in logical_lines:

            statement = logical_line.text

            if statement.lower().startswith(".control"):
                in_control_block = True
                continue

            if statement.lower().startswith(".endc"):
                in_control_block = False
                continue

            if in_control_block:
                continue

            # 跳过 .param、.subckt、.include 等
            if statement.startswith("."):
                continue

            statement_tokens = (
                statement.split()
            )

            if not statement_tokens:
                continue

            instance_name = (
                statement_tokens[0]
            )

            instance_prefix = (
                instance_name[0].upper()
            )

            if (
                instance_prefix
                not in {"M", "X", "R", "C", "I"}
            ):
                continue

            # 提取 W={...}、L={...} 等具名参数
            named_parameters = tuple(

                (
                    match.group("name"),
                    match.group("value"),
                )

                for match
                in _ASSIGNMENT_PATTERN.finditer(
                    statement
                )
            )

            # 删除具名参数后提取位置参数
            positional_statement = (
                _ASSIGNMENT_PATTERN.sub(
                    "",
                    statement,
                )
            )

            positional_tokens = (
                positional_statement.split()
            )

            model_name: Optional[str] = None

            positional_value: Optional[
                str
            ] = None

            if (
                instance_prefix == "M"
                and len(positional_tokens) >= 6
            ):
                # Mname drain gate source bulk model
                model_name = (
                    positional_tokens[5]
                )

            elif (
                instance_prefix == "X"
                and len(positional_tokens) >= 2
            ):
                # Xname node... model_or_subcircuit
                model_name = (
                    positional_tokens[-1]
                )

            elif (
                instance_prefix in {"R", "C"}
                and len(positional_tokens) >= 4
            ):
                # Rname node1 node2 value
                # Cname node1 node2 value
                positional_value = (
                    positional_tokens[3]
                )

            elif instance_prefix == "I" and len(positional_tokens) >= 4:
                # Iname node+ node- [DC] value
                value_index = 4 if positional_tokens[3].upper() == "DC" else 3
                if len(positional_tokens) > value_index:
                    positional_value = positional_tokens[value_index]

            instances.append(
                SpiceInstance(
                    instance_name=(
                        instance_name
                    ),
                    instance_prefix=(
                        instance_prefix
                    ),
                    model_name=model_name,
                    named_parameters=(
                        named_parameters
                    ),
                    positional_value=(
                        positional_value
                    ),
                    source_path=(
                        logical_line.source_path
                    ),
                    line_number=(
                        logical_line.line_number
                    ),
                )
            )

    active_logger.debug("SPICE 实例解析完成：paths=%s, count=%d", normalized_paths, len(instances))
    return instances


def rewrite_parameter_values(
    parameter_path: Path,
    parameter_values: Mapping[str, float],
    logger: Optional[logging.Logger] = None,
) -> None:
    """在保留注释、续行和同一行其他参数的前提下更新 `.param` 数值。"""

    active_logger = logger or logging.getLogger(__name__)
    parameter_path = Path(parameter_path)
    declared_names = read_parameter_names(parameter_path, logger=active_logger)
    declared_by_key = {name.casefold(): name for name in declared_names}
    supplied_by_key = {name.casefold(): value for name, value in parameter_values.items()}

    if set(declared_by_key) != set(supplied_by_key):
        missing = sorted(declared_by_key[key] for key in set(declared_by_key) - set(supplied_by_key))
        extra = sorted(name for name in parameter_values if name.casefold() not in declared_by_key)
        raise ValueError(f"参数名称不一致：missing={missing}, extra={extra}")

    formatted_values: dict[str, str] = {}
    for normalized_name, raw_value in supplied_by_key.items():
        if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float, np.number)):
            raise TypeError(f"参数 {declared_by_key[normalized_name]!r} 的值必须是数值")
        value = float(raw_value)
        if not np.isfinite(value):
            raise ValueError(f"参数 {declared_by_key[normalized_name]!r} 的值必须是有限数值")
        formatted_values[normalized_name] = repr(value)

    lines = parameter_path.read_text(encoding="utf-8").splitlines()
    rewritten: list[str] = []
    replaced_names: set[str] = set()
    index = 0

    while index < len(lines):
        line = lines[index]
        if _PARAM_DIRECTIVE_PATTERN.match(line.strip()) is None:
            rewritten.append(line)
            index += 1
            continue

        block_lines = [line]
        index += 1
        while index < len(lines) and lines[index].lstrip().startswith("+"):
            block_lines.append(lines[index])
            index += 1

        block = "\n".join(block_lines)
        for normalized_name, declared_name in declared_by_key.items():
            pattern = re.compile(
                rf"(?<![A-Za-z0-9_])(?P<prefix>{re.escape(declared_name)}\s*=\s*)"
                rf"(?P<value>\{{[^{{}}]*\}}|'[^']*'|\"[^\"]*\"|[^\s;$]+)",
                flags=re.IGNORECASE,
            )
            block, count = pattern.subn(
                lambda match, value=formatted_values[normalized_name]: match.group("prefix") + value,
                block,
            )
            if count > 1:
                raise ValueError(f"参数 {declared_name!r} 在参数文件中出现多次")
            if count == 1:
                replaced_names.add(normalized_name)

        rewritten.extend(block.splitlines())

    missing_replacements = set(declared_by_key) - replaced_names
    if missing_replacements:
        missing = sorted(declared_by_key[name] for name in missing_replacements)
        raise ValueError(f"无法重写以下参数：{missing}")

    parameter_path.write_text("\n".join(rewritten) + "\n", encoding="utf-8")
    active_logger.debug("参数文件重写完成：path=%s, count=%d", parameter_path, len(replaced_names))
