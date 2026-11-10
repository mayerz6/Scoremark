import os


class ArtifactValidator:
    def __init__(self, output_folder: str, garbage_folder: str):
        self.output_folder = output_folder
        self.garbage_folder = garbage_folder

    def summary(self):
        processed = len(os.listdir(self.output_folder))
        garbage = len(os.listdir(self.garbage_folder))

        return {
            "processed_files": processed,
            "garbage_files": garbage
        }