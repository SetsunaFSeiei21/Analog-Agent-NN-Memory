import csv
import shutil
import json
import re
import subprocess

import numpy as np

from pathlib import Path
from typing import List, Optional, Any, Dict, Tuple
from concurrent.futures import ProcessPoolExecutor


SINGLE_OPAMP_METRIC2METRIC = {
    "DC_GAIN": "DC_Gain_dB",
    "UGF": "UGF_Hz",
    "PM": "Phase_Margin_deg",
    "CMRR": "CMRR_dB",
    "P_PSRR": "PSRR_Plus_dB",
    "N_PSRR": "PSRR_Minus_dB",
    "P_SR": "Slew_Rise_V_us",
    "N_SR": "Slew_Fall_V_us",
    "POWER": "Power_Quiescent_uW",
}


SINGLE_OPAMP_METRIC2TESTBENCH_NAME = {
    "DC_GAIN": "ac",
    "UGF": "ac",

    "PM": "stability",

    "CMRR": "cmrr",

    "P_PSRR": "psrr",
    "N_PSRR": "psrr",

    "P_SR": "slew",
    "N_SR": "slew",

    "POWER": "power",
}


SINGLE_OPAMP_METRIC2RESULT_NAME = {
    "DC_GAIN": "dc_gain_db",
    "UGF": "gbw_hz",

    "PM": "phase_margin_deg",

    "CMRR": "cmrr_ref_db",

    "P_PSRR": "psrr_plus_ref_db",
    "N_PSRR": "psrr_minus_ref_db",

    "P_SR": "slew_rise_v_us",
    "N_SR": "slew_fall_v_us",

    "POWER": "power_uw",
}


class SimulationRunError(RuntimeError):
    """ngspice 对某个 design point 仿真失败。"""


class SimulationResultError(RuntimeError):
    """ngspice 已执行，但无法得到目标性能指标。"""


