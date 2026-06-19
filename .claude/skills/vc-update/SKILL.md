---
name: vc-update
description: Pull latest agent harness improvements from the remote kit repository. Shows a dry-run diff summary, waits for confirmation, then applies updates.
trigger_keywords: update harness, pull kit, sync harness, upgrade agents
layer: contract
metadata:
  author: vibecode
  version: "3.0.0"
---

# vc-update

> **Output style:** Follow `process/development-protocols/communication-standards.md` — answer-first, plain language, no unexplained jargon, TL;DR on long responses.

Pull the latest agent harness improvements from the remote vibecode-pro-max-kit repository into the current project.

## When to Use

- After being told a new harness version is available
- Periodically to check for updates
- After bootstrapping a project with `vc-setup` and wanting the latest improvements

## Workflow

Follow these steps exactly. Do NOT skip the dry-run or confirmation step.

### Step 1: Check Worktree Status

Run `git status --porcelain` in the project root.

- If output is non-empty: **warn** the user that they have uncommitted changes and suggest `git stash` or committing first. **Do not block** -- continue after warning.
- If output is empty: proceed silently.

### Step 2: Read Current Version

Read the file `.vc-version` in the project root.

- If it exists: store its contents as `currentVersion` (a semver string like `2.0.4`).
- If it does not exist: set `currentVersion` to `"0.0.0"` (treat as first update).

### Step 3: Clone Remote Repository

```bash
# Respect VC_KIT_SOURCE override (local path or alternate URL).
# When unset, defaults to the official remote.
KIT_SOURCE="${VC_KIT_SOURCE:-https://github.com/withkynam/vibecode-pro-max-kit.git}"
VC_UPDATE_TMPDIR="/tmp/vc-update-$(date +%s)"
git clone --local --depth 1 --quiet "$KIT_SOURCE" "$VC_UPDATE_TMPDIR" 2>/dev/null \
  || git clone --depth 1 --quiet "$KIT_SOURCE" "$VC_UPDATE_TMPDIR"
# Note: --local is a no-op for remote URLs (git ignores it); the fallback covers all cases.
```

> `VC_KIT_SOURCE` — if set, use this path or URL instead of the official remote. Accepts any value accepted by `git clone`. This enables offline testing (`VC_KIT_SOURCE=/path/to/local/kit`) and forks/pinned versions.

If the clone fails (network error, auth error, repo not found):
- Print the error message.
- Clean up the temp directory if it was partially created.
- **Stop.** Do not proceed.

### Step 4: Resolve Remote Manifest

Run the resolver script from the cloned repo:

```bash
node "$VC_UPDATE_TMPDIR/resolve-manifest.mjs" --root "$VC_UPDATE_TMPDIR" --json
```

Parse the JSON output to extract:
- `files` (string[]) -- resolved managed file paths
- `merge` (string[]) -- files where user customizations are preserved (not overwritten)
- `copyIfMissing` (string[]) -- files only installed if they don't already exist locally
- `strip` (string[]) -- files needing content stripping (informational)
- `symlinks` (object) -- symlink path -> target mappings
- `legacyDeletions` (string[]) -- paths to delete on migration (present in kit v3.0.0+; absent in older kits)

Extract the remote version from the manifest:
```bash
node -e "console.log(JSON.parse(require('fs').readFileSync('$VC_UPDATE_TMPDIR/vc-manifest.json','utf8')).version)"
```

**Retain Step 4 output through Step 7:** Keep the full resolver JSON (especially `symlinks`) in memory. `compute-sync-plan.mjs --json` (Steps 6/10) does not re-emit `symlinks`, so Step 7 depends on the Step 4 value.

**Legacy fallback:** If `resolve-manifest.mjs` does not exist in the remote (very old kit version), fall back to reading `vc-manifest.json` directly and using the old `managed`/`managedDirs`/`seedsDir` fields for file resolution.

### Step 5: Compare Versions

Compare the remote manifest `version` against `currentVersion`.

