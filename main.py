import sys
import os

# Add project root and handlers to path - multiple fallbacks for all server environments
_dir = os.path.dirname(os.path.abspath(__file__))
for _p in [_dir, os.getcwd(), os.path.join(_dir, "handlers")]:
    if _p and os.path.exists(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

from kinosave import main

if __name__ == '__main__':
    main()

