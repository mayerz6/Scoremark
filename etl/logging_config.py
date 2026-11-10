
# --------------------------------------------------------------------------
# Logging configuration
# --------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    filename='etl_pipeline.log',
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler('etl_pipeline.log'), logging.StreamHandler()]
)
