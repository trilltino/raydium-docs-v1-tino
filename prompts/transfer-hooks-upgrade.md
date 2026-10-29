# Deep-research prompt for upgrading the Raydium Transfer Hooks documentation

## Research synthesis

Your current `transfer-hooks.mdx` is already a strong technical draft. It explains the Token-2022 execution sequence, the five fixed `Execute` accounts, `ExtraAccountMetaList`, direct-`Execute` protection, rollback semantics, an amount-limit example, Raydium integration implications, and a risk section. It also records the source commits and verification date.

The main opportunity is **not to add more raw information**. It is to give the information a clearer teaching sequence and connect the generic Token-2022 mechanism to a concrete implementation pattern.

That conclusion matches both the Raydium documentation architecture and Stendhal's feedback. Your local docs architecture calls for "one topic, one home", progressive depth, runnable code where it matters, version-pinned examples, and diagrams with editable sources. Your local `AGENTS.md` adds concise active prose, second-person writing, Raydium-specific terminology, and canonical cross-reference rules, while `UNSLOP.md` explicitly requires concrete language, short sentences, active voice, and removal of generic AI prose.

The hosted site follows the same philosophy. It explicitly serves developers, researchers, and end users from one source of truth, and says program chapters follow predictable structures with runnable code. The particularly useful model is the LaunchLab overview: it does not begin with account structs or instruction names. It begins with **"The problem LaunchLab solves"**, then gives a lifecycle, and only afterwards adds implementation detail. That is the missing "glue" you identified.

Stendhal's feedback points in the same direction. He repeatedly favored a limited amount of context, direct references when more detail is needed, and "cutting down on the fat." He also specifically said the material from your Transfer Hook presentation belonged in the developer-guide fundamentals as an introductory course on Transfer Hooks. Earlier, he asked that examples explain the intended behavior, expected result, why the approach makes sense, and its shortcomings rather than merely displaying code. He also wanted standardized interfaces so contributors can focus on their strategy rather than reworking infrastructure.

That leads to the right editorial target:

> **A developer should finish this page understanding the Transfer Hook mental model, why account resolution and validation are the difficult parts, how policy logic can be separated from protocol plumbing, and how to test that policy. They should then have precise links for everything deeper.**

The `raydium-transfer-hook` repository is well suited as a **reference implementation**, rather than as the subject of the page. Its current Starter isolates the amount rule in `rule.rs`; `hook-kit` turns validated `Execute` accounts into a `TransferContext`; `hook-host` resolves hook accounts and runs compiled programs; and Trader Eligibility demonstrates how the same pattern grows into venue-aware policy composition.

## Editorial philosophy to encode in the prompt

The prompt below deliberately treats your slides as **source material to distill, not content to paste into the docs**.

The English presentation already contains the useful conceptual split: authenticate the `Execute` context, enforce the business invariant, then verify runtime behavior. That maps directly onto the code. `ExecuteAccountInfos::validate()` verifies account shape, mint-hook binding, token-account mint binding, the transferring flags, privileges, and the canonical metadata list before producing `TransferContext`. The Starter then reduces its actual policy to a small comparison against `RuleParams.limit`.

The documentation should therefore **teach this separation**, rather than provide a catalogue of every `hook-kit` module.

Likewise, `hook-host` should not get four documentation sections. One concise section can explain that `resolve_transfer()` builds a `TransferChecked` instruction and resolves the configured hook's additional accounts, while the LiteSVM examples execute the compiled hook and check exact failures and rollback. The Starter runtime example already covers the amount boundary, rejected transfers, multi-instruction rollback, direct-`Execute` attempts, metadata substitution, account privilege errors, and counterfeit account ownership.

Trader Eligibility is useful as the **one advanced pattern**. Its `Leg` enum classifies a transfer by the source and destination token-account addresses relative to registered venue vaults. `required()` then maps `Buy`, `Sell`, and `Transfer` to credential checks, with `OpenExit` permitting a sell into a registered venue without requiring a current source credential. This is exactly the kind of example Stendhal was asking for: simple enough to understand, but related to trading and LaunchLab rather than an unrelated application.

One other point is important for the research agent: **use the hosted Raydium docs as the quality and presentation benchmark, but not blindly as the factual source of truth.** Your local fork contains later corrections. For example, its current Token-2022 reference describes the newer admin per-mint registry model and records removal of older static bypasses, whereas the currently indexed hosted support page still describes the older bypass configuration. Current CPMM source should therefore outrank older prose when they disagree; its `is_supported_mint` and transfer helpers can be inspected directly. The same rule applies to CLMM.

This also solves your earlier preference about not filling the page with discussion of what is or is not live. **The Transfer Hooks page should teach Transfer Hooks.** The current Raydium support state belongs primarily in the dedicated Token-2022 support matrix because the repository's own "one topic, one home" rule says exactly that.

## Recommended target shape

I would instruct the research agent to converge on approximately this structure:

