#!/usr/bin/env python3
"""Cold, time-bounded Rust APL discovery. Not a P7.2 gate by itself."""
import argparse, copy, hashlib, json, os, random, subprocess, tempfile, time
from pathlib import Path

REFERENCE_DPS = 728.1936126415858

def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def average_dps(report):
    for keys in (("result","raidMetrics","dps","avg"), ("result","dps","avg"), ("dps","avg")):
        value = report
        for key in keys:
            value = value.get(key) if isinstance(value, dict) else None
        if isinstance(value, (float, int)):
            return float(value)
    raise ValueError("native Rust output contains no average DPS")

def simulate(binary, request, iterations, output_dir, label, rng_mode="stochastic", deadline=None):
    if deadline is not None and time.monotonic() >= deadline:
        raise TimeoutError("End-to-end search deadline exhausted before native execution")
    req = copy.deepcopy(request)
    req.setdefault("simOptions", {})["iterations"] = iterations
    with tempfile.TemporaryDirectory() as tmp:
        input_path, output_path = Path(tmp)/"in.json", Path(tmp)/"out.json"
        input_path.write_text(json.dumps(req, separators=(",", ":")))
        env = dict(os.environ, WOWSIM_RNG_MODE=rng_mode)
        started = time.monotonic()
        run = subprocess.run([str(binary), "sim", "--request", str(input_path), "--outfile",
                              str(output_path), "--gate"], capture_output=True, text=True,
                             env=env, timeout=max(0.001, min(90.0, deadline - time.monotonic())) if deadline is not None else 90.0)
        log = {"label":label, "iterations":iterations, "rng_mode":rng_mode,
               "request_sha256":digest(req), "exit_code":run.returncode,
               "elapsed_seconds":round(time.monotonic()-started, 6),
               "stderr":run.stderr[-3000:]}
        if run.returncode != 0 or not output_path.exists():
            raise RuntimeError(json.dumps(log))
        result = json.loads(output_path.read_text())
        log["dps"] = average_dps(result)
        if not label.startswith("candidate_"):
            Path(output_dir, label+".json").write_text(json.dumps({"run":log,"request":req,
                                                                      "result":result}, indent=2))
        return log

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--binary", type=Path, required=True)
    ap.add_argument("--request", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--seconds", type=float, default=300)
    ap.add_argument("--screen-iterations", type=int, default=100)
    ap.add_argument("--holdout-iterations", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=63272)
    args=ap.parse_args()
    if args.seconds <= 0 or args.screen_iterations < 1 or args.holdout_iterations < 1:
        ap.error("positive search duration and iteration counts required")
    args.output.mkdir(parents=True,exist_ok=True)
    ref=json.loads(args.request.read_text())
    original=ref["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"]
    if len(original) < 3:
        raise ValueError("priorityList too short for independent search")
    rng=random.Random(args.seed)
    started=time.monotonic()
    deadline=started+args.seconds
    # Reserve a bounded window for frozen holdout and writing the evidence.
    # The full budget includes screening, holdout and report serialization.
    holdout_reserve=min(90.0, max(1.0, args.seconds * 0.25))
    screening_deadline=deadline-holdout_reserve
    initial_hash=digest(original)
    seen={initial_hash} # never evaluate the saved reference APL as a search candidate
    best=None
    trials=[]
    index=0
    elites=[]
    # Cold random permutations: no reference-policy baseline paid or seeded as winner.
    # Legality: only reorder intact APL actions; pre-pull, gear, talents, spells and
    # conditions remain byte-for-byte unchanged.
    while time.monotonic() < screening_deadline:
        if elites and rng.random() < 0.8:
            candidate = copy.deepcopy(rng.choice(elites)[1])
            i,j=rng.sample(range(len(candidate)),2)
            candidate[i],candidate[j]=candidate[j],candidate[i]
        else:
            candidate=copy.deepcopy(original)
            rng.shuffle(candidate)
        key=digest(candidate)
        if key in seen: continue
        seen.add(key)
        req=copy.deepcopy(ref)
        req["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"]=candidate
        try:
            log=simulate(args.binary,req,args.screen_iterations,args.output,
                         "candidate_%05d"%index, deadline=screening_deadline)
            log["apl_hash"]=key
            trials.append(log)
            elites.append((log["dps"],candidate))
            elites=sorted(elites,key=lambda v:v[0],reverse=True)[:16]
            if best is None or log["dps"] > best["dps"]:
                best=dict(log)
                best["priorityList"]=candidate
        except TimeoutError:
            break
        except subprocess.TimeoutExpired:
            break
        except Exception as exc:
            trials.append({"label":"candidate_%05d"%index,"error":str(exc),"apl_hash":key})
        index+=1
    if best is None:
        raise RuntimeError("No executable candidate; P7.2 not passed")
    frozen=copy.deepcopy(ref)
    frozen["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"]=best["priorityList"]
    frozen["simOptions"]["randomSeed"] = str(args.seed + 1000000007)
    holdout=simulate(args.binary,frozen,args.holdout_iterations,args.output,
                     "frozen_stochastic_holdout",rng_mode="stochastic",deadline=deadline)
    report={"status":"DIAGNOSTIC_ONLY_P7_2_NOT_CERTIFIED",
            "seconds_budget":args.seconds, "elapsed_seconds":time.monotonic()-started,
            "candidates_paid":len(trials),
            "reference_dps":REFERENCE_DPS, "original_apl_hash":initial_hash,
            "best_screen":best, "holdout":holdout,"trials":trials,
            "fixed_gear":ref["raid"]["parties"][0]["players"][0].get("equipment"),
            "fixed_talents":ref["raid"]["parties"][0]["players"][0].get("talents"),
            "limitations":["Rust-only; no live 2D world/ACK causal trace",
                           "cold permutations retain original action content but not ordering",
                           "holdout is not independent of reference scenario seed unless separately changed"]}
    if time.monotonic() >= deadline:
        raise TimeoutError("End-to-end budget exhausted before evidence serialization")
    (args.output/"search_report.json").write_text(json.dumps(report,indent=2))
    if time.monotonic() > deadline:
        raise TimeoutError("End-to-end budget exceeded; report is not certifiable")
    print(json.dumps({k:report[k] for k in ["status","candidates_paid","reference_dps","holdout"]},indent=2))

if __name__=="__main__": main()