- If they are equal: report **"Already up to date (vX.Y.Z)"** and clean up `$TMPDIR`. **Stop.**
- If remote is newer (or currentVersion is `0.0.0`): continue to diff.
- If remote is **older** than `currentVersion`: print `⚠ WARNING: downgrade v{remoteVersion} → v{currentVersion} detected. The source kit is older than your installed version. Continuing will overwrite newer harness files with older ones.` then ask for explicit confirmation before continuing. If the user does not confirm, clean up `$VC_UPDATE_TMPDIR` and stop.

### Step 6: Read Local Snapshot and Compute Diff

**Computation via `compute-sync-plan.mjs`:** Once the remote manifest is resolved (Step 4), invoke the shared computation core:

```bash
node "$VC_UPDATE_TMPDIR/compute-sync-plan.mjs" \
  --root "$PROJECT_ROOT" \
  --kit-root "$VC_UPDATE_TMPDIR" \
  --json
```

Parse the JSON output: `{ toAdd, toModify, toDelete, toPreserve, staleWarnings }`.
- `toAdd` — files to copy from kit to project (not yet present or tracked).
- `toModify` — files to overwrite (tracked, present, content differs).
- `toDelete` — stale kit files to remove (in old snapshot, not in new ownedPaths, passed namespace guard).
- `toPreserve` — files to leave untouched (merge/copyIfMissing survivors, user-owned files).
- `staleWarnings` — paths that were in snapshot but failed namespace guard — print to user; do NOT delete.

The manual snapshot-reading and diff logic in the previous version of this step is replaced by this invocation. The prose description of the algorithm is preserved in `references/vc-update.md` for reference.

**Fallback — no `.vc-installed-files` (first update with new system):**
When the snapshot file is absent, `compute-sync-plan.mjs` sets `priorSnapshot = []` (empty — no disk scan). No stale removal occurs via the snapshot path because there are no prior entries to compare against. `legacyDeletions` from the manifest are still applied independently (step 4 in the function) and may delete old paths that exist on disk. `.vc-installed-files` is written only when `--apply` is passed, not during a `--json` dry-run.

**Merge files** (e.g. `.claude/settings.json`): files in the `merge` list that exist locally are placed in `toPreserve` by compute-sync-plan.mjs — they are never overwritten. Show the diff for manual review, flag for manual review.

**Copy-if-missing files:** files in the `copyIfMissing` list that already exist locally are also placed in `toPreserve`. Show the diff but note they will NOT be overwritten.

### Step 7: Check Symlinks

For each entry in the `symlinks` object (key = symlink path, value = target):

- If the symlink exists and points to the correct target: mark as **ok**.
- If the symlink is missing or points to a different target: mark as **will fix**.
- If a real directory exists at the symlink path (not a symlink): mark as **will replace dir with symlink**.

### Step 8: Print Dry-Run Summary

Print a summary with all collected results. Format:

```
vc-update dry run: v{currentVersion} -> v{remoteVersion}

FILES:
  [modified]  .claude/agents/vc-execute-agent.md  (+12 -3)
  [new]       .claude/hooks/lib/new-util.cjs
  [removed]   .claude/skills/deprecated-skill/SKILL.md
  [unchanged] .claude/agents/vc-debugger.md
  ...

MERGE (preserved, manual review needed):
  [differs]   .claude/settings.json  (+2 -1)

COPY-IF-MISSING (skipped, already present):
  (none)

SYMLINKS:
  [ok]        .agents/skills -> ../.claude/skills
  [will fix]  .codex/hooks -> ../.claude/hooks

STALE WARNINGS: N paths failed the namespace guard (showing first 5 — see full compute-sync-plan output)
  .claude/skills/my-custom-vc-tool/SKILL.md
  ...

Summary: 5 modified, 2 new, 1 removal, 1 merge skipped, 45 unchanged
```

If `staleWarnings` is empty, omit the `STALE WARNINGS` section entirely. If non-empty, print the count and the first 5 entries only — do not dump all paths. Stale warnings indicate vc-namespace paths in your prior snapshot that are not in the kit's known `ownedPaths`. **If you have a custom vc-\* skill at one of those paths, rename it before applying the update** to prevent it from being deleted as a stale kit artifact.

**Large-delete WARNING:** After computing the dry-run summary, check `toDelete.length`. If it exceeds 20 files OR exceeds 10% of the prior install file count (line count of `.vc-installed-files`), print the following block prominently before asking for confirmation:

