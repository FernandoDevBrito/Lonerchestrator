"""A stand-in for ANY third-party AI CLI: reads the prompt from stdin, logs how it was called, behaves by phase."""
import json
import os
import re
import sys
import time
from pathlib import Path

prompt = sys.stdin.read()
t0 = time.time()
task = prompt.rsplit("# Your task\n", 1)[-1]          # act on the task, like a real AI: the role text above it (the project's agents) quotes PHASE= markers too


def note(**kw):
    """One file per record: concurrent AIs appending to one file lose lines on Windows."""
    base = Path(os.environ["FAKEAI_LOG"])
    (base.parent / f"calls-{os.getpid()}-{time.time_ns()}.json").write_text(json.dumps(kw), encoding="utf-8")


note(argv=sys.argv[1:], len=len(prompt), cwd=os.getcwd())

if "PHASE=PLAN" in task:
    card = Path(re.search(r"Card: (\S+\.md)", task).group(1))
    tasks = "- [ ] make thing (criterion 1, test_thing)\n"
    if os.environ.get("FAKEAI_FILES"):                # tasks that declare their files
        tasks = "".join(f"- [ ] make {f} [files: {f}] (criterion 1)\n" for f in os.environ["FAKEAI_FILES"].split("|"))
    card.write_text(card.read_text(encoding="utf-8").replace("## Tasks\n", "## Tasks\n" + tasks), encoding="utf-8")
    print("RESULT: PLANNED")
elif "PHASE=IMPLEMENT" in task and "PART " in task:
    time.sleep(0.4)
    for name in re.search(r"Change ONLY these files: ([^\n]+?)\. Do not", task).group(1).split(", "):
        Path(name).write_text("x = 1\n", encoding="utf-8")
    if os.environ.get("FAKEAI_ROGUE"):
        Path("evil.py").write_text("x = 2\n", encoding="utf-8")
    Path(os.environ["FAKEAI_LOG"]).with_name(f"part-{os.getpid()}.json").write_text(json.dumps({"cwd": os.getcwd()}), encoding="utf-8")   # one file per process: no append races
    print("RESULT: DONE")
elif "PHASE=IMPLEMENT" in task:
    time.sleep(0.6)
    barrier = int(os.environ.get("FAKEAI_BARRIER", "0"))              # wait until N builders have started: forces parallel cards to overlap, however slow the machine
    if barrier:
        mark = Path(os.environ["FAKEAI_LOG"]).parent
        (mark / f"start-{os.getpid()}.mark").write_text("x")
        for _ in range(200):
            if len(list(mark.glob("start-*.mark"))) >= barrier:
                break
            time.sleep(0.05)
    stem = Path(re.search(r"Card: (\S+\.md)", task).group(1)).stem
    Path(stem + ".py").write_text("def thing():\n    return 1\n", encoding="utf-8")
    note(built=stem, cwd=os.getcwd(), t0=t0, t1=time.time())
    print("RESULT: DONE")
elif "Split-or-keep" in task:
    print("RESULT: SINGLE")
elif "# REVIEW INPUT" in task:
    print("looks fine\nVERDICT: APPROVED")
else:
    print("ok")