| Section | What it should accomplish | Presentation |
|---|---|---|
| **Why transfer hooks exist** | Give the reader the problem before the mechanism. Explain that a mint can require transfer-specific policy beyond ordinary token authorization. | Short prose + `<Info>` |
| **Mental model** | Separate what Token-2022 does, what the hook does, and what the caller/client must do. | Three-column table or restrained `CardGroup` |
| **How a transfer reaches the hook** | Explain `TransferChecked`, post-transfer state, `transferring`, `Execute`, success/error and atomic rollback. | One sequence diagram |
| **How extra accounts work** | Explain the five fixed accounts, metadata-list PDA, fixed keys/PDA resolution, and why callers must resolve extras. | Table + compact account-resolution diagram |
| **A safe implementation pattern** | Connect protocol validation → `TransferContext` → `rule.rs`, using `hook-kit` as the concrete reference implementation. | One short real Rust snippet |
| **Worked example: transfer limit** | Show the Starter's actual rule and one pass/one reject. Explain expected result and limitation. | Real `rule.rs` code + tiny result table |
| **Test the behavior** | Show how the same rule is executed under Token-2022 using `hook-host`/LiteSVM and how a rejection/rollback is asserted. | Short real Rust test snippet |
| **Advanced pattern: venue-aware eligibility** | Show that policies can grow beyond amount checks without bloating the introductory path. Explain `Leg` clearly. | `<Accordion>` or `<Expandable>` |
| **Raydium integration context** | Explain vault transfers, account forwarding/CPI implications, then link to the canonical support matrix for changing program-specific status. | Compact diagram + links |
| **Design checklist / Further reading** | Give developers the handful of invariants to check and direct them to deeper pages and source. | Checklist/cards, not another essay |

That mirrors the hosted docs' progressive-depth approach. The Solana fundamentals chapter is explicitly the minimum conceptual material developers and researchers need before moving into product-specific chapters, so this page should remain an **introductory technical course**, not become a second Token-2022 reference manual.

The generic protocol explanation should remain anchored in the official Transfer Hook interface. Solana documents `Execute`, the optional metadata-list initialization/update instructions, the `["extra-account-metas", mint]` PDA convention, the read-only nature of the hook's transfer accounts, and automatic client-side resolution through the metadata list.

## Copy-paste deep research prompt

