"""3Shape CAMair (Produce) Partner Integration Component.

CAMair is 3Shape's CAM module. It acts as the gRPC CLIENT and connects to a
Partner Integration Component (PIC) — the gRPC SERVER implemented here — to hand
over designed cases and then poll their manufacturing status.

The generated protobuf modules import each other by bare name (`import
CAMairDataTypes_pb2`), because the .proto files use flat imports. Putting
`_generated` on sys.path is the standard way to make that resolve without
rewriting every generated file.
"""

import sys
from pathlib import Path

_GENERATED_DIR = Path(__file__).parent / "_generated"
if str(_GENERATED_DIR) not in sys.path:
    sys.path.insert(0, str(_GENERATED_DIR))
