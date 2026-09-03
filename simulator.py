from typing import Dict
from pathlib import Path
import re, subprocess

FILE_NAME = "ota_params.sp"

def simulate(params: Dict[str, float], path: Path) -> float:
    
    params_path = path / FILE_NAME
    log_path = path / "logs" / "ac.log"
    if not params_path.exists():
        raise FileNotFoundError(f"{FILE_NAME} not found in {path}")
    content = params_path.read_text()
    for param, val in params.items():
        pattern = rf"(\.param\s+{param}\s*=\s*)\S+"
        content = re.sub(pattern, rf"\g<1>{val}", content)
    params_path.write_text(content)
    subprocess.run([
        "ngspice", "-b", "-o", "logs/ac.log", "tb_ac.cir"
    ], cwd=path, check=True
    )
    if not log_path.exists():
        raise FileNotFoundError(f"ac.log not found in {str(log_path)}")
    metric_content = log_path.read_text()
    pattern = r"(dc_gain_db\s*=\s*\S+)"
    all_dc_gain = re.findall(pattern, metric_content)
    if len(all_dc_gain) == 0:
        raise ValueError("Can not get dc_gain_db")
    dc_gain: str = all_dc_gain[0]
    dc_gain = dc_gain.split("=")[1].strip()
    
    return float(dc_gain)
    
if __name__  == '__main__':
    simulate(
        {
            "WIN_VAL": 5,
            "WLOAD_VAL": 10,
            "WTAIL_VAL": 10
        },
        Path("./test/ota5")
    )