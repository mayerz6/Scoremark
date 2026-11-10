etl_pipeline_app/
|
├── datasets/
│   │
│   ├── order_dataset.py
│   │
│   ├── Dakotadostavka/
│       ├── dako_raw_dataset.csv
|   
├── etl/
│   │
│   ├── config.py
│   ├── schema.py
│   │
│   ├── extract/
│   │   ├── csv_extractor.py
│   │   └── s3_extractor.py
│   │
│   ├── transform/
│   │   ├── transformer.py
│   │   └── field_cleaners.py
│   │
│   ├── load/
│   │   ├── csv_loader.py
│   │   └── redshift_loader.py
│   │
│   ├── reporting/
│       ├── scorecard.py
│       └── deduplication.py
│   
│
├── tests/
│   ├── test_validators.py
│   └── test_transformers.py
│
├── main.py
├── etl-pipeline.py
└── requirements.txt