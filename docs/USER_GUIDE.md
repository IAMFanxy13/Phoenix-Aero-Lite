# User Guide / 用户指南

## 1. Prepare the aircraft

Upload STEP/STP. Phoenix copies the file into a task directory and never modifies the original. Confirm dimensions and geometry diagnostics. A blocker prevents engineering analysis; a warning remains visible.

Use the 3D picker to identify nose and upper direction, then click the left and right main-wing surfaces. Orange surfaces are selected; click again to deselect. Phoenix recomputes `S_ref`, `c_ref` and span from the selected real surface geometry. Automatic and user-overridden values remain separately recorded.

## 2. Set the flight condition

Normal users enter speed, angle of attack and mass. Density, viscosity, reference values, mesh size and iteration limit are under advanced settings. Each preset displays purpose, expected runtime, near-wall intent and maximum evidence level.

## 3. Run and monitor

Progress names real stages: geometry, mesh, configuration, solve, convergence, post-processing and report. Cancel requests terminate the external process through the existing process runner. A conservative retry creates one child task and never overwrites the failed task.

## 4. Read results

Read in this order: plain-language verdict, health checks, CL/CD/L/D and loads, then professional evidence. Pressure/Cp, velocity slices and streamlines come from real SU2 VTK outputs. Failed streamlines remain failed; no substitute geometry is generated.

Unconverged fields may be useful for diagnosis, but coefficients are downgraded and no take-off claim is allowed. Lift greater than weight is only one force comparison, not proof of stable or safe flight.

## 5. Run a three-grid study

Open **Advanced settings**, select **Three-grid study**, and submit the same
confirmed model and flow condition. Phoenix creates three independent coarse,
medium and fine child jobs on the existing single-worker queue. The study view
shows each job's actual cell count, CL, CD and elapsed time. It computes the
existing three-dimensional GCI only when all three jobs completed, converged,
share the same model/physics/setup fingerprint and form a valid refinement
family.

If a child fails, stagnates, produces incomplete data or does not actually
refine the grid, the study remains **blocked** and no substitute GCI is shown.
Cancelling the group preserves completed children but records the whole study
as user-cancelled. The browser URL contains `?study=...`; reopening or
refreshing that URL restores the persisted group table and GCI view.
