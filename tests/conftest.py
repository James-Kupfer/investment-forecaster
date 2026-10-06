# test_image_extractor.py is disabled: it loads "Technical Analysis/image_extractor.py"
# at import time, and that folder is not in this repo, so collection of the whole
# suite aborted with FileNotFoundError. Remove this entry once the folder is restored.
collect_ignore = ["test_image_extractor.py"]
