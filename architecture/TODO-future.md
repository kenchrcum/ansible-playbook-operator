## Ansible Playbook Operator — Future Development TODO

This file tracks work planned for future phases beyond the current v1alpha1 scope. Items here are not part of the immediate development priorities but represent important future enhancements.

### CI/CD and Release
- [ ] CI pipeline: ruff, black, mypy, unit tests, minimal kind e2e smoke, chart lint; secret scanning and dependency audit.
- [ ] Supply chain: SBOM (Syft) and image scan (Trivy/Grype); publish digests on release; changelog automation.

### Later-phase (v1beta1+) considerations
- [ ] Introduce a dedicated `Run` CR (instead of annotation) for ad-hoc executions with history and status.
- [ ] Conversion and migration docs for any breaking CRD changes.
