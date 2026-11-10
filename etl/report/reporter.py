class SimpleReport:
    def generate(self, valid, garbage):
        print(f"Valid rows: {len(valid)}")
        print(f"Garbage rows: {len(garbage)}")