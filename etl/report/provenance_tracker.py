import json
import os
from datetime import datetime, timezone


class ProvenanceTracker:

    def __init__(self, output_file):

        self.output_file = output_file

    def write(self, metadata):

        metadata["timestamp"] = datetime.now(timezone.utc).isoformat()

        os.makedirs(os.path.dirname(self.output_file), exist_ok=True)

        with open(self.output_file, "w") as f:
            json.dump(metadata, f, indent=4)