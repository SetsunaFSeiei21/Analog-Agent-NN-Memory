from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import tempfile

from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from ..utils.spice_parser import read_parameter_names, rewrite_parameter_values
from .history_store import SamplingHistoryStore


__all__ = [
    "SimulationBatchResult",
    "SimulationResultError",
    "SimulationRunError",
    "Simulator",
]


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
    """ngspice 对某个 design point 执行失败。"""


class SimulationResultError(RuntimeError):
    """ngspice 已执行，但无法得到目标性能指标。"""


@dataclass(frozen=True)
class SimulationBatchResult:
    metrics: np.ndarray
    failure_records: Tuple[Dict[str, Any], ...]


class Simulator:
    GENERATED_NAMES = {
        ".git",
        ".workspaces",
        "__pycache__",
        "circuit_metadata.json",
        "logs",
        "sampling_history.sqlite3",
        "sampling_history.sqlite3-shm",
        "sampling_history.sqlite3-wal",
        "design_parameters.csv",
        "metrics.csv",
        "simulation_failures.jsonl",
    }

    def __init__(
        self,
        metrics: Sequence[str],
        circuit_type: str,
        circuit_name: str,
        simulate_condition_path: Optional[Path] = None,
        output_path: Optional[Path] = None,
        ngspice_command: str = "ngspice",
        timeout_seconds: Optional[float] = 300.0,
        keep_workspace: bool = False,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.logger = logger or logging.getLogger(__name__)
        self.module_path = Path(__file__).resolve().parent
        self.testbench_path = self.module_path / "testbench"

        if not self.testbench_path.is_dir():
            raise FileNotFoundError(f"Testbench 目录不存在：{self.testbench_path}")
        if not isinstance(circuit_name, str) or not circuit_name.strip():
            raise ValueError("circuit_name 不能为空")

        supported_types = sorted(path.name for path in self.testbench_path.iterdir() if path.is_dir())
        if circuit_type not in supported_types:
            raise ValueError(f"circuit_type 必须在 {supported_types} 中，实际为 {circuit_type!r}")

        self.circuit_type = circuit_type
        self.circuit_name = circuit_name
        self.raw_metrics = list(metrics)
        if not self.raw_metrics:
            raise ValueError("metrics 不能为空")
        if len(set(self.raw_metrics)) != len(self.raw_metrics):
            raise ValueError("metrics 中存在重复指标")

        self.metrics = self._metric_remapping(self.raw_metrics, circuit_type)
        self.circuit_testbench_path = self.testbench_path / circuit_type
        self.simulate_condition_path = (
            self.circuit_testbench_path / "default_simulate_condition"
            if simulate_condition_path is None
            else Path(simulate_condition_path)
        )
        if not self.simulate_condition_path.is_dir():
            raise NotADirectoryError(f"仿真条件目录不存在：{self.simulate_condition_path}")

        self.output_path = (
            self.module_path.parent.parent / "simulate_result"
            if output_path is None
            else Path(output_path)
        )
        self.output_path.mkdir(parents=True, exist_ok=True)
        self.circuit_result_path = self.output_path / self.circuit_name
        self.circuit_result_path.mkdir(parents=True, exist_ok=True)
        self.workspace_root = self.circuit_result_path / ".workspaces"
        self.workspace_root.mkdir(parents=True, exist_ok=True)

        if not isinstance(ngspice_command, str) or not ngspice_command.strip():
            raise ValueError("ngspice_command 不能为空")
        if timeout_seconds is not None and timeout_seconds <= 0:
            raise ValueError("timeout_seconds 必须大于 0 或为 None")
        if not isinstance(keep_workspace, bool):
            raise TypeError("keep_workspace 必须是 bool")

        self.ngspice_command = ngspice_command
        self.timeout_seconds = timeout_seconds
        self.keep_workspace = keep_workspace
        self.logger.info(
            "Simulator 初始化完成：circuit=%s, metrics=%s, conditions=%s",
            self.circuit_name,
            self.raw_metrics,
            self.simulate_condition_path,
        )

    @staticmethod
    def _metric_remapping(metrics: Sequence[str], circuit_type: str) -> List[str]:
        if circuit_type != "single_ended_opamp":
            raise NotImplementedError(f"暂不支持的电路类型：{circuit_type}")
        unsupported = [metric for metric in metrics if metric not in SINGLE_OPAMP_METRIC2METRIC]
        if unsupported:
            raise ValueError(f"不支持的性能指标：{unsupported}")
        return [SINGLE_OPAMP_METRIC2METRIC[metric] for metric in metrics]

    def _get_testbench_name_lst(self) -> List[str]:
        result: List[str] = []
        for metric in self.raw_metrics:
            testbench_name = SINGLE_OPAMP_METRIC2TESTBENCH_NAME[metric]
            if testbench_name not in result:
                result.append(testbench_name)
        return result

    @staticmethod
    def _generate_workspace(run_workspace: Path, n_workers: int) -> None:
        for worker_id in range(n_workers):
            (run_workspace / f"workspace_{worker_id}").mkdir()

    def _copy_circuit(self, circuit_path: Path, run_workspace: Path) -> None:
        circuit_path = Path(circuit_path)
        if not circuit_path.is_dir():
            raise NotADirectoryError(f"电路目录不存在：{circuit_path}")

        circuit_file = circuit_path / f"{self.circuit_name}.sp"
        params_file = circuit_path / f"{self.circuit_name}_params.sp"
        if not circuit_file.is_file():
            raise FileNotFoundError(f"电路文件不存在：{circuit_file}")
        if not params_file.is_file():
            raise FileNotFoundError(f"参数文件不存在：{params_file}")

        source_items = [
            item
            for item in circuit_path.iterdir()
            if item.name not in self.GENERATED_NAMES and not item.name.startswith(".sampling-")
        ]
        for sub_workspace in sorted(run_workspace.iterdir()):
            if not sub_workspace.is_dir():
                continue
            for source in source_items:
                destination = sub_workspace / source.name
                if source.is_dir():
                    shutil.copytree(source, destination, dirs_exist_ok=True)
                else:
                    shutil.copy2(source, destination)

        self.logger.debug(
            "电路文件复制完成：source=%s, files=%d, workers=%d",
            circuit_path,
            len(source_items),
            len(list(run_workspace.iterdir())),
        )

    def _generate_testbench_copy(self, run_workspace: Path) -> None:
        modified_testbench: Dict[str, str] = {}

        for testbench_name in self._get_testbench_name_lst():
            tb_file_path = self.circuit_testbench_path / f"tb_{testbench_name}.cir"
            cond_file_path = self.simulate_condition_path / f"{testbench_name}_condition.json"
            if not tb_file_path.is_file():
                raise FileNotFoundError(f"未找到 Testbench：{tb_file_path}")
            if not cond_file_path.is_file():
                raise FileNotFoundError(f"未找到仿真条件文件：{cond_file_path}")

            try:
                simulate_condition = json.loads(cond_file_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"仿真条件文件不是合法 JSON：{cond_file_path}") from exc
            if not isinstance(simulate_condition, dict):
                raise TypeError(f"仿真条件文件顶层必须是 JSON object：{cond_file_path}")
            if "DUT_PATH" in simulate_condition:
                raise ValueError(f"{cond_file_path.name} 中不应定义 DUT_PATH")
            if self.circuit_type == "single_ended_opamp" and "IBIAS" in simulate_condition:
                raise ValueError(f"{cond_file_path.name} 中不应定义 IBIAS；偏置电流是 DUT 内的设计参数")

            content = tb_file_path.read_text(encoding="utf-8")
            for key, value in simulate_condition.items():
                content = content.replace(f"{{{{{key}}}}}", str(value))
            modified_testbench[testbench_name] = content

        unresolved_pattern = re.compile(r"\{\{[A-Za-z_][A-Za-z0-9_]*\}\}")
        for sub_workspace in sorted(run_workspace.iterdir()):
            if not sub_workspace.is_dir():
                continue
            dut_path = (sub_workspace / f"{self.circuit_name}.sp").resolve()
            if not dut_path.is_file():
                raise FileNotFoundError(f"Workspace 中不存在 DUT 文件：{dut_path}")

            for testbench_name, content in modified_testbench.items():
                workspace_content = content.replace("{{DUT_PATH}}", dut_path.as_posix())
                unresolved = sorted(set(unresolved_pattern.findall(workspace_content)))
                if unresolved:
                    raise ValueError(f"tb_{testbench_name}.cir 中存在未替换参数：{unresolved}")
                (sub_workspace / f"tb_{testbench_name}.cir").write_text(
                    workspace_content, encoding="utf-8"
                )

        self.logger.debug("Testbench 生成完成：%s", self._get_testbench_name_lst())

    def _rewrite_parameters(self, sub_workspace: Path, design_parameters: np.ndarray) -> None:
        workspace_param_path = sub_workspace / f"{self.circuit_name}_params.sp"
        # 本方法运行在子进程中，不向主进程的 RotatingFileHandler 写日志，
        # 避免多个进程同时轮转同一个日志文件。
        parameter_names = read_parameter_names(workspace_param_path)
        values = np.asarray(design_parameters, dtype=float)
        if values.ndim != 1 or len(values) != len(parameter_names):
            raise ValueError(
                "design_parameters 与参数文件中的参数数量不一致："
                f"values={len(values)}, parameters={len(parameter_names)}"
            )
        if not np.all(np.isfinite(values)):
            raise ValueError("design_parameters 中存在 NaN 或 Inf")
        rewrite_parameter_values(
            workspace_param_path,
            dict(zip(parameter_names, values.tolist())),
        )

    @staticmethod
    def _log_excerpt(content: str, limit: int = 10000) -> str:
        return content if len(content) <= limit else "...<truncated>...\n" + content[-limit:]

    def _run_testbench(self, sub_workspace: Path) -> Dict[str, Path]:
        log_paths: Dict[str, Path] = {}

        for testbench_name in self._get_testbench_name_lst():
            testbench_path = sub_workspace / f"tb_{testbench_name}.cir"
            if not testbench_path.is_file():
                raise FileNotFoundError(f"Workspace 中不存在 Testbench：{testbench_path}")

            log_path = sub_workspace / f"{testbench_name}.log"
            log_path.unlink(missing_ok=True)
            command = [
                self.ngspice_command,
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
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except FileNotFoundError as exc:
                raise FileNotFoundError(
                    f"未找到 ngspice 命令 {self.ngspice_command!r}，请确认已安装并加入 PATH"
                ) from exc
            except subprocess.TimeoutExpired as exc:
                output = exc.stdout or ""
                if isinstance(output, bytes):
                    output = output.decode("utf-8", errors="replace")
                raise SimulationRunError(
                    f"ngspice 仿真超时：testbench={testbench_path.name}, "
                    f"timeout={self.timeout_seconds}s\n{self._log_excerpt(output)}"
                ) from exc

            log_content = (
                log_path.read_text(encoding="utf-8", errors="replace")
                if log_path.exists()
                else process.stdout or ""
            )
            excerpt = self._log_excerpt(log_content)
            if process.returncode != 0:
                raise SimulationRunError(
                    f"ngspice 仿真失败：testbench={testbench_path.name}, "
                    f"workspace={sub_workspace}, returncode={process.returncode}\n{excerpt}"
                )
            if re.search(r"(?im)^\s*(fatal error|error:)", log_content):
                raise SimulationRunError(
                    f"ngspice log 中检测到错误：testbench={testbench_path.name}, "
                    f"workspace={sub_workspace}\n{excerpt}"
                )
            if not log_path.is_file():
                raise SimulationRunError(f"ngspice 未生成 log 文件：{log_path}")
            log_paths[testbench_name] = log_path

        return log_paths

    def _read_simulation_result(self, log_path_dict: Dict[str, Path]) -> np.ndarray:
        results: List[float] = []
        log_contents: Dict[str, str] = {}
        number_pattern = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"

        for raw_metric in self.raw_metrics:
            testbench_name = SINGLE_OPAMP_METRIC2TESTBENCH_NAME[raw_metric]
            result_name = SINGLE_OPAMP_METRIC2RESULT_NAME[raw_metric]
            if testbench_name not in log_path_dict:
                raise SimulationResultError(f"未找到 {testbench_name} 对应的 log 文件")
            if testbench_name not in log_contents:
                log_contents[testbench_name] = log_path_dict[testbench_name].read_text(
                    encoding="utf-8", errors="replace"
                )

            pattern = rf"(?im)^\s*{re.escape(result_name)}\s*=\s*({number_pattern})"
            matches = re.findall(pattern, log_contents[testbench_name])
            if not matches:
                raise SimulationResultError(
                    f"无法从 {testbench_name}.log 中读取指标 {raw_metric}，期望变量 {result_name}"
                )
            value = float(matches[-1])
            if not np.isfinite(value):
                raise SimulationResultError(f"指标 {raw_metric} 不是有限数值：{value}")
            results.append(value)

        return np.asarray(results, dtype=float)

    def _simulate_chunk(
        self,
        sub_workspace: Path,
        chunk: np.ndarray,
        sample_index_chunk: np.ndarray,
        continue_on_error: bool,
    ) -> Tuple[np.ndarray, List[Dict[str, Any]]]:
        results: List[np.ndarray] = []
        failures: List[Dict[str, Any]] = []

        for sample_index, design_parameters in zip(sample_index_chunk, chunk):
            self._rewrite_parameters(sub_workspace, design_parameters)
            try:
                log_paths = self._run_testbench(sub_workspace)
                simulation_result = self._read_simulation_result(log_paths)
            except (SimulationRunError, SimulationResultError) as exc:
                if not continue_on_error:
                    raise
                simulation_result = np.full(len(self.raw_metrics), np.nan, dtype=float)
                failures.append(
                    {
                        "sample_index": int(sample_index),
                        "design_parameters": design_parameters.tolist(),
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
            results.append(simulation_result)

        if not results:
            return np.empty((0, len(self.raw_metrics)), dtype=float), failures
        return np.vstack(results), failures

    def simulate_batch(
        self,
        circuit_path: Path,
        n_workers: int,
        design_parameters_array: np.ndarray,
        continue_on_error: bool = False,
    ) -> SimulationBatchResult:
        if isinstance(n_workers, bool) or not isinstance(n_workers, int):
            raise TypeError("n_workers 必须为整数")
        if n_workers <= 0:
            raise ValueError("n_workers 必须大于 0")
        if not isinstance(continue_on_error, bool):
            raise TypeError("continue_on_error 必须是 bool")

        circuit_path = Path(circuit_path)
        parameter_path = circuit_path / f"{self.circuit_name}_params.sp"
        parameter_names = read_parameter_names(parameter_path, logger=self.logger)
        design_array = np.asarray(design_parameters_array, dtype=float)
        if design_array.ndim != 2:
            raise ValueError("design_parameters_array 必须为二维数组")
        if design_array.shape[0] == 0:
            raise ValueError("design_parameters_array 不能为空")
        if design_array.shape[1] != len(parameter_names):
            raise ValueError(
                "设计参数维度与参数文件不一致："
                f"design={design_array.shape[1]}, parameters={len(parameter_names)}"
            )
        if not np.all(np.isfinite(design_array)):
            raise ValueError("design_parameters_array 中存在 NaN 或 Inf")

        effective_workers = min(n_workers, design_array.shape[0])
        run_workspace = Path(tempfile.mkdtemp(prefix="run_", dir=self.workspace_root))
        self.logger.info(
            "开始 SPICE 批量仿真：samples=%d, workers=%d, workspace=%s",
            design_array.shape[0],
            effective_workers,
            run_workspace,
        )

        try:
            self._generate_workspace(run_workspace, effective_workers)
            self._copy_circuit(circuit_path, run_workspace)
            self._generate_testbench_copy(run_workspace)
            design_chunks = np.array_split(design_array, effective_workers)
            index_chunks = np.array_split(np.arange(design_array.shape[0]), effective_workers)

            if effective_workers == 1:
                worker_results = [
                    self._simulate_chunk(
                        run_workspace / "workspace_0",
                        design_chunks[0],
                        index_chunks[0],
                        continue_on_error,
                    )
                ]
            else:
                futures = []
                with ProcessPoolExecutor(max_workers=effective_workers) as executor:
                    for worker_id, (chunk, index_chunk) in enumerate(zip(design_chunks, index_chunks)):
                        futures.append(
                            executor.submit(
                                self._simulate_chunk,
                                run_workspace / f"workspace_{worker_id}",
                                chunk,
                                index_chunk,
                                continue_on_error,
                            )
                        )
                    worker_results = [future.result() for future in futures]

            result_array = np.vstack([result for result, _ in worker_results])
            failure_records = sorted(
                [failure for _, failures in worker_results for failure in failures],
                key=lambda record: int(record["sample_index"]),
            )
            if failure_records:
                self.logger.warning(
                    "SPICE 批量仿真完成但存在失败点：failed=%d/%d",
                    len(failure_records),
                    design_array.shape[0],
                )
            else:
                self.logger.info("SPICE 批量仿真完成：samples=%d", design_array.shape[0])
            return SimulationBatchResult(result_array, tuple(failure_records))
        except Exception:
            self.logger.exception("SPICE 批量仿真异常：workspace=%s", run_workspace)
            raise
        finally:
            if self.keep_workspace:
                self.logger.info("保留仿真 workspace：%s", run_workspace)
            else:
                shutil.rmtree(run_workspace, ignore_errors=True)
                self.logger.debug("已清理仿真 workspace：%s", run_workspace)

    def simulate(
        self,
        circuit_path: Path,
        n_workers: int,
        design_parameters_array: np.ndarray,
        continue_on_error: bool = False,
    ) -> np.ndarray:
        return self.simulate_batch(
            circuit_path,
            n_workers,
            design_parameters_array,
            continue_on_error,
        ).metrics

    def write_simulate_result(
        self,
        design_parameters: np.ndarray,
        metrics: np.ndarray,
        design_parameter_name_lst: Optional[List[str]] = None,
    ) -> None:
        """兼容旧接口；新 Controller 直接使用 SamplingHistoryStore。"""

        if design_parameter_name_lst is None:
            raise ValueError("必须指定 design_parameter_name_lst")
        design_array = np.asarray(design_parameters, dtype=float)
        metric_array = np.asarray(metrics, dtype=float)
        if design_array.ndim == 1:
            design_array = design_array.reshape(1, -1)
        if metric_array.ndim == 1:
            metric_array = metric_array.reshape(1, -1)

        store = SamplingHistoryStore(
            self.circuit_result_path,
            self.circuit_name,
            self.circuit_type,
            design_parameter_name_lst,
            self.metrics,
            logger=self.logger,
        )
        allocation = {"external": int(design_array.shape[0])}
        run_id = store.create_run(
            int(design_array.shape[0]),
            1,
            allocation,
            {"source": "Simulator.write_simulate_result"},
        )
        failures = [
            {
                "sample_index": index,
                "error_type": "NonFiniteMetric",
                "error": "外部结果包含 NaN 或 Inf",
            }
            for index, row in enumerate(metric_array)
            if not np.all(np.isfinite(row))
        ]
        try:
            store.write_batch(
                run_id,
                design_array,
                metric_array,
                ["external"] * len(design_array),
                failures,
            )
            store.mark_run_completed(run_id, len(failures))
            store.export_csv()
        except Exception as exc:
            store.mark_run_failed(run_id, exc)
            raise
