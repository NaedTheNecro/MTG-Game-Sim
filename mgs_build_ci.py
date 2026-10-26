#!/usr/bin/env python3
"""MGS v0.1 pinned-source strict bridge patch and compile probe.
Experimental build-only gate; neither games nor replays are executed.
"""
import os,subprocess,hashlib,json,pathlib,zipfile,difflib,datetime,sys
PIN="2e68eefa05d9d24895eac45162ff2ff4489103f1"
ROOT=pathlib.Path("Mage.Client.Bridge/src/main/java/mage/client/bridge/processor")
STRICT='Boolean.getBoolean("mgs.strictDecisions")'
def replace(src,old,new,desc):
    if src.count(old)!=1: raise ValueError(f"{desc}: expected 1 anchor, found {src.count(old)}")
    return src.replace(old,new,1)
def patch_priority(s):
    old='''            if (context.interactionsThisTurn() > context.maxInteractionsPerTurn()) {
                logLoopDetected(method);
                context.executeDefaultAction();
                actionsPassed++;
                continue;
            }
'''
    new='''            if (Boolean.getBoolean("mgs.strictDecisions")) {
                if (context.interactionsThisTurn() > context.maxInteractionsPerTurn()) {
                    var violation = new ActionResult();
                    violation.error = "MGS_INTEGRITY_ABORT: interaction_limit";
                    violation.stop_reason = "mgs_integrity_abort";
                    violation.game_seq = action.gameSeq();
                    finish(violation, action, actionView, true);
                    return;
                }
                finish(context.pendingActionResult(action, "mgs_explicit_decision", boardCursorParam),
                    action, actionView, true);
                return;
            }
'''+old
    s=replace(s,old,new,"priority_auto_pass")
    old='''    private boolean initialize() {
        yieldStartTurn = context.lastTurnNumber();
        if (until == null) {
            return false;
        }
'''
    new='''    private boolean initialize() {
        yieldStartTurn = context.lastTurnNumber();
        if (Boolean.getBoolean("mgs.strictDecisions") && until != null) {
            var violation = new ActionResult();
            violation.error = "MGS_INTEGRITY_ABORT: client_side_yield_forbidden";
            violation.stop_reason = "mgs_integrity_abort";
            finish(violation, null, context.lastGameView(), false);
            return false;
        }
        if (until == null) {
            return false;
        }
'''
    return replace(s,old,new,"yield")
def patch_decision(s):
    s=replace(s,'''    public Map<String, Object> executeDefaultAction() {
        var result = new HashMap<String, Object>();
''','''    public Map<String, Object> executeDefaultAction() {
        if (Boolean.getBoolean("mgs.strictDecisions")) {
            throw new IllegalStateException("MGS_INTEGRITY_ABORT: unauthorized_default_action");
        }
        var result = new HashMap<String, Object>();
''',"default_action")
    s=replace(s,'''        Boolean autoTap = input.autoTap();

        if (processorState.interactionState().interactionsThisTurn() > processorState.interactionState().maxInteractionsPerTurn()) {
''','''        Boolean autoTap = input.autoTap();
        if (Boolean.getBoolean("mgs.strictDecisions") && Boolean.TRUE.equals(autoTap)) {
            return chooseActionDone(buildChooseActionError(result, "mgs_integrity_abort",
                "MGS_INTEGRITY_ABORT: autoTap forbidden", false, action, false));
        }
        if (processorState.interactionState().interactionsThisTurn() > processorState.interactionState().maxInteractionsPerTurn()) {
            if (Boolean.getBoolean("mgs.strictDecisions")) {
                return chooseActionDone(buildChooseActionError(result, "mgs_integrity_abort",
                    "MGS_INTEGRITY_ABORT: interaction_limit", false, action, false));
            }
''',"choose_action_limit")
    s=replace(s,"processorState.interactionState().setManaPlan(parsedPlan, !(autoTap != null && !autoTap));","processorState.interactionState().setManaPlan(parsedPlan,\n                                        !Boolean.getBoolean(\"mgs.strictDecisions\") && !(autoTap != null && !autoTap));","mana_fallback")
    s=replace(s,"        NonDecisionActionStatus nonDecisionStatus = maybeAutoHandleNonDecisionAction(action, source);",'''        if (Boolean.getBoolean("mgs.strictDecisions")) {
            return processorState.decisionState().pendingAction() == action
                ? new DecisionBoundaryTransition(DecisionBoundaryStatus.READY, action)
                : new DecisionBoundaryTransition(DecisionBoundaryStatus.CHANGED, null);
        }
        NonDecisionActionStatus nonDecisionStatus = maybeAutoHandleNonDecisionAction(action, source);''',"automatic_target_and_mana")
    return s
