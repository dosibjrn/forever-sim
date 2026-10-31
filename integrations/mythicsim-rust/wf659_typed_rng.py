#!/usr/bin/env python3
"""Apply after WF652 patch: one typed RNG policy for stochastic and balanced."""
from pathlib import Path
p=Path("src/core/rng.rs")
s=p.read_text()
marker="pub(crate) enum SimRng {"
assert s.count(marker)==1
s=s.replace(marker, """#[derive(Clone, Copy)]
pub(crate) enum RandomRequest { Uniform01, Bernoulli(f64) }

pub(crate) enum RandomOutcome { Float(f64), Bool(bool) }

"""+marker)
# Move existing policy into a single typed dispatch. Public legacy signatures are wrappers.
start=s.index("    pub(crate) fn proc(&mut self, chance: f64, label: &str) -> bool {")
end=s.index("\n    }",start)+6
s=s[:start]+"""    pub(crate) fn proc(&mut self, chance: f64, label: &str) -> bool {
        match self.sample(RandomRequest::Bernoulli(chance), label) {
            RandomOutcome::Bool(value) => value,
            _ => unreachable!(),
        }
    }"""+s[end:]
start=s.index("    pub(crate) fn next_f64(&mut self, label: &str) -> f64 {")
end=s.index("\n    }",start)+6
s=s[:start]+"""    pub(crate) fn next_f64(&mut self, label: &str) -> f64 {
        match self.sample(RandomRequest::Uniform01, label) {
            RandomOutcome::Float(value) => value,
            _ => unreachable!(),
        }
    }"""+s[end:]
anchor="impl SimRng {"
assert s.count(anchor)==1
s=s.replace(anchor,anchor+"""
    /// The one entry point to both RNG modes. Callers must state whether
    /// their draw is continuous or a Bernoulli decision.
    pub(crate) fn sample(&mut self, request: RandomRequest, label: &str) -> RandomOutcome {
        match request {
            RandomRequest::Uniform01 => {
                let value = match self {
                    SimRng::Balanced(rng) => rng.float(label),
                    SimRng::Shared(rng) => rng.next_f64(),
                    SimRng::Labeled { seed, streams } => {
                        if let Some((_,rng)) = streams.iter_mut().find(|(name,_)| name == label) {
                            rng.next_f64()
                        } else {
                            let mut rng = SplitMix64::new(labeled_seed(*seed,label));
                            let value = rng.next_f64();
                            streams.push((label.to_owned(),rng));
                            value
                        }
                    }
                };
                RandomOutcome::Float(value)
            }
            RandomRequest::Bernoulli(p) => {
                let value = match self {
                    SimRng::Balanced(rng) => rng.proc(p,label),
                    _ if p>=1.0 => true,
                    _ if p<=0.0 => false,
                    _ => matches!(self.sample(RandomRequest::Uniform01,label),
                        RandomOutcome::Float(x) if x < p),
                };
                RandomOutcome::Bool(value)
            }
        }
    }
""",1)
assert "self.sample(RandomRequest::Bernoulli(chance), label)" in s
assert "self.sample(RandomRequest::Uniform01, label)" in s
p.write_text(s)
