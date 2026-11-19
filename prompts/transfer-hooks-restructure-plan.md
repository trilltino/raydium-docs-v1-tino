# Plan: restructure the Transfer hooks page

Page: `docs/en/solana-fundamentals/transfer-hooks.mdx` (about 2,800 words)
Reference implementation: `trilltino/raydium-transfer-hook` (private, `main`)
Goal: a fundamentals page of about 1,600 words that teaches the Token-2022 hook contract, with the kit demoted from subject to evidence.

This file lives in `prompts/`, which `.mintignore` excludes from the site.

## Why restructure

The page does three jobs for three readers:

| Reader | Wants | Where it is today |
| --- | --- | --- |
| Developer new to hooks | The mental model and the account rules | Sections 2 and 3, about a third of the page |
| Hook author | Build and test a policy | Sections 4 to 6, the other two thirds |
| Raydium integrator or LP | Whether a hooked token works, and who can change the rule | Section 7, short, last |

Specific problems, from the review of the whole chapter:

1. No opening summary. The other fundamentals pages open with an `<Info>` box. This one repeats its title as an H2 and spends two paragraphs on navigation.
2. The kit is private, so most readers cannot follow its links or its clone command. The page also publishes an internal note ("Public access to the kit requires a separate maintainer visibility decision").
3. `hook-kit`, `hook-host`, `TransferContext`, a seven-check paragraph and a second diagram all come before the eight-line rule.
4. The CLI reference repeats the kit's own `hook-host/GUIDE.md`. That duplication is what drifted before.
5. The Trader Eligibility table and the template picker are kit detail, not fundamentals.
6. The scope note appears twice, in the intro and as a closing disclaimer.
7. Long sentences (roughly lines 104, 106, 110, 161, 223) break the one-idea-per-sentence rule in `AGENTS.md`.
8. PDA and TLV appear before they are defined.
9. Missing: who can change the rule, what a hook costs in a transaction, and a failure table.
10. The ending differs from the other pages (they end with Pointers and Sources).

## Decision needed first: the private repo

Everything below assumes the page must make sense to a reader with no kit access. Choose one before editing:

| Option | Effect | Cost |
| --- | --- | --- |
| A. Make the kit public | All existing links work. Keep the structure below. | Maintainer decision outside this repo. |
| B. Keep it private, make the page self-contained (recommended default) | Inline the `rule.rs` excerpt and a short scenario excerpt. Only the "Test it" section depends on the kit, and says so once. | Slightly longer excerpts. |
| C. Keep it private, move all kit material to a separate page | The fundamentals page has no kit links except one pointer. | Needs a new page, so nav and locale sync. |

Plan assumes B. If A is chosen, the "access required" wording is deleted and nothing else changes.

## Target outline

Word budgets add up to about 1,600.

| # | Section | Purpose | Words | Source |
| --- | --- | --- | --- | --- |
| 0 | `<Info>` summary plus one `<Note>` on scope and status | Three sentences: what a hook is, what it cannot do, that Raydium admission is separate. One merged note replaces both scope notes. | 120 | Current intro, lines 6 to 12 and 272 to 274 |
| 1 | What a hook can and cannot do | Motivation first. Limits: not run on mint, burn or `SetAuthority`; sees accounts and amounts, not people; self-transfers may skip it. | 150 | Lines 37 to 41, kit README "Build your own" |
| 2 | How a transfer reaches the hook | Keep the sequence diagram unchanged. Define CPI inline on first use. | 200 | Lines 14 to 41 |
| 3 | Accounts and the metadata list | Keep the six-row account table. Define PDA (link to PDAs and CPIs) and TLV on first use. | 220 | Lines 43 to 60 |
| 4 | A complete rule: the transfer limit | Show `rule.rs` and the 499/500/501 table directly after the accounts. | 200 | Lines 112 to 136 |
| 5 | What the shared validation protects | Short bullet list of what `ExecuteAccountInfos::validate` checks and what each template must still check. Drop the second diagram. | 120 | Lines 62 to 110, `hook-kit/src/execute.rs` |
| 6 | Test it | One command (`test-scenario check`), what it proves, one sentence on `--url devnet`, link to the kit guide. | 120 | Lines 138 to 161 |
| 7 | Who can change the rule | New. See below. | 150 | New |
| 8 | Hook tokens on Raydium | Admission versus execution, forwarding extras on every leg, transaction cost, failure table. Link the support matrix. | 220 | Lines 237 to 261, plus new |
| 9 | Before you ship | Keep the checklist, add anchors back to sections. | 100 | Lines 263 to 270 |
| 10 | Pointers and Sources | Same shape as the other seven pages. | 50 | Lines 276 to 281 |

## Section 7: who can change the rule (new)

Answer the question a trader or LP asks before depositing.

- The mint's transfer-hook authority can point the mint at a different hook program.
- The hook program's upgrade authority can change the program's behavior.
- A hook's own configuration authority (for the Starter, whoever holds the config) can change its parameters.
- Show how to read the first two: `test-scenario inspect --mint <mint>` reports who holds a mint's hook and mint authorities.

Verify before writing: the exact extension field names in the Token-2022 transfer-hook extension, and that `inspect` still reports these. Source: the Transfer Hook interface docs and `hook-host/GUIDE.md` ("Create a hooked mint and dry-run a transfer").

## Section 8: transaction cost and the failure table (new)

