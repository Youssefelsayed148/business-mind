"""Remove Pydantic's partial synthetic settings value from failed harness logs."""
from pathlib import Path
import re

root = Path(__file__).resolve().parent
for name in ('registry.log', 'fixed-empty-head.log', 'fixed-drift.log'):
    path = root / name
    text = path.read_text(encoding='utf-8')
    text = re.sub(r'input_value=.*?, input_type=dict',
                  'input_value=[synthetic settings redacted], input_type=dict', text)
    path.write_text(text, encoding='utf-8')
print('Sanitized three failed harness logs; failure diagnostics retained.')
