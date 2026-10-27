# UI review (qa/RC2), vs docs/design/direction.md
Screenshots (light+dark, 1440 wide, my own stack with real data from run qa2-clean): screens/*.png.
- Overview: PASS. Verdict headline, 4 tiles filled, worst calls, platform health with consumer-lag list capped ("and 19 more"), recent runs, review list scoped to the agent. Minor: the worst-calls panel is stretched to equal height, leaving empty space with only 3 calls. Open DLQ 65 / lag rows are test pollution from the Kafka suite, not a product state.
- Run detail: PASS. Title and "No failures" banner derived from calls, matrix and histogram correct, "not measured" with reason for latency/barge-in, calls table with filters.
- Dialect: PASS (empty state on my fresh stack, clean and honest). The report view was checked from FIX-02's own screenshot (proof/FIX-02/screenshots/dialect-report-light.png): synthetic groups labelled, low-n hatched, "Not enough clips" headline. It is synthetic data; real consented clips (H-02) are still owed.
- Run compare: not reviewed (FE-03 pending owner decision).
