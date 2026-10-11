"""Local source-only successor of reviewed management closeout; not execution."""
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / 'pyproject.toml').exists())
source = (ROOT / '.tmp/s013-management-closeout/postprocess.py').read_text('utf-8')
source = source.replace('management closeout draft', 'single gap exit closeout draft')
source = source.replace("ROOT / '.tmp/s013-management-runner'", "ROOT / '.tmp/s013-gap-exit-runner'")
source = source.replace('8a9d86a30d1c5f98a4a621ef1dc4c26387ec7db0e1f365e8fc28952b364e82e8', '4c665de0464dcf8949272ce331d618a5d39509592c587023557253e600a34af0')
source = source.replace("('B0', 'N_LOCK', 'N_CURRENT')", "('B0', 'N_GAP_EXIT')")
source = source.replace("key = 'lock' if label == 'N_LOCK' else 'current'", "key = ''")
source = source.replace("contract.method['reservation'][key + '_center']", "contract.method['reservation']['center']")
source = source.replace("contract.method['reservation'][key + '_points']", "contract.method['reservation']['points']")
source = source.replace("contract.method['reservation']['lock_center' if label == 'N_LOCK' else 'current_center']", "contract.method['reservation']['center']")
source = source.replace("management-closeout-", "gap-exit-closeout-")
(HERE / 'postprocess.py').write_text(source, 'utf-8')
