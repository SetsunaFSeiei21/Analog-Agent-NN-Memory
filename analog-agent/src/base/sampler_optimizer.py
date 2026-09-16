from typing import Sequence, Tuple, List
from pathlib import Path
from abc import ABC, abstractmethod

class Sampler_Optimizer(ABC):
    
    def __init__(self, circuit_param_path: Path, parameter_name_lst: Sequence[str], bounds: Sequence[Tuple[float, float, float]], seed: int = 42) -> None:
        
        self.circuit_param_path = circuit_param_path
        self.parameter_name_lst: List[str] = list(parameter_name_lst)
        self.bounds: List[Tuple[float, float]] = list(bounds)
        self.seed = seed
        assert len(self.parameter_name_lst) == len(self.bounds), f"parameter_name_lst的长度必须等于bounds的长度!但parameter_name_lst的长度为{len(parameter_name_lst)}, bounds的长度为{len(bounds)}"
        
    def rewrite_param(self, value_lst: List[float]) -> None:
        
        if len(self.parameter_name_lst) != len(self.bounds):
            raise ValueError(
                "参数名称数量与参数范围数量不一致："
                f"{len(self.parameter_name_lst)} != {len(self.bounds)}"
            )
        write_content_lst = []
        for parameter_name, value in zip(self.parameter_name_lst, value_lst):
            write_content_lst.append(f".param {parameter_name}    = {value}")
        content_text = "\n".join(write_content_lst) + "\n"
        with open(self.circuit_param_path, mode = "w") as f:
            f.write(content_text)
    
    @abstractmethod
    def generate_sample_point(self, n_point: int, n_workers: int) -> List[List[float]]:
        
        "生成采样点"
        raise NotImplementedError