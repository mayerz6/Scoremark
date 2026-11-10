from collections import Counter

import matplotlib.pyplot as plt


class RuleTracker:

    def __init__(self):
        self.failures = Counter()

    def record_failure(self, rule_name):
        self.failures[rule_name] += 1

    def report(self):

        print("\nRULE FAILURE REPORT")
        print("-------------------")

        for rule, count in self.failures.items():
            print(f"{rule}: {count}")

    def visualize(self, reports_dir):
        """
        Bar chart of rejection reasons -- ported from the exploratory
        notebook's chart_garbage_reasons(), which is more informative than
        the plain-text report() above: a recruiter or future-you can see
        at a glance which single rule is responsible for most of the
        garbage file, instead of reading a list of numbers.

        reports_dir: the dataset's reports folder -- see
        etl/report/report_paths.reports_dir_for(). Returns the chart's path,
        or None if there was nothing to chart.
        """
        if not self.failures:
            print("No rule failures recorded -- nothing to chart.")
            return None

        import os
        os.makedirs(reports_dir, exist_ok=True)
        output_path = os.path.join(reports_dir, "rule_failures.png")

        rules = list(self.failures.keys())
        counts = [self.failures[r] for r in rules]

        plt.figure(figsize=(10, 6))
        bars = plt.bar(rules, counts)
        plt.xlabel("Rule")
        plt.ylabel("Rows Rejected")
        plt.title("Garbage Rows by Rejecting Rule")
        plt.xticks(rotation=20, ha="right")

        for bar in bars:
            height = bar.get_height()
            plt.text(bar.get_x() + bar.get_width() / 2, height, f"{int(height):,}",
                      ha="center", va="bottom")

        plt.tight_layout()
        # savefig(), not show() -- see ValidationEngine.visualize()'s
        # comment for why.
        plt.savefig(output_path)
        plt.close()
        print(f"Rule failure chart saved to {output_path}")
        return output_path