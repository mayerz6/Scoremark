import csv


class StreamingDeduplicator:

    def __init__(self, input_file, output_file, duplicate_file, key_fields):

        self.input_file = input_file
        self.output_file = output_file
        self.duplicate_file = duplicate_file
        self.key_fields = key_fields

        self.seen = set()

    def run(self):

        with open(self.input_file, encoding="utf-8") as infile, \
             open(self.output_file, "w", newline="", encoding="utf-8") as outfile, \
             open(self.duplicate_file, "w", newline="", encoding="utf-8") as dupfile:

            reader = csv.DictReader(infile)

            writer = csv.DictWriter(outfile, fieldnames=reader.fieldnames)
            dup_writer = csv.DictWriter(dupfile, fieldnames=reader.fieldnames)

            writer.writeheader()
            dup_writer.writeheader()

            for row in reader:

                key = tuple(row.get(field, "") for field in self.key_fields)

                if key in self.seen:
                    dup_writer.writerow(row)
                else:
                    self.seen.add(key)
                    writer.writerow(row)