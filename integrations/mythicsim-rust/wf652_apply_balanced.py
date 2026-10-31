#!/usr/bin/env python3
"""WF652: whole-engine RNG mode switch, preserving the pinned stochastic baseline.

WOWSIM_RNG_MODE=stochastic (default): exact upstream SplitMix64.
WOWSIM_RNG_MODE=balanced: uniform draws -> 0.5; Bernoulli draws -> cumulative
nearest-integer quota per stable event label, across fight iterations.

This is an experimental deterministic approximation, NOT exact analytic expected
DPS for nonlinear combat dynamics or a substitute for stochastic validation.
"""
from pathlib import Path

p=Path("src/core/rng.rs")
s=p.read_text()
needle="pub(crate) enum SimRng {"
assert s.count(needle)==1, "Unexpected Rust RNG upstream revision"
s=s.replace(needle, """/// Cumulative quota RNG: E[# successes] follows sum of probabilities to within
/// 0.5 successes, independently for each event label across ALL fight iterations.
#[derive(Default)]
pub(crate) struct BalancedRng {
    binary: std::collections::HashMap<String, (f64, u64)>,
}
impl BalancedRng {
    fn proc(&mut self, p: f64, key: &str) -> bool {
        assert!(p.is_finite() && (0.0..=1.0).contains(&p),
            "balanced RNG: probability must be finite and in [0,1]");
        let (expected, successes) = self.binary.entry(key.to_owned()).or_default();
        *expected += p;
        let target = (*expected + 0.5).floor() as u64;
        // A single Bernoulli event can increase the rounded target by at most 1.
        let outcome = *successes < target;
        if outcome { *successes += 1; }
        outcome
    }
    fn float(&self, _key: &str) -> f64 {
        // For U[0,1), E[U] = 0.5. Callers doing NONLINEAR transformations
        // need explicit analytical expectations (or quadrature), separately.
        0.5
    }
}
""" + needle)
s=s.replace(needle,needle+"\n    Balanced(BalancedRng),",1)
needle_new="    pub(crate) fn new(labeled: bool, seed: u64) -> Self {"
assert s.count(needle_new)==1
s=s.replace(needle_new,needle_new+"""
        match std::env::var("WOWSIM_RNG_MODE").as_deref() {
            Ok("balanced") => return SimRng::Balanced(BalancedRng::default()),
            Ok("stochastic") | Err(std::env::VarError::NotPresent) => {},
            _ => panic!("unknown WOWSIM_RNG_MODE; expected stochastic or balanced"),
        }
""",1)
needle_reseed="        match self {\n            SimRng::Shared(rng) => *rng = SplitMix64::new(iteration_seed),"
assert s.count(needle_reseed)==1
s=s.replace(needle_reseed,"        match self {\n            // Do NOT clear quotas between fights; else low-frequency procs are biased.\n            SimRng::Balanced(_) => {},\n            SimRng::Shared(rng) => *rng = SplitMix64::new(iteration_seed),",1)
needle_proc="    pub(crate) fn proc(&mut self, chance: f64, label: &str) -> bool {"
assert s.count(needle_proc)==1
s=s.replace(needle_proc,needle_proc+"""
        if let SimRng::Balanced(rng) = self { return rng.proc(chance, label); }
""",1)
needle_float="        match self {\n            SimRng::Shared(rng) => rng.next_f64(),"
assert s.count(needle_float)==1
s=s.replace(needle_float,"        match self {\n            SimRng::Balanced(rng) => rng.float(label),\n            SimRng::Shared(rng) => rng.next_f64(),",1)
s+="""
#[cfg(test)]
mod wf652_balanced_tests {
    use super::*;
    #[test]
    fn continuous_uniform_is_expectation() {
        let mut rng=SimRng::Balanced(BalancedRng::default());
        for _ in 0..100 {
            assert_eq!(rng.next_f64("Damage Roll"),0.5);
        }
    }
    #[test]
    fn bool_frequency_closest_to_cumulative_probability() {
        let mut rng=BalancedRng::default();
        for (p,n) in [(0.13,100u64),(0.72,100u64),(0.001,1000u64)] {
            let key=format!("event-{p}");
            let observed=(0..n).filter(|_|rng.proc(p,&key)).count();
            assert!((observed as f64 - (n as f64)*p).abs() <= 0.500000001);
        }
    }
    #[test]
    fn variable_probability_and_label_isolation() {
        let mut rng=BalancedRng::default();
        let mut expected=0.0;
        let mut observed=0u64;
        for i in 0..100 {
            let p=(i%17) as f64 / 17.0;
            expected+=p;
            if rng.proc(p,"a"){observed+=1;}
            assert!((observed as f64-expected).abs()<=0.500000001);
            assert!(rng.proc(1.0,"b"));
            assert!(!rng.proc(0.0,"c"));
        }
    }
    #[test]
    fn quotas_persist_over_reseed() {
        let mut rng=SimRng::Balanced(BalancedRng::default());
        let mut observed=0;
        for i in 0..100 {
            rng.reseed(i);
            if rng.proc(0.13,"rare") { observed+=1; }
        }
        assert_eq!(observed,13);
    }
    #[test]
    fn mode_switch_independent_of_seed_for_balanced() {
        // Avoid mutating process-global env in this test. Explicit constructors
        // validate mode mechanics; CLI smoke validates env selection.
        let mut a=SimRng::Balanced(BalancedRng::default());
        let mut b=SimRng::Balanced(BalancedRng::default());
        for i in 0..100 {
            a.reseed(i);b.reseed(i+10000);
            assert_eq!(a.proc(0.23,"crit"),b.proc(0.23,"crit"));
            assert_eq!(a.next_f64("damage"),b.next_f64("damage"));
        }
    }
}
"""
p.write_text(s)
# Boolean crit thresholds must use the quota API; uniform mean 0.5
# is for genuinely continuous draws, never for a Bernoulli decision.
d=Path("src/core/fight/damage.rs")
ds=d.read_text()
replacements={
    'self.random("Magical Crit Roll") < self.spell_crit_chance(spell)':
      'self.proc(self.spell_crit_chance(spell), "Magical Crit Roll")',
    'self.random("Magical Crit Roll") < self.tick_crit_chance(spell)':
      'self.proc(self.tick_crit_chance(spell), "Magical Crit Roll")',
}
for original,corrected in replacements.items():
    assert original in ds, "Expected hit/crit code changed upstream: "+original
    ds=ds.replace(original,corrected)
d.write_text(ds)

# All spell critical outcomes are Bernoulli, including physical crits.
physical='self.random("Physical Crit Roll") < self.physical_crit_chance(spell)'
assert physical in ds
ds=ds.replace(physical,'self.proc(self.physical_crit_chance(spell), "Physical Crit Roll")')
d.write_text(ds)

# Guard the two known binary decisions against accidental regression.
assert 'self.random("Magical Crit Roll") <' not in ds
assert 'self.random("Physical Crit Roll") <' not in ds

