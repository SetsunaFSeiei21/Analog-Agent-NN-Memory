import numpy as np

from pathlib import Path
from typing import List, Sequence, Tuple
from ..base import Sampler_Optimizer
from multiprocessing import Pool

class Random_Sampler(Sampler_Optimizer):
    
    def __init__(self, circuit_param_path: Path, parameter_name_lst: Sequence[str], bounds: Sequence[Tuple[float, float, float]], seed: int = 42):
        
        super().__init__(circuit_param_path, parameter_name_lst, bounds, seed)
        
    def generate_sample_point(self, n_points: int, n_workers: int) -> List[List[str]]:
        
        def generate_chunk(args: Tuple[np.random.SeedSequence, int]) -> np.ndarray:
            
            seed_seq, chunck_size = args
            rng = np.random.Generator(np.random.PCG64(seed_seq))
            columns = []
            for lower_bound, higher_bound, step in self.bounds:
                grid = np.arange(lower_bound, higher_bound + step / 2, step)
                col = rng.choice(grid, size = chunck_size)
                columns.append(col)
            
            return np.column_stack(columns)
        
        if n_workers == 0:
            raise ValueError(f"n_workers must not be 0!")
        chunck_size = n_points // n_workers
        seed_seqs = np.random.SeedSequence(self.seed).spawn(n_workers)
        tasks = [(seed_seq, chunck_size) for seed_seq in seed_seqs]
        with Pool(n_workers) as pool:
            chuncks = pool.map(generate_chunk, tasks)
        result = np.concatenate(chuncks, axis=0)
        
        return result