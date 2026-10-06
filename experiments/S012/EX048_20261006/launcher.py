import os
import runpy
from pathlib import Path
if __name__=='__main__':
    for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
        os.environ[name]='1'
    runpy.run_path(str(Path(__file__).with_name('execution_driver.py')),run_name='__main__')