```text
You are a senior Solana/Rust engineer, protocol researcher, and technical documentation editor working inside my local Raydium documentation checkout.

Your task is NOT to write a generic article about Transfer Hooks.

Your task is to research the current code and documentation deeply, then upgrade the existing local page:

docs/en/solana-fundamentals/transfer-hooks.mdx

to the same editorial and technical standard as the best pages in the Raydium documentation set, while using my `raydium-transfer-hook` repository as a concrete reference implementation where it genuinely helps the reader.

This is an end-to-end research, fact-checking, documentation-design, editing, and validation task.

============================================================
PRIMARY GOAL
============================================================

Turn `docs/en/solana-fundamentals/transfer-hooks.mdx` into a clear introductory technical course for Token-2022 Transfer Hooks in the Raydium Developer Guide.

The finished page should answer, in this order:

1. What problem does a Transfer Hook solve?
2. What exactly happens when Token-2022 executes a hooked transfer?
3. Which accounts does `Execute` receive?
4. Why does `ExtraAccountMetaList` exist and how are extra accounts resolved?
5. What must a safe hook validate before executing custom policy logic?
6. How can a developer separate protocol plumbing from their own `rule.rs` policy?
7. How can they test the resulting hook under actual Token-2022 execution rather than only unit-testing a pure function?
8. How can the same architecture scale from a trivial transfer-limit rule to a more realistic venue-aware policy?
9. What does a Raydium integrator need to understand about pool vault transfers and hook-account plumbing?
10. Where should the reader go for current Raydium Token-2022 support status, deeper CPI material, security risks, and full source examples?

The page must make sense without the slide deck or the transfer-hook repository open beside it.

At the same time, do not repeat material whose canonical home is another Raydium docs page.

============================================================
EDITORIAL INTENT
============================================================

Apply the philosophy behind the project discussions:

- Be lean.
- Give the reader only the context needed for the next concept.
- Prefer a direct source/reference link over repeating a large amount of secondary material.
- Start with the problem and mental model before implementation details.
- Use progressive depth so an experienced developer can skim the first half and a new or AI-assisted builder can continue into examples.
- Explain behavior, expected results, why a design exists, and meaningful shortcomings or boundaries.
- Standardize the conceptual interface so developers can focus on their own policy rather than rebuilding Token-2022 plumbing.
- Do not turn the page into a catalogue of every helper, module, template, or test.
- Do not make this page primarily about deployment status or "what is live / not live."
- Do not repeatedly tell the reader that something is unsupported, experimental, unofficial, or not deployed.
- Current product-specific Token-2022 admission/support status belongs in the canonical Token-2022 support matrix. Link there rather than duplicating it.
- If a compatibility fact is necessary to prevent a technically false explanation, state it neutrally and briefly, then point to the canonical reference.
- Do not use marketing language.
- Do not oversell my `raydium-transfer-hook` repository. Treat it as a concrete/reference implementation that demonstrates the patterns discussed on the page.

The page should feel like a natural Raydium Developer Guide page, not documentation for my separate repository.

============================================================
LOCAL REPOSITORY RULES COME FIRST
============================================================

Before editing anything, inspect the local working tree.

Run or equivalent:

git status --short
git rev-parse HEAD
git branch --show-current

Do NOT reset, checkout, discard, overwrite, or revert unrelated local changes.

Then read these local files in full:

ARCHITECTURE.mdx
AGENTS.md
UNSLOP.md
CONTRIBUTING.md
README.md
docs.json

and especially:

docs/en/solana-fundamentals/transfer-hooks.mdx
docs/en/solana-fundamentals/spl-token-and-token-2022.mdx
docs/en/solana-fundamentals/pdas-and-cpis.mdx
docs/en/solana-fundamentals/programs-and-anchor.mdx
docs/en/reference/token-2022-support.mdx
docs/en/reference/program-addresses.mdx
docs/en/reference/error-codes.mdx
docs/en/security/oracle-and-token-risks.mdx
docs/en/security/attack-vectors.mdx

Treat the LOCAL checkout as authoritative for repository layout and local editorial conventions.

This fork intentionally uses:

docs/en/
docs/i18n/

Do not "correct" it to the upstream Raydium repo's current root-level English layout.

Do not move the page unless the local architecture itself requires that.

============================================================
RESEARCH SOURCES
============================================================

Research all of these, not just the current MDX page.

A. My current docs fork

https://github.com/trilltino/raydium-docs-v1-tino

Target remote page:

https://github.com/trilltino/raydium-docs-v1-tino/blob/main/docs/en/solana-fundamentals/transfer-hooks.mdx

Use the local checkout over the remote copy when the working tree differs.

B. Current hosted Raydium documentation

https://docs.raydium.io/

Use the hosted site to study:

- information flow;
- page openings;
- section length;
- use of Info / Note / Warning;
- diagrams;
- tables;
- code samples;
- cross-linking;
- progressive disclosure;
- how "problem" sections introduce product concepts.

Pay particular attention to:

https://docs.raydium.io/products/launchlab/overview
https://docs.raydium.io/solana-fundamentals/spl-token-and-token-2022
https://docs.raydium.io/solana-fundamentals/pdas-and-cpis
https://docs.raydium.io/reference/token-2022-support

Do NOT assume hosted prose is newer than my local fork. Compare dates, commits, local references, and actual program source.

C. Current Raydium organization and source code

https://github.com/raydium-io

Inspect at minimum:

https://github.com/raydium-io/raydium-cp-swap
https://github.com/raydium-io/raydium-clmm
https://github.com/raydium-io/raydium-sdk-V2
https://github.com/raydium-io/raydium-sdk-V2-demo
https://github.com/raydium-io/raydium-idl
https://github.com/raydium-io/raydium-docs-v1

For CPMM and CLMM, inspect the CURRENT source rather than relying on prose descriptions.

Trace relevant transfer helpers, pool-vault movement, mint admission logic, remaining accounts, instruction account definitions, and any Token-2022-specific paths.

Important files include, but do not blindly assume paths have not changed:

raydium-cp-swap/programs/cp-swap/src/utils/token.rs
raydium-clmm/programs/amm/src/util/token.rs

Search the repositories for:

transfer_checked
remaining_accounts
is_supported_mint
SupportMintAssociated
TransferHook
swap_v2 / SwapV2
deposit / withdraw transfer helpers
vault transfers

Record the exact current commit SHA used for factual claims.

D. Official Solana / Token-2022 sources

Use primary sources.

At minimum research:

https://solana.com/docs/tokens/extensions/transfer-hook
https://www.solana-program.com/docs/transfer-hook-interface

Then inspect the CURRENT official source for:

- Token-2022 transfer processing;
- TransferHook extension;
- TransferHookAccount / `transferring`;
- Transfer Hook interface `Execute`;
- ExtraAccountMetaList;
- TLV account resolution;
- off-chain `add_extra_account_metas_for_execute`;
- on-chain `add_extra_accounts_for_execute_cpi`;
- handling of confidential transfers and the Execute amount;
- mint / burn behavior relative to hooks.

Do not rely on memory for these details.

E. My reference implementation

https://github.com/trilltino/raydium-transfer-hook/

Read the repository as a system, not just its README.

At minimum inspect:

README.md
AGENTS.md
CONTRIBUTING.md
hook-kit/src/lib.rs
hook-kit/src/execute.rs
hook-kit/src/mint.rs
hook-kit/src/token.rs
hook-kit/src/extra_account_metas.rs
hook-kit/src/cpi.rs
hook-host/src/transfer_accounts.rs
hook-host/src/test_case.rs
hook-host/src/litesvm.rs
hook-host/GUIDE.md

Starter:

programs/simple/transfer-hook-starter/src/instructions/execute.rs
programs/simple/transfer-hook-starter/src/rule.rs
programs/simple/transfer-hook-starter/src/client.rs
hook-host/examples/simple/starter.rs

Advanced example:

programs/launch-lab/trader-eligibility/src/rule.rs
programs/launch-lab/trader-eligibility/src/instructions/execute.rs
hook-host/examples/launch_lab/trader_eligibility.rs

Also inspect any files those depend on before describing them.

Do not describe an API from an old slide if the current source has renamed or removed it.

============================================================
SOURCE PRECEDENCE
============================================================

When sources disagree, use this hierarchy.

For Token-2022 protocol behavior:

1. Current official Token-2022 / Transfer Hook source.
2. Current official Solana Transfer Hook documentation.
3. Secondary explanations.

For Raydium program behavior:

1. Current Raydium program source and IDL where public.
2. Current local canonical Raydium reference page if it records a newer deployed change that is not obvious from an older hosted snapshot.
3. Current upstream Raydium docs repository.
4. Hosted documentation.
5. Old presentations, meeting notes, or assumptions.

For `raydium-transfer-hook` behavior:

1. Current repository source.
2. Current tests/examples.
3. Current README/GUIDE.
4. Slides and prior descriptions.

Use the presentations and conversations for editorial intent, not as factual authority.

If the hosted docs contradict current code, do not copy the stale statement merely because it looks polished.

============================================================
BUILD A FACT LEDGER BEFORE WRITING
============================================================

Before editing the MDX, build an internal research table with:

Claim
Primary source
File/function
Commit SHA
Verified date
Whether the current MDX states it correctly
Whether the claim belongs on this page or another canonical page

Verify at least these claims:

- what the `TransferHook` mint extension stores;
- when Token-2022 invokes `Execute`;
- whether balances are observed before or after movement;
- transaction rollback when the hook fails;
- fixed `Execute` account order;
- signer/writable privileges presented to the hook;
- what `owner_or_delegate` represents;
- the role of the source/destination `transferring` flag;
- why direct `Execute` must not be treated as a genuine transfer;
- whether plain `Transfer` is valid for a hook mint or `TransferChecked` is required;
- whether mint and burn invoke a transfer hook;
- canonical ExtraAccountMetaList PDA seeds;
- supported forms of ExtraAccountMeta entries and seeds;
- who resolves the additional accounts;
- off-chain account resolution;
- CPI account resolution;
- confidential-transfer amount behavior;
- `ImmutableOwner` implications for owner-keyed policies;
- upgradeability / hook-authority implications;
- current CPMM/CLMM transfer and mint-gating behavior;
- which Raydium page is the canonical home for current Token-2022 support status.

If a claim cannot be verified from a primary source, either remove it or label the uncertainty precisely.

============================================================
AUDIT THE REST OF THE LOCAL DOCS
============================================================

Search the local docs before changing the page.

For example:

rg -n -i \
  "transfer.?hook|TransferHook|ExtraAccountMeta|extra-account-metas|transferring|SwapV2" \
  docs/en

Identify:

- duplicate definitions;
- contradictions;
- older support statements;
- pages that should link to `transfer-hooks.mdx`;
- concepts already defined elsewhere that this page should link to rather than restate.

Do NOT turn this task into a rewrite of the whole documentation corpus.

If you find unrelated factual problems:

- record them in the research summary;
- make a separate minimal fix only if it is necessary for the Transfer Hooks page to be internally consistent;
- otherwise leave the unrelated page untouched and identify it as follow-up work.

============================================================
PAGE DESIGN
============================================================

Use progressive disclosure.

A strong target structure is:

# Transfer hooks

Opening description.

<Info>
A compact mental model explaining that a mint can configure a Transfer Hook program, Token-2022 remains responsible for the transfer, and the hook adds policy during transfer execution.
</Info>

## Why transfer hooks exist

Start with the problem, not the interface.

Explain in plain language that normal token authorization answers "may this owner/delegate move these tokens?" A Transfer Hook lets the mint add another question about the transfer itself, for example an amount constraint or account eligibility rule.

Do not dump a long list of hypothetical use cases.

Connect this directly to why a Raydium/Solana developer might need to understand them: any program moving the mint needs to construct the transfer with the hook's required accounts.

## Mental model

Explain the three responsibilities:

Token-2022:
- authorization;
- token movement;
- transfer extensions;
- hook invocation.

Hook program:
- validates its Execute context;
- applies policy;
- optionally reads/writes declared state or calls another program.

Caller/client:
- constructs the checked transfer;
- supplies/resolves the accounts needed by the hook.

Use either a compact table or a restrained three-card CardGroup.

Do not over-style it.

## How a transfer reaches the hook

Use one sequence/lifecycle diagram.

The diagram should show something close to:

caller
  -> Token-2022 TransferChecked
  -> validate transfer authority
  -> move token balances
  -> mark transfer in progress
  -> CPI Execute(amount)
      -> hook validates context
      -> hook applies policy
      -> Ok / Err
  -> clear transfer state
  -> success OR atomic rollback

Verify every ordering detail from current Token-2022 source.

Explain that the hook reads the token state presented during Execute and why the transferring flag matters.

Make clear that a direct call to Execute is not equivalent to a Token-2022 transfer.

## Accounts and ExtraAccountMetaList

Keep the fixed-account table.

Explain the five standard Execute accounts precisely.

Then explain the ExtraAccountMetaList as an account-resolution contract between the hook and callers.

Cover:

- canonical PDA;
- fixed pubkeys;
- PDA-derived accounts;
- seeds based on preceding accounts or data where supported;
- signer/writable metadata;
- off-chain resolution;
- CPI resolution.

Do not re-teach all PDA/CPI fundamentals.

Link to:

/docs/en/solana-fundamentals/pdas-and-cpis

Use a small diagram if it adds information:

mint
  -> TransferHook program
  -> ExtraAccountMetaList
  -> resolved policy/config/credential accounts
  -> complete TransferChecked instruction

## A safe implementation pattern

This is where the `raydium-transfer-hook` repository should first appear.

Introduce it as a concrete/reference implementation of the separation just described.

Do NOT start with a catalogue of `hook-kit` modules.

Show the architecture:

Token-2022 Execute accounts
        |
        v
hook-kit validation
        |
        v
TransferContext
        |
        v
rule.rs
        |
      Ok / Err

Then briefly explain that `ExecuteAccountInfos::validate()` centralizes the protocol-level checks before policy code receives a `TransferContext`.

Use a REAL, CURRENT snippet from:

hook-kit/src/execute.rs

and/or:

programs/simple/transfer-hook-starter/src/instructions/execute.rs

Keep the displayed excerpt short enough to read.

Prefer a snippet that shows the conceptual boundary, such as:

let transfer_context = accounts
    .execute_account_infos(...)
    .validate(...)?;

rule::enforce_transfer_limit(
    &accounts.transfer_hook_config.rule_params,
    &transfer_context,
)?;

Do not fabricate a simplified API that does not exist.

If lines are omitted, use an explicit comment such as:

// account setup omitted

Do not present edited pseudocode as verbatim repository code.

Link the snippet to the exact GitHub source file and pin the repository commit/date in the page's verification information.

Explain what validation buys the developer:

- policy code no longer parses raw untrusted AccountInfo values itself;
- common transfer invariants live in one implementation;
- policy functions become small enough for normal Rust unit tests.

Avoid claiming that a helper proves application-specific policy safety.

## Worked example: maximum transfer amount

Use the Starter as the main worked example.

Use the actual current implementation from:

programs/simple/transfer-hook-starter/src/rule.rs

Show:

pub fn enforce_transfer_limit(
    rule_params: &RuleParams,
    transfer_context: &TransferContext,
) -> Result<(), TransferHookStarterError> {
    if transfer_context.amount > rule_params.limit {
        return Err(
            TransferHookStarterError::TransferExceedsLimit
        );
    }
    Ok(())
}

Preserve source semantics exactly.

Then explain the example using the philosophy:

Goal:
Reject a transfer whose amount is above the configured maximum.

Mechanism:
The rule consumes an already validated `TransferContext`.

Expected behavior:
limit - 1 passes;
limit passes;
limit + 1 returns the policy error and the transaction fails atomically.

Boundary:
Amounts are raw token units, so explain decimals.
Also verify and explain the confidential-transfer amount issue if current Token-2022 behavior still passes `u64::MAX`.

Do not over-explain the trivial comparison.
The purpose of the example is to show where developer-owned policy begins.

## Test the behavior under Token-2022

Introduce `hook-host` here, not earlier.

Explain in one paragraph:

- pure unit tests test `rule.rs`;
- runtime tests need Token-2022 to invoke the compiled hook;
- `hook-host` provides account resolution and LiteSVM fixtures for this purpose.

Use the current API from:

hook-host/src/transfer_accounts.rs
hook-host/src/test_case.rs
hook-host/src/litesvm.rs
hook-host/examples/simple/starter.rs

Show ONE compact runtime example.

The code should demonstrate an expected rejection and, if concise, rollback verification.

A useful concept is:

TestCase {
    name: "...",
    instructions: ...,
    expect: ExpectedOutcome::Error { ... },
    monitored_accounts: ...,
}

Do not reproduce the entire test harness.

Explain what the test proves and what it does not need to prove.

Useful behaviors from the current Starter example may include:

- 500 accepted;
- 501 rejected;
- direct Execute rejected;
- rejected second instruction rolls back the accepted first instruction;
- malformed metadata/account privileges rejected.

Pick only enough to teach the testing model.

Link to the full example for the rest.

Also include a small reference, not a full section, to:

hook-host::transfer_accounts::resolve_transfer()

Explain that it constructs the checked transfer and resolves the hook's ExtraAccountMetaList so developers do not have to build every hook-aware account list by hand.

## Advanced pattern: venue-aware eligibility

This should NOT become a second large tutorial.

Use an <Accordion>, <Expandable>, or compact subsection titled something like:

"Advanced pattern: venue-aware eligibility"

Use the actual current Trader Eligibility code.

Explain `Leg` precisely.

`Leg` means the direction of ONE token transfer relative to the registered `VenueVault` token-account addresses.

It is not proof that an entire Raydium swap occurred.

Use this small truth table:

Leg::Buy
registered vault -> user
destination credential required

Leg::Sell + OpenExit
user -> registered vault
source credential not required by the credential rule

Leg::Sell + RequireCredential
user -> registered vault
source credential required

Leg::Transfer
ordinary/non-venue transfer
source and destination credentials required

Verify the exact current semantics first.

Show the current `required()` match only if it remains compact.

Explain WHY this example matters:

It shows that the same validated TransferContext can feed a policy that:
- classifies transfers using registered token-account addresses;
- applies local limits;
- composes with an external recipient-allowlist through CPI;
- distinguishes an eligible buy from an exit policy.

Do not turn the Fundamentals page into full Trader Eligibility documentation.

Link to the full source and test example.

Do not call it an implemented Raydium/LaunchLab feature unless current Raydium source itself establishes that.

Use the correct product name "LaunchLab", never "launchpad" as the Raydium product name.

## Raydium integration context

Keep this section compact.

This page should explain the MECHANICS a Raydium developer needs to reason about:

- pools hold assets in vault token accounts;
- pool instructions move assets through token-program CPIs;
- a hook policy operates on the concrete source/destination token accounts presented to Execute;
- extra-account requirements affect the instruction/CPI account graph;
- compute and account count are therefore relevant integration concerns.

Use current CPMM and CLMM source to make every statement precise.

Do not use this section as the canonical support matrix.

For current admission/support/gating state, link to:

/docs/en/reference/token-2022-support

If the current program source has a constraint that materially changes the explanation, state it in one or two factual sentences and link out.

Do not add a long "not live", "unsupported", or deployment disclaimer section.

The audience already understands the surrounding project context.

## Design checklist

End the teaching portion with a small actionable checklist.

Possible items, after verification:

- authenticate that Execute was reached through a genuine Token-2022 transfer;
- validate mint and token-account bindings;
- validate the canonical metadata list;
- validate every extra account's identity, owner, and privileges;
- decide whether owner-keyed policy requires ImmutableOwner;
- handle self-transfers and boundary values deliberately;
- define upgrade/hook-authority assumptions;
- unit-test pure policy;
- runtime-test the compiled hook and rollback behavior;
- account for extra accounts and compute.

Keep it short.

## Further reading

Use direct links to canonical homes.

Include, as appropriate:

- official Solana Transfer Hook extension;
- official Transfer Hook interface;
- SPL Token and Token-2022 fundamentals;
- PDAs and CPIs;
- Token-2022 support matrix;
- security/oracle-and-token-risks;
- the `raydium-transfer-hook` Starter;
- `hook-kit`;
- `hook-host` guide;
- Trader Eligibility source/example.

Do not create a huge bibliography.

============================================================
MINTLIFY / STYLING REQUIREMENTS
============================================================

Use the styling vocabulary that already exists in the Raydium docs.

Available components may include:

<Info>
<Note>
<Tip>
<Warning>
<CardGroup>
<Card>
<Tabs>
<Tab>
<Steps>
<Step>
<Accordion>
<AccordionGroup>
<Frame>
<CodeGroup>
<Expandable>

Confirm what the local repo actually supports before using one.

Use components because they improve comprehension, not decoration.

Good candidates:

- `<Info>` for the opening mental model.
- A compact table or `CardGroup` for "who does what."
- `<Warning>` only for a genuine technical trap such as confidential-transfer amount semantics, if verified.
- `<Note>` for raw token units or owner/delegate semantics.
- `<Accordion>` / `<Expandable>` for Trader Eligibility or other advanced material.
- `<CodeGroup>` only when there are genuinely parallel implementations worth comparing.

Do not wrap every paragraph in a component.

Do not create a wall of colored callouts.

============================================================
DIAGRAM REQUIREMENTS
============================================================

The final page should have at least one high-value diagram.

Preferred diagrams:

1. Transfer execution lifecycle.
2. Optional small architecture diagram mapping:
   Token-2022 -> hook-kit validation -> rule.rs
   plus hook-host on the off-chain testing side.

Do not add five diagrams where two will do.

Follow the local documentation convention.

If using committed architecture assets:

images/architecture/<descriptive-name>.svg
images/architecture/<descriptive-name>.mmd

or the equivalent local convention confirmed from the repo.

Commit the editable Mermaid/draw.io source beside the SVG.

For a sufficiently small diagram, inline Mermaid is acceptable if the local Mintlify setup renders it correctly.

Do not leave a diagram source that cannot be reproduced.

Diagrams must communicate program/account flow, not decorate the page.

============================================================
CODE REQUIREMENTS
============================================================

Every repository-derived code sample must come from CURRENT source.

Do not reconstruct code from the PowerPoint.

Do not use a function name merely because it existed in an older version.

For every sample:

- identify source repository;
- identify file;
- identify commit SHA;
- preserve the actual API;
- keep the excerpt small;
- verify it builds/tests in its own repository where practical;
- make clear when surrounding setup has been omitted.

For the `raydium-transfer-hook` examples, prioritize:

1. Starter `execute.rs`
2. Starter `rule.rs`
3. `hook-host` runtime test
4. `resolve_transfer()`
5. Trader Eligibility `required()` only as the advanced example

Do NOT put a full module catalogue into the page.

Do NOT paste the entire hostile-test matrix.

Do NOT turn the page into the README for `raydium-transfer-hook`.

============================================================
RAYDIUM DOCS STYLE
============================================================

Apply the local `AGENTS.md`, `ARCHITECTURE.mdx`, `CONTRIBUTING.md`, and `UNSLOP.md` literally.

In particular:

- active voice;
- second person where instructional;
- sentence-case headings;
- one idea per sentence;
- short paragraphs;
- concrete nouns and verbs;
- code formatting for code identifiers;
- no hype;
- no emoji;
- no generic AI phrases;
- no decorative conclusion;
- avoid em dashes if local UNSLOP forbids them;
- avoid repeated bold lead-ins;
- avoid unnecessary colons;
- avoid words such as "crucial", "delve", "pivotal", "showcase", "leverage", "robust", "seamless";
- do not write a sentence that could belong unchanged in any blockchain project's docs.

Use Raydium terminology exactly:

CPMM
CLMM
AMM v4
LaunchLab
liquidity provider / LP
trader

Distinguish carefully between:

mint
token account
token-account owner
owner/delegate
wallet
pool authority
pool vault
hook program
Token-2022 program

Never casually equate a wallet with a person.

Never casually equate `Leg::Buy` with proof that a complete Raydium swap occurred.

============================================================
ONE TOPIC, ONE HOME
============================================================

This is essential.

The Transfer Hooks page owns:

- Transfer Hook mental model;
- Execute lifecycle;
- extra-account resolution;
- safe hook implementation pattern;
- a small worked hook example;
- basic runtime-testing model.

It does NOT own:

- the complete Raydium Token-2022 product support matrix;
- all CPMM/CLMM account layouts;
- generic PDA/CPI education;
- exhaustive security analysis;
- every `raydium-transfer-hook` template;
- full deployment instructions;
- exhaustive code demos.

Link to those canonical homes instead.

Use this rule to CUT text, not to add cross-reference boilerplate.

============================================================
HANDLE CROSS-DOC CONTRADICTIONS
============================================================

Actively check for contradictions between:

- hosted Raydium pages;
- my local fork;
- current Raydium program source;
- `raydium-transfer-hook`;
- official Solana documentation.

Do not silently pick whichever statement is most convenient.

For every contradiction:

1. identify the claim;
2. identify the competing sources and dates/commits;
3. decide which source has precedence;
4. write the current fact;
5. decide whether the correction belongs in this page or another page.

Pay particular attention to Transfer Hook statements in the broad
"SPL Token and Token-2022" page versus the detailed support matrix and current CPMM/CLMM source.

The hosted site is the STYLE benchmark.
Current source is the BEHAVIOR benchmark.

============================================================
VERSION / VERIFICATION BANNER
============================================================

Retain the useful verification discipline already present in the current page.

Update it from actual research.

Include, compactly:

- date verified;
- Token-2022 source commit;
- Transfer Hook interface commit/version;
- Raydium CPMM commit used;
- Raydium CLMM commit used;
- `raydium-transfer-hook` commit used for examples;
- Rust/toolchain or package versions used to compile/test examples where applicable.

Do not claim a cluster test unless you actually executed one.

Do not claim a test passed merely because a source file contains a test.

Say exactly what you ran.

============================================================
VALIDATION
============================================================

After editing:

1. Render locally with the repository's documented Mintlify command.
2. Run the broken-link checker.
3. Check every internal link manually if the checker cannot resolve it.
4. Confirm MDX components render.
5. Confirm diagrams render.
6. Confirm code fences have correct languages.
7. Confirm no text overflows or malformed JSX exists.
8. Search for accidental placeholders:
   TODO
   FIXME
   XXX
   coming soon
9. Search the page for stale terminology.
10. Run the local locale/navigation sync check if required by the repository rules.

At minimum attempt the local equivalents of:

mint dev
mint broken-links
python3 scripts/sync-locales.py --check

Do not mutate locale/navigation files unless this edit actually requires it.

For code examples from `raydium-transfer-hook`, run the smallest relevant tests where practical.

For example, inspect the current repo instructions first, then run the appropriate locked package tests rather than inventing a command.

============================================================
DELIVERABLES
============================================================

Return all of the following.

A. Research findings

A concise table containing:

- important fact;
- source;
- commit/version;
- whether the old page was correct;
- action taken.

Focus on facts that changed the document.

B. Contradictions found

List only meaningful contradictions between current code and documentation.

State which source won and why.

C. Final rewritten MDX

Provide the complete final contents of:

docs/en/solana-fundamentals/transfer-hooks.mdx

It must be ready to write directly to disk.

D. Additional files

If you created diagrams, provide the exact paths and full Mermaid/source content.

If you changed another docs file, explain why that change was unavoidable and provide its diff.

E. Verification

Report the commands you actually ran and their results.

Do not invent passing checks.

F. Diff summary

Summarize:

- what was removed;
- what was retained;
- what was added;
- what was moved behind progressive disclosure;
- which repository references were added.

============================================================
FINAL QUALITY TEST
============================================================

Before returning the result, reread the page as each of these readers.

Reader A: experienced Solana/Rust developer

They should be able to skim the page quickly, understand the protocol flow, see the exact account-resolution problem, inspect real code, and follow source links without reading beginner explanations they do not need.

Reader B: developer new to Transfer Hooks

They should understand why the extension exists, what Token-2022 does, what the hook does, why the metadata list exists, and where their policy code belongs before encountering the advanced example.

Reader C: AI-assisted builder

The page should contain enough explicit structure and source references that an agent can identify the correct files, interfaces, invariants, and tests without guessing.

Reader D: Raydium engineer/reviewer

The page should use Raydium terminology correctly, avoid duplicating the support matrix, distinguish protocol facts from reference-implementation choices, and cite current program source where Raydium-specific claims are made.

Then apply the Stendhal test:

- Is every paragraph needed?
- Does the page explain the problem before the mechanism?
- Can context that belongs elsewhere be replaced by a direct link?
- Does each code example teach a specific design decision?
- Does the advanced example state its behavior and boundary?
- Have we cut documentation that exists merely because we know it?
- Can a reader stop halfway through and still have a useful mental model?

If the answer to any of those is no, edit again before returning the final MDX.
```

