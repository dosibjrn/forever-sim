from pathlib import Path
p = Path("src/core/rng.rs")
s = p.read_text()
needle = "pub(crate) enum SimRng {"
assert s.count(needle) == 1
s=s.replace(needle, """#[derive(Default)]
struct BalancedRng {
    binary: std::collections::HashMap<String, (f64, u64)>,
    uniform: std::collections::HashMap<String, u64>,
}
impl BalancedRng {
    fn proc(&mut self, p: f64, key: &str) -> bool {
        assert!(!p.is_nan(), "balanced RNG: NaN probability");
        let (expected, observed) = self.binary.entry(key.to_owned()).or_default();
        *expected += p.clamp(0.0, 1.0);
        let success = (*observed as f64) < (*expected + 0.5).floor();
        if success { *observed += 1; }
        success
    }
    fn float(&mut self, key: &str) -> f64 {
        let n = self.uniform.entry(key.to_owned()).or_default();
        *n += 1;
        (*n).reverse_bits() as f64 / (18446744073709551616.0_f64)
    }
    fn reset(&mut self) {
        self.binary.clear();
        self.uniform.clear();
    }
}
""" + needle)
s=s.replace(needle, needle+"\n    Balanced(BalancedRng),", 1)
s=s.replace("    pub(crate) fn new(labeled: bool, seed: u64) -> Self {", """    pub(crate) fn new(labeled: bool, seed: u64) -> Self {
        match std::env::var("WOWSIM_RNG_MODE").as_deref() {
            Ok("balanced") => return Self::Balanced(BalancedRng::default()),
            Ok("stochastic") | Err(std::env::VarError::NotPresent) => {},
            _ => panic!("unknown WOWSIM_RNG_MODE"),
        }
""",1)
s=s.replace("        match self {\n            SimRng::Shared(rng) => *rng = SplitMix64::new(iteration_seed),","        match self {\n            SimRng::Balanced(rng) => rng.reset(),\n            SimRng::Shared(rng) => *rng = SplitMix64::new(iteration_seed),",1)
s=s.replace("    pub(crate) fn proc(&mut self, chance: f64, label: &str) -> bool {", """    pub(crate) fn proc(&mut self, chance: f64, label: &str) -> bool {
        if let SimRng::Balanced(rng) = self { return rng.proc(chance, label); }
""",1)
s=s.replace("        match self {\n            SimRng::Shared(rng) => rng.next_f64(),","        match self {\n            SimRng::Balanced(rng) => rng.float(label),\n            SimRng::Shared(rng) => rng.next_f64(),",1)
s += """
#[cfg(test)]
mod balanced_tests {
    use super::*;
    #[test]
    fn quota_72_percent() {
        let mut rng = BalancedRng::default();
        let outcomes: Vec<_> = (0..4).map(|_| rng.proc(0.72, "crit")).collect();
        assert_eq!(outcomes, [true, false, true, true]);
    }
    #[test]
    fn isolation_and_reset() {
        let mut rng = BalancedRng::default();
        assert_eq!(rng.float("a"), 0.5);
        assert_eq!(rng.float("b"), 0.5);
        assert!(rng.proc(1.0, "x"));
        rng.reset();
        assert_eq!(rng.float("a"), 0.5);
    }
}
"""
p.write_text(s)