```
⚠ WARNING: {N} files scheduled for removal — unusually high.
Verify this is an expected upgrade before applying.
Do NOT blindly approve when this warning appears.
```

Do not suppress this warning or fold it into the summary line. It must appear as a standalone block so the user cannot miss it.

### Step 9: Wait for Confirmation

**STOP HERE.** Tell the user:

> "This is a dry-run summary. Type **apply** to proceed with the update, or **abort** to cancel. The temp clone will be cleaned up either way."

Do NOT proceed until the user explicitly says "apply" (or a clear affirmative like "yes", "go", "do it").

If the user aborts:
- Remove `$VC_UPDATE_TMPDIR`.
- Print "Update cancelled. No changes made."
- **Stop.**

### Step 10: Apply Changes

On user confirmation, run in two parts:

**Isolation guarantee (Parts A/B):** `$VC_UPDATE_TMPDIR` is a read-only clone — no changes are made to it between calls. The project root is also not mutated before Part B runs. Both invocations therefore see the same sync plan, so the backup in Part A covers the exact set that Part B will overwrite.

**Part A — Back up files that will be modified or deleted (toModify + toDelete lists):**

Before applying, back up every file in `toModify` AND every file in `toDelete` so both overwritten content and deleted files are recoverable:

```bash
node "$VC_UPDATE_TMPDIR/compute-sync-plan.mjs" \
  --root "$PROJECT_ROOT" \
  --kit-root "$VC_UPDATE_TMPDIR" \
  --json | PROJECT_ROOT="$PROJECT_ROOT" node -e "
    const plan = JSON.parse(require('fs').readFileSync('/dev/stdin','utf8'));
    const fs = require('fs'), path = require('path');
    const root = process.env.PROJECT_ROOT;
    const backupDir = path.join(root, '.vibecode-backup');
    // Rotate any prior backup so re-runs never silently overwrite it
    if (fs.existsSync(backupDir) && fs.readdirSync(backupDir).length > 0) {
      const rotated = path.join(root, '.vibecode-backup-' + Math.floor(Date.now() / 1000));
      fs.renameSync(backupDir, rotated);
      console.log('Existing backup rotated to ' + path.relative(root, rotated) + '/');
    }
    for (const rel of [...plan.toModify, ...plan.toDelete]) {
      const src = path.join(root, rel);
      if (!fs.existsSync(src)) continue;
      const dst = path.join(backupDir, rel);
      const stat = fs.statSync(src);
      if (stat.isDirectory()) {
        fs.cpSync(src, dst, { recursive: true });
      } else {
        fs.mkdirSync(path.dirname(dst), { recursive: true });
        fs.copyFileSync(src, dst);
      }
    }
  "
# Note: this backup step assumes a POSIX shell. On Windows, skip or adapt it — /dev/stdin is unavailable.
```

(This preserves the pre-update versions of both overwritten and removed files, so any content is recoverable from `.vibecode-backup/`. If a `.vibecode-backup/` directory already exists from a prior run, it is rotated to a timestamped name (`.vibecode-backup-{unix-ts}/`) before the new backup is written, so earlier backups are never overwritten.)

**Part B — Apply the full plan with the single mechanical command:**

```bash
node "$VC_UPDATE_TMPDIR/compute-sync-plan.mjs" \
  --root "$PROJECT_ROOT" \
  --kit-root "$VC_UPDATE_TMPDIR" \
  --resolver "$VC_UPDATE_TMPDIR/resolve-manifest.mjs" \
  --apply
```

