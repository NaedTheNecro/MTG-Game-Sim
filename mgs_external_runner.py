#!/usr/bin/env python3
"""Run an XMage Commander *plumbing* experiment with four independent external policies.

Monkeypatches only the upstream Python process launcher, not XMage rules.
The four child processes execute mgs_bridge_agent.py in strict mode.
No win-rate or deterministic-replay claims are permitted.
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--upstream",type=pathlib.Path,default=pathlib.Path("upstream"))
    p.add_argument("--evidence",type=pathlib.Path,default=pathlib.Path("evidence"))
    p.add_argument("--max-decisions",type=int,default=5)
    a=p.parse_args()
    root=a.upstream.resolve(); home=pathlib.Path(__file__).resolve().parent
    evidence=a.evidence.resolve();evidence.mkdir(parents=True,exist_ok=True)
    sys.path.insert(0,str(root/"src"))
    import magebench.orchestration.batch_coordination as batch
    from magebench.orchestration.config import Config
    from magebench.orchestration.orchestrator import run_orchestrator
    from magebench.common.log import setup_logging
    import mgs_cpu_smoke

    # Reuse the checked immutable 99+1 lists but replace all player controllers.
    mgs_cpu_smoke.prepare(root,evidence)
    config_path=root/"configs"/"mgs-cpu-smoke.json"
    config=json.loads(config_path.read_text())
    config["players"]=[{"type":"sleepwalker","name":x["name"],"deck":x["deck"]} for x in json.loads((evidence/"cpu-smoke-input.json").read_text())["players"]]
    config["skipPostGamePrompts"]=True
    config_path=root/"configs"/"mgs-external-smoke.json"
    config_path.write_text(json.dumps(config,indent=2)+"\n")

    launched=[]
    def strict_launcher(pm,project_root,cfg,name,deck_path,log_path):
        cmd=[sys.executable,str(home/"mgs_bridge_agent.py"),
            "--server",cfg.server,"--port",str(cfg.port),"--username",name,
            "--deck",str(project_root/deck_path),"--project-root",str(project_root),
            "--evidence-dir",str(evidence),"--max-decisions",str(a.max_decisions)]
        env={"PYTHONUNBUFFERED":"1","PYTHONPATH":str(root/"src")+os.pathsep+str(home)}
        proc=pm.start_process(args=cmd,cwd=root,env=env,log_file=log_path)
        launched.append((name,proc))
        return proc

    batch.start_sleepwalker_client=strict_launcher
    setup_logging()
    result=None
    try:
        cfg=Config(config_file=config_path,observer=True,skip_compile=True)
        result=run_orchestrator(cfg,project_root=root)
    finally:
        statuses={name:proc.poll() for name,proc in launched}
        record={"stage":"EXTERNAL_BRIDGE_PLUMBING_ONLY",
            "four_processes":len(launched)==4,"process_statuses":statuses,
            "orchestrator_exit":None if result is None else result.exit_code,
            "strict_external_agents":False,"complete_game_certified":False,
            "replay_verified":False,"statistics_authorized":False}
        (evidence/"external-run-receipt.json").write_text(json.dumps(record,indent=2)+"\n")
        print(json.dumps(record,indent=2),flush=True)
    return result.exit_code if result is not None else 1

if __name__=="__main__":sys.exit(main())