Transaction cost. A hook adds accounts to the transaction, compute to the instruction, and one more CPI level. Link `transactions-and-fees` (size, account and compute limits) and `pdas-and-cpis` (CPI depth). Carry over the warning that an aggregator, router, Raydium and a hook can reach the depth limit. Verify the depth count before stating a number: the call chain through Token-2022 adds a level.

Failure table. Reproduce each row in LiteSVM before publishing it.

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Hook never runs | Caller used `Transfer`, not `TransferChecked` | Use `TransferChecked` |
| Transaction fails on missing account | Client did not resolve the extras | Resolve from the metadata list |
| Swap on a hooked mint fails | The integrating program did not forward remaining accounts | Forward `remaining_accounts` on every transfer leg |
| Direct call to `Execute` fails | Transferring flags are not set | Expected; only Token-2022 can call it |
| A transfer is rejected with the policy error | The rule refused it | Read the error code, check limits and boundaries |

Rows 1 and 2 are known from the kit's rollback tests. Rows 3 to 5 need a captured error message each. Do not publish a row whose error text was not observed.

## What moves out of the page

| Current content | Destination |
| --- | --- |
| Install, subcommands, flags, wallets | Link `hook-host/GUIDE.md` (`#install-the-tool`, `#one-command-check`) |
| Custom-hook JSON scenario walkthrough (lines 171 to 225) | `hook-host/GUIDE.md#test-your-own-hook-from-a-json-scenario` |
| "Other execution environments" (existing mint, Devnet, pool fork) | `hook-host/GUIDE.md` sections on cluster, `new-mint` and `amm` |
| Trader Eligibility classification table | Kit template README, or the optional Phase 2 page |
| Template picker (Multi-Policy, Credential Gate, Fair Launch, Fee Split) | Kit README "Explore the templates" |
| Typed `starter.rs` and rollback detail | `hook-host/GUIDE.md#run-starter` |
| `#advanced-workflows` span anchor | Delete, after confirming nothing links to it |

Check inbound links to removed anchors before deleting: search `docs/` for `transfer-hooks#`.

## Phases

### Phase 1: restructure the existing page (no new pages)

1. Make the private-repo decision above.
2. Rewrite sections 0 to 1 and 10, merge the two scope notes, delete the maintainer-visibility sentence.
3. Reorder sections 2 to 6 as in the outline. Cut the second diagram.
4. Trim "Test it" to the single `check` command. Keep the "installed separately" sentence.
5. Write sections 7 and 8 from verified sources.
6. Split long sentences. Define CPI, PDA and TLV on first use.
7. Move kit-only content out as listed. Replace each with one link to the kit guide.

Because no page is added or removed, `sync-locales.py` is not required. Run `--check` anyway.

### Phase 2 (optional): a "Build a hook" page

A separate page for hook authors, for example `docs/en/integration-guides/build-a-transfer-hook.mdx`. It would hold the Starter walkthrough, the custom scenario flow, the Trader Eligibility pattern and the template picker. Only start this if the kit is public or you want the content on the site. It requires nav entry, locale sync (`python3 scripts/sync-locales.py`) and an `ARCHITECTURE.mdx` check.

## Writing rules

- Follow `AGENTS.md` and `UNSLOP.md`: second person, active voice, one idea per sentence, sentence-case headings.
- No commit SHAs, toolchain versions or "reviewed on" lines. Link to `main`. Keep only the worked-example numbers (500, 501, 4,500, 500).
- Terminology: Token-2022, CPMM, CLMM, LaunchLab, LP and trader as defined in `AGENTS.md`.
- Program IDs and mint admission rules live elsewhere: link `reference/program-addresses` and `reference/token-2022-support`. Do not restate them.
- Code excerpts stay under 30 lines, per the fundamentals index brief. The excerpt must either be complete or say what it omits.

## Verification

1. Run the kit commands the page shows on a clean checkout: `cargo test --locked -p transfer-hook-starter --lib` and `test-scenario check --program-dir templates/simple/transfer-hook-starter --scenario hook-host/examples/starter.json`. Last time all seven scenario cases passed.
2. Confirm every kit link resolves against `main` (the earlier pass checked 26).
3. Reproduce each failure-table row and capture the error text.
4. `mint validate`, `python3 scripts/sync-locales.py --check`.
5. Search for inbound links to removed anchors.
6. Preview with `mint dev` at desktop and mobile widths, light and dark. Confirm the diagram still renders.
7. Word count: target 1,500 to 1,700.
8. Add one entry to `docs/en/resources/tino-changes.mdx` with no SHAs or versions.

## Acceptance criteria

- A reader with no kit access can follow sections 0 to 5 and 7 to 10.
- The rule appears before the validation plumbing.
- The kit's CLI reference is not duplicated; only one command remains.
- The page ends with Pointers and Sources like the other fundamentals pages.
- Every claim in sections 7 and 8 has an observed result or a primary source.
- No SHAs, toolchain versions or internal notes remain.

## Risks

- The page will drift from the kit because it links to `main`. Mitigation: keep only the one `check` command and the Starter's rule; everything volatile lives in the kit guide.
- Section 7 asserts who holds which authority. Verify against the Token-2022 interface, not memory.
- Deleting the `#advanced-workflows` anchor may break external links. Check before removing.
- Deploying to the VPS preview is a separate step and happens only on request.
