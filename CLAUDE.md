# CLAUDE.md — babelchef-live-translator

## Working with the owner — do it yourself, the owner is the last resort

- If a step can be done with the tools you have (git, gh, gcloud, file edits, browser, APIs),
  do it yourself. Never hand the owner a command or a click you could have run — that
  includes the whole PR loop: branch, commit, push, open the PR, wait for CI, merge on green,
  clean up branches, verify after deploy.
- Hand something to the owner only when genuinely blocked: a permission/classifier denial, a
  sign-in or credential only they hold, a money decision, or a product decision that is
  theirs. Try every legitimate route first.
- When you must hand it over, give the exact how, not the what: every command in its own
  `bash` block, in order, starting with `cd` to the repo (their terminal is often elsewhere),
  or the exact click path in a UI, plus what success looks like. Then check the result
  yourself instead of asking what happened.
