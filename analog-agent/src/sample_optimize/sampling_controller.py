from pathlib import Path
from random_sampling import Random_Sampler
from lhs_sampling import LHS_Sampler
from sobol_sampling import Sobol_Sampler
from typing import List
from ..utils import read_parameter_names

class Sampling_Controller:
    
    def __init__(
        self,
        src_path: Path,
        circuit_name: str,
        circuit_type: str,
        target_path: Path,
        ) -> None:
        
        parameters_name_lst = read_parameter_names(src_path / f"{circuit_name}_params.sp")
        