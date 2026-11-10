import csv
from collections import Counter

class DataQualityEngine:
    def __init__(self, file_path, rules):
        self.file_path = file_path
        self.rules = rules
        self.total_rows = 0
        self.missing_email = 0
        self.missing_phone = 0
        self.invalid_email = 0

        self.email_domains = Counter()
        self.phone_numbers = Counter()


    def run(self):
        # Implement the logic to read the dataset, apply the rules, and generate a report
        print(f"Running Data Quality Engine on {self.file_path} with {len(self.rules)} rules.")

        with open(self.file_path, encoding="utf-8") as f:

            reader = csv.DictReader(f)

            for row in reader:

                self.total_rows += 1

                email = row.get("email")
                phone = row.get("phone")

                if not email:
                    self.missing_email += 1
                else:
                    domain = email.split("@")[-1]
                    self.email_domains[domain] += 1

                if not phone:
                    self.missing_phone += 1
                else:
                    self.phone_numbers[phone] += 1

        self.report()

    def report(self):

        print("\nDATA QUALITY REPORT")
        print("-------------------")

        print("Total rows:", self.total_rows)
        print("Missing email:", self.missing_email)
        print("Missing phone:", self.missing_phone)

        print("\nTop Email Domains")

        for domain, count in self.email_domains.most_common(10):
            print(domain, count)