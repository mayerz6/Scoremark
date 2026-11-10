from ..config import AppConfig, DatasetSchema
from ..schema import RowOutcome, DataQualityScorecard
# ----------------------------
# ETL Pipeline
# ----------------------------
class CSVIngestionETL:
    """
    Production-minded ingestion:
    - Structural validation (column count)
    - Transformation (cleaning, casing, truncation)
    - Business validation (email, name, phone)
    - Dual outputs (processed + garbage)
    - Data Quality Scorecard (JSON per file)
    """

    def __init__(self, config: AppConfig, schema: DatasetSchema):
        self.cfg = config
        os.makedirs(self.cfg.output_folder, exist_ok=True)
        os.makedirs(self.cfg.garbage_folder, exist_ok=True)
        os.makedirs(self.cfg.scorecard_folder, exist_ok=True)

    # ---------- I/O ----------
    def _write_rows(self, file_path: str, rows: List[List[str]], mode: str, header: Optional[Tuple[str, ...]] = None):
        with open(file_path, mode, newline="", encoding=self.cfg.output_encoding) as f:
            w = csv.writer(f)
            if header and mode == "w":
                w.writerow(list(header))
            w.writerows(rows)

    
    def _write_scorecard(self, scorecard: DataQualityScorecard, score_path: str):
        with open(score_path, "w", encoding="utf-8") as f:
            json.dump(asdict(scorecard), f, ensure_ascii=False, indent=2)

    # ---------- Core processing ----------
    def _validate_structure(self, row: List[str], score: DataQualityScorecard) -> Optional[str]:
        if len(row) < self.cfg.required_min_columns:
            score.structural_bad_column_count += 1
            return "STRUCT_BAD_COLUMN_COUNT"
        return None

    def _transform(self, row: List[str]) -> List[str]:
        # Clean + normalize early
        firstname_raw = FieldOps.clean_field(row[self.cfg.FN_IDX])
        lastname_raw = FieldOps.clean_field(row[self.cfg.LN_IDX])

        email_raw = FieldOps.clean_field(row[self.cfg.EMAIL_IDX]).lower()
        dob_raw = FieldOps.clean_field(row[self.cfg.DOB_IDX])
        phone_raw = FieldOps.clean_field(row[self.cfg.PHONE_IDX])

        address = f"{FieldOps.clean_field(row[self.cfg.STR1_IDX])} {FieldOps.clean_field(row[self.cfg.STR2_IDX])}".strip()
        city = FieldOps.clean_field(FieldOps.to_camel_case(row[self.cfg.CITY_IDX]) or "")
        state = FieldOps.clean_field(FieldOps.to_camel_case(row[self.cfg.STATE_IDX]) or "")
        zip_code = FieldOps.clean_field(row[self.cfg.ZIP_IDX])


        # Apply casing + truncation (byte-safe)
        firstname = FieldOps.truncate_to_max_bytes(firstname_raw.title(), self.cfg.max_field_bytes)
        lastname = FieldOps.truncate_to_max_bytes(lastname_raw.title(), self.cfg.max_field_bytes)
        dob = FieldOps.truncate_to_max_bytes(dob_raw, self.cfg.max_field_bytes)

        # Address canonicalization
        address = FieldOps.clean_field(FieldOps.to_camel_case(address) or "")
        address = FieldOps.truncate_to_max_bytes(address, self.cfg.max_field_bytes)

        # Phone digits-only (keep as string)
        phone_digits = FieldOps.digits_only(phone_raw)

        return [firstname, lastname, email_raw, phone_digits, dob, address, city, state, zip_code]



    def _validate_business(self, processed: List[str], score: DataQualityScorecard) -> Optional[str]:
        # processed schema mapping
        firstname, lastname, email, phone, dob, address, city, state, zip_code = processed

        # Occupancy / blanks tracking (doesn't auto-fail by itself)
        for field_name, value in zip(self.cfg.header, processed):
            if FieldOps.is_blank(value):
                score.bump_blank(field_name)

        # Email validation (hard fail)
        if not FieldOps.validate_email(email):
            score.email_invalid_count += 1
            return "INVALID_EMAIL"

        # Name constraints (hard fail)
        if len(firstname) > self.cfg.max_name_chars or "@" in firstname or FieldOps.is_blank(firstname):
            score.bump_maxlen("firstname")
            return "INVALID_FIRSTNAME"

        if len(lastname) > self.cfg.max_name_chars or "@" in lastname:
            score.bump_maxlen("lastname")
            return "INVALID_LASTNAME"

        # Phone profiling (soft-ish but you can make it hard fail)
        if phone and not phone.isdigit():
            score.phone_non_numeric_count += 1
            return "PHONE_NON_NUMERIC"

        # Domain profiling (only after email passes)
        score.bump_domain(email)

        return None


    def process_row(self, row: List[str], score: DataQualityScorecard) -> RowOutcome:
        reason = self._validate_structure(row, score)
        if reason:
            score.bump_reason(reason)
            return RowOutcome(is_valid=False, reason=reason)

        try:
            processed = self._transform(row)
            reason = self._validate_business(processed, score)
            if reason:
                score.bump_reason(reason)
                return RowOutcome(is_valid=False, reason=reason)

            return RowOutcome(is_valid=True, processed=processed)

        except Exception as e:
            # Don't swallow exceptions silently in prod
            logging.exception(f"Row processing exception: {e} | row={row[:25]}")
            score.bump_reason("ROW_EXCEPTION")
            return RowOutcome(is_valid=False, reason="ROW_EXCEPTION")

    def process_file(self, input_path: str) -> Dict[str, str]:
        file_name = os.path.basename(input_path)
        out_path = os.path.join(self.cfg.output_folder, f"processed_{file_name}")
        gar_path = os.path.join(self.cfg.garbage_folder, f"garbage_{file_name}")
        sc_path = os.path.join(self.cfg.scorecard_folder, f"scorecard_{os.path.splitext(file_name)[0]}.json")

        score = DataQualityScorecard(
            file_name=file_name,
            started_at=datetime.utcnow().isoformat() + "Z",
            finished_at="",
        )

        # Write headers (note: garbage gets a DIFFERENT header schema)
        self._write_rows(out_path, [], mode="w", header=self.cfg.header)
        # Garbage schema: keep raw row + reason (so it’s truthful and useful)
        self._write_rows(gar_path, [], mode="w", header=("reason", "raw_row"))

        valid_batch: List[List[str]] = []
        invalid_batch: List[List[str]] = []

        with open(input_path, "r", encoding=self.cfg.input_encoding, newline="") as f:
            reader = csv.reader(f, delimiter=self.cfg.delimiter)

            for row in reader:
                score.total_rows += 1
                outcome = self.process_row(row, score)

                if outcome.is_valid and outcome.processed:
                    score.valid_rows += 1
                    valid_batch.append(outcome.processed)
                else:
                    score.invalid_rows += 1
                    # Store reason + raw row as a single cell to keep CSV shape consistent
                    invalid_batch.append([outcome.reason or "INVALID", "|".join(row)])

                if len(valid_batch) >= self.cfg.batch_size:
                    self._write_rows(out_path, valid_batch, mode="a")
                    valid_batch.clear()

                if len(invalid_batch) >= self.cfg.batch_size:
                    self._write_rows(gar_path, invalid_batch, mode="a")
                    invalid_batch.clear()

        if valid_batch:
            self._write_rows(out_path, valid_batch, mode="a")
        if invalid_batch:
            self._write_rows(gar_path, invalid_batch, mode="a")

        score.finished_at = datetime.utcnow().isoformat() + "Z"
        self._write_scorecard(score, sc_path)


        logging.info(f"Done: {file_name} | total={score.total_rows} valid={score.valid_rows} invalid={score.invalid_rows}")
        return {"input": input_path, "output": out_path, "garbage": gar_path, "scorecard": sc_path}

    def run_folder(self, max_workers: Optional[int] = None) -> List[Dict[str, str]]:
        files = [f for f in os.listdir(self.cfg.input_folder) if f.lower().endswith(".csv")]
        paths = [os.path.join(self.cfg.input_folder, f) for f in files]

        results: List[Dict[str, str]] = []
        if not paths:
            logging.warning(f"No CSV files found in {self.cfg.input_folder}")
            return results

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(self.process_file, p): p for p in paths}
            for fut in as_completed(futures):
                p = futures[fut]
                try:
                    results.append(fut.result())
                except Exception as e:
                    logging.exception(f"File failed: {p} | {e}")
        return results