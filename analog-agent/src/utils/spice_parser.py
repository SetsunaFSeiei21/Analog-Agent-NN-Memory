from __future__ import annotations

import re

from dataclasses import dataclass
from pathlib import Path
from typing import (
    List,
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

    logical_lines = _read_logical_lines(
        parameter_path
    )

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
) -> List[SpiceInstance]:
    """
    解析电路网表中的 MOS、电阻和电容实例。

    支持实例前缀：

    M：原生 MOS
    X：PDK 器件或子电路
    R：原生电阻
    C：原生电容

    本函数只负责语法解析，不判断具体器件类型。
    """

    instances: List[SpiceInstance] = []

    normalized_paths = _normalize_paths(
        circuit_paths
    )

    for circuit_path in normalized_paths:

        logical_lines = _read_logical_lines(
            circuit_path
        )

        for logical_line in logical_lines:

            statement = logical_line.text

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
                not in {"M", "X", "R", "C"}
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

    return instances