`--apply` deterministically executes the computed plan:
- **toAdd / toModify**: `mkdir -p` parent + copy from kit to project. `toPreserve` entries (merge/copyIfMissing survivors) are never touched.
- **toDelete**: each entry is removed — directories via `rmSync({recursive:true,force:true})`, files via `rmSync({force:true})`.
- **Empty-parent sweep**: after all deletions, every ancestor directory of every deleted path is walked deepest-first and `rmdirSync`'d if empty. This is the guaranteed cleanup that prevents hollow deprecated skill dirs (e.g. empty `references/`, `scripts/` subdirs) from surviving after a skill is removed.
- **Snapshot**: writes `.vc-installed-files` (sorted `managedFiles` — the `files` list from resolve-manifest; `legacyDeletions` are re-derived each run and not persisted).
- **Version**: writes `.vc-version` (manifest version string).
- **`.gitignore` guard**: after writing the version, apply ensures the project-root `.gitignore` contains `.vibecode-backup*/` (additive — creates the file if absent, appends the glob form `.vibecode-backup*/` if the glob form is missing even if a non-glob `.vibecode-backup/` line already exists, no-ops if the glob form is already present). This prevents rotated backup dirs (`.vibecode-backup-{ts}/`) from being accidentally committed.
- **staleWarnings (Type 1 — non-vc- namespace)**: paths in the prior snapshot that are not in the vc- namespace — moved to `toPreserve`, never deleted. Message form: `'X' in prior snapshot but not in kit namespace — preserved (verify manually)`.
- **staleWarnings (Type 2 — vc- namespace, `WARNING:` prefix)**: vc- namespace paths that are in `toDelete` but not in the known `ownedPaths`/`legacyDeletions` — these ARE deleted. The warning is advisory: if the user has a custom vc- skill at that path, rename it before updating.

Do NOT hand-loop `rm` or `cp` commands — use only the `--apply` invocation above. The mechanical implementation guarantees correct empty-dir cleanup on every run, including directory-shaped deletions and deeply nested deprecated skill subdirs.

**Part C — Symlinks** (handled separately, unchanged):

For each entry in `symlinks`:
- If a real directory exists at the path: `rm -rf` it first.
- If a wrong symlink exists: `rm` it first.
- Create the symlink: `ln -s {target} {path}`

**Part D — Clean up**:

```bash
rm -rf "$VC_UPDATE_TMPDIR"
```

If `--apply` exits non-zero (permission error, missing kit file):
- Print the error message.
- Suggest running `chmod` on the affected path or checking file ownership.
- The command exits 1; do not treat a partial run as success.

### Step 11: Print Applied Changes Summary and Post-Update NOTICE

```
vc-update complete: v{currentVersion} -> v{remoteVersion}

Applied:
  5 files modified
  2 files added
  1 file removed
  1 symlink fixed
  1 merge file preserved (review .claude/settings.json manually)

Snapshot written to .vc-installed-files
Version written to .vc-version: {remoteVersion}
```

**After printing the summary, run three post-update checks and print a NOTICE block:**

**Check A — `.agents/skills` symlink vs real directory:**

```bash
[ -L .agents/skills ] && echo "symlink" || echo "real-dir"
```

If the result is `real-dir` (Windows fallback — a real directory instead of a symlink), re-sync it now so it stays current with the updated `.claude/skills/`:

```bash
cp -r .claude/skills/. .agents/skills/
```

Print: `NOTICE: .agents/skills is a real directory (Windows fallback) — re-synced from .claude/skills/`

If it is a symlink, skip this step (the symlink already resolves to the updated `.claude/skills/`).

**Check B — `.claude/settings.json` merge-preserved hooks gap:**

If `.claude/settings.json` was in `toPreserve` (it was merge-protected), print the following NOTICE block verbatim so the user knows exactly what to add:

```
NOTICE: .claude/settings.json was preserved (merge-protected). New hooks added in
this release will NOT fire until you add them manually.

Missing hooks most likely absent from your v2.x install:

  PostToolUse (Write)  → post-write-plan-check.mjs   — validates plan artifact structure on every plan write
  PostToolUse (Bash)   → post-commit-lint.mjs         — lints commit messages for conventional-commit prefix
  Stop                 → stop-validator-sweep.cjs      — runs core validators on session end
  SubagentStart        → subagent-init.cjs             — injects compact context into every subagent

Paste-ready hooks block: see https://github.com/withkynam/vibecode-pro-max-kit/blob/main/MIGRATION.md#action-required-settingsjson-hooks
or diff .claude/settings.json .vibecode-backup/.claude/settings.json
```

If `.claude/settings.json` was NOT in `toPreserve` (it was freshly written), skip this notice.

