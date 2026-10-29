# Supplied executor candidates

These bounded patches were prepared with coding assistance from the
published problem descriptions and pinned source, then corrected using
the independent upstream tests. No reference solution was supplied to the
generator. These are not predictions made by OwnStack's Nemotron runtime and
must not be reported as a model benchmark, independently held-out generalization
or human-authored work. Run them with `--origin model`.

| Candidate | Published source | Pinned revision |
| --- | --- | --- |
| flask-blueprints.json | https://github.com/pallets/flask/pull/4045 | d8c37f43724cd9fb0870f77877b7c4c7e38a19e0 |
| flask-decimal.json | https://github.com/pallets/flask/pull/4160 | 06cf349bb8b69d9946c3a6a64d32eb552cc7c28b |
| flask-exception.json | https://github.com/pallets/flask/pull/4169 | 66d9d4fa8d07dd50e4cb3036a9ae5f92c4693b84 |
| pytest-approx.json | https://github.com/pytest-dev/pytest/pull/10624 | 7421f3bb94df80ff2d131e932223b190f9b6d7b6 |
| sphinx-napoleon.json | https://github.com/sphinx-doc/sphinx/pull/7738 | c087d717f6ed183dd422359bf91210dc59689d63 |
| sphinx-signature.json | https://github.com/sphinx-doc/sphinx/pull/7757 | 212fd67b9f0b4fae6a7c3501fdf1a9a5b2801329 |
| jinja-native.json | https://github.com/pallets/jinja/pull/1537 | a4e2532489f804996be36ae32c25a69298bd1106 |

Flask is copyright the Pallets contributors and distributed under its BSD-3-Clause
license. Preserve the upstream license with downloaded source. Only small
anchored source edits are included here; the source archives and oracle patches
remain separate from these candidates. The published SWE-bench test cases remain
held out from training even when a supplied candidate passes.

Pytest is distributed under MIT; Sphinx and Jinja use BSD licenses. Preserve each
upstream license in downloaded source. REPOSITORY_EXPANSION records their exact
execution scope and retained failures. Jinja is a separate Nebius train-source
case with an explicit versioned oracle-ID expansion. It is not automatically
training-eligible: source reconstruction, rights and actual human review remain
gates. No new model training or OwnStack/Nemotron inference generated these patches.
