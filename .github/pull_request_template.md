<!-- AGENTS.md section 6. Fill every section; write "none" and why if one does not apply. -->

## Why the change

<!-- One paragraph. What was wrong or missing, who is affected. -->

## Spec items closed

<!-- docs/specs/<file>.md item ids, for example W2 (AC2.1 to AC2.10). -->

## Change outline

<!-- File by file, one line each. Name functions, not feelings. -->

## Verification evidence

<!-- Rule V2. Paste commands and the summary counts for the head commit. -->

```
make check
forge test:    <n> passed
pytest:        <n> passed
vitest:        <n> passed
evals:         bypass 0/<n>, report diff clean
make e2e:      <n> passed | not run because <reason per V5>
```

## Tests added, and tests whose expectations changed

<!-- Rule T2 and T3. New test names. For each changed expectation: file, old value, new value, why. -->

## Class search

<!-- Rule G2. The grep you ran for siblings of the defect, its output, and what you did with each hit. -->

## Risks and rollback

<!-- What could go wrong in production, how a reviewer would notice, how to revert. -->

## Screens or terminal captures

<!-- Rule G8. Required when a human facing surface changed. -->
