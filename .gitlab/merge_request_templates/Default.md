## What and why

<!-- What this MR changes and why. Link the spec in docs/plans/ if there is one. -->

## How it was verified

<!-- Commands run, pages clicked through, screenshots. There is no frontend test runner. -->

## Checklist

- [ ] `python scripts/check_theme.py` passes (frontend changes only). It is a manual gate, not
      run in CI: after the palette was replaced by theme tokens, a leftover raw colour class
      such as `bg-slate-800` compiles to nothing, with no error.
