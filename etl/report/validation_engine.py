import pandas as pd
import re
import matplotlib.pyplot as plt


class ValidationEngine:

    def __init__(self, file_path):

        self.file_path = file_path

        self.email_errors = []
        self.username_errors = []

        self.total_rows = 0

    def validate_emails(self, email_series):

        email_pattern = re.compile(
            r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        )

        for i, email in enumerate(email_series):

            if pd.isnull(email) or str(email).strip() == "":
                continue

            if not re.match(email_pattern, str(email)):
                self.email_errors.append(
                    f"Invalid email at row {i+1}: {email}"
                )

    def validate_usernames(self, name_series):

        # \w is Unicode-aware in Python's re for str patterns -- it matches
        # letters in any script (Cyrillic included), not just a-zA-Z. The
        # original ASCII-only pattern was rejecting ~99.9% of this file's
        # genuinely Cyrillic names as "invalid," which was never a real
        # data problem -- the rule just assumed Latin-alphabet names. See
        # handoff.md's "Known gaps" section for how this was found.
        name_pattern = re.compile(
            r'^[\w&|#(). ]+$', re.UNICODE
        )

        for i, name in enumerate(name_series):

            if not re.match(name_pattern, str(name)):
                self.username_errors.append(
                    f"Invalid username at row {i+1}: {name}"
                )

    def run(self):

        df = pd.read_csv(self.file_path, low_memory=False)

        self.total_rows = len(df)

        self.validate_emails(df["email"])
        self.validate_usernames(df["firstname"])

        self.report()

    def report(self):

        total_errors = (
            len(self.email_errors) +
            len(self.username_errors)
        )

        print("\nVALIDATION REPORT")
        print("------------------")

        print("Rows Tested:", self.total_rows)
        print("Total Errors:", total_errors)

        print("Email Errors:", len(self.email_errors))
        print("Username Errors:", len(self.username_errors))

    def visualize(self, reports_dir):
        """
        reports_dir: the dataset's reports folder -- see
        etl/report/report_paths.reports_dir_for(). Returns the chart's path.

        Called explicitly by the entry point (like the other engines'
        visualize()), not from report() -- report() doesn't know which
        dataset it's reporting on, so it can't know where the chart goes.
        """
        import os
        os.makedirs(reports_dir, exist_ok=True)
        output_path = os.path.join(reports_dir, "validation_errors.png")

        columns = ["Email Errors", "Username Errors"]
        counts = [
            len(self.email_errors),
            len(self.username_errors)
        ]

        plt.figure(figsize=(10,6))
        plt.bar(columns, counts)

        plt.title("Dataset Validation Errors")
        plt.ylabel("Error Count")

        # savefig(), not show(): show() opens an interactive Tkinter window,
        # which works fine run by hand but does nothing useful (and nothing
        # a web server could display) once this runs inside a Flask request
        # handler -- see handoff.md's chart-export section for how this was
        # found before it became a confusing failure in the frontend work.
        plt.savefig(output_path)
        plt.close()
        print(f"Validation chart saved to {output_path}")
        return output_path