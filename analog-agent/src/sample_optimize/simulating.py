import csv
import numpy  as np

from pathlib import Path
from typing import List, Optional

SINGLE_OPAMP_METRIC = { # 将外部输入的同一性能名称转换为具体电路类型testbench下的名称
    "DC_GAIN": "DC_Gain_dB",
    "UGF": "UGF_Hz",
    "PM": "Phase_Margin_deg",
    "CMRR": "CMRR_dB",
    "P_PSRR": "PSRR_Plus_dB",
    "N_PSRR": "PSRR_Minus_dB",
    "P_SR": "Slew_Rise_V_us",
    "N_SR": "Slew_Fall_V_us",
    "POWER": "Power_Quiescent_uW"
}

class Simulator:
    
    def __init__(self, 
                circuit_path: Path, 
                metrics: List[str],# 性能指标名称
                circuit_type: str, # 输入为单输出运放，双输出运放，比较器等
                circuit_name: str, # 电路名称
                simulate_condition_path: Optional[Path] = None,
                output_path: Optional[Path] = None
                ) -> None:
        
        pwd_path = Path(__file__).absolute().resolve().parent
        testbench_path = pwd_path / "testbench"
        type_name_lst = [p.name for p in testbench_path.iterdir() if p.is_dir()]
        if circuit_type not in type_name_lst:
            raise ValueError(f"Circuit type 必须在 {type_name_lst} 中，现在传入的参数为：{circuit_type}")
        self.circuit_type = circuit_type
        self.circuit_name = circuit_name
        self.metrics = self._metric_remapping(metrics, circuit_type)
        self.circuit_testbench_path = testbench_path / circuit_type
        if simulate_condition_path is None:
            self.simulate_condition_path = self.circuit_testbench_path / "default_simulate_condition"
        else:
            self.simulate_condition_path = simulate_condition_path
        if output_path is None:
            self.output_path = pwd_path.parent.parent / "simulate_result"
            self.output_path.mkdir(exist_ok=True)
        else:
            self.output_path = output_path
        self.circuit_path = circuit_path
    
    def _metric_remapping(self, metrics: List[str], circuit_type: str) -> List[str]:
        
        if circuit_type == "single_ended_opamp":
            return [SINGLE_OPAMP_METRIC[metric] for metric in metrics]
        else: #！ 后续补充其它电路类型
            pass
        
    def write_simulate_result(self, design_parameters: np.ndarray, metrics: np.ndarray, design_parameter_name_lst: Optional[List[str]] = None) -> None:
        
        circuit_result_path = self.output_path / self.circuit_name
        design_parameters_csv = circuit_result_path / "design_parameters.csv"
        metrics_csv_path = circuit_result_path / "metrics.csv"
        if circuit_result_path.exists():
            with open(design_parameters_csv, mode='a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(design_parameters.tolist())
            with open(metrics_csv_path, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(metrics.tolist())
        else:
            if design_parameter_name_lst is None:
                raise ValueError("第一次保存仿真结果必须指定设计参数名称。")
            with open(design_parameters_csv, mode='a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                if design_parameters_csv.stat().st_size == 0 and design_parameter_name_lst:
                    writer.writerow(design_parameter_name_lst)
                writer.writerows(design_parameters.tolist())
            with open(metrics_csv_path, mode='a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                if metrics_csv_path.stat().st_size == 0:
                    writer.writerow(self.metrics)
                writer.writerows(metrics.tolist())