## Why this prompt should produce a better page

The prompt deliberately prevents three common failure modes.

First, it stops the research model from treating the current page as a blank slate. Your existing page has valuable source verification and several technically important explanations that should be preserved.

Second, it prevents the model from turning the page into a description of your library. The library's architecture is useful because it concretely demonstrates the separation between protocol validation and business rules: `ExecuteAccountInfos::validate()` produces a `TransferContext`, the Starter consumes that context in a tiny policy function, and the runtime tests exercise the resulting program under Token-2022. That should support the explanation rather than replace it.

Third, it gives the research model a source-precedence rule. This matters because your local documentation branch is now capable of being **newer than the currently indexed hosted docs**. Your local Token-2022 support reference records later CPMM/CLMM changes than the hosted page currently shown by the public docs site. The prompt therefore tells the agent to take the hosted site's presentation standard while verifying behavior against current source.

## Expected end result

The finished page should feel closer to the hosted LaunchLab overview than to a library README: **problem first, lifecycle second, implementation details after the reader has a mental model**.

A reader should encounter the core concept roughly like this:

```text
Why does this exist?
        ↓
What does Token-2022 do?
        ↓
How does Execute work?
        ↓
Where do extra accounts come from?
        ↓
What must my hook validate?
        ↓
             ┌──────────────────┐
Execute ───► │ shared validation │
             └────────┬─────────┘
                      ↓
               TransferContext
                      ↓
                   rule.rs
                 Ok / Reject
                      ↓
              runtime verification
```

Then the real Starter code gives the reader a small implementation they can understand in one glance. The advanced Trader Eligibility example demonstrates that the same architecture can express a more realistic policy without requiring a catalogue of five unrelated templates. The repository's actual `required()` function already provides a concise mapping between venue-relative `Leg` classification and credential requirements.

The Raydium-specific section should then explain only the integration mental model. The dedicated support matrix remains the canonical home for changing product-specific Token-2022 policy, consistent with the repository's "one topic, one home" rule. The broader PDAs/CPIs page already owns the generic explanation of remaining accounts and CPI composition, so the Transfer Hooks page should link there rather than teach that subject again.

That gives you the balance Stendhal was asking for: **enough context to teach the concept, real code to make it concrete, direct links for depth, and no documentation added simply because the information exists.**