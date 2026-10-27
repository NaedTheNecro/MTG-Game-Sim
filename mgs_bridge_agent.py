#!/usr/bin/env python3
"""Independent external XMage bridge controller for MGS plumbing experiments.

This deliberately NONCOMPETITIVE bounded controller logs observations and exact
submitted actions. An explicit concede ends its participation after a small
number of decisions. Games are NOT MGS-valid wins or replay proofs.
"""
import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from mgs_explicit_policy import IntegrityAbort, propose_decision
from magebench.pilot.bridge_transport import build_bridge_launch_args, spawn_bridge_http
from magebench.pilot.tool_error import extract_text_content

SEATS = {"Elves":0, "Dragons":1, "Coven":2, "Equipment":3}

class Recorder:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = path.open("w", encoding="utf-8")
        self.step = 0
    def emit(self, kind, **data):
        record={"seq_local":self.step,"type":kind,"time_utc_unix_ns":time.time_ns(),**data}
        self.step+=1
        line=json.dumps(record,sort_keys=True,ensure_ascii=False)
        self.file.write(line+"\n")
        self.file.flush()
        os.fsync(self.file.fileno())
    def close(self):
        self.file.close()

async def run(args):
    if args.username not in SEATS:
        raise IntegrityAbort("Unrecognized seat name (fixed four seats required)")
    seat=SEATS[args.username]
    trace=Recorder(args.evidence_dir/f"mgs_seat_{seat+1}_decisions.jsonl")
    game_finished=False
    try:
        trace.emit("process_start",seat=seat,player=args.username,policy="MGS_EXPLICIT_V0_1_UNCOMPETITIVE",
            strict_decisions=True,max_decisions=args.max_decisions)
        launch=build_bridge_launch_args(server=args.server,port=args.port,username=args.username,
            deck_path=args.deck,heap_size_mb=512,error_log_path=args.evidence_dir/f"{args.username}_errors.log")
        jvm=launch.jvm_args+" -Dmgs.strictDecisions=true"
        trace.emit("bridge_launch",strict_property="-Dmgs.strictDecisions=true",
            executable="mvn",module="Mage.Client.Bridge")
        async with spawn_bridge_http(project_root=args.project_root,mvn_args=launch.mvn_args,
            jvm_args=jvm,log_file=args.evidence_dir/f"{args.username}_bridge_runtime.log") as session:
            await asyncio.wait_for(session.initialize(),timeout=45)
            trace.emit("bridge_connected")
            next_state=None
            n=0
            for _ in range(args.max_decisions):
                if next_state is None:
                    trace.emit("tool_call",tool="pass_priority",args={})
                    result=await asyncio.wait_for(session.call_tool("pass_priority",{}),timeout=180)
                    text=extract_text_content("pass_priority",result)
                    trace.emit("tool_result",tool="pass_priority",raw=text)
                    next_state=json.loads(text)
                state=next_state
                next_state=None
                if state.get("game_over") or state.get("player_dead") or state.get("stop_reason")=="game_over":
                    trace.emit("game_end_visible",state=state)
                    game_finished=True
                    break
                if not state.get("action_pending"):
                    trace.emit("no_action",state=state)
                    # No action isn't an explicit decision. Must not fall into automatic pass.
                    continue
                decision=propose_decision(state,seat=seat)
                # Persist observation/decision before sending ANY action to engine.
                trace.emit("explicit_decision",state=state,tool=decision.tool,
                    args=decision.arguments,game_seq=decision.game_seq)
                result=await asyncio.wait_for(session.call_tool(decision.tool,decision.arguments),timeout=180)
                raw=extract_text_content(decision.tool,result)
                trace.emit("decision_result",tool=decision.tool,raw=raw)
                parsed=json.loads(raw)
                if parsed.get("success") is False or "MGS_INTEGRITY_ABORT" in raw:
                    raise IntegrityAbort("Bridge rejected an explicit action or reported integrity abort")
                n+=1
                if parsed.get("action_pending"):
                    next_state=parsed
                if parsed.get("game_over") or parsed.get("player_dead") or parsed.get("stop_reason")=="game_over":
                    game_finished=True
                    break
            if not game_finished:
                # Deliberate termination for *plumbing* only: this is NOT a natural win.
                trace.emit("explicit_concession",after_decisions=n,reason="BOUNDED_HARNESS_ONLY")
                result=await asyncio.wait_for(session.call_tool("concede",{}),timeout=30)
                raw=extract_text_content("concede",result)
                trace.emit("concession_result",raw=raw)
                parsed=json.loads(raw)
                if parsed.get("success") is False:
                    raise IntegrityAbort("Concession was rejected")
            trace.emit("process_finished",decisions=n,natural_game_over=game_finished)
    except BaseException as exc:
        trace.emit("integrity_failure",error=repr(exc))
        raise
    finally:
        trace.close()

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--server",default="localhost")
    p.add_argument("--port",type=int,required=True)
    p.add_argument("--username",required=True)
    p.add_argument("--deck",type=Path,required=True)
    p.add_argument("--project-root",type=Path,required=True)
    p.add_argument("--evidence-dir",type=Path,required=True)
    p.add_argument("--max-decisions",type=int,default=5)
    args=p.parse_args()
    if not 1<=args.max_decisions<=50:
        raise IntegrityAbort("Invalid bounded decision count")
    asyncio.run(run(args))
    return 0

if __name__=="__main__":
    try:sys.exit(main())
    except BaseException as e:
        print("MGS_AGENT_FAIL_CLOSED:",repr(e),file=sys.stderr,flush=True)
        raise
