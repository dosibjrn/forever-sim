# Pinned MythicSim Go build — evidence

**Build gate: PASS.** This is a build/smoke gate, **not** native Go P7.1.2 parity.

- Workflow: https://github.com/dosibjrn/mage-level-sim/actions/runs/40900215711
- Upstream repository: https://github.com/sage3648/mythicsim-forever-engine-go
- Exact Go source revision: `a667dce8492bd9fb94269a9f864289cb74006775`
- Go source archive and compiled Linux x86-64 CLI: artifact `mythicsim-go-pinned-linux-x64` on the workflow
- Build generated protobuf bindings with `make sim/core/proto/api.pb.go`, then ran `go build -trimpath -o ../publish/wowsimcli ./cmd/wowsimcli`.
- Job `go`: **success**.
- Binary SHA-256 (verified after download): `ea8ba64fd3318b32c71d438cf09a8097472317d0b1f27cd94d4036af361d1cc9`
- File type: ELF 64-bit Linux x86-64; `wowsimcli --help` returned exit 0.
- Raw compile logs: workflow job `go`; source archive and bin in artifact.
- Open: real native Go reference parity (P7.1.2), 2D integration, independent stochastic holdout.

The generated SHA256SUMS entry names the original `publish/wowsimcli` CI path; comparison above was verified against extracted bytes.
