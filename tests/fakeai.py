"""A stand-in for ANY third-party AI CLI: reads the prompt from stdin, logs how it was called, behaves by phase."""
import json
import os
import sys
from pathlib import Path

prompt = sys.stdin.read()
with open(os.environ["FAKEAI_LOG"], "a", encoding="utf-8") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "len": len(prompt)}) + "\n")

if "PHASE=PLAN" in prompt:
    card = next(Path("board/doing").glob("*.md"))
    card.write_text(card.read_text(encoding="utf-8").replace("## Tasks\n", "## Tasks\n- [ ] make thing (criterion 1, test_thing)\n"), encoding="utf-8")
    print("RESULT: PLANNED")
elif "PHASE=IMPLEMENT" in prompt:
    Path("thing.py").write_text("def thing():\n    return 1\n", encoding="utf-8")
    print("RESULT: DONE")
elif "Split-or-keep" in prompt:
    print("RESULT: SINGLE")
elif "# REVIEW INPUT" in prompt:
    print("looks fine\nVERDICT: APPROVED")
else:
    print("ok")
