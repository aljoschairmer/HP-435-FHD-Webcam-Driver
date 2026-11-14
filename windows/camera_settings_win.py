#!/usr/bin/env python3
"""Read and display the HP 430/435 FHD Webcam settings (Windows, read-only).

Shows the standard UVC settings through the documented DirectShow interfaces
IAMVideoProcAmp (brightness, contrast, white balance, ...) and IAMCameraControl
(exposure, focus, ...), with current value, auto/manual mode, range and default.
Optionally also lists the raw values of the two vendor extension units.

Only Get/GetRange calls are made. Nothing is written to the camera.

Requires:  pip install comtypes   (Windows, Python 3.8+)
Usage:     py -3 windows\\camera_settings_win.py [--xu] [--json]
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
from ctypes import POINTER, byref, c_long

sys.path.insert(0, os.path.dirname(os.