class Simulator:

    def __init__(
        self,
        metrics: List[str],
        circuit_type: str,
        circuit_name: str,
        simulate_condition_path: Optional[Path] = None,
        output_path: Optional[Path] = None,
    ) -> None:

        pwd_path = Path(__file__).absolute().resolve().parent
        testbench_path = pwd_path / "testbench"

        if not testbench_path.exists():
            raise FileNotFoundError(
                f"Testbench 目录不存在: {testbench_path}"
            )

        type_name_lst = [
            path.name
            for path in testbench_path.iterdir()
            if path.is_dir()
        ]

        if circuit_type not in type_name_lst:
            raise ValueError(
                f"Circuit type 必须在 {type_name_lst} 中，"
                f"现在传入的参数为：{circuit_type}"
            )

        self.circuit_type = circuit_type
        self.circuit_name = circuit_name

        self.raw_metrics = list(metrics)

        self.metrics = self._metric_remapping(
            metrics,
            circuit_type,
        )

        self.circuit_testbench_path = (
            testbench_path / circuit_type
        )

        if simulate_condition_path is None:
            self.simulate_condition_path = (
                self.circuit_testbench_path
                / "default_simulate_condition"
            )
        else:
            self.simulate_condition_path = (
                simulate_condition_path
            )

        if output_path is None:
            self.output_path = (
                pwd_path.parent.parent
                / "simulate_result"
            )
        else:
            self.output_path = output_path

        self.output_path.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.workspace_path = (
            pwd_path / "workspace"
        )

        if self.workspace_path.exists():
            shutil.rmtree(
                self.workspace_path
            )

        self.workspace_path.mkdir()

    def _metric_remapping(
        self,
        metrics: List[str],
        circuit_type: str,
    ) -> List[str]:

        if circuit_type != "single_ended_opamp":
            raise NotImplementedError(
                f"暂不支持的电路类型: {circuit_type}"
            )

        for metric in metrics:
            if metric not in SINGLE_OPAMP_METRIC2METRIC:
                raise ValueError(
                    f"不支持的性能指标: {metric}"
                )

        return [
            SINGLE_OPAMP_METRIC2METRIC[metric]
            for metric in metrics
        ]

    def _get_testbench_name_lst(
        self,
    ) -> List[str]:

        testbench_name_lst = []

        for raw_metric in self.raw_metrics:

            testbench_name = (
                SINGLE_OPAMP_METRIC2TESTBENCH_NAME[
                    raw_metric
                ]
            )

            if testbench_name not in testbench_name_lst:
                testbench_name_lst.append(
                    testbench_name
                )

        return testbench_name_lst

    def _generate_workspace(
        self,
        n_workers: int,
    ) -> None:

        for worker_id in range(n_workers):

            sub_workspace = (
                self.workspace_path
                / f"workspace_{worker_id}"
            )

            sub_workspace.mkdir()

    def _copy_circuit(
        self,
        circuit_path: Path,
    ) -> None:

        circuit_file = (
            circuit_path
            / f"{self.circuit_name}.sp"
        )

        params_file = (
            circuit_path
            / f"{self.circuit_name}_params.sp"
        )

        if not circuit_file.exists():
            raise FileNotFoundError(
                "电路文件未找到或命名不正确，"
                "请确保电路文件命名为："
                "电路名称.sp"
            )

        if not params_file.exists():
            raise FileNotFoundError(
                "参数文件未找到或命名不正确，"
                "请确保参数文件命名为："
                "电路名称_params.sp"
            )

        for sub_workspace in (
            self.workspace_path.iterdir()
        ):

            if not sub_workspace.is_dir():
                continue

            shutil.copy2(
                circuit_file,
                sub_workspace,
            )

            shutil.copy2(
                params_file,
                sub_workspace,
            )

    def _generate_testbench_copy(
        self,
    ) -> None:

        testbench_name_lst = (
            self._get_testbench_name_lst()
        )

        modified_testbench: Dict[str, str] = {}

        # 先替换通用 simulation condition。
        # DUT_PATH 此时故意保留。
        for testbench_name in testbench_name_lst:

            tb_file_path = (
                self.circuit_testbench_path
                / f"tb_{testbench_name}.cir"
            )

            cond_file_path = (
                self.simulate_condition_path
                / f"{testbench_name}_condition.json"
            )

            if not tb_file_path.exists():
                raise FileNotFoundError(
                    f"未找到 Testbench 脚本: "
                    f"{tb_file_path}"
                )

            if not cond_file_path.exists():
                raise FileNotFoundError(
                    f"未找到仿真条件文件: "
                    f"{cond_file_path}"
                )

            testbench_content = (
                tb_file_path.read_text(
                    encoding="utf-8"
                )
            )

            simulate_condition: Dict[str, Any] = (
                json.loads(
                    cond_file_path.read_text(
                        encoding="utf-8"
                    )
                )
            )

            if "DUT_PATH" in simulate_condition:
                raise ValueError(
                    f"{cond_file_path.name} "
                    f"中不应定义 DUT_PATH"
                )

            for key, value in (
                simulate_condition.items()
            ):

                testbench_content = (
                    testbench_content.replace(
                        f"{{{{{key}}}}}",
                        str(value),
                    )
                )

            modified_testbench[
                testbench_name
            ] = testbench_content

        # 再针对不同 workspace 替换 DUT_PATH。
        for sub_workspace in (
            self.workspace_path.iterdir()
        ):

            if not sub_workspace.is_dir():
                continue

            dut_path = (
                sub_workspace
                / f"{self.circuit_name}.sp"
            ).resolve()

            if not dut_path.exists():
                raise FileNotFoundError(
                    f"Workspace 中不存在 DUT 文件: "
                    f"{dut_path}"
                )

            for (
                testbench_name,
                testbench_content,
            ) in modified_testbench.items():

                workspace_testbench_content = (
                    testbench_content.replace(
                        "{{DUT_PATH}}",
                        dut_path.as_posix(),
                    )
                )

                if (
                    "{{" in workspace_testbench_content
                    or "}}" in workspace_testbench_content
                ):
                    raise ValueError(
                        f"tb_{testbench_name}.cir "
                        f"中仍存在未替换的参数"
                    )

                target_testbench_file = (
                    sub_workspace
                    / f"tb_{testbench_name}.cir"
                )

                target_testbench_file.write_text(
                    workspace_testbench_content,
                    encoding="utf-8",
                )

    def _rewrite_parameters(
        self,
        sub_workspace: Path,
        design_parameters: np.ndarray,
    ) -> None:

        workspace_param_path = (
            sub_workspace
            / f"{self.circuit_name}_params.sp"
        )

        if not workspace_param_path.exists():
            raise FileNotFoundError(
                f"参数文件不存在: "
                f"{workspace_param_path}"
            )

        lines = (
            workspace_param_path
            .read_text(
                encoding="utf-8"
            )
            .splitlines()
        )

        param_line_index_lst = []

        for index, line in enumerate(lines):

            if (
                line.strip()
                .lower()
                .startswith(".param")
            ):
                param_line_index_lst.append(
                    index
                )

        if (
            len(param_line_index_lst)
            != len(design_parameters)
        ):
            raise ValueError(
                f"参数文件中共有 "
                f"{len(param_line_index_lst)} 个参数，"
                f"但 design_parameters 中有 "
                f"{len(design_parameters)} 个值"
            )

        for (
            value_index,
            line_index,
        ) in enumerate(
            param_line_index_lst
        ):

            line = lines[line_index]

            if "=" not in line:
                raise ValueError(
                    f"参数行格式错误: {line}"
                )

            left_part = (
                line.split("=", 1)[0]
            )

            lines[line_index] = (
                f"{left_part}= "
                f"{design_parameters[value_index]}"
            )

        workspace_param_path.write_text(
            "\n".join(lines) + "\n",
            encoding="utf-8",
        )

    def _run_testbench(
        self,
        sub_workspace: Path,
    ) -> Dict[str, Path]:

        testbench_name_lst = (
            self._get_testbench_name_lst()
        )

        log_path_dict: Dict[
            str,
            Path,
        ] = {}

        for testbench_name in (
            testbench_name_lst
        ):

            testbench_path = (
                sub_workspace
                / f"tb_{testbench_name}.cir"
            )

            if not testbench_path.exists():
                raise FileNotFoundError(
                    f"Workspace 中不存在 Testbench: "
                    f"{testbench_path}"
                )

            log_path = (
                sub_workspace
                / f"{testbench_name}.log"
            )

            if log_path.exists():
                log_path.unlink()

            command = [
                "ngspice",
                "-b",
                "-o",
                log_path.name,
                testbench_path.name,
            ]

            try:
                process = subprocess.run(
                    command,
                    cwd=sub_workspace,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )

            except FileNotFoundError as exc:
                raise FileNotFoundError(
                    "未找到 ngspice 命令，"
                    "请确认 ngspice 已安装并加入 PATH。"
                ) from exc

            if log_path.exists():
                log_content = (
                    log_path.read_text(
                        encoding="utf-8",
                        errors="replace",
                    )
                )
            else:
                log_content = (
                    process.stdout or ""
                )

            if process.returncode != 0:
                raise SimulationRunError(
                    f"ngspice 仿真失败。\n"
                    f"Testbench: {testbench_path.name}\n"
                    f"Workspace: {sub_workspace}\n"
                    f"Return code: "
                    f"{process.returncode}\n"
                    f"Log:\n{log_content}"
                )

            if re.search(
                r"(?im)^\s*"
                r"(fatal error|error:)",
                log_content,
            ):
                raise SimulationRunError(
                    f"ngspice log 中检测到错误。\n"
                    f"Testbench: {testbench_path.name}\n"
                    f"Workspace: {sub_workspace}\n"
                    f"Log:\n{log_content}"
                )

            if not log_path.exists():
                raise SimulationRunError(
                    f"ngspice 未生成 log 文件: "
                    f"{log_path}"
                )

            log_path_dict[
                testbench_name
            ] = log_path

        return log_path_dict

    def _read_simulation_result(
        self,
        log_path_dict: Dict[str, Path],
    ) -> np.ndarray:

        result_lst = []

        log_content_dict: Dict[
            str,
            str,
        ] = {}

        number_pattern = (
            r"[-+]?"
            r"(?:"
            r"\d+(?:\.\d*)?"
            r"|"
            r"\.\d+"
            r")"
            r"(?:[eE][-+]?\d+)?"
        )

        for raw_metric in self.raw_metrics:

            testbench_name = (
                SINGLE_OPAMP_METRIC2TESTBENCH_NAME[
                    raw_metric
                ]
            )

            result_name = (
                SINGLE_OPAMP_METRIC2RESULT_NAME[
                    raw_metric
                ]
            )

            if testbench_name not in log_path_dict:
                raise SimulationResultError(
                    f"未找到 {testbench_name} "
                    f"对应的 log 文件"
                )

            if (
                testbench_name
                not in log_content_dict
            ):

                log_path = (
                    log_path_dict[
                        testbench_name
                    ]
                )

                log_content_dict[
                    testbench_name
                ] = log_path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )

            log_content = (
                log_content_dict[
                    testbench_name
                ]
            )

            pattern = (
                rf"(?im)^\s*"
                rf"{re.escape(result_name)}"
                rf"\s*=\s*"
                rf"({number_pattern})"
            )

            matches = re.findall(
                pattern,
                log_content,
            )

            if not matches:
                raise SimulationResultError(
                    f"无法从 {testbench_name}.log "
                    f"中读取指标 {raw_metric}。\n"
                    f"期望变量名称: {result_name}"
                )

            result_value = float(
                matches[-1]
            )

            result_lst.append(
                result_value
            )

        return np.asarray(
            result_lst,
            dtype=float,
        )

    def _simulate_chunk(
        self,
        sub_workspace: Path,
        chunk: np.ndarray,
        sample_index_chunk: np.ndarray,
        continue_on_error: bool,
    ) -> Tuple[
        np.ndarray,
        List[Dict[str, Any]],
    ]:

        result_lst = []
        failure_records = []

        for (
            sample_index,
            design_parameters,
        ) in zip(
            sample_index_chunk,
            chunk,
        ):

            # 参数文件本身有问题属于配置错误，
            # 不应该当成“非法设计点”吞掉。
            self._rewrite_parameters(
                sub_workspace,
                design_parameters,
            )

            try:
                log_path_dict = (
                    self._run_testbench(
                        sub_workspace
                    )
                )

                simulation_result = (
                    self._read_simulation_result(
                        log_path_dict
                    )
                )

            except (
                SimulationRunError,
                SimulationResultError,
            ) as exc:

                if not continue_on_error:
                    raise

                simulation_result = (
                    np.full(
                        len(self.raw_metrics),
                        np.nan,
                        dtype=float,
                    )
                )

                failure_records.append(
                    {
                        "sample_index": int(
                            sample_index
                        ),
                        "design_parameters":
                            design_parameters.tolist(),
                        "error_type":
                            type(exc).__name__,
                        "error":
                            str(exc),
                    }
                )

            result_lst.append(
                simulation_result
            )

        if not result_lst:

            return (
                np.empty(
                    (
                        0,
                        len(self.raw_metrics),
                    ),
                    dtype=float,
                ),
                failure_records,
            )

        return (
            np.vstack(result_lst),
            failure_records,
        )

    def _write_failure_records(
        self,
        failure_records:
            List[Dict[str, Any]],
    ) -> None:

        if not failure_records:
            return

        circuit_result_path = (
            self.output_path
            / self.circuit_name
        )

        circuit_result_path.mkdir(
            parents=True,
            exist_ok=True,
        )

        failure_path = (
            circuit_result_path
            / "simulation_failures.jsonl"
        )

        with open(
            failure_path,
            mode="w",
            encoding="utf-8",
        ) as file:

            for record in failure_records:

                file.write(
                    json.dumps(
                        record,
                        ensure_ascii=False,
                    )
                    + "\n"
                )

    def write_simulate_result(
        self,
        design_parameters: np.ndarray,
        metrics: np.ndarray,
        design_parameter_name_lst:
            Optional[List[str]] = None,
    ) -> None:

        design_parameters_array = (
            np.asarray(
                design_parameters,
                dtype=float,
            )
        )

        metrics_array = (
            np.asarray(
                metrics,
                dtype=float,
            )
        )

        if design_parameters_array.ndim == 1:
            design_parameters_array = (
                design_parameters_array.reshape(
                    1,
                    -1,
                )
            )

        if metrics_array.ndim == 1:
            metrics_array = (
                metrics_array.reshape(
                    1,
                    -1,
                )
            )

        if design_parameters_array.ndim != 2:
            raise ValueError(
                "design_parameters 必须为 "
                "一维或二维数组"
            )

        if metrics_array.ndim != 2:
            raise ValueError(
                "metrics 必须为一维或二维数组"
            )

        if (
            design_parameters_array.shape[0]
            != metrics_array.shape[0]
        ):
            raise ValueError(
                "design_parameters 与 metrics "
                "的样本数量必须一致："
                f"{design_parameters_array.shape[0]}"
                " != "
                f"{metrics_array.shape[0]}"
            )

        if (
            metrics_array.shape[1]
            != len(self.metrics)
        ):
            raise ValueError(
                f"metrics 应有 "
                f"{len(self.metrics)} 列，"
                f"实际为 "
                f"{metrics_array.shape[1]} 列"
            )

        circuit_result_path = (
            self.output_path
            / self.circuit_name
        )

        circuit_result_path.mkdir(
            parents=True,
            exist_ok=True,
        )

        design_csv_path = (
            circuit_result_path
            / "design_parameters.csv"
        )

        metrics_csv_path = (
            circuit_result_path
            / "metrics.csv"
        )

        is_first_design = (
            not design_csv_path.exists()
        )

        if is_first_design:

            if design_parameter_name_lst is None:
                raise ValueError(
                    "第一次保存仿真结果必须指定 "
                    "design_parameter_name_lst。"
                )

            if (
                len(design_parameter_name_lst)
                != design_parameters_array.shape[1]
            ):
                raise ValueError(
                    "design_parameter_name_lst "
                    "长度与设计参数列数不一致"
                )

        else:

            with open(
                design_csv_path,
                mode="r",
                encoding="utf-8",
            ) as file:

                reader = csv.reader(file)
                existing_header = next(reader)

            if (
                len(existing_header)
                != design_parameters_array.shape[1]
            ):
                raise ValueError(
                    "现有 design_parameters.csv "
                    "与本次设计参数维度不一致"
                )

            if (
                design_parameter_name_lst
                is not None
                and existing_header
                != list(
                    design_parameter_name_lst
                )
            ):
                raise ValueError(
                    "本次参数名称与已有 "
                    "design_parameters.csv "
                    "表头不一致"
                )

        with open(
            design_csv_path,
            mode="a",
            newline="",
            encoding="utf-8",
        ) as file:

            writer = csv.writer(file)

            if is_first_design:
                writer.writerow(
                    design_parameter_name_lst
                )

            writer.writerows(
                design_parameters_array.tolist()
            )

        is_first_metric = (
            not metrics_csv_path.exists()
        )

        if not is_first_metric:

            with open(
                metrics_csv_path,
                mode="r",
                encoding="utf-8",
            ) as file:

                reader = csv.reader(file)
                existing_header = next(reader)

            if existing_header != self.metrics:
                raise ValueError(
                    "现有 metrics.csv 的指标列"
                    "与当前 Simulator 不一致"
                )

        with open(
            metrics_csv_path,
            mode="a",
            newline="",
            encoding="utf-8",
        ) as file:

            writer = csv.writer(file)

            if is_first_metric:
                writer.writerow(
                    self.metrics
                )

            writer.writerows(
                metrics_array.tolist()
            )

    def simulate(
        self,
        circuit_path: Path,
        n_workers: int,
        design_parameters_array: np.ndarray,
        continue_on_error: bool = False,
    ) -> np.ndarray:

        if (
            isinstance(n_workers, bool)
            or not isinstance(n_workers, int)
        ):
            raise TypeError(
                "n_workers 必须为整数"
            )

        if n_workers <= 0:
            raise ValueError(
                "n_workers 必须大于 0"
            )

        design_parameters_array = (
            np.asarray(
                design_parameters_array,
                dtype=float,
            )
        )

        if design_parameters_array.ndim != 2:
            raise ValueError(
                "design_parameters_array "
                "必须为二维数组，"
                "shape 应为 "
                "(n_samples, n_parameters)"
            )

        n_samples = (
            design_parameters_array.shape[0]
        )

        if n_samples == 0:
            raise ValueError(
                "design_parameters_array 不能为空"
            )

        effective_workers = min(
            n_workers,
            n_samples,
        )

        # 每次 simulate 都建立干净 workspace。
        if self.workspace_path.exists():
            shutil.rmtree(
                self.workspace_path
            )

        self.workspace_path.mkdir()

        self._generate_workspace(
            effective_workers
        )

        # 先复制 circuit，之后才能生成 DUT_PATH。
        self._copy_circuit(
            circuit_path
        )

        self._generate_testbench_copy()

        design_parameters_chunks = (
            np.array_split(
                design_parameters_array,
                effective_workers,
            )
        )

        sample_index_chunks = (
            np.array_split(
                np.arange(n_samples),
                effective_workers,
            )
        )

        futures = []

        with ProcessPoolExecutor(
            max_workers=effective_workers
        ) as executor:

            for (
                worker_id,
                (
                    chunk,
                    sample_index_chunk,
                ),
            ) in enumerate(
                zip(
                    design_parameters_chunks,
                    sample_index_chunks,
                )
            ):

                sub_workspace = (
                    self.workspace_path
                    / f"workspace_{worker_id}"
                )

                future = executor.submit(
                    self._simulate_chunk,
                    sub_workspace,
                    chunk,
                    sample_index_chunk,
                    continue_on_error,
                )

                futures.append(
                    future
                )

            worker_results = [
                future.result()
                for future in futures
            ]

        result_chunks = [
            result_chunk
            for (
                result_chunk,
                _,
            ) in worker_results
        ]

        failure_records = [
            failure_record
            for (
                _,
                worker_failure_records,
            ) in worker_results
            for failure_record
            in worker_failure_records
        ]

        result_array = np.vstack(
            result_chunks
        )

        self._write_failure_records(
            failure_records
        )

        return result_array