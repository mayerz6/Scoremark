import pandas as pd
import matplotlib.pyplot as plt
from collections import Counter


class DeduplicationEngine:

    def __init__(self, input_file, subset_columns):

        self.input_file = input_file
        self.subset_columns = subset_columns

        self.records_raw = 0
        self.records_clean = 0
        self.records_duplicates = 0

    def run(self):

        print(f"\nRunning Deduplication Engine on {self.input_file}")

        # Every value read as text, blanks kept as "". pandas' defaults
        # would infer phone as a number -- "0562020114" came back out as
        # "562020114.0" -- and turn blanks into NaN.
        df = pd.read_csv(self.input_file, dtype=str, keep_default_na=False)

        self.records_raw = len(df)

        subset_filtered = [
            col for col in self.subset_columns if col in df.columns
        ]

        mask_duplicates = self.duplicate_mask(df, subset_filtered)

        duplicates_df = df[mask_duplicates]
        cleaned_df = df[~mask_duplicates]

        self.records_duplicates = len(duplicates_df)
        self.records_clean = len(cleaned_df)

        clean_file = self.input_file.replace(".csv", "_deduplicated.csv")
        duplicates_file = self.input_file.replace(".csv", "_duplicates.csv")

        cleaned_df.to_csv(clean_file, index=False)
        duplicates_df.to_csv(duplicates_file, index=False)

        self.report()

        return clean_file

    @staticmethod
    def duplicate_mask(df, key_columns):
        """
        True for every row that repeats an earlier row's key (first
        occurrence, in file order, is kept).

        Keys are compared normalized -- trimmed and lowercased -- so the
        same customer exported as "KAMAL@x.com" by one source and
        "kamal@x.com" by another is caught. Only the comparison is
        normalized; the values written out are untouched.

        A row whose key columns are ALL blank is never a duplicate: blank
        means "unknown," not "the same." Without this, every record with
        no email and no phone (valid, since both are optional) collapsed
        into the first one, silently deleting different people.
        """
        if not key_columns:
            return pd.Series(False, index=df.index)

        keys = df[key_columns].apply(lambda col: col.str.strip().str.lower())
        has_any_key = keys.ne("").any(axis=1)
        return keys.duplicated(keep="first") & has_any_key

    def report(self):

        print("\nDEDUPLICATION REPORT")
        print("--------------------")

        print("Raw Records:", self.records_raw)
        print("Clean Records:", self.records_clean)
        print("Dropped Duplicates:", self.records_duplicates)

        if not self.records_raw:
            print("No records to deduplicate.")
            return

        print(
            f"Duplicate Rate: {(self.records_duplicates / self.records_raw) * 100:.2f}%"
        )

        print(
            f"Retention Rate: {(self.records_clean / self.records_raw) * 100:.2f}%"
        )

    def visualize(self, reports_dir):
        """
        reports_dir: the dataset's reports folder -- see
        etl/report/report_paths.reports_dir_for(). Returns the chart's path.
        """
        import os
        os.makedirs(reports_dir, exist_ok=True)
        output_path = os.path.join(reports_dir, "deduplication.png")

        labels = ["Raw", "Clean", "Duplicates"]
        values = [
            self.records_raw,
            self.records_clean,
            self.records_duplicates
        ]

        plt.figure(figsize=(8,6))
        plt.bar(labels, values)
        plt.title("Deduplication Results")

        # savefig(), not show() -- see ValidationEngine.visualize()'s
        # comment for why: show() needs a display to open a window on,
        # which a web server process doesn't have.
        plt.savefig(output_path)
        plt.close()
        print(f"Deduplication chart saved to {output_path}")
        return output_path