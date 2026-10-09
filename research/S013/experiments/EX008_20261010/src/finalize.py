"""Sequential completion of public assessment, quality audit, assembly and FULL validation."""
from pathlib import Path
import subprocess
import sys

def main():
    code=Path(__file__).resolve().parent
    for script,args in (('assess.py',()),('quality.py',()),('deliver.py',()),('deliver.py',('--validate-only',))):
        print({'phase':script,'arguments':args,'status':'START'},flush=True)
        subprocess.run((sys.executable,str(code/script),*args),check=True)
        print({'phase':script,'arguments':args,'status':'COMPLETE'},flush=True)

if __name__=='__main__':
    main()
