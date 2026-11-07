"""A stand-in for ANY third-party AI CLI: reads the prompt from stdin, logs how it was called, behaves by phase."""
import json
import os
import re
import sys
import time
from pathlib import Path

prompt = sys.stdin.read()
t0 = time.time()


def note(**kw):
    with open(os.environ["FAKEAI_LOG"], "a", encoding="utf-8") as f:
        f.write(json.dumps(kw) + "\n")


note(argv=sys.argv[1:], len=len(prompt), cwd=os.getcwd())

if "PHASE=PLAN" in prompt:
    card = next(Path("board/doing").glob("*.md"))
    tasks = "- [ ] make thing (criterion 1, test_thing)\n"
    if os.environ.get("FAKEAI_FILES"):                # tasks that declare their files
        tasks = "".join(f"- [ ] make {f} [files: {f}] (criterion 1)\n" for f in os.environ["FAKEAI_FILES"].split("|"))
    card.write_text(card.read_text(encoding="utf-8").replace("## Tasks\n", "## Tasks\n" + tasks), encoding="utf-8")
    print("RESULT: PLANNED")
elif "PHASE=IMPLEMENT" in prompt and "PART " in prompt:
    time.sleep(0.4)
    for name in re.search(r"Change ONLY these files: ([^\n]+?)\. Do not", prompt).group(1).split(", "):
        Path(name).write_text("x = 1\n", encoding="utf-8")
    if os.environ.get("FAKEAI_ROGUE"):
        Path("evil.py").write_text("x = 2\n", encoding="utf-8")
    Path(os.environ["FAKEAI_LOG"]).with_name(f"part-{os.getpid()}.json").write_text(json.dumps({"cwd": os.getcwd()}), encoding="utf-8")   # one file per process: no append races
    print("RESULT: DONE")
elif "PHASE=IMPLEMENT" in prompt:
    time.sleep(0.6)                                  # long enough for parallel cards to overlap
    stem = Path(re.search(r"Card: (\S+\.md)", prompt).group(1)).stem
    Path(stem + ".py").write_text("def thing():\n    return 1\n", encoding="utf-8")
    note(built=stem, cwd=os.getcwd(), t0=t0, t1=time.time())
    print("RESULT: DONE")
elif "Split-or-keep" in prompt:
    print("RESULT: SINGLE")
elif "# REVIEW INPUT" in prompt:
    print("looks fine\nVERDICT: APPROVED")
else:
    print("ok")
