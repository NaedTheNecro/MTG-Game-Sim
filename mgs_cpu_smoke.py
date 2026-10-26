#!/usr/bin/env python3
"""MGS v0.1 first *infrastructure-only* XMage Commander smoke experiment.

This deliberately uses four stock XMage CPU players. It does NOT test MGS
external-player strict decision policies or independently replay a game.
No outcome from this harness qualifies as an MGS win-rate observation.
"""
import argparse
import datetime
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import sys

PIN = "2e68eefa05d9d24895eac45162ff2ff4489103f1"
PRECONS = (
    ("Elves", "elven-empire-bg.json"),
    ("Dragons", "draconic-rage-rg.json"),
    ("Coven", "coven-counters-gw.json"),
    ("Equipment", "arm-for-battle.json"),
)
GAME_TYPES = ("game_over",)
HASH = lambda data: hashlib.sha256(data).hexdigest()


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def prepare(upstream, evidence):
    upstream = upstream.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=upstream, text=True).strip()
    if head != PIN:
        raise RuntimeError(f"Upstream revision mismatch: {head} (wanted {PIN})")
    deck_dir = upstream / "tmp" / "decks"
    deck_dir.mkdir(parents=True, exist_ok=True)
    seats = []
    for seat, (name, filename) in enumerate(PRECONS, 1):
        source = upstream / "data" / "decks" / "commander" / filename
        data = json.loads(source.read_text())
        cards = data.get("cards")
        if not isinstance(cards, list):
            raise ValueError(f"Deck has no complete card list: {filename}")
        parsed = []
        for line in cards:
            m = re.fullmatch(r"(SB:\s*)?(\d+)\s+\[[^\]]+\]\s+.+", line)
            if not m:
                raise ValueError(f"Malformed deck line {filename}: {line}")
            parsed.append((bool(m.group(1)), int(m.group(2)), line))
        main_count = sum(q for side, q, _ in parsed if not side)
        sb_count = sum(q for side, q, _ in parsed if side)
        if (main_count, sb_count) != (99, 1):
            raise ValueError(f"Expected 99+1 Commander: {filename}: {main_count}+{sb_count}")
        out = deck_dir / f"mgs-seat-{seat}.dck"
        out.write_text("\n".join(cards) + "\n")
        seats.append({
            "seat": seat,
            "name": name,
            "player_type": "XMage built-in CPU; NOT MGS external policy",
            "deck": str(out.relative_to(upstream)),
            "source": filename,
            "sha256": HASH(out.read_bytes()),
            "main_cards": main_count,
            "commander_cards": sb_count,
        })
    config = {
        "gameType": "Commander Free For All",
        "deckType": "Variant Magic - Freeform Commander",
        "matchTimeLimit": "MIN__20",
        "matchBufferTime": "NONE",
        "skipPostGamePrompts": True,
        "players": [{"type": "cpu", "name": s["name"], "deck": s["deck"]} for s in seats],
    }
    config_path = upstream / "configs" / "mgs-cpu-smoke.json"
    write_json(config_path, config)
    write_json(evidence / "cpu-smoke-input.json", {
        "upstream": PIN,
        "experiment_class": "INFRASTRUCTURE_SMOKE_ONLY",
        "mgs_agent_validation": False,
        "replay_validation": False,
        "statistics_authorized": False,
        "players": seats,
        "config_sha256": HASH(config_path.read_bytes()),
    })
    print("Prepared fixed 4-player XMage CPU smoke game:", config_path)


def audit(evidence, log_dir):
    evidence.mkdir(parents=True, exist_ok=True)
    report = {
        "status": "NO_GO", "mode": "CPU_INFRA_SMOKE_NOT_MGS",
        "mgs_agent_validation": False, "replay_validation": False,
        "statistics_authorized": False,
        "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "reason": None, "artifacts": {}, "game_over_events": 0,
    }
    try:
        games = sorted(log_dir.glob("game_*"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not games:
            raise RuntimeError("No game_* directory created; server/observer may not have started")
        game_dir = games[0]
        report["game_directory_name"] = game_dir.name
        snapshots = [game_dir / "game_events.jsonl", game_dir / "server_game_events.jsonl"]
        events_path = next((p for p in snapshots if p.is_file()), None)
        if events_path is None:
            raise RuntimeError("Missing independent observer game-events JSONL")
        for line in events_path.read_text().splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            if item.get("type") in GAME_TYPES:
                report["game_over_events"] += 1
        if report["game_over_events"] < 1:
            raise RuntimeError("No observer game_over event; incomplete/timeout game NOT counted")
        config_path = game_dir / "config.json"
        if not config_path.is_file():
            raise RuntimeError("Missing game config")
        cfg = json.loads(config_path.read_text())
        ps = cfg.get("players", [])
        if len(ps) != 4 or any(p.get("type") != "cpu" for p in ps):
            raise RuntimeError("Expected exactly four CPU Commander players")
        if cfg.get("gameType") != "Commander Free For All":
            raise RuntimeError("Not a four-player Commander game")
        report["status"] = "COMPLETED_CPU_INFRA_SMOKE_ONLY"
        report["reason"] = "Observer recorded game over, but CPU policies cannot certify MGS"
    except Exception as exc:
        report["reason"] = f"{type(exc).__name__}: {exc}"
    finally:
        # Copy complete, unmodified event history for external audit; no truncation.
        if "game_dir" in locals():
            included = [
                "manifest.json", "game_meta.json", "config.json", "game_events.jsonl",
                "server_game_events.jsonl", "game.jsonl", "errors.log",
                "server.log", "spectator.log",
            ]
            for name in included:
                path = game_dir / name
                if path.is_file():
                    dest = evidence / "game" / name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, dest)
                    report["artifacts"][name] = {
                        "sha256": HASH(dest.read_bytes()), "bytes": dest.stat().st_size,
                    }
        write_json(evidence / "cpu-smoke-result.json", report)
        print(json.dumps(report, indent=2))
    return 0 if report["status"] == "COMPLETED_CPU_INFRA_SMOKE_ONLY" else 1


def main():
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["prepare", "audit"])
    p.add_argument("--upstream", type=pathlib.Path, default=pathlib.Path("upstream"))
    p.add_argument("--evidence", type=pathlib.Path, default=pathlib.Path("evidence"))
    p.add_argument("--log-dir", type=pathlib.Path, default=pathlib.Path.home() / ".mage-bench" / "logs")
    a = p.parse_args()
    if a.mode == "prepare":
        prepare(a.upstream, a.evidence)
        return 0
    return audit(a.evidence, a.log_dir)


if __name__ == "__main__":
    sys.exit(main())
