import csv, shutil, json
import numpy as np
from pathlib import Path
from typing import List, Optional, Any, Dict

SINGLE_OPAMP_METRIC2METRIC = { 
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


class Simulator:
    
    def __init__(self, 
                circuit_path: Path, 
                metrics: List[str],
                circuit_type: str, 
                circuit_name: str, 
                simulate_condition_path: Optional[Path] = None,
                output_path: Optional[Path] = None
                ) -> None:
        
        pwd_path = Path(__file__).absolute().resolve().parent
        testbench_path = pwd_path / "testbench"
        
        if not testbench_path.exists():
            raise FileNotFoundError(f"Testbench 目录不存在: {testbench_path}")
            
        type_name_lst = [p.name for p in testbench_path.iterdir() if p.is_dir()]
        if circuit_type not in type_name_lst:
            raise ValueError(f"Circuit type 必须在 {type_name_lst} 中，现在传入的参数为：{circuit_type}")
            
        self.circuit_type = circuit_type
        self.circuit_name = circuit_name
        self.raw_metrics = metrics
        self.metrics = self._metric_remapping(metrics, circuit_type)
        self.circuit_testbench_path = testbench_path / circuit_type # 对应电路testbench所在文件夹的路径
        
        if simulate_condition_path is None:
            self.simulate_condition_path = self.circuit_testbench_path / "default_simulate_condition"
        else:
            self.simulate_condition_path = simulate_condition_path # 仿真条件路径
            
        if output_path is None:
            self.output_path = pwd_path.parent.parent / "simulate_result"
        else:
            self.output_path = output_path
        self.output_path.mkdir(parents=True, exist_ok=True)
        
        self.circuit_path = circuit_path # 电路所在的文件夹的路径
        
        self.workspace_path = pwd_path / "workspace"
        if self.workspace_path.exists():
            shutil.rmtree(self.workspace_path)
        self.workspace_path.mkdir()
    
    def _metric_remapping(self, metrics: List[str], circuit_type: str) -> List[str]:
        if circuit_type == "single_ended_opamp":
            return [SINGLE_OPAMP_METRIC2METRIC[metric] for metric in metrics]
        else:
            raise NotImplementedError(f"暂不支持的电路类型: {circuit_type}")
        
    def _generate_workspace(self, work_space: Path, n_workers) -> None:
        
        for number in range(n_workers):
            sub_work_space = work_space / f"_{number}"
            sub_work_space.mkdir()
            
    def _generate_testbench_copy(self) -> None:
        
        # 首先通过raw_metrics确认要调用哪些testbench脚本
        testbench_name_lst = []
        modified_testbench = {}
        for raw_metric in self.raw_metrics:
            if SINGLE_OPAMP_METRIC2TESTBENCH_NAME[raw_metric] not in testbench_name_lst:
                testbench_name_lst.append(SINGLE_OPAMP_METRIC2TESTBENCH_NAME[raw_metric])
        # 载入对应的testbench脚本内容和仿真设置条件
        for testbench_name in testbench_name_lst:
            tb_file_path = self.circuit_testbench_path / f"tb_{testbench_name}.cir"
            cond_file_path = self.simulate_condition_path / f"{testbench_name}_condition.json"
            if not tb_file_path.exists():
                raise FileNotFoundError(f"未找到 Testbench 脚本: {tb_file_path}")
            if not cond_file_path.exists():
                raise FileNotFoundError(f"未找到仿真条件文件: {cond_file_path}")
            testbench_content = tb_file_path.read_text(encoding='utf-8')
            simulate_condition: Dict[str, Any] = json.loads(cond_file_path.read_text(encoding='utf-8'))
            for key, value in simulate_condition.items():
                testbench_content = testbench_content.replace( f"{{{{{key}}}}}", str(value))
            modified_testbench[testbench_name] = testbench_content
        for sub_workspace in self.workspace_path.iterdir():
            if not sub_workspace.is_dir():
                continue
            for target_name, target_content in modified_testbench.items():
                target_testbench_file = sub_workspace / f"tb_{target_name}.cir"
                target_testbench_file.write_text(target_content, encoding='utf-8')
    
    def write_simulate_result(self, 
                            design_parameters: np.ndarray, 
                            metrics: np.ndarray, 
                            design_parameter_name_lst: Optional[List[str]] = None) -> None:
        
        circuit_result_path = self.output_path / self.circuit_name
        circuit_result_path.mkdir(parents=True, exist_ok=True)  # 确保电路结果文件夹存在
        
        design_csv_path = circuit_result_path / "design_parameters.csv"
        metrics_csv_path = circuit_result_path / "metrics.csv"
        
        # 1. 处理设计参数
        is_first_design = not design_csv_path.exists()
        with open(design_csv_path, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if is_first_design:
                if design_parameter_name_lst is None:
                    raise ValueError("第一次保存仿真结果必须指定 design_parameter_name_lst。")
                writer.writerow(design_parameter_name_lst)
            # 使用 writerow 写入单行数据
            writer.writerow(design_parameters.tolist())
            
        # 2. 处理仿真结果
        is_first_metric = not metrics_csv_path.exists()
        with open(metrics_csv_path, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if is_first_metric:
                writer.writerow(self.metrics)
            # 使用 writerow 写入单行数据
            writer.writerow(metrics.tolist())