def patch_state(s):
    return replace(replace(replace(replace(replace(s,
      "    private int maxInteractionsPerTurn = 25;",
      "    private int maxInteractionsPerTurn = Boolean.getBoolean(\"mgs.strictDecisions\") ? 1_000_000 : 25;","max_interactions"),
      "        this.maxInteractionsPerTurn = maxInteractionsPerTurn;",
      "        this.maxInteractionsPerTurn = Boolean.getBoolean(\"mgs.strictDecisions\") ? Math.max(1_000_000, maxInteractionsPerTurn) : maxInteractionsPerTurn;","interaction_setter"),
      "    private boolean manaPlanAutoTapFallback = true;",
      "    private boolean manaPlanAutoTapFallback = !Boolean.getBoolean(\"mgs.strictDecisions\");","mana_initial"),
      "        this.manaPlanAutoTapFallback = autoTapFallback;",
      "        this.manaPlanAutoTapFallback = !Boolean.getBoolean(\"mgs.strictDecisions\") && autoTapFallback;","mana_setter"),
      "        manaPlanAutoTapFallback = true;",
      "        manaPlanAutoTapFallback = !Boolean.getBoolean(\"mgs.strictDecisions\");","mana_clear")
PATCHERS={"BridgePassPriorityFlow.java":patch_priority,"BridgeDecisionFlowService.java":patch_decision,"BridgeInteractionState.java":patch_state}
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def run(cmd,cwd=None,log=None):
    if log:
        with open(log,"wb") as f:return subprocess.run(cmd,cwd=cwd,stdout=f,stderr=subprocess.STDOUT,timeout=3600).returncode
    return subprocess.check_output(cmd,cwd=cwd,text=True,stderr=subprocess.STDOUT).strip()
def main():
    repo=pathlib.Path("upstream");out=pathlib.Path("evidence");out.mkdir(exist_ok=True)
    receipt={"upstream_pin":PIN,"status":"BLOCKED","game_executed":False,"replay_executed":False,"statistics_authorized":False,"errors":[],"utc":datetime.datetime.now(datetime.timezone.utc).isoformat()}
    try:
        head=run(["git","rev-parse","HEAD"],repo)
        if head!=PIN:raise RuntimeError(f"pin mismatch {head}")
        if run(["git","status","--porcelain"],repo):raise RuntimeError("source tree not clean")
        originals={name:(repo/ROOT/name).read_text() for name in PATCHERS}
        patched={name:func(originals[name]) for name,func in PATCHERS.items()}
        diff=""
        for name in PATCHERS:
            path=str(ROOT/name)
            diff+="".join(difflib.unified_diff(originals[name].splitlines(True),patched[name].splitlines(True),fromfile="a/"+path,tofile="b/"+path))
        (out/"strict_bridge.diff").write_text(diff)
        for name in PATCHERS:(repo/ROOT/name).write_text(patched[name])
        receipt["source_pin_verified"]=True
        receipt["patch_sha256"]=sha(out/"strict_bridge.diff")
        receipt["patched_files_sha256"]={name:sha(repo/ROOT/name) for name in PATCHERS}
        cmd=["mvn","-B","-ntp","-pl","Mage.Client.Bridge","-am","-DskipTests","-Dmaven.build.cache.enabled=false","install"]
        receipt["maven_command"]=cmd
        receipt["maven_exit_code"]=run(cmd,repo,out/"maven-build.log")
        receipt["maven_log_sha256"]=sha(out/"maven-build.log")
        if receipt["maven_exit_code"]!=0:raise RuntimeError("Maven build failed")
        qualified=[]
        for jar in (repo/"Mage.Client.Bridge/target").glob("*.jar"):
            with zipfile.ZipFile(jar) as z:
                names=set(z.namelist())
            wanted={"mage/client/bridge/processor/"+x.replace(".java",".class") for x in PATCHERS}
            if wanted.issubset(names):qualified.append({"sha256":sha(jar),"path":str(jar)})
        if not qualified:raise RuntimeError("No jar contains all three patched classes")
        receipt["jars"]=qualified
        receipt["status"]="JAVA_BUILD_VERIFIED_NOT_GAMEPLAY"
    except Exception as e:receipt["errors"].append(repr(e))
    finally:(out/"build_receipt.json").write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n")
    print(json.dumps(receipt,indent=2))
    return 0 if receipt["status"]=="JAVA_BUILD_VERIFIED_NOT_GAMEPLAY" else 1
if __name__=="__main__":sys.exit(main())