**Check C — old-layout process/ folders:**

Scan for these two signals of pre-v3.0.0 plan layout:

1. Any `*.md` file matching `*_PLAN_*.md` that lives **directly** in `process/general-plans/active/` or `process/features/*/active/` (flat file, not inside a `{slug}_{date}/` subfolder).
2. Any `reports/` or `references/` directory that is a **sibling** of `active/`/`completed/`/`backlog/` under `process/general-plans/` or `process/features/*/`.

If either signal is found, print:

```
NOTICE: Old-layout process/ folders detected. v3.0.0 uses task-folder convention
(active/{slug}_{date}/{slug}_PLAN_{date}.md). Your existing plans still work as
read-only legacy artifacts, but new plans should use the task-folder layout.

To migrate automatically: run vc-setup (Flow B / Merge mode detects and migrates
old layouts with your approval before touching anything).
```

If no old-layout signals are found, print nothing for Check C.

**Recommended: run validators**

After the NOTICE block, print:

```
Recommended next step — run the five core validators:

  node .claude/skills/vc-audit-vc/scripts/validate-agent-parity.mjs
  node .claude/skills/vc-audit-vc/scripts/validate-skills.mjs
  node .claude/skills/vc-audit-vc/scripts/validate-kit-portability.mjs
  node .claude/skills/vc-audit-context/scripts/validate-context-discovery.mjs
  node .claude/skills/vc-context-discovery/scripts/discover-skills.mjs
```

## Rules

- `VC_KIT_SOURCE`: when set, overrides the remote URL for cloning. Used verbatim as the `git clone` source argument. No validation. Enables local testing and forks.
- `process/_seeds/` is a legacy optional scaffold surface. If a remote release still includes it, treat it as managed reference and overwrite it entirely on update. Its absence in the live repo is valid.
- Real working files outside `_seeds/` (`process/context/`, `process/features/`, `process/general-plans/`) are **NEVER** touched by vc-update.
- Always show the dry-run diff before applying. Never apply without user confirmation.
- Clean up the temp clone directory even on error or abort.
- If `.vc-version` is missing, treat as version `0.0.0` (first update, apply everything).
- `CLAUDE.md` and `AGENTS.md` are harness-only files -- overwritten freely on update. Project-specific content belongs in `process/context/all-context.md`, not in these files.
- Files in the `merge` list (e.g. `.claude/settings.json`) are never overwritten if they exist locally. Show the diff for manual review.
- Files in the `copyIfMissing` list are only installed if they don't already exist locally.
- Removals are detected by comparing the local `.vc-installed-files` snapshot against the new resolved file list.

## Migration from v2.x

Kit v3.0.0 introduces the `legacyDeletions` key in `resolveGlob()`'s JSON output (Step 4 above). **This note applies to users who are upgrading FROM a kit v2.x install that still has an OLD SKILL.md** (one that predates v3.0.0 and does not reference `compute-sync-plan.mjs`). When such a user runs `vc-update`, the remote resolver already emits `legacyDeletions` in its JSON output. The current SKILL.md (this file, v3.0.0+) reads and applies that field in Step 6 via `compute-sync-plan.mjs`. No local SKILL.md change is required on the user's side — the update process itself installs the new SKILL.md in the same run.

The one-shot migration on next `vc-update` from kit v3.0.0:
1. Resolver emits `legacyDeletions: [".claude/skills/vc-team", ".claude/skills/vc-chrome-devtools", ...]` in the JSON output.
2. Step 6 applies those deletions in addition to the normal snapshot diff.
3. The 11 deprecated skill dirs (vc-team, vc-chrome-devtools, vc-docs, vc-repomix, vc-preview, vc-merge-worktree, vc-tech-graph, vc-watzup, vc-xia, vc-mcp-management, vc-context-engineering) plus 5 deprecated protocol paths are removed from the local install in one pass.
4. Snapshot is written with the new v3.0.0 file list — subsequent updates use normal diff logic.

**Very old installs** (SKILL.md predating `legacyDeletions` support): use `install.sh` for a clean reinstall instead of `vc-update`.

## Reference

For detailed algorithm, error handling matrix, and edge cases, see `references/vc-update.md`.
