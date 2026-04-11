# katrain_debug/__main__.py
import os
os.environ["KIVY_NO_ARGS"] = "1"

from katrain_debug.cli import main

if __name__ == "__main__":
    main()
