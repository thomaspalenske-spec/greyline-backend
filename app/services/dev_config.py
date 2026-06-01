import os

def is_dev():
    return os.getenv("GREYLINE_ENV", "dev") == "dev"
