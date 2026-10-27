"""MGS v0.1 explicit external-player decision interface (offline policy prototype).

No XMage actions are executed in this module. A valid decision comes solely from
the current player's bridge-projected pending action. Unknown/unhandled prompts
abort rather than pass, auto-target, auto-tap, or invent a legal option.
"""
from dataclasses import dataclass
from typing import Any

class IntegrityAbort(RuntimeError):
    """Never count a game after an external policy integrity failure."""

@dataclass(frozen=True)
class Decision:
    tool: str
    arguments: dict[str, Any]
    game_seq: int

def _choices(data: dict) -> list[dict]:
    raw=data.get("choices")
    if not isinstance(raw,list) or not all(isinstance(v,dict) for v in raw):
        raise IntegrityAbort("Missing or malformed choices from bridge")
    return raw

def _by_index(choice: dict) -> str:
    idx=choice.get("index")
    if not isinstance(idx,int) or idx<0:
        raise IntegrityAbort("Choice lacks exact valid index")
    return str(idx)

def propose_decision(state: dict, *, seat: int) -> Decision:
    """Minimal deterministic independent policy, NOT a competitive Commander AI.

    A 4-seat orchestrator must call this in separate policy processes, and record
    the full state/choice/result before any response is sent to the engine.
    """
    if not 0<=seat<4:
        raise IntegrityAbort("Invalid seat")
    if not isinstance(state,dict) or state.get("action_pending") is not True:
        raise IntegrityAbort("No explicit pending action")
    seq=state.get("game_seq")
    if not isinstance(seq,int) or seq<0:
        raise IntegrityAbort("Missing engine game sequence")
    t=state.get("action_type")
    choices=_choices(state)
    args:dict[str,Any]
    if t=="GAME_ASK":
        # Explicitly answer any yes/no prompt; avoid unsafe assumptions by declining.
        args={"choice":"no"}
    elif t=="GAME_SELECT":
        # Play an indexed land when possible; otherwise explicitly pass priority.
        lands=[c for c in choices if c.get("action")=="land"]
        args={"choice":_by_index(lands[0])} if lands else {"choice":"no"}
    elif t in {"GAME_TARGET","GAME_CHOOSE_ABILITY","GAME_CHOOSE_CHOICE"}:
        if not choices:raise IntegrityAbort(f"{t}: no bridge-projected legal choice")
        args={"choice":_by_index(choices[0])}
    elif t in {"GAME_PLAY_MANA","GAME_PLAY_XMANA"}:
        # Explicitly cancel rather than implicit auto-tap; tests cannot claim
        # strategic competence or full-game completion on this prototype.
        args={"choice":"no"}
    elif t=="GAME_CHOOSE_PILE":
        args={"pile":1}
    elif t=="GAME_GET_AMOUNT":
        a=state.get("min")
        if not isinstance(a,int):raise IntegrityAbort("Amount minimum missing")
        args={"amount":a}
    else:
        raise IntegrityAbort(f"Unsupported action type {t!r}; no default action")
    args["auto_tap"]=False
    return Decision(tool="choose_action",arguments=args,game_seq=seq)
