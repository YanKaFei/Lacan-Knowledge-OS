# Community submissions

Prepared, reviewable submissions for community registries. Each directory contains the exact
file(s) to submit plus the PR body.

| Registry | File to submit | Status |
|---|---|---|
| [awesome-dsh-plugin](https://github.com/awesome-dsh-plugin/awesome-dsh-plugin) | `awesome-dsh-plugin/YanKaFei__Lacan-Knowledge-OS.yml` → `data/plugins/` | **prepared, not yet submitted** |

## Why it is prepared rather than submitted

The list's contribution rules require the submitted repository to be **at least one day old**
(checked automatically) — the rule exists to filter repos created minutes before their PR. This
repository was published on 2026-09-30, so the submission is staged here and can be opened on or
after **2026-10-01**.

To submit (no fork needed if you have write access to a fork):

```sh
gh repo fork awesome-dsh-plugin/awesome-dsh-plugin --clone
cd awesome-dsh-plugin
mkdir -p data/plugins
cp ../Lacan-Knowledge-OS/contributions/awesome-dsh-plugin/YanKaFei__Lacan-Knowledge-OS.yml data/plugins/
npm ci && node scripts/generate-readme.mjs     # regenerates both READMEs from the data files
git checkout -b add-lacan-knowledge-os
git add data/plugins/YanKaFei__Lacan-Knowledge-OS.yml README.md README.zh.md
git commit -m "Add YanKaFei/Lacan-Knowledge-OS"
gh pr create --title "Add YanKaFei/Lacan-Knowledge-OS" \
  --body-file ../Lacan-Knowledge-OS/contributions/awesome-dsh-plugin/PR_BODY.md
```

The list is also mirrored inside DSH by
[dsh-market](https://github.com/dsh-market/dsh-market), which reads the same plugin metadata —
so a merged entry shows up in the in-harness storefront as well.
