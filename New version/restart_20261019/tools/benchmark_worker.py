#!/usr/bin/env python3
"""Deterministic CPU-bound task used to validate runner accounting."""
import hashlib
import json
from pathlib import Path
import sys

target = Path(sys.argv[1])
rounds = int(sys.argv[2])
state = 0x345678
for index in range(rounds):
    state = (state * 1000003 + index) & 0xFFFFFFFFFFFFFFFF
payload = {"rounds": rounds, "state": state,
           "digest": hashlib.sha256(f"{rounds}:{state}".encode()).hexdigest()}
target.write_text(json.dumps(payload, sort_keys=True) + "\n")
