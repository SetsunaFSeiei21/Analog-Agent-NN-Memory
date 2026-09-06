import re

from pathlib import Path
from typing import List, Tuple

class SpectreSizingSimulator:
    
    def __init__(self, path: Path):
        
        self.path = path
        self.bounds, self.param_order = self._get_bounds()
        
    def _get_bounds(self) -> Tuple[List[Tuple[float, float]], List[str]]:
        
        param_file = self.path / "ota_params.sp"
        if not param_file.exists():
            raise FileNotFoundError(f"ota_params.sp not found in {self.path}")
        content = param_file.read_text()
        lines = content.splitlines()
        pattern = r"\.param\s+(?P<param_name>\w+)\s*="
        param_lst = re.findall(pattern, content)
        print(param_lst)
        
        return [], []
        
if __name__ == '__main__':
    spec = SpectreSizingSimulator(Path("test/ota5"))