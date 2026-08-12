# Validation

Evidence levels are deliberately separate:

1. **L1 regression:** official SU2 examples verify executable and pipeline compatibility.
2. **Public numerical comparison:** NASA TMR NACA0012 data checks coefficient and GCI algorithms under explicitly matched assumptions.
3. **Grid study:** coarse/medium/fine cases must all converge before Phoenix reports GCI.
4. **Private model diagnosis:** user CAD, including example_model.STEP, is never a public benchmark.

Current retained results and failures are listed in [benchmark matrix](validation/benchmark-matrix.md). A Windows SU2 CGNS access violation prevented a full public NASA grid-family solve; the published NASA table is used only to verify the GCI implementation and is labelled accordingly.
