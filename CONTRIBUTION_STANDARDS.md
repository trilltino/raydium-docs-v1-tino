# Contribution standards for the Raydium documentation

**Applies to:** this repository (`docs/en`, `docs/i18n`, `docs.json`, `scripts/`) and any change proposed from it to [`raydium-io/raydium-docs-v1`](https://github.com/raydium-io/raydium-docs-v1).

**Status:** a working summary of the expectations Stendhal described in five catch-up meetings (8, 12, 15, 22 and 27 October 2026), plus practical rules that follow from them. It is **not an adopted or official Raydium policy**.

**How it fits with the other files.** [`CONTRIBUTING.md`](./CONTRIBUTING.md) covers the PR mechanics, style and translations. [`AGENTS.md`](./AGENTS.md) covers terminology, style and content boundaries. [`ARCHITECTURE.mdx`](./ARCHITECTURE.mdx) covers audience, chapter map and page templates. This file adds what a reviewer expects from the contribution itself. If this file disagrees with those three, they win.

Each rule is tagged. **Stated** means Stendhal said it, with the meeting date. **Recommended** means it is a practical extension and was not dictated.

## 1. The central standard: say what is wrong and what you want

A docs contribution should answer four questions:

1. **What exactly is wrong, missing or unclear?** Name the page, line, diagram or behaviour.
2. **Why does it matter?** Say who is affected: a reader, an integrator, an end user.
3. **What would you change?** Give a concrete fix or guidelines someone else can follow.
4. **What does success look like?** Describe the result a reviewer can check.

Stendhal's recurring question was: *"What do you want specifically? What do you want to get out of that?"* Feedback that stops at "this should be better" is not constructive, because the next person has to guess.

**Stated.** 15 October, about 36:05 to 38:59.

## 2. Pick the right format

There are two good ways to contribute a docs change. Stendhal named both on 15 October.

| You have | Submit | It must include |
|---|---|---|
| The finished change | A **pull request** with the actual commit | What problem it fixes, what changed, how you checked it |
| A finding but not the fix | An **issue** | Where the problem is, why it matters, and guidelines for fixing it |

**Stated.** "Either you provide the commit which is addressing it and should be taken as is, or you write an issue" that explains why something is unclear and how it should be revised. 15 October, about 36:05 to 37:03.

### Issues

An issue is not a bare complaint. Give the next contributor enough to act without asking you. This structure works, and [issue #23](https://github.com/raydium-io/raydium-docs-v1/issues/23) and [issue #24](https://github.com/raydium-io/raydium-docs-v1/issues/24) are worked examples of it.

```md
> [!IMPORTANT]
> **Verification scope** (date, what was checked, what was not)

## Problem
What the docs say, where (page and line, pinned to a commit), and what the
source or behaviour shows instead.

## Why it matters
Who is misled and what happens to them.

## Proposed change
The specific edits, or the guidelines someone needs to make them.

## Desired result
- [ ] Observable outcomes a reviewer can tick off.

## References and verification
Commit, sources, checks run, limitations.
```

For a diagram, "this is confusing, use this picture" is not enough. Say why it is confusing, which relationships or labels need to be clearer, what the layout should look like, and what must be preserved. A mockup illustrates a proposal. It does not replace the written spec.

**Stated.** 15 October, about 36:05 to 38:09.

### Pull requests

Describe the change so a maintainer can judge it without reconstructing your work.

```md
## Problem addressed
What was wrong or missing, with the page and line.

## Changes made
Files and what changed in each.

## Result
What a reader sees or can do now.

## Verification
What you ran or read, and the result. Say plainly what you did not check.

## Open questions
What is uncertain or needs a maintainer's decision.
```

Include before and after screenshots for layout changes, as `CONTRIBUTING.md` asks. The last two sections are **Recommended**.

## 3. Ideas are contributions too

- You do not need to write the fix. A well-specified issue is a valid contribution.
- Do not worry about opening too many pull requests. Stendhal said they will be reviewed. No turnaround time was promised, and `CONTRIBUTING.md` says maintainers aim to respond within a few days.
- Recurring user questions are a good source of docs issues. If a question keeps coming up and the answer is missing or unclear in the docs, that is a docs gap worth filing.

**Stated.** 12 October, about 03:09 to 06:45 (issues as well as PRs); 15 October, about 38:59 (volume of PRs); 27 October, about 21:36 to 22:35 (recurring user errors and unclear docs).

## 4. Evidence and accuracy

Reviewers cannot check a claim they cannot trace. These rules matter most when the docs are being corrected.

### Cite and pin

- Link the exact line in the exact commit, not a branch name. Branches move.
- For behaviour claims, cite the source, such as program code, SDK code at a pinned version, or a transaction. `CONTRIBUTING.md` asks for the same for correctness issues.
- Follow the version-pinning rule in `ARCHITECTURE.mdx`. A page that shows code names the SDK version, program ID, Solana cluster and last-verified date.

### Say what you verified and how

Use plain labels so a reader can tell a finding from an assumption.

| Label | Meaning |
|---|---|
| Verified | You read the source or ran the check, and the statement follows from it |
| Unverified | You did not establish it |
| Source unavailable | The code is closed, so only documentation exists |
| Not run | No test or transaction was executed |

State the scope at the top: what you checked (live docs, public source, a transaction) and what you did not (deployed binaries, other clusters). Reading source is not the same as running a transaction, and the text should not blur the two.

**Recommended.**

### Check the premise before escalating

Verify that the apparent defect is real before reporting it. A missing token may reflect how it was created or how the UI lists it, not a bug. For a docs gap, first check whether the behaviour you expected is actually current. For example, a farm that returns no rewards may belong to a program the docs call "wind-down" (Farm v3 and v5), not a program that is meant to emit rewards (Farm v6). Identify the program from its `programId` before deciding what the docs should say.

**Stated.** 15 October, about 26:41 to 33:33; 27 October, about 27:54 to 28:34 (a deprecated farm program as the likely explanation). The farm example is a **Recommended** illustration.

### Reporting a contradiction

When two pages disagree:

1. Quote both sides and link each to its line at one pinned commit.
2. Say which side the source supports, and which it does not. Do not call either "wrong" without a source.
3. Do not describe planned or upcoming behaviour as current. Keep existing behaviour and expected changes separate, and say which you mean.
4. Name the other pages that make the same claim. A contradiction between two pages is rarely only two pages.

**Recommended.**

### Do not claim more than you tested

Do not say a Raydium program supports something because a community example, a local test or a different program does. Evidence from a local runtime is not evidence about a deployed Raydium program. State which one you have.

**Recommended.**

## 5. Scope and size

- **One topic per pull request.** Keep corrections separate from new content, so each can be accepted or declined on its own.
- **Start small.** A first PR for a new area should be the smallest useful page, not the whole section. Plan the deeper pages and propose them as follow-ups.
- **Fit the architecture.** New pages must sit in the chapter map in `ARCHITECTURE.mdx`. For a large page or section, open an issue first, as `CONTRIBUTING.md` asks.
- **Link, do not restate.** Point to the official Solana documentation and to the canonical Raydium page instead of copying them. Program IDs, error codes, math definitions and API shapes each have one home, named in `AGENTS.md`.
- **Tie it to Raydium.** Explain how new material relates to Raydium programs and the existing chapters. A page that stands apart from the products is harder to place.
- **Keep fundamentals short.** The fundamentals chapter keeps code short and shows one worked example per page (see `docs/en/solana-fundamentals/index.mdx`).

**Stated.** 27 October, about 13:34 (a guide that does not restate everything); 15 October (keep material lean and linked). The size rules are **Recommended**.

## 6. Working in this repository

This fork's layout differs from upstream. Keep the two path conventions apart.

| | This fork | Upstream `raydium-docs-v1` |
|---|---|---|
| English pages | `docs/en/...` | repository root (`products/...`) |
| Translations | `docs/i18n/<locale>/...` | `<locale>/...` |
| Internal links | `/docs/en/...` | `/products/...` |

Map paths when you prepare a patch for upstream, and do not include fork-only files (`docs/en/resources/tino-changes.mdx`, `docs/i18n` redirects, `public/tino-changes`).

### Before you open a PR

1. **Preview locally** with `mint dev`, and look at desktop and mobile widths. Stendhal called a local copy the best way to work on docs.
2. **Keep the Mintlify CLI on the latest stable version.** Stendhal asked for this on 27 October because of problematic dependencies. Check your installed version with `mint --version` and update before a long editing session.
3. **Run `mint validate`.** It must pass.
4. **Run `py scripts/sync-locales.py`**, then `--check`, whenever you add, remove or rename an English page. This regenerates the locale navigation and fallback redirects.
5. **Run `mint broken-links`, and read the result.** If it flags nearly every page, the tool is failing, not the pages. Record that and rely on `mint validate` and a rendered check. Do not report a pass you did not get.
6. **Follow the writing rules** in `AGENTS.md` and `UNSLOP.md`: active voice, sentence-case headings, no em dashes, no curly quotes.

**Stated.** 27 October, about 16:02 to 16:24 (local preview, update Mintlify). The remaining steps are **Recommended** and follow `CONTRIBUTING.md`.

### Track what you changed

- Record every substantive change in [`docs/en/resources/tino-changes.mdx`](./docs/en/resources/tino-changes.mdx) with a dated entry. Do not remove earlier entries or closed-PR history.
- If you regenerate the upstream comparison with `scripts/generate-upstream-diff.py`, pin it to the recorded base commit. Otherwise upstream's own new commits show up as differences from this checkout.
- State PR and issue status accurately. Check it on GitHub before writing it. A page that says "open for review" about a closed PR misleads the next reader.

**Recommended.**

### Branches and commits

- Branch off `main` with a descriptive name such as `fix/clmm-fee-tier-table`, and delete the branch once it is merged.
- Use a commit message of the form `docs: <what changed>`.
- Do not push to `main`, open an upstream PR, or publish a preview without your own go-ahead.

**Recommended.**

## 7. Sharing work for review

- **Send context with the link.** One line saying what it is and why it matters lets a reviewer decide quickly. Collect several items into one message instead of sending them one by one.
- **Telegram is fine for non-urgent items.** Ping directly only when you are certain it is urgent.
- **Tag ahead of a call.** If you changed something you want reviewed in a meeting, tell the reviewer beforehand so they can read it first.
- **Share your docs commits.** Stendhal asked for links to the documentation commits so he could review them.
- **Share previews carefully.** If you host a preview of this fork, put it behind a login, label it an unofficial fork, and keep the password out of shared channels. The content derives from Raydium's MIT-licensed docs, which grant no trademark rights.

**Stated.** 27 October, about 19:18 to 20:30 (context, batching); 22 October, about 01:31 and 31:02 (tagging ahead, Telegram and urgency); 27 October, about 35:30 (commit links). The preview rule is **Recommended**.

## 8. What the docs should and should not do

- **Document current behaviour.** Describe what exists today. Put planned changes, such as a pending contract upgrade, in a clearly marked separate place, or leave them out.
- **Do not explain business reasons as fact.** Many product decisions, such as permissioning, are made for reasons outside the code. If you are unsure why something works the way it does, ask before writing a rationale into the docs.
- **Stay inside the documented boundaries.** `AGENTS.md` excludes trading strategy, price predictions, detailed tokenomics modelling and internal runbooks that contain secrets or admin procedures.
- **Do not publish private material.** Private source code, credentials and unreleased details do not belong in a public PR, an issue or a preview. If a page needs code from a private repository, write an independent example against public interfaces or get explicit approval first.
- **Report security problems privately.** Use the route in the Security disclosures section of `CONTRIBUTING.md`. Do not open a public issue for a vulnerability.
- **Do not imply endorsement.** Community tools and examples that the docs mention must be described as community work, not as Raydium products, and must not be presented as eligible for any Raydium programme or reward.

**Stated.** 22 October, about 24:03 to 25:24 (business reasons behind decisions); 15 October (publication scope). The rest follow `AGENTS.md` and `CONTRIBUTING.md`.

## 9. Pre-submission checklist

- [ ] I named the specific page, line or behaviour.
- [ ] I explained why it matters and who is affected.
- [ ] I gave a concrete fix or guidelines, or the actual commit.
- [ ] I described the result a reviewer can check.
- [ ] Every claim links to a pinned source, and I said what I did not verify.
- [ ] I checked the premise before calling something a bug.
- [ ] Existing behaviour and planned changes are kept apart.
- [ ] The change is one topic, and any follow-ups are listed separately.
- [ ] `mint validate` passes, locales are in sync, and I previewed the page locally.
- [ ] I recorded the change in Tino changes and checked any PR status I mention.
- [ ] Nothing private, secret or unreleased is in the diff.
- [ ] I sent the reviewer a one-line context with the link.

## Source record

| Date | Topics that shaped this file |
|---|---|
| 8 October 2026 | Keep material lean and link to authoritative documentation |
| 12 October 2026 | Welcome issues and ideas, not only pull requests |
| 15 October 2026 | Issue versus commit, "what do you want specifically", readability, review of the architecture-diagram issue |
| 22 October 2026 | Tag reviewers ahead of calls, Telegram and urgency, business reasons behind decisions, tie material to Raydium programs |
| 27 October 2026 | Introductory guide request, local preview and CLI updates, sharing commit links, context and batching, recurring user questions, farm program status |

The transcripts are automatic and imperfect. Check timestamps and wording against the recordings before treating any rule as official policy. Hook-specific standards are out of scope here and belong in the Transfer Hook repository.
