class Pipeline:
    def __init__(self, extractor, transformer, loader, garbage_loader, config=None):
        self.cfg = config
        self.extractor = extractor
        self.transformer = transformer
        self.loader = loader
        self.garbage_loader = garbage_loader

    def run(self):
        valid = []
        garbage = []
        
        for raw in self.extractor.extract():
            result = self.transformer.transform(raw)
            if result:
                valid.append(result)
            else:
                garbage.append(raw)

        # Load clean records
        self.loader.load(valid)
        if not valid:
            print("WARNING: 0 valid rows produced -- wrote a header-only output file.")

        # Load garbage records
        if garbage:
            self.garbage_loader.load(garbage)

        print("----- ETL Summary -----")
        print(f"Valid rows: {len(valid)}")
        print(f"Garbage rows: {len(garbage)}")

        return len(valid), len(garbage)


def run_pipeline_for_folder(input_folder, output_folder, garbage_folder, build_pipeline):
    """
    Runs one Pipeline per file found in `input_folder` (every `*.csv`),
    instead of one hardcoded file path -- the folder-processing idea from
    the exploratory notebook, deliberately scoped down to "one whole file
    per run" rather than "split one huge file into byte-size chunks."
    Each file stays independently valid and is never torn across a
    boundary, so there's no cross-chunk bookkeeping (header duplication,
    a row split mid-line, deduplication state that must survive chunk
    boundaries) to get wrong -- see docs/ETL_HANDOFF.md for the chunking
    bug this specifically avoids.

    build_pipeline: a function (input_path, output_path, garbage_path) -> Pipeline,
        so this stays agnostic to which schema/rules/loaders a particular
        tool uses -- main.py and main_hybrid.py each pass their own.

    One bad file doesn't stop the batch: if a single file's Pipeline.run()
    raises, it's recorded and every other file in the folder still runs.
    Returns a summary dict with per-file results and the totals.
    """
    import os

    os.makedirs(output_folder, exist_ok=True)
    os.makedirs(garbage_folder, exist_ok=True)

    results = {}
    total_valid = 0
    total_garbage = 0

    csv_files = sorted(f for f in os.listdir(input_folder) if f.endswith(".csv"))

    for filename in csv_files:
        input_path = os.path.join(input_folder, filename)
        output_path = os.path.join(output_folder, filename)
        garbage_path = os.path.join(garbage_folder, f"garbage_{filename}")

        print(f"\n=== Processing {filename} ===")

        try:
            pipeline = build_pipeline(input_path, output_path, garbage_path)
            valid_count, garbage_count = pipeline.run()
            results[filename] = {"valid": valid_count, "garbage": garbage_count, "error": None}
            total_valid += valid_count
            total_garbage += garbage_count
        except Exception as e:
            print(f"FAILED to process {filename}: {e}")
            results[filename] = {"valid": 0, "garbage": 0, "error": str(e)}

    print("\n----- Folder Batch Summary -----")
    print(f"Files processed: {len(csv_files)}")
    print(f"Total valid rows: {total_valid}")
    print(f"Total garbage rows: {total_garbage}")
    failed = [f for f, r in results.items() if r["error"]]
    if failed:
        print(f"Files that failed entirely: {failed}")

    return {"per_file": results, "total_valid": total_valid, "total_garbage": total_garbage}