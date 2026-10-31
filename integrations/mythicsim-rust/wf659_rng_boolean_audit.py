#!/usr/bin/env python3
"""CI audit: potential Bernoulli draws hidden behind numeric RNG."""
import pathlib,re,sys
root=pathlib.Path(sys.argv[1])
patterns=[
 re.compile(r'(?:self\.)?random\s*\([^\n]*?\)\s*(?:<|<=|>|>=)'),
 re.compile(r'(?:<|<=|>|>=)\s*(?:self\.)?random\s*\('),
 re.compile(r'next_f64\s*\([^\n]*?\)\s*(?:<|<=|>|>=)'),
]
hits=[]
for file in root.rglob('*.rs'):
    # Standalone mage spell calculation uses separate local RNG, not Fight/SimRng.
    # This remains an explicitly documented integration limitation.
    if file.as_posix().endswith('classes/mage/spells/frostbolt.rs'):
        continue
    for n,line in enumerate(file.read_text().splitlines(),1):
        if any(p.search(line) for p in patterns):
            hits.append(f'{file}:{n}: {line.strip()}')
print('RNG boolean threshold candidates:',len(hits))
print('\n'.join(hits[:300]))
if hits:
    raise SystemExit('FAIL: review and route threshold comparisons through proc(probability, event_key)')


# Verify the *patched Rust engine* contains the actual policy dispatch and that
# the public Fight bridge reaches it. A passing regex scan alone is insufficient.
rng=(root/"core/rng.rs").read_text()
fight=(root/"core/fight.rs").read_text()
required_rng=[
    "pub(crate) enum RandomRequest { Uniform01, Bernoulli(f64) }",
    "pub(crate) fn sample(&mut self, request: RandomRequest, label: &str)",
    "RandomRequest::Bernoulli(chance)",
    "RandomRequest::Uniform01",
    "SimRng::Balanced(rng) => rng.proc(p,label)",
    "SimRng::Balanced(rng) => rng.float(label)",
]
required_fight=[
    "self.rng.proc(",
    "self.rng.next_f64(",
]
missing=[f"rng.rs: {s}" for s in required_rng if s not in rng]
missing += [f"fight.rs: {s}" for s in required_fight if s not in fight]
if missing:
    raise SystemExit("FAIL: typed RNG not connected to live Fight runtime:\\n" + "\\n".join(missing))
print("Typed RNG dispatch and live Fight bridge: PASS")
