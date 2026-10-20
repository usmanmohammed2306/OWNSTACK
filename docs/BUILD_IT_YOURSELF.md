# Learn from the complete reference

Use the active [NINETY_DAY_PLAN.md](NINETY_DAY_PLAN.md) for ninety dated feature
slices, October 14 to January 11, with daily commit suggestions, negative checks,
official reading and a short lesson command. The user-selected rebuild starter is
`../ownstack-rebuild`. [LEARNING_GUIDE.md](LEARNING_GUIDE.md) preserves the original
thirty-day calendar as history. Production and submission gates stay documented
in UNPROVEN, independently of the learning schedule.

Today: implement only the Day 1 pure read decision in the rebuild starter.
Predict same-tenant admin allowed and ungranted contractor denied, then run
`python3 -m unittest discover -s tests -v` there. The starter has two intentional
errors until you implement the function. Record your own observed passing result
and commit only the reviewed slice. Tomorrow add direct cross-tenant denial.

October 10 optional measured-performance slice: use [PERFORMANCE](PERFORMANCE.md)
to predict first-valid-grant selection, rebuild the SQL selector and prove parity
with the pure policy. A small-workload slowdown is a useful result too. Save your
own raw timings and narrow commit, not an invented performance/adoption claim.

October 10 recovery slice: [RELIABILITY_LAB](RELIABILITY_LAB.md) contains exact
commands, real-process crash checkpoints, five defective baselines, official
readings, symptoms and three personal reconstruction commits. Predict crash
before versus after commit first. Rebuild one case yourself before copying a
whole harness. No inference is needed and the exhausted allowance is not renewed.
