from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import (
    List,
    Optional,
    Sequence,
    Tuple,
)

import numpy as np


Bounds = Tuple[float, float, float]


class Sampler_Optimizer(ABC):

    def __init__(
        self,
        circuit_param_path: Path,
        parameter_name_lst: Sequence[str],
        bounds: Sequence[Bounds],
        seed: int = 42,
    ) -> None:

        self.circuit_param_path = Path(
            circuit_param_path
        )

        self.parameter_name_lst: List[str] = list(
            parameter_name_lst
        )

        self.bounds: List[Bounds] = [
            tuple(map(float, bound))
            for bound in bounds
        ]

        self.seed = seed

        if (
            len(self.parameter_name_lst)
            != len(self.bounds)
        ):
            raise ValueError(
                "parameter_name_lst 的长度必须等于 "
                "bounds 的长度："
                f"{len(self.parameter_name_lst)} "
                f"!= {len(self.bounds)}"
            )

        if not self.parameter_name_lst:
            raise ValueError(
                "parameter_name_lst 不能为空"
            )

        normalized_names = {
            name.casefold()
            for name in self.parameter_name_lst
        }

        if (
            len(normalized_names)
            != len(self.parameter_name_lst)
        ):
            raise ValueError(
                "parameter_name_lst 中存在重复参数"
            )

        for parameter_name, bound in zip(
            self.parameter_name_lst,
            self.bounds,
        ):
            self._validate_bound(
                parameter_name,
                bound,
            )

    @staticmethod
    def _validate_bound(
        parameter_name: str,
        bound: Bounds,
    ) -> None:

        if len(bound) != 3:
            raise ValueError(
                f"参数 {parameter_name!r} 的范围"
                "必须为 "
                "(lower_bound, upper_bound, step)"
            )

        (
            lower_bound,
            upper_bound,
            step,
        ) = bound

        if not all(
            np.isfinite(value)
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
                f"参数 {parameter_name!r} 的 "
                "lower_bound 必须小于 upper_bound"
            )

        if step <= 0:
            raise ValueError(
                f"参数 {parameter_name!r} 的 "
                "step 必须大于 0"
            )

    def _project_to_legal_grid(
        self,
        values: np.ndarray,
    ) -> np.ndarray:
        """
        将连续采样点投影到合法离散网格。

        对于：

        lower=0
        upper=1
        step=0.35

        合法值只能是：

        0, 0.35, 0.70

        不会因为 clip 产生非法的 1.0。
        """

        values_array = np.asarray(
            values,
            dtype=float,
        )

        if values_array.ndim != 2:
            raise ValueError(
                "values 必须为二维数组"
            )

        if (
            values_array.shape[1]
            != len(self.bounds)
        ):
            raise ValueError(
                "values 的参数维度与 bounds "
                "不一致："
                f"{values_array.shape[1]} "
                f"!= {len(self.bounds)}"
            )

        bound_array = np.asarray(
            self.bounds,
            dtype=float,
        )

        lower_array = (
            bound_array[:, 0]
            .reshape(1, -1)
        )

        upper_array = (
            bound_array[:, 1]
            .reshape(1, -1)
        )

        step_array = (
            bound_array[:, 2]
            .reshape(1, -1)
        )

        step_ratio = (
            upper_array - lower_array
        ) / step_array

        tolerance = (
            np.maximum(
                1.0,
                np.abs(step_ratio),
            )
            * 1e-12
        )

        max_step_index = np.floor(
            step_ratio + tolerance
        ).astype(np.int64)

        step_index = np.rint(
            (
                values_array
                - lower_array
            )
            / step_array
        ).astype(np.int64)

        step_index = np.maximum(
            step_index,
            0,
        )

        step_index = np.minimum(
            step_index,
            max_step_index,
        )

        result = (
            lower_array
            + step_index * step_array
        )

        # 只用于消除浮点数极小误差，不会制造非法上界点
        result = np.minimum(
            result,
            upper_array,
        )

        return result

    def rewrite_param(
        self,
        value_lst: Sequence[float],
    ) -> None:

        if (
            len(self.parameter_name_lst)
            != len(value_lst)
        ):
            raise ValueError(
                "参数名称数量与参数值数量不一致："
                f"{len(self.parameter_name_lst)} "
                f"!= {len(value_lst)}"
            )

        write_content_lst = [
            f".param {parameter_name} = {value}"

            for parameter_name, value in zip(
                self.parameter_name_lst,
                value_lst,
            )
        ]

        self.circuit_param_path.write_text(
            "\n".join(write_content_lst)
            + "\n",
            encoding="utf-8",
        )

    @abstractmethod
    def generate_sample_point(
        self,
        n_points: int,
        n_workers: Optional[int] = None,
    ) -> np.ndarray:
        """
        生成采样点。
        """

        raise NotImplementedError